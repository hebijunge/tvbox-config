#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上游候选评估：算「独有站点数」，回答「这个候选到底带不带新内容」。

为什么需要它
------------
discover_upstreams.py 能发现候选并按 score（可达 + 是 TVBox 配置 + 站点数）打分，
但 TVBox 生态互相抄配置极普遍：一个 score=100 的新上游，里面的站点可能我们早都有了。
直接按 score 自动收编，只会把重复站点灌进合并结果，反而稀释质量。

所以收编前必须先过一道「独有度」：
  指纹 = sha1(归一化的 api + ext)，与当前 tvbox.json 的站点指纹集合比对，
  算出 候选总站点 / 重合 / 独有 / 独有率，按「独有数」而非 score 排序。

产出 radar/candidate_eval.json，供：
  1. 人工/自动决定哪些候选进 canary（state/extra_upstreams.json）
  2. 给 discover 的阈值提供依据（独有站点 >= N 才值得收编）

用法
----
    python scripts/evaluate_candidates.py
    python scripts/evaluate_candidates.py --min-unique 5      # 只看独有>=5 的
    python scripts/evaluate_candidates.py --probe radar/discovered.json --base tvbox.json
"""
import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor


def norm(v):
    """把 ext（可能是 dict/str/None）归一化成稳定字符串，用于指纹。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(v)


def fingerprint(site: dict) -> str:
    """站点指纹：api + ext（与 dedup 的二级指纹口径一致）。"""
    key = f"{site.get('api') or ''}|{norm(site.get('ext'))}"
    return hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()


def sites_of(doc):
    """兼容各种顶层形态：{'sites':[...]} / {'video':[...]} / 裸数组 [{...}]。

    上游配置格式并不统一，裸数组（顶层就是站点列表）是真实存在的形态，
    必须兼容——否则一条非预期格式就会把整轮评估带崩。
    裸数组分支要求 api（与 discover_upstreams.sites_of 同口径）：只认 name 会把
    Alist 服务器列表那类「有 name 无 api」的数组当站点，而这里数出来的 unique
    直接决定 canary 收编，虚高比误杀更贵。
    """
    if isinstance(doc, list):
        return [x for x in doc if isinstance(x, dict) and x.get("api")]
    if isinstance(doc, dict):
        v = doc.get("sites") or doc.get("video") or []
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
    return []


def http_get(url, timeout=15):
    """拉 URL；github 链接走每日实测镜像链。

    这里曾与 discover_upstreams 一样写死 `https://ghproxy.net/`（该站不在每日实测池、
    09-19 实测仅 47KB/s）——而本脚本的 unique 完全取决于能不能取到候选内容，
    慢镜像＝候选被算成 0 独有＝直接漏收编。取数实现统一交给 discover_upstreams，
    避免同一份逻辑三处漂移。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import discover_upstreams as _du
    _st, raw = _du.http_get(url, timeout, 4_000_000)
    return raw.decode("utf-8", "replace")


def load_base_fps(path):
    """当前产物里的站点指纹集合（去重基准）。"""
    doc = json.load(open(path, encoding="utf-8"))
    sites = doc.get("sites") or doc.get("video") or []
    return {fingerprint(s) for s in sites if isinstance(s, dict)}, len(sites)


def _looks_like_live(text: str) -> bool:
    """直播列表形态（m3u / txt #genre#），不是点播配置。"""
    head = text[:2000]
    return ("#EXTM3U" in head) or ("#EXTINF" in head) or ("#genre#" in head)


def _looks_like_html(text: str) -> bool:
    head = text[:200].lstrip().lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or head.startswith("<svg")


