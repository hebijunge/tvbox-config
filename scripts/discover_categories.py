#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""discover_categories.py — 动态仓发现：扫 tvbox.json 统计未命中品类的高频词。

用法
----
    python scripts/discover_categories.py
    python scripts/discover_categories.py --min-pct 5.0

输出：state/category_suggestions.json（人工审核后再加进 GROUP_ORDER / category_vocab.json）。
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tvbox", default="tvbox.json")
    ap.add_argument("--vocab", default="config/category_vocab.json")
    ap.add_argument("--out", default="state/category_suggestions.json")
    ap.add_argument("--min-pct", type=float, default=5.0)
    args = ap.parse_args()

    if not os.path.isfile(args.tvbox):
        print(f"[discover] 找不到 {args.tvbox}", file=sys.stderr)
        return 1

    tv = json.load(open(args.tvbox, encoding="utf-8"))
    sites = tv.get("sites", [])

    vocab = {}
    if os.path.isfile(args.vocab):
        vocab = json.load(open(args.vocab, encoding="utf-8"))
    known_kw = set()
    for kws in vocab.values():
        if isinstance(kws, list):
            known_kw.update(str(k).lower() for k in kws)

    # 提取每个站 name 里的 2-4 字词
    word_counter = Counter()
    for s in sites:
        name = (s.get("name") or "").lower()
        if not name:
            continue
        # 粗切：按非字符切，取 2 字以上片段
        for tok in re.split(r"[\s\-_·|：:：,，。.()（）\[\]【】]+", name):
            if len(tok) >= 2 and tok not in known_kw:
                word_counter[tok] += 1

    total = max(len(sites), 1)
    suggestions = []
    for word, n in word_counter.most_common(50):
        pct = 100.0 * n / total
        if pct >= args.min_pct:
            suggestions.append({"word": word, "count": n, "pct": round(pct, 1)})

    doc = {
        "total_sites": total,
        "min_pct": args.min_pct,
        "suggestions": suggestions,
        "note": "高频未命中词；人工审核后决定是否加进 GROUP_ORDER / category_vocab.json",
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print(f"[discover] 扫描 {total} 站，{len(suggestions)} 个高频未命中词（≥{args.min_pct}%）")
    for s in suggestions[:15]:
        print(f"   {s['pct']:5.1f}%  ({s['count']:4d})  {s['word']}")
    print(f"[discover] 建议 -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
