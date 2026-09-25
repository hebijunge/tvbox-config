"""live_vocab.py — 直播频道分类（基于 JSON 词表，可日迭代）。

设计原则：
- 规则/词表全部来自 state/vocab/*.json（不要在此文件硬编码）。
- 分类优先级遵循产品1号方案（categories.json 中显式给出）：
    source_marker > adult > cctv > gangtai > lunbo > local > live
- 入参：name（频道名，必填）、url（可选，rtp/udp/host 判别）、source_marker（来源源标记，可选）。
- 输出：{'group': str, 'key': str, 'canonical': str, 'debug': dict}
- group ∈ {'cctv', 'gangtai', 'lunbo', 'local', 'live', 'adult', 'source'}
- key：归一化键（去质量词/品牌后缀/方括号/全半角/繁简），用于跨上游聚合
- canonical：标准显示名（CCTV-N / 港台电视31 / 湖南卫视 等）

# 2026-09-25 落地：词表驱动版本（研发1号）
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Optional


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
VOCAB_DIR = os.path.join(REPO, "state", "vocab")


@lru_cache(maxsize=1)
def _load_normalization():
    with open(os.path.join(VOCAB_DIR, "normalization.json"), encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_categories():
    with open(os.path.join(VOCAB_DIR, "categories.json"), encoding="utf-8") as f:
        return json.load(f)


def _compiled():
    """编译一次 regex，返回 (norm_meta, cat_meta, compiled_regexes_dict)。"""
    norm = _load_normalization()
    cat = _load_categories()
    out = {
        "norm": norm,
        "cat": cat,
        "strip_group": [re.compile(p) for p in norm.get("strip_group_prefix_patterns", [])],
        "quality_strip": [re.compile(p, re.IGNORECASE) for p in norm.get("quality_strip_patterns", [])],
        "brand_suffix": [re.compile(p) for p in norm.get("brand_suffix_patterns", [])],
        "alias_regex": [re.compile(r["pattern"]) for r in norm.get("alias_regex", [])],
        "cctv_numbered": next((re.compile(r["pattern"]) for r in norm["alias_regex"] if r["id"] == "cctv_numbered"), None),
        "cctv_cetv": next((re.compile(r["pattern"]) for r in norm["alias_regex"] if r["id"] == "cctv_cetv"), None),
        "cctv_cgtn": next((re.compile(r["pattern"]) for r in norm["alias_regex"] if r["id"] == "cctv_cgtn"), None),
        "adult_pure_num": re.compile(cat["adult"]["name_pure_num_regex"]),
        "adult_bracket_tag": re.compile(cat["adult"]["name_bracket_tag_regex"]),
        "adult_date_code": re.compile(cat["adult"]["name_date_code_regex"]),
        "adult_host_re": re.compile(cat["adult"]["host_blacklist_pattern"], re.IGNORECASE),
        "lunbo_exclude": [re.compile(p) for p in cat["lunbo"].get("exclude_patterns", [])],
        "fullwidth_map": norm.get("fullwidth_map", {}),
        "t2s": norm.get("t2s", {}),
        "cctv_subname_strip": cat["cctv"].get("subname_strip", []),
        "cctv_alias_canonical": norm.get("cctv_alias_canonical", {}),
    }
    return out


def _host_of(url: str) -> str:
    """提取 host（仅 scheme://host[:port] 部分；rtp/udp 走 multicast_schemes）。"""
    if not url:
        return ""
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://([^/?#]+)", url)
    return m.group(1).lower() if m else ""


def normalize(name: str, *, strip_quality: bool = True, strip_brand: bool = True) -> str:
    """频道名归一化（用于去重键；不输出标准名，只输出「干净键」）。

    顺序：
      a) 方括号/全角括号来源组前缀整段剥
      b) 全角→半角
      c) 质量词剥离（仅 strip_quality=True 时；剥离时用 \s+ 折叠空白，保证词边界）
      d) 品牌后缀剥离（仅 strip_brand=True 时）
      e) 折叠空白（强制）
      f) 繁→简（聚合键需简体）
      g) lowercase
    """
    if not name:
        return ""
    c = _compiled()
    s = name.strip()
    # a) 方括号/全角括号来源组前缀整段剥
    for rgx in c["strip_group"]:
        s = rgx.sub("", s)
    # b) 全角→半角
    if c["fullwidth_map"]:
        s = "".join(c["fullwidth_map"].get(ch, ch) for ch in s)
    # c) 质量词剥离（先折叠空白再做匹配，避免 CCTV-1 1080P → CCTV-11080p 失去词边界）
    if strip_quality:
        s = re.sub(r"[\s\u3000]+", " ", s)  # 折叠为单空格（保留边界）
        for rgx in c["quality_strip"]:
            s = rgx.sub(" ", s)  # 替成空格以便后续折叠
        # 也清掉残留方括号/全角括号（双保险）
        s = re.sub(r"[\[\]【】()（）]", " ", s)
    # d) 品牌后缀
    if strip_brand:
        for rgx in c["brand_suffix"]:
            s = rgx.sub(" ", s)
    # e) 折叠空白
    s = re.sub(r"[\s\u3000]+", "", s)
    # f) 繁→简
    if c["t2s"]:
        s = "".join(c["t2s"].get(ch, ch) for ch in s)
    # g) lowercase
    return s.lower()


