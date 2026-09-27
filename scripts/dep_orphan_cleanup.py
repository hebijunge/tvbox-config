#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖孤儿文件清理（deps/ 中未被 manifest 引用的文件）。

背景
----
``deps/`` 随每日上游聚合持续增长，已落库的文件一旦上游改版/下线、站点被剔，就会变成
磁盘上残留、但 ``deps/manifest.json`` 里再无 ``local`` 指向它的「孤儿」。直接按磁盘全量
删风险高：manifest 是产物里引用路径的唯一事实源，manifest 指向的文件绝不能动；反过来，
manifest 不再指向的文件才是清理候选。

判定规则
--------
1. 被引用集合 = ``deps/manifest.json`` 每条记录的 ``local`` 字段（仓库相对路径）。
2. 磁盘集合 = 递归遍历 ``deps/`` 得到的全部文件（仓库相对路径，正斜杠）。
3. 孤儿 = 磁盘集合 - 被引用集合。
4. 对每个孤儿，去 ``raw-vod/manifest.json`` 账本反查（deps 与 raw-vod 按
   ``<origin>/<rel>`` 镜像）：
     - 账本标记 ``status == "deleted_upstream"`` 且 ``deleted_at`` 距今超过
       ``--grace-days``（默认 90 天）→ 上游早已不恢复，本地残留可安全删除；
     - 否则（账本无记录 / 仍 ok / 删除未满宽限期）→ **保留**，仅列入报告待人工确认。

安全约束
--------
* 默认 **dry-run**：只生成报告 ``state/dep_orphan_report.json``，不删任何文件；
  必须显式加 ``--execute`` 才真正删除。
* 只删孤儿集合里「账本确认 deleted_upstream 超宽限期」的那部分，其余一律保留。
* 纯标准库；``raw-vod/`` 本地不存在时优雅降级（全部按「保留」处理）。

用法
----
    python scripts/dep_orphan_cleanup.py                 # dry-run，只出报告
    python scripts/dep_orphan_cleanup.py --execute       # 真正删除超期孤儿
    python scripts/dep_orphan_cleanup.py --grace-days 60
"""
import argparse
import datetime as _dt
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

# 允许从任意 cwd 运行：把脚本所在目录（scripts/）加入 import 路径，复用 pathutil。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pathutil  # noqa: E402  （跨平台路径安全工具）

DEFAULT_GRACE_DAYS = 90
REPORT_PATH = "state/dep_orphan_report.json"


def _load_json(path: str) -> dict:
    """宽松读取 JSON；缺失/损坏返回空 dict。

    注意：deps/manifest.json 因历史 URL 大小写存在重复 key，``json.load`` 会按出现顺序
    后者覆盖前者自动去重——这正是我们想要的语义（与 fetch_merge 落库时的覆盖口径一致）。
    PowerShell ``ConvertFrom-Json`` 会对重复 key 报错，故此处统一用 Python。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _repo_rel(path: str, repo: str) -> str:
    return os.path.relpath(path, repo).replace("\\", "/")


def collect_referenced_locals(manifest: dict) -> set:
    """从 deps/manifest.json 提取全部被引用的 local 路径集合。"""
    refs = set()
    for ent in manifest.values():
        if not isinstance(ent, dict):
            continue
        loc = ent.get("local")
        if isinstance(loc, str) and loc:
            refs.add(loc.replace("\\", "/"))
    return refs


def collect_disk_files(dep_dir: str, repo: str) -> List[Tuple[str, int]]:
    """递归遍历 deps/，返回 [(仓库相对路径, 字节数), ...]（正斜杠）。"""
    out: List[Tuple[str, int]] = []
    if not os.path.isdir(dep_dir):
        return out
    for root, _, names in os.walk(dep_dir):
        for n in names:
            p = os.path.join(root, n)
            try:
                out.append((_repo_rel(p, repo), os.path.getsize(p)))
            except OSError:
                continue
    return out


def build_ledger_index(store: str) -> Dict[str, dict]:
    """把 raw-vod 账本按 ``path``（相对 store 的镜像路径）索引，便于孤儿反查。

    raw-vod/manifest.json 的 value 形如 ``{"path": "<origin>/<rel>", "status": ...,
    "deleted_at": "YYYY-MM-DD", ...}``。deps 侧孤儿路径为 ``deps/<origin>/<rel>``，
    去掉 ``deps/`` 前缀即得账本 ``path``。
    """
    mpath = os.path.join(store, "manifest.json")
    ledger = _load_json(mpath)
    idx: Dict[str, dict] = {}
    for key, ent in ledger.items():
        if not isinstance(ent, dict):
            continue
        rel = ent.get("path")
        if isinstance(rel, str) and rel:
            idx[rel.replace("\\", "/")] = {
                "key": key,
                "status": ent.get("status", "ok"),
                "deleted_at": ent.get("deleted_at"),
                "deleted_reason": ent.get("deleted_reason", ""),
            }
    return idx


