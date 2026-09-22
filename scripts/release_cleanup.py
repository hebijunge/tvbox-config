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
      --keep tvbox.json,vod.json,live.json,short.json,list.json,status.json,checks.json,tvbox-latest.zip
  # 可选 --repo OWNER/REPO（缺省读 GITHUB_REPOSITORY）、--release latest、--dry-run

注意：删除是逐资产的 Release 资产级操作，不动仓库文件、不动 tag 本身。
"""
import argparse
import json
import os
import subprocess
import sys

# 永不清理：受限内容产物按所有者决策保留（2026-09-22），不进白名单、不更新、不推广
RETAIN_FOREVER = {"adult.json"}


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", required=True,
                    help="本轮发布白名单（文件名逗号分隔，与 daily.yml 上传的 FILES 一致）")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--release", default="latest")
    ap.add_argument("--dry-run", action="store_true", help="只打印将删除的资产，不执行")
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
    if not to_delete:
        print("无需清理")
        return 0
    if args.dry_run:
        print("dry-run，未执行删除")
        return 0

    id_by_name = {a.get("name", ""): a.get("id") for a in assets}
    fail = 0
    for n in to_delete:
        try:
            gh_delete(args, id_by_name[n])
            print("  已删除: %s" % n)
        except RuntimeError as e:
            fail += 1
            print("  !! %s" % e, file=sys.stderr)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
