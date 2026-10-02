#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""迁移仓库内仅大小写不同的同目录路径（Windows 上互相覆盖的文件）。

背景
----
上游同名文件常只差大小写（``IPTV.m3u`` / ``iptv.m3u``），落库路径由 URL 段原样
派生，两者在 Linux CI 上共存无事，在 Windows 上却映射到同一个文件：检出时后写者
覆盖前者，于是磁盘内容、git index 两条记录、账本里各自登记的 sha256 三方对不上，
``git status`` 还会永久显示该文件已修改，驱动 daily 每轮重写同一份大文件。

写入侧已由 ``fetch_merge.resolve_dep_paths`` / ``raw_store._settle_case_rel`` 消解
新冲突，本脚本负责清历史存量：

1. 用 :func:`pathutil.resolve_case_collisions` 算出每组的新名字（字节序首个保留原名，
   其余降级为 ``<base>~<md5(path)[:6]><ext>``）；
2. 两条内容都从 git index 的 blob 还原——磁盘上只有一份，另一份只在对象库里；
   覆盖磁盘前把原文件备份到 ``.qoder-tmp/case_migration/``；
3. 同步改写 ``deps/manifest.json`` 的 ``local`` 与各 raw store 账本的 ``path``
   （顺带把历史遗留的反斜杠路径归一为正斜杠）；
4. 幂等：无冲突时不做任何改动。

改名后 git 会看到「旧名删除 + 新名未追踪」，由调用方 ``git add -A`` 收口。

用法
----
    python scripts/fix_case_collisions.py            # dry-run，只打印计划
    python scripts/fix_case_collisions.py --apply     # 实际改名与改写账本
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

import pathutil  # noqa: E402

BACKUP_DIR = os.path.join(".qoder-tmp", "case_migration")
DEP_MANIFEST = os.path.join("deps", "manifest.json")
# 各 raw store 的账本：entry 里的 path 是 store 内相对路径
RAW_MANIFESTS = [os.path.join("raw", "live", "manifest.json"),
                 os.path.join("raw", "vod", "manifest.json"),
                 os.path.join("raw-vod", "manifest.json")]


def tracked_paths() -> list:
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def index_blob(path: str) -> str:
    """该路径在 index 里的 blob hash（找不到返回空串）。"""
    out = subprocess.run(["git", "ls-files", "-s", "--", path], capture_output=True)
    line = out.stdout.decode("utf-8", "replace").strip()
    if not line:
        return ""
    return line.split()[1]


def blob_bytes(blob: str) -> bytes:
    return subprocess.run(["git", "cat-file", "blob", blob], capture_output=True,
                          check=True).stdout


