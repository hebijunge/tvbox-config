#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JS(drpy) 源实测：按规则构造真实请求，验证「站点结构是否还对得上规则」。

为什么不是完整 Node 运行时而
---------------------------
drpy 规则依赖引擎解释（中文函数名、fyclass/fypage 模板、$js.toString 扩展语法），
而引擎 drpy2 的代码由宿主 App 提供、本地 deps 里并没有——纯 Node 沙箱跑不起来。
但规则的失效原因里，绝大多数不是引擎问题是**站点改版**：选择器对不上新页面、
接口改了返回结构。这类失效可以不等引擎就验出来。

做法
----
  1. 解析规则文件，取出 host / url(分类页模板) / searchUrl(搜索模板) / 编码 / class_url
  2. 把 fyclass、fypage 换成真实值，构造出可直接请求的分类页与搜索页 URL
  3. 请求并判断响应里到底有没有内容：
     · JSON 型接口 → 能解析出非空数组
     · HTML 型页面 → 详情页链接数 >= 5
  4. 另外用 node --check 校验规则文件本身语法（加载即失败的文件直接判死）

评级：S3 分类页+搜索页都有内容 / S2 分类页有内容 / S1 可达但无内容特征 / S0 请求失败或文件缺失

用法
----
    python scripts/probe_js.py
    python scripts/probe_js.py --concurrency 24 --keywords 庆余年,流浪地球
