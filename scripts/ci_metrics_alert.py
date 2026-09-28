#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 关键指标告警（P1）。

对比本轮 tvbox.json 的 sites / lives 数量与 deps 文件数，与上一轮
（``state/last_run.json``）对比。任一指标下降超过 10% 时，用 ``gh`` CLI
创建标题含 ``[CI-ALERT]`` 的 GitHub issue，附前后对比数据。

首次运行（last_run.json 不存在）只记录基线、不告警。

用法
----
    python scripts/ci_metrics_alert.py [--tvbox tvbox.json] [--state state/last_run.json]
                                      [--threshold 0.10] [--repo $GITHUB_REPOSITORY]

退出码
------
    0  正常（含告警已创建）；1  执行异常（如 tvbox.json 缺失）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Dict, Optional

METRICS = ("sites", "lives", "deps_count")
DEFAULT_THRESHOLD = 0.10


def count_deps_files(deps_dir: str = "deps") -> int:
    """统计 deps/ 目录下文件总数（含子目录）。"""
    total = 0
    if not os.path.isdir(deps_dir):
        return 0
    for _root, _dirs, files in os.walk(deps_dir):
        total += len(files)
    return total


def collect_current(tvbox_path: str = "tvbox.json",
                   deps_dir: str = "deps") -> Dict[str, int]:
    """收集本轮指标：sites 数、lives 数、deps 文件数。"""
    metrics: Dict[str, int] = {"sites": 0, "lives": 0, "deps_count": 0}
    try:
        with open(tvbox_path, encoding="utf-8") as f:
            tvbox = json.load(f)
        if isinstance(tvbox, dict):
            sites = tvbox.get("sites", [])
            lives = tvbox.get("lives", [])
            metrics["sites"] = len(sites) if isinstance(sites, list) else 0
            metrics["lives"] = len(lives) if isinstance(lives, list) else 0
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ci_metrics_alert] 读取 {tvbox_path} 失败: {e}", file=sys.stderr)
    metrics["deps_count"] = count_deps_files(deps_dir)
    return metrics


def load_last(state_path: str) -> Optional[Dict[str, int]]:
    """读取上轮指标；不存在或损坏返回 None。"""
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and all(k in data for k in METRICS):
            return {k: int(data[k]) for k in METRICS}
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def save_state(state_path: str, metrics: Dict[str, int]) -> None:
    """原子写入本轮指标到 state/last_run.json。"""
    os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)
    os.replace(tmp, state_path)


def dropped(prev: int, cur: int, threshold: float) -> bool:
    """本轮是否比上轮下降超过 threshold。prev<=0 时不告警（避免除零）。"""
    if prev <= 0:
        return False
    return (prev - cur) / prev > threshold


