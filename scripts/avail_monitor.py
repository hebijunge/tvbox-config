#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""avail_monitor.py — 配置可用性抽样监控（P1-5）。

每日 CI 末尾抽 10% 点播站点测 L1 连通性，算可用率，写 state/avail_report.json。
ci_metrics_alert.py 读该文件：可用率 < 90% 时飞书告警。

设计要点
--------
  * 只测 type 0/1 的 http(s) 接口；type 3（本地 JS / drpy）HTTP 测不了，跳过。
  * L1 轻探：GET ``<api>?ac=list``，HTTP 200 即视为可用（不解析正文，3s 超时）。
  * 并发 64，超时 3 秒（PRD 给定）；CI runner 出网可能被 WAF 拦，故本脚本永不 exit 1，
    抽样本身失败只记 unknown，不阻断发布（daily.yml 已 continue-on-error）。

用法
----
    python scripts/avail_monitor.py --sample-ratio 0.10 --concurrency 64 --timeout 3
    # 可选 --tvbox tvbox.json --out state/avail_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)


def load_sites(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[avail_monitor] 读取 {path} 失败: {e}", file=sys.stderr)
        return []
    sites = doc.get("sites", []) if isinstance(doc, dict) else []
    return [s for s in sites if isinstance(s, dict)]


def pick_probe_target(site):
    """返回待探测 URL；非 http 接口（本地 JS / 相对路径）返回 None。"""
    api = site.get("api", "")
    if not isinstance(api, str):
        return None
    if not api.startswith(("http://", "https://")):
        return None
    sep = "&" if "?" in api else "?"
    return api.rstrip("/") + sep + "ac=list"


def probe_one(url, timeout):
    """L1 轻探：返回 (ok, status_or_err, ms)。"""
    req = urllib.request.Request(url, headers={"User-Agent": "okhttp/4.9"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.getcode()
            ms = int((time.time() - t0) * 1000)
            return (200 <= code < 400, code, ms)
    except urllib.error.HTTPError as e:
        ms = int((time.time() - t0) * 1000)
        # 403/429 视为未知（可能 WAF），不算可用也不算死
        return (False, f"HTTP{e.code}", ms)
    except Exception as e:  # noqa: BLE001 —— 超时/连接失败/SSL 都算不可用
        ms = int((time.time() - t0) * 1000)
        return (False, type(e).__name__, ms)


def main() -> int:
    ap = argparse.ArgumentParser(description="配置可用性抽样监控（P1-5）")
    ap.add_argument("--tvbox", default="tvbox.json")
    ap.add_argument("--out", default="state/avail_report.json")
    ap.add_argument("--sample-ratio", type=float, default=0.10,
                    help="抽样比例（默认 0.10 = 10%%）")
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--timeout", type=float, default=3.0, help="单源超时秒（默认 3）")
    ap.add_argument("--seed", type=int, default=20260927, help="抽样随机种子（可复现）")
    args = ap.parse_args()

    sites = load_sites(args.tvbox)
    http_sites = [s for s in sites if pick_probe_target(s)]
    random.seed(args.seed)
    k = max(1, int(len(http_sites) * args.sample_ratio))
    sample = random.sample(http_sites, min(k, len(http_sites))) if http_sites else []

    print(f"[avail_monitor] 总站点 {len(sites)}，可 HTTP 探测 {len(http_sites)}，"
          f"抽样 {len(sample)}（{args.sample_ratio:.0%}），并发 {args.concurrency}，超时 {args.timeout}s")

    results = []
    if sample:
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futs = {}
            for s in sample:
                url = pick_probe_target(s)
                futs[ex.submit(probe_one, url, args.timeout)] = (s.get("key", ""), s.get("name", ""), url)
            for fut in as_completed(futs):
                key, name, url = futs[fut]
                ok, status, ms = fut.result()
                results.append({"key": key, "name": name, "url": url,
                                "ok": ok, "status": status, "ms": ms})

    available = sum(1 for r in results if r["ok"])
    tested = len(results)
    rate = round(available / tested * 100, 1) if tested else 0.0
    failures = sorted([r for r in results if not r["ok"]], key=lambda r: r["key"])[:50]

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "sample_ratio": args.sample_ratio,
        "total_sites": len(sites),
        "http_probeable": len(http_sites),
        "sample_tested": tested,
        "available": available,
        "unavailable": tested - available,
        "avail_rate": rate,
        "threshold": 90.0,
        "below_threshold": bool(tested) and rate < 90.0,
        "failures": failures,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"[avail_monitor] 可用 {available}/{tested} = {rate}%"
          f"（阈值 90%，{'⚠️ 低于阈值' if report['below_threshold'] else '正常'}）")
    print(f"[avail_monitor] 产物 -> {args.out}")
    return 0  # 永不阻断发布；是否告警由 ci_metrics_alert 读 avail_rate 决定


if __name__ == "__main__":
    sys.exit(main())
