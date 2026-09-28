#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline_step_stats.py — 全链路「分步成果文件」生成器。

run_all.py 每个阶段跑完后立即调用本模块：
  1. extract_step_stats(stage_id) 从该步产物文件（status.json / probe/* /
     state/* / radar/*）提取该步关键统计（拉取仓库数 / 接口数 / 多仓接口数 /
     汇总 / 去重 / 活 / 死 / 黑名单 / deps 重下 等）
  2. write_step_file(stage_id, status, elapsed) 落盘
     state/pipeline_steps/step_<id>_<名>.json（每步一个文件，跑完即有）
  3. write_pipeline_report() 汇总所有步 + 全链路总账
     state/pipeline_report.json（机器读） + state/pipeline_report.md（人读版）

只读既有产物、不改变任何流水线行为；某步产物缺失时记 skipped/missing，不报错。
"""
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
STEPS_DIR = os.path.join(REPO, "state", "pipeline_steps")


def _load_json(path):
    p = os.path.join(REPO, path)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _db_health_dist():
    p = os.path.join(REPO, "state", "tvbox.db")
    if not os.path.isfile(p):
        return None
    try:
        conn = sqlite3.connect(p)
        total = conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0]
        dist = dict(conn.execute(
            "SELECT health, COUNT(*) FROM interfaces GROUP BY health").fetchall())
        conn.close()
        return {"total": total, "by_health": dist,
                "alive_healthy": dist.get("healthy", 0),
                "alive_degraded": dist.get("degraded", 0),
                "unknown": dist.get("unknown", 0),
                "dead": dist.get("dead", 0)}
    except sqlite3.Error:
        return None


def _lines(p):
    p = os.path.join(REPO, p)
    if not os.path.isfile(p):
        return 0
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# ---------------- 各步统计提取器（stage_id -> dict） ----------------

def _s1_mirror():
    # mirror_probe 只把择优结果写进 GITHUB_ENV（CI）或打印 GH_MIRRORS=...（本地），
    # 无落盘产物；本地以 fetch_merge 内置默认镜像链为基准报告。
    default_chain = ["https://ghproxy.net/", "https://gh-proxy.com/",
                     "https://ghfast.top/", "https://gh.acmsz.top/"]
    env_mirrors = os.environ.get("GH_MIRRORS")
    return {"note": "镜像实测延迟/吞吐择优，首位=运行时前缀（本地无落盘，按默认链/环境变量报告）",
            "active_mirrors": (env_mirrors.split(",") if env_mirrors else default_chain)}


def _probe_summary(path):
    d = _load_json(path)
    if not d:
        return {"note": f"{path} 未生成"}
    out = {"source_file": path}
    if "summary" in d:
        out["summary"] = d["summary"]
    lv = (d.get("summary") or {}).get("levels")
    if lv:
        out["level_dist"] = lv
    return out


def _s2a_sites_probe():
    st = _probe_summary("probe/sites_probe.json")
    st["levels_L1_L3"] = "L0=不可达 L1=连通 L2=有内容 L3=可解析"
    return st


def _s2b_spider_probe():
    st = _probe_summary("probe/spider_probe.json")
    st["note"] = "type3 源连通性（drpy 规则/ext 提取真实站点）"
    return st


def _s2c_js_probe():
    return _probe_summary("probe/js_probe.json")


def _s2d_dedup_mirrors():
    g = _load_json("state/mirror_groups.json") or {}
    groups = g.get("groups") or g.get("mirrors") or []
    out = {"source_file": "state/mirror_groups.json",
           "mirror_groups": len(groups) if isinstance(groups, list) else g.get("total_groups")}
    if isinstance(g, dict) and "summary" in g:
        out["summary"] = g["summary"]
    return out


def _s3_drpy():
    st = _probe_summary("probe/drpy_probe.json")
    lv = st.get("level_dist") or {}
    st["five_stage_pass"] = lv.get("D5", 0)
    st["note"] = "D1=首页..D5=播放五关全通（Node 沙箱）"
    return st


def _s4_discover():
    d = _load_json("radar/discovered.json") or {}
    cands = d.get("candidates") or d.get("repos") or []
    out = {"source_file": "radar/discovered.json",
           "candidates": len(cands) if isinstance(cands, list) else d.get("total")}
    if isinstance(d, dict):
        for k in ("routes", "route_stats", "summary"):
            if k in d:
                out[k] = d[k]
    return out


def _s5_evaluate():
    out = {}
    eu = _load_json("state/extra_upstreams.json") or {}
    out["extra_upstreams"] = len(eu.get("upstreams") or [])
    cu = _load_json("candidate_upstreams.json") or {}
    out["candidate_pool"] = len(cu.get("candidates") or [])
    cands = _load_json("radar/candidate_eval.json") or {}
    if cands:
        out["eval_summary"] = cands.get("summary") or {k: cands[k] for k in cands if not isinstance(cands[k], (list, dict))}
    return out


def _s6_fetch_merge():
    s = _load_json("status.json") or {}
    summ = s.get("summary") or {}
    stores = s.get("stores") or {}
    prod = s.get("products") or {}
    out = {"source_file": "status.json"}
    # 上游仓库
    out["upstreams_total"] = ((s.get("upstreams_health") or {}).get("total"))
    out["upstreams_summary"] = (s.get("upstreams_health") or {})
    out["extra_upstreams_merged"] = _lines("state/extra_upstreams.json") and len((_load_json("state/extra_upstreams.json") or {}).get("upstreams") or [])
    # 接口数（多仓拆分）
    out["multi_repo_counts"] = stores.get("counts")
    out["csp_searchable_filter"] = stores.get("csp_searchable_filter")
    out["multi_repo_entry"] = stores.get("entry_mirror")
    # 汇总 / 去重
    out["interfaces_total"] = summ.get("interfaces_total")
    out["interfaces_by_verdict"] = {"usable": summ.get("interfaces_usable"),
                                     "full": summ.get("interfaces_full"),
                                     "partial": summ.get("interfaces_partial"),
                                     "dead": summ.get("interfaces_dead")}
    out["sites_total"] = summ.get("sites_total")
    out["sites_kept"] = summ.get("sites_kept")
    out["dedup_secondary_removed"] = summ.get("sites_secondary_dedup")
    out["mirrors_skipped"] = summ.get("mirrors_skipped")
    out["sites_removed"] = summ.get("sites_removed")
    out["adult_gate"] = summ.get("adult_gate_sweep")
    # 产物
    out["product_fingerprints"] = {k: v.get("bytes") for k, v in (prod.get("items") or {}).items()}
    # deps 闸门（fetch_merge 内置 deps_gate）
    out["deps_gate"] = s.get("deps_gate")
    return out


def _s6b_dep_repair():
    r = _load_json("state/dep_repair_report.json") or {}
    return {"source_file": "state/dep_repair_report.json",
            "total_refs": r.get("total_refs"),
            "was_missing": r.get("was_missing"),
            "repaired": r.get("repaired"),
            "repair_failed": len(r.get("repair_failed") or []),
            "generated_at": r.get("generated_at"),
            "note": "缺失依赖按 manifest 可回溯 URL 走镜像链重下（md5/sha 校验）"}


def _s7a_store():
    out = {"source_file": "state/tvbox.db"}
    out["health_dist"] = _db_health_dist()
    lv = _load_json("state/live_check_meta.json") or _load_json("state/live_checks.json") or {}
    if lv:
        out["live_meta"] = {k: v for k, v in lv.items() if not isinstance(v, (list, dict))} or \
                           {k: len(v) for k, v in lv.items() if isinstance(v, list)}
    return out


def _s7b_export():
    out = {"source_file": "exports/"}
    for name in ("all", "healthy", "usable", "vod", "spider", "localjs", "pan", "short", "live"):
        p = f"exports/{name}.json"
        d = _load_json(p)
        if d is None:
            out[name] = 0
        else:
            if "sites" in d and isinstance(d["sites"], list):
                out[name] = len(d["sites"])
            elif "lives" in d and isinstance(d["lives"], list):
                out[name] = len(d["lives"])
            else:
                out[name] = len(d)
    return out


def _s7c_live_prune():
    r = _load_json("state/live_dead_prune_report.json") or {}
    keep = ["generated_at", "action", "db_total", "db_dead", "gh_resurrected",
            "prune_keys", "product_hit", "pruned_in_products", "ratio"]
    out = {k: r.get(k) for k in keep if r.get(k) is not None}
    out["source_file"] = "state/live_dead_prune_report.json"
    out["note"] = "P1-4：只剔 404 确定性死源（连接失败=unknown 不剔），gh 源剥前缀走镜像复活"
    return out


def _s7d_health_report():
    r = _load_json("exports/health_report.json") or {}
    keep = ["generated_at", "total", "new", "gone", "recovered", "summary"]
    out = {k: r.get(k) for k in keep if r.get(k) is not None}
    if "changes" in r:
        out["changes_count"] = len(r["changes"])
    out["source_file"] = "exports/health_report.json"
    return out


def _s7e_dep_audit():
    r = _load_json("state/dep_audit.json") or {}
    keep = ["generated_at", "deps_files", "deps_bytes", "duplicate_groups",
            "duplicate_savable_bytes", "unreferenced_count", "unreferenced_bytes",
            "jar_suffix_mismatch_count"]
    return {k: r.get(k) for k in keep if r.get(k) is not None}


def _s8_probe_sources():
    r = _load_json("radar/source_probe.json") or {}
    keep = ["generated_at", "total", "ok", "bad"]
    out = {k: r.get(k) for k in keep if r.get(k) is not None}
    out["source_file"] = "radar/source_probe.json"
    return out


def _s9_pack_local():
    r = _load_json("packs/pack_report.json") or {}
    out = {"source_file": "packs/pack_report.json"}
    for k in ("generated_at", "sizes", "note", "manifest_files"):
        if r.get(k) is not None:
            out[k] = r[k] if not isinstance(r[k], (list, dict)) else len(r[k])
    zips = []
    for root, _dirs, files in os.walk(os.path.join(REPO, "packs")):
        zips += [os.path.relpath(os.path.join(root, f), REPO) for f in files if f.endswith(".zip")]
    out["zips"] = zips[:5]
    return out


def _blacklist_stats():
    auto = _load_json("state/blacklist_auto.txt")
    a_lines = _lines("state/blacklist_auto.txt")
    m_lines = _lines("state/blacklist_manual.txt")
    return {"auto_lines": a_lines, "manual_lines": m_lines,
            "note": "state/blacklist_auto.txt=连续失败自动停用（下轮不再拉取）/ manual=人工"}


STAGE_EXTRACTORS = {
    "1": _s1_mirror,
    "2a": _s2a_sites_probe,
    "2b": _s2b_spider_probe,
    "2c": _s2c_js_probe,
    "2d": _s2d_dedup_mirrors,
    "3": _s3_drpy,
    "4": _s4_discover,
    "5": _s5_evaluate,
    "6": _s6_fetch_merge,
    "6b": _s6b_dep_repair,
    "7a": _s7a_store,
    "7b": _s7b_export,
    "7c": _s7c_live_prune,
    "7d": _s7d_health_report,
    "7e": _s7e_dep_audit,
    "8": _s8_probe_sources,
    "9": _s9_pack_local,
}

STAGE_TITLES = {
    "1": "镜像测速择优", "2a": "探针: HTTP L1-L3", "2b": "探针: type3 连通性",
    "2c": "探针: JS 分类页", "2d": "同库镜像去重", "3": "drpy 沙箱五关",
    "4": "全网发现(六路)", "5": "候选评估+canary收编", "6": "拉取合并(必须成功)",
    "6b": "依赖完整性闸门", "7a": "入库", "7b": "导出清单", "7c": "直播死源剔除",
    "7d": "健康日报", "7e": "依赖审计", "8": "采集入口可达性探测", "9": "本地接口包",
}


def extract_stage(stage_id: str) -> dict:
    fn = STAGE_EXTRACTORS.get(stage_id)
    if not fn:
        return {"unknown_stage": stage_id}
    try:
        stats = fn() or {}
    except Exception as e:  # noqa: BLE001
        stats = {"extract_error": str(e)[:200]}
    return stats


def write_step_file(stage_id: str, status: str, elapsed_s: float,
                    cmd: str = "", extra: dict | None = None) -> str:
    """单步跑完立即落盘 state/pipeline_steps/step_<id>.json。"""
    os.makedirs(STEPS_DIR, exist_ok=True)
    m = re.match(r"(\d+[a-z]?)", stage_id or "")
    sid = m.group(1) if m else "x"
    rec = {
        "stage": sid,
        "title": STAGE_TITLES.get(sid, stage_id),
        "cmd": cmd,
        "status": status,          # OK / CONT / FAIL / SKIP
        "elapsed_sec": round(elapsed_s, 1),
        "stats": extract_stage(sid),
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        rec["extra"] = extra
    p = os.path.join(STEPS_DIR, f"step_{sid}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return p


def write_pipeline_report() -> tuple:
    """汇总所有已落盘的 step 文件 + 全局总账 → json + md。"""
    steps = []
    if os.path.isdir(STEPS_DIR):
        for fn in sorted(os.listdir(STEPS_DIR)):
            if fn.startswith("step_") and fn.endswith(".json"):
                d = _load_json(os.path.relpath(os.path.join(STEPS_DIR, fn), REPO))
                if d:
                    steps.append(d)
    db_dist = _db_health_dist() or {}
    bl = _blacklist_stats()
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "steps": steps,
        "totals": {
            "interfaces_total": next((s["stats"].get("interfaces_total")
                                      for s in reversed(steps) if s["stage"] == "6"), None),
            "sites_total": next((s["stats"].get("sites_total")
                                 for s in reversed(steps) if s["stage"] == "6"), None),
            "sites_kept": next((s["stats"].get("sites_kept")
                                for s in reversed(steps) if s["stage"] == "6"), None),
            "multi_repo_counts": next((s["stats"].get("multi_repo_counts")
                                      for s in reversed(steps) if s["stage"] == "6"), None),
            "health_by": db_dist.get("by_health"),
            "healthy": db_dist.get("alive_healthy"),
            "degraded": db_dist.get("alive_degraded"),
            "unknown": db_dist.get("unknown"),
            "dead": db_dist.get("dead"),
            "live_pruned_in_products": next(
                (s["stats"].get("pruned_in_products")
                 for s in reversed(steps) if s["stage"] == "7c"), None),
            "deps_repaired": next((s["stats"].get("repaired")
                                   for s in reversed(steps) if s["stage"] == "6b"), None),
            "deps_was_missing": next((s["stats"].get("was_missing")
                                     for s in reversed(steps) if s["stage"] == "6b"), None),
            "blacklist_auto_lines": bl["auto_lines"],
            "blacklist_manual_lines": bl["manual_lines"],
            "steps_ok": sum(1 for s in steps if s.get("status") == "OK"),
            "steps_failed": sum(1 for s in steps if s.get("status") in ("FAIL", "CONT")),
        },
        "blacklist_note": bl["note"],
    }
    jpath = os.path.join(REPO, "state", "pipeline_report.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    # ---- 人读版 md ----
    t = report["totals"]
    lines = [
        "# 全链路流水线运行报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 阶段：{t.get('steps_ok')} 成功 / {t.get('steps_failed')} 异常（共 {len(steps)} 步已落盘）",
        "",
        "## 每步成果",
        "",
        "| 阶段 | 状态 | 耗时 | 关键统计 |",
        "| --- | --- | ---: | --- |",
    ]

    def _brief(sid, st):
        st = st or {}
        if sid == "6":
            return (f"上游 {st.get('upstreams_total')} 个｜接口汇总 {st.get('interfaces_total')}"
                    f"（可用 {st.get('interfaces_by_verdict', {}).get('usable')} / 死 "
                    f"{st.get('interfaces_by_verdict', {}).get('dead')}）｜站点 {st.get('sites_total')}"
                    f" → 留 {st.get('sites_kept')}（二级去重剔 {st.get('dedup_secondary_removed')}）｜"
                    f"多仓 {st.get('multi_repo_counts')}")
        if sid == "2a":
            sv = (st.get("summary") or {})
            return f"L1-L3 实测 {sv.get('total')} 站（{json.dumps(sv.get('levels'), ensure_ascii=False)}）" if sv else str(st)
        if sid == "2b":
            sv = st.get("summary") or {}
            return f"连通 {sv.get('reachable')}/{sv.get('probed')}（无信号 {sv.get('no_signal')}）"
        if sid == "2c":
            sv = st.get("summary") or {}
            return f"JS 源 {sv.get('total')}（{json.dumps(st.get('level_dist'), ensure_ascii=False)}）"
        if sid == "3":
            lv = st.get("level_dist") or {}
            return f"五关全通(D5) {lv.get('D5', 0)} / 共 {lv.get('D5', 0) + lv.get('D4', 0) + lv.get('D3', 0) + lv.get('D2', 0) + lv.get('D1', 0) + lv.get('D0', 0)}"
        if sid == "4":
            return f"候选 {st.get('candidates')}"
        if sid == "5":
            return f"canary {st.get('extra_upstreams')} 条 / 人工池 {st.get('candidate_pool')}"
        if sid == "6b":
            return f"缺失 {st.get('was_missing')} → 重下成功 {st.get('repaired')}（失败 {st.get('repair_failed')}）"
        if sid == "7a":
            h = st.get("health_dist") or {}
            return f"DB {h.get('total')} 接口：活 {h.get('alive_healthy')}+{h.get('alive_degraded')} / unknown {h.get('unknown')} / 死 {h.get('dead')}"
        if sid == "7b":
            return f"exports：healthy {st.get('healthy')} / usable {st.get('usable')} / 全量 {st.get('all')} / 直播 {st.get('live')}"
        if sid == "7c":
            return f"DB 死源 {st.get('db_dead')}（全 404）→ 剔 {st.get('pruned_in_products')} 条产物 / 复活 {st.get('gh_resurrected')}"
        if sid == "7e":
            return f"deps {st.get('deps_files')} 文件 {round((st.get('deps_bytes') or 0)/1e6)}MB，重复 {st.get('duplicate_groups')} 组"
        if sid == "8":
            return f"采集入口 {st.get('ok')}/{st.get('total')} 可达"
        if sid == "9":
            return f"本地包 {st.get('zips') or '未生成'}"
        if sid == "1":
            return f"生效镜像链 {st.get('active_mirrors')}"
        return json.dumps(st, ensure_ascii=False)[:160]

    for s in steps:
        lines.append(f"| {s.get('title') or s.get('stage')} | {s.get('status')} "
                     f"| {s.get('elapsed_sec')}s | {_brief(s.get('stage'), s.get('stats'))} |")
    lines += [
        "",
        "## 全链路总账",
        "",
        f"- 接口（上游实测 verdict）：汇总 **{t.get('interfaces_total')}** 个，可用 "
        f"**{next((s['stats'].get('interfaces_by_verdict', {}).get('usable') for s in reversed(steps) if s.get('stage') == '6'), '?')}**，"
        f"死 **{next((s['stats'].get('interfaces_by_verdict', {}).get('dead') for s in reversed(steps) if s.get('stage') == '6'), '?')}**（连续失败自动进黑名单）",
        f"- 站点：上游汇总 **{t.get('sites_total')}** → 去重/门禁后留 **{t.get('sites_kept')}**",
        f"- 多仓拆分（stores/）：{t.get('multi_repo_counts')}",
        f"- 全库健康（DB）：healthy **{t.get('healthy')}** / degraded **{t.get('degraded')}** "
        f"/ unknown **{t.get('unknown')}** / dead **{t.get('dead')}**",
        f"- 直播死源（404 确定性）：剔 **{t.get('live_pruned_in_products')}** 条产物条目",
        f"- 依赖闸门：缺失 {t.get('deps_was_missing')} → 重下 {t.get('deps_repaired')}",
        f"- 自动黑名单：{t.get('blacklist_auto_lines')} 行（连续失败自动停用）＋ 人工 {t.get('blacklist_manual_lines')} 行",
        "",
        "> 每步明细见 `state/pipeline_steps/step_*.json`；机器读 `state/pipeline_report.json`。",
    ]
    mpath = os.path.join(REPO, "state", "pipeline_report.md")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return jpath, mpath


def main() -> int:
    """直接调用：python scripts/pipeline_step_stats.py <stage_id> <status> <sec>
    或 --report 只重生成汇总。"""
    if len(sys.argv) >= 2 and sys.argv[1] == "--report":
        jp, mp = write_pipeline_report()
        print(f"[pipeline_report] {os.path.relpath(jp, REPO)} + {os.path.relpath(mp, REPO)}")
        return 0
    if len(sys.argv) >= 4:
        sid, status, sec = sys.argv[1], sys.argv[2], float(sys.argv[3])
        p = write_step_file(sid, status, sec,
                            cmd=" ".join(sys.argv[4:]) if len(sys.argv) > 4 else "")
        print(f"[pipeline_step] {os.path.relpath(p, REPO)}")
        write_pipeline_report()
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
