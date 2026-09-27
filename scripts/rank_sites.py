#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""站点排序与分组：按「分类 → 搜索可用性 → 实测速度」重排 sites。

现状问题
--------
合并后的 tvbox.json 里 1222 个站点既没有 group 字段，顺序也完全跟着上游清单走：
打开就是一堆乱序，前几条甚至可能是死站；上游自报的 searchable 同样不可靠
（实测发现标了可搜却搜不出结果的站不少）。

本模块做三件事
--------------
  1. 分类 给每个站点写 group：采集站 / 直连点播 / 蜘蛛源 / 本地JS / 网盘 / 短剧 / 成人
  2. 搜索 用探针实测结论校正 searchable —— 搜不出来的标 0，客户端搜索时会跳过，
          直接减少无效请求（这是对搜索体感最直接的优化）
  3. 速度 按实测延迟升序，快的在前

最终 sites 数组顺序 = 分类块 → 块内「实测可搜 > 未知 > 不可搜」→ 延迟升序 → 名称。

用法
----
    python scripts/rank_sites.py                    # 产出 tvbox.ranked.json 并打印报告
    python scripts/rank_sites.py --in-place         # 直接改写 tvbox.json
    python scripts/rank_sites.py --probe probe/sites_probe.json
    # drpy Node 沙箱实测（type=3 本地 JS 源）通过 --drpy-probe 接入：
    python scripts/rank_sites.py --drpy-probe probe/drpy_probe.json
