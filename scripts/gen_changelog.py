#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新日志生成（任务4：P1）。

对比本轮与上轮 tvbox.json 的差异：
    - 站点：新增 / 删除 / 修改（name/api/jar 变化）
    - 直播：新增频道 / 删除频道
    - 质量：可搜源数、平均速度（从 name 中的 [Nms] 标注提取）

上轮数据来源：state/last_tvbox.json；首次运行创建基线不生成 diff。

输出
----
    exports/changelog.json  结构化
    exports/changelog.md    可读
"""
import argparse
import json
import os
import re
import sys
import time
from collections import OrderedDict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def sites_index(doc):
    """把 sites 列表转成 {key: site_dict} 索引。"""
    idx = OrderedDict()
    for s in doc.get("sites", []):
        if isinstance(s, dict) and s.get("key"):
            idx[s["key"]] = s
    return idx


def lives_index(doc):
    """把 lives 列表转成 {name: url} 索引（取 name+url 作为频道标识）。"""
    idx = OrderedDict()
    for l in doc.get("lives", []):
        if isinstance(l, dict):
            key = f"{l.get('name','')}|{l.get('url','')}"
            idx[key] = l
    return idx


def avg_speed_ms(sites):
    """从 name 中提取 [Nms|...] 标注，计算平均延迟。"""
    speeds = []
    for s in sites:
        m = re.search(r"\[(\d+)ms", str(s.get("name", "")))
        if m:
            speeds.append(int(m.group(1)))
    return round(sum(speeds) / len(speeds), 1) if speeds else None


def searchable_count(sites):
    return sum(1 for s in sites if s.get("searchable") == 1)


def diff_sites(prev_idx, curr_idx):
    """对比两个 sites 索引，返回 (added, removed, modified)。"""
    added = []
    removed = []
    modified = []

    prev_keys = set(prev_idx.keys())
    curr_keys = set(curr_idx.keys())

    for k in curr_keys - prev_keys:
        added.append({"key": k, "name": curr_idx[k].get("name", "")})

    for k in prev_keys - curr_keys:
        removed.append({"key": k, "name": prev_idx[k].get("name", "")})

    for k in prev_keys & curr_keys:
        p, c = prev_idx[k], curr_idx[k]
        changes = []
        for field in ("name", "api", "jar"):
            pv = p.get(field, "")
            cv = c.get(field, "")
            if pv != cv:
                changes.append({"field": field, "old": pv, "new": cv})
        if changes:
            modified.append({"key": k, "name": c.get("name", ""), "changes": changes})

    return added, removed, modified


def diff_lives(prev_idx, curr_idx):
    prev_keys = set(prev_idx.keys())
    curr_keys = set(curr_idx.keys())
    added = len(curr_keys - prev_keys)
    removed = len(prev_keys - curr_keys)
    return added, removed


def main():
    ap = argparse.ArgumentParser(description="更新日志生成")
    ap.add_argument("--baseline", action="store_true",
                    help="强制用当前 tvbox.json 创建基线")
    args = ap.parse_args()

    curr = load_json("tvbox.json")
    if curr is None:
        print("[gen_changelog] tvbox.json 不存在或损坏")
        return 1

    prev = load_json("state/last_tvbox.json")

    os.makedirs("exports", exist_ok=True)
    os.makedirs("state", exist_ok=True)

    now_str = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # 首次运行 / 强制基线：保存当前为基线
    if prev is None or args.baseline:
        changelog = {
            "date": now_str,
            "baseline_created": True,
            "message": "首次运行，已创建基线，下次运行生成 diff",
            "curr_stats": {
                "sites": len(curr.get("sites", [])),
                "lives": len(curr.get("lives", [])),
                "parses": len(curr.get("parses", [])),
                "searchable": searchable_count(curr.get("sites", [])),
                "avg_speed_ms": avg_speed_ms(curr.get("sites", [])),
            },
        }
        with open("state/last_tvbox.json", "w", encoding="utf-8") as f:
            json.dump(curr, f, ensure_ascii=False, indent=1)
        with open("exports/changelog.json", "w", encoding="utf-8") as f:
            json.dump(changelog, f, ensure_ascii=False, indent=1)
        with open("exports/changelog.md", "w", encoding="utf-8") as f:
            f.write(f"# 更新日志（基线）\n\n- 时间：{now_str}\n")
            f.write(f"- 站点数：{changelog['curr_stats']['sites']}\n")
            f.write(f"- 直播数：{changelog['curr_stats']['lives']}\n")
            f.write(f"- 可搜源：{changelog['curr_stats']['searchable']}\n")
        print(f"[gen_changelog] 基线已创建: sites={changelog['curr_stats']['sites']}")
        return 0

    # 正常 diff
    prev_sites = sites_index(prev)
    curr_sites = sites_index(curr)
    added, removed, modified = diff_sites(prev_sites, curr_sites)

    prev_lives = lives_index(prev)
    curr_lives = lives_index(curr)
    live_added, live_removed = diff_lives(prev_lives, curr_lives)

    prev_speed = avg_speed_ms(prev.get("sites", []))
    curr_speed = avg_speed_ms(curr.get("sites", []))
    prev_searchable = searchable_count(prev.get("sites", []))
    curr_searchable = searchable_count(curr.get("sites", []))

    changelog = {
        "date": now_str,
        "baseline_created": False,
        "sites": {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
            "added_list": added[:50],
            "removed_list": removed[:50],
            "modified_list": modified[:50],
        },
        "lives": {
            "added": live_added,
            "removed": live_removed,
        },
        "quality": {
            "searchable_prev": prev_searchable,
            "searchable_curr": curr_searchable,
            "searchable_delta": curr_searchable - prev_searchable,
            "avg_speed_ms_prev": prev_speed,
            "avg_speed_ms_curr": curr_speed,
            "avg_speed_delta": (curr_speed - prev_speed) if (prev_speed and curr_speed) else None,
        },
    }

    with open("exports/changelog.json", "w", encoding="utf-8") as f:
        json.dump(changelog, f, ensure_ascii=False, indent=1)

    # 可读 md
    with open("exports/changelog.md", "w", encoding="utf-8") as f:
        f.write(f"# 更新日志\n\n时间：{now_str}\n\n")
        f.write(f"## 站点\n\n")
        f.write(f"- 新增：{len(added)}\n")
        f.write(f"- 删除：{len(removed)}\n")
        f.write(f"- 修改：{len(modified)}\n\n")
        if added[:10]:
            f.write("### 新增源（前10）\n\n")
            for a in added[:10]:
                f.write(f"- `{a['key']}` {a['name']}\n")
            f.write("\n")
        if removed[:10]:
            f.write("### 删除源（前10）\n\n")
            for r in removed[:10]:
                f.write(f"- `{r['key']}` {r['name']}\n")
            f.write("\n")
        f.write(f"## 直播\n\n")
        f.write(f"- 新增频道：{live_added}\n")
        f.write(f"- 删除频道：{live_removed}\n\n")
        q = changelog["quality"]
        f.write(f"## 质量\n\n")
        f.write(f"- 可搜源：{q['searchable_prev']} → {q['searchable_curr']}（{q['searchable_delta']:+d}）\n")
        if q["avg_speed_ms_prev"] is not None:
            f.write(f"- 平均延迟：{q['avg_speed_ms_prev']}ms → {q['avg_speed_ms_curr']}ms（{q['avg_speed_delta']:+.1f}ms）\n")

    # 更新基线
    with open("state/last_tvbox.json", "w", encoding="utf-8") as f:
        json.dump(curr, f, ensure_ascii=False, indent=1)

    print(f"[gen_changelog] sites +{len(added)}/-{len(removed)} ~{len(modified)} "
          f"lives +{live_added}/-{live_removed} "
          f"searchable {prev_searchable}→{curr_searchable}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
