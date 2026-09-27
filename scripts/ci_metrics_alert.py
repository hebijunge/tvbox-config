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


def main() -> int:
    parser = argparse.ArgumentParser(description="CI 关键指标下降告警")
    parser.add_argument("--tvbox", default="tvbox.json")
    parser.add_argument("--state", default="state/last_run.json")
    parser.add_argument("--deps-dir", default="deps")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args()

    cur = collect_current(args.tvbox, args.deps_dir)
    print(f"[ci_metrics_alert] 本轮指标: {cur}")

    prev = load_last(args.state)
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

    save_state(args.state, cur)
    return 0


if __name__ == "__main__":
    sys.exit(main())
