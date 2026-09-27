#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置产物质量校验 + 引用完整性（任务1：P0 基础）。

校验对象
--------
    tvbox.json / vod.json / short.json / stores/*.json 中的 sites 列表。

校验规则
--------
    1. 每个 site 必须有 key/name/api/type 四字段（缺一记入 state/config_issues.json）。
    2. type ∈ {0,1,2,3}，越界告警；--fix 时修正为最接近合法值。
    3. key 全局唯一；重复 key 自动加后缀 key_2/key_3。
    4. api 非空（type 0/1 必须有 api；type 3 允许本地路径）。
    5. name 非空且长度 1-100。
    6. 引用完整性：./deps/... 引用必须落盘存在；spider/jar/ext 引用缺失则置空并
       记入 state/broken_refs.json。

输出
----
    exports/config_quality.json  校验通过率 / 问题分类 / 引用统计 / 字段完整率 / 与上轮对比
    state/config_issues.json     本轮所有问题明细
    state/broken_refs.json       本轮断引用明细

用法
----
    python scripts/config_validate.py            # 只报告
    python scripts/config_validate.py --fix      # 自动修正（key 去重、type 修正、断引用置空）

退出码
------
    0 = 全部通过 或 引用失效率 ≤ 5%
    1 = 引用失效率 > 5%（CI 中 `|| true` 不阻断）
"""
import argparse
import json
import os
import sys
import time

# 仓库根 = 本文件上两级
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
# 复用 pathutil 的路径规范化（与落库时一致）
sys.path.insert(0, os.path.join(REPO, "scripts"))
try:
    from pathutil import safe_segment
except ImportError:  # pragma: no cover
    def safe_segment(s):
        return s.replace(":", "_")

VALID_TYPES = (0, 1, 2, 3)
MAX_NAME_LEN = 100

TARGET_FILES = [
    "tvbox.json",
    "vod.json",
    "short.json",
    "stores/cms.json",
    "stores/app.json",
    "stores/pan.json",
    "stores/csp.json",
]

_LEGIT_TYPES = set(VALID_TYPES)


def nearest_valid_type(t) -> int:
    """把越界 type 修正为最接近的合法值。"""
    try:
        ti = int(t)
    except (TypeError, ValueError):
        return 3
    if ti in _LEGIT_TYPES:
        return ti
    return min(VALID_TYPES, key=lambda v: abs(v - ti))


def validate_site(site: dict, fix: bool, file_label: str) -> list:
    """校验单个 site dict，返回 issues 列表。fix=True 时就地修正。"""
    issues = []
    if not isinstance(site, dict):
        issues.append({"file": file_label, "kind": "not_dict", "detail": str(site)[:80]})
        return issues

    key = site.get("key", "")
    name = site.get("name", "")
    api = site.get("api", "")
    has_type = "type" in site
    t = site.get("type")

    for field in ("key", "name", "api", "type"):
        if field not in site or site.get(field) in (None, ""):
            issues.append({"file": file_label, "key": key, "kind": f"missing_{field}",
                           "detail": f"缺失字段 {field}"})

    if has_type:
        try:
            ti = int(t)
        except (TypeError, ValueError):
            ti = None
        if ti is None or ti not in _LEGIT_TYPES:
            fixed = nearest_valid_type(t)
            issues.append({"file": file_label, "key": key, "kind": "type_out_of_range",
                           "detail": f"type={t!r} 越界，修正为 {fixed}"})
            if fix:
                site["type"] = fixed
    else:
        if fix:
            site["type"] = 3
            issues.append({"file": file_label, "key": key, "kind": "type_missing_defaulted",
                           "detail": "缺失 type，默认 3"})

    effective_type = site.get("type", t)
    try:
        et = int(effective_type)
    except (TypeError, ValueError):
        et = 3
    if et in (0, 1) and not api:
        issues.append({"file": file_label, "key": key, "kind": "api_empty",
                       "detail": f"type={et} 但 api 为空"})

    if name:
        if len(str(name)) > MAX_NAME_LEN:
            issues.append({"file": file_label, "key": key, "kind": "name_too_long",
                           "detail": f"name 长度 {len(str(name))} > {MAX_NAME_LEN}"})
    else:
        issues.append({"file": file_label, "key": key, "kind": "name_empty", "detail": "name 为空"})

    return issues


def dedup_keys(sites: list, fix: bool) -> list:
    """检测重复 key；fix=True 时自动加后缀。"""
    seen = {}
    dupes = []
    for s in sites:
        if not isinstance(s, dict):
            continue
        k = s.get("key", "")
        if not k:
            continue
        if k in seen:
            seen[k] += 1
            new_key = f"{k}_{seen[k]}"
            dupes.append({"original_key": k, "new_key": new_key})
            if fix:
                s["key"] = new_key
        else:
            seen[k] = 1
    return dupes


def _resolve_dep_path(ref: str) -> str:
    """把 './deps/...' 引用解析为仓库内实际落盘路径（与 pathutil 落库规则一致）。"""
    p = ref
    if ";" in p:
        p = p.split(";", 1)[0]
    p = p.lstrip("./")
    parts = [safe_segment(seg) for seg in p.replace("\\", "/").split("/") if seg not in ("", ".")]
    return "/".join(parts)


def _check_one_ref(ref: str, file_label: str, field: str, broken_refs: list,
                   fix: bool, owner: dict):
    """检查单个 ./deps/ 引用字符串是否落盘存在。"""
    rel = _resolve_dep_path(ref)
    if not os.path.exists(rel):
        broken_refs.append({"file": file_label, "field": field, "ref": ref, "resolved": rel})
        if fix and field == "jar":
            owner[field] = ""
        elif fix and field == "ext":
            parts = ref.split("$$$")
            kept = []
            for p in parts:
                if p.startswith("./deps/"):
                    pr = _resolve_dep_path(p)
                    if os.path.exists(pr):
                        kept.append(p)
                else:
                    kept.append(p)
            owner[field] = "$$$".join(kept)


def check_refs_in_obj(obj, file_label: str, broken_refs: list, fix: bool):
    """递归检查 dict/list 中所有 ./deps/... 字符串引用。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and "./deps/" in v:
                if k == "ext" and "$$$" in v:
                    for piece in v.split("$$$"):
                        if piece.startswith("./deps/"):
                            _check_one_ref(piece, file_label, k, broken_refs, fix, obj)
                elif v.startswith("./deps/"):
                    _check_one_ref(v, file_label, k, broken_refs, fix, obj)
                else:
                    check_refs_in_obj(v, file_label, broken_refs, fix)
            else:
                check_refs_in_obj(v, file_label, broken_refs, fix)
    elif isinstance(obj, list):
        for item in obj:
            check_refs_in_obj(item, file_label, broken_refs, fix)


def check_spider_ref(spider: str, file_label: str, broken_refs: list,
                     fix: bool, doc: dict):
    """检查 spider 字段引用的本地 jar 是否存在。"""
    if not spider or not isinstance(spider, str):
        return
    if spider.startswith("./"):
        rel = _resolve_dep_path(spider)
        if not os.path.exists(rel):
            broken_refs.append({"file": file_label, "field": "spider",
                                "ref": spider, "resolved": rel})
            if fix:
                doc["spider"] = ""


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def validate_file(path: str, fix: bool, all_issues: list, broken_refs: list):
    """校验单个产物文件。返回 (sites_count, issues_count, broken_count)。"""
    if not os.path.exists(path):
        all_issues.append({"file": path, "kind": "file_missing", "detail": "文件不存在"})
        return 0, 1, 0

    doc = load_json(path)
    if doc is None:
        all_issues.append({"file": path, "kind": "json_parse_error", "detail": "JSON 解析失败"})
        return 0, 1, 0

    sites = doc.get("sites") if isinstance(doc, dict) else None
    if not isinstance(sites, list):
        return 0, 0, 0

    file_issues = []
    for site in sites:
        file_issues.extend(validate_site(site, fix, path))

    dupes = dedup_keys(sites, fix)
    for d in dupes:
        file_issues.append({"file": path, "kind": "duplicate_key", **d})

    file_broken = []
    check_refs_in_obj(doc, path, file_broken, fix)
    if isinstance(doc, dict):
        check_spider_ref(doc.get("spider", ""), path, file_broken, fix, doc)

    all_issues.extend(file_issues)
    broken_refs.extend(file_broken)

    if fix:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    return len(sites), len(file_issues), len(file_broken)


def main():
    ap = argparse.ArgumentParser(description="配置产物质量校验")
    ap.add_argument("--fix", action="store_true",
                    help="自动修正 key 去重/type 修正/断引用置空")
    args = ap.parse_args()

    all_issues = []
    broken_refs = []
    total_sites = 0
    total_issues = 0
    total_broken = 0
    per_file = {}

    for fpath in TARGET_FILES:
        n, ni, nb = validate_file(fpath, args.fix, all_issues, broken_refs)
        per_file[fpath] = {"sites": n, "issues": ni, "broken_refs": nb}
        total_sites += n
        total_issues += ni
        total_broken += nb

    issue_kinds = {}
    for it in all_issues:
        k = it.get("kind", "unknown")
        issue_kinds[k] = issue_kinds.get(k, 0) + 1

    field_stats = {"key": 0, "name": 0, "api": 0, "type": 0}
    for fpath in TARGET_FILES:
        doc = load_json(fpath)
        if not doc or not isinstance(doc, dict):
            continue
        for s in doc.get("sites", []):
            if not isinstance(s, dict):
                continue
            for f in field_stats:
                if s.get(f) not in (None, ""):
                    field_stats[f] += 1
    field_rates = {f: round(field_stats[f] / total_sites * 100, 2) if total_sites else 0.0
                   for f in field_stats}

    total_refs_checked = 0
    for fpath in TARGET_FILES:
        doc = load_json(fpath)
        if not doc or not isinstance(doc, dict):
            continue
        for s in doc.get("sites", []):
            if not isinstance(s, dict):
                continue
            for f in ("api", "ext", "jar"):
                v = s.get(f)
                if isinstance(v, str) and "./deps/" in v:
                    if f == "ext" and "$$$" in v:
                        total_refs_checked += sum(
                            1 for p in v.split("$$$") if p.startswith("./deps/"))
                    else:
                        total_refs_checked += 1
        sp = doc.get("spider", "")
        if isinstance(sp, str) and sp.startswith("./deps/"):
            total_refs_checked += 1

    ref_fail_rate = round(total_broken / total_refs_checked * 100, 2) if total_refs_checked else 0.0

    prev_quality = {}
    prev_path = "exports/config_quality.json"
    if os.path.exists(prev_path):
        try:
            with open(prev_path, encoding="utf-8") as f:
                prev = json.load(f)
            prev_quality = {
                "prev_pass_rate": prev.get("pass_rate"),
                "prev_issue_count": prev.get("issue_count"),
                "prev_ref_fail_rate": prev.get("ref_fail_rate"),
            }
        except (OSError, json.JSONDecodeError):
            pass

    pass_rate = round((total_sites - total_issues) / total_sites * 100, 2) if total_sites else 100.0

    quality = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "fix_mode": args.fix,
        "total_sites": total_sites,
        "issue_count": total_issues,
        "broken_ref_count": total_broken,
        "pass_rate": pass_rate,
        "ref_fail_rate": ref_fail_rate,
        "ref_total_checked": total_refs_checked,
        "issue_kinds": issue_kinds,
        "field_completeness": field_rates,
        "per_file": per_file,
        "compare_prev": prev_quality,
    }

    os.makedirs("exports", exist_ok=True)
    os.makedirs("state", exist_ok=True)
    with open("exports/config_quality.json", "w", encoding="utf-8") as f:
        json.dump(quality, f, ensure_ascii=False, indent=1)
    with open("state/config_issues.json", "w", encoding="utf-8") as f:
        json.dump({"issues": all_issues, "total": len(all_issues)}, f,
                  ensure_ascii=False, indent=1)
    with open("state/broken_refs.json", "w", encoding="utf-8") as f:
        json.dump({"broken_refs": broken_refs, "total": len(broken_refs)}, f,
                  ensure_ascii=False, indent=1)

    print(f"[config_validate] sites={total_sites} issues={total_issues} "
          f"broken_refs={total_broken} pass_rate={pass_rate}% ref_fail={ref_fail_rate}%")
    if issue_kinds:
        for k, v in sorted(issue_kinds.items(), key=lambda x: -x[1]):
            print(f"  - {k}: {v}")

    if ref_fail_rate > 5.0:
        print(f"[config_validate] 引用失效率 {ref_fail_rate}% > 5%，标记失败（CI 用 || true 不阻断）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
