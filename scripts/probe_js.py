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
import concurrent.futures as cf
import gzip
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

UA = {"User-Agent": "okhttp/3.15", "Accept": "*/*", "Accept-Encoding": "gzip, deflate"}
TIMEOUT = 12
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


def parse_rule(text):
    out = {}
    for k, rx in RX.items():
        m = rx.search(text)
        out[k] = m.group(1) if m else None
    cu = out.get("classUrl") or ""
    out["first_cate"] = re.split(r"[&,]|\\|", cu)[0] if cu else "1"
    return out


def node_check(fp):
    """规则文件语法校验（加载即失败的文件直接判死）。node 不存在时返回 None。"""
    node = shutil.which("node") or r"C:\Users\ajun\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
    if not node or not os.path.exists(node):
        return None
    try:
        r = subprocess.run([node, "--check", fp], capture_output=True, timeout=20)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def probe_one(site, repo, keywords):
    r = {"key": site.get("key"), "name": site.get("name"), "kind": "js"}
    ext = site.get("ext")
    if not isinstance(ext, str) or not ext.strip().startswith("./"):
        r.update({"level": "S0", "reason": "无本地规则文件"})
        return r
    rel = ext.strip().split(";")[0][2:]
    fp = os.path.join(repo, rel)
    r["rule"] = rel
    if not os.path.isfile(fp):
        r.update({"level": "S0", "reason": "规则文件缺失"})
        return r
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
        r.update({"level": "S0", "reason": "规则文件语法错误"})
        return r
    if not rule.get("host"):
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
        else:
            r.update({"level": "S0" if ("HTTP" in cat_ev or "构造" in cat_ev) else "S1",
                      "reason": f"分类页无效：{cat_ev}"})
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
    sites = [s for s in (doc.get("sites") or [])
             if isinstance(s.get("api"), str) and s["api"].startswith("./")]
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    print(f"[js] 待测 JS 源 {len(sites)} 个（并发 {args.concurrency}）", flush=True)

    results = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(args.concurrency) as ex:
        futs = {ex.submit(probe_one, s, repo, keywords): s for s in sites}
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
    sys.exit(main())
