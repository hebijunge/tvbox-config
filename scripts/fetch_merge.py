#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox 配置每日拉取合并脚本（stdlib only，无第三方依赖）

流程：拉取上游清单 → 可用性测试与分级 → 合并去重（按 key，先到先得不覆盖）
      → 测速验活（type 0/1 直连站点）→ 失效自动剔除 → 输出 tvbox.json / list.json / status.json

输出：
  tvbox.json   合并后的统一配置
  list.json    上游接口清单（含每条测试记录）
  status.json  状态可视化（总量、分级、站点验活统计、剔除明细）
"""
import json
import os
import re
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

# 上游清单：顺序即合并优先级，同名 key 先到先得、后续不覆盖（不误伤已有源）
UPSTREAMS = [
    ("juhe-tvapi",  "https://raw.githubusercontent.com/ccAzy/juhe-tvapi/main/config.json"),
    ("qist/jsm",    "https://raw.githubusercontent.com/qist/tvbox/master/jsm.json"),
    ("qist/js",     "https://raw.githubusercontent.com/qist/tvbox/master/js.json"),
    ("qist/dianshi","https://raw.githubusercontent.com/qist/tvbox/master/dianshi.json"),
    ("qist/fty",    "https://raw.githubusercontent.com/qist/tvbox/master/fty.json"),
    ("qist/XYQ",    "https://raw.githubusercontent.com/qist/tvbox/master/XYQ.json"),
    ("qist/0821",   "https://raw.githubusercontent.com/qist/tvbox/master/0821.json"),
    ("qist/0825",   "https://raw.githubusercontent.com/qist/tvbox/master/0825.json"),
    ("qist/0826",   "https://raw.githubusercontent.com/qist/tvbox/master/0826.json"),
    ("qist/0827",   "https://raw.githubusercontent.com/qist/tvbox/master/0827.json"),
    ("qist/367",    "https://raw.githubusercontent.com/qist/tvbox/master/367.json"),
    ("qist/9918",   "https://raw.githubusercontent.com/qist/tvbox/master/9918.json"),
    ("qist/99188",  "https://raw.githubusercontent.com/qist/tvbox/master/99188.json"),
    ("gao/js",      "https://raw.githubusercontent.com/gaotianliuyun/gao/master/js.json"),
    ("gao/XYQ",     "https://raw.githubusercontent.com/gaotianliuyun/gao/master/XYQ.json"),
    ("gao/0821",    "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0821.json"),
    ("gao/0825",    "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0825.json"),
    ("gao/0826",    "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0826.json"),
    ("gao/0827",    "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0827.json"),
    ("cluntop/jsm", "https://raw.githubusercontent.com/cluntop/tvbox/main/jsm.json"),
    ("cluntop/box", "https://raw.githubusercontent.com/cluntop/tvbox/main/box.json"),
    ("cluntop/fun", "https://raw.githubusercontent.com/cluntop/tvbox/main/fun.json"),
    ("cluntop/aa",  "https://raw.githubusercontent.com/cluntop/tvbox/main/aa.json"),
    ("cluntop/bb",  "https://raw.githubusercontent.com/cluntop/tvbox/main/bb.json"),
    ("cluntop/wv",  "https://raw.githubusercontent.com/cluntop/tvbox/main/wv.json"),
    ("cluntop/yt",  "https://raw.githubusercontent.com/cluntop/tvbox/main/yt.json"),
    ("cluntop/test","https://raw.githubusercontent.com/cluntop/tvbox/main/test.json"),
    ("nxppru/jsm",  "https://raw.githubusercontent.com/nxppru/tvbox/master/jsm.json"),
    ("nxppru/js",   "https://raw.githubusercontent.com/nxppru/tvbox/master/js.json"),
    ("nxppru/dianshi","https://raw.githubusercontent.com/nxppru/tvbox/master/dianshi.json"),
    ("nxppru/fty",  "https://raw.githubusercontent.com/nxppru/tvbox/master/fty.json"),
    ("nxppru/XYQ",  "https://raw.githubusercontent.com/nxppru/tvbox/master/XYQ.json"),
    ("nxppru/0821", "https://raw.githubusercontent.com/nxppru/tvbox/master/0821.json"),
    ("nxppru/0825", "https://raw.githubusercontent.com/nxppru/tvbox/master/0825.json"),
    ("nxppru/0826", "https://raw.githubusercontent.com/nxppru/tvbox/master/0826.json"),
    ("nxppru/0827", "https://raw.githubusercontent.com/nxppru/tvbox/master/0827.json"),
    ("top98",       "http://home.jundie.top:81/top98.json"),
]


def strip_comments_and_clean(text: str) -> str:
    """去 BOM、去 // 与 /* */ 注释（状态机，不误伤字符串内 //）、去尾随逗号。"""
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


