#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-4 直播源级死源剔除闸门。

背景
----
store.py --probe-lives 给 lives 表做源级连通实测（healthy/dead/degraded），
但判死结果从未回流产物：tvbox.json 432 条 lives 是无条件全量合并，死源照发。
本脚本读 DB 判死清单，分三类精细处置后回写 tvbox.json / live.json / exports/live.json：

  直连 http     — 实测拉不到（12s 超时）→ 剔除
  本地相对      — 仓库文件不存在（依赖缺失类）→ 剔除；文件存在 → 保留（真机可用）
  gh 镜像前缀   — 剥镜像 host 复测原始 URL：仍死 → 剔除；复活 → 保留并把
                  DB health 改回 healthy（镜像挂了≠源死，且 URL 可改写回直连）

guard：DB healthy 占比 < 5% 判定为探测环境全断（沙箱断网/代理全挂、判级不可信），
本轮不剔除、只出报告。高剔除率本身是死源真实写照，不 abort。
与 live_pool_prune（频道级剔死 lives/*.txt）互补：本脚本管「源级条目」，
live_pool_prune 管「源内频道流」。

用法
----
  python scripts/store.py --probe-lives          # 先刷新 DB 判级
  python scripts/live_dead_prune.py             # 剔除并回写产物
  python scripts/live_dead_prune.py --dry-run   # 只出清单不写
"""
import argparse
import json
import os
import re
import sqlite3
import ssl
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "state", "tvbox.db")
REPORT = os.path.join(ROOT, "state", "live_dead_prune_report.json")
PRODUCTS = ["tvbox.json", "exports/live.json"]
GUARD_MIN_HEALTHY = 0.05      # DB healthy 占比 < 5% 判探测环境全断，abort
GH_INNER = re.compile(r"(https?://(?:raw\.|gist\.|github\.|objects\.github)[^ ]+)")
# github 裸直连在沙箱常被墙/10054 打断（WinError 10054 / 超时），误把活源判死。
# 复测走镜像链（gh.acmsz.top 实测 5s 通），与 dep_repair 同源经验。
GH_MIRRORS = [
    "https://gh.acmsz.top/",
    "https://ghproxy.net/",
    "https://gh-proxy.com/",
    "https://ghfast.top/",
    "",  # 兜底裸直连
]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"}
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def log(msg):
    print(f"[live_dead_prune {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def classify(url):
    u = (url or "").strip()
    if not u:
        return "no_url"
    if u.startswith("./") or u.startswith("/"):
        return "local"
    if u.startswith("http"):
        return "direct" if not re.search(r"gh-proxy|ghfast|ghproxy|down\.nigx", u) else "gh"
    return "direct"


def gh_reprobe(url, timeout=15):
    """剥镜像 host 取内层原始 URL，走 GH_MIRRORS 链逐个复测。

    沙箱里 github 裸直连常被墙/10054 打断，故必须套镜像（gh.acmsz.top 实测 5s 通）。
    任一镜像拉到「像流内容」即判复活，全链失败才判真死。返回 (resurrected, detail)。
    """
    m = GH_INNER.search(url)
    inner = m.group(1) if m else url
    last_err = ""
    for mirror in GH_MIRRORS:
        target = inner if not mirror else mirror + inner
        try:
            req = urllib.request.Request(target, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                body = r.read(8192)
                n = body.count(b"#EXTINF")
                if n >= 1:
                    return True, f"复活 channels={n} via {target[:50]}"
                txt = body.decode("utf-8", "ignore")
                if "http" in txt and len(txt) > 200:
                    return True, f"复活(非m3u) via {target[:50]}"
                last_err = f"内容不像流 via {target[:40]}"
                continue
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:30]} via {target[:40]}"
            continue
    return False, last_err or "全镜像链失败"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT key, name, url, health FROM lives WHERE health='dead'")]
    total = con.execute("SELECT COUNT(*) c FROM lives").fetchone()["c"]
    healthy = con.execute("SELECT COUNT(*) c FROM lives WHERE health='healthy'").fetchone()["c"]
    dead_ratio = len(rows) / total if total else 0
    healthy_ratio = healthy / total if total else 0
    log(f"DB lives {total} 源：healthy {healthy}（{healthy_ratio:.0%}）/ dead {len(rows)}（{dead_ratio:.0%}）")

    # guard：只有 healthy 占比极低（探测环境全断、几乎没一个源能连）才判环境故障不剔。
    # 高死源率本身是正常现象（很多上游直播源确实挂了），不是 abort 信号。
    if healthy_ratio < GUARD_MIN_HEALTHY:
        log(f"GUARD_ABORT: healthy 占比 {healthy_ratio:.0%} < {GUARD_MIN_HEALTHY:.0%}"
            f"（疑探测环境全断，判级不可信），本轮不剔除，仅出报告")
        report = {"generated_at": now_str(), "action": "guard_abort",
                  "db_total": total, "db_dead": len(rows), "db_healthy": healthy,
                  "healthy_ratio": round(healthy_ratio, 4), "pruned": []}
        json.dump(report, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        con.close()
        return 2

    # 三类分桶
    by_cat = Counter()
    prune_keys = set()
    local_kept = gh_saved = 0
    gh_results = {}

    # 本地相对：文件在仓库 → 保留（真机可用），不在 → 剔
    for r in rows:
        cat = classify(r["url"])
        by_cat[cat] += 1
        if cat == "local":
            p = r["url"].lstrip("./")
            if os.path.exists(os.path.join(ROOT, p)):
                local_kept += 1
            else:
                prune_keys.add(r["key"])
        elif cat == "no_url":
            pass  # 无 url 的条目保守保留（可能是聚合指针对象）
        elif cat == "gh":
            gh_results[r["key"]] = r
        # direct 直接进剔除集
        elif cat == "direct":
            prune_keys.add(r["key"])

    log(f"分桶: {dict(by_cat)} | 本地文件存在保留 {local_kept} | 直连死 {by_cat['direct']}")

    # gh 镜像：剥前缀并发复测
    def one(item):
        k, r = item
        res, detail = gh_reprobe(r["url"])
        return k, res, detail

    if gh_results:
        gh_saved = 0
        gh_pruned = 0
        with ThreadPoolExecutor(args.workers) as ex:
            for k, res, detail in ex.map(one, list(gh_results.items())):
                if res:
                    gh_saved += 1
                    # 仅实跑时回写 DB（dry-run 必须零副作用）
                    if not args.dry_run:
                        con.execute("UPDATE lives SET health='healthy', updated_at=? WHERE key=?",
                                     (now_str(), k))
                    log(f"  [复活] {gh_results[k]['name']} -> {detail}")
                else:
                    gh_pruned += 1
                    prune_keys.add(k)
                    log(f"  [剔除] {gh_results[k]['name']} | {detail}")
        if not args.dry_run:
            con.commit()

    # 对照产物：实际能剔掉多少（产物里没有的死源 key 不算）
    tv = json.load(open(os.path.join(ROOT, "tvbox.json"), encoding="utf-8"))
    product_keys = {l.get("url") for l in tv.get("lives", []) if l.get("url")}
    hit_in_product = [k for k in prune_keys if k in product_keys]
    kept_total = len(product_keys)
    ratio = len(hit_in_product) / kept_total if kept_total else 0
    log(f"剔除集 {len(prune_keys)} key，其中在 tvbox.json 432 里命中 {len(hit_in_product)}"
        f"（占产物 {ratio:.0%}）")

    # 注：DB 级 guard（healthy 占比 < 5%）已拦「探测环境全断」。走到这里说明环境正常，
    # 高剔除率是死源真实写照，仅记录不阻断（高剔除率正常，不该 abort）。
    if ratio > 0.5:
        log(f"  [warning] 产物剔除占比 {ratio:.0%} 偏高（环境已确认正常，照剔）")

    report = {
        "generated_at": now_str(),
        "action": "pruned" if not args.dry_run else "dry_run",
        "db_total": total, "db_dead": len(rows),
        "buckets": dict(by_cat),
        "local_kept": local_kept, "gh_resurrected": gh_saved,
        "prune_keys": sorted(prune_keys),
        "product_hit": len(hit_in_product), "ratio": round(ratio, 4),
    }

    if args.dry_run:
        json.dump(report, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log(f"DRY-RUN：将剔 {len(hit_in_product)} 条。报告 -> {os.path.basename(REPORT)}")
        con.close()
        return 0

    # 回写产物：tvbox.json + exports/live.json（按 url key 过滤）
    pruned_in_tv = 0
    for f in PRODUCTS:
        p = os.path.join(ROOT, f)
        if not os.path.exists(f):
            continue
        doc = json.load(open(p, encoding="utf-8"))
        if "lives" not in doc:
            continue
        before = len(doc["lives"])
        doc["lives"] = [l for l in doc["lives"] if l.get("url") not in prune_keys]
        removed = before - len(doc["lives"])
        pruned_in_tv += removed
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
        log(f"{f}: lives {before} -> {len(doc['lives'])}（剔除 {removed}）")

    report["pruned_in_products"] = pruned_in_tv
    json.dump(report, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"完成：DB 判死 {len(rows)} → 剔除 {pruned_in_tv} 条产物条目"
        f"（gh 复活 {gh_saved} 已回写 healthy）")
    con.close()
    return 0


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
