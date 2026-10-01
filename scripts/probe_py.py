#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5f：py 插件源静态探针（国内本机跑；产物 probe/py_probe.json）。

为什么需要它：main 产物里 py 插件源有 **189 个（141 个 .py 直链 + 48 个 py_ 插件名形态），
此前覆盖率为 0**——现有探针没有一路管 python 插件（5a 只测 type 0/1 的 http api，5b 测 type3
jar 连通性，5c/5e 是 JS 引擎），它们永远记 unknown。

（这里的 189 是重新按产物数出来的。第一版文档写的"1112"是拿台账 interfaces 表的 key 去 join
产物、又用了 `key or name` 兜底，数到了幽灵行上——凡是"某类站有多少"的量级结论，
先确认分母是产物还是台账。）

只做什么、不做什么（这条线只能证明"结构上能不能被加载"）：
  * python 引擎在手机上（TVBox 的 py 运行时），PC 上跑不了真实请求，所以**不产出"能播"级结论**；
  * 绝不 import/exec 这些插件文件（它们是不可信第三方代码，会真发请求/读文件），只做
    `compile()` 语法校验 + AST/正则结构识别；
  * 取不到文件、或结构看不清 → 记 unknown，不判死：PC 取不到网盘直链不代表手机取不到
    （本机实测 189 个里 47 个（25%）在 deps 账本里根本没有记录，全是网盘/私有域直链）。

等级口径（store.classify 里映射）：
  P0 unknown   本地无副本（未下载或源不可达）
  P1 dead      文件在手且 compile() 语法失败（真坏文件，err 带行列）
  P2 unknown   找不到 Spider 类（引擎入口认不出，不能据此说站点死）
  P3 degraded  有 Spider 类但入口方法不全（缺哪个写哪个）
  P4 degraded  类与六个入口方法齐（能被加载的静态证据；不证明能播）
  P? unknown   读文件/解析自身出错

用法（cwd=仓库根）：
  py -3.12 scripts/probe_py.py                     # 全量
  py -3.12 scripts/probe_py.py --limit 20 --out /tmp/py_probe.json
