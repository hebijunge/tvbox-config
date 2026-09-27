#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""release_cleanup.py — Release latest 陈旧资产清理（P1-2 产物卫生修复，2026-09-22）

背景
----
Release latest 采用 Guovin 双通道模式每日 --clobber 覆盖白名单资产，
但历史遗留的白名单外资产（早期的 *_proxy.json、按日期命名的旧 zip）既不更新
也不清理，只增不减。本脚本在每日上传后跑一遍：白名单外的一律删除。

规则
----
  keep    当前发布白名单（= 本轮刚上传的文件名，由 --keep 传入）
  retain  永不清理的资产。当前仅一项：adult.json —— 受限内容产物，
          所有者 2026-09-22 明确拍板保留（不得删除产物本身），故即使它
          不在每日发布白名单里，也原样保留、不更新、不推广。
  其余     删除（含 4 个陈旧 _proxy.json、历史日期名 zip 等）。

用法（CI 内，GH_TOKEN 由工作流 env 提供）
------------------------------------------
  python scripts/release_cleanup.py \
      --keep tvbox.json,vod.json,live.json,short.json,status.json,checks.json,tvbox-latest.zip
  # 可选 --repo OWNER/REPO（缺省读 GITHUB_REPOSITORY）、--release latest、--dry-run
  # P1-4 旧 tag 滚动：--retention-days 30（默认）清理 30 天前的 vYYYY-MM-DD-bN tag
  # P2-1 旧 Release 滚动：--keep-releases 10（默认）保留最近 10 个按 tag 的归档 Release

注意：删除是逐资产的 Release 资产级操作，不动仓库文件。
      latest 这个特殊 Release 永不删除（稳定入口）；旧 tag/归档 Release 滚动清理。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# 永不清理：受限内容产物按所有者决策保留（2026-09-22），不进白名单、不更新、不推广
RETAIN_FOREVER = {"adult.json"}

# P1-4 每日版本 tag 形态：v2026-09-27-b1234（也匹配 rollback- 前缀的回滚 tag）
VERSION_TAG_RE = re.compile(r"^(v\d{4}-\d{2}-\d{2}-b\d+|rollback-\d{4}-\d{2}-\d{2}-b\d+)$")


def decide(asset_names, keep, retain=RETAIN_FOREVER):
    """纯决策函数：返回 (to_delete, to_keep)。单测覆盖点，不做任何 IO。"""
    keep, retain = set(keep), set(retain)
    to_delete, to_keep = [], []
    for name in asset_names:
        if name in keep or name in retain:
            to_keep.append(name)
        else:
            to_delete.append(name)
    return sorted(to_delete), sorted(to_keep)


