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

# 热词：优先选长期在架、覆盖面广的剧名，命中率比随机词高
KEYWORDS = ["庆余年", "流浪地球", "甄嬛传"]

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


def probe_l1(api):
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
            st, raw, ms, _ = http_get(url, L1_TIMEOUT, MAX_JSON)
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


def probe_l2(api, keywords):
    """L2：热词搜索是否命中。多种参数变体轮试，记录失败细节。"""
    best = {"ok": False, "hits": 0, "kw": None, "ms": None, "tried": [], "env": 0}
    for kw in keywords:
        q = urllib.parse.quote(kw)
        for variant in (f"wd={q}", f"ac=detail&wd={q}", f"ac=list&wd={q}"):
            url = join_api(api, variant)
            try:
                st, raw, ms, _ = http_get(url, L2_TIMEOUT, MAX_JSON)
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


def probe_l3(api, vod_id):
    """L3：能否取到可播的播放地址（取首片验证）。

    接受 m3u8（响应含 #EXTM3U）与 video/* 直链；两者都算「可取链」。
    """
    url = join_api(api, f"ac=detail&ids={urllib.parse.quote(str(vod_id))}")
    try:
        st, raw, ms, _ = http_get(url, L3_TIMEOUT, MAX_JSON)
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
        st2, body, ms2, ctype = http_get(play, L3_TIMEOUT, MAX_TS, {"Range": "bytes=0-2047"})
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


def probe_http_site(site, keywords, deep=True):
    """对单个 HTTP 型站点跑 L1→L2→L3。"""
    api = site.get("api")
    r = {"key": site.get("key"), "name": site.get("name"), "api": api, "kind": "http"}
    l1 = probe_l1(api)
    r["l1"] = l1
    if not l1.get("ok"):
        # 连接层失败只说明本机到该域名的链路不通，不能判定站点不可用
        r["level"] = "L?" if l1.get("cls") == "env" else "L0"
        return r
    r["level"] = "L1"
    if not deep:
        return r
    l2 = probe_l2(api, keywords)
    r["l2"] = l2
    if l2.get("ok"):
        r["level"] = "L2"
    vod_id = l2.get("vod_id")
    if vod_id is None:
        # 搜索失败或未命中时，用 L1 列表里的第一条 id 兜底试 L3（判断是搜索不可用还是接口整体不可用）
        try:
            st, raw, _, _ = http_get(join_api(api, "ac=list"), L1_TIMEOUT, MAX_JSON)
            lst, _ = parse_any(raw)
            if lst and isinstance(lst[0], dict):
                vod_id = lst[0].get("vod_id")
        except (urllib.error.URLError, OSError, ValueError):
            pass
    if vod_id is not None:
        l3 = probe_l3(api, vod_id)
        r["l3"] = l3
        if l3.get("ok"):
            r["level"] = "L3"
    return r


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="tvbox.json", help="合并产物配置")
    ap.add_argument("--out", default="probe/sites_probe.json")
    ap.add_argument("--repo", default=".", help="仓库根（用于静态检查）")
    ap.add_argument("--only", default="all", choices=["all", "http", "js", "csp"])
    ap.add_argument("--limit", type=int, default=0, help="每类最多测多少个")
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--keywords", default=",".join(KEYWORDS))
    ap.add_argument("--shallow", action="store_true", help="只跑 L1，不跑 L2/L3")
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

    if args.only in ("all", "http"):
        print(f"[probe] L1-L3 实测 {len(http_sites)} 个（并发 {args.concurrency}，热词 {keywords}）...", flush=True)
        t0 = time.time()
        with cf.ThreadPoolExecutor(args.concurrency) as ex:
            futs = {ex.submit(probe_http_site, s, keywords, not args.shallow): s for s in http_sites}
            done = 0
            for fut in cf.as_completed(futs):
                try:
                    results.append(fut.result())
                except Exception as e:  # noqa: BLE001
                    s = futs[fut]
                    results.append({"key": s.get("key"), "name": s.get("name"), "api": s.get("api"),
                                    "kind": "http", "level": "L0", "error": f"{type(e).__name__}: {e}"[:120]})
                done += 1
                if done % 25 == 0:
                    print(f"  ... {done}/{len(http_sites)} ({time.time()-t0:.0f}s)", flush=True)

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
        "levels": dict(sorted(by_level.items())),
        "http_levels": {lv: sum(1 for r in http_res if r["level"] == lv) for lv in ("L3", "L2", "L1", "L0", "L?")},
        "static_levels": {lv: sum(1 for r in results if r["level"] == lv and r.get("kind") != "http")
                          for lv in ("S1", "S0", "S?")},
    }
    out = {"summary": summary, "sites": results}
    os.makedirs(os.path.dirname(os.path.join(repo, args.out)) or ".", exist_ok=True)
    with open(os.path.join(repo, args.out), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"[probe] 完成：{summary['http_levels']}（http 型四级分布） 静态：{summary['static_levels']}")
    print(f"[probe] 产物 -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
