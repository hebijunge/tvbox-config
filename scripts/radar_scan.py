#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
源雷达扫描（P2，QingNing / ngo5 / dongyubin 三个导航仓作为种子）：
  每周抓取种子 README → 提取候选链接（json/m3u/txt 或 tvbox/live/iptv 关键词）→ 快速验活
  → radar/candidates.json（人工确认后收编进 fetch_merge.py 的 UPSTREAMS）。
"""
import json
import os
import re
import sys
import time
import urllib.request
import concurrent.futures as cf

UA = {"User-Agent": "okhttp/3.15", "Accept": "*/*"}
OUT_FILE = os.environ.get("RADAR_FILE", "radar/candidates.json")
MAX_CANDIDATES = int(os.environ.get("RADAR_MAX", "60"))
TIMEOUT = 8
CONCURRENCY = 8

SEEDS = [
    {"name": "QingNing", "url": "https://raw.githubusercontent.com/Zhou-Li-Bin/Tvbox-QingNing/main/README.md"},
    {"name": "ngo5", "url": "https://raw.githubusercontent.com/ngo5/IPTV/main/README.md"},
    {"name": "dongyubin", "url": "https://raw.githubusercontent.com/dongyubin/IPTV/main/README.md"},
]

URL_RE = re.compile(r"https?://[^\s\"'<>\\)\]]+", re.I)
KEEP_RE = re.compile(r"\.(json|m3u|m3u8|txt)(\?|$)|tvbox|live|iptv|box", re.I)
DROP_RE = re.compile(r"github\.com/[^/]+/[^/]+/(tree|blob|issues|pull)|img\.shields\.io|badge|avatars|\.png|\.jpg|\.svg|\.ico|\.webp", re.I)


def http_get(url, timeout, max_bytes=0):
    req = urllib.request.Request(url, headers=UA)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(max_bytes) if max_bytes else r.read()
    return r.status, data, int((time.time() - t0) * 1000)


def main() -> int:
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8)))
    candidates = {}
    for seed in SEEDS:
        try:
            st, raw, _ = http_get(seed["url"], TIMEOUT, 500_000)
            if st != 200:
                print(f"  seed {seed['name']}: HTTP {st}", flush=True)
                continue
        except Exception as e:  # noqa: BLE001
            print(f"  seed {seed['name']}: {type(e).__name__}: {e}", flush=True)
            continue
        txt = raw.decode("utf-8", "replace")
        found = 0
        for m in URL_RE.finditer(txt):
            u = m.group(0).rstrip(".,;")
            if DROP_RE.search(u) or not KEEP_RE.search(u):
                continue
            if u in candidates:
                continue
            candidates[u] = {"url": u, "source": seed["name"]}
            found += 1
            if len(candidates) >= MAX_CANDIDATES * 3:
                break
        print(f"  seed {seed['name']}: 候选 +{found}", flush=True)

    items = list(candidates.values())[:MAX_CANDIDATES * 2]

    def probe(c):
        try:
            st, raw, ms = http_get(c["url"], TIMEOUT, 20480)
            c["status"] = st
            c["bytes"] = len(raw)
            c["latency_ms"] = ms
            c["ok"] = st == 200 and len(raw) > 100
        except Exception as e:  # noqa: BLE001
            c["status"] = 0
            c["error"] = f"{type(e).__name__}: {e}"[:100]
            c["ok"] = False
        return c

    with cf.ThreadPoolExecutor(CONCURRENCY) as ex:
        results = list(ex.map(probe, items))
    results.sort(key=lambda c: (not c.get("ok"), c.get("latency_ms", 99999)))
    doc = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S") + " +08:00",
        "note": "源雷达候选（自动扫描导航仓 README，仅候选；收编需人工确认后加入 fetch_merge.py UPSTREAMS）",
        "seeds": [s["url"] for s in SEEDS],
        "summary": {"scanned": len(results),
                    "reachable": sum(1 for c in results if c.get("ok"))},
        "candidates": results,
    }
    os.makedirs(os.path.dirname(OUT_FILE) or ".", exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"[radar] 完成：扫描 {len(results)}，可达 {doc['summary']['reachable']} -> {OUT_FILE}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
