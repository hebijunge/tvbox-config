#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""健康趋势日报：用 DB 的检测结论算出「今天相比上次发生了什么」。

为什么需要它
------------
没有日报，每日运行只是「把流程重跑一遍」，跑完没人知道变好了还是变坏了。
有了它，每天的变化都能被看见：
  * 哪些源掉线了（healthy/degraded → dead）——往往是站点关停或防盗链升级
  * 哪些源恢复了（dead → healthy/degraded）——可能是临时抽风，别急着拉黑
  * 新增了哪些源——直接反映上游发现/收编有没有真的带来新东西

首次运行会建立基线（快照），此后每次与快照对比。

产出
----
  exports/health_report.json    当日报告（含变化明细）
  state/health_snapshot.json    下次对比的基线

用法
----
    python scripts/health_report.py
    python scripts/health_report.py --top 20        # 变化明细最多列 20 条
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime

GOOD = ("healthy", "degraded")


def log(msg):
    print(f"[health {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_current(db_path):
    """从 DB 读当前健康状态：点播(key) + 直播(url)。"""
    vod, live = {}, {}
    if not os.path.isfile(db_path):
        log(f"未找到 DB {db_path}，报告将为空（先跑 store.py 入库）")
        return vod, live
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for r in conn.execute("SELECT key, name, health, latency_ms, level FROM interfaces"):
        vod[r["key"]] = {"name": r["name"], "health": r["health"] or "unknown",
                         "latency_ms": r["latency_ms"], "level": r["level"]}
    for r in conn.execute("SELECT key, name, health FROM lives"):
        live[r["key"]] = {"name": r["name"], "health": r["health"] or "unknown"}
    conn.close()
    return vod, live


def diff(cur: dict, prev: dict):
    """与上次快照对比，返回变化明细。"""
    new, gone, down, recovered = [], [], [], []
    for k, v in cur.items():
        if k not in prev:
            new.append({"key": k, "name": v.get("name"), "health": v["health"]})
            continue
        old_h = (prev[k] or {}).get("health", "unknown")
        new_h = v["health"]
        if old_h in GOOD and new_h == "dead":
            down.append({"key": k, "name": v.get("name"), "from": old_h, "to": new_h})
        elif old_h == "dead" and new_h in GOOD:
            recovered.append({"key": k, "name": v.get("name"), "from": old_h, "to": new_h})
    for k, v in prev.items():
        if k not in cur:
            gone.append({"key": k, "name": (v or {}).get("name")})
    return new, gone, down, recovered


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="state/tvbox.db")
    ap.add_argument("--snapshot", default="state/health_snapshot.json")
    ap.add_argument("--out", default="exports/health_report.json")
    ap.add_argument("--top", type=int, default=15, help="变化明细最多列多少条")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    db = os.path.join(repo, args.db)
    snap_path = os.path.join(repo, args.snapshot)
    out_path = os.path.join(repo, args.out)

    vod, live = load_current(db)
    stat_v = Counter(v["health"] for v in vod.values())
    stat_l = Counter(v["health"] for v in live.values())
    log(f"当前：点播 {len(vod)} 个 {dict(stat_v)}｜直播 {len(live)} 条 {dict(stat_l)}")

    prev = {}
    is_baseline = False
    if os.path.isfile(snap_path):
        try:
            prev = json.load(open(snap_path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = {}
    else:
        is_baseline = True
        log("无历史快照，本次将建立基线（下次起才有对比）")

    prev_v = (prev or {}).get("vod", {}) if isinstance(prev, dict) else {}
    prev_l = (prev or {}).get("live", {}) if isinstance(prev, dict) else {}

    n_new, n_gone, n_down, n_rec = diff(vod, prev_v)
    l_new, l_gone, l_down, l_rec = diff(live, prev_l)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "is_baseline": is_baseline,
        "vod": {
            "total": len(vod), "summary": dict(stat_v),
            "new": n_new[:args.top], "gone": n_gone[:args.top],
            "down": n_down[:args.top], "recovered": n_rec[:args.top],
            "counts": {"new": len(n_new), "gone": len(n_gone),
                       "down": len(n_down), "recovered": len(n_rec)},
        },
        "live": {
            "total": len(live), "summary": dict(stat_l),
            "counts": {"new": len(l_new), "gone": len(l_gone),
                       "down": len(l_down), "recovered": len(l_rec)},
            "new": l_new[:args.top], "down": l_down[:args.top],
        },
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    json.dump(report, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 更新快照（下次对比的基线）
    os.makedirs(os.path.dirname(snap_path) or ".", exist_ok=True)
    json.dump({"generated_at": report["generated_at"],
               "vod": vod, "live": live},
              open(snap_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n==== 健康日报 ====")
    print(f"点播 {len(vod)} 个：healthy {stat_v.get('healthy',0)} / "
          f"degraded {stat_v.get('degraded',0)} / dead {stat_v.get('dead',0)} / "
          f"unknown {stat_v.get('unknown',0)}")
    print(f"直播 {len(live)} 条：healthy {stat_l.get('healthy',0)} / "
          f"unknown {stat_l.get('unknown',0)}")
    if is_baseline:
        print("（首次运行，已建立基线）")
    else:
        print(f"变化：新增 {len(n_new)}｜掉线 {len(n_down)}｜恢复 {len(n_rec)}｜移除 {len(n_gone)}")
        for d in n_down[:8]:
            print(f"   ↓ 掉线  {d['name']}  ({d['from']}→{d['to']})")
        for r in n_rec[:8]:
            print(f"   ↑ 恢复  {r['name']}  ({r['from']}→{r['to']})")
        for n in n_new[:5]:
            print(f"   + 新增  {n['name']}  ({n['health']})")
    print(f"产物 -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
