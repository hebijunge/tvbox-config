#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox 配置每日拉取合并脚本 v2（stdlib only，无第三方依赖）

流程：拉取上游清单（一上游一适配器）→ 内容质量门槛（最小字节/行数 + sha256 指纹）
      → 连续不过自动停用（黑白名单三层）→ 合并去重（按 key，先到先得不覆盖）
      → 测速验活（type 0/1 直连站点）→ 失效自动剔除
      → 直播源分类测速优选（央视/卫视/港台分组 txt）
      → 快照存档（snapshot/<日期>/）→ 输出 tvbox.json / list.json / status.json / checks.json
      → README 可用性锚点回写

对应第二期调研路线图：
  P0 上游验活门槛（joevess 教训 + Guovin 机制）
  P0 直播源上游收编（Guovin/iptv-api gd 分支 + Releases 双通道）
  P1 每日快照存档（kimwang1978/collect-txt 模式）
  P1 黑白名单分文件（kimwang + Guovin 模式）
  P1 分类测速优选（Supprise0901/TVBox_live 模式）
  P1 checks.json 校验产物 + 内容指纹 + 通过时间（azhansy/ds-tvbox 模式）
  P2 一上游一适配器（HerbertHe/iptv-sources 模式）
  P2 域名替换层（hl128k/tvbox 思路）
