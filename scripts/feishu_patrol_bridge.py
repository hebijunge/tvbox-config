#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feishu_patrol_bridge.py — 飞书每日巡检线 ↔ validated.json 单一事实源桥接（P1-A）。

职责边界（双线收敛后）：
  GitHub 发现验证线：daily-fetch/validate 维护 sources 的「今日验证结果」（写）；
  飞书汇聚分发线（本桥接）：读 validated.json 取全量源状态与衰减结论 →
    用当日复测结果（retest JSON 列表）按规范键合并回写 → 应用跨日衰减 →
    可选推送 GitHub（--push，凭据环境变量 GITHUB_PAT）。

飞书线此后不再自建 prev_list 状态链：prev 状态一律取自本文件；
  dedup/build_list 等下游消费 vs.active_sources(doc)（自动剔除 watch/out 衰减源）。

用法：
  python scripts/feishu_patrol_bridge.py --inputs ../retest_20260925.json [更多...] \
      [--repo /path/to/tvbox-config] [--push] [--dry-run]

输入行格式（飞书线 retest/各 *_tested.json 通用）：{name, url, level[, ...]}；
  level ∈ fully_available / partially_available / unavailable（自动归一为 fully/partially/unavailable）。
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validated_state as vs  # noqa: E402


def load_rows(paths):
    rows = []
    for p in paths:
        data = json.load(open(p, encoding="utf-8"))
        if isinstance(data, dict):  # 兼容 {interfaces:[...]} 形态
            data = data.get("interfaces") or []
        for r in data:
            if isinstance(r, dict) and r.get("url"):
                rows.append({"name": r.get("name"), "url": r["url"],
                             "level": r.get("level"), "date": r.get("date")})
    return rows


def merge(doc, rows):
    """按规范键合并飞书线当日复测结果。返回计数摘要。"""
    stat = {"rows": len(rows), "matched": 0, "new": 0, "level_pass": 0,
            "level_fail": 0, "upgraded": 0}
    # ckey 索引（含飞书线历史条目）
    idx = {}
    for ent in doc["sources"].values():
        if isinstance(ent, dict) and ent.get("ckey"):
            idx.setdefault(ent["ckey"], ent)
    for r in rows:
        ckey = vs.canonical_key(r["url"])
        ent = idx.get(ckey)
        if ent is None:
            # 兼容：按 name 兜底（无 url 的旧条目）
            nm = r.get("name") or ""
            ent = doc["sources"].get(nm)
            if isinstance(ent, dict) and not ent.get("ckey"):
                pass
            else:
                ent = {"name": nm or ckey}
                doc["sources"][ent["name"]] = ent
                idx[ckey] = ent
                stat["new"] += 1
        else:
            stat["matched"] += 1
        ent["url"] = r["url"]
        ent["ckey"] = ckey
        ent["last_line"] = "feishu"
        lv = vs.LEVEL_ALIASES.get(r.get("level"), r.get("level"))
        d = r.get("date") or vs.today_bj()
        hist = ent.setdefault("history", {})
        prev = hist.get(d)
        if not vs._pass_level(prev):
            hist[d] = lv
            if vs._pass_level(lv):
                stat["level_pass"] += 1
            else:
                stat["level_fail"] += 1
        elif prev != "fully" and lv == "fully":
            hist[d] = lv
            stat["upgraded"] += 1
        vs.trim_history(ent)
        if vs._pass_level(lv):
            ent["level"] = lv
            ent["fail_count"] = 0
            ent["disabled"] = False
            ent["last_ok_at"] = ent.get("last_ok_at") or "%s 05:00:00" % d
    return stat


def git_push(repo, token):
    url = "https://%s@github.com/hebijunge/tvbox-config.git" % token
    cmds = [["git", "-C", repo, "add", "state/validated.json"],
            ["git", "-C", repo, "commit", "-m",
             "chore(patrol): 飞书巡检线回写 validated.json（单一事实源，P1-A 桥接）"],
            ["git", "-C", repo, "push", url, "main"]]
    for c in cmds:
        r = subprocess.run(c, capture_output=True, text=True, timeout=120)
        print("$", " ".join(c[:3]), "→", (r.stdout or r.stderr).strip()[-200:])
        if r.returncode != 0 and "nothing to commit" not in (r.stdout or ""):
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True, help="飞书线当日复测 JSON（可多个）")
    ap.add_argument("--repo", default=".", help="tvbox-config 仓库根目录")
    ap.add_argument("--push", action="store_true", help="合并后提交并推送 GitHub")
    ap.add_argument("--dry-run", action="store_true", help="只读不写")
    a = ap.parse_args()
    inputs_abs = [os.path.abspath(p) for p in a.inputs]  # 先解析输入路径，再切 repo 目录
    os.chdir(a.repo)
    doc = vs.load_validated(".")
    rows = load_rows(inputs_abs)
    stat = merge(doc, rows)
    before = len(doc["sources"])
    decay = vs.apply_decay(doc)
    stat["sources_total"] = before
    stat["decay"] = decay
    active = vs.active_sources(doc)
    stat["active_sources"] = len(active)
    print(json.dumps(stat, ensure_ascii=False, indent=1))
    if not a.dry_run:
        vs.save_validated(doc, ".", note="飞书巡检线桥接回写（feishu_patrol_bridge）")
        print("validated.json 已回写：", vs.VALIDATED_FILE)
        if a.push:
            token = os.environ.get("GITHUB_PAT", "")
            if not token:
                print("缺 GITHUB_PAT，跳过推送")
                sys.exit(3)
            ok = git_push(".", token)
            sys.exit(0 if ok else 4)
    else:
        print("[dry-run] 未落盘")


if __name__ == "__main__":
    main()
