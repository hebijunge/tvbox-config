#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上游健康状态导出（P1）。

从 ``state/validated.json``（sources 段）与 ``state/upstreams_state.json``
合并每个上游的健康指标，输出 ``exports/upstream_health.json``，供外部
监控/面板消费。

输出字段
--------
    name           上游标识
    ok             最近一次探测是否 fully 成功（bool）
    sites_count    该上游贡献的本地依赖文件数（从 deps/json/manifest.json 按 origin 统计）
    fail_streak    连续失败天数（validated.sources.decay.streak_days）
    last_seen      最近一次成功时间（last_ok_at）
    disabled       是否被自动拉黑/disabled
    stage          decay 阶段：active / watch / out

用法
----
    python scripts/export_upstream_health.py [--out exports/upstream_health.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List


def load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def count_deps_by_origin(manifest_path: str = "deps/json/manifest.json") -> Dict[str, int]:
    """从 manifest.json 按 origin 统计 local 依赖文件数。"""
    data = load_json(manifest_path)
    counts: Dict[str, int] = {}
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        origin = entry.get("origin", "")
        if origin:
            counts[origin] = counts.get(origin, 0) + 1
    return counts


def build_upstream_entry(name: str, v: dict, deps_counts: Dict[str, int]) -> dict:
    """合并 validated.sources 单条记录为健康指标。"""
    decay = v.get("decay") or {}
    history = v.get("history") or {}
    # 最近一条 history 结果
    last_result = ""
    if history:
        try:
            last_result = history[sorted(history.keys())[-1]]
        except (IndexError, KeyError):
            last_result = ""
    ok = (last_result == "fully") or (decay.get("stage") == "active" and not v.get("decayed", False))
    return {
        "name": name,
        "ok": bool(ok),
        "sites_count": deps_counts.get(name, 0),
        "fail_streak": int(decay.get("streak_days", 0) or 0),
        "last_seen": v.get("last_ok_at", ""),
        "disabled": bool(v.get("disabled", False)),
        "stage": decay.get("stage"),
        "url": v.get("url", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="导出上游健康状态")
    parser.add_argument("--out", default="exports/upstream_health.json")
    args = parser.parse_args()

    validated = load_json("state/validated.json")
    us_state = load_json("state/upstreams_state.json")
    deps_counts = count_deps_by_origin()

    sources = validated.get("sources", {})
    if not isinstance(sources, dict):
        sources = {}

    entries: List[dict] = []
    seen = set()
    # 以 validated.sources 为主
    for name, v in sources.items():
        if not isinstance(v, dict):
            continue
        entries.append(build_upstream_entry(name, v, deps_counts))
        seen.add(name)

    # 补充 upstreams_state 中有但 validated 中没有的
    for name, v in us_state.items():
        if name in seen or not isinstance(v, dict):
            continue
        entries.append({
            "name": name,
            "ok": not v.get("disabled", False) and v.get("fail_count", 0) == 0,
            "sites_count": deps_counts.get(name, 0),
            "fail_streak": int(v.get("fail_count", 0) or 0),
            "last_seen": v.get("last_ok_at", ""),
            "disabled": bool(v.get("disabled", False)),
            "stage": None,
            "url": "",
        })

    healthy = sum(1 for e in entries if e["ok"] and not e["disabled"])
    report = {
        "total": len(entries),
        "healthy": healthy,
        "unhealthy": len(entries) - healthy,
        "upstreams": entries,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    tmp = args.out + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        os.replace(tmp, args.out)
    except OSError as e:
        print(f"[export_upstream_health] 写入 {args.out} 失败: {e}", file=sys.stderr)
        return 1

    print(f"[export_upstream_health] 导出 {len(entries)} 个上游："
          f"healthy={healthy} unhealthy={len(entries)-healthy} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
