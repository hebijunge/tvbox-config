#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接口实测探针（L1-L3）：把「能连上」升级为「真能用」。

背景
----
fetch_merge.py 的 check_site() 判据是「HTTP 200 且首字节非 HTML」，一个返回空
JSON 的死站同样能通过。用户端体感取决于接口有没有真实片库、能不能搜到、能不能出片，
本脚本对外部可验证的 HTTP 型采集接口做三段式实测：

    L1 接口可用  : ?ac=list 返回 JSON，list 非空且元素含 vod_id/vod_name
    L2 搜索可用  : 热词 ?wd=xxx 能命中结果
    L3 出片可取链: ?ac=detail&ids=xxx 拿到 vod_play_url，抽一个 m3u8 取首片
                   （Range: bytes=0-2047）确认返回 #EXTM3U

对无法在 CI 中动态执行的类型做静态降级检查：
    js 型（./deps/xxx.js）→ ext 文件存在性 + 头部 searchable 标注
    csp 型（csp_xxx）     → spider jar 是否已在 deps 中落地

用法
----
    python scripts/probe_sites.py                          # 全量（http 实测，其余静态）
    python scripts/probe_sites.py --only http --limit 50   # 只测 http 型前 50 个
    python scripts/probe_sites.py --concurrency 32 --top 200
