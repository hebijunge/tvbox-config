#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按健康度导出可被 TVBox 直接引用的接口清单。

设计要点
--------
* **骨架取自 tvbox.json**：DB 的 interfaces 只存摘要（健康/延迟/来源），
  而 TVBox 导入需要完整站点字段（searchable/quickSearch/filterable/ext/jar…）。
  所以以产物为骨架、用 DB 的健康结论增强，避免导出出「字段不全的残配置」。
* **附加字段用 `_` 前缀**：TVBox 只认它认识的字段，陌生字段会被忽略，
  这样既满足「地址/类型/来源/最后检测时间/健康状态」可追溯，又不破坏兼容性。
* **幂等**：每次全量重写导出目录，重复运行结果一致。

产出 exports/
  all.json        全部（带健康标注）
  healthy.json    仅「实测能搜/能播」= healthy   ← 体感最好，推荐默认订阅
  usable.json     healthy + degraded（能连通即可）
  vod.json / live.json / short.json / pan.json / spider.json  按类型分组
  health_index.json  纯索引（key→健康/检测时间/延迟/来源），供外部系统消费

用法
----
    python scripts/export_healthy.py
    python scripts/export_healthy.py --min-health degraded     # 只导可用以上的
    python scripts/export_healthy.py --db state/tvbox.db --base tvbox.json
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime

GROUPS = {
    "vod": {"采集站", "直连点播"},
    "spider": {"蜘蛛源"},
    "localjs": {"本地JS"},
    "pan": {"网盘"},
    "short": {"短剧"},
}


def log(msg):
    print(f"[export {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def health_map(db_path):
    """key -> 健康结论（来自 DB）。"""
    if not os.path.isfile(db_path):
        log(f"未找到 DB {db_path}，健康维度将缺失（全部标注 unknown）")
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    out = {}
    for r in conn.execute(
            "SELECT key, health, last_check_at, latency_ms, level, source, fail_streak FROM interfaces"):
        out[r["key"]] = {
            "health": r["health"] or "unknown",
            "checked_at": r["last_check_at"],
            "latency_ms": r["latency_ms"],
            "level": r["level"],
            "source": r["source"],
            "fail_streak": r["fail_streak"] or 0,
        }
    conn.close()
    return out


def enrich(site, hm):
    """给站点附加健康字段（`_` 前缀，TVBox 会忽略）。"""
    h = hm.get(site.get("key"), {})
    s = dict(site)
    s["_health"] = h.get("health", "unknown")
    s["_checked_at"] = h.get("checked_at")
    s["_latency_ms"] = h.get("latency_ms")
    s["_level"] = h.get("level")
    s["_source"] = h.get("source")
    s["_type"] = site.get("group") or ("点播" if site.get("type") in (0, 1) else "其他")
    return s


def build_doc(base_doc, sites):
    """组装成完整配置：保留 spider/wallpaper/parses/lives，只替换 sites。"""
    doc = {k: v for k, v in base_doc.items() if k != "sites"}
    doc["sites"] = sites
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="state/tvbox.db")
    ap.add_argument("--base", default="tvbox.json")
    ap.add_argument("--out-dir", default="exports")
    ap.add_argument("--min-health", default="",
                    choices=["", "healthy", "degraded", "unknown"],
                    help="全局最低健康门槛（默认不设，各清单按自身定义）")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    base_path = os.path.join(repo, args.base)
    doc = json.load(open(base_path, encoding="utf-8"))
    sites = doc.get("sites") or []
    hm = health_map(os.path.join(repo, args.db))

    enriched = [enrich(s, hm) for s in sites if isinstance(s, dict)]
    stat = Counter(e["_health"] for e in enriched)
    log(f"基准 {args.base}: {len(enriched)} 站点｜健康分布 {dict(stat)}")

    outdir = os.path.join(repo, args.out_dir)
    os.makedirs(outdir, exist_ok=True)

    def dump(name, subset):
        p = os.path.join(outdir, name)
        json.dump(build_doc(doc, subset), open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        log(f"  {name:20} {len(subset):5d} 个")
        return len(subset)

    order = {"healthy": 3, "degraded": 2, "unknown": 1, "dead": 0}
    floor = order.get(args.min_health, 0) if args.min_health else 0
    if floor:
        enriched = [e for e in enriched if order.get(e["_health"], 0) >= floor]
        log(f"应用最低健康门槛 {args.min_health} → 剩 {len(enriched)} 个")

    healthy = [e for e in enriched if e["_health"] == "healthy"]
    usable = [e for e in enriched if e["_health"] in ("healthy", "degraded")]

    dump("all.json", enriched)
    dump("healthy.json", healthy)
    dump("usable.json", usable)

    for name, gset in GROUPS.items():
        dump(f"{name}.json", [e for e in usable if e.get("group") in gset])

    # 直播单独导：lives 不在 sites 里，单独成一份（带上游健康来源）
    lives = doc.get("lives") or []
    if lives:
        p = os.path.join(outdir, "live.json")
        json.dump({"lives": lives, "parses": doc.get("parses") or []},
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log(f"  {'live.json':20} {len(lives):5d} 条（直播源）")

    # 纯健康索引，供外部系统/看板消费
    idx = {e["key"]: {k: e[k] for k in ("_health", "_checked_at", "_latency_ms", "_level", "_source")}
           for e in enriched if e.get("key")}
    json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"),
               "total": len(idx), "summary": dict(stat), "items": idx},
              open(os.path.join(outdir, "health_index.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    log(f"  {'health_index.json':20} {len(idx):5d} 条")

    print(f"\n[export] 完成 -> {args.out_dir}/ "
          f"(healthy {len(healthy)} / usable {len(usable)} / all {len(enriched)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
