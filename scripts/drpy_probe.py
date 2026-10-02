#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
drpy Node 沙箱批量实测。

目标：把仓库里「本地 drpy JS 源」（type=3, api 含 drpy, 规则在 ext 指向的 .js 文件）
用 host.mjs 在 Node 沙箱里真跑五关（home/category/search/detail/play），
产出 probe/drpy_probe.json（与 probe/csp_probe.json 同构，靠 key 匹配），供 rank_sites.py 排序消费。

之前外部 HTTP 探针对 type 3 只能查「规则文件在不在」，拿不到「能不能搜到片」；
真机 jar 测只覆盖 csp 爬虫类（api 以 csp_ 开头），覆盖不到这 ~280 个 drpy 源。
Node 沙箱是唯一能低成本覆盖它们的手段。

产物格式（对齐 csp_probe.json）：
  {
    "generated_at": ...,
    "note": ...,
    "summary": {"total": N, "levels": {"D5":x,"D4":x,"D3":x,"D2":x,"D1":x,"D0":x},
                "searchable": k, "detail_ok": j, "play_ok": p},
    "sites": [ {key, name, rule, type, home, cat, search, detail, play, ms, reqs, grade, level, err} ]
  }

用法：
  python drpy_probe.py                 # 全量（输出到 <repo>/probe/drpy_probe.json）
  python drpy_probe.py --limit 5      # 调试：只跑前 5 个
  python drpy_probe.py --kw 庆余年 --workers 6 --out /tmp/x.json