"""

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 分类与关键词复用主流程，避免两套标准打架
try:
    from fetch_merge import (ADULT_KEYWORDS, CMS_API_RE, PAN_EXT_RE, PAN_KEY_RE,  # noqa: PLC0415
                             PAN_NAME_RE, SHORT_KEYWORDS)
except ImportError:  # 独立运行且主流程不可用时的兜底
    SHORT_KEYWORDS = ["短剧", "微短剧", "duanju"]
    ADULT_KEYWORDS = ["成人", "18+", "jav", "麻豆"]
    CMS_API_RE = re.compile(r"api\.php|provide/vod|inc/api|atas\.php", re.I)
    PAN_KEY_RE = PAN_NAME_RE = PAN_EXT_RE = re.compile(r"网盘|夸克|阿里云|pan|quark", re.I)

# 分组即「分类维度」，数组顺序按此排列；序号决定客户端里分组的先后
GROUP_ORDER = ["采集站", "直连点播", "蜘蛛源", "本地JS", "网盘", "短剧", "成人", "其他"]
UNKNOWN_LATENCY = 99999
# 实测产物的时效上限（天）：csp 真机靠手工产出、无法在 CI 跑，超过这个天数就不再作为
# 排序依据——否则等于拿很久以前的结论给今天的源排位（源站天天在变）。
# drpy 沙箱已接入 CI 每日更新，一般不受影响。
STALE_DAYS = int(os.environ.get("PROBE_STALE_DAYS", "7"))

# ==================== 加权综合分排序（P1，docs/ranking-scoring.md） ====================
# 综合分公式：score = w1*avail_rank_inv + w2*latency_norm + w3*stability
#                  + w4*richness + w5*freshness + w6*group_confidence
# 各维全部归一化到 [0,1]，权重可经环境变量 RANK_WEIGHTS 调整（无需改代码）。
# 默认权重（docs/ranking-scoring.md 7.2）：可用性优先，其次稳定性/速度/丰富度。
DIM_ORDER = ("avail", "latency", "stability", "richness", "freshness", "group")
DEFAULT_WEIGHTS = {
    "avail": 0.30, "latency": 0.15, "stability": 0.20,
    "richness": 0.15, "freshness": 0.10, "group": 0.10,
}


def parse_weights(env: str = None) -> dict:
    """解析 RANK_WEIGHTS 环境变量。

    两种格式：
      * 命名式："avail=0.30,latency=0.15,..."（按名覆盖）
      * 顺序式："0.30,0.15,0.20,0.15,0.10,0.10"（按 DIM_ORDER 顺序）
    缺省项用内置默认；非法输入一律回退默认（绝不因调参串让排序崩）。
    """
    w = dict(DEFAULT_WEIGHTS)
    raw = (env if env is not None else os.environ.get("RANK_WEIGHTS", "")).strip()
    if not raw:
        return w
    try:
        if "=" in raw:
            for part in raw.split(","):
                k, _, v = part.partition("=")
                k = k.strip().lower()
                if k in w:
                    w[k] = float(v)
        else:
            vals = [float(x) for x in raw.split(",") if x.strip()]
            if len(vals) == len(DIM_ORDER):
                for k, v in zip(DIM_ORDER, vals):
                    w[k] = v
    except (ValueError, AttributeError):
        return dict(DEFAULT_WEIGHTS)
    return w


def use_legacy() -> bool:
    """是否回退旧 tuple 排序：--legacy 标志或 RANK_LEGACY=1。"""
    return os.environ.get("RANK_LEGACY", "") == "1"


def stale_days(doc: dict) -> float:
    """产物距今天数。解析不出时返回 0（视为新鲜，不改变既有行为）。"""
    g = (doc or {}).get("generated_at") or ""
    if not g:
        return 0.0
    try:
        s = str(g).replace("T", " ").strip()
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - dt).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return 0.0


def _text_of(site: dict) -> str:
    ext = site.get("ext")
    ext_str = ext if isinstance(ext, str) else (json.dumps(ext, ensure_ascii=False) if isinstance(ext, dict) else "")
    return f"{site.get('name') or ''} {site.get('key') or ''} {site.get('api') or ''} {ext_str}".lower()


CATEGORY_ORDER = ["电影", "剧", "综艺", "动漫", "纪录片", "体育", "少儿", "综合"]
# 这些类型本身即独立通道，不再与品类复合（短剧/成人有独立产物，其他保持兜底）
SPECIAL_TYPES = {"短剧", "成人", "其他"}


def load_category_vocab(repo: str) -> dict:
    """config/category_vocab.json：{品类: [关键词]}。缺失/损坏返回中性空表（全归综合）。"""
    doc = _load_json(repo, "config/category_vocab.json")
    vocab = {c: [] for c in CATEGORY_ORDER}
    for k, v in (doc or {}).items():
        if k in vocab and isinstance(v, list):
            vocab[k] = [str(x) for x in v]
    return vocab


def category_of(site: dict, vocab: dict) -> str:
    """从站点 name/ext 提取内容品类（电影/剧/综艺/...），未命中归「综合」。"""
    if not isinstance(site, dict):
        return "综合"
    name = site.get("name") or ""
    ext = site.get("ext")
    ext_str = ext if isinstance(ext, str) else (json.dumps(ext, ensure_ascii=False) if isinstance(ext, dict) else "")
    text = f"{name} {ext_str}".lower()
    for cat in CATEGORY_ORDER:
        if cat == "综合":
            continue
        kws = vocab.get(cat) or []
        if any(kw and kw.lower() in text for kw in kws):
            return cat
    return "综合"


def type_of(site: dict) -> str:
    """把一个站点归入「类型」分组（采集站/直连点播/蜘蛛源/本地JS/网盘/短剧/成人/其他）。"""
    api = site.get("api") if isinstance(site.get("api"), str) else ""
    text = _text_of(site)
    if any(kw.lower() in text for kw in SHORT_KEYWORDS):
        return "短剧"
    if any(kw.lower() in text for kw in ADULT_KEYWORDS):
        return "成人"
    if PAN_KEY_RE.search(text) or PAN_NAME_RE.search(text) or PAN_EXT_RE.search(text):
        return "网盘"
    if site.get("type") in (0, 1):
        return "采集站" if CMS_API_RE.search(api) else "直连点播"
    if api.startswith("csp_"):
        return "蜘蛛源"
    if api.startswith("./"):
        return "本地JS"
    return "其他"


def group_of(site: dict, vocab: dict = None, legacy_group: bool = False) -> str:
    """产出客户端 group 字段。

    默认复合名："<品类>-<类型>"（如 电影-采集站）；短剧/成人/其他不复合。
    legacy_group=True 时回退扁平类型名（--legacy-group 回滚）。"""
    typ = type_of(site)
    if legacy_group or typ in SPECIAL_TYPES:
        return typ
    return f"{category_of(site, vocab or {})}-{typ}"


def group_sort_key(group: str):
    """组块排序键 (类型序, 品类序)。扁平/特殊组品类序为 0。"""
    if not group or "-" not in group:
        ti = GROUP_ORDER.index(group) if group in GROUP_ORDER else len(GROUP_ORDER)
        return (ti, 0)
    cat, _, typ = group.partition("-")
    ti = GROUP_ORDER.index(typ) if typ in GROUP_ORDER else len(GROUP_ORDER)
    ci = CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else len(CATEGORY_ORDER)
    return (ti, ci)


def search_verdict(site: dict, probe: dict, js_probe: dict = None, csp_probe: dict = None,
                  drpy_probe: dict = None):
    """用实测结论判断「能不能搜」。返回 1 / 0 / None(不可测，保持上游自报值)。"""
    if probe:
        level = probe.get("level")
        l2 = probe.get("l2") or {}
        if l2.get("ok"):
            return 1
        if level == "L?" or l2.get("cls") == "env":
            return None                      # 本机网络不通，无法判定，不动上游标注
        if level in ("L1", "L2", "L3"):
            return 0                         # 接口活着但搜索确实无命中
    key = site.get("key") if isinstance(site, dict) else None
    # drpy Node 沙箱五关实测：比 js 连通性更深，优先于 js_probe
    dp = (drpy_probe or {}).get(key)
    if dp:
        lv = dp.get("level")
        if lv in ("D3", "D4", "D5"):
            return 1                         # 热词实测确实搜到了片
        if lv == "D2":
            return 0                         # 分类通、但搜索专门测过却无命中，结论可信
        return None                          # D0/D1/D? 证据不足，不妄改上游标注
    jp = (js_probe or {}).get(key)
    if jp:
        if str(jp.get("searchable_rule")) == "0":
            return 0                         # 规则自己声明不支持搜索，这个信号可信
        ss = jp.get("search_signal")
        # 只有分类页已验证通过（S2/S3）时，搜索页的实测结论才可信；
        # 其余情况保持上游标注——宁可留着让客户端去试，也不误标成搜不到
        if jp.get("level") in ("S2", "S3") and isinstance(ss, int):
            return 1 if ss >= 1 else 0
        return None
    cp = (csp_probe or {}).get(key)
    if cp:
        lv = cp.get("level")
        if lv in ("C0", "C?"):
            return None                      # 加载失败/超时：无从判断，不妄改
        if cp.get("flags", {}).get("search") is True:
            return 1
        # 搜索关在宿主里是无条件执行的，所以 C1~C5 的「搜不到」是可信结论
        if lv in ("C1", "C2", "C3", "C4", "C5"):
            return 0
        return None
    return None                              # 证据不足，不妄改上游标注


def latency_of(probe: dict):
    l1 = (probe or {}).get("l1") or {}
    ms = l1.get("ms")
    return ms if isinstance(ms, int) and ms > 0 else UNKNOWN_LATENCY


def fresh_check_ms(probe: dict) -> int:
    """验活实测的「取到内容耗时」（check_ms，fetch_merge [3/6] 并入）。

    只认 STALE_DAYS 内的记录——这是当天验活时拿到的有效配置正文耗时（含
    DNS/建连/正文读取），比旧的 l1 探针更贴近今天的真实速度；过期则返回 0。
    """
    ms = (probe or {}).get("check_ms")
    at = (probe or {}).get("check_at") or ""
    if not (isinstance(ms, int) and ms > 0 and at):
        return 0
    try:
        dt = datetime.strptime(str(at).replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")
        if (datetime.now() - dt).total_seconds() > STALE_DAYS * 86400:
            return 0
    except (ValueError, TypeError):
        return 0
    return ms


def speed_of(key, probe_map: dict, spider_map: dict, js_map: dict = None, csp_map: dict = None,
             drpy_map: dict = None):
    """速度取值：HTTP 采集接口 > 真机 csp 实测 > JS 分类页实测 > drpy 五关实测 > type3 连通性。"""
    p = probe_map.get(key)
    if p:
        if p.get("level") == "L?":
            return UNKNOWN_LATENCY, "本机不可达"
        # 当天验活的「取到内容耗时」优先——比旧 l1 探针更贴近今天的真实速度
        ck = fresh_check_ms(p)
        if ck:
            return ck, "验活实测"
        ms = latency_of(p)
        if ms < UNKNOWN_LATENCY:
            return ms, "http实测"
    cp = (csp_map or {}).get(key)
    if cp:
        lv = cp.get("level")
        if lv in ("C0", "C?"):
            return UNKNOWN_LATENCY, "csp未通过"
        ms = cp.get("ms")
        if isinstance(ms, int) and ms > 0:
            return ms, "csp实测"
    jp = (js_map or {}).get(key)
    if jp:
        if jp.get("level") == "S?":
            return UNKNOWN_LATENCY, "js本机不可达"
        ms = jp.get("cat_ms")
        if isinstance(ms, int) and ms > 0:
            return ms, "js实测"
    dp = (drpy_map or {}).get(key)
    if dp:
        lv = dp.get("level")
        if lv in ("D0", "D?"):
            return UNKNOWN_LATENCY, "drpy未通过"
        # ms 是五关累计耗时（比单关粗），作为 drpy 源的速度代理
        ms = dp.get("ms")
        if isinstance(ms, int) and ms > 0:
            return ms, "drpy实测"
    sp = spider_map.get(key)
    if sp:
        if sp.get("ok") and isinstance(sp.get("ms"), int):
            return sp["ms"], "spider实测"
        return UNKNOWN_LATENCY, "不可达"
    return UNKNOWN_LATENCY, "未测"


def struct_score(site: dict, spider_map: dict, js_map: dict = None, csp_map: dict = None,
                 drpy_map: dict = None) -> int:
    """无实测速度时的替代质量信号（0 最差 / 3 最好）。

    有真机/半动态评级的直接用评级；其余按结构判断：
    规则文件缺失 = 加载即失败的死源，必须沉底；有 ext 配置的比两手空空的强。
    """
    if not isinstance(site, dict):
        return 0
    key = site.get("key")
    cp = (csp_map or {}).get(key)
    if cp:
        return {"C5": 3, "C4": 3, "C3": 2, "C2": 2, "C1": 1, "C?": 1}.get(cp.get("level"), 0)
    jp = (js_map or {}).get(key)
    if jp:
        return {"S3": 3, "S2": 3, "S1": 1, "S?": 1}.get(jp.get("level"), 0)
    dp = (drpy_map or {}).get(key)
    if dp:
        return {"D5": 3, "D4": 3, "D3": 2, "D2": 2, "D1": 1}.get(dp.get("level"), 0)
    sp = spider_map.get(key)
    if sp:
        if sp.get("reason") == "js 规则文件缺失":
            return 0
        if sp.get("from"):
            return 3 if sp.get("ok") else 1
    return 2 if site.get("ext") else 1


def avail_rank(site: dict, probe_map: dict, spider_map: dict,
               js_map: dict = None, csp_map: dict = None, drpy_map: dict = None) -> int:
    """可用性档位（0 最好 / 5 最差），让「实测更可用」的源在同组内排前面。

    用户要的是「分类 → 搜索 → 速度」，但速度不该凌驾于可用性：
    一个五关全通、2.2 秒的源，显然该排在一个只能搜到结果、0.8 秒的源前面。
    所以插一层档位：真机五关 > 真机搜索/分类 > 仅首页 > 仅连通 > 未测 > 实测失败。
    """
    key = site.get("key") if isinstance(site, dict) else None
    if not key:
        return 5
    cp = (csp_map or {}).get(key)
    if cp:
        return {"C5": 0, "C4": 0, "C3": 1, "C2": 1, "C1": 2}.get(cp.get("level"), 5)
    p = probe_map.get(key)
    if p:
        return {"L3": 0, "L2": 1, "L1": 2}.get(p.get("level"), 5)
    jp = (js_map or {}).get(key)
    if jp:
        return {"S3": 0, "S2": 1, "S1": 2}.get(jp.get("level"), 5)
    dp = (drpy_map or {}).get(key)
    if dp:
        return {"D5": 0, "D4": 0, "D3": 1, "D2": 1, "D1": 2}.get(dp.get("level"), 5)
    sp = spider_map.get(key)
    if sp and sp.get("ok"):
        return 3
    return 4                                  # 未测：中性，排在「仅连通」之后、「实测失败」之前


def load_stability(repo: str) -> dict:
    """从 state/tvbox.db 的 checks 表读取近 7 天成功率，作为稳定性信号。

    返回 {key: success_rate(0~1)}；db 缺失/损坏/为空一律返回 {}（优雅降级，
    综合分里该维取中性 0.5，不报错不阻断）。
    """
    import sqlite3  # 纯标准库，惰性导入
    db = os.path.join(repo, "state", "tvbox.db")
    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        agg = {}
        for r in conn.execute(
                "SELECT key, ok FROM checks WHERE checked_at >= ?", (cutoff,)):
            a = agg.setdefault(r["key"], {"ok": 0, "n": 0})
            a["n"] += 1
            if r["ok"]:
                a["ok"] += 1
        conn.close()
        return {k: (v["ok"] / v["n"] if v["n"] else 0.0) for k, v in agg.items()}
    except Exception as e:  # db 不可用：优雅降级
        print(f"[rank] tvbox.db 不可用，跳过稳定性维度（{e}）", flush=True)
        return {}


def richness_hits(key, pmap: dict, dmap: dict) -> int:
    """内容丰富度原始信号：探针 L2 搜索命中数 / drpy D3+ 命中数取较大者。

    无命中数据返回 -1（综合分里取中性 0.5，不惩罚新源）。"""
    hits = -1
    p = pmap.get(key) if key else None
    if p and isinstance(p.get("l2"), dict):
        h = p["l2"].get("hits")
        if isinstance(h, int) and h >= 0:
            hits = h
    dp = (dmap or {}).get(key) if key else None
    if dp:
        dh = dp.get("hits")
        if isinstance(dh, int) and dh > hits:
            hits = dh
    return hits


def group_conf(site: dict) -> float:
    """粗粒度分类置信度（0.5 低 / 1.0 高），作为综合分的 group 维。

    强结构信号（csp_ 协议前缀 / 本地 .js 规则 / type0-1 命中 CMS 接口 / 多盘正则）
    视为高置信；其余视为中性偏低。"""
    if not isinstance(site, dict):
        return 0.5
    api = site.get("api") if isinstance(site.get("api"), str) else ""
    if api.startswith("csp_"):
        return 1.0
    if api.startswith("./") and api.endswith(".js"):
        return 1.0
    if site.get("type") in (0, 1) and CMS_API_RE.search(api):
        return 1.0
    text = _text_of(site)
    pan_hits = sum(1 for rx in (PAN_KEY_RE, PAN_NAME_RE, PAN_EXT_RE) if rx.search(text))
    if pan_hits >= 2:
        return 1.0
    return 0.5


def rank_sites(sites: list, probe_doc: dict, spider_doc: dict = None,
               mirror_drops: set = None, js_doc: dict = None, csp_doc: dict = None,
               drpy_doc: dict = None, stab_map: dict = None, legacy: bool = False,
               vocab: dict = None, legacy_group: bool = False):
    """重排站点并回写 group / searchable。返回 (新列表, 统计)。

    legacy=True 走旧 tuple 排序（回滚）；否则走加权综合分排序。"""
    def _map(doc):
        out = {}
        for r in (doc or {}).get("sites", []):
            if isinstance(r, dict) and r.get("key"):
                out[r["key"]] = r
        return out

    pmap, smap = _map(probe_doc), _map(spider_doc)
    jmap, cmap, dmap = _map(js_doc), _map(csp_doc), _map(drpy_doc)

    # 时效闸门：产物过旧就不参与排序，避免用陈旧结论给今天的源排位
    if stale_days(csp_doc) > STALE_DAYS:
        print(f"[rank] csp 实测产物已 {stale_days(csp_doc):.0f} 天未更新（>{STALE_DAYS}），本轮不参与排序",
              flush=True)
        cmap = {}
    if stale_days(drpy_doc) > STALE_DAYS:
        print(f"[rank] drpy 实测产物已 {stale_days(drpy_doc):.0f} 天未更新（>{STALE_DAYS}），本轮不参与排序",
              flush=True)
        dmap = {}
    drops = mirror_drops or set()

    enriched = []
    stats = Counter()
    for s in sites:
        if not isinstance(s, dict):
            enriched.append(s)
            continue
        key = s.get("key")
        if key in drops:                     # 同库镜像：只留可用性最好的一份
            stats["mirror_skipped"] += 1
            continue
        probe = pmap.get(key)
        group = group_of(s, vocab, legacy_group)
        verdict = search_verdict(s, probe, jmap, cmap, dmap)

        s = dict(s)
        s["group"] = group
        if verdict is not None:
            before = str(s.get("searchable"))
            s["searchable"] = verdict
            stats[f"searchable:{before}->{verdict}"] += 1
        _, lat_src = speed_of(key, pmap, smap, jmap, cmap, dmap)
        stats[f"speed:{lat_src}"] += 1
        stats[f"group:{group}"] += 1
        if verdict == 1:
            stats[f"searchable_ok:{group}"] += 1
        # drpy 沙箱实测统计
        dp = dmap.get(key)
        if dp:
            stats["drpy_total"] += 1
            if verdict == 1:
                stats["drpy_searchable"] += 1
            lv = dp.get("level")
            if lv == "D5":
                stats["drpy_D5"] += 1
            if lv in ("D3", "D4", "D5"):
                stats["drpy_D3p"] += 1
        enriched.append(s)

    def _key_legacy(s):
        key = s.get("key") if isinstance(s, dict) else None
        lat, _ = speed_of(key, pmap, smap, jmap, cmap, dmap) if key else (UNKNOWN_LATENCY, "")
        if lat >= UNKNOWN_LATENCY:
            # 没测到速度的，用结构/评级兜底排序（死源沉底），不让未测的源纯按名字乱排
            lat = UNKNOWN_LATENCY + (3 - struct_score(s, smap, jmap, cmap, dmap)) * 1000
        group = s.get("group") if isinstance(s, dict) else None
        return (group_sort_key(group),
                0 if s.get("searchable") == 1 else (1 if s.get("searchable") is None else 2),
                avail_rank(s, pmap, smap, jmap, cmap, dmap),
                lat,
                str(s.get("name") or "") if isinstance(s, dict) else "")

    if legacy:
        enriched.sort(key=_key_legacy)
        return enriched, stats

    # ---- 加权综合分排序：组块外排，组内按综合分（docs/ranking-scoring.md）----
    weights = parse_weights()
    raw = []
    known_lats, known_hits = [], []
    for s in enriched:
        if not isinstance(s, dict):
            raw.append((s, None))
            continue
        key = s.get("key")
        lat, _ = speed_of(key, pmap, smap, jmap, cmap, dmap) if key else (UNKNOWN_LATENCY, "")
        ar = avail_rank(s, pmap, smap, jmap, cmap, dmap)
        hits = richness_hits(key, pmap, dmap)
        stab = (stab_map or {}).get(key)
        if lat < UNKNOWN_LATENCY:
            known_lats.append(lat)
        if hits >= 0:
            known_hits.append(hits)
        raw.append((s, (lat, ar, hits, stab, key)))

    if known_lats:
        lmin_l = math.log10(min(known_lats))
        lmax_l = math.log10(max(known_lats))
        lspan = (lmax_l - lmin_l) or 1.0
    else:
        lmin_l = None
        lspan = 1.0
    maxh = max(known_hits) if known_hits else 0

    def _lat_norm(ms):
        if lmin_l is None:
            return 0.5
        if ms >= UNKNOWN_LATENCY:
            return 0.0
        v = (math.log10(ms) - lmin_l) / lspan
        return max(0.0, min(1.0, 1.0 - v))

    def _rich_norm(h):
        if h < 0:
            return 0.5
        if maxh <= 0:
            return 0.5
        return min(1.0, math.log10(h + 1) / math.log10(maxh + 1))

    scores = {}
    for s, sig in raw:
        if sig is None:
            scores[id(s)] = -1e9
            continue
        lat, ar, hits, stab, key = sig
        avail_inv = 1.0 - ar / 5.0
        stab_v = 0.5 if stab is None else max(0.0, min(1.0, float(stab)))
        fresh = 1.0 if fresh_check_ms(pmap.get(key) or {}) else 0.5
        scores[id(s)] = (weights["avail"] * avail_inv
                         + weights["latency"] * _lat_norm(lat)
                         + weights["stability"] * stab_v
                         + weights["richness"] * _rich_norm(hits)
                         + weights["freshness"] * fresh
                         + weights["group"] * group_conf(s))

    def _key_score(s):
        if not isinstance(s, dict):
            return (len(GROUP_ORDER), 2, 1e9, "")
        group = s.get("group")
        gidx = group_sort_key(group)
        sp = s.get("searchable")
        spref = 0 if sp == 1 else (1 if sp is None else 2)
        return (gidx, -scores.get(id(s), 0.0), spref, str(s.get("name") or ""))

    enriched.sort(key=_key_score)
    return enriched, stats


def print_report(sites: list, stats: Counter):
    print("分类分布（按数组实际顺序）:")
    seen = Counter()
    for s in sites:
        seen[s.get("group")] += 1
    order = []
    for s2 in sites:
        g2 = s2.get("group") if isinstance(s2, dict) else None
        if g2 and g2 not in order:
            order.append(g2)
    for g in order:
        n = seen.get(g)
        ok = stats.get(f"searchable_ok:{g}", 0)
        print(f"  {g:14} {n:6d} 个 | 实测可搜 {ok:5d} 个")
    speed = {k.split(":", 1)[1]: v for k, v in stats.items() if k.startswith("speed:")}
    print("速度数据来源:", speed)
    print("searchable 修正:", {k.split(":", 1)[1]: v for k, v in stats.items() if k.startswith("searchable:")})
    if stats.get("drpy_total"):
        print(f"drpy Node 沙箱实测: {stats['drpy_total']} 个 | 可搜 {stats.get('drpy_searchable', 0)} "
              f"| D5 {stats.get('drpy_D5', 0)} | D3+ {stats.get('drpy_D3p', 0)}")
    if stats.get("mirror_skipped"):
        print(f"同库镜像已剔除: {stats['mirror_skipped']} 个")


def _load_json(repo, rel):
    p = os.path.join(repo, rel)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="tvbox.json")
    ap.add_argument("--probe", default="probe/sites_probe.json")
    ap.add_argument("--spider-probe", default="probe/spider_probe.json")
    ap.add_argument("--js-probe", default="probe/js_probe.json")
    ap.add_argument("--csp-probe", default="probe/csp_probe.json")
    ap.add_argument("--drpy-probe", default="probe/drpy_probe.json")
    ap.add_argument("--mirror-groups", default="state/mirror_groups.json")
    ap.add_argument("--keep-mirrors", action="store_true", help="保留同库镜像站点（默认剔除）")
    ap.add_argument("--out", default="tvbox.ranked.json")
    ap.add_argument("--in-place", action="store_true", help="直接改写 --input")
    ap.add_argument("--legacy", action="store_true", help="回退旧 tuple 排序（默认加权综合分）")
    ap.add_argument("--legacy-group", action="store_true", help="回退扁平类型 group（默认品类-类型复合名）")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    src = os.path.join(repo, args.input)
    with open(src, encoding="utf-8") as f:
        doc = json.load(f)

    probe_doc = _load_json(repo, args.probe)
    if not probe_doc:
        print(f"[rank] 未找到探针产物 {args.probe}，搜索可用性维度将缺失", flush=True)
    spider_doc = _load_json(repo, args.spider_probe)
    if not spider_doc:
        print(f"[rank] 未找到 spider 探针 {args.spider_probe}，type 3 站点将无速度数据", flush=True)
    js_doc = _load_json(repo, args.js_probe)
    csp_doc = _load_json(repo, args.csp_probe)
    if csp_doc:
        print(f"[rank] 加载真机 csp 实测 {len(csp_doc.get('sites') or [])} 条"
              f"（{csp_doc.get('summary', {}).get('levels')}）", flush=True)
    drpy_doc = _load_json(repo, args.drpy_probe)
    if drpy_doc:
        print(f"[rank] 加载 drpy Node 沙箱实测 {len(drpy_doc.get('sites') or [])} 条"
              f"（{drpy_doc.get('summary', {}).get('levels')}）", flush=True)

    mirror_drops = set()
    if not args.keep_mirrors:
        mg = _load_json(repo, args.mirror_groups)
        mirror_drops = set(mg.get("drop_keys") or [])
        if mirror_drops:
            print(f"[rank] 将剔除 {len(mirror_drops)} 个同库镜像站点（--keep-mirrors 可保留）", flush=True)

    sites = doc.get("sites") or []
    legacy = args.legacy or use_legacy()
    legacy_group = args.legacy_group or os.environ.get("LEGACY_GROUP", "") == "1"
    vocab = load_category_vocab(repo)
    stab_map = load_stability(repo) if not legacy else {}
    if stab_map:
        print(f"[rank] 加载稳定性记录 {len(stab_map)} 个源（近7天 checks）", flush=True)
    if legacy:
        print("[rank] 使用旧 tuple 排序（--legacy / RANK_LEGACY=1）", flush=True)
    else:
        print(f"[rank] 加权综合分排序，权重={parse_weights()}", flush=True)
    print(f"[rank] group 模式: {'扁平类型' if legacy_group else '品类-类型复合'}", flush=True)
    ranked, stats = rank_sites(sites, probe_doc, spider_doc, mirror_drops, js_doc, csp_doc, drpy_doc,
                               stab_map=stab_map, legacy=legacy, vocab=vocab, legacy_group=legacy_group)
    doc["sites"] = ranked

    dst = src if args.in_place else os.path.join(repo, args.out)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print_report(ranked, stats)
    print(f"[rank] 站点 {len(sites)} 个已重排 -> {os.path.relpath(dst, repo)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
