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


def _fp(v: dict):
    """站点身份指纹：api 优先（同库换 key/换域名后 api 往往不变），ext 前缀兜底。

    2026-09-28 P1-5 修复：早期以 key 为身份，同库镜像换 key（ikun→ikun-3）、
    上游把测速标记塞进 name（[590ms|5] iKun资源）会刷出一堆假 new/gone。
    指纹取内容源 api，换 key 不报警；无 api 的源（csp 爬虫）退到 ext 前 80 字符。
    """
    api = str(v.get("api") or "").strip()
    if api:
        return "api:" + api
    ext = v.get("ext")
    ext = ext if isinstance(ext, str) else (json.dumps(ext, ensure_ascii=False) if ext else "")
    return ("ext:" + str(ext)[:80]) if ext else ""


def load_current(db_path):
    """从 DB 读当前健康状态：点播(key) + 直播(url)。"""
    vod, live = {}, {}
    if not os.path.isfile(db_path):
        log(f"未找到 DB {db_path}，报告将为空（先跑 store.py 入库）")
        return vod, live
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for r in conn.execute("SELECT key, name, api, ext, health, latency_ms, level FROM interfaces"):
        vod[r["key"]] = {"name": r["name"], "api": r["api"], "ext": r["ext"],
                         "health": r["health"] or "unknown",
                         "latency_ms": r["latency_ms"], "level": r["level"]}
    for r in conn.execute("SELECT key, name, health FROM lives"):
        live[r["key"]] = {"name": r["name"], "health": r["health"] or "unknown"}
    conn.close()
    return vod, live


def diff(cur: dict, prev: dict, kind: str = "vod"):
    """与上次快照对比，返回 (new, gone, down, recovered)。

    身份口径（P1-5）：点播源以 _fp(api) 指纹为主身份、key 为兜底——
      * 新增：指纹与 key 都不在快照里（兼容旧快照无 api 字段：按 key 兜底不误报）；
      * 移除：快照条目既没按指纹也没按 key 出现在当前；
      * 掉线/恢复：指纹或 key 命中旧条目后比较健康状态，同库换 key 不再误报。
    直播条目 key 即 url（天然稳定），指纹与 key 口径一致，同一逻辑复用。
    """
    new, gone, down, recovered = [], [], [], []
    if kind == "vod":
        # 指纹从两侧内容现算（_fp：api 优先，ext 兜底），不依赖快照是否存过 fp 字段——
        # 旧快照（无 api）指纹为空，自动退回 key 兜底逻辑，平滑过渡一轮。
        prev_by_fp = {}
        for k, v in prev.items():
            f = _fp(v)
            if f and f not in prev_by_fp:
                prev_by_fp[f] = v
        cur_fps = {}
        for k, v in cur.items():
            f = _fp(v)
            if f and f not in cur_fps:
                cur_fps[f] = k
        for k, v in cur.items():
            f = _fp(v)
            pv = prev_by_fp.get(f) if f else None
            if pv is None and k in prev:
                pv = prev[k]
            if pv is None:
                new.append({"key": k, "name": v.get("name"), "health": v["health"]})
                continue
            old_h = (pv or {}).get("health", "unknown")
            new_h = v["health"]
            if old_h in GOOD and new_h == "dead":
                down.append({"key": k, "name": v.get("name"), "from": old_h, "to": new_h})
            elif old_h == "dead" and new_h in GOOD:
                recovered.append({"key": k, "name": v.get("name"), "from": old_h, "to": new_h})
        for k, v in prev.items():
            f = _fp(v)
            fp_kept = bool(f) and f in cur_fps
            key_kept = k in cur
            if not fp_kept and not key_kept:
                gone.append({"key": k, "name": (v or {}).get("name")})
        return new, gone, down, recovered

    # 直播：key 即 url，直接按 key 对比（原口径）
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


def write_summary_md(report: dict, out_path: str):
    """把 health_report 渲染成人读 Markdown（exports/SUMMARY.md）。

    只做格式化、不做二次计算：所有数字直接取自 report，
    长尾明细各截前 10 条（完整明细在 health_report.json）。"""
    v, l = report.get("vod", {}), report.get("live", {})
    sv, sl = v.get("summary", {}), l.get("summary", {})
    cv, cl = v.get("counts", {}), l.get("counts", {})
    lines = [
        "# 每日健康日报（人读版）",
        "",
        f"生成时间：{report.get('generated_at', '')}"
        + ("（首次运行，已建立基线，无对比数据）" if report.get("is_baseline") else ""),
        "",
        "## 总览",
        "",
        "| 类别 | 总量 | healthy | degraded | unknown | dead |",
        "|---|---|---|---|---|---|",
        f"| 点播 | {v.get('total', 0)} | {sv.get('healthy', 0)} | {sv.get('degraded', 0)} "
        f"| {sv.get('unknown', 0)} | {sv.get('dead', 0)} |",
        f"| 直播 | {l.get('total', 0)} | {sl.get('healthy', 0)} | {sl.get('degraded', 0)} "
        f"| {sl.get('unknown', 0)} | {sl.get('dead', 0)} |",
        "",
        f"较上轮变化：新增 {cv.get('new', 0)}｜掉线 {cv.get('down', 0)}｜恢复 {cv.get('recovered', 0)}｜移除 {cv.get('gone', 0)}（点播）；"
        f"新增 {cl.get('new', 0)}｜掉线 {cl.get('down', 0)}｜恢复 {cl.get('recovered', 0)}｜移除 {cl.get('gone', 0)}（直播）",
        "",
    ]
    if v.get("down"):
        lines += ["## 点播掉线（前 10）", ""]
        lines += [f"- {d.get('name') or d.get('key')}（{d.get('from')} → {d.get('to')}）"
                  for d in v["down"][:10]]
        lines.append("")
    if v.get("recovered"):
        lines += ["## 点播恢复（前 10）", ""]
        lines += [f"- {r.get('name') or r.get('key')}（{r.get('from')} → {r.get('to')}）"
                  for r in v["recovered"][:10]]
        lines.append("")
    if v.get("new"):
        lines += ["## 点播新增（前 10）", ""]
        lines += [f"- {n.get('name') or n.get('key')}（{n.get('health')}）" for n in v["new"][:10]]
        lines.append("")
    if l.get("down"):
        lines += ["## 直播掉线（前 10）", ""]
        lines += [f"- {d.get('name') or d.get('key')}（{d.get('from')} → {d.get('to')}）"
                  for d in l["down"][:10]]
        lines.append("")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


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

    n_new, n_gone, n_down, n_rec = diff(vod, prev_v, "vod")
    l_new, l_gone, l_down, l_rec = diff(live, prev_l, "live")

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

    # P2-2 人读日报（2026-09-22）：同一份报告输出轻量 Markdown（exports/SUMMARY.md），
    # 供导航页与 README 引用；数据源与 health_report.json 完全一致，不做二次加工。
    summary_path = os.path.join(repo, "exports", "SUMMARY.md")
    write_summary_md(report, summary_path)

    # 更新快照（下次对比的基线）。
    # P1-5：点播条目带 fp（api 指纹）作为下轮对比的主身份；旧快照无 fp 时 diff 按 key 兜底。
    os.makedirs(os.path.dirname(snap_path) or ".", exist_ok=True)
    snap_vod = {k: {**v, "fp": _fp(v)} for k, v in vod.items()}
    json.dump({"generated_at": report["generated_at"],
               "vod": snap_vod, "live": live},
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
