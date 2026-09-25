#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dedup_layers.py — 去重管线 L0/L4 增强层（P1-A 第 2、3 项）。

既有三层（飞书线 dedup_merge6，口径不变）：
  L1 同 key 同 api 去重（同 key 不同 api 改名保留）
  L2 内容指纹（type+api+jar）
  L3 lives/parses 归一化（name+URL）

P1-A 增补：
  L0 规范键归一化（进 L1 之前）：源站点 URL / key / 频道名先归一化为规范键——
     URL：代理剥离(大小写不敏感/递归) + host 小写去 www + 默认端口去除 + 尾斜杠/fragment 去除；
     key：小写 + 去空白/分隔符；频道名：分组前缀剥离 + 全角转半角 + 繁转简 + 小写 + 去分隔符
     （规则单源于 state/vocab/normalization.json）。
     L0 同时统计「归一化后新增碰撞」（raw URL 不同但规范键相同的对，即此前 L1-L3 漏掉的重复）。
  L4 跨日衰减过滤（聚合入池之前）：读 validated.json（单一事实源），
     剔除 decay stage ∈ {watch, out} 的上游源（连续 3 日未通过→watch 观察剔除，
     连续 7 日→out 归档淘汰；任一日通过自动回捞）。衰减策略见 validated_state.DEFAULT_POLICY。

本模块被仓库管线与飞书线 dedup_merge6 共同引用——去重规范键只有这一份实现。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validated_state import (  # noqa: E402
    canonical_key, normalize_name, load_validated, active_sources, strip_proxy,
)


def norm_url(u):
    """L0 URL 规范键（替代旧 norm_url 的 lower+rstrip——旧实现不剥代理/端口/www）。"""
    if not isinstance(u, str):
        return u
    return canonical_key(u.strip())


def norm_api(a):
    if not isinstance(a, str):
        return a
    a = a.strip()
    if a.startswith("http"):
        return norm_url(a)
    return a


def api_ci(a):
    a = norm_api(a)
    return a.lower() if isinstance(a, str) else a


def norm_name(n):
    """L0 频道/站点名规范键。"""
    if not isinstance(n, str):
        return n
    return normalize_name(n.strip())


def norm_key(k):
    """L0 站点 key 规范键：小写 + 去空白/分隔符。"""
    if not isinstance(k, str):
        return k
    import re
    return re.sub(r"[\s_\-·•]+", "", k.strip().lower())


# ---------------- L0：归一化 + 碰撞统计 ----------------

def l0_pass(sites):
    """对站点列表做 L0 归一化标注。返回 (标注数, 新增碰撞组数, 样本)。
    碰撞组 = raw url 互不相同但 url 规范键相同（≥2 个）。"""
    import re as _re
    changed = 0
    by_ckey = {}
    for s in sites:
        if not isinstance(s, dict):
            continue
        raw = s.get("api") or s.get("url") or ""
        ck = norm_url(raw) if isinstance(raw, str) and raw.strip().startswith("http") else None
        old = {"url": raw, "key": s.get("key"), "name": s.get("name")}
        kn = norm_key(s.get("key") or "")
        nn = norm_name(s.get("name") or "")
        s["_l0"] = {"url_ckey": ck, "key_norm": kn, "name_norm": nn}
        if (ck != old["url"] and ck is not None) or kn != (old["key"] or "").strip().lower() or nn != (old["name"] or "").strip().lower():
            changed += 1
        if ck:
            by_ckey.setdefault(ck, []).append(old["url"])
    collisions = {k: v for k, v in by_ckey.items()
                  if len({u.rstrip("/").lower() for u in v}) >= 2}
    sample = [{"ckey": k[:80], "raw_urls": v[:3]} for k, v in list(collisions.items())[:8]]
    return changed, len(collisions), sample


# ---------------- L1：同 key 同 api（key 用规范键比较） ----------------

def l1_key_dedup(sources):
    """sources: [{'name','canonical_url','sites':[...]}]（sources_parsed.json 的 ok 子集）。"""
    by_key = {}
    l1_removed, l1_renamed = [], []
    raw_total = 0
    for s in sources:
        for site in s.get("sites", []):
            if not isinstance(site, dict) or not site.get("key") or not site.get("name"):
                continue
            raw_total += 1
            k_raw = site["key"]
            k = norm_key(k_raw) or k_raw
            sc = dict(site)
            sc["_src"] = s["name"]
            sc["_src_url"] = s.get("canonical_url", "")
            if k in by_key:
                if api_ci(by_key[k].get("api")) == api_ci(sc.get("api")):
                    l1_removed.append({"key": k_raw, "name": (sc.get("name") or "")[:40],
                                       "kept_from": by_key[k]["_src"], "dup_from": s["name"]})
                else:
                    nk, i = k, 2
                    while nk in by_key:
                        if api_ci(by_key[nk].get("api")) == api_ci(sc.get("api")):
                            break
                        nk = "%s-%d" % (k, i)
                        i += 1
                    if nk in by_key:
                        l1_removed.append({"key": k_raw, "name": (sc.get("name") or "")[:40],
                                           "kept_from": by_key[nk]["_src"], "dup_from": s["name"]})
                    else:
                        sc["key"] = nk
                        by_key[nk] = sc
                        l1_renamed.append({"orig_key": k_raw, "new_key": nk, "src": s["name"]})
            else:
                by_key[k] = sc
    return by_key, {"removed": l1_removed, "renamed": l1_renamed, "raw_total": raw_total}