"""
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import urllib.error
import concurrent.futures as cf
from datetime import datetime, timezone, timedelta

BEIJING = timezone(timedelta(hours=8))
UA = {"User-Agent": "okhttp/3.15", "Accept": "*/*"}
FETCH_TIMEOUT = 15          # 单次拉取超时（秒）
TEST_TIMEOUT = 6            # 站点验活单次超时（秒）
CONCURRENCY = int(os.environ.get("CONCURRENCY", "20"))
MAX_BODY = 4096             # 验活最多读取字节数
GHPROXY = "https://ghproxy.net/"

REPO_RAW = "https://raw.githubusercontent.com/hebijunge/tvbox-config/main"

# ---- P0：内容质量门槛参数 ----
MIN_BYTES_TVBOX = int(os.environ.get("MIN_BYTES_TVBOX", "512"))    # 配置类上游最小字节数
MIN_ITEMS_TVBOX = int(os.environ.get("MIN_ITEMS_TVBOX", "1"))      # 至少含多少条 sites/lives/parses
MIN_BYTES_M3U = int(os.environ.get("MIN_BYTES_M3U", "1024"))       # m3u 类上游最小字节数
MIN_ENTRIES_M3U = int(os.environ.get("MIN_ENTRIES_M3U", "50"))     # m3u 至少多少条频道

# ---- P0/P1：连续失败自动停用（黑白名单）----
STATE_FILE = os.environ.get("STATE_FILE", "state/upstreams_state.json")
BLACKLIST_AUTO = os.environ.get("BLACKLIST_AUTO", "state/blacklist_auto.txt")
BLACKLIST_MANUAL = os.environ.get("BLACKLIST_MANUAL", "state/blacklist_manual.txt")
WHITELIST_MANUAL = os.environ.get("WHITELIST_MANUAL", "state/whitelist_manual.txt")
FAIL_LIMIT = int(os.environ.get("UPSTREAM_FAIL_LIMIT", "3"))       # 连续 N 次不达标自动停用

# ---- P1：快照存档 ----
SNAPSHOT_DIR = os.environ.get("SNAPSHOT_DIR", "snapshot")
SNAPSHOT_RETENTION_DAYS = int(os.environ.get("SNAPSHOT_RETENTION_DAYS", "14"))

# ---- P1：直播分类测速优选 ----
LIVE_SPEEDTEST = os.environ.get("LIVE_SPEEDTEST", "1") == "1"
LIVE_TIMEOUT = int(os.environ.get("LIVE_TIMEOUT", "4"))
LIVE_CONCURRENCY = int(os.environ.get("LIVE_CONCURRENCY", "24"))
LIVE_MAX_URLS = int(os.environ.get("LIVE_MAX_URLS", "1200"))       # 单轮测速 URL 总量上限
LIVE_PER_CHANNEL = int(os.environ.get("LIVE_PER_CHANNEL", "3"))    # 每频道保留条数
LIVES_DIR = os.environ.get("LIVES_DIR", "lives")
CHECKS_FILE = os.environ.get("CHECKS_FILE", "checks.json")
DOMAIN_MAP_FILE = os.environ.get("DOMAIN_MAP_FILE", "state/domain_map.json")
README_FILE = os.environ.get("README_FILE", "README.md")

# 上游清单（点播配置类）：顺序即合并优先级，同名 key 先到先得、后续不覆盖（不误伤已有源）
# 一上游一适配器：kind 决定拉取后如何解析（tvbox=json 配置 / m3u=直播列表）
UPSTREAMS = [
    {"name": "juhe-tvapi", "kind": "tvbox",
     "url": "https://raw.githubusercontent.com/ccAzy/juhe-tvapi/main/config.json"},
    {"name": "qist/jsm", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/jsm.json"},
    {"name": "qist/js", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/js.json"},
    {"name": "qist/dianshi", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/dianshi.json"},
    {"name": "qist/fty", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/fty.json"},
    {"name": "qist/XYQ", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/XYQ.json"},
    {"name": "qist/0821", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0821.json"},
    {"name": "qist/0825", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0825.json"},
    {"name": "qist/0826", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0826.json"},
    {"name": "qist/0827", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0827.json"},
    {"name": "qist/367", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/367.json"},
    {"name": "qist/9918", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/9918.json"},
    {"name": "qist/99188", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/99188.json"},
    {"name": "gao/js", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/js.json"},
    {"name": "gao/XYQ", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/XYQ.json"},
    {"name": "gao/0821", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0821.json"},
    {"name": "gao/0825", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0825.json"},
    {"name": "gao/0826", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0826.json"},
    {"name": "gao/0827", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0827.json"},
    {"name": "cluntop/jsm", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/jsm.json"},
    {"name": "cluntop/box", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/box.json"},
    {"name": "cluntop/fun", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/fun.json"},
    {"name": "cluntop/aa", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/aa.json"},
    {"name": "cluntop/bb", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/bb.json"},
    {"name": "cluntop/wv", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/wv.json"},
    {"name": "cluntop/yt", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/yt.json"},
    {"name": "cluntop/test", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/test.json"},
    {"name": "nxppru/jsm", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/jsm.json"},
    {"name": "nxppru/js", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/js.json"},
    {"name": "nxppru/dianshi", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/dianshi.json"},
    {"name": "nxppru/fty", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/fty.json"},
    {"name": "nxppru/XYQ", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/XYQ.json"},
    {"name": "nxppru/0821", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0821.json"},
    {"name": "nxppru/0825", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0825.json"},
    {"name": "nxppru/0826", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0826.json"},
    {"name": "nxppru/0827", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0827.json"},
    {"name": "top98", "kind": "tvbox", "url": "http://home.jundie.top:81/top98.json"},
]

# P0：直播源上游（Guovin/iptv-api 双通道产物，2026-09-17 实测 200 且为社区公共上游）
LIVE_UPSTREAMS = [
    {"name": "guovin-gd-ipv4", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/ipv4/result.m3u"},
    {"name": "guovin-release", "kind": "m3u",
     "url": "https://github.com/Guovin/iptv-api/releases/download/playlist-latest/result.m3u"},
]

ALL_UPSTREAMS = UPSTREAMS + LIVE_UPSTREAMS

UPSTREAM_BASES = {u["name"]: u["url"].rsplit("/", 1)[0] + "/" for u in UPSTREAMS if u.get("kind") == "tvbox"}


# ==================== 依赖收集（jar / js / json 库文件） ====================
DEPS_DIR = "deps"
MANIFEST_PATH = os.path.join(DEPS_DIR, "manifest.json")
DEP_TIMEOUT = 25
DEP_MAX_BYTES = 8 * 1024 * 1024
DEP_CONCURRENCY = int(os.environ.get("DEP_CONCURRENCY", "8"))
# 沙箱/CI 网络受限时可跳过站点验活或强制用缓存
SKIP_SITE_TEST = os.environ.get("SKIP_SITE_TEST", "0") == "1"
SKIP_REFRESH = os.environ.get("SKIP_REFRESH", "0") == "1"

_IDNA_CACHE = {}


def _idna_host(host: str) -> str:
    """中文域名手动 punycode（urllib 对部分中文域名内置 idna 会抛错）。"""
    if host.isascii():
        return host
    if host in _IDNA_CACHE:
        return _IDNA_CACHE[host]
    labels = []
    for lab in host.split("."):
        if lab.isascii():
            labels.append(lab)
        else:
            try:
                labels.append("xn--" + lab.encode("punycode").decode())
            except Exception:
                labels.append(lab)
    out = ".".join(labels)
    _IDNA_CACHE[host] = out
    return out


def dep_lenient_json(text: str) -> bool:
    if text.startswith("\ufeff"):
        text = text[1:]
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        json.loads(text)
        return True
    except Exception:
        return False


def dep_classify(kind_hint: str, content: bytes) -> str:
    """按内容判定依赖类型: jar / js / json / unknown（伪装扩展名靠内容识别）。"""
    if content[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "jar"
    if content[:3] == b"dex\n":
        return "jar"
    if content[:2] == b"\x1f\x8b":
        return "data"  # gzip 数据文件（如 pikpakclass.db.gz 分享码库）
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return "unknown"
    low = text[:2000].lower()
    if "<html" in low or "<!doctype" in low:
        return "unknown"
    if kind_hint == "json":
        try:
            json.loads(text)
            return "json"
        except Exception:
            return "json" if dep_lenient_json(text) else "data"
    if re.search(r"\b(function|var|let|const|import|export|require)\b", text[:4000]) or "=>" in text[:1000]:
        return "js"
    return "data"  # 其余可解码纯文本（TSV 分享码库等）视为数据文件


def dep_download(url: str):
    """原 URL → ghproxy 兜底。返回 (bytes, channel) 或 (None, err)。"""
    import urllib.parse
    attempts = [url]
    wrapped = gh_url(url) if "github" in url else url
    if wrapped != url:
        attempts.append(wrapped)
    elif re.match(r"^https?://(raw\.)?githubusercontent\.com/", url):
        attempts.append(GHPROXY + url)
    attempts = [
        urllib.parse.quote(u, safe="%/:=&?~#+!$,;'@()*[]|") if not u.isascii() else u
        for u in attempts
    ]
    last = ""
    for u in attempts:
        try:
            status, data, _ = http_get(u, DEP_TIMEOUT, DEP_MAX_BYTES)
            if status == 200 and data:
                return data, ("direct" if u == attempts[0] else "ghproxy")
            last = f"HTTP {status}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"[:120]
    return None, last


def is_file_ref(v: str):
    """识别配置字符串里的依赖文件引用。返回 ('rel'|'abs', path) 或 None。"""
    v = v.strip()
    if not v or "{name}" in v or "{cateId}" in v or "{catePg}" in v:
        return None
    base = v.split(";")[0]
    if "$$$" in base:
        return None
    if base.startswith("./") or base.startswith("../") or base.startswith("/"):
        return ("rel", base)
    if re.match(r"^https?://", base):
        host = urllib.parse.urlparse(base).netloc
        if "127.0.0.1" in host or "localhost" in host:
            return None
        path = base.split("?")[0].lower()
        if path.endswith((".js", ".jar", ".zip", ".php")):
            return ("abs", base)
    return None


def dep_local_path(origin: str, url: str) -> str:
    if origin == "remote":
        name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or ""
        if not name or len(name) > 80:
            name = hashlib.md5(url.encode()).hexdigest()[:12]
        return f"{DEPS_DIR}/remote/{name}"
    u = urllib.parse.urlparse(url)
    segs = u.path.lstrip("/").split("/")
    if u.netloc == "raw.githubusercontent.com" and len(segs) > 3:
        segs = segs[3:]  # 剥离 owner/repo/branch，路径与仓库已入库布局一致
    path = "/".join(segs)
    if not path:
        path = hashlib.md5(url.encode()).hexdigest()[:12]
    return f"{DEPS_DIR}/{origin}/{path}"


def load_manifest() -> dict:
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def collect_and_rewrite_deps(tvbox: dict, site_origin: dict, spider_origin: dict):
    """收集 tvbox 配置中的 jar/js/json 依赖到 deps/ 并把引用改写为仓库相对路径。
    site_origin: key -> origin 名；spider_origin: (origin 名, base url)
    返回统计 dict；同时更新 deps/manifest.json。"""
    import urllib.parse

    manifest = load_manifest()
    now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S +08:00")

    # ---- 1. 生成 (origin, url) 待收集清单 ----
    entries = []  # (kind_hint, url, origin)

    def add_ref(kind_hint: str, ref: str, origin: str, base: str):
        r = is_file_ref(ref)
        if not r:
            return
        where, pathv = r
        url = urllib.parse.urljoin(base, pathv) if where == "rel" else pathv
        e = (kind_hint, url, origin)
        if e not in entries:
            entries.append(e)

    if isinstance(tvbox.get("spider"), str) and spider_origin:
        add_ref("jar", tvbox["spider"].split(";md5;")[0], spider_origin[0], spider_origin[1])
    for s in tvbox.get("sites", []):
        origin = site_origin.get(s.get("key"))
        if not origin:
            continue
        base = UPSTREAM_BASES.get(origin, "")
        if not base:
            continue
        for field in ("jar", "ext"):
            v = s.get(field)
            if isinstance(v, str):
                hint = "jar" if field == "jar" else ("js" if v.lower().split("?")[0].endswith(".js") else "json")
                for seg in (v.split("$$$") if "$$$" in v else [v]):
                    add_ref(hint, seg, origin, base)
            elif isinstance(v, dict):
                for v2 in v.values():
                    if isinstance(v2, str):
                        for seg in (v2.split("$$$") if "$$$" in v2 else [v2]):
                            add_ref("json", seg, origin, base)

    # ---- 2. 并发下载/校验/入库 ----
    def work(e):
        kind_hint, url, origin = e
        lp = dep_local_path(origin, url)
        fp = os.path.join(lp)
        rec = {"key": f"{origin}|{url}", "url": url, "origin": origin, "local": lp,
               "ok": False, "kind": "", "md5": "", "size": 0, "err": "", "channel": ""}
        if os.path.exists(fp) and os.path.getsize(fp) > 0:
            content = open(fp, "rb").read()
        else:
            content, ch = dep_download(url)
            rec["channel"] = ch if content else str(ch)
            if content is None:
                rec["err"] = str(ch)
                return rec
        hint = {"jar": "jar", "zip": "jar", "js": "js", "json": "json", "php": "jar"}.get(
            url.lower().split("?")[0].rsplit(".", 1)[-1], "")
        kind = dep_classify(hint, content)
        rec["kind"] = kind
        rec["size"] = len(content)
        rec["md5"] = hashlib.md5(content).hexdigest()
        if kind == "unknown":
            rec["err"] = f"content not js/jar/json ({content[:24]!r})"
            return rec
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "wb").write(content)
        rec["ok"] = True
        return rec

    ok_map: dict = {}
    print(f"[deps] 收集 {len(entries)} 个依赖（并发 {DEP_CONCURRENCY}）...", flush=True)
    with cf.ThreadPoolExecutor(DEP_CONCURRENCY) as ex:
        futs = {ex.submit(work, e): e for e in entries}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            rec = fut.result()
            if rec["ok"]:
                ok_map[rec["key"]] = rec
            if i % 50 == 0:
                print(f"  ... {i}/{len(entries)}", flush=True)

    # ---- 3. 失败项回退：manifest 缓存 ----
    for e in entries:
        key = f"{e[2]}|{e[1]}"
        if key not in ok_map and SKIP_REFRESH and key in manifest:
            m = manifest[key]
            if os.path.exists(m["local"]):
                ok_map[key] = {"key": key, "url": e[1], "origin": e[2], "local": m["local"],
                               "ok": True, "kind": m["kind"], "md5": m["md5"],
                               "size": m.get("size", 0), "err": "", "channel": "manifest-cache"}

    # ---- 4. 改写引用 ----
    stats = {"total": len(entries), "collected": len(ok_map), "rewritten": 0, "kept": 0, "spider": 0}
    missing = []

    def md5_of(local: str):
        if not os.path.exists(local):
            missing.append(local)
            return None
        with open(local, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    if isinstance(tvbox.get("spider"), str) and spider_origin:
        key = f"{spider_origin[0]}|{tvbox['spider'].split(';md5;')[0] if is_file_ref(tvbox['spider'].split(';md5;')[0]) else tvbox['spider']}"
        # spider 的 url 已在 entries 里以 (origin, base) 生成，直接按 url 查
        sk = None
        for e in entries:
            if e[2] == spider_origin[0] and e[0] == "jar":
                sk = ok_map.get(f"{e[2]}|{e[1]}")
                if sk:
                    break
        if sk:
            md5v = md5_of(sk["local"])
            if md5v:
                tvbox["spider"] = f"./{sk['local']};md5;{md5v}"
                stats["spider"] = 1

    for s in tvbox.get("sites", []):
        origin = site_origin.get(s.get("key"))
        if not origin:
            continue
        for field in ("jar", "ext"):
            v = s.get(field)
            vals = []
            if isinstance(v, str):
                vals = [(field, None, v)]
            elif isinstance(v, dict):
                vals = [(field, k2, v2) for k2, v2 in v.items() if isinstance(v2, str)]
            for f0, k2, raw in vals:
                if "$$$" in raw:
                    segs = raw.split("$$$")
                    changed = False
                    for si, seg in enumerate(segs):
                        r = is_file_ref(seg)
                        if not r:
                            continue
                        base2 = UPSTREAM_BASES.get(origin, "")
                        url2 = urllib.parse.urljoin(base2, r[1]) if r[0] == "rel" else r[1]
                        rec2 = ok_map.get(f"{origin}|{url2}")
                        if not rec2:
                            continue
                        md52 = md5_of(rec2["local"])
                        if md52 is None:
                            continue
                        segs[si] = f"./{rec2['local']}"
                        changed = True
                        stats["rewritten"] += 1
                    if changed:
                        if k2 is None:
                            s[f0] = "$$$".join(segs)
                        else:
                            s[f0][k2] = "$$$".join(segs)
                    continue
                r = is_file_ref(raw)
                if not r:
                    continue
                base = UPSTREAM_BASES.get(origin, "")
                url = urllib.parse.urljoin(base, r[1]) if r[0] == "rel" else r[1]
                rec = ok_map.get(f"{origin}|{url}")
                if not rec:
                    stats["kept"] += 1
                    continue
                md5v = md5_of(rec["local"])
                if md5v is None:
                    stats["kept"] += 1
                    continue
                if f0 == "jar":
                    had = ";md5;" in raw
                    new = f"./{rec['local']};md5;{md5v}" if had else f"./{rec['local']}"
                    if k2 is None:
                        s[f0] = new
                    else:
                        s[f0][k2] = new
                else:
                    new = f"./{rec['local']}"
                    if k2 is None:
                        s[f0] = new
                    else:
                        s[f0][k2] = new
                stats["rewritten"] += 1
    if missing:
        print(f"  [deps] WARN 缺失本地文件 {len(missing)} 个，如 {missing[:3]}", flush=True)

    # ---- 5. 更新 manifest ----
    for rec in ok_map.values():
        manifest[rec["key"]] = {"url": rec["url"], "origin": rec["origin"], "local": rec["local"],
                                "md5": rec["md5"], "kind": rec["kind"], "size": rec["size"],
                                "channel": rec.get("channel", ""), "updated_at": now}
    os.makedirs(DEPS_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"[deps] 完成：收集 {stats['collected']}/{stats['total']}，改写 {stats['rewritten']} 处引用，"
          f"spider {'已修复' if stats['spider'] else '未变'}", flush=True)
    return stats


def strip_comments_and_clean(text: str) -> str:
    """去 BOM、去行注释与块注释（状态机，不误伤字符串内双斜杠）、去尾随逗号。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    cleaned = "".join(out)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


