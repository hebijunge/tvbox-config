#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snapshot_rotate.py — snapshot 止血后的每日轮换（2026-09-25 P1 收口，总调度拍板）

背景
----
snapshot/（上游原始抓取快照）此前每日全量入 git，历史累计 172MB / 2591 文件。
2026-09-25 止血（不做 git 历史重写）：
  · 历史日 zip 归档到 Release `snapshot-archive`（snapshot-YYYYMMDD.zip）；
  · .gitignore 增加 snapshot/，快照不再随 `git add snapshot/` 入库；
  · 主干树只保留最新一日快照——本脚本在 daily.yml 提交前轮换：
    git rm --cached 旧日（保留工作区文件）+ git add -f 最新日；
  · Release 维度 14 天滚动清理（本脚本 --prune-release）。

用法（daily.yml 内，GH_TOKEN 由工作流 env 提供）
------------------------------------------------
  python scripts/snapshot_rotate.py                      # 轮换 git 跟踪
  python scripts/snapshot_rotate.py --prune-release      # 轮换 + Release 14 天滚动
  # 可选 --release snapshot-archive --keep-release-days 14 --dry-run
"""
import argparse
import json
import os
import re
import subprocess
import sys

RELEASE_TAG = "snapshot-archive"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def list_day_dirs(snapshot_dir):
    """snapshot/ 下的日期目录名，升序。"""
    if not os.path.isdir(snapshot_dir):
        return []
    return sorted(d for d in os.listdir(snapshot_dir)
                  if os.path.isdir(os.path.join(snapshot_dir, d)) and DATE_RE.match(d))


def list_tracked_day_dirs(snapshot_dir):
    """git 已跟踪的 snapshot 日期目录名（git ls-files snapshot/），升序。"""
    out = subprocess.run(["git", "ls-files", snapshot_dir],
                         capture_output=True, text=True, timeout=60)
    days = set()
    for ln in out.stdout.splitlines():
        parts = ln.split("/")
        if len(parts) >= 2 and DATE_RE.match(parts[1]):
            days.add(parts[1])
    return sorted(days)


def decide(day_dirs, tracked_days):
    """纯决策函数（单测覆盖点）：
    返回 (to_untrack, to_track)——主干只保留最新一日快照。
    to_untrack：已跟踪的非最新日；to_track：最新日中尚未跟踪的。
    day_dirs 为空时两者皆空（CI 异常时不误删任何跟踪）。"""
    if not day_dirs:
        return [], []
    newest = day_dirs[-1]
    to_untrack = [d for d in tracked_days if d != newest]
    to_track = [newest] if newest not in tracked_days else []
    return to_untrack, to_track


def asset_date(name):
    """snapshot-YYYYMMDD.zip → YYYY-MM-DD；非日期命名返回 None。"""
    m = re.match(r"^snapshot-(\d{4})(\d{2})(\d{2})\.zip$", name or "")
    return "%s-%s-%s" % m.groups() if m else None


def decide_release_prune(asset_names, cutoff, retain=()):
    """纯决策函数（单测覆盖点）：返回 (to_delete, to_keep)。
    cutoff: 'YYYY-MM-DD'，早于（不含）该日的日期命名附件删除；
    retain: 永不删除名单（防御性参数，当前为空）。"""
    to_delete, to_keep = [], []
    for n in asset_names:
        d = asset_date(n)
        if d and d < cutoff and n not in retain:
            to_delete.append(n)
        else:
            to_keep.append(n)
    return sorted(to_delete), sorted(to_keep)


def gh_api(endpoint, args=(), method="GET"):
    out = subprocess.run(["gh", "api", "--method", method, endpoint] + list(args),
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("gh api %s 失败: %s" % (endpoint, out.stderr.strip()[:200]))
    return out.stdout


def prune_release(repo, tag, keep_days, retain=()):
    """Release 维度 14 天滚动清理。返回 (deleted, kept)。"""
    import datetime
    rel = json.loads(gh_api("/repos/%s/releases/tags/%s" % (repo, tag)))
    assets = [a["name"] for a in rel.get("assets") or []]
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days - 1)
              ).isoformat()
    to_delete, to_keep = decide_release_prune(assets, cutoff, retain)
    for name in to_delete:
        aid = next(a["id"] for a in rel["assets"] if a["name"] == name)
        gh_api("/repos/%s/releases/assets/%d" % (repo, aid), method="DELETE")
    print("release prune: cutoff<%s deleted=%d kept=%d" % (cutoff, len(to_delete), len(to_keep)),
          flush=True)
    return to_delete, to_keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-dir", default=os.environ.get("SNAPSHOT_DIR", "snapshot"))
    ap.add_argument("--prune-release", action="store_true",
                    help="同时对 Release %s 做 14 天滚动清理" % RELEASE_TAG)
    ap.add_argument("--release", default=RELEASE_TAG)
    ap.add_argument("--keep-release-days", type=int,
                    default=int(os.environ.get("SNAPSHOT_RELEASE_KEEP_DAYS", "14")))
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    day_dirs = list_day_dirs(args.snapshot_dir)
    tracked = list_tracked_day_dirs(args.snapshot_dir)
    to_untrack, to_track = decide(day_dirs, tracked)
    print("snapshot days on disk: %s" % (day_dirs or ["<none>"]), flush=True)
    print("rotate: untrack=%s track=%s" % (to_untrack or ["<none>"], to_track or ["<none>"]),
          flush=True)
    if args.dry_run:
        return 0
    for d in to_untrack:
        # --cached 只解除跟踪保留工作区文件；--sparse 兼容 CI 全量 checkout 之外的极端情况
        subprocess.run(["git", "rm", "-r", "-q", "--cached", "--sparse",
                        os.path.join(args.snapshot_dir, d)], check=True, timeout=300)
    for d in to_track:
        # -f 覆盖 .gitignore 的 snapshot/ 规则（每日最新快照仍在主干树留一日）
        subprocess.run(["git", "add", "-f", os.path.join(args.snapshot_dir, d)],
                       check=True, timeout=300)
    if args.prune_release:
        if not args.repo:
            print("prune-release 需 --repo 或 GITHUB_REPOSITORY", flush=True)
        else:
            prune_release(args.repo, args.release, args.keep_release_days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
