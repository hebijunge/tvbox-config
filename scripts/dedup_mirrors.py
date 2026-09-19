#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""镜像站去重（第三级去重）：用片名集合识别「同一片库换域名 / 换路径」的重复站点。

一级去重按 key，二级按 api+ext 指纹，两者都抓不到真正的重复：
    ① 同库换域名   zuidapi.com 与 zuidazy.co      —— 片库同为 123163 条
    ② 仅查询串不同 bfzyapi.com/api.php/provide/vod 与 .../vod/?ac=list
    ③ 主域与子域   sdzyapi.com 与 xsd.sdzyapi.com
这三类在 api+ext 指纹下字符串不同，因而全部漏网。

本脚本取探针（probe_sites.py）在 L1 阶段抓到的片名集合，用 Jaccard 相似度判定同源，
并辅以片库总量（total）差异做二次确认，把同源站点并成一组，输出
state/mirror_groups.json 供 fetch_merge.py 在合并阶段剔除多余项。

保守原则：证据不足一律不合并（宁可留重复，不可误杀可用源）。

用法
----
    python scripts/dedup_mirrors.py                       # 生成分组并打印报告
    python scripts/dedup_mirrors.py --threshold 0.75
    python scripts/dedup_mirrors.py --out state/mirror_groups.json
"""

import argparse
import json
import os
import re
import sys
import time

LEVEL_RANK = {"L3": 0, "L2": 1, "L1": 2, "L?": 3, "L0": 4, "S1": 5, "S0": 6}


def norm(name: str) -> str:
    """片名规范化：去掉空白/标点/括号，统一小写，只留字母数字与汉字。"""
    return re.sub(r"[\W_]+", "", name, flags=re.UNICODE).lower()


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def same_library(a: dict, b: dict, thr: float, total_tol: float):
    """判定两条记录是否同一片库。返回 (是否同源, 证据)。"""
    j = jaccard(a["names"], b["names"])
    evidence = {"jaccard": round(j, 3), "overlap": len(a["names"] & b["names"])}
    if j < thr:
        return False, evidence
    ta, tb = a.get("total"), b.get("total")
    if ta and tb:
        diff = abs(ta - tb) / max(ta, tb)
        evidence["total_diff"] = round(diff, 3)
        # 片名高度重合但片库总量差太多：可能只是「最新更新」撞车，保守放弃
        if diff > total_tol:
            return False, evidence
    return True, evidence


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="probe/sites_probe.json")
    ap.add_argument("--out", default="state/mirror_groups.json")
    ap.add_argument("--threshold", type=float, default=0.8, help="片名 Jaccard 阈值")
    ap.add_argument("--total-tol", type=float, default=0.15, help="片库总量允许的相对差异")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    src = os.path.join(repo, args.input)
    if not os.path.isfile(src):
        print(f"[dedup] 找不到探针产物 {src}，先跑 scripts/probe_sites.py", file=sys.stderr)
        return 1
    with open(src, encoding="utf-8") as f:
        probe = json.load(f)

    items = []
    for s in probe.get("sites", []):
        l1 = s.get("l1") or {}
        names = l1.get("names") or []
        if not l1.get("ok") or len(names) < 5:
            continue
        items.append({
            "key": s.get("key"), "name": s.get("name"), "api": s.get("api"),
            "level": s.get("level"), "total": l1.get("total"),
            "ms": l1.get("ms") or 99999,
            "names": {norm(n) for n in names if norm(n)},
        })

    print(f"[dedup] 参与判定 {len(items)} 个源（需 L1 通过且片名 >= 5 条）", flush=True)

    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            ok, ev = same_library(items[i], items[j], args.threshold, args.total_tol)
            if ok:
                union(i, j)
                pairs.append((items[i]["key"], items[j]["key"], ev))

    groups: dict = {}
    for idx in range(len(items)):
        groups.setdefault(find(idx), []).append(idx)

    out_groups, drop_keys = [], []
    for root, idxs in groups.items():
        if len(idxs) < 2:
            continue
        members = [items[i] for i in idxs]
        members.sort(key=lambda m: (LEVEL_RANK.get(m.get("level"), 9), m.get("ms") or 99999))
        keep = members[0]
        drops = members[1:]
        ev = next((e for a, b, e in pairs if {a, b} & {m["key"] for m in members}), {})
        out_groups.append({
            "keep": {"key": keep["key"], "name": keep["name"], "api": keep["api"],
                     "level": keep.get("level"), "total": keep.get("total")},
            "drops": [{"key": d["key"], "name": d["name"], "api": d["api"],
                       "level": d.get("level"), "total": d.get("total")} for d in drops],
            "evidence": ev,
        })
        drop_keys.extend(d["key"] for d in drops)

    out_groups.sort(key=lambda g: -(g["evidence"].get("jaccard") or 0))
    doc = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": args.input,
        "threshold": args.threshold,
        "total_tol": args.total_tol,
        "note": "同片库镜像站分组；drop_keys 供合并阶段剔除（证据不足不合并）",
        "summary": {"considered": len(items), "groups": len(out_groups),
                    "redundant": len(drop_keys)},
        "groups": out_groups,
        "drop_keys": drop_keys,
    }
    dst = os.path.join(repo, args.out)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print(f"[dedup] 发现 {len(out_groups)} 组镜像，冗余 {len(drop_keys)} 个源")
    for g in out_groups[:12]:
        ev = g["evidence"]
        print(f"  保留 {g['keep']['name'][:16]:16} ({g['keep']['level']}, {g['keep'].get('total')} 条)"
              f"  ← 冗余 {len(g['drops'])} 个 | Jaccard {ev.get('jaccard')}")
        for d in g["drops"][:3]:
            print(f"        - {d['name'][:20]:20} {d['api'][:60]}")
    print(f"[dedup] 产物 -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
