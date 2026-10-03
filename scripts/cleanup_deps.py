#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cleanup_deps.py — deps 未引用依赖保守清理（P1-8，高风险，默认 dry-run）。

安全模型（宁可不清，不可误删）
----------------------------
  1. 只扫 ``deps/localized/`` 与 ``deps/external/`` 两个无主目录；
     ``deps/<origin>/``（按上游分目录）一律不动。
  2. 未引用文件先记 ``state/dep_unused.json`` 带 ``unused_since``，**不当轮删**；
     下一轮再扫仍未引用、且超过保留期才删（按体积分档）。
  3. 体积分档（P2-3）：>1MB 留 7 天删；100KB~1MB 留 14 天删；<100KB 永久保留。
  4. 默认 dry-run（只报告）；``--execute`` 才真删——且是**移动**到
     ``deps/.trash/<日期>/``，不是 rm，回收站保留 30 天可回滚。
  5. 引用收集 = 所有公开产物（tvbox/vod/live/short/status/adult/adult_live +
     stores/*.json）里的 ``./deps/`` 路径，**并上** deps/manifest.json 账本 local
     字段；与 dep_audit / dep_gc 走同一份 dep_refs.collect_all_refs（见 scripts/dep_refs.py）。

为什么不能直接删
----------------
JS 动态 import / jar 反射加载静态扫描看不到，误删=源静默失效。
故前 2-3 周只标记不删，观察回收站无误报后再开 --execute。

用法
----
    python scripts/cleanup_deps.py                 # dry-run：只写 state/dep_unused.json + 报告
    python scripts/cleanup_deps.py --execute       # 真删（移入 deps/.trash/<日期>/）
    # 可选 --repo . --state state/dep_unused.json --trash-keep-days 30
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import shutil
import sys
import time
from datetime import datetime, timezone

# 复用 dep_audit.py 的引用正则与磁盘扫描思路（不 import 其 main，避免触发 IO）
DEP_RE = re.compile(r"\.?/?deps/[^\s\"'<>\\),;]+")

# 只清这两个无主目录；deps/<origin>/ 永不碰（P1-8 安全边界）
CLEANABLE_DIRS = ("deps/localized/", "deps/external/")

# P2-3 体积分档（字节）
BIG_MIN = 1 * 1024 * 1024      # >1MB
MID_MIN = 100 * 1024           # 100KB ~ 1MB
BIG_GRACE_DAYS = 7             # >1MB 未引用 7 天后删
MID_GRACE_DAYS = 14            # 100KB~1MB 未引用 14 天后删
SMALL_PERMANENT = True         # <100KB 永久保留


def collect_refs(repo):
    """产物 ∪ deps/manifest.json 账本登记；权威口径见 scripts/dep_refs.py。

    与 dep_audit / dep_gc 严格一致，避免"报告口径改了、真删还是旧口径"。
    """
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    import dep_refs
    return dep_refs.collect_all_refs(repo)


def scan_cleanable_files(repo):
    """扫描 CLEANABLE_DIRS 下所有文件，返回 [(abs_path, rel_posix, size), ...]。"""
    out = []
    for d in CLEANABLE_DIRS:
        root = os.path.join(repo, d)
        if not os.path.isdir(root):
            continue
        for base, _dirs, names in os.walk(root):
            for n in names:
                ap = os.path.join(base, n)
                try:
                    size = os.path.getsize(ap)
                except OSError:
                    continue
                rel = os.path.relpath(ap, repo).replace("\\", "/")
                out.append((ap, rel, size))
    return out


def grace_days(size):
    """P2-3 按体积返回保留天数；<100KB 返回 None（永久保留）。"""
    if size >= BIG_MIN:
        return BIG_GRACE_DAYS
    if size >= MID_MIN:
        return MID_GRACE_DAYS
    return None  # 永久保留


def load_unused(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_unused(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def main() -> int:
    ap = argparse.ArgumentParser(description="deps 未引用依赖保守清理（默认 dry-run）")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--state", default="state/dep_unused.json")
    ap.add_argument("--execute", action="store_true",
                    help="真删（移入 deps/.trash/<日期>/）；缺省只报告")
    ap.add_argument("--trash-keep-days", type=int, default=30,
                    help=".trash 回收站保留天数（默认 30，超期才真删）")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    refs = collect_refs(repo)
    files = scan_cleanable_files(repo)
    print(f"[cleanup_deps] 可清目录文件 {len(files)} 个，产物引用到 deps 路径 {len(refs)} 条")

    unused = load_unused(os.path.join(repo, args.state))
    today = datetime.now(timezone.utc).date().isoformat()
    new_unused, ready_to_trash, kept_small = [], [], 0

    for ap, rel, size in files:
        if rel in refs:
            continue  # 仍被引用，从待清清单移除
        g = grace_days(size)
        if g is None:
            kept_small += 1
            continue  # <100KB 永久保留
        rec = unused.get(rel)
        if rec is None:
            # 首次发现未引用：只记录，本轮不删
            unused[rel] = {"bytes": size, "unused_since": today, "grace_days": g}
            new_unused.append((rel, size, g))
            continue
        # 已有记录：算距 unused_since 天数
        try:
            since = datetime.fromisoformat(rec["unused_since"]).date()
            age = (datetime.now(timezone.utc).date() - since).days
        except (KeyError, ValueError):
            unused[rel] = {"bytes": size, "unused_since": today, "grace_days": g}
            continue
        if age >= g:
            ready_to_trash.append((ap, rel, size, age))
        else:
            new_unused.append((rel, size, g))  # 继续观察

    # 清理 .trash 里超期文件（真删）
    trash_pruned = 0
    trash_root = os.path.join(repo, "deps", ".trash")
    if args.execute and os.path.isdir(trash_root):
        cutoff = time.time() - args.trash_keep_days * 86400
        for base, _dirs, names in os.walk(trash_root):
            for n in names:
                fp = os.path.join(base, n)
                try:
                    if os.path.getmtime(fp) < cutoff:
                        os.remove(fp)
                        trash_pruned += 1
                except OSError:
                    pass

    moved = 0
    trash_dir = os.path.join(trash_root, today)
    for ap, rel, size, age in ready_to_trash:
        print(f"  - 待回收: {rel} ({size/1024:.0f}KB, 未引用 {age}d >= {grace_days(size)}d)")
        if not args.execute:
            moved += 1
            continue
        os.makedirs(trash_dir, exist_ok=True)
        dst = os.path.join(trash_dir, os.path.basename(rel))
        try:
            shutil.move(ap, dst)
            unused.pop(rel, None)
            moved += 1
        except OSError as e:
            print(f"    !! 移动失败: {e}", file=sys.stderr)

    save_unused(os.path.join(repo, args.state), unused)
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"[cleanup_deps][{mode}] 新标记未引用 {len(new_unused)}，"
          f"到期待回收 {len(ready_to_trash)}，<100KB 保留 {kept_small}，"
          f"回收站清理 {trash_pruned}")
    if not args.execute:
        print("[cleanup_deps] dry-run：未移动任何文件。确认无误后加 --execute 真删。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