"""

import argparse
import atexit
import concurrent.futures as cf
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

UA = {"User-Agent": "okhttp/3.15", "Accept": "*/*", "Accept-Encoding": "gzip, deflate"}
TIMEOUT = 12
RULE_TIMEOUT = int(os.environ.get("JS_RULE_TIMEOUT", "25"))   # 远程规则常在慢盘/镜像上
MAX_BODY = 400_000
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

STR_RE = r"""['"`]([^'"`]*)['"`]"""
RX = {
    "host": re.compile(r"""\bhost\s*:\s*""" + STR_RE),
    "url": re.compile(r"""\burl\s*:\s*""" + STR_RE),
    "searchUrl": re.compile(r"""\bsearchUrl\s*:\s*""" + STR_RE),
    "searchable": re.compile(r"""\bsearchable\s*:\s*(\d+)"""),
    "charset": re.compile(r"""\b编码\s*:\s*""" + STR_RE),
    "classUrl": re.compile(r"""\bclass_url\s*:\s*""" + STR_RE),
}


def http_get(url, timeout=TIMEOUT, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        raw = r.read(MAX_BODY)
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
        return r.status, raw, int((time.time() - t0) * 1000), r.headers.get("Content-Type", "")


def decode_body(raw, charset):
    """按规则声明的编码解码（不少 drpy 源站点是 gb2312）。"""
    encs = []
    if charset:
        encs.append(charset.lower())
    encs += ["utf-8", "gb18030", "big5"]
    for e in encs:
        try:
            return raw.decode(e)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def content_signal(text):
    """判断响应里到底有没有内容。返回 (强度 0-2, 证据)。"""
    if not text or len(text) < 60:
        return 0, "响应过短"
    stripped = text.lstrip()
    if stripped[:1] not in "[{":
        # JSONP：形如 callback({"data":[...]})，剥掉回调外壳再判
        m = re.match(r"^[A-Za-z_$][\w$.]*\s*\(\s*([\[{])", stripped)
        if m:
            body = stripped[m.start(1):].rstrip()
            stripped = body[: body.rfind(")")] if body.endswith(")") else body
    if stripped[:1] in "[{":
        try:
            doc = json.loads(stripped)
        except json.JSONDecodeError:
            doc = None
        if doc is not None:
            arr = None
            if isinstance(doc, list):
                arr = doc
            elif isinstance(doc, dict):
                for k in ("data", "list", "items", "result", "results", "videos", "content"):
                    v = doc.get(k)
                    if isinstance(v, list):
                        arr = v
                        break
                    if isinstance(v, dict):
                        for kk in ("list", "data", "items"):
                            if isinstance(v.get(kk), list):
                                arr = v[kk]
                                break
                    if arr is not None:
                        break
            if arr:
                return 2, f"json 数组 {len(arr)} 项"
            if doc:
                return 1, "json 非空但无数组"
    links = len(re.findall(r"<a\s+[^>]*href\s*=", text, re.I))
    if links >= 5:
        return 2, f"html 链接 {links} 个"
    if links >= 1:
        return 1, f"html 链接 {links} 个"
    if re.search(r"(vod_|playlist|play_url|episodes|listpage)", text, re.I):
        return 1, "疑似内容字段"
    return 0, "无内容特征"


def build_url(host, template, cate=None, page=1, keyword=None):
    """把规则模板里的 fyclass / fypage / ** 换成真实值。"""
    if not template:
        return None
    u = template
    if keyword is not None:
        u = u.replace("**", urllib.parse.quote(keyword))
    if cate is not None:
        u = u.replace("fyclass", cate)
    # 规则里常见分页表达式（腾讯等）：((fypage-1)*21) 在第 1 页应展开为 0
    u = re.sub(r"\(\(\s*fypage\s*-\s*1\s*\)\s*\*\s*\d+\)", "0", u)
    u = re.sub(r"\(\(\s*fypage\s*-\s*1\s*\)\s*\*\s*\d+", "0", u)
    u = u.replace("fypage", str(page))
    u = re.sub(r"\{\{.*?\}\}", "", u)          # 未展开的模板变量直接去掉
    if u.startswith("http"):
        return u
    if not host:
        return None
    return host.rstrip("/") + "/" + u.lstrip("/")


def _abs(repo, loc):
    return loc if os.path.isabs(loc) else os.path.join(repo, loc)


def local_rule_file(site, repo, man_idx):
    """这个 JS 源的解释文件在本地哪儿？

    tvbox.json 的本地化约定是把 api/ext 的远程地址改写成一串指纹，真正的下载记录在
    deps/manifest.json 的 key（"origin|url"）里——按指纹回查，再退到 api/ext 的原始形态。
    """
    cands = []
    for v in (site.get("api"), site.get("ext")):
        if isinstance(v, str) and v.strip():
            cands.append(v.strip().split(";")[0])
    for c in cands:
        if c.startswith("./") or c.startswith("deps/"):
            p = os.path.join(repo, c[2:] if c.startswith("./") else c)
            if os.path.isfile(p):
                return p
        if c.startswith("http"):
            for key in (c, gh_inner(c)):
                loc = man_idx.get(key)
                if loc and os.path.isfile(_abs(repo, loc)):
                    return _abs(repo, loc)
        else:
            loc = man_idx.get(c)          # api 被改写成指纹（deps 本地化的形态）
            if loc and os.path.isfile(_abs(repo, loc)):
                return _abs(repo, loc)
    return None


def manifest_index(repo):
    idx = {}
    p = os.path.join(repo, "deps", "manifest.json")
    if not os.path.exists(p):
        return idx
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return idx
    for key, v in data.items():
        if not isinstance(v, dict):
            continue
        loc = (v.get("local") or "").replace("\\", "/")
        if not loc:
            continue
        url = v.get("url") or ""
        orig = key.split("|", 1)[1] if "|" in key else url
        for k in filter(None, (url, orig, gh_inner(orig), loc, loc[len("deps/"):] if
                               loc.startswith("deps/") else loc)):
            idx.setdefault(k, loc)
    return idx


def parse_rule(text):
    out = {}
    for k, rx in RX.items():
        m = rx.search(text)
        out[k] = m.group(1) if m else None
    cu = out.get("classUrl") or ""
    out["first_cate"] = re.split(r"[&,]|\\|", cu)[0] if cu else "1"
    return out


def gh_inner(url):
    """去掉镜像前缀，还原被包住的真实地址（deps 账本按真实地址记）。

    先认 github raw（产出改写的主形态），再兜一般的 "https://镜像/<http 内层>" 结构，
    不然 gitcode/agit 这类被 gh-proxy 包起来的引用查不到账本。
    """
    u = str(url or "").split(";md5")[0]
    m = re.search(r"(https?://raw\.githubusercontent\.com/\S+)", u)
    if m:
        return m.group(1)
    m = re.search(r"https?://[^/]+/(https?://.*)$", u)
    return m.group(1) if m else u


def is_engine_file(fp, text):
    """是不是 drpy **引擎**文件（几百个站共用一个，host 不在文件里而在远端规则里）。

    引擎定义 `function main(...)`、并从 assets://js/lib/* 引依赖；规则文件是 `var rule={host…}`。
    """
    name = os.path.basename(fp).lower()
    if name.startswith("drpy") or name.endswith(".min.js"):
        return True
    head = text[:200000]
    return "assets://js/lib" in head or bool(re.search(r"\bfunction\s+main\s*\(", head))


def is_js_site(s):
    """是不是 JS 源。

    先剥掉 query 与 `;md5;` 尾：`https://zoe.im/tvbox/sites/ddys/spider.js?v=3` 这类带版本号
    的直链以前匹配不到 `.js`，产物里 3 个站因此谁都没测（5a/5c/5e 都按后缀分流）。
    """
    api = str(s.get("api") or "").split("?")[0].split(";md5")[0].strip()
    ext = str(s.get("ext") or "").split("?")[0].strip()
    return api.endswith(".js") or ext.endswith(".js") or s.get("kind") == "js"


RULE_SUFFIX = (".js", ".txt", ".json", ".xml")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "::1")
_TMP = {}


def tmp_dir():
    d = _TMP.get("d")
    if not d:
        d = tempfile.mkdtemp(prefix="jsrules-")
        _TMP["d"] = d
        atexit.register(shutil.rmtree, d, True)
    return d


def remote_rule_urls(site):
    """配置里能联网取规则文件的地址（ext 是规则本体，api 也可能直接是 http .js）。

    按字符类抓而不是切逗号：ext 既可能是 `https://a/x.js,https://b/x.js` 的**备用域列表**
    （spider 会挨个试，只取首域判死就是假死——5h 的 wencai 踩过同一条），也可能是
    JSON 数组/对象形态（`["https://a/r.js",""]`），切逗号会把带引号括号的头一个元素整个丢掉。
    """
    got = []
    for v in (site.get("ext"), site.get("api")):
        s = v if isinstance(v, str) else json.dumps(v or "", ensure_ascii=False)
        for u in re.findall(r"https?://[^\s\"'(),;}\]$]+", s):
            try:
                host = urllib.parse.urlparse(u).hostname or ""
            except ValueError:
                continue
            if host in LOCAL_HOSTS or host.startswith("192.168.") or host.startswith("10."):
                continue
            got.append(u)
    return list(dict.fromkeys(got))


def looks_like_rule_js(text):
    t = (text or "").lstrip("\ufeff \t\r\n")
    return len(t) >= 64 and "<html" not in t[:400].lower() and \
        "<!doctype html" not in t[:400].lower()


def miss_kind(url, status=None, text=""):
    """只有「规则文件本身不在这个地址上了」才构成已亡。

    与 5h 同一条规矩：drpy 站的 ext 也常直接是站点根 URL（引擎自己抓首页），返回整页
    HTML 是正常形态，据此判死就是自己造假死（上一版误判 31 个站的同款）。
    """
    if not urllib.parse.urlparse(url).path.lower().endswith(RULE_SUFFIX):
        return ""
    if status in (404, 410):
        return "gone-%s" % status
    low = (text or "")[:300].lower()
    return "lander-html" if ("<html" in low or "<!doctype" in low) else ""


def _stash(url, text):
    """把取回的规则落到临时文件，下游（node --check / 构造请求）按本地文件同一套走。"""
    name = os.path.basename(urllib.parse.urlsplit(url).path) or "rule.js"
    name = re.sub(r"[^\w.\-]", "_", name)[:60]
    if not name.endswith(".js"):
        name += ".js"
    fp = os.path.join(tmp_dir(), hashlib.md5(url.encode("utf-8")).hexdigest()[:10] + "-" + name)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(text)
    return fp


def fetch_remote_rule(site):
    """本地无副本时在国内真取一次远程规则 → (路径|None, 结论|None)。

    死刑只有拿到结构性证据才下（域名 DoH 一致无记录 / 规则文件 404·410 / .js 地址变 HTML 壳），
    而且必须**每个备用域都**结构性失踪；超时、连接重置、TLS、DoH 说域名还在都算环境性 → S?。
    为什么必须拆开：S0 会进产物算成「站点已死」，而"我们没把规则取到手"是工装的事——
    2026-10-02 抽审 152 条「规则源取不到」，当场就能取回 7 条、DoH 确认已亡只有 7 条。
    """
    urls = remote_rule_urls(site)
    if not urls:
        return None, None
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        from probe_endpoints import doh_cached
    except ImportError:
        doh_cached = None
    try:
        from probe_sites import gh_retry_candidates
    except ImportError:
        gh_retry_candidates = lambda u: []
    dead, env = [], []
    for u in urls:
        host = urllib.parse.urlparse(u).hostname or ""
        why = ""
        for cand in [u] + list(gh_retry_candidates(u))[:3]:
            try:
                st, raw, _ms, _ct = http_get(cand, RULE_TIMEOUT)
                text = raw.decode("utf-8", "ignore")
            except urllib.error.HTTPError as e:
                why = why or miss_kind(cand, e.code, "")
                continue
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "getaddrinfo" in msg or "11001" in msg:
                    if doh_cached is None:
                        env.append("DNS未复核")
                        continue
                    verdict, detail = doh_cached(host, RULE_TIMEOUT)
                    if verdict is False:
                        why = why or "域名无解析记录(DoH一致)"
                        break
                    env.append("DNS未确认")      # DoH 说域名还在：本机网络问题，不是站死
                elif "timed out" in msg or "10054" in msg or "Unable to connect" in msg:
                    env.append("env")
                else:
                    env.append(type(e).__name__)
                continue
            if st == 200 and looks_like_rule_js(text):
                return _stash(cand, text), {"rule_src_url": cand}
            why = why or miss_kind(cand, st, text)
            if not why:
                env.append("HTTP%s" % st)
        if why:
            dead.append(why)
    if dead and len(dead) == len(urls):
        return None, {"level": "S0", "reason": "远程规则已亡：" + dead[0][:60],
                      "evidence": {"ext_dep": "remote-rule-unreachable",
                                   "url": urls[0][:120], "tried": len(urls),
                                   "cause": ";".join(dead)[:120]}}
    return None, {"level": "S?", "reason": "远程规则未取到（环境性/未证实，不算站死）",
                  "env_hints": ";".join(env[:4])}


def node_check(fp):
    """规则文件语法校验（加载即失败的文件直接判死）。node 不存在时返回 None。

    drpy 规则本身是 ES 模块（`import cheerio from "assets://..."`、还有中文标识符），
    `node --check x.js` 按 CommonJS 解析会报 "Cannot use import statement outside a
    module"，把正常的 drpy2.min.js 判成"语法错误"（2026-10-01 实测 9 个 S0 全是误判）。
    所以含 import/export 的内容先复制成 .mjs 再校验。
    """
    node = shutil.which("node") or r"C:\Users\ajun\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
    if not node or not os.path.exists(node):
        return None
    target = fp
    tmp = None
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(60000)
    except OSError:
        head = ""
    if re.search(r"^\s*(import|export)\b", head, re.M) or "assets://" in head:
        # 临时副本必须唯一：几百个站共享同一个 drpy2.min.js，用固定名字会 A 删 B 用，
        # 制造出一片假"语法错误"（2026-10-01 实测 38 例）。
        try:
            fd, tmp = tempfile.mkstemp(suffix=".mjs")
            os.close(fd)
            shutil.copyfile(fp, tmp)
            target = tmp
        except OSError:
            tmp = None
    try:
        try:
            r = subprocess.run([node, "--check", target], capture_output=True, timeout=20)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return None
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def probe_one(site, repo, keywords, man_idx=None):
    r = {"key": site.get("key"), "name": site.get("name"), "kind": "js"}
    fp = local_rule_file(site, repo, man_idx or {})
    remote_from = ""
    if not fp:
        # 本地没副本不等于规则亡了：先在国内真取一次，取到就照原流程实测，取不到也只对
        # 有结构性证据的下 S0，其余留 S?（旧版在这里一律写 S0，152 条死刑没一条带证据）。
        fp, v = fetch_remote_rule(site)
        if not fp:
            r.update(v or {"level": "S?", "reason": "配置里既无本地副本也无远程规则地址"})
            return r
        remote_from = v["rule_src_url"]
    rel = ("remote:" + remote_from) if remote_from else \
        os.path.relpath(fp, repo).replace("\\", "/")
    r["rule"] = rel
    try:
        with open(fp, "rb") as f:
            text = f.read(400_000).decode("utf-8", "ignore")
    except OSError:
        r.update({"level": "S0", "reason": "规则读取失败"})
        return r

    rule = parse_rule(text)
    r.update({"host": rule.get("host"), "searchable_rule": rule.get("searchable")})
    syn = node_check(fp)
    r["syntax_ok"] = syn
    if syn is False:
        # 文件在手且 node --check 真报错：这是规则自身的结构性失效，带证据入库
        r.update({"level": "S0", "reason": "规则文件语法错误",
                  "evidence": {"static": "rule-syntax-error", "checker": "node --check"}})
        return r
    if not rule.get("host"):
        if is_engine_file(fp, text):
            # drpy2.min.js 这类是**引擎**，host 在各站远端规则里，5c 用正则拿不到证据；
            # 判 S1（入库即 degraded）是拿工装能力冒充站点质量结论——留 S?，交 5e 沙箱真解释。
            r.update({"level": "S?", "reason": "引擎文件，规则未随包（待 5e 沙箱判）"})
            return r
        r.update({"level": "S1", "reason": "规则未声明 host"})
        return r

    headers = {"Referer": rule["host"] + "/"}
    cat_url = build_url(rule["host"], rule.get("url"), cate=rule["first_cate"], page=1)
    r["cat_url"] = (cat_url or "")[:200]
    cat_sig, cat_ev = 0, "未构造出分类页 URL"
    if cat_url:
        try:
            st, raw, ms, _ = http_get(cat_url, headers=headers)
            if st == 200:
                cat_sig, cat_ev = content_signal(decode_body(raw, rule.get("charset")))
                r["cat_ms"] = ms
            else:
                cat_ev = f"HTTP {st}"
        except urllib.error.HTTPError as e:
            cat_ev = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001  探测边界
            cat_ev = type(e).__name__
    r["cat_signal"], r["cat_evidence"] = cat_sig, cat_ev

    if cat_sig == 0:
        # 连接层异常只说明本机到该域名不通，不能算站点或规则失效
        env_fail = any(k in cat_ev for k in (
            "URLError", "RemoteDisconnected", "ConnectionReset", "ConnectionAborted",
            "Timeout", "WinError", "certificate"))
        if env_fail:
            r.update({"level": "S?", "reason": f"本机网络不可达：{cat_ev}"})
        elif "构造" in cat_ev or "HTTP" in cat_ev:
            # 5c 是浅探针：造不出请求 / 拿到错误状态只证明「这一关没验成」，不证明规则或站点坏。
            # 判死必须有结构性证据（规则文件 404·410·变壳·DoH 一致无记录，或本地副本语法坏），
            # 深浅之分与 store 的 PROBE_PRIORITY 同一条口径。
            r.update({"level": "S?", "reason": f"分类页未验成：{cat_ev}"})
        else:
            r.update({"level": "S1", "reason": f"分类页无效：{cat_ev}"})
        return r
    r["level"] = "S2"

    # 搜索页
    kw = keywords[0] if keywords else "电影"
    sr_url = build_url(rule["host"], rule.get("searchUrl"), page=1, keyword=kw)
    if sr_url:
        r["search_url"] = sr_url[:200]
        try:
            st, raw, ms, _ = http_get(sr_url, headers=headers)
            if st == 200:
                sig, ev = content_signal(decode_body(raw, rule.get("charset")))
                r["search_signal"], r["search_evidence"] = sig, ev
                if sig >= 1:
                    r["level"] = "S3"
            else:
                r["search_evidence"] = f"HTTP {st}"
        except urllib.error.HTTPError as e:
            r["search_evidence"] = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            r["search_evidence"] = type(e).__name__
    else:
        r["search_evidence"] = "规则无可构造的搜索 URL"
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="tvbox.json")
    ap.add_argument("--out", default="probe/js_probe.json")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--keywords", default="庆余年,流浪地球")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    with open(os.path.join(repo, args.input), encoding="utf-8") as f:
        doc = json.load(f)
    sites = [s for s in (doc.get("sites") or []) if is_js_site(s)]
    man_idx = manifest_index(repo)
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    print(f"[js] 待测 JS 源 {len(sites)} 个（并发 {args.concurrency}）", flush=True)

    results = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(args.concurrency) as ex:
        futs = {ex.submit(probe_one, s, repo, keywords, man_idx): s for s in sites}
        done = 0
        for fut in cf.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001
                s = futs[fut]
                results.append({"key": s.get("key"), "name": s.get("name"),
                                "kind": "js", "level": "S0", "reason": type(e).__name__})
            done += 1
            if done % 40 == 0:
                print(f"  ... {done}/{len(sites)} ({time.time()-t0:.0f}s)", flush=True)

    lv = {}
    for r in results:
        lv[r["level"]] = lv.get(r["level"], 0) + 1
    doc_out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "drpy 规则半动态验证：按规则构造分类页/搜索页请求，验证站点结构是否还对得上规则",
        "summary": {"total": len(results), "levels": lv},
        "sites": results,
    }
    os.makedirs(os.path.dirname(os.path.join(repo, args.out)) or ".", exist_ok=True)
    with open(os.path.join(repo, args.out), "w", encoding="utf-8") as f:
        json.dump(doc_out, f, ensure_ascii=False, indent=1)

    print(f"[js] 完成：{lv}")
    for r in sorted([x for x in results if x["level"] == "S3"], key=lambda x: x.get("cat_ms") or 99999)[:10]:
        print(f"   {str(r.get('cat_ms')):>6}ms  {str(r.get('name'))[:18]:18} {str(r.get('cat_evidence'))[:22]}")
    print(f"[js] 产物 -> {args.out}")
    return 0


if __name__ == "__main__":
    # Windows 直跑时 stdout 默认 GBK，站点名带 emoji 会在打印处 UnicodeEncodeError 崩掉整轮
    # （run_all/CI 子进程有 PYTHONIOENCODING=utf-8，只有单脚本直跑踩这个坑）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
