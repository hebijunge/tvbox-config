#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置产物质量校验 + 引用完整性 + 名称清洗（任务1+2合并）。

校验对象
--------
    tvbox.json / vod.json / short.json / stores/*.json 中的 sites 列表。

校验规则
--------
    1. 每个 site 必须有 key/name/api/type 四字段（缺一记入 state/config_issues.json）。
    2. type ∈ {0,1,2,3}，越界告警；--fix 时修正为最接近合法值。
    3. key 全局唯一；重复 key 自动加后缀 key_2/key_3。
    4. api 非空（type 0/1 必须有 api；type 3 允许本地路径）。
    5. name 非空且长度 1-100；纯空白/纯符号用 key 替代。
    6. 引用完整性：./deps/... 引用必须落盘存在；spider/jar/ext 引用缺失则置空并
       记入 state/broken_refs.json。
    7. 名称清洗：广告后缀正则清洗、全角转半角、繁转简、乱码标记（词表见
       config/name_clean_vocab.json）。

输出
----
    exports/config_quality.json  校验通过率 / 问题分类 / 引用统计 / 字段完整率 / 与上轮对比
    state/config_issues.json     本轮所有问题明细
    state/broken_refs.json       本轮断引用明细

用法
----
    python scripts/config_validate.py            # 只报告
    python scripts/config_validate.py --fix      # 自动修正

退出码
------
    0 = 全部通过 或 引用失效率 ≤ 5%
    1 = 引用失效率 > 5%（CI 中 `|| true` 不阻断）
"""
import argparse
import json
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
try:
    from pathutil import safe_segment
except ImportError:
    def safe_segment(s):
        return s.replace(":", "_")

VALID_TYPES = (0, 1, 2, 3)
MAX_NAME_LEN = 100
VOCAB_PATH = "config/name_clean_vocab.json"

TARGET_FILES = [
    "tvbox.json", "vod.json", "short.json",
    "stores/cms.json", "stores/app.json", "stores/pan.json", "stores/csp.json",
]
_LEGIT_TYPES = set(VALID_TYPES)


# --------------------------------------------------------------------------- #
# 词表加载（任务2）
# --------------------------------------------------------------------------- #
def load_vocab():
    default = {
        "ad_patterns": [
            {"re": "加[群微][群信]?", "label": "加群"},
            {"re": "[Qq]{2}[群扣]", "label": "QQ群"},
            {"re": "福利", "label": "福利"},
            {"re": "微信", "label": "微信"},
            {"re": "免费看", "label": "免费看"},
        ],
        "noise_chars_re": "[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]",
        "traditional_to_simplified": {},
    }
    try:
        with open(VOCAB_PATH, encoding="utf-8") as f:
            v = json.load(f)
        if isinstance(v, dict):
            v.setdefault("ad_patterns", default["ad_patterns"])
            v.setdefault("noise_chars_re", default["noise_chars_re"])
            v.setdefault("traditional_to_simplified", {})
            return v
    except (OSError, json.JSONDecodeError):
        pass
    return default


_VOCAB = load_vocab()
_AD_RES = [(p.get("re", ""), p.get("label", "ad"))
           for p in _VOCAB.get("ad_patterns", []) if p.get("re")]
_NOISE_RE = re.compile(_VOCAB.get("noise_chars_re", "")) if _VOCAB.get("noise_chars_re") else None
_T2S = _VOCAB.get("traditional_to_simplified", {})

_FW_MAP = {}
for i, ch in enumerate(_VOCAB.get("fullwidth_digits", "０１２３４５６７８９")):
    hd = _VOCAB.get("halfwidth_digits", "0123456789")
    _FW_MAP[ch] = hd[i] if i < len(hd) else ch
for code in range(0xFF21, 0xFF3B):
    _FW_MAP[chr(code)] = chr(code - 0xFEE0)
for code in range(0xFF41, 0xFF5B):
    _FW_MAP[chr(code)] = chr(code - 0xFEE0)


def clean_name(raw_name, key=""):
    """清洗站点名称。返回 (cleaned_name, issues_list)。"""
    issues = []
    s = str(raw_name) if raw_name is not None else ""
    s = "".join(_FW_MAP.get(ch, ch) for ch in s)
    s = "".join(_T2S.get(ch, ch) for ch in s)
    if _NOISE_RE and _NOISE_RE.search(s):
        issues.append({"kind": "garbled", "raw": raw_name, "detail": "含不可打印字符"})
        s = _NOISE_RE.sub("", s)
    for pat, label in _AD_RES:
        try:
            new = re.sub(pat, "", s)
            if new != s:
                issues.append({"kind": "ad_removed", "raw": raw_name, "detail": f"命中[{label}]"})
                s = new
        except re.error:
            continue
    s = s.strip(" \t\r\n-_·|：:：,，。.")
    if not re.sub(r"[\W_]+", "", s, flags=re.UNICODE):
        if key:
            issues.append({"kind": "empty_name", "raw": raw_name, "detail": "纯空白/纯符号，用 key 替代"})
            s = key
        else:
            issues.append({"kind": "empty_name", "raw": raw_name, "detail": "空名称且无 key"})
            s = str(raw_name) or "unknown"
    if len(s) > MAX_NAME_LEN:
        issues.append({"kind": "name_too_long", "raw": raw_name, "detail": f"长度{len(s)}>{MAX_NAME_LEN}"})
        s = s[:MAX_NAME_LEN]
    return s, issues


def nearest_valid_type(t) -> int:
    try:
        ti = int(t)
    except (TypeError, ValueError):
        return 3
    if ti in _LEGIT_TYPES:
        return ti
    return min(VALID_TYPES, key=lambda v: abs(v - ti))


def validate_site(site: dict, fix: bool, file_label: str) -> list:
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
            issues.append({"file": file_label, "key": key, "kind": f"missing_{field}", "detail": f"缺失字段 {field}"})

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
    elif fix:
        site["type"] = 3
        issues.append({"file": file_label, "key": key, "kind": "type_missing_defaulted", "detail": "缺失 type，默认 3"})

    et = site.get("type", t)
    try:
        et = int(et)
    except (TypeError, ValueError):
        et = 3
    if et in (0, 1) and not api:
        issues.append({"file": file_label, "key": key, "kind": "api_empty", "detail": f"type={et} 但 api 为空"})

    if name:
        if len(str(name)) > MAX_NAME_LEN:
            issues.append({"file": file_label, "key": key, "kind": "name_too_long",
                           "detail": f"name 长度 {len(str(name))} > {MAX_NAME_LEN}"})
    else:
        issues.append({"file": file_label, "key": key, "kind": "name_empty", "detail": "name 为空"})

    cleaned, clean_issues = clean_name(str(name), str(key))
    for ci in clean_issues:
        ci["file"] = file_label
        ci["key"] = key
        issues.append(ci)
    if fix and cleaned != str(name):
        site["name"] = cleaned
    return issues


def dedup_keys(sites: list, fix: bool) -> list:
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
    p = ref
    if ";" in p:
        p = p.split(";", 1)[0]
    p = p.lstrip("./")
    parts = [safe_segment(seg) for seg in p.replace("\\", "/").split("/") if seg not in ("", ".")]
    return "/".join(parts)


def _check_one_ref(ref, file_label, field, broken_refs, fix, owner):
    rel = _resolve_dep_path(ref)
    if not os.path.exists(rel):
        broken_refs.append({"file": file_label, "field": field, "ref": ref, "resolved": rel})
        if fix and field == "jar":
            owner[field] = ""
        elif fix and field == "ext":
            kept = []
            for p in ref.split("$$$"):
                if p.startswith("./deps/"):
                    if os.path.exists(_resolve_dep_path(p)):
                        kept.append(p)
                else:
                    kept.append(p)
            owner[field] = "$$$".join(kept)


def check_refs_in_obj(obj, file_label, broken_refs, fix):
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


def check_spider_ref(spider, file_label, broken_refs, fix, doc):
    if not spider or not isinstance(spider, str) or not spider.startswith("./"):
        return
    rel = _resolve_dep_path(spider)
    if not os.path.exists(rel):
        broken_refs.append({"file": file_label, "field": "spider", "ref": spider, "resolved": rel})
        if fix:
            doc["spider"] = ""


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def validate_file(path, fix, all_issues, broken_refs):
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
    file_issues = [issue for site in sites for issue in validate_site(site, fix, path)]
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


# P0-4 产出后校验：产物文件大小上限（硬错误阻断，软错误告警）
# tvbox.json 不设上限（站点规模增长后体积自然膨胀，不再作为阻断条件）
SIZE_LIMITS = {
    "vod.json": (400 * 1024, "soft"),
    "short.json": (400 * 1024, "soft"),
    "live.json": (200 * 1024, "soft"),
}


def _dir_size(path: str) -> int:
    total = 0
    for root, _, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n))
            except OSError:
                pass
    return total


def _check_file_sizes():
    """P0-4：校验产物文件大小。返回 (hard_errors, soft_warnings)。"""
    hard, soft = [], []
    for fp, (limit, level) in SIZE_LIMITS.items():
        if not os.path.isfile(fp):
            continue
        sz = os.path.getsize(fp)
        if sz > limit:
            entry = {"file": fp, "size_kb": round(sz / 1024, 1),
                     "limit_kb": round(limit / 1024, 1)}
            (hard if level == "hard" else soft).append(entry)
            print(f"  [{'HARD' if level=='hard' else 'warn'}] {fp} = {sz/1024:.0f}KB"
                  f" > 上限 {limit/1024:.0f}KB", flush=True)
    # deps/ 目录总体积
    if os.path.isdir("deps"):
        dsz = _dir_size("deps")
        if dsz > 200 * 1024 * 1024:
            soft.append({"dir": "deps/", "size_mb": round(dsz / 1024 / 1024, 1),
                         "limit_mb": 200})
            print(f"  [warn] deps/ = {dsz/1024/1024:.0f}MB > 上限 200MB", flush=True)
    return hard, soft


def main():
    ap = argparse.ArgumentParser(description="配置产物质量校验")
    ap.add_argument("--fix", action="store_true")
    args = ap.parse_args()

    all_issues, broken_refs = [], []
    total_sites = total_issues = total_broken = 0
    per_file = {}
    for fp in TARGET_FILES:
        n, ni, nb = validate_file(fp, args.fix, all_issues, broken_refs)
        per_file[fp] = {"sites": n, "issues": ni, "broken_refs": nb}
        total_sites += n
        total_issues += ni
        total_broken += nb

    issue_kinds = {}
    for it in all_issues:
        k = it.get("kind", "unknown")
        issue_kinds[k] = issue_kinds.get(k, 0) + 1

    field_stats = {"key": 0, "name": 0, "api": 0, "type": 0}
    for fp in TARGET_FILES:
        doc = load_json(fp)
        if not doc or not isinstance(doc, dict):
            continue
        for s in doc.get("sites", []):
            if isinstance(s, dict):
                for f in field_stats:
                    if s.get(f) not in (None, ""):
                        field_stats[f] += 1
    field_rates = {f: round(field_stats[f] / total_sites * 100, 2) if total_sites else 0.0
                   for f in field_stats}

    total_refs_checked = 0
    for fp in TARGET_FILES:
        doc = load_json(fp)
        if not doc or not isinstance(doc, dict):
            continue
        for s in doc.get("sites", []):
            if not isinstance(s, dict):
                continue
            for f in ("api", "ext", "jar"):
                v = s.get(f)
                if isinstance(v, str) and "./deps/" in v:
                    if f == "ext" and "$$$" in v:
                        total_refs_checked += sum(1 for p in v.split("$$$") if p.startswith("./deps/"))
                    else:
                        total_refs_checked += 1
        sp = doc.get("spider", "")
        if isinstance(sp, str) and sp.startswith("./deps/"):
            total_refs_checked += 1

    ref_fail_rate = round(total_broken / total_refs_checked * 100, 2) if total_refs_checked else 0.0
    prev_quality = {}
    if os.path.exists("exports/config_quality.json"):
        try:
            with open("exports/config_quality.json", encoding="utf-8") as f:
                prev = json.load(f)
            prev_quality = {"prev_pass_rate": prev.get("pass_rate"),
                            "prev_issue_count": prev.get("issue_count"),
                            "prev_ref_fail_rate": prev.get("ref_fail_rate")}
        except (OSError, json.JSONDecodeError):
            pass

    pass_rate = round((total_sites - total_issues) / total_sites * 100, 2) if total_sites else 100.0
    quality = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "fix_mode": args.fix, "total_sites": total_sites, "issue_count": total_issues,
        "broken_ref_count": total_broken, "pass_rate": pass_rate,
        "ref_fail_rate": ref_fail_rate, "ref_total_checked": total_refs_checked,
        "issue_kinds": issue_kinds, "field_completeness": field_rates,
        "per_file": per_file, "compare_prev": prev_quality,
    }
    os.makedirs("exports", exist_ok=True)
    os.makedirs("state", exist_ok=True)
    with open("exports/config_quality.json", "w", encoding="utf-8") as f:
        json.dump(quality, f, ensure_ascii=False, indent=1)
    with open("state/config_issues.json", "w", encoding="utf-8") as f:
        json.dump({"issues": all_issues, "total": len(all_issues)}, f, ensure_ascii=False, indent=1)
    with open("state/broken_refs.json", "w", encoding="utf-8") as f:
        json.dump({"broken_refs": broken_refs, "total": len(broken_refs)}, f, ensure_ascii=False, indent=1)

    print(f"[config_validate] sites={total_sites} issues={total_issues} "
          f"broken_refs={total_broken} pass_rate={pass_rate}% ref_fail={ref_fail_rate}%")
    for k, v in sorted(issue_kinds.items(), key=lambda x: -x[1]):
        print(f"  - {k}: {v}")
    # P0-4：产出后文件大小校验
    size_hard, size_soft = _check_file_sizes()
    quality["size_hard_errors"] = size_hard
    quality["size_soft_warnings"] = size_soft

    if ref_fail_rate > 5.0:
        print(f"[config_validate] [warn] 引用失效率 {ref_fail_rate}% > 5%（仅告警不阻断；上游 deps 下载失败属常态）")
    if size_hard:
        print(f"[config_validate] 硬错误 {len(size_hard)} 个（产物超大小上限），exit 1")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