def fetch_config(url: str):
    """两通道重试：直连 → ghproxy（仅 GitHub 链接）。返回 (cfg_dict, http_ms, channel) 或 (None, 0, err)。"""
    attempts = [url]
    if "github" in url:
        attempts.append(gh_url(url))
    last_err = ""
    for ch, u in enumerate(attempts):
        try:
            status, raw, ms = http_get(u, FETCH_TIMEOUT)
            txt = raw.decode("utf-8", "replace")
            cfg = json.loads(strip_comments_and_clean(txt))
            if not isinstance(cfg, dict):
                raise ValueError("top-level is not an object")
            return cfg, ms, ("direct" if ch == 0 else "ghproxy")
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"[:120]
    return None, 0, last_err


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
    """对 site/live/parse 字段里的 GitHub 原链统一加 ghproxy.net 前缀。"""
    if isinstance(value, str):
        return gh_url(value)
    if isinstance(value, list):
        return [rewrite_gh(v) for v in value]
    if isinstance(value, dict):
        return {k: rewrite_gh(v) for k, v in value.items()}
    return value


GH_FIELDS_SITE = ("api", "ext", "jar")
GH_FIELDS_LIVE = ("url",)
GH_FIELDS_PARSE = ("url", "ext")


def main() -> int:
    now = datetime.now(BEIJING)
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S") + " +08:00"

    interfaces = []          # 每条上游的测试记录
    merged: dict = {}        # 全局字段
    sites_by_key: dict = {}
    lives_by_name: dict = {}
    parses_by_name: dict = {}

    print(f"[1/4] 拉取 {len(UPSTREAMS)} 个上游 ...", flush=True)
    with cf.ThreadPoolExecutor(min(8, CONCURRENCY)) as ex:
        results = list(ex.map(fetch_config, [u for _, u in UPSTREAMS]))

    for (name, url), (cfg, ms, info) in zip(UPSTREAMS, results):
        rec = {
            "name": name,
            "url": url,
            "http_ms": ms,
            "channel": info if cfg else "",
            "sites": 0, "lives": 0, "parses": 0,
            "merged_sites": 0, "merged_lives": 0, "merged_parses": 0,
            "grade": "不可用",
            "error": "",
        }
        if cfg is None:
            rec["error"] = info
            interfaces.append(rec)
            print(f"  FAIL {name}: {info}", flush=True)
            continue

        cfg_sites = cfg.get("sites") or []
        cfg_sites = [s for s in cfg_sites if isinstance(s, dict) and s.get("key") and s.get("api")]
        cfg_lives = [l for l in (cfg.get("lives") or []) if isinstance(l, dict) and l.get("name")]
        cfg_parses = [p for p in (cfg.get("parses") or []) if isinstance(p, dict) and p.get("name")]

        added_s = added_l = added_p = 0
        for s in cfg_sites:
            k = merge_key_site(s)
            if k and k not in sites_by_key:
                sites_by_key[k] = rewrite_gh(s)
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
            grade=grade_of(len(cfg_sites), valid),
        )
        for gk in ("spider", "wallpaper"):
            if gk in cfg and gk not in merged and isinstance(cfg[gk], str):
                merged[gk] = rewrite_gh(cfg[gk])
        interfaces.append(rec)
        print(f"  OK   {name}: sites={len(cfg_sites)} lives={len(cfg_lives)} "
              f"parses={len(cfg_parses)} (+{added_s}/{added_l}/{added_p}) {ms}ms", flush=True)

    usable = [r for r in interfaces if r["grade"] != "不可用"]
    if not usable:
        print("所有上游均不可用，中止（不产出配置）", flush=True)
        return 1

    sites = list(sites_by_key.values())
    lives = list(lives_by_name.values())
    parses = list(parses_by_name.values())
    print(f"[2/4] 合并完成：{len(sites)} sites / {len(lives)} lives / {len(parses)} parses", flush=True)

    # ---- 测速验活：仅 type 0/1 且 api 为 http(s) 的直连站点，失败重试一次，仍失败剔除 ----
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

    to_test = [s for s in sites if testable(s)]
    limit = int(os.environ.get("SITE_LIMIT", "0"))
    if limit > 0:
        to_test = to_test[:limit]
    print(f"[3/4] 站点验活：{len(to_test)}/{len(sites)} 个直连站点，并发 {CONCURRENCY} ...", flush=True)
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

    tvbox = dict(merged)
    tvbox["sites"] = kept_sites
    tvbox["lives"] = lives
    tvbox["parses"] = parses
    for fname, obj in (("tvbox.json", tvbox), ("list.json", interfaces), ("status.json", None)):
        if obj is not None:
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=1)

    status = {
        "generated_at": generated_at,
        "summary": {
            "interfaces_total": len(interfaces),
            "interfaces_usable": len(usable),
            "interfaces_full": sum(1 for r in usable if r["grade"] == "完全可用"),
            "interfaces_partial": sum(1 for r in usable if r["grade"] == "部分可用"),
            "interfaces_dead": len(interfaces) - len(usable),
            "sites_total": len(sites),
            "sites_kept": len(kept_sites),
            "sites_tested": len(to_test),
            "sites_tested_pass": tested_pass,
            "sites_removed": len(removed),
            "sites_untested": len(sites) - len(to_test),
            "lives": len(lives),
            "parses": len(parses),
        },
        "interfaces": interfaces,
        "removed_sites": removed,
        "top_interfaces": sorted(
            ({"name": r["name"], "sites": r["sites"], "http_ms": r["http_ms"], "grade": r["grade"]}
             for r in usable), key=lambda x: (-x["sites"], x["http_ms"]),
        )[:15],
    }
    with open("status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)

    print(f"[4/4] 输出完成：tvbox.json / list.json / status.json @ {generated_at}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
