#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环④ P0 依赖完整性闸门（第一步：缺失重下）。

背景：tvbox.json 里 1920 条 deps/ 本地引用，777 条磁盘缺失。其中 161 条在
deps/manifest.json 里有账本记录（url + md5 + local），可按账本重下补齐；
145 条（全是 deps/localized|auto|sv 的无扩展名本地化产物）账本没挂 URL，
只能靠下轮管道重新本地化，本脚本报告清单但不强行处理。

流程：
  1. 扫 tvbox.json 全部 deps/ 引用，算出磁盘缺失集合；
  2. 用 manifest 反推可补下清单（local → url + 期望 md5）；
  3. 并发下载（github URL 走镜像重试），落盘前 md5 校验；
  4. 成功条目回写 manifest（fail_count=0 / updated_at / size），失败累加 fail_count；
  5. 出修复报告 state/dep_repair_report.json（补了几个、补不下的源降级清单）。

用法：
  python dep_repair.py            # 补下 + 回写 + 报告
  python dep_repair.py --dry-run  # 只算清单不下载
"""
import argparse
import concurrent.futures
import gzip
import hashlib
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.request
import zlib
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "deps", "manifest.json")
TVBOX = os.path.join(ROOT, "tvbox.json")
REPORT = os.path.join(ROOT, "state", "dep_repair_report.json")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"}
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE
# github raw 国内常阻断，走镜像重试。
# 实测（9/28）：裸 raw 直连常超时，gh.acmsz.top 5s 内出 200KB，故把它放首位；
# 裸连("")放最后当兜底，避免每次都先空等。GH_ACMSZ=0 可临时停用该镜像。
GH_MIRRORS = ["https://gh.acmsz.top/", "https://ghproxy.net/", "https://gh-proxy.com/", "https://ghfast.top/", ""]
# 支持 GH_ACMSZ=0 临时停用该镜像
if os.environ.get("GH_ACMSZ") == "0":
    GH_MIRRORS.remove("https://gh.acmsz.top/")


def log(msg):
    print(f"[dep_repair {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def normalize_url(url):
    """路径里中文/空格等字符做 percent-encoding（查询串原样保留）。

    上游账本里的 URL 常带中文路径（如 /一木源/JSON/…）或空格（vo fl ix.json），
    urllib 直连会 UnicodeEncodeError / InvalidURL。只对 path 段 quote，
    不动 query（镜像/防盗链参数）。
    """
    from urllib.parse import urlsplit, urlunsplit, quote
    sp = urlsplit(url)
    if sp.scheme in ("http", "https"):
        return urlunsplit((sp.scheme, sp.netloc, quote(sp.path, safe="/"),
                           sp.query, sp.fragment))
    return url


def http_get(url, timeout=25, max_bytes=200_000_000):
    url = normalize_url(url)
    mirrors = GH_MIRRORS if "github" in url else [""]
    last = None
    for m in mirrors:
        u = url if not m else m + url
        try:
            req = urllib.request.Request(u, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                raw = r.read(max_bytes)
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
                return raw, (m or "direct")
        except Exception as e:
            last = e
    raise last


def scan_refs():
    """扫 tvbox.json 里所有 deps/ 引用（ext/jar/parses）。"""
    tv = json.load(open(TVBOX, encoding="utf-8"))
    refs = set()

    def add(r):
        for m in re.finditer(r"((?:\./)?deps/[A-Za-z0-9_\-./%?&]+)", str(r)):
            refs.add(m.group(1))

    for s in tv["sites"]:
        for f in ("ext", "jar"):
            v = s.get(f)
            if isinstance(v, str):
                add(v)
            elif isinstance(v, dict):
                for x in v.values():
                    add(str(x))
    for p in tv.get("parses", []):
        add(p.get("ext"))
    return refs, tv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    refs, tv = scan_refs()
    missing = {r.lstrip("./") for r in refs if not os.path.exists(r.lstrip("./"))}
    log(f"deps 引用 {len(refs)} 条，磁盘缺失 {len(missing)} 条")

    man = json.load(open(MANIFEST, encoding="utf-8"))
    by_loc = {}
    for k, v in man.items():
        loc = (v.get("local") or "").lstrip("./")
        if loc:
            by_loc.setdefault(loc, k)
    tasks = []
    for loc in sorted(missing):
        k = by_loc.get(loc)
        if k and man[k].get("url"):
            v = man[k]
            tasks.append({"key": k, "local": loc, "url": v["url"],
                          "md5": v.get("md5"), "origin": v.get("origin")})
    unfixable = sorted(missing - {t["local"] for t in tasks})
    log(f"可补下 {len(tasks)}（manifest 有 URL）| 无账本 {len(unfixable)}（下轮管道重新本地化）")
    if args.dry_run:
        print(json.dumps({"fixable": len(tasks), "unfixable": len(unfixable),
                          "sample": [t["local"] for t in tasks[:5]]}, ensure_ascii=False, indent=1))
        return

    def one(t):
        fp = os.path.join(ROOT, t["local"])
        # 已落盘且 md5 匹配 → 跳过（幂等重跑）
        if os.path.isfile(fp):
            disk_md5 = hashlib.md5(open(fp, "rb").read()).hexdigest()
            if not t.get("md5") or disk_md5 == t["md5"]:
                return t, True, "skipped (already present)"
        try:
            blob, via = http_get(t["url"])
        except Exception as e:
            return t, False, f"{type(e).__name__}: {str(e)[:60]}"
        # 内容 sanity：防镜像返回错误页/死链空壳
        if len(blob) < 100:
            return t, False, f"内容过小 {len(blob)}B（疑错误页）"
        if (t.get("kind") == "jar" or t["local"].endswith(".jar")) and blob[:2] != b"PK":
            return t, False, "非 jar（前 2 字节非 PK，疑错误页）"
        drift = bool(t.get("md5")) and hashlib.md5(blob).hexdigest() != t["md5"]
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "wb") as f:
            f.write(blob)
        if drift:
            return t, True, f"md5 漂移（源已更新，接受新内容）{len(blob)//1024}KB via {via}"
        return t, True, f"{len(blob)//1024}KB via {via}"

    ok, failed = [], []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for t, good, info in ex.map(one, tasks):
            done += 1
            if good:
                ok.append(t)
                # 回写账本：清失败计数 + 同步实际落盘的 md5/size（drift 时刷新）
                fp = os.path.join(ROOT, t["local"])
                if os.path.isfile(fp):
                    blob2 = open(fp, "rb").read()
                    man[t["key"]].update({"fail_count": 0, "size": len(blob2),
                                          "md5": hashlib.md5(blob2).hexdigest(),
                                          "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S %z"),
                                          "last_error": None})
            else:
                failed.append((t, info))
                man[t["key"]]["fail_count"] = int(man[t["key"]].get("fail_count", 0)) + 1
                man[t["key"]]["last_error"] = info
                log(f"  [失败] {t['local'][:60]} -> {info}")
            if done % 20 == 0 or done == len(tasks):
                log(f"  进度 {done}/{len(tasks)}（成功 {len(ok)} / 失败 {len(failed)}）")
    json.dump(man, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"manifest 已回写（成功 {len(ok)} 清零 fail_count，失败 {len(failed)} 累加）")

    # 受影响站点：配置引用了缺失依赖的站（补下后重算）
    still = {t["local"] for t, _ in failed} | set(unfixable)
    aff = []
    for s in tv["sites"]:
        blob = " ".join(str(x) for f in ("ext", "jar")
                        for x in ([s.get(f)] if isinstance(s.get(f), str)
                                  else (list(s.get(f).values()) if isinstance(s.get(f), dict) else [])))
        for m in re.finditer(r"((?:\./)?deps/[A-Za-z0-9_\-./%?&]+)", blob):
            if m.group(1).lstrip("./") in still:
                aff.append(s.get("key"))
                break
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_refs": len(refs),
        "was_missing": len(missing),
        "repaired": len(ok),
        "repair_failed": [{"local": t["local"], "url": t["url"], "err": i} for t, i in failed],
        "unfixable_no_manifest": unfixable,
        "sites_still_broken": sorted(set(aff)),
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    json.dump(report, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"报告 -> {os.path.basename(REPORT)}：补下 {len(ok)}/{len(tasks)}，"
        f"仍坏站点 {len(set(aff))}（含无账本 {len(unfixable)} + 下载失败 {len(failed)}）")


if __name__ == "__main__":
    main()
