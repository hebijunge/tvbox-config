#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""head_slim_deps.py — 从 HEAD 移除"当前无引用 ∧ 最近 N 天没动过"的 deps 文件。

为什么需要
----------
`fetch_merge.py` 每次 daily 都会按 URL 的 md5 命名拉 dep 落到 `deps/` 下，一旦上游
jar 更新、URL 变了、或者源被剥离，旧 md5 命名的文件既不会被新引用，也不在
manifest 里再登记 —— 但它仍然被 git 跟踪在 HEAD 里，CI 每次 `actions/checkout`
都要把这些"历史 md5 副本"整份拉下来。2026-10-03 实测 fresh checkout 时
`deps/` = **12165 files / 1492 MB**，但 dep_refs 权威口径只引用 **3435** 条，
**~8700 个文件 / 1.15 GB** 是 HEAD 里跟踪的孤儿。

`cleanup_deps.py` 只清 `deps/localized/` + `deps/external/` 两个无主目录（P1-8
安全边界），大头 `deps/auto/*` / `deps/jar/*` 不在白名单里；且它只删磁盘不
删索引，daily 又会把索引里的老 blob 检出。所以**"从 HEAD 移除"是独立议题**：
它让 CI 不再检出、让 pack 停止被这些文件撑大，但**不解锁物理删除**。