def ledgers_with_renames(renames: dict, apply: bool) -> list:
    """把 旧路径->新路径 映射写进所有账本，返回 [(文件, 命中条数)]。

    按字节替换而不是 json.load/dump：``deps/manifest.json`` 按插入序排版、raw 账本
    按 key 排序，而且 autocrlf 机器上工作树是 CRLF——整份重写会把四行改名放大成
    上万行 diff，review 无从下手。文本模式读还会被 universal newlines 悄悄改行尾。
    """
    touched = []
    for mf in [DEP_MANIFEST] + RAW_MANIFESTS:
        if not os.path.isfile(mf):
            continue
        try:
            raw = open(mf, "rb").read()
        except OSError as e:
            print(f"  [skip] 读不到 {mf}: {e}")
            continue
        store_dir = os.path.dirname(mf).replace("\\", "/")
        hits = 0
        for old, new in renames.items():
            if not old.startswith(store_dir + "/") and not old.startswith("deps/"):
                continue
            olds = [old]
            if old.startswith(store_dir + "/"):
                # raw 账本的 path 是 store 内相对路径，历史遗留还有反斜杠写法
                rel = old[len(store_dir) + 1:]
                olds.append(rel)
                olds.append(rel.replace("/", "\\"))
            field = "local" if mf == DEP_MANIFEST else "path"
            # deps/manifest.json 的 local 是仓库相对路径（带 deps/ 前缀），必须整条替换；
            # raw 账本的 path 是 store 内相对路径，才需要剥掉 store 前缀。
            if mf != DEP_MANIFEST and new.startswith(store_dir + "/"):
                new_val = new[len(store_dir) + 1:]
            else:
                new_val = new
            for o in olds:
                # 模式串交给 json.dumps：账本里的反斜杠在 JSON 文本中是转义两道，
                # 直接拼字符串永远匹配不上，历史坏路径就漏改。
                pat = f'"{field}": {json.dumps(o, ensure_ascii=False)}'.encode("utf-8")
                n = raw.count(pat)
                if not n:
                    continue
                raw = raw.replace(
                    pat, f'"{field}": {json.dumps(new_val, ensure_ascii=False)}'.encode("utf-8"))
                hits += n
        if hits:
            touched.append((mf, hits))
            if apply:
                with open(mf, "wb") as f:
                    f.write(raw)
    return touched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="实际改名并改写账本（缺省只打印计划）")
    args = ap.parse_args()

    paths = tracked_paths()
    groups = pathutil.case_collisions(paths)
    if not groups:
        print("[fix_case_collisions] 无大小写冲突，无需迁移")
        return 0

    resolved = pathutil.resolve_case_collisions(
        [p for g in groups for p in g])
    renames = {old: new for old, new in resolved.items() if old != new}

    print(f"[fix_case_collisions] 冲突组 {len(groups)}，需改名 {len(renames)}"
          f"{'（APPLY）' if args.apply else '（dry-run）'}")
    for group in groups:
        for p in group:
            print(f"    {p} -> {renames.get(p, p)}  (blob {index_blob(p)[:8]})")

    if not args.apply:
        touched = ledgers_with_renames(renames, False)
        for mf, hits in touched:
            print(f"  账本 {mf}: 改写 {hits} 条（dry-run 未写盘）")
        print("[fix_case_collisions] dry-run 结束；确认无误后加 --apply 执行")
        return 0

    # 大小写不敏感的文件系统上，同组两条 index 记录指向**同一个物理文件**。
    # 必须先把败者改名挪走，再回来还原胜者；顺序反了会把胜者一起改名，
    # 然后被败者的内容覆盖，两条记录同时丢内容。
    backups = []
    for old, new in renames.items():
        blob = index_blob(old)
        if not blob:
            print(f"  [warn] index 里没有 {old}，跳过")
            continue
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if os.path.isfile(old):
            bak = os.path.join(BACKUP_DIR, old.replace("/", "__"))
            shutil.copy2(old, bak)   # 保住 daily 刚重写、尚未提交的字节
            backups.append(bak)
            os.makedirs(os.path.dirname(new), exist_ok=True)
            os.replace(old, new)
        with open(new, "wb") as f:
            f.write(blob_bytes(blob))
        print(f"  挪走并还原 {old} -> {new}")

    for group in groups:
        w = group[0]
        blob = index_blob(w)
        if not blob:
            continue
        data = blob_bytes(blob)
        cur = open(w, "rb").read() if os.path.isfile(w) else None
        if cur != data:
            os.makedirs(os.path.dirname(w), exist_ok=True)
            with open(w, "wb") as f:
                f.write(data)
            print(f"  还原胜者 {w}（blob {blob[:8]}）")

    touched = ledgers_with_renames(renames, True)
    for mf, hits in touched:
        print(f"  账本 {mf}: 改写 {hits} 条")

    print(f"[fix_case_collisions] 备份 {len(backups)} 个原文件到 {BACKUP_DIR}/")
    print("[fix_case_collisions] 现在 git 会看到旧名删除 + 新名未追踪，"
          "用 git add -A 收口后 windows_path_check 才会 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