def gh_url(u: str) -> str:
    """GitHub 链接换 ghproxy 通道（脚本拉取用备用通道）。"""
    if "ghproxy" in u:
        return u
    if re.match(r"^https?://(raw\.)?githubusercontent\.com/", u) or re.match(
        r"^https?://github\.com/[^/]+/[^/]+/(raw|releases|archive)/", u
    ):
        return GHPROXY + u
    return u


def http_get(url: str, timeout: int, max_bytes: int = 0):
    """返回 (status, bytes, elapsed_ms)。非 2xx 抛异常。"""
    req = urllib.request.Request(url, headers=UA)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(max_bytes) if max_bytes else r.read()
    return r.status, data, int((time.time() - t0) * 1000)


# ---------------- P2：域名替换层 ----------------

def load_domain_map() -> dict:
    try:
        with open(DOMAIN_MAP_FILE, "r", encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m, dict):
            return {str(k): str(v) for k, v in m.items() if k and v and not str(k).startswith("_")}
    except Exception:  # noqa: BLE001
        pass
    return {}


DOMAIN_MAP = {}


def map_domain(value):
    """对 URL 字符串应用 state/domain_map.json 的域名/前缀替换（上游换域名时改写而非丢源）。"""
    if not DOMAIN_MAP or not isinstance(value, str):
        return value
    for old, new in DOMAIN_MAP.items():
        if old in value:
            value = value.replace(old, new)
    return value


