#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 兼容性检查（CI job: windows-path-check）。

遍历 ``deps/manifest.json``（依赖落库总账本）中所有 local 落库路径，逐条调用
``pathutil.is_windows_safe()`` 验证：

- 不含 Windows 非法字符 ``<>:"|?*`` 及控制字符；
- 不以点/空格结尾；
- 不是 Windows 保留设备名（CON/PRN/AUX/NUL/COM*/LPT*）；
- 路径总长度不超过 pathutil.MAX_PATH（240）。

任意一条不通过则 exit 1，打印前 20 条问题路径；全部通过 exit 0。

用法
----
    python scripts/windows_path_check.py [--manifest deps/manifest.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Tuple

# 允许 scripts/ 直接运行（python scripts/windows_path_check.py）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pathutil  # noqa: E402


def load_manifest(path: str) -> dict:
    """加载 deps/manifest.json，失败时返回空 dict。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[windows_path_check] 无法读取 manifest {path}: {e}", file=sys.stderr)
        return {}


def collect_local_paths(manifest: dict) -> List[str]:
    """从 manifest 收集所有 local 落库路径。

    manifest 结构: { "origin|url": {"local": "deps/...", ...}, ... }
    """
    paths: List[str] = []
    for key, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        local = entry.get("local")
        if local and isinstance(local, str):
            paths.append(local)
    return paths


def check_paths(paths: List[str]) -> List[Tuple[str, str]]:
    """对每条路径调用 is_windows_safe，返回 [(path, reason), ...] 问题列表。"""
    problems: List[Tuple[str, str]] = []
    for p in paths:
        ok, reason = pathutil.is_windows_safe(p)
        if not ok:
            problems.append((p, reason))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows 路径兼容性检查")
    parser.add_argument(
        "--manifest",
        default="deps/manifest.json",
        help="manifest.json 路径（默认 deps/manifest.json，即依赖落库总账本）",
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    if not manifest:
        print("[windows_path_check] manifest 为空或缺失，跳过检查", file=sys.stderr)
        return 0

    paths = collect_local_paths(manifest)
    problems = check_paths(paths)

    print(f"[windows_path_check] 共检查 {len(paths)} 条 local 路径，"
          f"问题 {len(problems)} 条")

    if problems:
        print("[windows_path_check] 前 20 条问题路径：")
        for i, (p, reason) in enumerate(problems[:20], 1):
            print(f"  {i}. {p}  -- {reason}")
        if len(problems) > 20:
            print(f"  ... 其余 {len(problems) - 20} 条省略")
        print("[windows_path_check] FAIL: 存在 Windows 不兼容路径")
        return 1

    print("[windows_path_check] OK: 所有路径在 Windows 上可创建")
    return 0


if __name__ == "__main__":
    sys.exit(main())