def build_issue_body(prev: Dict[str, int], cur: Dict[str, int],
                     threshold: float) -> str:
    """构造 issue 正文（Markdown 表格）。"""
    lines = [
        "本轮 CI 关键指标较上轮下降超过 "
        f"{threshold*100:.0f}%，请排查上游拉取/合并是否异常。",
        "",
        "| 指标 | 上轮 | 本轮 | 变化 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for k in METRICS:
        p, c = prev[k], cur[k]
        delta = c - p
        pct = f"{(delta / p * 100):+.1f}%" if p else "n/a"
        mark = " ⚠️" if dropped(p, c, threshold) else ""
        lines.append(f"| {k} | {p} | {c} | {delta:+d} ({pct}){mark} |")
    return "\n".join(lines)


def create_issue(repo: str, body: str) -> None:
    """调用 gh CLI 创建 issue（标题含 [CI-ALERT]）。失败只打印警告，不抛异常。"""
    title = "[CI-ALERT] 关键指标下降超过阈值，请排查"
    cmd = [
        "gh", "issue", "create",
        "--repo", repo,
        "--title", title,
        "--body", body,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            print(f"[ci_metrics_alert] issue 已创建: {proc.stdout.strip()}")
        else:
            print(f"[ci_metrics_alert] gh issue create 失败 rc={proc.returncode}: "
                  f"{proc.stderr.strip()}", file=sys.stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"[ci_metrics_alert] 无法调用 gh CLI: {e}", file=sys.stderr)


def check_avail_report(report_path: str = "state/avail_report.json",
                       repo: str = "", avail_threshold: float = 90.0) -> None:
    """P1-5: 读 avail_monitor.py 抽样结果, 可用率 < 阈值时建 issue 告警。

    文件缺失(avail_monitor 未跑/被 WAF 拦)时静默跳过, 不误报。
    """
    try:
        with open(report_path, encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, json.JSONDecodeError):
        print("[ci_metrics_alert] 无 avail_report.json, 跳过可用率告警")
        return
    rate = rep.get("avail_rate")
    tested = rep.get("sample_tested", 0)
    if not tested:
        print("[ci_metrics_alert] 本轮抽样 0 个(网络被 WAF 拦?), 跳过可用率告警")
        return
    print(f"[ci_metrics_alert] 抽样可用率 {rate}% (阈值 {avail_threshold}%)")
    if rep.get("below_threshold") or (rate is not None and rate < avail_threshold):
        body = (
            f"[ALERT] 配置可用性告警: 抽样可用率 {rate}% < {avail_threshold}%\n\n"
            f"- 抽样数: {tested}, 可用 {rep.get('available')}, 不可用 {rep.get('unavailable')}\n"
            f"- 生成时间: {rep.get('generated_at')}\n\n"
            "可能原因: 上游大面积挂掉 / CI runner 出网被 WAF 误拦(连续 3 次触发紧急构建)。"
        )
        print(body)
        if repo:
            create_issue(repo, body)

def check_unknown_ratio(db_path: str = "state/tvbox.db",
                       repo: str = "",
                       unknown_threshold: float = 40.0,
                       last_alerted: bool = False) -> bool:
    """环② P1：unknown 占比超过阈值时告警——防止「没测过的源静默进配置」。

    读 DB interfaces 表统计各健康度占比（P1 判级修正后的权威结论）。DB 缺失/无记录
    时静默跳过，不误报。unknown 占比是绝对值（非环比），超阈值即建 issue 提醒补测。
    去重：last_alerted=True（上轮已建 issue）且本轮仍超阈值 → 只打印不重复建单。
    返回：本轮是否触发了告警（供调用方回写 last_alerted 标记）。
    """
    import sqlite3
    if not os.path.isfile(db_path):
        print(f"[ci_metrics_alert] 无 {db_path}, 跳过 unknown 占比告警")
        return False
    try:
        conn = sqlite3.connect(db_path)
        total, rows = conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0], \
            conn.execute(
                "SELECT health, COUNT(*) FROM interfaces GROUP BY health").fetchall()
        conn.close()
    except Exception as e:  # noqa: BLE001
        print(f"[ci_metrics_alert] DB 读取失败, 跳过 unknown 告警: {e}")
        return False
    if not total:
        print("[ci_metrics_alert] interfaces 空, 跳过 unknown 占比告警")
        return False
    dist = {h: n for h, n in rows}
    unknown = dist.get("unknown", 0)
    ratio = unknown / total * 100
    print(f"[ci_metrics_alert] 健康分布 {dist} | unknown {unknown}/{total}={ratio:.1f}% "
          f"(阈值 {unknown_threshold}%)")
    # 去重：上轮已告警且本轮仍超阈值 → 只打印不重复建 issue（持续超阈值降为每日提醒级）
    if ratio >= unknown_threshold:
        if last_alerted:
            print(f"[ci_metrics_alert] unknown 占比连续超阈值(上轮已建 issue), 本轮不重复建单, 仅打印")
            return True
        body = (
            f"[CI-ALERT] unknown 占比过高: {ratio:.1f}% ({unknown}/{total}) >= "
            f"{unknown_threshold}%\n\n"
            f"- 健康分布: {dist}\n"
            f"- 含义: 这些源未经实测就进了配置, 可用性未知。\n"
            f"- 处置: 跑真机 csp 补测刷新 probe/csp_probe.json 解除 STALE, "
            f"或临时降低订阅门槛至 exports/usable.json 之外。\n"
        )
        print(body)
        if repo:
            create_issue(repo, body)
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="CI 关键指标下降告警")
    parser.add_argument("--tvbox", default="tvbox.json")
    parser.add_argument("--state", default="state/last_run.json")
    parser.add_argument("--deps-dir", default="deps")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--db", default="state/tvbox.db",
                        help="健康度 DB（unknown 占比告警数据源）")
    parser.add_argument("--unknown-threshold", type=float, default=40.0,
                        help="unknown 占比告警阈值(百分比)")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args()

    cur = collect_current(args.tvbox, args.deps_dir)
    print(f"[ci_metrics_alert] 本轮指标: {cur}")

    prev = load_last(args.state)
    _last_unknown_alerted = False
    try:
        with open(args.state, encoding="utf-8") as _f:
            _last_unknown_alerted = bool(json.load(_f).get("unknown_alerted", False))
    except (OSError, json.JSONDecodeError):
        pass
    if prev is None:
        print("[ci_metrics_alert] 无历史基线，记录本轮为基线，不告警")
        save_state(args.state, cur)
        return 0

    print(f"[ci_metrics_alert] 上轮指标: {prev}")
    alerts = [k for k in METRICS if dropped(prev[k], cur[k], args.threshold)]

    if alerts:
        print(f"[ci_metrics_alert] 告警指标: {alerts}")
        body = build_issue_body(prev, cur, args.threshold)
        if args.repo:
            create_issue(args.repo, body)
        else:
            print("[ci_metrics_alert] 未设置 GITHUB_REPOSITORY，跳过创建 issue")
            print(body)
    else:
        print("[ci_metrics_alert] 指标无显著下降")

    check_avail_report(repo=args.repo)
    _unknown_alerted = check_unknown_ratio(args.db, repo=args.repo,
                                           unknown_threshold=args.unknown_threshold,
                                           last_alerted=_last_unknown_alerted)
    cur["unknown_alerted"] = _unknown_alerted
    save_state(args.state, cur)
    return 0


if __name__ == "__main__":
    sys.exit(main())
