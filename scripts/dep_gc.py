#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dep_gc.py — 依赖垃圾回收候选清单（P2-1，dry-run 默认，只报告不删除）。

读 state/dep_audit.json 的 unreferenced_top，筛出 age_days>=7 且 gc_candidate=True
的文件，输出可清理清单。**绝不删除任何文件**——实际删除由 cleanup_deps.py 负责。

用法
----
    python scripts/dep_gc.py                  # dry-run：只打印候选
    python scripts/dep_gc.py --json out.json   # 写候选清单
"""
import argparse
import json
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", default="state/dep_audit.json")
    ap.add_argument("--out", default="state/dep_gc_candidates.json")
    ap.add_argument("--min-age-days", type=float, default=7.0)
    args = ap.parse_args()

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