def _is_multicast(url: str) -> bool:
    cat = _load_categories()
    schemes = cat["local"].get("multicast_schemes", [])
    return any(url.startswith(s) for s in schemes)


def _host_is_adult(host: str) -> bool:
    c = _compiled()
    if not host:
        return False
    exact = _load_categories()["adult"].get("host_blacklist_exact", [])
    if host in exact:
        return True
    return bool(c["adult_host_re"].search(host))


def _is_adult_name(name: str) -> bool:
    c = _compiled()
    if not name:
        return False
    if c["adult_pure_num"].match(name.strip()):
        return True
    if c["adult_bracket_tag"].match(name):
        return True
    if c["adult_date_code"].match(name.lower().strip()):
        return True
    cat = _load_categories()
    pkw = [k.lower() for k in cat["adult"]["name_keywords"]]
    low = name.lower()
    return any(k in low for k in pkw)


def _cctv_match(name: str) -> Optional[str]:
    """匹配 CCTV（含 CGTN/CETV），返回 canonical 名（如 'CCTV-1'/'CETV-2'/'CGTN'/'CGTN english'）。"""
    c = _compiled()
    if not name:
        return None
    raw = name.strip()
    low = raw.lower().replace(" ", "").replace("\u3000", "")
    # 央视一套...十七套 别名表
    alias = c["cctv_alias_canonical"]
    if raw in alias:
        return alias[raw]
    cat = _load_categories()
    cctv_prefix = cat["cctv"]["prefix_keywords"]
    if not any(low.startswith(k) for k in cctv_prefix):
        # 兜底：含 cctv/央视 子串也算
        if not any(k in low for k in cctv_prefix):
            return None
    # 编号 CCTV
    m = c["cctv_numbered"].match(low)
    if m:
        n_str = str(int(m.group(2)))
        plus = m.group(3) or ""
        # 严格任务约束：仅 1..17 归 cctv 组
        if 1 <= int(n_str) <= 17:
            return f"CCTV-{n_str}{plus}"
        return None  # 越界 CCTV（如 CCTV-20 纪录片/付费）→ 不归 cctv
    m = c["cctv_cetv"].match(low)
    if m:
        return f"CETV-{int(m.group(1))}"
    m = c["cctv_cgtn"].match(low)
    if m:
        lang = (m.group(2) or "").strip().lower()
        return f"CGTN{(' ' + lang) if lang else ''}"
    return None


def _gangtai_match(name: str) -> Optional[str]:
    """匹配港台组（TVB/翡翠/明珠/凤凰/HK开电视/HOY/TVBS/中天/东森/民视/三立/华视/公视/纬来 等）。"""
    if not name:
        return None
    cat = _load_categories()
    kws = [k.lower() for k in cat["gangtai"]["keywords"]]
    neg = cat["gangtai"].get("negative", [])
    low = name.lower().replace(" ", "").replace("\u3000", "")
    # 负面守卫：翡翠湾 等
    if any(n.lower() in low for n in neg):
        return None
    if any(k in low for k in kws):
        return name.strip()
    return None


def _lunbo_match(name: str) -> Optional[str]:
    """匹配轮播组（含轮播/循环/重播等）；但要排除「第N期/初舞台/回味」等综艺/节目名。"""
    if not name:
        return None
    cat = _load_categories()
    kws = cat["lunbo"]["keywords"]
    if not any(k in name for k in kws):
        return None
    c = _compiled()
    for rx in c["lunbo_exclude"]:
        if rx.search(name):
            return None
    return name.strip()


def _local_match(name: str, url: str) -> Optional[str]:
    """匹配地方（省/直辖市 + 卫视/都市/新闻等子频道）；rtp/udp 组播优先归地方。
    返回省/直辖市名，未命中返回 None。"""
    if not name:
        return None
    cat = _load_categories()
    # 组播优先：rtp/udp 强制归地方
    if _is_multicast(url):
        # 在省份表里再找一次
        for prov in cat["local"]["province_table"]:
            for kw in prov["keywords"]:
                if kw.lower() in name.lower():
                    return prov["name"]
        return "其他"  # 组播但找不到省 → 地方-其他
    # 普通省级表
    for prov in cat["local"]["province_table"]:
        for kw in prov["keywords"]:
            if kw.lower() in name.lower():
                return prov["name"]
    # 子级关键词（卫视/都市/新闻/民生等）即便未命中省也归地方
    for suf in cat["local"].get("suffix_keywords", []):
        if suf in name:
            return "其他"
    return None