def gh_json(args, endpoint):
    out = subprocess.run(
        ["gh", "api", endpoint, "--paginate"] + args,
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError("gh api %s 失败: %s" % (endpoint, out.stderr.strip()[:200]))
    return json.loads(out.stdout)


def gh_delete(args, asset_id):
    out = subprocess.run(
        ["gh", "api", "--method", "DELETE",
         "repos/%s/releases/assets/%s" % (args.repo, asset_id)],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError("删除资产 %s 失败: %s" % (asset_id, out.stderr.strip()[:200]))


def _now():
    return datetime.now(timezone.utc)


def prune_old_tags(args, retention_days):
    """P1-4：删除超过 retention_days 天的每日版本 tag（vYYYY-MM-DD-bN / rollback-*）。

    latest 不是 tag 形态（是 Release 名），天然不受影响。tag 删除不影响 main 分支。
    """
    if retention_days <= 0:
        return 0
    try:
        tags = gh_json([], "repos/%s/tags?per_page=100" % args.repo)
    except RuntimeError as e:
        print("  = 列 tag 失败（跳过旧 tag 清理）: %s" % e, file=sys.stderr)
        return 0
    cutoff = _now().timestamp() - retention_days * 86400
    removed = 0
    for t in tags or []:
        name = t.get("name", "")
        if not VERSION_TAG_RE.match(name):
            continue  # 只滚每日版本 tag，其他 tag（含手工打的）不动
        # tag 列表不含创建时间，按 name 里的日期解析（vYYYY-MM-DD-bN）
        m = re.match(r"^(?:v|rollback-)(\d{4})-(\d{2})-(\d{2})-b", name)
        if not m:
            continue
        try:
            created = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                               tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if created < cutoff:
            print("  - 清理旧 tag: %s" % name)
            if args.dry_run:
                removed += 1
                continue
            r = subprocess.run(["gh", "api", "--method", "DELETE",
                                "repos/%s/git/refs/tags/%s" % (args.repo, name)],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                removed += 1
            else:
                print("    !! 删除 tag 失败: %s" % r.stderr.strip()[:120], file=sys.stderr)
    if removed:
        print("旧 tag 滚动清理（>%d 天）：%d 个" % (retention_days, removed))
    return removed


def prune_old_releases(args, keep):
    """P2-1：按 tag 归档的 Release 只保留最近 keep 个，更早的连 Release+tag 一起删。

    latest（稳定入口）与 snapshot-archive（快照归档 Release）永不删。
    """
    if keep <= 0:
        return 0
    try:
        rels = gh_json([], "repos/%s/releases?per_page=100" % args.repo)
    except RuntimeError as e:
        print("  = 列 Release 失败（跳过旧 Release 清理）: %s" % e, file=sys.stderr)
        return 0
    # 只处理我们自己打的归档 tag Release（vYYYY-MM-DD-bN / rollback-*）
    cand = [r for r in (rels or [])
            if VERSION_TAG_RE.match(r.get("tag_name", ""))]
    # 按发布时间降序，新的在前
    cand.sort(key=lambda r: r.get("published_at") or "", reverse=True)
    stale = cand[keep:]
    removed = 0
    for r in stale:
        tag = r.get("tag_name", "")
        rid = r.get("id")
        print("  - 清理旧归档 Release: %s" % tag)
        if args.dry_run:
            removed += 1
            continue
        r1 = subprocess.run(["gh", "api", "--method", "DELETE",
                             "repos/%s/releases/%s" % (args.repo, rid)],
                            capture_output=True, text=True, timeout=60)
        r2 = subprocess.run(["gh", "api", "--method", "DELETE",
                             "repos/%s/git/refs/tags/%s" % (args.repo, tag)],
                            capture_output=True, text=True, timeout=60)
        if r1.returncode == 0 or r2.returncode == 0:
            removed += 1
        else:
            print("    !! 清理 Release/tag 失败: %s" % r1.stderr.strip()[:120], file=sys.stderr)
    if removed:
        print("旧归档 Release 滚动清理（保留最近 %d 个）：%d 个" % (keep, removed))
    return removed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", required=True,
                    help="本轮发布白名单（文件名逗号分隔，与 daily.yml 上传的 FILES 一致）")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--release", default="latest")
    ap.add_argument("--dry-run", action="store_true", help="只打印将删除的资产，不执行")
    ap.add_argument("--retention-days", type=int, default=30,
                    help="P1-4 旧版本 tag 保留天数（默认 30；<=0 关闭）")
    ap.add_argument("--keep-releases", type=int, default=10,
                    help="P2-1 保留最近 N 个按 tag 归档的 Release（默认 10；<=0 关闭）")
    args = ap.parse_args()

    if not args.repo:
        print("!! 缺 --repo 且无 GITHUB_REPOSITORY", file=sys.stderr)
        return 2
    keep = [k.strip() for k in args.keep.split(",") if k.strip()]

    rel = gh_json([], "repos/%s/releases/tags/%s" % (args.repo, args.release))
    assets = rel.get("assets") or []
    names = [a.get("name", "") for a in assets]
    to_delete, to_keep = decide(names, keep)

    print("Release %s 现有资产 %d 个：保留 %d、清理 %d"
          % (args.release, len(names), len(to_keep), len(to_delete)))
    for n in to_delete:
        print("  - 清理: %s" % n)
    for n in to_keep:
        if n in RETAIN_FOREVER and n not in keep:
            print("  = 保留(所有者决策): %s" % n)

    id_by_name = {a.get("name", ""): a.get("id") for a in assets}
    fail = 0
    if to_delete:
        if args.dry_run:
            print("dry-run，latest 资产未删除")
        else:
            for n in to_delete:
                try:
                    gh_delete(args, id_by_name[n])
                    print("  已删除: %s" % n)
                except RuntimeError as e:
                    fail += 1
                    print("  !! %s" % e, file=sys.stderr)
    else:
        print("latest 资产无需清理")

    # P1-4 / P2-1：旧 tag 与旧归档 Release 滚动清理（与 latest 资产清理解耦，始终执行）
    try:
        prune_old_tags(args, args.retention_days)
    except Exception as e:  # noqa: BLE001 —— 清理是兜底，绝不能让它拖挂主发布
        print("  = 旧 tag 清理异常（忽略）: %s" % e, file=sys.stderr)
    try:
        prune_old_releases(args, args.keep_releases)
    except Exception as e:  # noqa: BLE001
        print("  = 旧 Release 清理异常（忽略）: %s" % e, file=sys.stderr)

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