def eval_one(cand, base_fps):
    url = cand.get("url")
    out = dict(cand)
    out.update(total=0, dup=0, unique=0, unique_rate=0.0, err="", skipped="")
    try:
        txt = http_get(url)
    except Exception as e:
        out["err"] = str(e)[:120]
        return out
    # 与 discover_upstreams.probe_candidate 同口径：先按形态分流，再谈解析。
    # 旧实现直接 json.loads，导致「直播列表 / HTML 页 / SVG」全被记成
    # `Expecting value: line 1 column 1`——55 条失败里 32 条是这么来的，
    # 看着像通道坏了，其实是候选本身不是点播配置。
    if _looks_like_live(txt):
        out["skipped"] = "直播列表（走直播线，不算点播独有度）"
        out["entries"] = txt.count("#EXTINF") or txt.count(",http")
        return out
    if _looks_like_html(txt):
        out["err"] = "HTML/SVG 页面（非配置，候选池噪声）"
        return out
    try:
        doc = json.loads(txt.lstrip("\ufeff \t\r\n"))
    except Exception as e:
        out["err"] = f"{type(e).__name__}: {str(e)[:90]}"
        return out
    try:
        sites = sites_of(doc)
        if not sites:
            out["err"] = "无站点数组（格式未识别）"
            return out
        fps = [fingerprint(s) for s in sites]
        dup = sum(1 for f in fps if f in base_fps)
        total = len(fps)
        out.update(total=total, dup=dup, unique=total - dup,
                   unique_rate=round((total - dup) / total, 3) if total else 0.0,
                   bytes=len(txt.encode("utf-8")))
    except Exception as e:      # 单条解析异常绝不能带崩整轮
        out["err"] = "解析异常: " + str(e)[:100]
    return out


def kind_of(cand: dict) -> str:
    """判定候选归属：点播 tvbox / 直播 live。

    只看 discover 给的 kind 不够准——实测发现含有效 sites 的配置会被判成 other，
    而 m3u8/直播数据混在点播池里会被当坏源。按 URL 特征再校一次。
    """
    u = (cand.get("url") or "").lower()
    k = (cand.get("kind") or "").lower()
    if k == "m3u" or "m3u8" in u or "/live" in u or u.endswith(".txt") or u.endswith(".m3u"):
        return "live"
    return "tvbox"


