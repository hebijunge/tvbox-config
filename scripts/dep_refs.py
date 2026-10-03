#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deps 引用口径的**唯一权威**：产物显式引用 ∪ deps/manifest.json 账本登记 ∪ 其余消费者文件引用。

为什么要有这个模块
------------------
`scripts/dep_audit.py`（只报告）、`scripts/dep_gc.py`（列 GC 候选）、
`scripts/cleanup_deps.py`（真删 localized/external）历史上各自算一份 refs：

  - dep_audit / dep_gc 只扫 `tvbox.json`，不看 vod/live/short/adult 等分线产物；
  - cleanup_deps 扫 5 个主产物 + stores/*.json，但同样漏了 adult.json /
    adult_live.json；
  - 三处都不看 `deps/manifest.json` 的账本 `local` 字段。

后果是**报告与实际删除用了不同口径**：dep_audit 报"未引用 545MB / 89%"看着像
可清一大半（2026-10-03 实测）；但 manifest 里 1377 条 fetch_merge 已经拉过、
账本仍在登记的 dep 被算成孤儿——照它清理就是拿"账本没跟上的那一面"当"未使用"
判死。抽一份共享函数后：任何一处口径变化会同时反映到报告、候选、实际删除，
`tests/test_dep_refs_authority.py` 用耦合测试钉住三处一致。

用法
----
    from dep_refs import collect_all_refs, collect_product_refs, collect_manifest_refs
    refs = collect_all_refs(repo)      # 合并后的 posix 相对路径集合（无 ./ 前缀）
    prod, mf = collect_product_refs(repo), collect_manifest_refs(repo)

产物清单（PRODUCT_FILES + STORES_GLOB）与 manifest 路径（deps/manifest.json）
在本模块集中定义，改动只需再动这一处。
"""

from __future__ import annotations

import json
import os
import posixpath
import re

# 依赖引用可能出现在哪里
PRODUCT_FILES = (
    "tvbox.json",
    "vod.json",
    "live.json",
    "short.json",
    "status.json",
    "adult.json",       # P2-2 成人专供产物也带 ./deps/ 引用
    "adult_live.json",
)
STORES_DIR = "stores"
STORES_SUFFIX = ".json"

# 7 主产物之外还会写 `./deps/...` 路径的**消费者**文件。2026-10-04 全仓实测：
# HEAD 索引里除 deps/scripts/tests/docs 外有 37 个文件提到 deps 路径，其中真正
# "下游拿去取文件"的只有这几类——`exports/*.json` 是对外导出包（all.json 582 处、
# usable.json 344 处、spider.json 166 处引用），`adult_live_channels/*` 是成人
# 直播列表（adult.m3u 36 处本地路径），`config/upstreams.json` / `list.json` /
# `candidate_upstreams.json` 是入库上游清单（本地路径即抓取输入）。
# 它们原来不在口径里：照旧口径清理会把**真被引用**的 dep 判成孤儿删掉。
CONSUMER_GLOBS = (
    "exports/*.json",
    "adult_live_channels/*",
    "config/upstreams.json",
    "list.json",
    "candidate_upstreams.json",
)

# 反过来，state/ probe/ snapshot/ raw/ 里同样大量出现 deps 路径，但它们是**台账**
# 不是消费者：`state/deps_broken_refs.json` 记的正是"引用了但文件不存在"的 3918 条
# 坏引用，`state/deps_redirect.json` 是 2900 条改名映射（老路径→新路径）。把它们
# 算进引用集会反过来给死文件发放通行证，让 unreferenced 判定大幅虚低。
NON_CONSUMER_DIRS = ("state", "probe", "snapshot", "raw", "raw-vod", "radar")

DEP_RE = re.compile(r"\.?/?deps/[^\s\"'<>\\),;]+")

# 账本 / 备份文件本身：既不会被产物引用，也不能被 dep_gc / cleanup_deps /
# head_slim_deps 从 HEAD 或磁盘移除——否则 collect_manifest_refs 下轮直接读空、
# 全仓 deps 会一夜之间被算成孤儿。
LEDGER_PATHS = frozenset({
    "deps/manifest.json",
    "deps/manifest.json.pre_gc",
})


def collect_ledger_paths() -> frozenset:
    return LEDGER_PATHS


def _norm(raw: str) -> str:
    # Windows 反斜杠、前导 ./、双斜杠统一到 posix 相对仓库根
    return posixpath.normpath(raw.lstrip("./").replace("\\", "/"))


def collect_product_refs(repo: str) -> set[str]:
    """扫所有公开产物里的 ./deps/ 路径。缺文件不阻塞（部分分线产物可能不存在）。"""
    refs: set[str] = set()
    files: list[str] = [os.path.join(repo, f) for f in PRODUCT_FILES]
    stores = os.path.join(repo, STORES_DIR)
    if os.path.isdir(stores):
        for n in sorted(os.listdir(stores)):
            if n.endswith(STORES_SUFFIX):
                files.append(os.path.join(stores, n))
    for p in files:
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                txt = f.read()
        except OSError:
            continue
        for m in DEP_RE.finditer(txt):
            refs.add(_norm(m.group(0)))
    return refs


def collect_consumer_refs(repo: str, deps_dir: str = "deps") -> set[str]:
    """CONSUMER_GLOBS 里提到、且磁盘上确实存在的 dep 路径。

    存在性过滤与 `collect_manifest_refs` 同口径：产物引用一个不存在的路径，那是
    要剥离的坏引用（P0-1），不该反过来保护什么。
    """
    import glob

    refs: set[str] = set()
    for pattern in CONSUMER_GLOBS:
        full = os.path.join(repo, *pattern.split("/"))
        for p in sorted(glob.glob(full)):
            if not os.path.isfile(p):
                continue
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except OSError:
                continue
            for m in DEP_RE.finditer(txt):
                norm = _norm(m.group(0))
                if os.path.isfile(os.path.join(repo, norm)):
                    refs.add(norm)
    return refs


def collect_manifest_refs(repo: str, deps_dir: str = "deps") -> set[str]:
    """deps/manifest.json 里 **磁盘上仍存在** 的 local 字段。

    缺账本 / JSON 坏都按空账本继续，不阻塞审计（审计本来就是只报告）。

    2026-10-03 PR#41 CI 揭示的口径漏账：manifest 9017 unique local 里磁盘匹配
    只约 2000，其余 6800 是"URL 拉过 → 登记 → 上游删了/内容改了 → 老 md5 文件被
    daily checkout 又检出 → 但当前 manifest 里的 local 路径已指向不存在的文件名"
    的历史幽灵。把它们算成"引用"会让 dep_audit 报的 unreferenced 大幅虚低、
    cleanup 决策拿到的分母是错的；`dep_gc.py --prune-manifest`（P1-2 已合）
    负责剪账本自身，这里负责**读取侧**——账本登记 ≠ 文件仍在。
    """
    mf_path = os.path.join(repo, deps_dir, "manifest.json")
    if not os.path.isfile(mf_path):
        return set()
    try:
        with open(mf_path, encoding="utf-8") as f:
            mf = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    refs: set[str] = set()
    if not isinstance(mf, dict):
        return refs
    for rec in mf.values():
        if not isinstance(rec, dict):
            continue
        lp = rec.get("local")
        if not (isinstance(lp, str) and lp):
            continue
        norm = _norm(lp)
        if os.path.isfile(os.path.join(repo, norm)):
            refs.add(norm)
    return refs


def collect_all_refs(repo: str, deps_dir: str = "deps") -> set[str]:
    """权威口径 = 产物显式引用 ∪ manifest 账本登记 ∪ 其余消费者文件引用。"""
    return (collect_product_refs(repo)
            | collect_manifest_refs(repo, deps_dir)
            | collect_consumer_refs(repo, deps_dir))


def split_refs(repo: str, deps_dir: str = "deps") -> tuple[set[str], set[str], set[str]]:
    """给需要按来源分别统计的调用方（dep_audit 报告里要区分 product/manifest/consumer）。"""
    return (collect_product_refs(repo),
            collect_manifest_refs(repo, deps_dir),
            collect_consumer_refs(repo, deps_dir))
