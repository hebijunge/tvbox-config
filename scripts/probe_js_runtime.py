#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 JS 源（drpy/drpy2）的真实运行探针。

外部 HTTP 探针只能查到「规则文件在不在、URL 模板能不能拼」，拿不到「它到底能不能搜到片」。
这里直接用 Node 跑 drpy2 引擎（宿主见 `.workbuddy/drpy-sandbox/host.mjs`），
按五关实测：home / category / search / detail / play。

评级（对齐 csp 那套口径）：
    J5 播放通 · J4 详情通 · J3 搜索通 · J2 分类通 · J1 仅首页 · J0 失败 · J? 超时/网络问题不判死

用法:
    python probe_js_runtime.py --limit 20          # 先小样本
    python probe_js_runtime.py --concurrency 4     # 全量
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))          # 本文件在 scripts/ 下，仓库根是上一层
SANDBOX = os.path.join(REPO, ".workbuddy", "drpy-sandbox")
NODE = os.environ.get(
    "NODE_BIN", r"C:\Users\ajun\.workbuddy\binaries\node\versions\22.22.2-3\node.exe")
HOST = os.path.join(SANDBOX, "host.mjs")

TIMEOUT_HOME = 150


def level_of(r):
    if r.get("timeout"):
        return "J?"
    if r.get("play"):
        return "J5"
    if r.get("detail"):
        return "J4"
    if r.get("search"):
        return "J3"
    if r.get("cat"):
        return "J2"
    if r.get("home"):
        return "J1"
    # 一次请求都没发出去 → 多半是环境/网络，别判死
    if not r.get("reqs"):
        return "J?"
    return "J0"


def probe_one(task):
    rule, key, name = task["rule"], task["key"], task["name"]
    cmd = [NODE, HOST, "--rule", rule, "--op", "all", "--kw", "庆余年"]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_HOME, cwd=REPO)
        out = (p.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        r = {}
        for line in reversed(out):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    r = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if not r:
            return {"key": key, "name": name, "rule": rule, "level": "J0",
                    "reason": "无结果输出", "ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"key": key, "name": name, "rule": rule, "level": "J?",
                "reason": f"超时>{TIMEOUT_HOME}s", "ms": int((time.time() - t0) * 1000)}
    r["key"] = key
    r["name"] = name
    r["level"] = level_of(r)
    r.setdefault("ms", int((time.time() - t0) * 1000))
    return r


def collect_tasks(repo):
    with open(os.path.join(repo, "tvbox.json"), encoding="utf-8") as f:
        d = json.load(f)
    tasks = []
    for s in d.get("sites") or []:
        api = s.get("api")
        if not (isinstance(api, str) and api.startswith("./") and "drpy" in api):
            continue
        ext = s.get("ext")
        if not isinstance(ext, str) or not ext:
            continue
        rel = ext.split("?")[0]
        rel = rel[2:] if rel.startswith("./") else rel.lstrip("/")
        fp = os.path.join(repo, rel.replace("/", os.sep))
        if not os.path.isfile(fp):
            continue
        tasks.append({"rule": rel.replace(os.sep, "/"), "key": s.get("key"), "name": s.get("name")})
    return tasks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--out", default=os.path.join(REPO, "probe", "js_runtime_probe.json"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--kw", default="庆余年")
    args = ap.parse_args()

    if not os.path.isfile(HOST):
        print(f"[jsrt] 找不到宿主 {HOST}", flush=True)
        return 1
    tasks = collect_tasks(args.repo)
    print(f"[jsrt] 可实测的 JS 规则 {len(tasks)} 个（引擎 drpy/drpy2，且本地有规则文件）", flush=True)
    if args.limit:
        tasks = tasks[: args.limit]

    t0 = time.time()
    results = []
    with ThreadPoolExecutor(args.concurrency) as ex:
        for i, r in enumerate(ex.map(probe_one, tasks), 1):
            results.append(r)
            if i % 10 == 0 or i == len(tasks):
                ok = sum(1 for x in results if x["level"] in ("J5", "J4", "J3"))
                print(f"  ... {i}/{len(tasks)}  可用(J3+)={ok}  {int(time.time()-t0)}s", flush=True)

    stats = {}
    for r in results:
        stats[r["level"]] = stats.get(r["level"], 0) + 1
    doc = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "Node 沙箱跑 drpy2 引擎实测本地 JS 源五关（home/category/search/detail/play）",
        "summary": {"total": len(results), "levels": stats},
        "sites": results,
    }
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"[jsrt] 等级分布 {stats}", flush=True)
    print(f"[jsrt] 产物 -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