# ---------------- P0：拉取与解析（一上游一适配器） ----------------

def fetch_raw(url: str):
    """两通道重试：直连 → ghproxy（仅 GitHub 链接）。返回 (raw_bytes, channel) 或 (None, err)。"""
    attempts = [url]
    if "github" in url:
        attempts.append(gh_url(url))
    last_err = ""
    for ch, u in enumerate(attempts):
        try:
            status, raw, _ms = http_get(u, FETCH_TIMEOUT)
            return raw, ("direct" if ch == 0 else "ghproxy")
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"[:120]
    return None, last_err


def parse_tvbox(raw: bytes):
    """适配器：TVBox json 配置。返回 dict。"""
    txt = raw.decode("utf-8", "replace")
    cfg = json.loads(strip_comments_and_clean(txt))
    if not isinstance(cfg, dict):
        raise ValueError("top-level is not an object")
    return cfg


EXTINF_RE = re.compile(r"^#EXTINF:?\s*-?\d+\s*(.*)$")


def parse_m3u(raw: bytes):
    """适配器：m3u/txt 直播列表。返回 [(频道名, 分组, url)]。"""
    txt = raw.decode("utf-8", "replace")
    entries = []
    attr_name = None
    group = ""
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            m = EXTINF_RE.match(line)
            rest = m.group(1) if m else ""
            gm = re.search(r'group-title="([^"]*)"', rest)
            group = gm.group(1).strip() if gm else ""
            attr_name = rest.rsplit(",", 1)[-1].strip() if "," in rest else rest.strip()
            continue
        if line.startswith("#"):
            continue
        if attr_name:
            entries.append((attr_name, group, line))
            attr_name = None
    return entries


PARSERS = {"tvbox": parse_tvbox, "m3u": parse_m3u}


def evaluate_upstream(u: dict, raw):
    """P0 质量门槛。返回 (ok, status, detail, error)。
    status: ok / degraded（解析成功但不达门槛，不参与合并）/ dead（拉取或解析失败）。"""
    try:
        parser = PARSERS[u["kind"]]
    except KeyError:
        return False, "dead", {}, f"unknown kind {u.get('kind')}"
    if raw is None:
        return False, "dead", {}, "fetch failed"
    if len(raw) < (MIN_BYTES_M3U if u["kind"] == "m3u" else MIN_BYTES_TVBOX):
        return False, "degraded", {}, f"too small ({len(raw)} bytes)"
    try:
        parsed = parser(raw)
    except Exception as e:  # noqa: BLE001
        return False, "dead", {}, f"{type(e).__name__}: {e}"[:120]
    if u["kind"] == "tvbox":
        n = sum(len(parsed.get(k) or []) for k in ("sites", "lives", "parses"))
        if n < MIN_ITEMS_TVBOX:
            return False, "degraded", {"items": n}, "no usable items"
        return True, "ok", {"items": n, "cfg": parsed}, ""
    else:
        if len(parsed) < MIN_ENTRIES_M3U:
            return False, "degraded", {"entries": len(parsed)}, f"only {len(parsed)} entries"
        return True, "ok", {"entries": len(parsed)}, ""


# ---------------- P0/P1：状态、黑白名单 ----------------

def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)


