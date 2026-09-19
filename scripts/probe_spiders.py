#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""蜘蛛源 / JS 源连通性探针：给 type 3 的源补上「访问速度」这个维度。

问题
----
1222 个站点里只有 155 个（13%）是 HTTP 型采集接口，能用 probe_sites.py 直接实测。
剩下 68% 是 type 3：
    js 型（352）  ext 指向本地 drpy 规则文件，真实站点地址写在文件里的 host 字段
    csp 型（699） 真实地址在 spider jar 内部，外部拿不到；但其中约 25% 的 ext
                  直接写了站点 URL（如 csp_XBPQ 的「分类url」）
不补这一块，「按速度排序」就只能覆盖 13% 的源。

做法
----
  1. js 型：读本地下好的 deps js 文件，提取 host / url，得到真实站点地址
  2. csp 型：从 ext 里提取站点地址（过滤 127.0.0.1 / localhost 这类无效值）
  3. 对提取到的地址做一次连通性探测，记录 HTTP 状态与耗时

产物 probe/spider_probe.json 供 scripts/rank_sites.py 并入排序。

用法
----
    python scripts/probe_spiders.py
    python scripts/probe_spiders.py --concurrency 32 --timeout 8
"""

import argparse
import concurrent.futures as cf
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

UA = {"User-Agent": "okhttp/3.15", "Accept": "*/*"}
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

BAD_HOST = re.compile(r"127\.0\.0\.1|localhost|0\.0\.0\.0|example\.com|\.local\b", re.I)
URL_RE = re.compile(r"""https?://[^\s"'\\,;)\]}]+""")
HOST_FIELD_RE = re.compile(r"""\b(?:host|url|api|域名)\s*[:=]\s*['"](https?://[^'"]+)['"]""")


def extract_target(site, repo_dir):
    """返回 (真实站点地址, 来源说明)。取不到返回 (None, reason)。"""
    api = site.get("api")
    ext = site.get("ext")
    if isinstance(api, str) and api.startswith("./"):
        # js 型：ext 是本地规则文件，host 写在文件里
        if not isinstance(ext, str) or not ext.strip().startswith("./"):
            return None, "js 无本地规则文件"
        path = ext.strip().split(";")[0][2:]
        fp = os.path.join(repo_dir, path)
        if not os.path.isfile(fp):
            return None, "js 规则文件缺失"
        try:
            with open(fp, "rb") as f:
                text = f.read(300_000).decode("utf-8", "ignore")
        except OSError:
            return None, "js 读取失败"
        m = HOST_FIELD_RE.search(text)
        if m and not BAD_HOST.search(m.group(1)):
            return m.group(1), "js.host"
        for u in URL_RE.findall(text):
            if not BAD_HOST.search(u):
                return u, "js.url"
        return None, "js 内无可信地址"
    if isinstance(ext, str):
        for u in URL_RE.findall(ext):
            if not BAD_HOST.search(u):
                return u, "csp.ext-str"
    if isinstance(ext, dict):
        for v in ext.values():
            if isinstance(v, str):
                for u in URL_RE.findall(v):
                    if not BAD_HOST.search(u):
                        return u, "csp.ext-dict"
        line = " ".join(str(v) for v in ext.values())
        m = HOST_FIELD_RE.search(line)
        if m and not BAD_HOST.search(m.group(1)):
            return m.group(1), "csp.ext-dict"
    return None, "无 ext 地址"


def probe(target, timeout):
    """连通性探测：任何 HTTP 响应都算可达（403/404 也说明服务器在）。"""
    req = urllib.request.Request(target, headers=UA)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            r.read(1024)
            return {"ok": True, "http": r.status, "ms": int((time.time() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        return {"ok": True, "http": e.code, "ms": int((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001  探测边界：任何异常都算不可达
        return {"ok": False, "error": type(e).__name__, "ms": int((time.time() - t0) * 1000)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="tvbox.json")
    ap.add_argument("--out", default="probe/spider_probe.json")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--timeout", type=int, default=8)
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    with open(os.path.join(repo, args.input), encoding="utf-8") as f:
        doc = json.load(f)
    sites = doc.get("sites") or []

    targets, no_signal = [], []
    for s in sites:
        if s.get("api") and isinstance(s["api"], str) and s["api"].startswith("http"):
            continue  # HTTP 型由 probe_sites.py 负责
        target, src = extract_target(s, repo)
        if target:
            targets.append({"key": s.get("key"), "name": s.get("name"),
                            "kind": "js" if str(s.get("api", "")).startswith("./") else "csp",
                            "target": target[:200], "from": src})
        else:
            no_signal.append({"key": s.get("key"), "name": s.get("name"), "reason": src})

    print(f"[spider] 非 HTTP 型站点 {len(targets) + len(no_signal)} 个："
          f"可探 {len(targets)}，无地址 {len(no_signal)}", flush=True)
    by_from = {}
    for t in targets:
        by_from[t["from"]] = by_from.get(t["from"], 0) + 1
    print(f"[spider] 地址来源：{by_from}", flush=True)

    results = []
    if targets:
        t0 = time.time()
        with cf.ThreadPoolExecutor(args.concurrency) as ex:
            futs = {ex.submit(probe, t["target"], args.timeout): t for t in targets}
            done = 0
            for fut in cf.as_completed(futs):
                t = futs[fut]
                try:
                    r = fut.result()
                except Exception as e:  # noqa: BLE001
                    r = {"ok": False, "error": type(e).__name__}
                t.update(r)
                results.append(t)
                done += 1
                if done % 50 == 0:
                    print(f"  ... {done}/{len(targets)} ({time.time()-t0:.0f}s)", flush=True)

    for n in no_signal:
        n.update({"ok": False, "ms": None})
        results.append(n)

    reachable = [r for r in results if r.get("ok")]
    lats = sorted(r["ms"] for r in reachable if isinstance(r.get("ms"), int))
    doc_out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "type 3 源的真实站点地址来源于本地 drpy 规则文件 / ext 配置；无信号者无法测速",
        "summary": {
            "total": len(results), "probed": len(targets), "reachable": len(reachable),
            "no_signal": len(no_signal),
            "p50_ms": lats[len(lats) // 2] if lats else None,
        },
        "sites": results,
    }
    os.makedirs(os.path.dirname(os.path.join(repo, args.out)) or ".", exist_ok=True)
    with open(os.path.join(repo, args.out), "w", encoding="utf-8") as f:
        json.dump(doc_out, f, ensure_ascii=False, indent=1)

    print(f"[spider] 完成：可达 {len(reachable)}/{len(targets)}，中位延迟 {doc_out['summary']['p50_ms']}ms")
    for r in sorted(reachable, key=lambda x: x["ms"] or 99999)[:10]:
        print(f"   {r['ms']:6d}ms  HTTP {r.get('http')}  {str(r.get('name'))[:18]:18} {r['target'][:56]}")
    print(f"[spider] 产物 -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
