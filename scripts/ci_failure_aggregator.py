#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 失败聚合报告（P1）。

从各探针/状态文件收集本轮失败信息，按类型聚合计数，输出
``state/ci_failures.json``，并在 stdout 打印摘要（类型计数 + top 10 失败样例）。

收集来源
--------
- 探针失败：``probe/sites_probe.json`` / ``spider_probe.json`` / ``js_probe.json`` /
  ``csp_probe.json`` / ``drpy_probe.json`` 中 ``l1/l2/l3`` 任一级 ``ok=false`` 的站点；
- 上游拉取失败：``state/validated.json`` 的 ``sources`` 中 ``decayed=true`` 或
  ``decay.stage`` 为 watch/out 的上游；
- 依赖异常：``state/dep_audit.json`` 的 unreferenced / jar_suffix_mismatch 计数。

本脚本只读，不修改任何上游/产物文件。在 CI 各 continue-on-error 步骤后以
``|| true`` 调用，自身异常时 exit 0（不阻断发布）。

用法
----
    python scripts/ci_failure_aggregator.py [--out state/ci_failures.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Tuple

PROBE_FILES = [
    "probe/sites_probe.json",
    "probe/spider_probe.json",
    "probe/js_probe.json",
    "probe/csp_probe.json",
    "probe/drpy_probe.json",
]


def load_json(path: str) -> dict:
    """加载 JSON，失败返回空 dict。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def collect_probe_failures() -> Tuple[int, List[dict]]:
    """从各探针 JSON 收集失败站点，返回 (总数, 样例列表)。"""
    total = 0
    samples: List[dict] = []
    for path in PROBE_FILES:
        data = load_json(path)
        sites = data.get("sites", [])
        if not isinstance(sites, list):
            continue
        probe_name = os.path.basename(path).replace("_probe.json", "")
        for s in sites:
            if not isinstance(s, dict):
                continue
            # 任一级探测失败即计入
            failed_levels = []
            for lv in ("l1", "l2", "l3"):
                lvl = s.get(lv)
                if isinstance(lvl, dict) and lvl.get("ok") is False:
                    failed_levels.append(lv)
            if failed_levels:
                total += 1
                if len(samples) < 50:
                    samples.append({
                        "probe": probe_name,
                        "name": s.get("name") or s.get("key") or "?",
                        "api": s.get("api", ""),
                        "failed_levels": failed_levels,
                    })
    return total, samples


def collect_upstream_failures() -> Tuple[int, List[dict]]:
    """从 state/validated.json 收集 decayed/watch/out 上游。"""
    data = load_json("state/validated.json")
    sources = data.get("sources", {})
    if not isinstance(sources, dict):
        return 0, []
    total = 0
    samples: List[dict] = []
    for name, info in sources.items():
        if not isinstance(info, dict):
            continue
        decayed = info.get("decayed", False)
        stage = (info.get("decay") or {}).get("stage")
        disabled = info.get("disabled", False)
        if decayed or stage in ("watch", "out") or disabled:
            total += 1
            if len(samples) < 50:
                samples.append({
                    "name": name,
                    "url": info.get("url", ""),
                    "stage": stage,
                    "decayed": decayed,
                    "disabled": disabled,
                    "last_ok_at": info.get("last_ok_at", ""),
                })
    return total, samples


def collect_dep_issues() -> Dict[str, int]:
    """从 state/dep_audit.json 收集依赖异常计数。"""
    data = load_json("state/dep_audit.json")
    return {
        "unreferenced": int(data.get("unreferenced_count", 0) or 0),
        "jar_suffix_mismatch": int(data.get("jar_suffix_mismatch_count", 0) or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CI 失败聚合报告")
    parser.add_argument("--out", default="state/ci_failures.json")
    args = parser.parse_args()

    probe_total, probe_samples = collect_probe_failures()
    upstream_total, upstream_samples = collect_upstream_failures()
    dep_issues = collect_dep_issues()

    report = {
        "summary": {
            "probe_failures": probe_total,
            "upstream_failures": upstream_total,
            "dep_unreferenced": dep_issues["unreferenced"],
            "dep_jar_mismatch": dep_issues["jar_suffix_mismatch"],
        },
        "probe_samples": probe_samples[:10],
        "upstream_samples": upstream_samples[:10],
    }

    # 原子写入
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    tmp = args.out + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        os.replace(tmp, args.out)
    except OSError as e:
        print(f"[ci_failure_aggregator] 写入 {args.out} 失败: {e}", file=sys.stderr)
        return 0  # 不阻断 CI

    # 打印摘要
    s = report["summary"]
    print("[ci_failure_aggregator] 失败摘要:")
    print(f"  探针失败站点: {s['probe_failures']}")
    print(f"  上游异常(decayed/watch/out/disabled): {s['upstream_failures']}")
    print(f"  依赖未引用: {s['dep_unreferenced']}")
    print(f"  依赖 jar 后缀不匹配: {s['dep_jar_mismatch']}")

    if probe_samples:
        print("  Top 10 探针失败样例:")
        for i, x in enumerate(probe_samples[:10], 1):
            print(f"    {i}. [{x['probe']}] {x['name']} ({','.join(x['failed_levels'])})")
    if upstream_samples:
        print("  Top 10 上游异常样例:")
        for i, x in enumerate(upstream_samples[:10], 1):
            print(f"    {i}. {x['name']} stage={x['stage']} decayed={x['decayed']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
