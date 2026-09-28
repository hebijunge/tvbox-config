#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dep_gc.py — 依赖垃圾回收候选清单（P2-1，dry-run 默认，只报告不删除）。

读 state/dep_audit.json 的 unreferenced_top，筛出 age_days>=7 且 gc_candidate=True
的文件，输出可清理清单。**绝不删除任何文件**——实际删除由 cleanup_deps.py 负责。

另负责 deps/manifest.json 账本瘦身（--prune-manifest）：ref_count=0 且本地文件
已不存在的孤儿记录只增不减会让账本无界膨胀，清理它们不影响任何产物
（死域重试由 state/dep_fail_backoff.json 退避账本独立管理）。

用法
----
    python scripts/dep_gc.py                  # dry-run：只打印候选
    python scripts/dep_gc.py --json out.json   # 写候选清单
    python scripts/dep_gc.py --prune-manifest              # 账本孤儿记录 dry-run
    python scripts/dep_gc.py --prune-manifest --apply      # 实际剪除（自动备份）
"""
import argparse
import json
import os
import sys
import time


def prune_manifest(args) -> int:
    """剪除 manifest 中 ref_count=0 且本地文件缺失、且超过闲置天数的孤儿记录。"""
    if not os.path.isfile(args.manifest):
        print(f"[dep_gc] 找不到 {args.manifest}", file=sys.stderr)
        return 1
    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)
    now = time.time()
    orphans = []
    for key, rec in manifest.items():
        if not isinstance(rec, dict):
            continue
        if int(rec.get("ref_count", 0) or 0) > 0:
            continue
        if os.path.isfile(rec.get("local", "")):
            continue
        upd = (rec.get("updated_at") or "")[:10]
        try:
            idle_days = (now - time.mktime(time.strptime(upd, "%Y-%m-%d"))) / 86400.0
        except ValueError:
            idle_days = 9999
        if idle_days >= args.min_idle_days:
            orphans.append({"key": key, "local": rec.get("local"),
                            "idle_days": round(idle_days, 1)})
    print(f"[dep_gc] manifest {len(manifest)} 条，孤儿记录（ref=0+文件缺失+闲置>="
          f"{args.min_idle_days}天）{len(orphans)} 条")
    for o in orphans[:5]:
        print(f"   {o['idle_days']:7.1f}d  {o['key'][:90]}")
    if not args.apply:
        print("[dep_gc] dry-run：未写回（--apply 生效）")
        return 0
    drop = {o["key"] for o in orphans}
    pruned = {k: v for k, v in manifest.items() if k not in drop}
    backup = args.manifest + ".pre_gc"
    with open(backup, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    with open(args.manifest, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=1)
    print(f"[dep_gc] 已剪除 {len(drop)} 条 -> {args.manifest}（备份 {backup}）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", default="state/dep_audit.json")
    ap.add_argument("--out", default="state/dep_gc_candidates.json")
    ap.add_argument("--min-age-days", type=float, default=7.0)
    ap.add_argument("--prune-manifest", action="store_true",
                    help="清理 deps/manifest.json 孤儿账本记录（默认 dry-run）")
    ap.add_argument("--manifest", default=os.path.join("deps", "manifest.json"))
    ap.add_argument("--min-idle-days", type=float, default=3.0)
    ap.add_argument("--apply", action="store_true", help="配合 --prune-manifest 实际写回")
    args = ap.parse_args()

    if args.prune_manifest:
        return prune_manifest(args)

    if not os.path.isfile(args.audit):
        print(f"[dep_gc] 找不到 {args.audit}，先跑 scripts/dep_audit.py", file=sys.stderr)
        return 1

    with open(args.audit, encoding="utf-8") as f:
        audit = json.load(f)

    # dep_audit 里 unreferenced_top 只列了 TOP N；这里全量重扫 deps/ 以 refs 为准
    refs = set()
    base = "tvbox.json"
    if os.path.isfile(base):
        import re as _re
        txt = open(base, encoding="utf-8", errors="replace").read()
        for m in _re.finditer(r"\.?/?deps/[^\s\"'<>\\),;]+", txt):
            refs.add(m.group(0).lstrip("./").replace("\\", "/"))

    import time as _time
    now = _time.time()
    candidates = []
    total_bytes = 0
    for root, _, names in os.walk("deps"):
        for n in names:
            fp = os.path.join(root, n)
            rel = os.path.relpath(fp, ".").replace("\\", "/")
            if rel in refs:
                continue
            try:
                age = (now - os.path.getmtime(fp)) / 86400.0
                sz = os.path.getsize(fp)
            except OSError:
                continue
            if age >= args.min_age_days:
                candidates.append({"path": rel, "bytes": sz, "age_days": round(age, 1)})
                total_bytes += sz

    candidates.sort(key=lambda x: -x["bytes"])
    doc = {
        "dry_run": True,
        "note": "只报告不删除；实际清理由 cleanup_deps.py 执行",
        "min_age_days": args.min_age_days,
        "candidate_count": len(candidates),
        "reclaimable_mb": round(total_bytes / 1024 / 1024, 1),
        "candidates": candidates,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print(f"[dep_gc] dry-run：{len(candidates)} 个未引用且 ≥{args.min_age_days} 天的候选，"
          f"可回收 {total_bytes/1024/1024:.1f} MB")
    for c in candidates[:10]:
        print(f"   {c['bytes']/1024:8.0f} KB  {c['age_days']:5.1f}d  {c['path']}")
    print(f"[dep_gc] 候选清单 -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
