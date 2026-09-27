#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""迁移 deps/json/manifest.json 中 Windows 不兼容的 local 落库路径。

背景
----
历史上 dep_local_path() 未正确剥离 ghproxy 类镜像前缀
（``https://<镜像>/https://raw.githubusercontent.com/...``），导致 local 路径里
出现 ``https:`` 带冒号目录名 / 双斜杠空段，在 Windows 上 WinError 123。
当前 fetch_merge.dep_local_path() 已修复镜像前缀剥离逻辑，本脚本对每条坏路径
用 (origin, url) 重算正确路径，并：

1. 若旧路径文件在磁盘上存在，移动到新路径（目标已存在则不覆盖）；
2. 把 manifest entry 的 local 字段更新为新路径；
3. 记录 旧路径 -> 新路径 映射，扫描产物 JSON 把旧路径引用替换为新路径。

幂等：重跑时所有 local 均已 windows-safe，不会做任何改动。

用法
----
    python scripts/migrate_bad_dep_paths.py            # 实际执行
    python scripts/migrate_bad_dep_paths.py --dry-run  # 只打印计划不写盘
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

# 允许 scripts/ 直接运行
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

import pathutil  # noqa: E402
import fetch_merge as fm  # noqa: E402

# manifest 主文件（windows_path_check 读取的那个）
MANIFEST_PATH = os.path.join("deps", "json", "manifest.json")
# deps/manifest.json 与上面是硬链接双胞胎；写主文件后再同步一份，双保险。
MANIFEST_TWIN = os.path.join("deps", "manifest.json")

# 需要替换旧路径引用的产物文件范围（交付给 TVBox 客户端的配置）：
#   - 仓库根目录下的 *.json
#   - stores/*.json
# 不处理：deps/（产物落库目录，manifest 单独管）、state/ probe/ snapshot/ sync/
#         （内部审计/历史快照/缓存，会被下次跑批重新生成，不是交付产物）。
PRODUCT_GLOBS = [
    "*.json",
    os.path.join("stores", "*.json"),
]
# 显式排除（即便命中 glob 也不碰）
EXCLUDE_FILES = {
    os.path.normpath(MANIFEST_PATH),
    os.path.normpath(MANIFEST_TWIN),
}


def load_manifest(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest: dict, path: str) -> None:
    """紧凑写回，与历史格式一致（无缩进、无尾换行、ensure_ascii=False）。"""
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(manifest, f, ensure_ascii=False, separators=(",", ":"))


def build_mapping(manifest: dict) -> dict:
    """返回 {old_local: new_local}，并就地把 entry['local'] 改成 new_local。

    只处理当前 local 在 Windows 上不安全的 entry。
    """
    mapping = {}
    for key, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        old = entry.get("local")
        if not isinstance(old, str) or not old:
            continue
        ok, _ = pathutil.is_windows_safe(old)
        if ok:
            continue
        origin = entry.get("origin")
        url = entry.get("url")
        try:
            new = fm.dep_local_path(origin, url)
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] 重算失败，跳过: key={key} err={e}", file=sys.stderr)
            continue
        if not isinstance(new, str) or not new:
            print(f"[migrate] 重算路径为空，跳过: key={key}", file=sys.stderr)
            continue
        # 重算后本身必须 windows-safe，否则说明 dep_local_path 仍有 bug
        nok, nwhy = pathutil.is_windows_safe(new)
        if not nok:
            print(f"[migrate] 重算结果仍不安全({nwhy})，跳过: {old} -> {new}",
                  file=sys.stderr)
            continue
        if new == old:
            continue
        entry["local"] = new
        mapping[old] = new
    return mapping