"""
import json
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import shutil

HERE = os.path.dirname(os.path.abspath(__file__))               # scripts/
REPO = os.path.abspath(os.path.join(HERE, ".."))                # 仓库根
# Node 可执行文件：CI 用 PATH 里的 node；本地回退到 WorkBuddy 自带版本
NODE = (os.environ.get("NODE_BIN") or shutil.which("node")
        or r"C:\Users\ajun\.workbuddy\binaries\node\versions\22.22.2-3\node.exe")
HOST = os.path.join(REPO, "drpy-sandbox", "host.mjs")
OUT = os.path.join(REPO, "probe", "drpy_probe.json")

# 按源「类型」选默认热词，让可搜性统计更有意义
HOT = {
    "影视": "庆余年",
    "动漫": "火影",
    "音频": "周杰伦",
    "听书": "斗破",
    "直播": "英雄联盟",
}
DEFAULT_KW = "庆余年"


def rule_path_of(site):
    """从 type=3 本地 drpy 源的 ext 字段解析出规则文件路径。"""
    ext = site.get("ext")
    if isinstance(ext, str):
        return ext
    if isinstance(ext, dict):
        for k in ("json", "url", "file", "rule", "js", "path"):
            if k in ext and isinstance(ext[k], str):
                return ext[k]
    return None


def collect_jobs():
    tv = json.load(open(os.path.join(REPO, "tvbox.json"), encoding="utf-8"))
    sites = tv.get("sites", [])
    jobs = []
    for s in sites:
        api = s.get("api", "") or ""
        if "drpy" not in api.lower():
            continue
        rp = rule_path_of(s)
        if not rp:
            continue
        full = os.path.join(REPO, rp.lstrip("./"))
        if not os.path.exists(full):
            continue  # Windows 非法路径未落盘的约 10 个，跳过
        jobs.append({
            "key": s.get("key"),
            "name": s.get("name"),
            "rule": rp,
            "full": full,
            "type": (s.get("type_name") or "").strip(),
        })
    return jobs


def run_one(job, kw):
    name, rule, full = job["name"], job["rule"], job["full"]
    try:
        p = subprocess.run(
            [NODE, HOST, "--rule", full, "--op", "all", "--kw", kw],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=90, cwd=HERE,
        )
        lines = [l for l in p.stdout.splitlines() if l.strip().startswith("{")]
        if not lines:
            # 这条早退以前漏了 key：产物里整批行没有 key，store 按 key 入库会全部跳过，
            # 而撤回逻辑反过来把它们当成「本轮不再报」清掉——一次沙箱故障会连带抹掉历史判定。
            return {"key": job["key"], "name": name, "rule": rule, "ok": False,
                    "err": "no-json:" + (p.stderr or "")[-240:]}
        r = json.loads(lines[-1])
        r["key"] = job["key"]
        r["name"] = name
        r["rule"] = rule
        r["type"] = job["type"]
        r["level"] = r.get("grade")  # 对齐 csp_probe 的 level 字段，便于 rank_sites 统一读取
        return r
    except subprocess.TimeoutExpired:
        return {"key": job["key"], "name": name, "rule": rule, "ok": False, "err": "timeout>90s"}
    except Exception as e:
        return {"key": job["key"], "name": name, "rule": rule, "ok": False, "err": str(e)[:240]}


SANDBOX_BROKEN_HINTS = ("MODULE_NOT_FOUND", "Cannot find", "no-json")


def sandbox_broken(results):
    """这一轮的 drpy 结果是不是「沙箱坏掉」而不是「站点都死了」。

    真实站点不会 100% 在同一轮里同时失败；全 D0 且错误信息里带模块缺失/no-json，
    只能是工装自己出问题（依赖没装、node 版本、host.mjs 报错）。这种情况必须拒绝覆写，
    否则一次环境缺失就会把真实的五关历史抹成一片死。
    """
    total = len(results)
    if not total or sum(1 for r in results if r.get("grade") != "D0") > 0:
        return False
    brk = sum(1 for r in results
              if any(t in (r.get("err") or "") for t in SANDBOX_BROKEN_HINTS))
    return brk >= max(1, int(total * 0.9))


def grade(r):
    """对齐 csp 口径：D5五关全通 / D4详情 / D3搜索 / D2分类 / D1首页 / D0失败。"""
    home = bool(r.get("home"))
    cat = bool(r.get("cat"))
    search = bool(r.get("search"))
    detail = bool(r.get("detail"))
    play = bool(r.get("play"))
    if home and cat and search and detail and play:
        return "D5"
    if detail:
        return "D4"
    if search:
        return "D3"
    if cat:
        return "D2"
    if home:
        return "D1"
    return "D0"


def main():
    argv = sys.argv[1:]
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 0
    kw = argv[argv.index("--kw") + 1] if "--kw" in argv else ""
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 5
    out = argv[argv.index("--out") + 1] if "--out" in argv else OUT

    # fail-fast：沙箱或 node 缺失时不 spawn、不覆写既有产物（否则会拿 MODULE_NOT_FOUND
    # 把真实的 drpy 实测结果全刷成 D0）。本地沙箱未重建属正常态，保留上一版产物。
    if not os.path.exists(HOST):
        print(f"[!] 沙箱缺失 {HOST}，跳过 drpy 实测，保留现有产物 {out}（不覆写）", flush=True)
        return 0
    if not (NODE and os.path.exists(NODE)):
        print(f"[!] node 不可用（NODE={NODE}），跳过 drpy 实测，不覆写产物", flush=True)
        return 0
    # 只查 host.mjs / node 在不在是不够的：新 worktree 里源码齐、node 也在，缺的只是
    # node_modules（.gitignore 忽略它，要 npm ci 现装）。这时每个源都以
    # ERR_MODULE_NOT_FOUND 失败 → 整份产物刷成 D0，比"没跑"更糟（2026-10-02 就这么
    # 合进过 main 一次）。所以依赖缺失也必须当沙箱缺位处理。
    if not os.path.isdir(os.path.join(REPO, "drpy-sandbox", "node_modules")):
        print("[!] 沙箱依赖未安装（缺 drpy-sandbox/node_modules），跳过 drpy 实测，"
              "不覆写产物。先跑：cd drpy-sandbox && npm ci", flush=True)
        return 0

    jobs = collect_jobs()
    if limit:
        jobs = jobs[:limit]
    print(f"[*] 本地 drpy 源（规则文件存在）共 {len(jobs)} 个，并发 {workers}，热词='{kw or '按类型自动'}'")

    results = []
    t0 = time.time()
    done = 0

    def pick_kw(job):
        if kw:
            return kw
        return HOT.get(job["type"], DEFAULT_KW)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_one, j, pick_kw(j)): j for j in jobs}
        for f in futs:
            r = f.result()
            r["grade"] = grade(r)
            r["level"] = r.get("grade")
            results.append(r)
            done += 1
            if done % 20 == 0 or done == len(jobs):
                el = time.time() - t0
                print(f"    [{done}/{len(jobs)}] {el:.0f}s  最近: {r.get('name')} -> {r.get('grade')}")

    # 统计
    gc = Counter(r["grade"] for r in results)
    searchable_yes = sum(1 for r in results if r.get("search"))
    detail_yes = sum(1 for r in results if r.get("detail"))
    play_yes = sum(1 for r in results if r.get("play"))
    total = len(results)
    summary = {
        "total": total,
        "levels": {g: gc.get(g, 0) for g in ("D5", "D4", "D3", "D2", "D1", "D0")},
        "searchable": searchable_yes,
        "detail_ok": detail_yes,
        "play_ok": play_yes,
    }
    doc = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "note": "drpy Node 沙箱五关实测（home/cat/search/detail/play）。"
                "grade: D5五关全通/D4详情通/D3搜索通/D2分类通/D1仅首页/D0失败。",
        "summary": summary,
        "sites": results,
    }
    # 兜底闸门：见 sandbox_broken 的判据说明。
    if sandbox_broken(results):
        print(f"[!] {total}/{total} 源全 D0 且错误形态像沙箱故障（模块缺失/no-json）"
              f"——判定为工装问题，跳过覆写 {out}", flush=True)
        return 0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n==== 统计 ====")
    print(f"总源数: {total}")
    for g in ("D5", "D4", "D3", "D2", "D1", "D0"):
        print(f"  {g}: {gc.get(g, 0)}")
    print(f"  可搜(search): {searchable_yes} ({100 * searchable_yes // max(total, 1)}%)")
    print(f"  详情通过:     {detail_yes}")
    print(f"  播放通过:     {play_yes}")
    print(f"产物: {out}")
    print(f"总耗时: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    # Windows 直跑时 stdout 默认 GBK，站点名带 emoji 会在打印处 UnicodeEncodeError 崩掉整轮
    # （run_all/CI 子进程有 PYTHONIOENCODING=utf-8，只有单脚本直跑踩这个坑）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