"""
import argparse
import json
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO, "probe", "py_probe.json")

# py 插件的引擎入口约定：class Spider(基类) + 这些方法
ENTRY_METHODS = ("init", "homeContent", "categoryContent", "detailContent",
                 "searchContent", "playerContent")
CLASS_RX = re.compile(r"^\s*class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:", re.M)
DEF_RX = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.M)
IMPORT_RX = re.compile(r"^\s*(?:from|import)\s+([\w\.]+)", re.M)
# 手机端 py 运行时未必带的库：只记 flag，不判死
RISKY_MODS = ("bs4", "lxml", "requests", "Cryptodome", "Crypto", "aiohttp", "pandas")


def load_manifest_index(repo):
    """远程 .py 直链 → deps 里的本地副本（账本 key 形如 "origin|url"）。"""
    path = os.path.join(repo, "deps", "manifest.json")
    idx = {}
    if not os.path.exists(path):
        return idx
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return idx
    for key, v in data.items():
        if not isinstance(v, dict):
            continue
        loc = (v.get("local") or "").replace("\\", "/")
        url = v.get("url") or ""
        orig = key.split("|", 1)[1] if "|" in key else url
        for k in filter(None, (url, orig, loc, loc[2:] if loc.startswith("./") else loc)):
            idx.setdefault(k, loc)
    return idx


def local_py_file(site, repo, idx):
    """返回 (绝对路径或 "", 说明)。说明用于区分"账本无记录"与"有记录但文件没落盘"。"""
    for cand in (str(site.get("api") or ""), str(site.get("ext") or "") if isinstance(site.get("ext"), str) else ""):
        c = cand.split(";")[0].strip()
        if not c:
            continue
        if c.endswith(".py"):
            if c.startswith("./") or c.startswith("deps/") or os.path.isabs(c):
                p = c[2:] if c.startswith("./") else c
                p = p if os.path.isabs(p) else os.path.join(repo, p)
                if os.path.isfile(p):
                    return p, ""
                continue
            if c.startswith("http"):
                loc = idx.get(c)
                if loc:
                    lp = loc if os.path.isabs(loc) else os.path.join(repo, loc)
                    if os.path.isfile(lp):
                        return lp, ""
                    return "", "账本有记录但文件不在盘"
    return "", "账本无记录（网盘/私有域直链）"


def inspect_source(text):
    """结构识别：类名、基类、入口方法、依赖模块。不执行任何插件代码。"""
    classes = [(m.group(1), (m.group(2) or "").strip()) for m in CLASS_RX.finditer(text)]
    defs = set(DEF_RX.findall(text))
    mods = set(m.group(1).split(".")[0] for m in IMPORT_RX.finditer(text))
    spider = ""
    for name, base in classes:
        if name.lower() in ("spider", "spiderimpl") or base in ("Spider", "BaseSpider") or "spider" in base.lower():
            spider = name
            break
    if not spider and classes:
        spider = classes[0][0]
    missing = [m for m in ENTRY_METHODS if m not in defs]
    return {
        "classes": [c[0] for c in classes][:6],
        "spider_class": spider,
        "bases": [c[1] for c in classes][:4],
        "methods_missing": missing,
        "modules": sorted(mods)[:14],
        "risky_modules": sorted(m for m in mods if m in RISKY_MODS),
    }


def probe_one(site, repo, idx):
    api = str(site.get("api") or "")
    r = {"key": site.get("key"), "name": (site.get("name") or "")[:24], "kind": "py",
         "api": api[:120]}
    t0 = time.time()
    fp, note = local_py_file(site, repo, idx)
    if not fp:
        r.update({"level": "P0", "reason": note or "本地无副本"})
        return r
    r["file"] = os.path.relpath(fp, repo).replace("\\", "/")
    try:
        with open(fp, "rb") as f:
            raw = f.read(40 * 1024 * 1024)
    except OSError as e:
        r.update({"level": "P?", "reason": "read:" + type(e).__name__})
        return r
    # 必须整读：只读 600KB 会把 1.5-2.3MB 的大插件切断，报出假的
    # "unterminated string literal"（实测 4 个 P1 里 3 个是这个原因）；
    # BOM 也要吃掉，否则 utf-8 读法让行首多出 U+FEFF 又算一次假语法错。
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", "replace")
    try:
        compile(text, r["file"], "exec")
    except SyntaxError as e:
        r.update({"level": "P1", "reason": "SyntaxError line %s: %s" % (e.lineno, (e.msg or "")[:120])})
        return r
    info = inspect_source(text)
    r["size"] = len(text)
    r.update({k: info[k] for k in ("methods_missing", "risky_modules", "spider_class")})
    if not info["spider_class"]:
        r.update({"level": "P2", "reason": "找不到 Spider 类（classes=%s）" % info["classes"]})
        return r
    if info["methods_missing"]:
        r.update({"level": "P3",
                  "reason": "入口方法不全：缺 %s" % ",".join(info["methods_missing"])})
        return r
    r.update({"level": "P4", "reason": "类与六个入口方法齐（静态可加载）"})
    r["ms"] = int((time.time() - t0) * 1000)
    return r


def is_py_site(s):
    for f in ("api", "ext"):
        v = s.get(f)
        if isinstance(v, str) and v.split(";")[0].strip().endswith(".py"):
            return True
    return False


def main(argv=None):
    if getattr(sys.stdout, "encoding", "").lower().replace("-", "") not in ("utf8", "utf-8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = argv if argv is not None else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="tvbox.json")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    with open(os.path.join(REPO, args.input), encoding="utf-8") as f:
        doc = json.load(f)
    sites = [s for s in (doc.get("sites") or []) if is_py_site(s)]
    idx = load_manifest_index(REPO)
    if args.limit:
        sites = sites[:args.limit]
    print(f"[py] 待测 py 源 {len(sites)} 个（deps 账本 {len(idx)} 条映射）", flush=True)

    rows = []
    t0 = time.time()
    for i, s in enumerate(sites, 1):
        try:
            rows.append(probe_one(s, REPO, idx))
        except Exception as e:      # 单站异常不拖垮整轮
            rows.append({"key": s.get("key"), "name": (s.get("name") or "")[:24], "kind": "py",
                         "level": "P?", "reason": type(e).__name__})
        if i % 200 == 0 or i == len(sites):
            print(f"  ... {i}/{len(sites)} ({int(time.time() - t0)}s)", flush=True)

    from collections import Counter
    levels = Counter(r.get("level") for r in rows)
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "summary": {"total": len(rows), "levels": dict(levels),
                       "note": "py 插件源静态判定：P4/P3=结构可加载(degraded)，P1=语法坏(dead)，"
                               "P0/P2=取不到或认不出(unknown)；不执行插件代码，不证明能播"},
           "sites": rows}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[py] 完成：{dict(levels)} -> {os.path.basename(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
