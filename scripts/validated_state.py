#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validated_state.py — validated.json 单一事实源（TVBox P1-A 双线职责收敛）。

背景（P1-A 任务 #7689407877773053122）：
  GitHub 发现验证线（daily-fetch 03:00 + validate/live-validate/radar）与
  飞书每日巡检线（05:00）此前各持一套验证状态（state/upstreams_state.json、
  state/sites_state.json vs 飞书线 workdir 的 retest_*/list_* prev 链），
  是 P0 期间门禁口径漂移 / 词表不同步的架构根因。
  本模块把两线收敛到唯一事实源文件 **state/validated.json**：
  - GitHub 线经 fetch_merge.load_state/save_state 读写 `sources` 段，
    经 load_site_state/save_site_state 读写 `sites` 段；
  - 飞书线经 scripts/feishu_patrol_bridge.py 读本文件取 prev 状态、
    把当日复测结果合并回写（不再自建 prev_list 链）；
  - 两线接口键 = 规范键 canonical_key(url)（第 0 层去重同源），name 作为兼容别名。

文件布局（tvbox.validated/1）：
  {
    "schema": "tvbox.validated/1",
    "updated_at": "...",
    "policy": { 阈值与衰减策略（与 rules/gate_criteria.json 同源声明） },
    "sources": { "<上游名>": {name,url,ckey,fail_count,disabled,level,history,decay,...} },
    "sites":   { "<站点名>": {...站点验活历史（原 sites_state 形态）} }
  }

跨日衰减（第 4 层去重，apply_decay）：
  - not_pass = history 中非 fully/partially 的任何档位（unavailable/not-parsable/drift 等，同计 streak）；
  - disabled（fail-limit 连续 3 次不达标停用）条目即时 stage=out（decayed=true；通过仍可复位回捞）；
  - 未停用条目：连续 not_pass 天数 >= watch_after_days(3) → stage=watch：保留状态但默认排除出聚合/分发产物；
    连续 not_pass 天数 >= out_after_days(7) → stage=out：标记 decayed=true 归档淘汰（条目留档可审计）；
  - 任一日通过（fully/partially）即复位 streak 与 stage（自动回捞）。

本模块 stdlib only。
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))

VALIDATED_FILE = os.environ.get("VALIDATED_FILE", "state/validated.json")
SCHEMA = "tvbox.validated/1"
HISTORY_MAX_DAYS = 14

# 聚合代理前缀（与飞书线 sources_collect.PROXIES 同口径；此处为仓库内单一定义，
# 飞书线自 P1-A 起从本模块导入，不再自持副本）
PROXIES = [
    'https://ghproxy.net/https://', 'https://gh-proxy.com/https://',
    'https://gh-proxy.com/', 'https://github.moeyy.xyz/https://',
    'https://ghp.ci/https://', 'https://hub.gitmirror.com/https://',
    'https://mirror.ghproxy.com/https://', 'https://gh.con.sh/https://',
    'https://gitdl.cn/https://', 'https://g.3344550.xyz/https://',
    'https://ghproxy.net/',
]

DEFAULT_POLICY = {
    "upstream_fail_limit": 3,
    "site_fail_limit": 3,
    "probe_interval_days": 7,
    "decay": {
        "watch_after_days": 3,
        "out_after_days": 7,
        "not_pass_levels": ["unavailable"],
        "not_pass_levels_note": "凡非 fully/partially 的档位（not-parsable/drift 等）同计 streak",
        "note": "disabled（fail-limit 停用）即时 out；未停用条目按连续 N 日 not_pass 衰减："
                "watch=默认排除出聚合/分发产物；out=归档淘汰（decayed=true）不进任何产物；任一日通过即复位回捞",
    },
}

# 飞书线五级/三档判级 → 内部统一档位
LEVEL_ALIASES = {
    "fully_available": "fully",
    "fully": "fully",
    "partially_available": "partially",
    "partially": "partially",
    "unavailable": "unavailable",
}


# ---------------- 规范键（第 0 层去重与双线接口键共用同一实现） ----------------

def strip_proxy(url: str) -> str:
    """剥聚合代理前缀 → 原始 URL（大小写不敏感）。"""
    u = (url or "").strip()
    low = u.lower()
    for p in PROXIES:
        if low.startswith(p.lower()):
            rest = u[len(p):]
            if not rest.startswith("http"):
                rest = "https://" + rest
            return strip_proxy(rest)  # 递归剥多层代理嵌套
    return u


