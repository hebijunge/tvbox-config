#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""站点名称清洗 + 重名处理（任务3：P0）。

读取 tvbox.json，对所有 site 的 name 应用清洗逻辑，处理重名：
    - 同名不同上游 → 加上游标识后缀，如 "YouTube[feishu]"
    - 同名同上游（真正重复）→ 保留质量高的一个，另一个标记 duplicate

输出
----
    state/duplicate_names.json  重名/重复明细

用法
----
    python scripts/normalize_names.py              # 只报告
    python scripts/normalize_names.py --in-place   # 直接修改 tvbox.json
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

try:
    from config_validate import clean_name
except ImportError:
    clean_name = lambda s, k: (str(s), [])


def upstream_tag(site: dict) -> str:
    """从 site 中提取简短上游标识（优先 _origin，取最后一段）。"""
    origin = site.get("_origin", "")
    if origin:
        tag = origin.split("/")[-1]
        tag = re.sub(r"^\d+-", "", tag)
        return tag[:12]
    key = str(site.get("key", ""))
    return key[:8] if key else "unk"


def quality_score(site: dict) -> int:
    """粗略质量分：重名时保留质量高的一个。"""
    score = 0
    if re.search(r"\[\d+ms", str(site.get("name", ""))):
        score += 10
    if site.get("searchable") == 1:
        score += 5
    if site.get("quickSearch") == 1:
        score += 3
    if site.get("api"):
        score += 2
    return score


def normalize_sites(sites: list, in_place: bool) -> dict:
    """对 sites 列表做名称清洗和重名处理。返回报告 dict。"""
    report = {"cleaned_count": 0, "renamed_with_tag": [], "duplicates_removed": []}

    for s in sites:
        if not isinstance(s, dict):
            continue
        old_name = str(s.get("name", ""))
        cleaned, issues = clean_name(old_name, str(s.get("key", "")))
        if cleaned != old_name:
            s["name"] = cleaned
            report["cleaned_count"] += 1

    by_name = defaultdict(list)
    for i, s in enumerate(sites):
        if isinstance(s, dict):
            by_name[str(s.get("name", ""))].append(i)

    indices_to_remove = []
    for name, idxs in by_name.items():
        if len(idxs) <= 1:
            continue
        by_upstream = defaultdict(list)
        for i in idxs:
            tag = upstream_tag(sites[i])
            by_upstream[tag].append(i)

        if len(by_upstream) > 1:
            for tag, group_idxs in by_upstream.items():
                if len(group_idxs) == 1:
                    i = group_idxs[0]
                    old = sites[i].get("name", "")
                    sites[i]["name"] = f"{old}[{tag}]"
                    report["renamed_with_tag"].append({
                        "name": old, "key": sites[i].get("key"),
                        "upstream": tag, "new_name": sites[i]["name"]})
                else:
                    group_sorted = sorted(group_idxs, key=lambda i: quality_score(sites[i]), reverse=True)
                    for dup_i in group_sorted[1:]:
                        report["duplicates_removed"].append({
                            "name": sites[dup_i].get("name"), "key": sites[dup_i].get("key"),
                            "upstream": tag, "reason": "same_upstream_duplicate"})
                        indices_to_remove.append(dup_i)
        else:
            tag = list(by_upstream.keys())[0]
            group_idxs = by_upstream[tag]
            group_sorted = sorted(group_idxs, key=lambda i: quality_score(sites[i]), reverse=True)
            for dup_i in group_sorted[1:]:
                report["duplicates_removed"].append({
                    "name": sites[dup_i].get("name"), "key": sites[dup_i].get("key"),
                    "upstream": tag, "reason": "same_upstream_duplicate"})
                indices_to_remove.append(dup_i)

    if in_place and indices_to_remove:
        for i in sorted(set(indices_to_remove), reverse=True):
            sites.pop(i)
    return report


def main():
    ap = argparse.ArgumentParser(description="站点名称清洗 + 重名处理")
    ap.add_argument("--in-place", action="store_true")
    args = ap.parse_args()

    with open("tvbox.json", encoding="utf-8") as f:
        doc = json.load(f)
    sites = doc.get("sites", [])
    report = normalize_sites(sites, args.in_place)

    os.makedirs("state", exist_ok=True)
    with open("state/duplicate_names.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    if args.in_place:
        tmp = "tvbox.json.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, "tvbox.json")

    print(f"[normalize_names] cleaned={report['cleaned_count']} "
          f"tagged={len(report['renamed_with_tag'])} "
          f"dup_removed={len(report['duplicates_removed'])} in_place={args.in_place}")


if __name__ == "__main__":
    main()