def move_files(mapping: dict, dry_run: bool) -> tuple:
    """把磁盘上存在的旧路径文件移动到新路径。返回 (moved, missing, skipped_target_exists)。"""
    moved = 0
    missing = 0
    skipped_target_exists = 0
    # 长路径优先无所谓；逐个处理
    for old, new in mapping.items():
        if not os.path.exists(old):
            missing += 1
            continue
        if os.path.isdir(old):
            # 旧路径是目录（理论上不会，因为坏路径段是文件名中间）；保守跳过
            print(f"[migrate] 旧路径是目录，未移动: {old}", file=sys.stderr)
            continue
        if os.path.exists(new):
            # 目标已存在：不覆盖。通常是同资源镜像去重，第一条已移动，后续共享。
            skipped_target_exists += 1
            continue
        if dry_run:
            moved += 1
            continue
        os.makedirs(os.path.dirname(new), exist_ok=True)
        shutil.move(old, new)
        moved += 1
    return moved, missing, skipped_target_exists


def collect_product_files() -> list:
    """收集需要替换旧路径引用的产物文件列表。"""
    import glob as _g
    files = []
    for pat in PRODUCT_GLOBS:
        files.extend(_g.glob(pat))
    out = []
    for fp in files:
        n = os.path.normpath(fp)
        if n in EXCLUDE_FILES:
            continue
        if not os.path.isfile(fp):
            continue
        out.append(fp)
    return out


def rewrite_product_refs(mapping: dict, dry_run: bool) -> tuple:
    """在产物 JSON 文本里把旧路径子串替换为新路径。返回 (改了几个文件, 替换次数)。"""
    if not mapping:
        return 0, 0
    # 长路径优先替换，避免短前缀先替换破坏长路径匹配
    items = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)
    changed_files = 0
    total_subs = 0
    for fp in collect_product_files():
        try:
            with open(fp, encoding="utf-8") as f:
                txt = f.read()
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] 读取失败 {fp}: {e}", file=sys.stderr)
            continue
        new_txt = txt
        file_subs = 0
        for old, new in items:
            if old in new_txt:
                cnt = new_txt.count(old)
                new_txt = new_txt.replace(old, new)
                file_subs += cnt
        if file_subs:
            changed_files += 1
            total_subs += file_subs
            print(f"[migrate] {fp}: 替换 {file_subs} 处旧路径引用")
            if not dry_run:
                with open(fp, "w", encoding="utf-8", newline="") as f:
                    f.write(new_txt)
    return changed_files, total_subs


def main() -> int:
    ap = argparse.ArgumentParser(description="迁移 manifest 中 Windows 不兼容的 dep local 路径")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写盘")
    args = ap.parse_args()

    manifest = load_manifest(MANIFEST_PATH)
    print(f"[migrate] 读取 manifest: {MANIFEST_PATH} ({len(manifest)} entries)")

    mapping = build_mapping(manifest)
    print(f"[migrate] 需要迁移的旧路径 -> 新路径 映射: {len(mapping)} 条")

    moved, missing, skipped = move_files(mapping, args.dry_run)
    print(f"[migrate] 文件移动: moved={moved} (磁盘上旧文件不存在={missing}, "
          f"目标已存在跳过={skipped})")

    # 写 manifest（主文件 + 硬链接双胞胎）
    if not args.dry_run and mapping:
        save_manifest(manifest, MANIFEST_PATH)
        # 硬链接双胞胎：直接复制内容（即使已硬链接也无害）
        try:
            with open(MANIFEST_PATH, encoding="utf-8") as f:
                twin_txt = f.read()
            with open(MANIFEST_TWIN, "w", encoding="utf-8", newline="") as f:
                f.write(twin_txt)
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] 写 {MANIFEST_TWIN} 失败: {e}", file=sys.stderr)

    # 产物文件引用替换
    changed_files, total_subs = rewrite_product_refs(mapping, args.dry_run)
    print(f"[migrate] 产物引用替换: {changed_files} 个文件, 共 {total_subs} 处")

    # 汇总
    print("[migrate] 完成。")
    print(f"  迁移路径条数(映射条目): {len(mapping)}")
    print(f"  实际移动文件数: {moved}")
    print(f"  产物文件: {changed_files} 个被更新, {total_subs} 处替换")
    return 0


if __name__ == "__main__":
    sys.exit(main())