def canonical_key(url) -> str:
    """源站点 URL 规范键：代理剥离 + scheme 归一 + host 小写去 www + 默认端口去除
    + fragment 去除 + 尾斜杠去除。query 保留（部分接口以 query 区分）。
    不可解析/非字符串返回原值小写尾斜杠规整。"""
    if not isinstance(url, str) or not url.strip():
        return url if not isinstance(url, str) else ""
    u = strip_proxy(url)
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)([^#]*)?(?:#.*)?$", u)
    if not m:
        return u.lower().rstrip("/")
    authority, path = m.group(1), (m.group(2) or "")
    if "@" in authority:
        userinfo, hostport = authority.rsplit("@", 1)
    else:
        userinfo, hostport = "", authority
    host, port = hostport, ""
    mm = re.match(r"^(\[[^\]]+\]|[^:]+)(:(\d+))?$", hostport)
    if mm:
        host = mm.group(1)
        port = mm.group(3) or ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    if port in ("80", "443") or port == "":
        port_part = ""
    else:
        port_part = ":" + port
    path = path.rstrip("/")
    return host + port_part + (userinfo + "@" if userinfo else "") + path


def _norm_vocab():
    """载入 state/vocab/normalization.json 的繁简/全角/前缀规则（单一定义）。
    缺失时返回 None，调用方退化为基础归一。"""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "state", "vocab", "normalization.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


_VOCAB = None
_VOCAB_TRIED = False


def _vocab():
    global _VOCAB, _VOCAB_TRIED
    if not _VOCAB_TRIED:
        _VOCAB_TRIED = True
        _VOCAB = _norm_vocab()
    return _VOCAB


def normalize_name(name) -> str:
    """频道/站点名规范键：分组前缀剥离 + 全角转半角 + 繁转简 + 小写 + 去空白/分隔符。
    规则来自 state/vocab/normalization.json（研发1号词表，单一定义源）。"""
    if not isinstance(name, str):
        return "" if name is None else str(name)
    s = name
    v = _vocab()
    if v:
        for pat in v.get("strip_group_prefix_patterns", []):
            try:
                s = re.sub(pat, "", s)
            except re.error:
                pass
        fw = v.get("fullwidth_map", {})
        if fw:
            s = "".join(fw.get(ch, ch) for ch in s)
        t2s = v.get("t2s", {})
        if t2s:
            s = "".join(t2s.get(ch, ch) for ch in s)
    s = s.lower()
    s = re.sub(r"[\s_\-·•]+", "", s)
    return s


# ---------------- validated.json 读写 ----------------

def now_bj() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def today_bj() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")


def load_validated(root=".") -> dict:
    """读 validated.json；不存在/损坏时返回带默认 policy 的空骨架。"""
    path = os.path.join(root, VALIDATED_FILE)
    doc = None
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:  # noqa: BLE001
        doc = None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        doc = {}
    doc.setdefault("schema", SCHEMA)
    doc.setdefault("policy", json.loads(json.dumps(DEFAULT_POLICY)))
    # 声明字段（note/not_pass_levels_note）由代码侧 DEFAULT_POLICY 刷新——
    # 口径文案修订后旧文件中的陈旧声明随下次读取自动更新（阈值类字段仍尊重文件内既有值）。
    pol = doc["policy"]
    if isinstance(pol, dict):
        pol.setdefault("decay", {})
        if isinstance(pol["decay"], dict):
            pol["decay"].setdefault("watch_after_days", DEFAULT_POLICY["decay"]["watch_after_days"])
            pol["decay"].setdefault("out_after_days", DEFAULT_POLICY["decay"]["out_after_days"])
            pol["decay"]["note"] = DEFAULT_POLICY["decay"]["note"]
            pol["decay"]["not_pass_levels_note"] = DEFAULT_POLICY["decay"]["not_pass_levels_note"]
    doc.setdefault("sources", {})
    doc.setdefault("sites", {})
    return doc


def save_validated(doc: dict, root=".", note=None):
    doc["schema"] = SCHEMA
    doc["updated_at"] = now_bj()
    if note:
        doc["note"] = note
    path = os.path.join(root, VALIDATED_FILE)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)


def resolve_entry(doc: dict, name: str, url=None) -> dict:
    """按名取（或创建）sources 条目，补写 ckey/url。兼容旧 name 键控形态。"""
    ent = doc["sources"].get(name)
    if not isinstance(ent, dict):
        ent = {}
    ent.setdefault("name", name)
    if url and not ent.get("url"):
        ent["url"] = url
    if url:
        ent["ckey"] = canonical_key(url)
    doc["sources"][name] = ent
    return ent


def trim_history(entry: dict):
    h = entry.get("history")
    if not isinstance(h, dict):
        return
    if len(h) > HISTORY_MAX_DAYS:
        keep = sorted(h)[-HISTORY_MAX_DAYS:]
        entry["history"] = {k: h[k] for k in keep}


# ---------------- 判级记录（两线统一入口） ----------------

def record_day(entry: dict, ok: bool, level=None):
    """写当日 history（同日通过优先），供跨日衰减统计。entry 为 sources/sites 条目。"""
    if level is None:
        level = "fully" if ok else "unavailable"
    else:
        level = LEVEL_ALIASES.get(level, level)
    today = today_bj()
    hist = entry.setdefault("history", {})
    prev = hist.get(today)
    if _pass_level(prev) and not ok:
        return  # 同日已有通过记录，保留
    if prev != "fully" and level == "fully":
        hist[today] = level
    elif prev is None or not _pass_level(prev):
        hist[today] = level
    trim_history(entry)

def record_result(doc: dict, name: str, ok: bool, whitelist_manual=(),
                  url=None, level=None, line="github") -> str:
    """按日记录验证结果并维护 fail_count/disabled。返回 'ok'/'disabled_now'/'failing'。
    ok=True 时 level 取参数或 'fully'；ok=False 记 'unavailable' 并累计连续失败。
    白名单（手动豁免）语义与原 fetch_merge.record_result 一致。"""
    policy = doc.get("policy", DEFAULT_POLICY)
    fail_limit = int(policy.get("upstream_fail_limit", 3))
    ent = resolve_entry(doc, name, url)
    ent["last_line"] = line
    record_day(ent, ok, level)
    if ok:
        ent.update({"fail_count": 0, "last_ok_at": now_bj(), "disabled": False,
                    "disabled_reason": "", "level": level})
        _apply_decay_one(ent, doc.get("policy", DEFAULT_POLICY))
        return "ok"
    fc = int(ent.get("fail_count", 0)) + 1
    ent["fail_count"] = fc
    ent["last_fail_at"] = now_bj()
    ent["level"] = level if level in ("fully", "partially") else "unavailable"
    out = "failing"
    if fc >= fail_limit and name not in whitelist_manual and not ent.get("disabled"):
        ent["disabled"] = True
        ent["disabled_reason"] = "连续 %d 次不达标，自动停用" % fc
        out = "disabled_now"
    _apply_decay_one(ent, doc.get("policy", DEFAULT_POLICY))
    return out


# ---------------- 第 4 层：跨日衰减 ----------------

def _pass_level(v) -> bool:
    return v in ("fully", "partially")


def not_pass_streak_days(entry: dict) -> int:
    """从 history 尾部向前数连续 not_pass 天数（not_pass=unavailable 或同日 disabled）。"""
    h = entry.get("history") or {}
    days = sorted(h)
    n = 0
    for d in reversed(days):
        v = h[d]
        if _pass_level(v):
            break
        n += 1
    return n


def _apply_decay_one(ent: dict, policy: dict):
    dec = policy.get("decay", {})
    watch_n = int(dec.get("watch_after_days", 3))
    out_n = int(dec.get("out_after_days", 7))
    streak = not_pass_streak_days(ent)
    disabled = bool(ent.get("disabled"))
    if _pass_level(ent.get("history", {}).get(today_bj(), "")) and not disabled:
        stage = "active"
    elif disabled or streak >= out_n:
        stage = "out"
    elif streak >= watch_n:
        stage = "watch"
    else:
        stage = "active"
    ent["decay"] = {"stage": stage, "streak_days": 0 if stage == "active" else streak,
                    "watch_after_days": watch_n, "out_after_days": out_n}
    if stage == "active":
        ent["decay"]["streak_days"] = 0
        ent["decayed"] = False
        ent["decay_stage"] = None
    else:
        ent["decay_stage"] = stage
        if stage == "out":
            ent["decayed"] = True
            ent.setdefault("decayed_at", today_bj())
        else:
            ent["decayed"] = False


def apply_decay(doc: dict) -> dict:
    """对 sources 全量应用衰减策略，返回计数摘要。"""
    counts = {"active": 0, "watch": 0, "out": 0}
    for ent in doc["sources"].values():
        if not isinstance(ent, dict):
            continue
        _apply_decay_one(ent, doc.get("policy", DEFAULT_POLICY))
        st = ent.get("decay", {}).get("stage", "active")
        counts[st] = counts.get(st, 0) + 1
    return counts


def active_sources(doc: dict) -> dict:
    """聚合/分发线消费视图：剔除 watch/out 衰减条目。"""
    return {k: v for k, v in doc["sources"].items()
            if isinstance(v, dict) and not v.get("decayed")
            and (v.get("decay") or {}).get("stage") not in ("watch", "out")}


# ---------------- 迁移（旧双轨状态 → validated.json） ----------------

def migrate(root=".", extra_feishu=None, note=None) -> dict:
    """合并旧状态：state/upstreams_state.json（GitHub 线）+ state/sites_state.json
    + 飞书线复测结果（extra_feishu: [{name,url,level}, ...]）→ state/validated.json。
    幂等：已存在条目按记录时间择新保留。"""
    doc = load_validated(root)
    # 1) GitHub 线 upstreams_state
    up_path = os.path.join(root, "state", "upstreams_state.json")
    try:
        ups = json.load(open(up_path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        ups = {}
    n_up = 0
    for name, ent in ups.items():
        if not isinstance(ent, dict):
            continue
        cur = doc["sources"].setdefault(name, {"name": name})
        cur.update({k: v for k, v in ent.items() if k != "history"})
        cur.setdefault("history", {})
        n_up += 1
    # ckey 回填（URL 来自仓库内上游清单）
    try:
        sys.path.insert(0, os.path.join(root, "scripts"))
        import fetch_merge as fm  # noqa: E402
        for u in fm.ALL_UPSTREAMS:
            ent = doc["sources"].get(u["name"])
            if isinstance(ent, dict):
                ent.setdefault("url", u["url"])
                ent["ckey"] = canonical_key(u["url"])
    except Exception as e:  # noqa: BLE001
        print("[migrate] ckey 回填跳过:", e)
    # 2) 飞书线复测结果
    n_fs = 0
    for r in (extra_feishu or []):
        url = r.get("url")
        if not url:
            continue
        ckey = canonical_key(url)
        # 按 ckey 找既有条目，找不到按 name 建新
        hit = None
        for ent in doc["sources"].values():
            if isinstance(ent, dict) and ent.get("ckey") == ckey:
                hit = ent
                break
        if hit is None:
            hit = doc["sources"].setdefault(r.get("name") or ckey, {"name": r.get("name") or ckey})
        hit["url"] = url
        hit["ckey"] = ckey
        lv = LEVEL_ALIASES.get(r.get("level"), r.get("level"))
        d = r.get("date") or today_bj()
        hist = hit.setdefault("history", {})
        # 飞书线结果仅在既有当日记录非通过时写入；既有通过且新结果更好时允许升级
        prev = hist.get(d)
        if not _pass_level(prev):
            hist[d] = lv
        elif prev != "fully" and lv == "fully":
            hist[d] = lv
        trim_history(hit)
        if _pass_level(lv):
            hit["level"] = lv
            hit["last_ok_at"] = hit.get("last_ok_at") or "%s 05:00:00" % d
            hit["fail_count"] = 0
            hit["disabled"] = False
        n_fs += 1
    # 3) sites 段（GitHub 线站点验活历史原样并入）
    site_path = os.path.join(root, "state", "sites_state.json")
    try:
        sites = json.load(open(site_path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        sites = {}
    for k, v in sites.items():
        if isinstance(v, dict):
            doc["sites"].setdefault(k, v)
    # 4) 衰减 + 落盘
    decay_counts = apply_decay(doc)
    save_validated(doc, root, note=note or "P1-A 迁移：upstreams_state+sites_state+飞书复测收敛为单一事实源")
    return {"sources": len(doc["sources"]), "from_upstreams": n_up,
            "feishu_merged": n_fs, "sites": len(doc["sites"]),
            "decay": decay_counts}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="validated.json 单一事实源工具")
    ap.add_argument("--migrate", action="store_true", help="从旧状态文件迁移生成 validated.json")
    ap.add_argument("--decay", action="store_true", help="对现有 validated.json 应用衰减并落盘")
    ap.add_argument("--root", default=".", help="仓库根目录")
    ap.add_argument("--stats", action="store_true", help="打印现状统计")
    a = ap.parse_args()
    if a.migrate:
        print(json.dumps(migrate(a.root), ensure_ascii=False, indent=1))
    elif a.decay:
        doc = load_validated(a.root)
        print(json.dumps(apply_decay(doc), ensure_ascii=False))
        save_validated(doc, a.root, note="跨日衰减应用")
    elif a.stats:
        doc = load_validated(a.root)
        lv = {}
        for e in doc["sources"].values():
            lv[e.get("level", "unknown")] = lv.get(e.get("level", "unknown"), 0) + 1
        print(json.dumps({"sources": len(doc["sources"]), "sites": len(doc["sites"]),
                          "levels": lv, "updated_at": doc.get("updated_at")},
                         ensure_ascii=False, indent=1))
    else:
        ap.print_help()