def classify_orphans(disk_files: List[Tuple[str, int]],
                     referenced: set,
                     ledger: Dict[str, dict],
                     grace_days: int,
                     today: _dt.date) -> Tuple[List[dict], List[dict]]:
    """把磁盘文件分为 (可删除候选, 应保留) 两组。

    可删除候选：孤儿 且 账本标记 deleted_upstream 且 deleted_at 距今 > grace_days。
    其余孤儿一律保留（账本无记录 / 仍 ok / 删除未满宽限期）。
    """
    deletable: List[dict] = []
    keep: List[dict] = []
    for rel, size in disk_files:
        if rel in referenced:
            continue  # 仍被 manifest 引用，绝不动
        # deps/<origin>/<rel> -> 账本 path <origin>/<rel>
        ledger_rel = rel.split("/", 1)[1] if rel.startswith("deps/") else rel
        info = ledger.get(ledger_rel)
        if not info:
            keep.append({"path": rel, "bytes": size, "reason": "ledger_missing"})
            continue
        if info["status"] != "deleted_upstream":
            keep.append({"path": rel, "bytes": size,
                         "reason": f"ledger_status={info['status']}"})
            continue
        deleted_at = info.get("deleted_at")
        age_days = None
        overdue = False
        if deleted_at:
            try:
                d = _dt.date.fromisoformat(str(deleted_at)[:10])
                age_days = (today - d).days
                overdue = age_days > grace_days
            except ValueError:
                overdue = False
        if overdue:
            deletable.append({
                "path": rel, "bytes": size,
                "ledger_key": info["key"],
                "deleted_at": deleted_at, "age_days": age_days,
                "deleted_reason": info.get("deleted_reason", ""),
            })
        else:
            keep.append({"path": rel, "bytes": size,
                         "reason": f"deleted_upstream_but_age={age_days}d<=grace",
                         "deleted_at": deleted_at})
    deletable.sort(key=lambda x: -x["bytes"])
    keep.sort(key=lambda x: -x["bytes"])
    return deletable, keep


def main() -> int:
    ap = argparse.ArgumentParser(description="deps/ 孤儿文件清理（默认 dry-run）")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--deps", default="deps")
    ap.add_argument("--raw-vod", default="raw-vod")
    ap.add_argument("--out", default=REPORT_PATH)
    ap.add_argument("--grace-days", type=int, default=DEFAULT_GRACE_DAYS,
                    help="deleted_upstream 标记超过该天数才可删（默认 90）")
    ap.add_argument("--execute", action="store_true",
                    help="真删；缺省只出报告（dry-run）")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    dep_dir = os.path.join(repo, args.deps)
    today = _dt.date.today()

    manifest = _load_json(os.path.join(dep_dir, "manifest.json"))
    referenced = collect_referenced_locals(manifest)
    disk_files = collect_disk_files(dep_dir, repo)
    disk_set = {rel for rel, _ in disk_files}

    raw_vod_exists = os.path.isdir(os.path.join(repo, args.raw_vod))
    ledger = build_ledger_index(os.path.join(repo, args.raw_vod)) if raw_vod_exists else {}

    deletable, keep = classify_orphans(disk_files, referenced, ledger,
                                        args.grace_days, today)

    freed = sum(x["bytes"] for x in deletable)

    # 执行删除（仅 --execute 时）
    deleted_paths: List[str] = []
    if args.execute:
        for x in deletable:
            fs = os.path.join(repo, x["path"])
            try:
                os.remove(fs)
                deleted_paths.append(x["path"])
            except OSError as e:
                x["delete_error"] = f"{type(e).__name__}: {e}"
        # 顺手清理删空的空子目录（自底向上，不删 deps/ 本体）
        for root, dirs, _ in os.walk(dep_dir, topdown=False):
            for d in dirs:
                dp = os.path.join(root, d)
                try:
                    if not os.listdir(dp):
                        os.rmdir(dp)
                except OSError:
                    pass

    doc = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "dry_run": not args.execute,
        "grace_days": args.grace_days,
        "raw_vod_present": raw_vod_exists,
        "manifest_entries": len(manifest),
        "referenced_locals": len(referenced),
        "disk_files": len(disk_files),
        "orphan_total": len(deletable) + len(keep),
        "deletable_count": len(deletable),
        "deletable_bytes": freed,
        "kept_count": len(keep),
        "kept_bytes": sum(x["bytes"] for x in keep),
        "deleted_actually": len(deleted_paths),
        "deletable": deletable,
        "kept": keep,
        "note": "dry-run 默认只报告不删；--execute 才真删。仍被 manifest 引用的文件永不触碰。",
    }
    out_path = os.path.join(repo, args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print(f"[orphan] 磁盘 {len(disk_files)} 文件 / manifest 引用 {len(referenced)} 条")
    print(f"[orphan] 孤儿 {len(deletable)+len(keep)}：可删 {len(deletable)}"
          f"（{freed/1024/1024:.1f} MB）/ 保留 {len(keep)}")
    if args.execute:
        print(f"[orphan] 已实际删除 {len(deleted_paths)} 个文件")
    else:
        print("[orphan] dry-run：未删除任何文件（加 --execute 真删）")
    print(f"[orphan] 报告 -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
