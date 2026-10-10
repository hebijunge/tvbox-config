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
import subprocess
import sys
from typing import List, Tuple

# Windows runner 的 stdout 管道默认英文 locale（cp1252, strict），print 中文即
# UnicodeEncodeError 崩掉本检查（2026-09-29 CI run#111 实证；旧版只写 stderr 才幸免）。
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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


def check_case_collisions(paths: List[str]) -> List[Tuple[str, str]]:
    """检查仅大小写不同的同名落库路径。

    Linux CI 能并存、Windows 只能留一个，于是本地内容与 git 记录、账本 sha256
    三方错位，且检出后 git status 永久显示该文件已修改，驱动 daily 反复重写。
    """
    return [("<->".join(g),
             "同目录内仅大小写不同，Windows 上互相覆盖（应由 dep_local_path 消解命名）")
            for g in pathutil.case_collisions(paths)]


def check_index_collisions() -> List[List[str]]:
    """扫描 git 索引里的同目录大小写冲突，作为账本之外的可见性补充。

    账本只覆盖 ``local`` 落库路径，而 ``raw/vod`` 这类 store 实体里的冲突（本轮实测
    存在 ``Box.json`` 与 ``box.json`` 并存、外加迁移出的 ``box~5c82e9.json``）不在
    扫描面上，只能靠人工 ``ls-tree`` 才发现。这里先只报数不判死：存量清完再收紧。
    """
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True)
    if out.returncode != 0:
        print("[windows_path_check] git ls-files 失败，跳过索引冲突扫描",
              file=sys.stderr)
        return []
    paths = [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]
    return pathutil.case_collisions(paths)


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
    collisions = check_case_collisions(paths)
    index_collisions = check_index_collisions()

    print(f"[windows_path_check] 共检查 {len(paths)} 条 local 路径，"
          f"问题 {len(problems)} 条，大小写冲突 {len(collisions)} 组")

    if problems:
        print("[windows_path_check] 前 20 条问题路径：")
        for i, (p, reason) in enumerate(problems[:20], 1):
            print(f"  {i}. {p}  -- {reason}")
        if len(problems) > 20:
            print(f"  ... 其余 {len(problems) - 20} 条省略")

    if collisions:
        print("[windows_path_check] 大小写冲突组：")
        for i, (p, reason) in enumerate(collisions[:20], 1):
            print(f"  {i}. {p}  -- {reason}")

    if index_collisions:
        print(f"[windows_path_check] 账本外的索引冲突 {len(index_collisions)} 组"
              f"（仅告警，不计入判定）：")
        for i, group in enumerate(index_collisions[:20], 1):
            print(f"  {i}. {'<->'.join(group)}")
        if len(index_collisions) > 20:
            print(f"  ... 其余 {len(index_collisions) - 20} 组省略")

    if problems or collisions:
        print("[windows_path_check] FAIL: 存在 Windows 不兼容路径")
        return 1

    print("[windows_path_check] OK: 所有路径在 Windows 上可创建")
    return 0


if __name__ == "__main__":
    sys.exit(main())
