#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deps 引用口径的**唯一权威**：产物显式引用 ∪ deps/manifest.json 账本登记。

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

DEP_RE = re.compile(r"\.?/?deps/[^\s\"'<>\\),;]+")


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


def collect_manifest_refs(repo: str, deps_dir: str = "deps") -> set[str]:
    """deps/manifest.json 的账本 local 字段。缺账本 / JSON 坏都按空账本继续，
    不阻塞审计（审计本来就是只报告）。"""
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
        if isinstance(lp, str) and lp:
            refs.add(_norm(lp))
    return refs


def collect_all_refs(repo: str, deps_dir: str = "deps") -> set[str]:
    """权威口径 = 产物显式引用 ∪ manifest 账本登记。"""
    return collect_product_refs(repo) | collect_manifest_refs(repo, deps_dir)


def split_refs(repo: str, deps_dir: str = "deps") -> tuple[set[str], set[str]]:
    """给需要按来源分别统计的调用方（dep_audit 报告里要区分 product/manifest）。"""
    return collect_product_refs(repo), collect_manifest_refs(repo, deps_dir)
