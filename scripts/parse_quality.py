#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析接口质量排序（被 fetch_merge.py 在输出 parses 前调用）。

依据 probe/parses_probe.json 的探活结果对 tvbox.json parses 字段排序：
    响应速度（快 > 慢）> 返回格式规范（标准 json > 自定义格式）> 无广告标记 > 稳定性
优质解析排前面（TVBox 默认选第一个解析，直接影响用户首播放体验）；
失效解析（unreachable）排最后；ad_warn（广告解析）权重最低，仅高于失效。

无探活数据时（首次运行 / probe 文件缺失 / 解析接口不在上次探活名单）保持原有
相对顺序——不排序。所有异常由调用方 fetch_merge 用 try/except 包裹，不阻断每日构建。

用法（fetch_merge.py 内）：
    import parse_quality
    parses = parse_quality.rank_parses(parses)
"""
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE_PATH = os.path.join(REPO_ROOT, "probe", "parses_probe.json")


def normalize_parse_url(url: str) -> str:
    """与 probe_parses.normalize_parse_url 同语义（独立实现避免循环导入）。"""
    if not isinstance(url, str) or not url:
        return ""
    u = url.strip()
    if u in ("Web", "Demo"):
        return u
    low = u.lower()
    if low.startswith("http://"):
        u = "https://" + u[len("http://"):]
    elif not low.startswith("https://"):
        return u
    tail = u[len("https://"):]
    host, _, rest = tail.partition("/")
    host = host.lower()
    rest = rest.rstrip("/")
    return "https://" + host + ("/" + rest if rest else "")


def load_probe_results() -> dict:
    """读取 probe/parses_probe.json，返回 {norm_url: result}。

    文件缺失 / 损坏时返回空 dict（调用方据此保持原序）。
    """
    try:
        with open(PROBE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for r in (data.get("results") or []):
        if isinstance(r, dict):
            out[normalize_parse_url(r.get("url", ""))] = r
    return out


# 状态排序权重（越小越靠前）：
#   ok(可用) 0 < placeholder(Web/Demo) 1 < no_playable/anti_chain 2
#   < ad_warn(广告) 3 < unreachable(失效) 4
_STATUS_RANK = {
    "ok": 0,
    "placeholder": 1,
    "no_playable": 2,
    "anti_chain": 2,
    "ad_warn": 3,
    "unreachable": 4,
}


def _sort_key(item: dict, probe: dict) -> tuple:
    """返回 (status_rank, ms, type_pref) 三元组，越小越靠前。"""
    status = (probe or {}).get("status", "")
    rank = _STATUS_RANK.get(status, 2)  # 无探活记录 → 中性 2
    ms = (probe or {}).get("ms") or 999999
    # type=1（JSON 解析）返回格式更规范，优先于 type=0（web 解析）
    type_pref = 0 if item.get("type") == 1 else 1
    return (rank, ms, type_pref)


def rank_parses(parses: list) -> list:
    """按质量分重排 parses。无探活数据时原样返回（稳定排序）。

    parses: list[dict]，每个含 name/type/url。
    返回新 list，不修改入参。
    """
    probe = load_probe_results()
    if not probe:
        return list(parses)
    indexed = list(enumerate(parses))
    indexed.sort(key=lambda t: (_sort_key(t[1], probe.get(normalize_parse_url(t[1].get("url", "")))),
                                t[0]))
    return [p for _, p in indexed]


def dedup_parses_safe(parses: list) -> list:
    """best-effort 去重：按规范化 URL 合并，保留首个出现项。

    与 probe_parses.dedup_parses 语义一致；这里无探活数据时保留首项。
    任何异常由调用方捕获。fetch_merge 可在 rank 前调用。
    """
    seen = set()
    out = []
    for p in parses:
        if not isinstance(p, dict):
            continue
        key = normalize_parse_url(p.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


if __name__ == "__main__":
    # 自检：加载 probe 结果统计
    probe = load_probe_results()
    print(json.dumps({"probe_entries": len(probe),
                      "status_breakdown": _STATUS_RANK},
                     ensure_ascii=False, indent=2))