def classify(name: str, url: str = "", source_marker: Optional[str] = None) -> dict:
    """分类主入口。返回 {'group', 'key', 'canonical', 'debug'}。

    顺序（与 categories.json['priority'] 对齐）：
      1) source_marker（整源/整站点标记者，整源归指定组）
      2) adult URL host 命中（域名级）
      3) [来源组名] 前缀整段剥离 + 归一化（normalize）；归一后再做关键词命中
         - 避免 "[SWAG]CCTV-1" 被 SWAG 关键词误判为成人；同时不丢成人命名「SWAG直播」之类
      4) adult name 命中（含 PORN_KW + 数字纯短名 + 括号成人标签 + 日期代号）
      5) cctv（含 CGTN/CETV，按 strict 任务定义只覆盖 1..17 编号主频道）
      6) gangtai（含 TVB/HK开电视/凤凰等；负面守卫过滤「翡翠湾」类误伤）
      7) lunbo（含轮播/循环/重播；排除「第N期/初舞台/回味」等综艺名）
      8) local（省/直辖市表 + 卫视等子级关键词；rtp/udp 组播强制归地方）
      9) live（兜底）
    """
    debug = {"matched_by": None, "raw": name, "url": url}
    if not name:
        return {"group": "live", "key": "", "canonical": "", "debug": debug}
    # 1) source_marker
    if source_marker:
        cat = _load_categories()
        sm = cat.get("source_marker", {}).get("map", {})
        grp = sm.get(source_marker)
        if grp:
            debug["matched_by"] = "source_marker"
            return {"group": grp, "key": normalize(name), "canonical": name.strip(), "debug": debug}
    # 2) URL host adult
    host = _host_of(url)
    if _host_is_adult(host):
        debug["matched_by"] = "adult_host"
        return {"group": "adult", "key": normalize(name), "canonical": name.strip(), "debug": debug}
    # 3) adult bracket_tag / date_code / pure_num（必须在 normalize 之前，否则【】会被剥掉）
    cat = _load_categories()
    c = _compiled()
    if c["adult_pure_num"].match(name.strip()):
        debug["matched_by"] = "adult_pure_num"
        return {"group": "adult", "key": normalize(name), "canonical": name.strip(), "debug": debug}
    if c["adult_bracket_tag"].match(name):
        debug["matched_by"] = "adult_bracket_tag"
        return {"group": "adult", "key": normalize(name), "canonical": name.strip(), "debug": debug}
    if c["adult_date_code"].match(name.lower().strip()):
        debug["matched_by"] = "adult_date_code"
        return {"group": "adult", "key": normalize(name), "canonical": name.strip(), "debug": debug}
    # 4) 归一化（剥 [来源组名] + 质量词 + 品牌后缀 + 繁简）
    norm_name = normalize(name, strip_quality=True, strip_brand=True)
    # 5) adult name（基于归一化结果；只在归一化后做关键词匹配，避免「[SWAG]CCTV-1」误判）
    pkw = [k.lower() for k in cat["adult"]["name_keywords"]]
    if any(k in norm_name for k in pkw):
        debug["matched_by"] = "adult_name"
        return {"group": "adult", "key": norm_name, "canonical": norm_name, "debug": debug}
    # 5) cctv
    canon = _cctv_match(name) or _cctv_match(norm_name)
    if canon:
        debug["matched_by"] = "cctv"
        return {"group": "cctv", "key": normalize(canon), "canonical": canon, "debug": debug}
    # 6) gangtai
    canon = _gangtai_match(name) or _gangtai_match(norm_name)
    if canon:
        debug["matched_by"] = "gangtai"
        return {"group": "gangtai", "key": normalize(canon), "canonical": canon, "debug": debug}
    # 7) lunbo
    canon = _lunbo_match(name) or _lunbo_match(norm_name)
    if canon:
        debug["matched_by"] = "lunbo"
        return {"group": "lunbo", "key": normalize(canon), "canonical": canon, "debug": debug}
    # 8) local
    prov = _local_match(name, url) or _local_match(norm_name, url)
    if prov:
        debug["matched_by"] = "local"
        return {"group": "local", "key": normalize(name), "canonical": name.strip(), "debug": debug}
    # 9) 兜底 live
    debug["matched_by"] = "live"
    return {"group": "live", "key": normalize(name), "canonical": name.strip(), "debug": debug}


if __name__ == "__main__":
    # 简易烟测
    for n, u in [
        ("[SWAG]CCTV-1 咪咕", "http://t7.cdn2020.com/1.m3u8"),
        ("央视一套", "rtp://239.10.0.1:8000"),
        ("TVB無綫新聞台", "https://rthklive1-lh.akamaihd.net/i/rthk31_1@167495/index_2052_av-b.m3u8"),
        ("凤凰卫视中文台", "https://example.com/phoenix.m3u8"),
        ("YY轮播", "http://example.com/yylb.m3u8"),
        ("湖南卫视", "https://example.com/hunan.m3u8"),
        ("麻豆传媒XXX", "http://vod.mycamtv.net/abc.m3u8"),
        ("乘风2026娜就聊姐姐第8期：循环回味初舞台", "http://example.com/xf.m3u8"),
        ("❌福建漳州六鳌翡翠湾", "http://example.com/feicuiwan.m3u8"),
    ]:
        r = classify(n, u)
        print(f"{n!r:50s} → {r['group']:8s} canon={r['canonical']!r:25s} by={r['debug']['matched_by']}")