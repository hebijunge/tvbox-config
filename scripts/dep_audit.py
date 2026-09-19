#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖审计：deps/ 的重复与未引用文件分析（**只报告，不删除**）。

为什么只报告不删
----------------
deps/ 已 81MB / 868 文件，且每天随上游增长。但直接删有风险：
产物里的引用是相对路径，一旦删掉仍被引用的文件，客户端就加载不到 jar/js。
所以这里只算清楚「能省多少、哪些安全」，清理动作留给人确认后再做。

分析两项
--------
  1. 重复文件：内容（md5）相同、但占了多个路径的文件 → 可去重
  2. 未引用文件：磁盘上有、但 tvbox.json 里没有任何引用的文件 → 可清理候选

产出 state/dep_audit.json，并在标准输出打印摘要。

用法
----
    python scripts/dep_audit.py
    python scripts/dep_audit.py --max-list 30
"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import sys
from collections import defaultdict
from datetime import datetime

DEP_RE = re.compile(r"\.?/?deps/[^\s\"'<>\\),;]+")


def md5_of(path, chunk=1 << 20):
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="tvbox.json")
    ap.add_argument("--deps", default="deps")
    ap.add_argument("--out", default="state/dep_audit.json")
    ap.add_argument("--max-list", type=int, default=25)
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    dep_dir = os.path.join(repo, args.deps)
    if not os.path.isdir(dep_dir):
        print(f"[audit] 无 {args.deps}/ 目录，跳过")
        return 0

    # 1) 扫描磁盘
    files = []
    for root, _, names in os.walk(dep_dir):
        for n in names:
            p = os.path.join(root, n)
            try:
                files.append((p, os.path.getsize(p)))
            except OSError:
                continue
    total_bytes = sum(s for _, s in files)
    print(f"[audit] deps/ 共 {len(files)} 个文件，{total_bytes/1024/1024:.1f} MB")

    # 2) 按 md5 找重复
    by_md5 = defaultdict(list)
    for p, s in files:
        m = md5_of(p)
        if m:
            by_md5[m].append((p, s))
    dup_groups = {m: v for m, v in by_md5.items() if len(v) > 1}
    dup_bytes = sum(sum(s for _, s in v) - v[0][1] for v in dup_groups.values())
    print(f"[audit] 内容重复：{len(dup_groups)} 组，去重可省 {dup_bytes/1024/1024:.1f} MB")

    # 3) 引用分析
    refs = set()
    base_path = os.path.join(repo, args.base)
    if os.path.isfile(base_path):
        txt = open(base_path, encoding="utf-8", errors="replace").read()
        for m in DEP_RE.finditer(txt):
            # 必须用 posixpath：os.path.normpath 在 Windows 会转出反斜杠，
            # 与磁盘上的正斜杠相对路径永远匹配不上（曾导致「100% 未引用」的假结果——
            # 照它清理会把全部依赖删光）。
            ref = posixpath.normpath(m.group(0).lstrip("./").replace("\\", "/"))
            refs.add(ref)
    print(f"[audit] 产物中引用到的 deps 路径：{len(refs)} 条")

    unreferenced = []
    for p, s in files:
        rel = os.path.relpath(p, repo).replace("\\", "/")
        if rel not in refs:
            unreferenced.append({"path": rel, "bytes": s})
    un_bytes = sum(u["bytes"] for u in unreferenced)
    unreferenced.sort(key=lambda u: -u["bytes"])
    print(f"[audit] 未被引用：{len(unreferenced)} 个，{un_bytes/1024/1024:.1f} MB"
          f"（占总量的 {100*un_bytes/max(total_bytes,1):.0f}%）")

    doc = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "deps_files": len(files),
        "deps_bytes": total_bytes,
        "duplicate_groups": len(dup_groups),
        "duplicate_savable_bytes": dup_bytes,
        "unreferenced_count": len(unreferenced),
        "unreferenced_bytes": un_bytes,
        "note": "仅分析报告，不做删除。清理前须确认引用真的不存在（引用可能是运行时拼接的）。",
        "duplicates": [{"md5": m, "files": [p for p, _ in v]}
                       for m, v in list(dup_groups.items())[:args.max_list]],
        "unreferenced_top": unreferenced[:args.max_list],
    }
    out_path = os.path.join(repo, args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    json.dump(doc, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n未引用文件 TOP（按体积）：")
    for u in unreferenced[:10]:
        print(f"   {u['bytes']/1024:8.0f} KB  {u['path']}")
    print(f"\n产物 -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