def write_canary(repo, picked, out_rel, min_unique):
    """按 unique（不是 score）重写 canary 池。

    score 已被证明与「能带来多少新站点」无关：score 30 的候选带来 17 个独有站点，
    score 90 的只带来 3 个。所以收编标准必须是 unique。
    手动黑名单（state/blacklist_manual.txt，与 fetch_merge 同一份）：name 或 url 命中
    即永不收编——否则收编池重建时已拉黑的上游会换个名字混回来。
    """
    bl_path = os.path.join(repo, "state", "blacklist_manual.txt")
    bl = []
    if os.path.isfile(bl_path):
        for ln in open(bl_path, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                bl.append(ln)

    def banned(c):
        url, name = str(c.get("url", "")), str(c.get("name", ""))
        for x in bl:
            if x == url or x == name:
                return True
            if len(x) >= 8 and (x in url or url in x):
                return True
        return False

    ups, skipped_live, skipped_black = [], [], []
    for i, c in enumerate(picked, 1):
        if banned(c):
            skipped_black.append(c)
            continue
        if kind_of(c) == "live":
            skipped_live.append(c)
            continue
        _u = c.get("url")
        # 2026-09-26 治理：jsdelivr 主域规范为 fastly 子域（与 fetch_merge._norm_jsdelivr 同口径）
        if isinstance(_u, str) and "://cdn.jsdelivr.net/" in _u:
            _u = _u.replace("://cdn.jsdelivr.net/", "://fastly.jsdelivr.net/")
        ups.append({
            "name": "auto-u%d-%dn" % (i, c.get("unique", 0)),
            "kind": "tvbox",
            "url": _u,
            "auto": True,
            "score": c.get("score", 0),
            "unique": c.get("unique", 0),
            "total": c.get("total", 0),
        })
    doc = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "note": "按独有站点数(unique)自动收编的 canary 上游；默认不并入主流程，"
                "需 EXTRA_UPSTREAMS=1 才生效。收编标准已由 score 改为 unique。",
        "criteria": {"min_unique": min_unique, "sorted_by": "unique desc"},
        "upstreams": ups,
    }
    p = os.path.join(repo, out_rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[canary] 已按 unique 写入 {len(ups)} 个上游 -> {out_rel}")
    for u in ups:
        print(f"    unique={u['unique']:3d} total={u['total']:3d} (score={u['score']})  {u['url']}")
    if skipped_live:
        print(f"[canary] 另有 {len(skipped_live)} 个疑似直播源未入点播池（应走直播链路）:")
        for c in skipped_live:
            print(f"    unique={c.get('unique')}  {c.get('url')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default="radar/discovered.json")
    ap.add_argument("--base", default="tvbox.json")
    ap.add_argument("--out", default="radar/candidate_eval.json")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-unique", type=int, default=0, help="只在报告里展示/收编独有>=N 的候选")
    ap.add_argument("--write-canary", action="store_true",
                    help="按独有站点数重写 canary 池（默认不写，避免误改线上数据）")
    ap.add_argument("--from-eval", default="",
                    help="直接复用已有评估结果生成 canary，不重新拉取（省一轮网络）")
    ap.add_argument("--canary-out", default="state/extra_upstreams.json")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)

    # 复用已有评估结果直接更新 canary：不重新拉取（一轮网络 5 分钟 → 秒级）
    if args.from_eval:
        ev = json.load(open(os.path.join(repo, args.from_eval), encoding="utf-8"))
        cands = ev.get("candidates") or []
        picked = [c for c in cands if c.get("unique", 0) >= args.min_unique and not c.get("err")]
        picked.sort(key=lambda c: -c.get("unique", 0))
        if args.write_canary:
            write_canary(repo, picked, args.canary_out, args.min_unique)
        else:
            print(f"（未指定 --write-canary，仅预览 {len(picked)} 个）")
            for c in picked:
                print(f"    unique={c.get('unique')}  {c.get('url')}")
        return 0

    doc = json.load(open(os.path.join(repo, args.probe), encoding="utf-8"))
    cands = doc.get("candidates") or []
    base_fps, base_n = load_base_fps(os.path.join(repo, args.base))
    print(f"[eval] 基准 {args.base}: {base_n} 站点 / {len(base_fps)} 个去重后指纹")
    print(f"[eval] 候选 {len(cands)} 个，并发 {args.workers}")

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(lambda c: eval_one(c, base_fps), cands):
            results.append(r)

    results.sort(key=lambda r: (-r.get("unique", 0), -r.get("score", 0)))

    os.makedirs(os.path.dirname(os.path.join(repo, args.out)), exist_ok=True)
    # 汇总要能分清「成功评估 / 直播列表跳过 / HTML 噪声 / 真解析失败」，
    # 否则 fetch_ok 会把跳过的也算成功（旧口径就是靠这个掩盖了 32 条假失败）
    _skipped = sum(1 for r in results if r.get("skipped"))
    _html = sum(1 for r in results if str(r.get("err", "")).startswith("HTML/SVG"))
    _noarr = sum(1 for r in results if str(r.get("err", "")).startswith("无站点数组"))
    _fetch_fail = sum(1 for r in results
                      if r.get("err") and not str(r["err"]).startswith(("HTML/SVG", "无站点数组")))
    summary = {
        "candidates": len(results),
        "evaluated": sum(1 for r in results
                         if not r.get("err") and not r.get("skipped")),
        "skipped_live": _skipped,
        "html_noise": _html,
        "no_sites": _noarr,
        "fetch_or_parse_failed": _fetch_fail,
        "fetch_ok": sum(1 for r in results if not r.get("err")),   # 兼容旧字段名
        "with_unique": sum(1 for r in results if r.get("unique", 0) > 0),
        "total_unique_sites": sum(r.get("unique", 0) for r in results),
    }
    with open(os.path.join(repo, args.out), "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "note": "候选独有度评估：unique=该候选带来、当前产物里没有的新站点数。"
                    "收编应看 unique 而非 score。",
            "base": {"file": args.base, "sites": base_n, "unique_fps": len(base_fps)},
            "summary": summary,
            "candidates": results,
        }, f, ensure_ascii=False, indent=1)
    print(f"[eval] 汇总：评估成功 {summary['evaluated']} / 直播列表跳过 {summary['skipped_live']} "
          f"/ HTML 噪声 {summary['html_noise']} / 无站点数组 {summary['no_sites']} "
          f"/ 取数或解析失败 {summary['fetch_or_parse_failed']}（共 {len(results)} 条）", flush=True)

    print("\n==== 候选独有度（按 unique 降序；只看 score 会被重复站点误导）====")
    print(f"{'score':>5} {'站点':>5} {'重合':>5} {'独有':>5} {'独有率':>6}  url")
    shown = 0
    for r in results:
        if r.get("unique", 0) < args.min_unique:
            continue
        shown += 1
        if shown > 25:
            print("  ...（其余见产物）")
            break
        err = ("  <拉取失败: %s>" % r["err"][:40]) if r.get("err") else ""
        print(f"{r.get('score',0):>5} {r.get('total',0):>5} {r.get('dup',0):>5} "
              f"{r.get('unique',0):>5} {r.get('unique_rate',0):>6}  {r.get('url','')[:72]}{err}")

    s = sum(r.get("unique", 0) for r in results)
    print(f"\n合计可带来新站点: {s} 个（来自 {sum(1 for r in results if r.get('unique',0)>0)} 个候选）")
    print(f"产物: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