def read_name_list(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    except Exception:  # noqa: BLE001
        return []


def record_result(state: dict, name: str, ok: bool, whitelist_manual: list) -> str:
    """更新连续失败计数；达阈值自动停用（手动白名单保护）。返回 'ok'/'disabled_now'/'failing'。"""
    now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    ent = state.get(name) if isinstance(state.get(name), dict) else {}
    if ok:
        ent.update({"fail_count": 0, "last_ok_at": now, "disabled": False, "disabled_reason": ""})
        state[name] = ent
        return "ok"
    fc = int(ent.get("fail_count", 0)) + 1
    ent["fail_count"] = fc
    ent["last_fail_at"] = now
    disabled_now = ""
    if fc >= FAIL_LIMIT and name not in whitelist_manual and not ent.get("disabled"):
        ent["disabled"] = True
        ent["disabled_reason"] = f"连续 {fc} 次不达标，自动停用"
        disabled_now = "disabled_now"
    state[name] = ent
    return disabled_now or "failing"


def sync_blacklist_auto(state: dict):
    """把自动停用的上游回写 blacklist_auto.txt（自动层）。"""
    names = sorted(n for n, v in state.items() if isinstance(v, dict) and v.get("disabled"))
    os.makedirs(os.path.dirname(BLACKLIST_AUTO) or ".", exist_ok=True)
    with open(BLACKLIST_AUTO, "w", encoding="utf-8") as f:
        f.write("# 自动黑名单：连续不达标自动停用的上游（由脚本维护，勿手工编辑）\n")
        for n in names:
            f.write(n + "\n")


def enabled_of(u: dict, state: dict, blacklist_manual: list, whitelist_manual: list):
    """返回 (是否拉取, 状态标签)。手动黑名单 > 自动停用（白名单可豁免自动停用）> 启用。"""
    name = u["name"]
    if name in blacklist_manual:
        return False, "blacklisted"
    ent = state.get(name) if isinstance(state.get(name), dict) else {}
    if ent.get("disabled") and name not in whitelist_manual:
        return False, "disabled"
    return True, "enabled"


# ---------------- P1：快照存档 ----------------

def snapshot_save(name: str, kind: str, raw: bytes, now: datetime) -> str:
    date_dir = os.path.join(SNAPSHOT_DIR, now.strftime("%Y-%m-%d"))
    os.makedirs(date_dir, exist_ok=True)
    ext = "m3u" if kind == "m3u" else "json"
    path = os.path.join(date_dir, f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}__{now.strftime('%H%M%S')}.{ext}")
    with open(path, "wb") as f:
        f.write(raw)
    return path


def snapshot_prune(keep_days: int) -> list:
    """只保留最近 keep_days 个日期目录，控制仓库体积。"""
    if not os.path.isdir(SNAPSHOT_DIR) or keep_days <= 0:
        return []
    dates = sorted(d for d in os.listdir(SNAPSHOT_DIR)
                   if os.path.isdir(os.path.join(SNAPSHOT_DIR, d)) and re.match(r"^\d{4}-\d{2}-\d{2}$", d))
    removed = []
    for d in dates[:-keep_days]:
        shutil.rmtree(os.path.join(SNAPSHOT_DIR, d), ignore_errors=True)
        removed.append(d)
    return removed


# ---------------- P1：直播分类测速优选 ----------------

def category_of(channel: str, group: str) -> str:
    text = f"{group} {channel}"
    up = text.upper()
    if re.search(r"CCTV|CGTN|CETV|央视", up):
        return "cctv"
    if "卫视" in text:
        return "weishi"
    if re.search(r"香港|台湾|凤凰|TVB|翡翠|明珠|澳门|港台|星空|华视|中天|东森|民视|三立|TVBS|HKTW|HK\b|TW\b", up):
        return "gangtai"
    return "other"


CATEGORY_LABELS = [("cctv", "央视"), ("weishi", "卫视"), ("gangtai", "港台"), ("other", "其他")]


def speed_test(entries, limit: int) -> dict:
    """并发测速，返回 {url: latency_ms}（失败的 URL 不在结果里）。"""
    urls = []
    seen = set()
    for _name, _group, url in entries:
        if url not in seen:
            seen.add(url)
            urls.append(url)
    if limit > 0 and len(urls) > limit:
        urls = urls[:limit]  # 顺序即上游优先级，截前 limit 个
    lat = {}
    print(f"    测速 {len(urls)} 条直播 URL（并发 {LIVE_CONCURRENCY}，单条 {LIVE_TIMEOUT}s）...", flush=True)

    def probe(u):
        try:
            st, body, ms = http_get(u, LIVE_TIMEOUT, 2048)
            if st == 200 and body:
                return u, ms
        except Exception:  # noqa: BLE001
            pass
        return u, None

    with cf.ThreadPoolExecutor(LIVE_CONCURRENCY) as ex:
        for u, ms in ex.map(probe, urls):
            if ms is not None:
                lat[u] = ms
    return lat


def build_live_outputs(entries) -> dict:
    """分类 →（可选测速排序）→ 每频道取前 N 条 → 输出 lives/*.txt。返回分类统计 dict。"""
    os.makedirs(LIVES_DIR, exist_ok=True)
    lat = speed_test(entries, LIVE_MAX_URLS) if LIVE_SPEEDTEST else {}

    per_cat = {k: [] for k, _ in CATEGORY_LABELS}
    for name, group, url in entries:
        per_cat[category_of(name, group)].append((name, url))

    stats = {}
    for key, label in CATEGORY_LABELS:
        items = per_cat[key]
        if lat:
            by_ch = {}
            for name, url in items:
                ms = lat.get(url)
                if ms is None:
                    continue  # 测速失败剔除
                by_ch.setdefault(name, []).append((ms, url))
            ranked = []
            for name in sorted(by_ch):
                for ms, url in sorted(by_ch[name])[:LIVE_PER_CHANNEL]:
                    ranked.append((name, url, ms))
        else:
            seen_ch = {}
            ranked = []
            for name, url in items:
                seen_ch.setdefault(name, [])
                if len(seen_ch[name]) < LIVE_PER_CHANNEL:
                    seen_ch[name].append(url)
                    ranked.append((name, url, None))
        stats[key] = {"channels": len({n for n, _u, _ms in ranked}), "urls": len(ranked),
                      "input_urls": len(items), "speed_tested": bool(lat)}
        if not ranked:
            continue
        path = os.path.join(LIVES_DIR, f"live_{key}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{label},#genre#\n")
            for name, url, _ms in ranked:
                f.write(f"{name},{url}\n")
        print(f"    {label}: {stats[key]['channels']} 频道 / {stats[key]['urls']} 条 -> {path}", flush=True)

    with open(os.path.join(LIVES_DIR, "live.txt"), "w", encoding="utf-8") as f:
        for key, _label in CATEGORY_LABELS:
            p = os.path.join(LIVES_DIR, f"live_{key}.txt")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as pf:
                    f.write(pf.read())
    return stats


# ---------------- P1：checks.json + README 回写 ----------------

def sha12(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def write_checks(records: list, generated_at: str) -> dict:
    order = {"ok": 0, "degraded": 1, "dead": 2, "disabled": 3, "blacklisted": 4}
    recs = sorted(records, key=lambda r: order.get(r.get("status"), 5))
    doc = {
        "generated_at": generated_at,
        "note": "每条含最近检测时间、内容 sha256 指纹（前 12 位）、字节数与连续失败计数（azhansy/ds-tvbox checks.json 模式）",
        "summary": {
            "total": len(recs),
            "ok": sum(1 for r in recs if r["status"] == "ok"),
            "degraded": sum(1 for r in recs if r["status"] == "degraded"),
            "dead": sum(1 for r in recs if r["status"] == "dead"),
            "disabled": sum(1 for r in recs if r["status"] == "disabled"),
            "blacklisted": sum(1 for r in recs if r["status"] == "blacklisted"),
        },
        "upstreams": recs,
    }
    with open(CHECKS_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


ICONS = {"ok": "🟢", "degraded": "🟡", "dead": "🔴", "disabled": "⚫", "blacklisted": "🚫"}
STATUS_CN = {"ok": "可用", "degraded": "降级", "dead": "失效", "disabled": "已停用", "blacklisted": "黑名单"}


def update_readme_availability(records: list) -> bool:
    """README 内 availability:start/end 锚点间回写可用性表（laoma2053 模式）。"""
    try:
        with open(README_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:  # noqa: BLE001
        return False
    lines = ["| 上游 | 状态 | 字节数 | 指纹 | 连续失败 | 最近通过 |",
             "|------|------|--------|------|----------|----------|"]
    for r in records:
        lines.append(
            "| {name} | {icon} {st} | {bt} | `{fp}` | {fc} | {ok_at} |".format(
                name=r.get("name", ""), icon=ICONS.get(r.get("status"), "⚪"),
                st=STATUS_CN.get(r.get("status"), r.get("status", "")),
                bt=r.get("bytes", 0) or "-", fp=r.get("sha256", "") or "-",
                fc=r.get("fail_count", 0), ok_at=r.get("last_ok_at", "-") or "-"))
    table = "\n".join(lines)
    start = "<!-- availability:start -->"
    end = "<!-- availability:end -->"
    if start in content and end in content:
        pre = content.split(start, 1)[0]
        post = content.split(end, 1)[1]
        content = f"{pre}{start}\n{table}\n{end}{post}"
    else:
        content = content.rstrip() + f"\n\n## 上游可用性（自动回写）\n\n{start}\n{table}\n{end}\n"
    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    return True


# ---------------- 合并辅助（保持既有口径） ----------------

def grade_of(nsites: int, valid: bool) -> str:
    if not valid or nsites <= 0:
        return "不可用"
    if nsites >= 10:
        return "完全可用"
    return "部分可用"


def merge_key_site(s: dict):
    return s.get("key")


def merge_key_live(l: dict):
    return l.get("name")


def merge_key_parse(p: dict):
    return p.get("name")


def rewrite_gh(value):
    """对 site/live/parse 字段里的 GitHub 原链统一加 ghproxy.net 前缀（先过域名替换层）。"""
    if isinstance(value, str):
        return gh_url(map_domain(value))
    if isinstance(value, list):
        return [rewrite_gh(v) for v in value]
    if isinstance(value, dict):
        return {k: rewrite_gh(v) for k, v in value.items()}
    return value


def main() -> int:
    global DOMAIN_MAP
    DOMAIN_MAP = load_domain_map()
    now = datetime.now(BEIJING)
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S") + " +08:00"

    state = load_state()
    blacklist_manual = read_name_list(BLACKLIST_MANUAL)
    whitelist_manual = read_name_list(WHITELIST_MANUAL)

    interfaces = []          # 每条上游的测试记录（list.json，保持原字段）
    checks = []              # P1 校验状态记录（checks.json）
    merged: dict = {}        # 全局字段
    spider_origin_info = None
    site_origin_name: dict = {}   # site key -> 来源上游名
    sites_by_key: dict = {}
    lives_by_name: dict = {}
    parses_by_name: dict = {}

    print(f"[1/6] 拉取 {len(ALL_UPSTREAMS)} 个上游（含 {len(LIVE_UPSTREAMS)} 个直播源上游）...", flush=True)
    fetchable = []
    for u in ALL_UPSTREAMS:
        ok, tag = enabled_of(u, state, blacklist_manual, whitelist_manual)
        fetchable.append((u, ok, tag))

    def do_fetch(item):
        u, ok, _tag = item
        if not ok:
            return u, None, "skipped"
        raw, info = fetch_raw(u["url"])
        return u, raw, info

    with cf.ThreadPoolExecutor(min(8, CONCURRENCY)) as ex:
        fetched = list(ex.map(do_fetch, fetchable))

    snapshot_paths = []
    disabled_now_list = []
    for (u, fetchable_ok, tag), (u2, raw, info) in zip(fetchable, fetched):
        name, kind = u["name"], u["kind"]
        state_ent = state.get(name) if isinstance(state.get(name), dict) else {}
        rec = {
            "name": name, "url": u["url"], "kind": kind,
            "http_ms": 0, "channel": "", "bytes": 0, "sha256": "",
            "sites": 0, "lives": 0, "parses": 0,
            "merged_sites": 0, "merged_lives": 0, "merged_parses": 0,
            "grade": "不可用", "error": "",
            "status": tag, "fail_count": int(state_ent.get("fail_count", 0)),
            "last_ok_at": state_ent.get("last_ok_at", ""),
        }
        if not fetchable_ok:
            checks.append(rec)
            interfaces.append(rec)
            print(f"  SKIP {name}（{STATUS_CN.get(tag, tag)}）", flush=True)
            continue

        if raw is not None:
            rec["bytes"] = len(raw)
            rec["sha256"] = sha12(raw)
            snapshot_paths.append(snapshot_save(name, kind, raw, now))

        ok_eval, status_tag, detail, err = evaluate_upstream(u, raw)
        rec["status"] = status_tag
        rec["error"] = err or ""
        outcome = record_result(state, name, ok_eval, whitelist_manual)
        if outcome == "disabled_now":
            disabled_now_list.append(name)
        rec["fail_count"] = int(state[name].get("fail_count", 0))
        rec["last_ok_at"] = state[name].get("last_ok_at", "")
        if raw is None:
            rec["error"] = info

        if not ok_eval:
            checks.append(rec)
            interfaces.append(rec)
            print(f"  {'DEGRADED' if status_tag == 'degraded' else 'FAIL'} {name}: {err or info}", flush=True)
            continue

        # ---- 合并 ----
        if kind == "tvbox":
            cfg = detail["cfg"]
            cfg_sites = [s for s in (cfg.get("sites") or [])
                         if isinstance(s, dict) and s.get("key") and s.get("api")]
            cfg_lives = [l for l in (cfg.get("lives") or []) if isinstance(l, dict) and l.get("name")]
            cfg_parses = [p for p in (cfg.get("parses") or []) if isinstance(p, dict) and p.get("name")]
            added_s = added_l = added_p = 0
            for s in cfg_sites:
                k = merge_key_site(s)
                if k and k not in sites_by_key:
                    sites_by_key[k] = rewrite_gh(s)
                    site_origin_name[k] = name
                    added_s += 1
            for l in cfg_lives:
                k = merge_key_live(l)
                if k and k not in lives_by_name:
                    lives_by_name[k] = rewrite_gh(l)
                    added_l += 1
            for p in cfg_parses:
                k = merge_key_parse(p)
                if k and k not in parses_by_name:
                    parses_by_name[k] = rewrite_gh(p)
                    added_p += 1
            valid = bool(cfg_sites)
            rec.update(
                sites=len(cfg_sites), lives=len(cfg_lives), parses=len(cfg_parses),
                merged_sites=added_s, merged_lives=added_l, merged_parses=added_p,
                grade=grade_of(len(cfg_sites), valid), channel=info,
            )
            for gk in ("spider", "wallpaper"):
                if gk in cfg and gk not in merged and isinstance(cfg[gk], str):
                    merged[gk] = rewrite_gh(cfg[gk])
                    if gk == "spider":
                        spider_origin_info = (name, u["url"].rsplit("/", 1)[0] + "/")
            print(f"  OK   {name}: sites={len(cfg_sites)} lives={len(cfg_lives)} "
                  f"parses={len(cfg_parses)} (+{added_s}/{added_l}/{added_p}) "
                  f"{rec['bytes']}B #{rec['sha256']}", flush=True)
        else:
            print(f"  OK   {name}: {detail['entries']} 条频道 {rec['bytes']}B #{rec['sha256']}", flush=True)
        checks.append(rec)
        interfaces.append(rec)

    sync_blacklist_auto(state)
    save_state(state)
    if disabled_now_list:
        print(f"  本轮自动停用：{', '.join(disabled_now_list)}", flush=True)

    usable_config = [r for r in interfaces if r["kind"] == "tvbox" and r["grade"] != "不可用"]
    if not usable_config:
        print("所有配置类上游均不可用，中止（不产出配置）", flush=True)
        return 1

    sites = list(sites_by_key.values())
    lives = list(lives_by_name.values())
    parses = list(parses_by_name.values())
    print(f"[2/6] 合并完成：{len(sites)} sites / {len(lives)} lives / {len(parses)} parses", flush=True)

    # ---- [3/6] 测速验活：仅 type 0/1 且 api 为 http(s) 的直连站点 ----
    def testable(s: dict) -> bool:
        return s.get("type") in (0, 1) and isinstance(s.get("api"), str) and s["api"].startswith("http")

    def check_site(s: dict):
        url = s["api"]
        for _ in range(2):  # 失败重试一次
            try:
                status, body, _ = http_get(url, TEST_TIMEOUT, MAX_BODY)
                if status == 200 and body:
                    head = body[:1024].lstrip()
                    low = head.lower()
                    if head[:1] in (b"{", b"<") and b"<html" not in low:
                        return True
            except Exception:  # noqa: BLE001
                pass
        return False

    to_test = [] if SKIP_SITE_TEST else [s for s in sites if testable(s)]
    limit = int(os.environ.get("SITE_LIMIT", "0"))
    if limit > 0:
        to_test = to_test[:limit]
    print(f"[3/6] 站点验活：{len(to_test)}/{len(sites)} 个直连站点，并发 {CONCURRENCY} ...", flush=True)
    t0 = time.time()
    verdict = {}
    with cf.ThreadPoolExecutor(CONCURRENCY) as ex:
        futs = {ex.submit(check_site, s): s for s in to_test}
        done = 0
        for fut in cf.as_completed(futs):
            s = futs[fut]
            try:
                verdict[s["key"]] = fut.result()
            except Exception:  # noqa: BLE001
                verdict[s["key"]] = False
            done += 1
            if done % 100 == 0:
                print(f"  ... {done}/{len(to_test)} ({time.time()-t0:.0f}s)", flush=True)

    removed = []
    kept_sites = []
    for s in sites:
        if testable(s) and verdict.get(s["key"]) is False:
            removed.append({
                "key": s.get("key"), "name": s.get("name"),
                "api": s.get("api"), "reason": "验活连续两次失败",
            })
        else:
            kept_sites.append(s)
    tested_pass = sum(1 for v in verdict.values() if v)
    print(f"    通过 {tested_pass}/{len(to_test)}，剔除 {len(removed)}，保留 {len(kept_sites)} 站点", flush=True)

    # ---- [4/6] 直播源分类测速优选 ----
    print("[4/6] 直播源分类测速优选（Guovin 上游 → 央视/卫视/港台/其他）...", flush=True)
    m3u_entries = []
    for (u, fetchable_ok, tag), (u2, raw, info) in zip(fetchable, fetched):
        if u["kind"] != "m3u" or raw is None:
            continue
        try:
            for name, group, url in parse_m3u(raw):
                # 过滤 Guovin 列表头的「更新时间」伪频道与纯日期条目
                if re.search(r"更新时间|update.?time", group, re.I):
                    continue
                if re.match(r"^\d{4}-\d{2}-\d{2}", name):
                    continue
                m3u_entries.append((name, group, url))
        except Exception:  # noqa: BLE001
            pass
    seen_pairs = set()
    dedup_entries = []
    for name, group, url in m3u_entries:
        pk = (name, url)
        if pk not in seen_pairs:
            seen_pairs.add(pk)
            dedup_entries.append((name, group, url))
    print(f"    共 {len(m3u_entries)} 条，去重后 {len(dedup_entries)} 条", flush=True)
    live_stats = {}
    if dedup_entries:
        live_stats = build_live_outputs(dedup_entries)
        for key, label in CATEGORY_LABELS:
            entry_name = f"Guovin·{label}"
            if os.path.exists(os.path.join(LIVES_DIR, f"live_{key}.txt")) and entry_name not in lives_by_name:
                lives_by_name[entry_name] = rewrite_gh({
                    "name": entry_name, "type": 0,
                    "url": f"{REPO_RAW}/lives/live_{key}.txt",
                    "epg": "https://live.fanmingming.cn/e.xml",
                })
    lives = list(lives_by_name.values())

    # ---- [5/6] 产出配置 ----
    tvbox = dict(merged)
    tvbox["sites"] = kept_sites
    tvbox["lives"] = lives
    tvbox["parses"] = parses
    dep_stats = collect_and_rewrite_deps(tvbox, site_origin_name, spider_origin_info)
    with open("tvbox.json", "w", encoding="utf-8") as f:
        json.dump(tvbox, f, ensure_ascii=False, indent=1)

    # ---- 拆分产物：vod.json（点播）+ live.json（直播）----
    # vod.json = tvbox 去掉 lives（保留 spider / wallpaper / sites / parses 等点播相关字段）；
    # live.json = {"lives": [...]}，并确保汇总 lives/ 目录的分类文件条目（央视/卫视/港台/其他）。
    vod = {k: v for k, v in tvbox.items() if k != "lives"}
    live = {"lives": [l for l in lives if isinstance(l, dict) and l.get("name")]}
    for key, label in CATEGORY_LABELS:
        name = f"Guovin·{label}"
        path = os.path.join(LIVES_DIR, f"live_{key}.txt")
        if os.path.exists(path) and not any(l.get("name") == name for l in live["lives"]):
            live["lives"].append({
                "name": name, "type": 0,
                "url": f"{REPO_RAW}/lives/live_{key}.txt",
                "epg": "https://live.fanmingming.cn/e.xml",
            })
    with open("vod.json", "w", encoding="utf-8") as f:
        json.dump(vod, f, ensure_ascii=False, indent=1)
    with open("live.json", "w", encoding="utf-8") as f:
        json.dump(live, f, ensure_ascii=False, indent=1)
    print(f"[5/6] 产出：tvbox.json / vod.json（{len(vod.get('sites', []))} sites + {len(vod.get('parses', []))} parses）"
          f" / live.json（{len(live['lives'])} 条直播源）/ list.json", flush=True)

    with open("list.json", "w", encoding="utf-8") as f:
        json.dump(interfaces, f, ensure_ascii=False, indent=1)

    checks_doc = write_checks(checks, generated_at)
    update_readme_availability(checks)

    # ---- 快照合并产物 + 保留期清理 ----
    merged_dir = os.path.join(SNAPSHOT_DIR, now.strftime("%Y-%m-%d"))
    os.makedirs(merged_dir, exist_ok=True)
    with open(os.path.join(merged_dir, f"tvbox_merged__{now.strftime('%H%M%S')}.json"), "wb") as f:
        f.write(open("tvbox.json", "rb").read())
    pruned = snapshot_prune(SNAPSHOT_RETENTION_DAYS)
    if pruned:
        print(f"    快照清理：移除 {', '.join(pruned)}（保留最近 {SNAPSHOT_RETENTION_DAYS} 天）", flush=True)

    # ---- status.json（增强：上游健康度 + 产物指纹） ----
    products = {}
    for p in ("tvbox.json", "vod.json", "live.json", "list.json", "status.json", CHECKS_FILE,
              os.path.join(LIVES_DIR, "live.txt"), os.path.join(LIVES_DIR, "live_cctv.txt"),
              os.path.join(LIVES_DIR, "live_weishi.txt"), os.path.join(LIVES_DIR, "live_gangtai.txt"),
              os.path.join(LIVES_DIR, "live_other.txt")):
        if os.path.exists(p):
            b = open(p, "rb").read()
            products[p] = {"bytes": len(b), "sha256": sha12(b)}

    status = {
        "generated_at": generated_at,
        "summary": {
            "interfaces_total": len(interfaces),
            "interfaces_usable": len(usable_config),
            "interfaces_full": sum(1 for r in usable_config if r["grade"] == "完全可用"),
            "interfaces_partial": sum(1 for r in usable_config if r["grade"] == "部分可用"),
            "interfaces_dead": sum(1 for r in interfaces if r["kind"] == "tvbox" and r["grade"] == "不可用"),
            "sites_total": len(sites),
            "sites_kept": len(kept_sites),
            "sites_tested": len(to_test),
            "sites_tested_pass": tested_pass,
            "sites_removed": len(removed),
            "sites_untested": len(sites) - len(to_test),
            "lives": len(lives),
            "parses": len(parses),
            "deps_total": dep_stats["total"],
            "deps_collected": dep_stats["collected"],
            "deps_rewritten": dep_stats["rewritten"],
        },
        "upstreams_health": {
            "note": "checks.json 的摘要镜像；disabled=连续不达标自动停用，blacklisted=手动黑名单",
            "threshold": {"fail_limit": FAIL_LIMIT,
                          "min_bytes_tvbox": MIN_BYTES_TVBOX, "min_bytes_m3u": MIN_BYTES_M3U},
            **checks_doc["summary"],
            "disabled_now": disabled_now_list,
            "snapshot_files": len(snapshot_paths),
            "snapshot_pruned": pruned,
        },
        "lives_by_category": live_stats,
        "products": {"note": "产物 sha256 指纹（前 12 位）与字节数", "items": products},
        "interfaces": interfaces,
        "removed_sites": removed,
        "top_interfaces": sorted(
            ({"name": r["name"], "sites": r["sites"], "http_ms": r["http_ms"], "grade": r["grade"]}
             for r in usable_config), key=lambda x: (-x["sites"], x["http_ms"]),
        )[:15],
    }
    with open("status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)

    print(f"[6/6] 输出完成：tvbox.json / vod.json / live.json / list.json / status.json / checks.json / lives/* @ {generated_at}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