"""

import argparse
import concurrent.futures as cf
import gzip
import io
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib

UA = {"User-Agent": "okhttp/3.15", "Accept": "*/*", "Accept-Encoding": "gzip, deflate"}
L1_TIMEOUT = 8
L2_TIMEOUT = 10
L3_TIMEOUT = 10
MAX_JSON = 512 * 1024
MAX_TS = 4096

# ---- V4 并发拉满 + 同域信号量（参考 fetch_merge.py L1479 模式）----
# 默认总并发 24→48；同域并发封顶 PROBE_DOMAIN_CONCURRENCY（默认 6），
# raw.githubusercontent.com 等热门 CDN 单独限到 PROBE_GH_CONCURRENCY（默认 8），
# 避免单域名被我们自己打限流。
PROBE_CONCURRENCY_DEFAULT = int(os.environ.get("PROBE_CONCURRENCY", "48"))
# P0-2 验活配额：>0 时每轮最多实测 N 个代表任务，优先覆盖无历史结论的 unknown 源，
# 按天轮转窗口；0=不限量（现行为）。
PROBE_QUOTA_DEFAULT = int(os.environ.get("PROBE_QUOTA", "0"))
PROBE_DOMAIN_CONCURRENCY = int(os.environ.get("PROBE_DOMAIN_CONCURRENCY", "6"))
PROBE_GH_CONCURRENCY = int(os.environ.get("PROBE_GH_CONCURRENCY", "8"))
_DOMAIN_LOCK = threading.Lock()
_DOMAIN_SEMAPHORES = {}


def _domain_semaphore(url: str) -> threading.Semaphore:
    """按 URL host 的信号量：同域并发封顶。GitHub 系域名单独限额。"""
    host = (urllib.parse.urlparse(url).netloc or "default").lower()
    cap = PROBE_GH_CONCURRENCY if "github" in host else PROBE_DOMAIN_CONCURRENCY
    with _DOMAIN_LOCK:
        sem = _DOMAIN_SEMAPHORES.get(host)
        if sem is None:
            sem = threading.Semaphore(cap)
            _DOMAIN_SEMAPHORES[host] = sem
        return sem

# ---- 探针结果缓存跳过（P1）----
# 上次实测 healthy（L1/L2/L3）且延迟 < CACHE_MAX_LATENCY_MS 且在 CACHE_TTL_HOURS 小时内
# 测过的源，本轮跳过实测直接复用结论；只测新增源、上次降级/超时（L0/L?）源、fail_streak>0 源。
CACHE_TTL_HOURS = float(os.environ.get("PROBE_CACHE_HOURS", "24"))
CACHE_MAX_LATENCY_MS = int(os.environ.get("PROBE_CACHE_MAX_MS", "2000"))
HEALTHY_LEVELS = ("L1", "L2", "L3")

# 热词：优先选长期在架、覆盖面广的剧名，命中率比随机词高
# L2 搜索热词：前三部热剧验"有正经内容"；末位单字"大"作兜底——片库大但没有这几部
# 热剧的站不该被误杀（所有者 2026-09-29 指令），任何正经影视库对"大"都有命中。
KEYWORDS = ["庆余年", "流浪地球", "甄嬛传", "大"]

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def http_get(url, timeout, max_bytes=0, extra=None):
    """带 gzip 解压与宽松证书的 GET。返回 (status, body_bytes, ms, content_type)。"""
    req = urllib.request.Request(url, headers={**UA, **(extra or {})})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        raw = r.read(max_bytes) if max_bytes else r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
        if "gzip" in enc:
            try:
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            except OSError:
                pass
        elif "deflate" in enc:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                pass
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return r.status, raw, int((time.time() - t0) * 1000), ctype


def load_json(raw):
    """容错 JSON 解析：去 BOM、截取首个 { 或 [ 到末尾。"""
    if not raw:
        return None
    text = raw.decode("utf-8", "replace").lstrip("\ufeff \t\r\n")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for m in re.finditer(r"[{\[]", text):
        frag = text[m.start():]
        for end in range(len(frag), 0, -1):
            if frag[end - 1] in "}]":
                try:
                    return json.loads(frag[:end])
                except json.JSONDecodeError:
                    continue
        break
    return None


def pick_list(doc):
    """从 maccms 返回里取出 list 数组。"""
    if not isinstance(doc, dict):
        return []
    for k in ("list", "data", "result"):
        v = doc.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            for kk in ("list", "data"):
                if isinstance(v.get(kk), list):
                    return v[kk]
    return []


def join_api(api, query):
    """把 ac/wd 等查询参数拼到 api 上（保留 api 已有查询串）。"""
    sep = "&" if "?" in api else "?"
    return f"{api}{sep}{query}"


def parse_xml(raw):
    """解析 maccms XML 接口（type 0）返回，统一成与 JSON 相同的 list 结构。

    返回 (vod 列表, 分类名列表)。XML 的播放地址在 <dl><dd flag="m3u8">集数$url</dd></dl>。
    """
    text = raw.decode("utf-8", "replace").lstrip("\ufeff \t\r\n")
    if "<rss" not in text[:400] and "<video" not in text[:2000]:
        return [], []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        i = text.find("<rss")
        if i < 0:
            return [], []
        try:
            root = ET.fromstring(text[i:])
        except ET.ParseError:
            return [], []
    lst = []
    for v in root.iter("video"):
        item = {
            "vod_id": (v.findtext("id") or "").strip(),
            "vod_name": (v.findtext("name") or "").strip(),
        }
        urls = [(dd.text or "").strip() for dd in v.iter("dd") if (dd.text or "").strip()]
        if urls:
            item["vod_play_url"] = "#".join(urls)
        if item["vod_id"] or item["vod_name"]:
            lst.append(item)
    classes = [(t.text or "").strip() for t in root.iter("ty") if (t.text or "").strip()][:60]
    return lst, classes


def parse_any(raw):
    """统一解析 JSON（type 1）与 XML（type 0）两种 maccms 返回。

    只认 JSON 会把这批 XML 接口误判为不可用——实测 155 个 http 型源里有 10 个属此类。
    """
    doc = load_json(raw)
    lst = pick_list(doc)
    if lst:
        classes = []
        if isinstance(doc, dict):
            for k in ("class", "classes", "type_list"):
                v = doc.get(k)
                if isinstance(v, list):
                    for c in v[:60]:
                        if isinstance(c, dict):
                            nm = c.get("type_name") or c.get("name")
                            if nm:
                                classes.append(str(nm))
        return lst, classes
    return parse_xml(raw)


def probe_l1(api, timeout=L1_TIMEOUT):
    """L1：接口是否有真实片库。

    失败分类很重要，用于避免误杀：
      cls=env    连接层失败（RST/超时/DNS），本机网络问题，**不能判定站点不可用**
      cls=http   服务端明确返回错误码
      cls=empty  200 但空响应 / 无有效 list（确认不可用）
    """
    last = {"ok": False, "cls": "unknown", "reason": "未执行"}
    for q in ("ac=list", "ac=videolist"):
        url = join_api(api, q)
        try:
            st, raw, ms, _ = http_get(url, timeout, MAX_JSON)
        except urllib.error.HTTPError as e:
            last = {"ok": False, "cls": "http", "reason": f"HTTP {e.code}", "url": url}
            continue
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = {"ok": False, "cls": "env", "reason": f"{type(e).__name__}: {e}"[:90], "url": url}
            continue
        if st != 200:
            last = {"ok": False, "cls": "http", "reason": f"HTTP {st}", "url": url}
            continue
        if not raw:
            last = {"ok": False, "cls": "empty", "reason": "空响应", "url": url}
            continue
        lst, classes = parse_any(raw)
        if lst and any(isinstance(x, dict) and (x.get("vod_id") or x.get("vod_name")) for x in lst):
            doc = load_json(raw)
            total = doc.get("total") if isinstance(doc, dict) else None
            if total is None:
                m = re.search(rb'recordcount="(\d+)"', raw)
                if m:
                    total = int(m.group(1))
            return {"ok": True, "ms": ms, "count": len(lst), "total": total,
                    "format": "json" if isinstance(doc, dict) else "xml",
                    "sample": (lst[0].get("vod_name") if isinstance(lst[0], dict) else None),
                    "classes": classes,
                    # 片名集合：供镜像站去重算数据指纹（同库换域名的站，这批名字会高度重合）
                    "names": [str(x.get("vod_name")) for x in lst[:20]
                              if isinstance(x, dict) and x.get("vod_name")]}
        last = {"ok": False, "cls": "empty", "reason": f"无有效 list；响应前 80 字节: {raw[:80]!r}", "url": url}
    return last


def probe_l2(api, keywords, timeout=L2_TIMEOUT):
    """L2：热词搜索是否命中。多种参数变体轮试，记录失败细节。"""
    best = {"ok": False, "hits": 0, "kw": None, "ms": None, "tried": [], "env": 0}
    for kw in keywords:
        q = urllib.parse.quote(kw)
        for variant in (f"wd={q}", f"ac=detail&wd={q}", f"ac=list&wd={q}"):
            url = join_api(api, variant)
            try:
                st, raw, ms, _ = http_get(url, timeout, MAX_JSON)
            except urllib.error.HTTPError as e:
                best["tried"].append(f"{variant.split('&')[0]}→HTTP {e.code}")
                continue
            except (urllib.error.URLError, OSError, ValueError) as e:
                best["tried"].append(f"{variant.split('&')[0]}→{type(e).__name__}")
                best["env"] += 1
                continue
            if st != 200 or not raw:
                best["tried"].append(f"{variant.split('&')[0]}→HTTP {st}")
                continue
            lst, _ = parse_any(raw)
            hits = len(lst)
            best["tried"].append(f"{variant.split('&')[0]}→{hits} 条")
            if hits > best["hits"]:
                first = lst[0] if lst and isinstance(lst[0], dict) else {}
                best.update({"ok": True, "hits": hits, "kw": kw, "ms": ms,
                             "vod_id": first.get("vod_id"), "vod_name": first.get("vod_name")})
            if best["ok"]:
                return best
    if best["env"] and best["env"] == len(best["tried"]):
        best["cls"] = "env"
        best["reason"] = "搜索接口连接层失败（本机网络，无法判定）"
    elif not best["ok"]:
        best["reason"] = "搜索无命中"
    return best


def pick_m3u8(vod):
    """从 vod 详情里抽出第一个播放地址（优先 m3u8）。"""
    if not isinstance(vod, dict):
        return None, None
    for field in ("vod_play_url", "vod_play_note", "vod_url"):
        s = vod.get(field)
        if not isinstance(s, str):
            continue
        for line in s.split("#"):
            line = line.strip()
            if not line:
                continue
            for sep in ("$", "&"):
                if sep in line:
                    label, _, url = line.partition(sep)
                    if url.startswith("http"):
                        return (label or None), url
            if line.startswith("http"):
                return None, line
    return None, None


def probe_l3(api, vod_id, timeout=L3_TIMEOUT):
    """L3：能否取到可播的播放地址（取首片验证）。

    接受 m3u8（响应含 #EXTM3U）与 video/* 直链；两者都算「可取链」。
    """
    url = join_api(api, f"ac=detail&ids={urllib.parse.quote(str(vod_id))}")
    try:
        st, raw, ms, _ = http_get(url, timeout, MAX_JSON)
    except urllib.error.HTTPError as e:
        return {"ok": False, "reason": f"detail HTTP {e.code}"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "reason": f"detail {type(e).__name__}"}
    if st != 200 or not raw:
        return {"ok": False, "reason": f"detail HTTP {st}"}
    lst, _ = parse_any(raw)
    if not lst or not isinstance(lst[0], dict):
        return {"ok": False, "reason": "detail 无 list"}
    label, play = pick_m3u8(lst[0])
    if not play:
        return {"ok": False, "reason": "无播放地址"}

    try:
        st2, body, ms2, ctype = http_get(play, timeout, MAX_TS, {"Range": "bytes=0-2047"})
    except urllib.error.HTTPError as e:
        return {"ok": False, "play_url": play[:140], "reason": f"播放 HTTP {e.code}"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "play_url": play[:140], "reason": f"播放 {type(e).__name__}"}

    head = body.lstrip()[:64]
    if st2 in (200, 206):
        if head.startswith(b"#EXTM3U") or b"#EXTM3U" in body:
            return {"ok": True, "play_url": play[:180], "label": label, "media": "m3u8",
                    "detail_ms": ms, "play_ms": ms2}
        if ctype.startswith("video/") or "octet-stream" in ctype:
            return {"ok": True, "play_url": play[:180], "label": label, "media": ctype or "video",
                    "detail_ms": ms, "play_ms": ms2}
    return {"ok": False, "play_url": play[:140], "reason": f"非可播(HTTP {st2}, {ctype or '无 CT'})"}


def probe_http_site(site, keywords, deep=True, prev_l1_ms=None):
    """对单个 HTTP 型站点跑 L1→L2→L3。

    prev_l1_ms: 上轮 L1 实测毫秒数（V8 智能调度）。>5000ms 视为慢源，
    本轮 L1/L2/L3 超时统一缩到 SLOW_SOURCE_TIMEOUT，避免慢源长期霸占并发槽。
    """
    api = site.get("api")
    r = {"key": site.get("key"), "name": site.get("name"), "api": api, "kind": "http"}
    # V4 同域信号量：submit 进来的任务在执行时才按域名封顶，避免单域打爆
    sem = _domain_semaphore(api or "")
    with sem:
        # V8 慢源超时缩减：上轮 >5s 的源本轮把 L1/L2/L3 超时压到 3s
        slow = isinstance(prev_l1_ms, (int, float)) and prev_l1_ms > 5000
        l1_timeout = SLOW_SOURCE_TIMEOUT if slow else L1_TIMEOUT
        l2_timeout = SLOW_SOURCE_TIMEOUT if slow else L2_TIMEOUT
        l3_timeout = SLOW_SOURCE_TIMEOUT if slow else L3_TIMEOUT
        l1 = probe_l1(api, l1_timeout)
        r["l1"] = l1
        if slow:
            r["slow_source"] = True
        if not l1.get("ok"):
            # 连接层失败只说明本机到该域名的链路不通，不能判定站点不可用
            r["level"] = "L?" if l1.get("cls") == "env" else "L0"
            return r
        r["level"] = "L1"
        if not deep:
            return r
        l2 = probe_l2(api, keywords, l2_timeout)
        r["l2"] = l2
        if l2.get("ok"):
            r["level"] = "L2"
        vod_id = l2.get("vod_id")
        if vod_id is None:
            # 搜索失败或未命中时，用 L1 列表里的第一条 id 兜底试 L3（判断是搜索不可用还是接口整体不可用）
            try:
                st, raw, _, _ = http_get(join_api(api, "ac=list"), l1_timeout, MAX_JSON)
                lst, _ = parse_any(raw)
                if lst and isinstance(lst[0], dict):
                    vod_id = lst[0].get("vod_id")
            except (urllib.error.URLError, OSError, ValueError):
                pass
        if vod_id is not None:
            l3 = probe_l3(api, vod_id, l3_timeout)
            r["l3"] = l3
            if l3.get("ok"):
                r["level"] = "L3"
        return r


# V8 慢源（上轮 >5s）本轮用的紧缩超时（秒）
SLOW_SOURCE_TIMEOUT = 3


def static_check(site, repo_dir, manifest):
    """js / csp 型的静态降级检查。"""
    api = site.get("api") or ""
    ext = site.get("ext")
    r = {"key": site.get("key"), "name": site.get("name"), "api": api, "level": "S?"}
    if isinstance(api, str) and api.startswith("./"):
        r["kind"] = "js"
        p = api[2:].split(";")[0]
        fp = os.path.join(repo_dir, p)
        if os.path.isfile(fp):
            r["level"] = "S1"
            r["file"] = p
            try:
                with open(fp, "rb") as f:
                    head = f.read(65536).decode("utf-8", "ignore")
                if re.search(r"searchable\s*[:=]\s*0\b", head):
                    r["level"] = "S0"
                    r["reason"] = "searchable=0"
            except OSError:
                pass
        else:
            r["level"] = "S0"
            r["reason"] = "ext 文件缺失"
        return r
    if isinstance(api, str) and api.startswith("csp_"):
        r["kind"] = "csp"
        spider = manifest.get("spider") if isinstance(manifest, dict) else None
        ok_spider = bool(spider) or bool(ext)
        r["level"] = "S1" if ok_spider else "S0"
        if not ok_spider:
            r["reason"] = "无 spider"
        return r
    r["kind"] = "other"
    r["level"] = "S?"
    return r


# ---------------- 3.5-2 无广告排序维度：广告启发式粗判 ----------------
# 页面特征/弹窗域名启发式。只做粗筛写 ad_warn，不做精细判定（精细判定交给客户端）。
# 命中任一信号即标记 ad_warn=True。
_AD_PAGE_MARKS = (
    "弹窗", "点击下载", "立即下载", "长按保存", "关注公众号", "加群",
    "点击观看", "跳转浏览器", "下载APP", "下载app", "高速下载",
)
_AD_DOMAIN_MARKS = (
    "ad.", "ads.", "pop.", "push.", "redirect.", "jump.",
)


def detect_ad_heuristic(l1_result: dict) -> bool:
    """3.5-2：根据 L1 抓回的首屏片名/样本粗判是否带广告弹窗。

    启发式：当前 probe_l1 只保留了 names/sample，不保留正文 HTML；
    这里用「样本片名里混入下载/弹窗关键词」做弱信号（多数干净片库片名不会带这些词）。
    强信号（弹窗域名）在 fetch_merge 主流程抓取阶段已能拿到，此处只做兜底。
    """
    if not isinstance(l1_result, dict):
        return False
    text = " ".join(str(x) for x in l1_result.get("names") or [])
    text += " " + str(l1_result.get("sample") or "")
    return any(mark in text for mark in _AD_PAGE_MARKS)


# ---------------- V11 源突变检测：每轮存指纹，与历史均值对比 ----------------
ANOMALY_BASELINE_PATH = os.path.join("state", "anomaly_baseline.json")


def _fingerprint(l1: dict) -> dict:
    """从 L1 结果提取内容指纹：分类数 / 影片数 / 首屏片名集合。"""
    if not isinstance(l1, dict) or not l1.get("ok"):
        return {}
    names = {str(n) for n in (l1.get("names") or []) if n}
    return {
        "classes": len(l1.get("classes") or []),
        "total": l1.get("total") or len(names),
        "names": sorted(names)[:20],
    }


def detect_source_anomaly(results: list, repo: str) -> list:
    """V11：每轮指纹与历史均值对比，分类数/影片数变化超 ±50% 标记异常。

    与 C5 共用 state/anomaly_baseline.json。只标记不剔除。
    返回被标记的 key 列表。
    """
    bp_path = os.path.join(repo, ANOMALY_BASELINE_PATH)
    baseline = {}
    try:
        with open(bp_path, encoding="utf-8") as f:
            baseline = json.load(f).get("snapshots") or {}
    except (OSError, json.JSONDecodeError):
        baseline = {}
    flagged = []
    new_snap = {}
    for r in results:
        if r.get("kind") != "http":
            continue
        key = r.get("key")
        fp = _fingerprint(r.get("l1") or {})
        if not fp:
            continue
        new_snap[key] = fp
        old = baseline.get(key)
        if not old:
            continue
        # 影片数/分类数任一变化超 ±50% 即标记
        for field in ("classes", "total"):
            ov, nv = old.get(field), fp.get(field)
            if isinstance(ov, (int, float)) and isinstance(nv, (int, float)) and ov > 0:
                ratio = (nv - ov) / ov
                if abs(ratio) > 0.5:
                    r["anomaly"] = f"{field}_shift_{ratio:+.0%}"
                    flagged.append(key)
                    break
    # 写回新基线（只保留最近 1 轮，避免无限膨胀）
    try:
        os.makedirs(os.path.dirname(bp_path), exist_ok=True)
        with open(bp_path, "w", encoding="utf-8") as f:
            json.dump({"snapshots": new_snap,
                       "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return flagged


def load_probe_cache(out_path: str) -> dict:
    """读上次 probe/sites_probe.json，返回 {api: result}。文件缺失/损坏返回空。"""
    try:
        with open(out_path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    cache = {}
    for r in (doc.get("sites") or []):
        api = r.get("api")
        if isinstance(api, str) and api:
            cache[api] = r
    return cache


def _age_hours(result: dict, file_generated_at: str) -> float:
    """距上次实测的小时数。优先用单条 tested_at，缺失回退到文件 generated_at。"""
    ts = result.get("tested_at") or file_generated_at or ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = time.strptime(ts, fmt)
            return (time.time() - time.mktime(dt)) / 3600.0
        except ValueError:
            continue
    return 1e9  # 时间解析失败 → 视为过期，必须重测


def cache_hit(result: dict, file_generated_at: str) -> bool:
    """判定是否可复用上轮结论：healthy + 延迟达标 + 24h 内测过。"""
    if result.get("level") not in HEALTHY_LEVELS:
        return False
    if int(result.get("fail_streak", 0) or 0) > 0:
        return False
    l1 = result.get("l1") or {}
    ms = l1.get("ms")
    if not isinstance(ms, (int, float)) or ms >= CACHE_MAX_LATENCY_MS:
        return False
    if _age_hours(result, file_generated_at) >= CACHE_TTL_HOURS:
        return False
    return True


def _health_score(prev: dict) -> float:
    """V8 健康分：越健康越靠前排队。L3=1.0 L2=0.8 L1=0.6 L?=0.3 其余=0。"""
    return {"L3": 1.0, "L2": 0.8, "L1": 0.6, "L?": 0.3}.get((prev or {}).get("level"), 0.0)


def _should_test_this_round(prev: dict, round_idx: int) -> bool:
    """V7 增量验活分档：按上轮健康分三档降频。

      前20%（L3/L2 健康源）每轮都测；
      中60%（L1/L?）隔轮测（round_idx 偶数）；
      后20%（L0/失败 streak 高）三轮测一次。
    无历史记录的新源一律每轮测（必须先建立基线）。
    """
    if not prev:
        return True
    lvl = prev.get("level")
    streak = int(prev.get("fail_streak", 0) or 0)
    if lvl in ("L3", "L2"):
        return True                       # 头部健康源：每轮
    if lvl in ("L1", "L?"):
        return round_idx % 2 == 0         # 中部：隔轮
    # 尾部（L0/S0/失败 streak≥2）：三轮一次
    return round_idx % 3 == 0


def _dedup_by_api_ext(to_test: list):
    """V3 同 API 端点去重：按 (api, ext) 分组，只 submit 代表任务，
    结果广播给同组其余站点（同接口不同 key 的站，实测结论完全一致）。

    返回 (representatives, broadcast_map)：
      representatives  实际要 submit 的站点列表（每组第一个）
      broadcast_map    {代表api_ext_key: [同组其余站点]}
    """
    groups = {}
    order = []
    for s in to_test:
        api = s.get("api") or ""
        ext = s.get("ext") or ""
        if isinstance(ext, dict):
            ext = json.dumps(ext, ensure_ascii=False, sort_keys=True)
        key = (api, str(ext))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(s)
    reps, broadcast = [], {}
    for key in order:
        members = groups[key]
        reps.append(members[0])
        if len(members) > 1:
            broadcast[id(members[0])] = members[1:]
    return reps, broadcast


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="tvbox.json", help="合并产物配置")
    ap.add_argument("--out", default="probe/sites_probe.json")
    ap.add_argument("--repo", default=".", help="仓库根（用于静态检查）")
    ap.add_argument("--only", default="all", choices=["all", "http", "js", "csp"])
    ap.add_argument("--limit", type=int, default=0, help="每类最多测多少个")
    ap.add_argument("--concurrency", type=int, default=PROBE_CONCURRENCY_DEFAULT)
    ap.add_argument("--quota", type=int, default=PROBE_QUOTA_DEFAULT,
                    help="每轮最多实测代表数（0=不限量）；超限时优先 unknown 源并按天轮转")
    ap.add_argument("--keywords", default=",".join(KEYWORDS))
    ap.add_argument("--shallow", action="store_true", help="只跑 L1，不跑 L2/L3")
    ap.add_argument("--force", action="store_true",
                    help="强制全量实测，跳过缓存复用（默认复用 24h 内 healthy 且 <2s 的上轮结论）")
    ap.add_argument("--proxy", default=os.environ.get("PROBE_PROXY", ""),
                    help="本地测试代理，如 http://127.0.0.1:7890（国内直连被阻断时使用）")
    args = ap.parse_args()

    if args.proxy:
        urllib.request.install_opener(urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": args.proxy, "https": args.proxy})))
        print(f"[probe] 走代理 {args.proxy}", flush=True)

    repo = os.path.abspath(args.repo)
    with open(os.path.join(repo, args.input), encoding="utf-8") as f:
        doc = json.load(f)
    sites = doc.get("sites") or []
    manifest_path = os.path.join(repo, "deps", "manifest.json")
    manifest = {}
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            manifest = {}
    if not manifest and doc.get("spider"):
        manifest = {"spider": doc.get("spider")}

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    http_sites, other_sites = [], []
    for s in sites:
        api = s.get("api")
        if s.get("type") in (0, 1) and isinstance(api, str) and api.startswith("http"):
            http_sites.append(s)
        else:
            other_sites.append(s)
    if args.limit:
        http_sites = http_sites[: args.limit]

    print(f"[probe] 站点 {len(sites)}：http 型 {len(http_sites)}，静态类 {len(other_sites)}", flush=True)
    results = []

    # ---- 缓存复用：24h 内 healthy 且 <2s 的源跳过实测 ----
    out_path = os.path.join(repo, args.out)
    prev_cache = {}
    prev_generated_at = ""
    if not args.force:
        try:
            with open(out_path, encoding="utf-8") as f:
                prev_generated_at = (json.load(f).get("summary") or {}).get("generated_at", "")
        except (OSError, json.JSONDecodeError):
            prev_generated_at = ""
        prev_cache = load_probe_cache(out_path)

    cached_count = 0
    cache_hit_rate = 0.0
    if args.only in ("all", "http"):
        # V10：缓存命中率统计（分子/分母）
        cache_denom = len(http_sites)
        to_test, reused = [], []
        # V7 增量验活分档：用本轮 round_idx（按天递增）决定中部/尾部源是否跳过
        round_idx = 0
        if prev_generated_at:
            try:
                round_idx = int(time.mktime(time.strptime(prev_generated_at, "%Y-%m-%d %H:%M:%S")) / 86400)
            except ValueError:
                round_idx = 0
        for s in http_sites:
            prev = prev_cache.get(s.get("api"))
            if args.force:
                to_test.append(s)
                continue
            if prev is not None and cache_hit(prev, prev_generated_at):
                reused.append((s, prev))
            elif prev is not None and not _should_test_this_round(prev, round_idx):
                # V7：本轮不该测的档（中部隔轮/尾部三轮），沿用上轮结论算复用
                reused.append((s, prev))
            else:
                to_test.append(s)
        cached_count = len(reused)
        cache_hit_rate = round(100 * cached_count / max(cache_denom, 1), 1)

        # V3：同 (api, ext) 分组，只 submit 代表任务，结果广播同组其余站点
        reps, broadcast = _dedup_by_api_ext(to_test)
        dedup_saved = len(to_test) - len(reps)

        # V8：提交前按 (健康分 desc, 历史 ms asc) 排序——健康的快源先测，慢源压后
        def _submit_order(s):
            prev = prev_cache.get(s.get("api")) or {}
            hs = _health_score(prev)
            ms = ((prev.get("l1") or {}).get("ms") if isinstance(prev, dict) else None) or 99999
            return (-hs, ms)
        reps.sort(key=_submit_order)

        # P0-2 配额轮转：限时优先补 unknown——无历史源的站按天偏移轮转窗口，
        # 保证 ceil(unknown/配额) 轮内全覆盖；被跳过的有档站沿用上轮结论，
        # 无档站记 L? 占位（skipped_by_quota），下一轮继续轮转。
        if args.quota > 0 and len(reps) > args.quota:
            never = [s for s in reps if not prev_cache.get(s.get("api"))]
            known = [s for s in reps if prev_cache.get(s.get("api"))]
            off = round_idx % max(len(never), 1)
            rot = never[off:] + never[:off]
            picked = rot[:args.quota]
            picked_ids = {id(s) for s in picked}
            picked += [s for s in known if id(s) not in picked_ids][:args.quota - len(picked)]
            picked_ids = {id(s) for s in picked}
            skipped_no_prev = 0
            for s in reps:
                if id(s) in picked_ids:
                    continue
                prev = prev_cache.get(s.get("api"))
                if prev is not None:
                    reused.append((s, prev))
                else:
                    skipped_no_prev += 1
                    results.append({"key": s.get("key"), "name": s.get("name"), "api": s.get("api"),
                                    "kind": "http", "level": "L?", "skipped_by_quota": True,
                                    "tested_at": now})
            print(f"[probe] PROBE_QUOTA={args.quota}：本轮实测 {len(picked)} 代表"
                  f"（unknown 池 {len(never)}，窗口偏移 {off}），跳过 {len(reps)-len(picked)}"
                  f"（其中无历史 {skipped_no_prev}）", flush=True)
            reps = picked
            cached_count = len(reused)
            cache_hit_rate = round(100 * cached_count / max(cache_denom, 1), 1)

        print(f"[probe] L1-L3 实测代表 {len(reps)} 个（并发 {args.concurrency}，热词 {keywords}）"
              f"，V3 分组省去 {dedup_saved} 个重复任务，缓存/分档复用 {cached_count} 个"
              f"（命中率 {cache_hit_rate}%）{'（--force 全量）' if args.force else ''}...", flush=True)
        t0 = time.time()
        with cf.ThreadPoolExecutor(args.concurrency) as ex:
            futs = {}
            for s in reps:
                prev = prev_cache.get(s.get("api")) or {}
                prev_ms = (prev.get("l1") or {}).get("ms")
                futs[ex.submit(probe_http_site, s, keywords, not args.shallow, prev_ms)] = s
            done = 0
            for fut in cf.as_completed(futs):
                try:
                    r = fut.result()
                except Exception as e:  # noqa: BLE001
                    s = futs[fut]
                    r = {"key": s.get("key"), "name": s.get("name"), "api": s.get("api"),
                         "kind": "http", "level": "L0", "error": f"{type(e).__name__}: {e}"[:120]}
                r["tested_at"] = now
                prev = prev_cache.get(r.get("api")) or {}
                prev_streak = int(prev.get("fail_streak", 0) or 0)
                r["fail_streak"] = 0 if r["level"] in HEALTHY_LEVELS else prev_streak + 1
                if detect_ad_heuristic(r.get("l1") or {}):
                    r["ad_warn"] = True
                results.append(r)
                for sib in broadcast.get(id(futs[fut]), []):
                    br = dict(r)
                    br["key"] = sib.get("key")
                    br["name"] = sib.get("name")
                    br["broadcast_from"] = r.get("key")
                    results.append(br)
                done += 1
                if done % 25 == 0:
                    print(f"  ... {done}/{len(reps)} ({time.time()-t0:.0f}s)", flush=True)
        for s, prev in reused:
            r = dict(prev)
            r["cached"] = True
            results.append(r)

    # V11：源突变检测（只标记，不剔除）
    anomaly_keys = detect_source_anomaly(results, repo)
    if anomaly_keys:
        print(f"[probe] V11 源突变标记 {len(anomaly_keys)} 个源（分类数/影片数环比 ±50%）", flush=True)

    if args.only in ("all", "js", "csp"):
        for s in other_sites:
            results.append(static_check(s, repo, manifest))

    by_level = {}
    for r in results:
        by_level[r["level"]] = by_level.get(r["level"], 0) + 1

    http_res = [r for r in results if r.get("kind") == "http"]
    summary = {
        "generated_at": now,
        "sites_total": len(sites),
        "http_tested": len(http_res),
        "http_cached": cached_count,
        "cache_hit_rate": cache_hit_rate,
        "anomaly_flagged": len(anomaly_keys),
        "levels": dict(sorted(by_level.items())),
        "http_levels": {lv: sum(1 for r in http_res if r["level"] == lv) for lv in ("L3", "L2", "L1", "L0", "L?")},
        "static_levels": {lv: sum(1 for r in results if r["level"] == lv and r.get("kind") != "http")
                          for lv in ("S1", "S0", "S?")},
    }
    out = {"summary": summary, "sites": results}
    os.makedirs(os.path.dirname(os.path.join(repo, args.out)) or ".", exist_ok=True)
    with open(os.path.join(repo, args.out), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"[probe] 完成：{summary['http_levels']}（http 型四级分布） 静态：{summary['static_levels']}"
          f" 缓存跳过：{cached_count}（命中率 {cache_hit_rate}%）")
    print(f"[probe] 产物 -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