# ---------------- L2：内容指纹 ----------------

def l2_fingerprint(by_key):
    seen, removed, after = {}, [], {}
    for k, s in by_key.items():
        fp = (s.get("type"), api_ci(s.get("api")),
              norm_url(s.get("_jar_abs") or s.get("jar") or ""))
        if fp in seen:
            removed.append({"removed_key": k, "removed_name": (s.get("name") or "")[:40],
                            "kept_key": seen[fp]["key"], "kept_src": seen[fp]["_src"]})
        else:
            seen[fp] = s
            after[k] = s
    return after, removed


# ---------------- L3：lives/parses（name 用规范键） ----------------

def l3_lives_parses(sources):
    lives_map, lm_removed, parses_map, pm_removed = {}, [], {}, []
    raw_l = raw_p = 0
    for s in sources:
        for lv in s.get("lives") or []:
            if not isinstance(lv, dict):
                continue
            raw_l += 1
            k = (norm_name(lv.get("name") or ""), norm_url(lv.get("url") or ""))
            if not k[1]:
                continue
            if k in lives_map:
                lm_removed.append({"kept": lv.get("name"), "removed_src": s["name"]})
            else:
                lives_map[k] = lv
        for p in s.get("parses") or []:
            if not isinstance(p, dict) or not p.get("url"):
                continue
            raw_p += 1
            k = (norm_name(p.get("name") or ""), norm_url(p.get("url") or ""))
            if k in parses_map:
                pm_removed.append({"kept": p.get("name"), "removed_src": s["name"]})
            else:
                parses_map[k] = p
    return lives_map, parses_map, {"lives_removed": lm_removed, "parses_removed": pm_removed,
                                   "raw_lives": raw_l, "raw_parses": raw_p}


# ---------------- L4：跨日衰减过滤 ----------------

def l4_filter(sources, root="."):
    """按 validated.json 衰减结论过滤上游源。返回 (保留sources, 摘要)。"""
    doc = load_validated(root)
    active = active_sources(doc)
    kept, dropped = [], []
    for s in sources:
        nm = s.get("name")
        ckey = norm_url(s.get("canonical_url") or "")
        ent = None
        for e in doc["sources"].values():
            if isinstance(e, dict) and (e.get("name") == nm or e.get("ckey") == ckey):
                ent = e
                break
        stage = (ent or {}).get("decay_stage") or (ent or {}).get("decay", {}).get("stage", "unknown")
        if ent is None or stage == "active":
            kept.append(s)
        else:
            dropped.append({"source": nm, "stage": stage,
                            "streak": (ent.get("decay") or {}).get("streak_days"),
                            "last_ok_at": ent.get("last_ok_at", "")})
    summary = {"sources_in": len(sources), "sources_kept": len(kept),
               "sources_dropped": len(dropped),
               "sites_dropped": sum(x.get("site_count", 0) for x in dropped),
               "dropped_detail": dropped[:12],
               "policy": doc.get("policy", {}).get("decay")}
    return kept, summary


# ---------------- 一键管线（供巡检与对账复跑） ----------------

def run(sources_parsed_path, out_report, root=".", apply_l4=True):
    srcs = json.load(open(sources_parsed_path, encoding="utf-8"))
    ok = [s for s in srcs if s.get("status") == "ok"]
    report = {"input": sources_parsed_path, "sources_fetched": len(srcs), "sources_ok": len(ok)}
    if apply_l4:
        ok, report["L4"] = l4_filter(ok, root)
    # L0
    all_sites = [s for src in ok for s in src.get("sites", [])]
    changed, coll_n, coll_sample = l0_pass(all_sites)
    report["L0"] = {"sites": len(all_sites), "normalized_changed": changed,
                    "new_collision_groups": coll_n, "collision_sample": coll_sample}
    # L1
    by_key, l1 = l1_key_dedup(ok)
    report["L1"] = {"layer": "key去重(规范键)", "before": l1["raw_total"], "after": len(by_key),
                    "removed": len(l1["removed"]), "renamed_kept": len(l1["renamed"])}
    # L2
    after_l2, l2 = l2_fingerprint(by_key)
    report["L2"] = {"layer": "内容指纹(type+api+jar)", "before": len(by_key),
                    "after": len(after_l2), "removed": len(l2)}
    # L3
    lives_map, parses_map, l3 = l3_lives_parses(ok)
    report["L3"] = {"layer": "lives+parses归一化(规范键name+URL)",
                    "before": "lives %d / parses %d" % (l3["raw_lives"], l3["raw_parses"]),
                    "after": "lives %d / parses %d" % (len(lives_map), len(parses_map)),
                    "removed": len(l3["lives_removed"]) + len(l3["parses_removed"])}
    report["summary"] = {"final_sites": len(after_l2), "final_lives": len(lives_map),
                         "final_parses": len(parses_map),
                         "total_removed": report["L1"]["removed"] + report["L2"]["removed"] + report["L3"]["removed"]}
    with open(out_report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return report


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: dedup_layers.py <sources_parsed.json> <out_report.json> [--root R]")
        sys.exit(2)
    root = "."
    if "--root" in sys.argv:
        i = sys.argv.index("--root")
        root = sys.argv[i + 1]
        sys.argv = sys.argv[:i] + sys.argv[i + 2:]
    r = run(sys.argv[1], sys.argv[2], root)
    for k in ("L4", "L0", "L1", "L2", "L3", "summary"):
        if k in r:
            print(k, json.dumps(r[k], ensure_ascii=False)[:300])
