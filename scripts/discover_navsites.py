#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置聚合导航站爬取：从公开导航页提取 GitHub/Gitee 仓库外链。

比从零搜索命中率高：导航站作者已经替我们筛过一遍。
纯标准库（urllib + re + json），单站失败不影响整体。

用法
----
    python scripts/discover_navsites.py
    python scripts/discover_navsites.py --out candidate_navsites.json
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 种子导航站（可后续扩展）。均为公开可访问的聚合/导航页。
NAV_SITES = [
    "https://tvbox.cyou/",
    "https://github.com/topics/tvbox",
    "https://github.com/topics/catvod",
    "https://github.com/topics/tvbox-config",
    "https://catvods.github.io/",
]

# 匹配 GitHub / Gitee 仓库首页链接（owner/repo 两级，不带后续路径）
REPO_RE = re.compile(
    r"https?://(?:github\.com|gitee\.com)/[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+",
    re.I)
# 排除 GitHub/Gitee 自身的非仓库页
DROP_RE = re.compile(
    r"/(topics|search|about|login|signup|features|pricing|explore|settings|"
    r"notifications|new|organizations|topics|collections|trending|"
    r"(?:github\.com|gitee\.com)/[^/]+/?$)",
    re.I)
# 排除仓库内部路径（tree/blob/issues/pull/actions 等），只保留仓库根
INNER_RE = re.compile(
    r"/(tree|blob|issues|pull|actions|wiki|releases|commit|commits|tags|branches)/",
    re.I)


def fetch(url, timeout=10):
    """拉取页面文本。connect/read 共超时 timeout 秒。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(5_000_000)  # 导航页不会太大，限 5MB
    return raw.decode("utf-8", "replace")


def extract_repos(html):
    """从 HTML 文本提取去重后的 GitHub/Gitee 仓库根链接。"""
    found = set()
    for m in REPO_RE.finditer(html):
        u = m.group(0).rstrip(".,;)\"'<>]")
        if DROP_RE.search(u):
            continue
        if INNER_RE.search(u):
            continue
        # 去掉尾部可能的 .git
        u = u[:-4] if u.endswith(".git") else u
        # 归一化：去掉尾斜杠
        u = u.rstrip("/")
        found.add(u)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="candidate_navsites.json")
    ap.add_argument("--timeout", type=int, default=10)
    args = ap.parse_args()

    by_site = {}
    all_repos = set()
    for site in NAV_SITES:
        try:
            html = fetch(site, timeout=args.timeout)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"[导航] {site} 失败：{type(e).__name__} {e}", flush=True)
            by_site[site] = {"error": f"{type(e).__name__}", "repos": []}
            continue
        repos = extract_repos(html)
        by_site[site] = {"repos": sorted(repos)}
        all_repos |= repos
        print(f"[导航] {site} → {len(repos)} 个仓库链接", flush=True)
        time.sleep(1)

    doc = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "配置聚合导航站爬取的 GitHub/Gitee 仓库外链，候选池；"
                "种子列表可在 NAV_SITES 扩展",
        "total": len(all_repos),
        "repos": sorted(all_repos),
        "by_site": by_site,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"[导航] 合计 {len(all_repos)} 个仓库，写入 {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