安全模型（宁可不移，不可移错）
--------------------------------
  1. 引用口径 = `dep_refs.collect_all_refs` = 7 主产物 + stores/*.json +
     `deps/manifest.json` 账本 + exports/adult_live_channels/config 等消费者文件，
     与 dep_audit / dep_gc / cleanup_deps 严格一致；
  2. 只挑"最近 `--min-age-days`（默认 30）天**未在 git log 里出现过**"的文件——
     这条把 fetch_merge 每天在改的活跃 dep 排除掉，也顺手排除了"上周刚剥离引用
     但按 7/14 天保留期还未到期"的一族；
  3. 默认 dry-run，只写 `state/head_slim_candidates.json`；`--execute` 才
     `git rm`（同时删索引和磁盘，磁盘部分由 fetch_merge 下一轮重下真正需要的）。

用法
----
    python scripts/head_slim_deps.py                       # 默认 dry-run，min-age=30 天
    python scripts/head_slim_deps.py --min-age-days 7      # 更激进（不推荐）
    python scripts/head_slim_deps.py --json out.json       # 自定义候选清单路径
    python scripts/head_slim_deps.py --execute             # 真 git rm（**必须显式**）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import dep_refs  # noqa: E402


def _git(args, repo="."):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace",
    ).stdout


def tracked_deps(repo="."):
    """git ls-files 拿 HEAD 索引里跟踪的 deps/**。返回 posix 相对仓库根路径集合。"""
    out = _git(["ls-files", "--", "deps/"], repo=repo)
    return {ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()}


def recently_touched_deps(min_age_days, repo="."):
    """最近 min_age_days 天内 git log 里出现过的 deps/**。"""
    cutoff = f"{min_age_days}.days.ago"
    out = _git(["log", f"--since={cutoff}", "--name-only", "--pretty=format:",
                "--", "deps/"], repo=repo)
    return {ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()}


def build_candidates(repo=".", min_age_days=30, only_dir=None):
    """返回 {paths: [...], bytes: int, by_dir: {top-dir: {count, bytes}}}。

    引用口径由 dep_refs 唯一提供；recently_touched 用 git log 拿，绕开 mtime
    在 CI/多 worktree 下的漂移。only_dir 若非空则按前缀过滤（分批推进用：
    先 `deps/external/` → `deps/localized/` → `deps/auto/`）。
    """
    refs = dep_refs.collect_all_refs(repo)
    # 账本 / 备份文件本身既不会被引用、也绝不能从 HEAD 移除（否则 dep_refs 下轮没账本可读）
    keep = set(getattr(dep_refs, "LEDGER_PATHS", ()))
    tracked = tracked_deps(repo)
    touched = recently_touched_deps(min_age_days, repo)
    cand_paths = sorted(p for p in tracked
                        if p not in refs and p not in touched and p not in keep
                        and (only_dir is None or p.startswith(only_dir)))
    by_dir = defaultdict(lambda: {"count": 0, "bytes": 0})
    total_bytes = 0
    sizes = {}
    for rel in cand_paths:
        abs_p = os.path.join(repo, rel)
        try:
            sz = os.path.getsize(abs_p)
        except OSError:
            sz = 0
        sizes[rel] = sz
        total_bytes += sz
        # 按 deps/<top>/ 分桶，让 review 一眼看清哪些目录是主力
        parts = rel.split("/", 2)
        top = "/".join(parts[:2]) + "/" if len(parts) >= 3 else rel
        by_dir[top]["count"] += 1
        by_dir[top]["bytes"] += sz
    return {
        "paths": cand_paths,
        "bytes": total_bytes,
        "sizes": sizes,
        "by_dir": dict(by_dir),
        "refs_total": len(refs),
        "tracked_total": len(tracked),
        "recently_touched": len(touched),
        "min_age_days": min_age_days,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--min-age-days", type=int, default=30,
                    help="git log 里最近 N 天出现过的 deps 视为活跃，不参与候选")
    ap.add_argument("--only-dir", default=None,
                    help="限定前缀（如 deps/external/），配合分批推进；默认全扫")
    ap.add_argument("--out", default="state/head_slim_candidates.json")
    ap.add_argument("--top", type=int, default=20, help="TOP N 大文件写进摘要")
    ap.add_argument("--execute", action="store_true",
                    help="git rm 候选；默认 dry-run")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    cand = build_candidates(repo=repo, min_age_days=args.min_age_days,
                             only_dir=args.only_dir)
    scope = f" (only_dir={args.only_dir})" if args.only_dir else ""
    print(f"[head_slim] deps 跟踪 {cand['tracked_total']} 条，"
          f"引用 {cand['refs_total']} 条，"
          f"最近 {args.min_age_days} 天有改动 {cand['recently_touched']} 条{scope}")
    print(f"[head_slim] 候选：{len(cand['paths'])} 个 / {cand['bytes']/1024/1024:.1f} MB")
    print("[head_slim] 按目录分桶（前 10）：")
    for top, meta in sorted(cand["by_dir"].items(),
                             key=lambda kv: -kv[1]["bytes"])[:10]:
        print(f"   {meta['bytes']/1024/1024:8.1f} MB  {meta['count']:5} 个  {top}")
    print("[head_slim] TOP 大文件：")
    for p in sorted(cand["paths"], key=lambda x: -cand["sizes"].get(x, 0))[:args.top]:
        print(f"   {cand['sizes'].get(p, 0)/1024:8.0f} KB  {p}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dry_run": not args.execute,
        "min_age_days": args.min_age_days,
        "candidate_count": len(cand["paths"]),
        "reclaimable_bytes": cand["bytes"],
        "refs_total": cand["refs_total"],
        "tracked_total": cand["tracked_total"],
        "by_dir": cand["by_dir"],
        "paths": cand["paths"],
        "note": "从 HEAD 移除不等于物理删除；下一轮 fetch_merge 只重下"
                "manifest 里仍在登记的。--execute 才真 git rm。",
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"[head_slim] 清单 -> {args.out}")

    if not args.execute:
        print(f"[head_slim] dry-run：未 git rm；确认无误后加 --execute")
        return 0

    # 分批喂给 git rm，避免命令行过长（Windows CreateProcess ~32K）
    n = 0
    buf = []
    for p in cand["paths"]:
        buf.append(p)
        if len(buf) >= 500:
            subprocess.run(["git", "rm", "--quiet", "--", *buf],
                            cwd=repo, check=True)
            n += len(buf)
            buf = []
    if buf:
        subprocess.run(["git", "rm", "--quiet", "--", *buf], cwd=repo, check=True)
        n += len(buf)
    print(f"[head_slim] 已 git rm {n} 个文件（下一步请 git commit）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
