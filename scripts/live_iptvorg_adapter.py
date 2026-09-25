#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_iptvorg_adapter.py — iptv-org 扩源接入适配器（P1-B，方案 docs/iptvorg-adapter-plan.md）。

四段管线（方案 §3）：
  fetch        抓取 iptv-org API 四端点（channels/streams/feeds/blocklist），24h TTL 缓存，
               落 state/iptvorg/*.json + fetch_meta.json（commit_sha + 时间戳溯源）
  parse        解析为 IptvOrgChannel/IptvOrgStream，过滤大中华区（CN/HK/TW/MO）+ 剔除
               blocklist(dmca) + is_nsfw 反向校验通道单独落盘
  to-upstream  单条 stream -> 本仓标准上游形态（方案 §3.3，挂 source=iptv-org marker）
  to-canary    刷新 canary 池 state/canary/iptvorg.json（按 stream_id 增量合并，
               保留既有 probe_history/admitted 状态，方案 §4.3）

另有两个入口（P1-B 任务交付）：
  daily        幂等每日步骤：fetch(TTL 命中则跳过，不重复拉取) -> parse -> to-canary。
               巡检线挂载点：`python3 scripts/live_iptvorg_adapter.py daily`
               后接 `python3 scripts/canary_promote.py --probe --promote`
  vocab        生成 state/vocab/normalization.iptvorg_additions.json（周一批 review 增量）
  vocab-merge  review 通过后把增量合入 state/vocab/normalization.json（带备份 + 冲突检测）

许可证事实（方案 §1 实测）：iptv-org 五仓均 Unlicense（public domain），可聚合。
本脚本只采元数据 + 已知稳定流，不做频道数膨胀；大中华区子集 + canary 闸门收编。
"""
import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(REPO, "state")
IPTVORG_DIR = os.path.join(STATE, "iptvorg")
CANARY_DIR = os.path.join(STATE, "canary")
VOCAB_DIR = os.path.join(STATE, "vocab")

TZ = timezone(timedelta(hours=8))

# ---- 抓取层（方案 §3.1）----------------------------------------------------

ENDPOINTS = {
    "channels":  "https://iptv-org.github.io/api/channels.json",
    "streams":   "https://iptv-org.github.io/api/streams.json",
    "feeds":     "https://iptv-org.github.io/api/feeds.json",
    "blocklist": "https://iptv-org.github.io/api/blocklist.json",
}
FETCH_TTL_HOURS = int(os.environ.get("IPTVORG_TTL_HOURS", "24"))
FETCH_TIMEOUT = 30
UA = "tvbox-config-aggregator/1.0 (iptvorg-adapter)"

COMMIT_SHA_ENDPOINTS = {
    "database": "https://api.github.com/repos/iptv-org/database/commits/master",
    "iptv":     "https://api.github.com/repos/iptv-org/iptv/commits/master",
}

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def _now():
    return datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def http_get_json(url, timeout=FETCH_TIMEOUT):
    """GET 并解析 JSON；返回 (status, obj|None)。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            body = r.read()
            return r.status, json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return 0, None


def fetch(endpoint_url, dest, *, max_age_hours=FETCH_TTL_HOURS, force=False):
    """带 TTL 的抓取：本地缓存 < max_age_hours 直接复用；过期或缺失则拉新。
    返回 (cache_hit, status)。"""
    if not force and os.path.exists(dest):
        age_h = (time.time() - os.path.getmtime(dest)) / 3600.0
        if age_h < max_age_hours:
            return True, 200
    status, obj = http_get_json(endpoint_url)
    if status != 200 or obj is None:
        # 拉新失败但有过期缓存：降级复用（比空数据好），并标注降级
        if os.path.exists(dest):
            print("  [fetch-degraded] %s 拉取失败(status=%s)，复用过期缓存" % (endpoint_url, status))
            return True, status
        return False, status
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, dest)
    return False, status


def fetch_commit_shas():
    """溯源：取 database/iptv 两仓 master HEAD commit_sha（失败不阻断）。"""
    meta_path = os.path.join(IPTVORG_DIR, "fetch_meta.json")
    meta = {}
    if os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path, encoding="utf-8"))
        except Exception:
            meta = {}
    shas = {}
    for name, url in COMMIT_SHA_ENDPOINTS.items():
        if not url:
            continue
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
                obj = json.loads(r.read().decode("utf-8", "replace"))
                shas[name] = obj.get("sha", "")
        except Exception:
            shas[name] = meta.get("commit_sha", {}).get(name, "")  # 保留上次已知值
    return shas


def cmd_fetch(args):
    os.makedirs(IPTVORG_DIR, exist_ok=True)
    if args.dry_run:
        # 验证清单 §8：--dry-run 拉到 4 个端点、无 5xx（HEAD/Range 轻探，不落盘）
        ok = True
        for name, url in ENDPOINTS.items():
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-255"})
            try:
                with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
                    print("  [dry-run] %-10s %s (%d bytes sample)" % (name, r.status, len(r.read())))
                    if r.status >= 500:
                        ok = False
            except Exception as e:
                print("  [dry-run] %-10s FAIL %s" % (name, e))
                ok = False
        return 0 if ok else 1
    hits, fails = 0, 0
    for name, url in ENDPOINTS.items():
        dest = os.path.join(IPTVORG_DIR, "%s.json" % name)
        hit, status = fetch(url, dest, force=args.force)
        hits += 1 if hit else 0
        if status != 200:
            fails += 1
        print("  [fetch] %-10s %s cache=%s" % (name, status or "ERR", hit))
    shas = fetch_commit_shas()
    meta = {"fetched_at": _now(), "commit_sha": shas, "endpoints": ENDPOINTS,
            "ttl_hours": FETCH_TTL_HOURS}
    with open(os.path.join(IPTVORG_DIR, "fetch_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("[fetch] %d 端点（%d 命中缓存），commit_sha=%s" % (len(ENDPOINTS), hits, shas))
    return 1 if fails else 0


# ---- 解析层（方案 §3.2）----------------------------------------------------

GC_REGIONS = {"CN", "HK", "TW", "MO"}          # 大中华区子集
NSFW_BLOCK_REASONS = {"nsfw"}                  # blocklist 反向校验原因；dmca 直接剔除
DMCA_EXCLUDE = {"dmca"}
MAX_ALT_NAME_LEN = 24                          # 异常长别名（多为描述句）不收

# 方案 §3.2 候选收录类目
CANDIDATE_CATEGORIES = {
    "general", "news", "movies", "entertainment", "music", "sports",
    "kids", "education", "documentary", "culture", "family", "animation",
    "comedy", "cooking", "outdoor", "travel", "weather", "business",
    "science", "auto", "legislative", "life", "religious", "classic",
    "series", "shop",
}


class IptvOrgChannel:
    __slots__ = ("iptv_id", "name", "alt_names", "country", "categories", "is_nsfw", "website")

    def __init__(self, iptv_id, name, alt_names, country, categories, is_nsfw, website=None):
        self.iptv_id = iptv_id
        self.name = name
        self.alt_names = alt_names or []
        self.country = country
        self.categories = categories or []
        self.is_nsfw = bool(is_nsfw)
        self.website = website


class IptvOrgStream:
    __slots__ = ("iptv_channel_id", "feed", "title", "url", "referrer", "user_agent",
                 "quality", "labels")

    def __init__(self, iptv_channel_id, feed, title, url, referrer, user_agent, quality, labels):
        self.iptv_channel_id = iptv_channel_id
        self.feed = feed
        self.title = title
        self.url = url
        self.referrer = referrer
        self.user_agent = user_agent
        self.quality = quality
        self.labels = labels or []


def load_raw():
    """读缓存原始数据；缺失返回 None 项。"""
    out = {}
    for name in ENDPOINTS:
        p = os.path.join(IPTVORG_DIR, "%s.json" % name)
        if os.path.exists(p):
            try:
                out[name] = json.load(open(p, encoding="utf-8"))
            except Exception:
                out[name] = None
        else:
            out[name] = None
    return out


def parse_channels(raw_channels):
    chans = []
    for c in raw_channels or []:
        try:
            chans.append(IptvOrgChannel(
                iptv_id=c.get("id") or "",
                name=c.get("name") or "",
                alt_names=[a for a in (c.get("alt_names") or []) if isinstance(a, str)],
                country=c.get("country") or "",
                categories=c.get("categories") or [],
                is_nsfw=c.get("is_nsfw") or False,
                website=c.get("website"),
            ))
        except Exception:
            continue
    return chans


def parse_streams(raw_streams):
    streams = []
    for s in raw_streams or []:
        url = s.get("url") or ""
        if not isinstance(url, str) or not re.match(r"^https?://", url):
            continue
        try:
            streams.append(IptvOrgStream(
                iptv_channel_id=s.get("channel") or "",
                feed=s.get("feed") or "",
                title=(s.get("title") or "").strip(),
                url=url.strip(),
                referrer=s.get("referrer") or None,
                user_agent=s.get("user_agent") or None,
                quality=s.get("quality") or None,
                labels=[l for l in (s.get("labels") or []) if isinstance(l, str)],
            ))
        except Exception:
            continue
    return streams


def select_gc_channels(channels, blocklist=None):
    """大中华区子集（方案 §1：聚焦 1065 个 CN+HK+TW+MO 频道）。
    blocklist(dmca) 频道剔除；is_nsfw 不进主池（反向校验通道单独处理）。"""
    blocked = set()
    for b in blocklist or []:
        if (b.get("reason") or "") in DMCA_EXCLUDE:
            blocked.add(b.get("channel") or "")
    gc, nsfw = [], []
    for c in channels:
        if c.country not in GC_REGIONS:
            continue
        if c.iptv_id in blocked:
            continue
        (nsfw if c.is_nsfw else gc).append(c)
    return gc, nsfw


def link_streams(streams, chan_index):
    """stream -> channel 关联（channel 字段为空或未知 channel 的流丢弃：无元数据不收）。"""
    linked, orphans = [], 0
    for s in streams:
        c = chan_index.get(s.iptv_channel_id)
        if c is None:
            orphans += 1
            continue
        linked.append((s, c))
    return linked, orphans


def cmd_parse(args):
    raw = load_raw()
    missing = [k for k, v in raw.items() if v is None]
    if missing:
        print("[parse] 缺少端点数据 %s，先跑 fetch" % missing)
        return 1
    channels = parse_channels(raw["channels"])
    streams = parse_streams(raw["streams"])
    gc, nsfw = select_gc_channels(channels, raw.get("blocklist"))
    chan_index = {c.iptv_id: c for c in gc + nsfw}
    linked, orphans = link_streams(streams, chan_index)
    print("[parse] channels=%d streams=%d | 大中华区=%d (nsfw=%d) | 关联流=%d 孤儿流=%d"
          % (len(channels), len(streams), len(gc), len(nsfw), len(linked), orphans))
    if args.check_fields:
        errs = 0
        for s, c in linked:
            if not s.url or not c.iptv_id:
                errs += 1
            if s.labels and not all(isinstance(l, str) for l in s.labels):
                errs += 1
        for c in gc:
            for a in c.alt_names:
                if not isinstance(a, str) or not a.strip():
                    errs += 1
        print("[parse] check-fields: %d 错误" % errs)
        if errs:
            return 1
    if args.nsfw_out:
        os.makedirs(os.path.dirname(args.nsfw_out), exist_ok=True)
        payload = {
            "schema": "tvbox.live_vocab.iptvorg_nsfw_crosscheck/1",
            "generated": _now(),
            "note": "iptv-org is_nsfw 大中华区频道反向校验素材（方案 §4.5，仅审计不自动处置）",
            "channels": [{"id": c.iptv_id, "name": c.name, "alt_names": c.alt_names,
                          "country": c.country, "categories": c.categories}
                         for c in sorted(nsfw, key=lambda x: x.iptv_id)],
        }
        with open(args.nsfw_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("[parse] nsfw 反向校验素材 -> %s (%d 条)" % (args.nsfw_out, len(nsfw)))
    return 0


# ---- 合并层（方案 §3.3）----------------------------------------------------

def to_upstream(stream, channel):
    """单条 iptv-org stream -> 本仓标准上游形态。
    注意：不直接 import 到 live_verified.txt —— source=iptv-org 的条目只能经 canary 晋升进入。"""
    headers = {}
    if stream.referrer:
        headers["Referer"] = stream.referrer
    if stream.user_agent:
        headers["User-Agent"] = stream.user_agent
    return {
        "name": stream.title or channel.name,
        "url": stream.url,
        "tvg_id": stream.iptv_channel_id,
        "headers": headers,
        "quality": stream.quality,
        "labels": stream.labels,
        "source": "iptv-org",
    }


# ---- Canary 池（方案 §4.3）-------------------------------------------------

REJECT_LABELS = ["Geo-blocked", "Not 24/7"]    # 闸 3 反证（promote 时执行）
CANARY_POOL_PATH = os.path.join(CANARY_DIR, "iptvorg.json")


def stream_id(stream):
    import hashlib
    h = hashlib.sha1(stream.url.encode("utf-8")).hexdigest()[:12]
    return "%s::%s::%s" % (stream.iptv_channel_id, stream.feed or "", h)


def build_canary_entries(linked):
    """关联流 -> canary entry 骨架（probe_history 由 canary_promote.py 逐日补）。"""
    entries = []
    for s, c in linked:
        entries.append({
            "stream_id": stream_id(s),
            "iptv_channel_id": s.iptv_channel_id,
            "channel_name": c.name,
            "alt_names": c.alt_names[:8],
            "country": c.country,
            "title": s.title or c.name,
            "url": s.url,
            "headers": {"Referer": s.referrer or "", "User-Agent": s.user_agent or ""},
            "quality": s.quality,
            "labels": s.labels,
            "probe_history": [],
            "admitted": False,
            "admit_date": None,
            "reject_reason": None,
        })
    return entries


def load_canary_pool(path=CANARY_POOL_PATH):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return {"meta": {}, "entries": []}


def merge_canary(old_pool, new_entries, max_new):
    """按 stream_id 增量合并：既有条目保留（含 probe_history/admitted），新流按 max_new 分批入池。
    上游已消失的流保留观测（可能回源），连续无成功由 canary_promote.py 移入 rejected。"""
    old_by_id = {e["stream_id"]: e for e in old_pool.get("entries", [])}
    merged, added = [], 0
    for e in new_entries:
        prev = old_by_id.get(e["stream_id"])
        if prev:
            # 刷新元数据（labels/quality 可能更新），保留历史与状态
            prev.update({k: e[k] for k in ("channel_name", "alt_names", "country", "title",
                                           "url", "headers", "quality", "labels")})
            merged.append(prev)
        else:
            if added >= max_new:
                continue  # 分批入池（方案 §7 池膨胀风险）
            added += 1
            merged.append(e)
    # 上游消失但既有历史/已晋升的条目：保留在池尾
    new_ids = {e["stream_id"] for e in new_entries}
    for sid, e in old_by_id.items():
        if sid not in new_ids and (e.get("probe_history") or e.get("admitted")):
            merged.append(e)
    return merged, added


def cmd_to_canary(args):
    raw = load_raw()
    missing = [k for k, v in raw.items() if v is None]
    if missing:
        print("[to-canary] 缺少端点数据 %s，先跑 fetch" % missing)
        return 1
    channels = parse_channels(raw["channels"])
    streams = parse_streams(raw["streams"])
    gc, nsfw = select_gc_channels(channels, raw.get("blocklist"))
    chan_index = {c.iptv_id: c for c in gc + nsfw}
    linked, _ = link_streams(streams, chan_index)
    entries = build_canary_entries(linked)
    old_pool = load_canary_pool(args.out)
    merged, added = merge_canary(old_pool, entries, args.max_new)
    meta_path = os.path.join(IPTVORG_DIR, "fetch_meta.json")
    shas = {}
    if os.path.exists(meta_path):
        try:
            shas = json.load(open(meta_path, encoding="utf-8")).get("commit_sha", {})
        except Exception:
            pass
    pool = {
        "schema": "tvbox.live.canary.iptvorg/1",
        "meta": {
            "updated": _now(),
            "iptvorg_commit_sha": shas,
            "ttl_days": 7,
            "stability_days": 7,
            "threshold": 0.6,
            "max_new_per_batch": args.max_new,
            "counts": {"total": len(merged), "added": added},
            "note": "直播 canary 池（iptv-org 来源）；准入/晋升由 canary_promote.py 执行，"
                    "通过后方入 state/upstreams/iptvorg.normal.json，最终由 live_aggregate 汇入 live_verified.txt",
        },
        "entries": merged,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=1)
    os.replace(tmp, args.out)
    print("[to-canary] 关联流=%d 池内=%d（新入 %d，上限 %d）-> %s"
          % (len(entries), len(merged), added, args.max_new, args.out))
    return 0


def cmd_daily(args):
    """巡检线挂载点：fetch(TTL 幂等) -> parse -> to-canary。不重复拉取（24h TTL 命中即跳过）。"""
    rc = cmd_fetch(argparse.Namespace(dry_run=False, force=args.force))
    if rc != 0:
        print("[daily] fetch 失败，中止本轮（canary 池保持昨日状态）")
        return rc
    nsfw_out = os.path.join(CANARY_DIR, "iptvorg_nsfw_crosscheck.json")
    rc = cmd_parse(argparse.Namespace(check_fields=True, nsfw_out=nsfw_out))
    if rc != 0:
        return rc
    return cmd_to_canary(argparse.Namespace(out=CANARY_POOL_PATH, max_new=args.max_new))


# ---- 词表增量（方案 §3.4 / 任务交付 4）--------------------------------------

VOCAB_ADDITIONS_PATH = os.path.join(VOCAB_DIR, "normalization.iptvorg_additions.json")

_CN_RE = re.compile(r"[\u4e00-\u9fff]")
_SAFE_ALIAS_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9＋\+\-－\s]+$")
CCTV_ID_RE = re.compile(r"^CCTV[^0-9]*?(\d{1,2})")


def _clean_alias(a):
    a = (a or "").strip()
    if not a or len(a) > MAX_ALT_NAME_LEN:
        return None
    if not _SAFE_ALIAS_RE.match(a):
        return None
    # 单语种或「中文+英文数字」形态；纯符号/混杂标点不收
    return a


def build_vocab_additions(gc_channels):
    """把 iptv-org alt_names 增量整理为待 review 词表（只接受单语种+中文/英文+全名匹配形态）。
    CCTV 系频道：别名可建议进 cctv_alias_canonical（review 后合入）；
    其余频道：alt_names 仅作 review 素材留存，不自动进词表。"""
    cctv_suggestions = {}
    others = []
    for c in gc_channels:
        aliases = []
        for a in c.alt_names:
            a2 = _clean_alias(a)
            if a2 and a2 != c.name:
                aliases.append(a2)
        if not aliases:
            continue
        m = CCTV_ID_RE.match(c.name)
        if m:
            n = int(m.group(1))
            for a2 in aliases:
                # 形态约束：别名须含中文（如「央视N套/中文别名」），且不与既有 canonical 冲突形态
                if _CN_RE.search(a2):
                    cctv_suggestions.setdefault(a2, "CCTV-%d" % n)
        else:
            others.append({"id": c.iptv_id, "name": c.name, "alt_names": aliases})
    return cctv_suggestions, others


def cmd_vocab(args):
    raw = load_raw()
    if raw.get("channels") is None:
        print("[vocab] 缺少 channels.json，先跑 fetch")
        return 1
    channels = parse_channels(raw["channels"])
    blocklist = raw.get("blocklist") or []
    gc, _ = select_gc_channels(channels, blocklist)
    cctv_suggestions, others = build_vocab_additions(gc)
    shas = {}
    meta_path = os.path.join(IPTVORG_DIR, "fetch_meta.json")
    if os.path.exists(meta_path):
        try:
            shas = json.load(open(meta_path, encoding="utf-8")).get("commit_sha", {})
        except Exception:
            pass
    payload = {
        "schema": "tvbox.live_vocab.normalization.iptvorg_additions/1",
        "generated": _now(),
        "iptvorg_commit_sha": shas,
        "review_note": "周一批 review 增量（方案 §3.4）：cctv_alias_canonical_additions 人工确认后 "
                       "执行 `python3 scripts/live_iptvorg_adapter.py vocab-merge` 合入；"
                       "channel_alt_names 仅留存 review，不自动进词表。",
        "cctv_alias_canonical_additions": dict(sorted(cctv_suggestions.items())),
        "channel_alt_names": others,
    }
    os.makedirs(os.path.dirname(VOCAB_ADDITIONS_PATH), exist_ok=True)
    with open(VOCAB_ADDITIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("[vocab] additions -> %s（cctv 建议 %d 条，其他频道 %d 条待 review）"
          % (VOCAB_ADDITIONS_PATH, len(cctv_suggestions), len(others)))
    return 0


def cmd_vocab_merge(args):
    """把已 review 的 cctv_alias_canonical_additions 合入 normalization.json。
    冲突（别名已映射到不同 canonical）跳过并报告；合入前备份，合入后 JSON 自检。"""
    if not os.path.exists(VOCAB_ADDITIONS_PATH):
        print("[vocab-merge] 无增量文件 %s，先跑 vocab" % VOCAB_ADDITIONS_PATH)
        return 1
    add = json.load(open(VOCAB_ADDITIONS_PATH, encoding="utf-8"))
    additions = add.get("cctv_alias_canonical_additions") or {}
    if not additions:
        print("[vocab-merge] 增量为空，无事可做")
        return 0
    norm_path = os.path.join(VOCAB_DIR, "normalization.json")
    norm = json.load(open(norm_path, encoding="utf-8"))
    # 备份先落盘（改动前），再内存变更
    bak = norm_path + ".bak-" + datetime.now(TZ).strftime("%Y%m%d%H%M%S")
    with open(bak, "w", encoding="utf-8") as f:
        json.dump(norm, f, ensure_ascii=False, indent=1)
    canon = norm.setdefault("cctv_alias_canonical", {})
    merged, skipped = [], []
    for alias, canonical in additions.items():
        existing = canon.get(alias)
        if existing is not None:
            if existing != canonical:
                skipped.append((alias, existing, canonical))
            continue  # 已存在：幂等
        canon[alias] = canonical
        merged.append((alias, canonical))
    if not merged:
        print("[vocab-merge] 无新增（重复 %d，冲突跳过 %d）" % (len(additions) - len(skipped), len(skipped)))
        for alias, old, new in skipped:
            print("  [conflict] %s: 已映射 %s，iptv-org 建议 %s（保留既有）" % (alias, old, new))
        return 0
    # 版本号 + 落盘
    norm["version"] = "iptvorg-" + datetime.now(TZ).strftime("%Y%m%d")
    norm["source_note"] = (norm.get("source_note") or "") + \
        "；%s iptv-org alt_names 增量合入 %d 条（review 流程，脚本 live_iptvorg_adapter.py vocab-merge）。" \
        % (datetime.now(TZ).strftime("%Y-%m-%d"), len(merged))
    with open(norm_path, "w", encoding="utf-8") as f:
        json.dump(norm, f, ensure_ascii=False, indent=1)
    # 自检：JSON 可回读 + live_vocab 可加载
    json.load(open(norm_path, encoding="utf-8"))
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import live_vocab  # noqa: F401  词表加载自检
    except Exception as e:
        print("[vocab-merge] live_vocab 加载失败，回滚：%s" % e)
        os.replace(bak, norm_path)
        return 1
    print("[vocab-merge] 合入 %d 条 -> %s（备份 %s）" % (len(merged), norm_path, bak))
    for alias, canonical in merged:
        print("  + %s -> %s" % (alias, canonical))
    for alias, old, new in skipped:
        print("  [conflict] %s: 保留既有 %s（iptv-org 建议 %s）" % (alias, old, new))
    return 0


def main():
    ap = argparse.ArgumentParser(description="iptv-org 扩源适配器（fetch/parse/to-upstream/to-canary/vocab）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="抓取四端点（24h TTL 缓存）")
    p.add_argument("--dry-run", action="store_true", help="轻探端点可用性，不落盘（验证清单 §8）")
    p.add_argument("--force", action="store_true", help="绕过 TTL 强制拉新")
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("parse", help="解析 + 大中华区筛选 + 字段校验")
    p.add_argument("--check-fields", action="store_true")
    p.add_argument("--nsfw-out", default="", help="is_nsfw 反向校验素材落盘路径")
    p.set_defaults(fn=cmd_parse)

    p = sub.add_parser("to-canary", help="刷新 canary 池（增量合并，保留历史）")
    p.add_argument("--out", default=CANARY_POOL_PATH)
    p.add_argument("--max-new", type=int, default=500, help="单批新入池上限（池膨胀防护）")
    p.set_defaults(fn=cmd_to_canary)

    p = sub.add_parser("daily", help="巡检线幂等步骤：fetch(TTL) -> parse -> to-canary")
    p.add_argument("--force", action="store_true")
    p.add_argument("--max-new", type=int, default=500)
    p.set_defaults(fn=cmd_daily)

    p = sub.add_parser("vocab", help="生成 normalization.iptvorg_additions.json（周一批 review）")
    p.set_defaults(fn=cmd_vocab)

    p = sub.add_parser("vocab-merge", help="review 后把增量合入 normalization.json（带备份/冲突检测）")
    p.set_defaults(fn=cmd_vocab_merge)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
