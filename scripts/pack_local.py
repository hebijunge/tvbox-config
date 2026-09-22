#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pack_local.py — 生成本地 TVBox 接口包（zip）

产出可直接导入 TVBox 的配置 + 被引用的依赖文件。核心规则：
  包内文件路径 = 配置引用的字面路径（去掉 ./ 前缀）——TVBox 在 Android 上
  路径大小写敏感/不解码 URL，因此必须按引用字面落盘，内容从本地解析路径读取。

产出：
  tvbox.json   点播主配置（剔除实测 dead + 依赖缺失站点，排序后）
  live.json    直播
  short.json   短剧（group=短剧）
  adult.json   成人（本地留档 .workbuddy/adult.local.json；文件不存在自动跳过）
  deps/ lib/ js/ lives/  被引用的依赖

用法：python scripts/pack_local.py [--out packs] [--keep-dead] [--no-rank]
接入：run_all.py 阶段 8；daily.yml CI 步骤（无成人留档自动跳过）
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.parse
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

REL_RE = re.compile(r"(\./(?:deps|lib|js|lives|json)/[^\s\"';|]+)")

# 全局：本地路径索引（小写 + URL 解码键 -> 真实相对路径）
PATH_IDX = {}


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def build_path_idx():
    for dp, _, fs in os.walk("."):
        parts = dp.replace(os.sep, "/").split("/")
        if any(p in (".git", ".workbuddy", "node_modules", "packs") for p in parts):
            continue
        for f in fs:
            rel = os.path.join(dp, f).replace(os.sep, "/").lstrip("./")
            PATH_IDX[rel.lower()] = rel
            try:
                PATH_IDX[urllib.parse.unquote(rel).lower()] = rel
            except Exception:
                pass


def resolve_ref(ref):
    """'./deps/...' -> 本地真实存在的相对路径；不存在返回 None。
    兼容：大小写差异（Windows 落盘）、URL 编码差异（%xx vs 中文）。"""
    p = ref[2:]
    if os.path.isfile(p):
        return p
    hit = PATH_IDX.get(p.lower())
    if hit:
        return hit
    try:
        pu = urllib.parse.unquote(p).lower()
    except Exception:
        pu = p
    hit = PATH_IDX.get(pu)
    if hit:
        return hit
    try:
        pq = urllib.parse.quote(p).lower()
    except Exception:
        pq = p
    return PATH_IDX.get(pq)


def collect_rel_refs(obj, out):
    """递归收集对象里所有 ./deps|lib|js|lives|json/ 引用（保留 ./ 前缀字面）。"""
    if isinstance(obj, str):
        for m in REL_RE.finditer(obj):
            out.add(m.group(1).rstrip(".,"))
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_rel_refs(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_rel_refs(v, out)


def site_rel_refs(site):
    out = set()
    collect_rel_refs(site, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="packs")
    ap.add_argument("--keep-dead", action="store_true", help="保留实测 dead 站点")
    ap.add_argument("--no-rank", action="store_true", help="跳过重跑 rank_sites")
    ap.add_argument("--adult", default=os.path.join(".workbuddy", "adult.local.json"))
    args = ap.parse_args()
    os.chdir(ROOT)

    # ---------- 0. 重跑排序：最新合并产物 + 最新探针 ----------
    if not args.no_rank:
        log("重跑 rank_sites（对最新 tvbox.json 套用探针排序/分组）…")
        subprocess.run([sys.executable, os.path.join(HERE, "rank_sites.py"),
                        "--drpy-probe", "probe/drpy_probe.json"],
                       check=False, capture_output=True)

    ranked_path = "tvbox.ranked.json" if os.path.isfile("tvbox.ranked.json") else "tvbox.json"
    base = json.load(open(ranked_path, encoding="utf-8"))
    log("配置骨架：%s（%d 站点）" % (ranked_path, len(base.get("sites", []))))
    build_path_idx()
    log("本地路径索引：%d 个文件" % len(PATH_IDX))

    # ---------- 1. DB 健康 ----------
    dead_sites, dead_live_urls, health_of = set(), set(), {}
    dbp = os.path.join("state", "tvbox.db")
    if os.path.isfile(dbp):
        conn = sqlite3.connect(dbp)
        if not args.keep_dead:
            dead_sites = {r[0] for r in conn.execute(
                "SELECT key FROM interfaces WHERE health='dead'")}
            dead_live_urls = {r[0] for r in conn.execute(
                "SELECT url FROM lives WHERE health='dead'")}
        for k, h, ms, lv, at in conn.execute(
                "SELECT key, health, latency_ms, level, last_check_at FROM interfaces"):
            health_of[k] = {"_health": h, "_latency_ms": ms,
                            "_level": lv, "_checked_at": at}
        conn.close()
        log("DB dead 站点 %d / dead 直播源 %d" % (len(dead_sites), len(dead_live_urls)))

    # ---------- 2. 壳与点播过滤 ----------
    shell = {k: v for k, v in base.items() if k != "sites"}
    sites_all = [s for s in base.get("sites", []) if isinstance(s, dict)]

    m = re.match(r"^(\./[^;]+)", shell.get("spider") or "")
    top_spider = m.group(1) if m else None

    kept, drop_dead, drop_dep = [], 0, 0
    missing_refs = set()
    for s in sites_all:
        if s.get("key") in dead_sites:
            drop_dead += 1
            continue
        bad = {r for r in site_rel_refs(s) if resolve_ref(r) is None}
        if bad:
            drop_dep += 1
            missing_refs |= bad
            continue
        s.update(health_of.get(s.get("key"), {"_health": "unknown"}))
        kept.append(s)
    log("点播：总 %d → 剔 dead %d + 剔依赖缺失 %d → 保留 %d"
        % (len(sites_all), drop_dead, drop_dep, len(kept)))
    if missing_refs:
        log("  缺失依赖样例: " + "; ".join(sorted(missing_refs)[:5]))

    def filter_lives(lives):
        out, drop = [], 0
        for lv in lives or []:
            if not isinstance(lv, dict):
                continue
            urls = [u.strip() for u in re.split(r"[;,]", str(lv.get("url") or "")) if u.strip()]
            refs = set()
            collect_rel_refs(lv, refs)
            if urls and all(u in dead_live_urls for u in urls):
                drop += 1
                continue
            if refs and all(resolve_ref(r) is None for r in refs):
                drop += 1
                continue
            out.append(lv)
        return out, drop

    lives_kept, shell_live_drop = filter_lives(shell.get("lives"))
    parses_kept, parse_drop = [], 0
    for p in shell.get("parses") or []:
        if not isinstance(p, dict):
            continue
        refs = set()
        collect_rel_refs(p, refs)
        if refs and all(resolve_ref(r) is None for r in refs):
            parse_drop += 1
            continue
        parses_kept.append(p)
    log("壳内直播 %d→%d（剔 %d）、解析 %d→%d（剔 %d）"
        % (len(shell.get("lives") or []), len(lives_kept), shell_live_drop,
           len(shell.get("parses") or []), len(parses_kept), parse_drop))

    # ---------- 3. 四份配置 ----------
    def new_cfg(sites):
        cfg = dict(shell)
        cfg["sites"] = sites
        cfg["lives"] = lives_kept
        cfg["parses"] = parses_kept
        return cfg

    cfg_tvbox = new_cfg(kept)
    short_sites = [s for s in kept if s.get("group") == "短剧"]
    cfg_short = new_cfg(short_sites)

    live_doc = json.load(open("live.json", encoding="utf-8")) if os.path.isfile("live.json") else {}
    live_src = live_doc.get("lives") or lives_kept
    lv_kept, lv_drop = filter_lives(live_src)
    cfg_live = {"lives": lv_kept, "spider": shell.get("spider", ""),
                "parses": parses_kept}
    log("直播专版：%d → 剔 %d → 保留 %d" % (len(live_src), lv_drop, len(lv_kept)))

    cfg_adult = None
    if os.path.isfile(args.adult):
        adoc = json.load(open(args.adult, encoding="utf-8"))
        ad_ok, ad_bad = [], 0
        for s in (adoc.get("sites") or []):
            if any(resolve_ref(r) is None for r in site_rel_refs(s)):
                ad_bad += 1
                continue
            ad_ok.append(s)
        cfg_adult = new_cfg(ad_ok)
        log("成人：留档 %d → 剔依赖缺失 %d → 保留 %d" % (len(adoc.get("sites") or []), ad_bad, len(ad_ok)))

    docs = [("tvbox.json", cfg_tvbox), ("live.json", cfg_live), ("short.json", cfg_short)]
    if cfg_adult:
        docs.append(("adult.json", cfg_adult))

    # ---------- 4. 依赖收集（按引用字面落盘） ----------
    refs = set()
    for _, cfg in docs:
        collect_rel_refs(cfg, refs)
    if top_spider:
        refs.add(top_spider)

    plan = {}      # 包内字面路径 -> 本地真实路径
    unresolvable = []
    for r in sorted(refs):
        src = resolve_ref(r)
        if src:
            plan[r[2:]] = src
        else:
            unresolvable.append(r)

    # ---------- 4.5 内容级去重（2026-09-21 点播+容错线，借鉴 fish2018/tvbox）----------
    # fish2018 tvbox_tools 在下载侧用 file_hash（内容 hash）+ 文件大小双条件判重后
    # 跳过重复下载；我们是组包侧等价实现：不同引用路径但内容完全相同（sha256 与
    # 大小双双一致）的依赖只随包附带一份，其余引用路径统一改写到保留路径。
    # 与 fetch_merge 的 L1/L2 源级去重作用对象不同（它防重复源入库，这里防重复文件落包），互补而非替代。
    def _rewrite_refs(obj, pat, new_ref):
        if isinstance(obj, str):
            return pat.sub(new_ref, obj)
        if isinstance(obj, dict):
            return {k: _rewrite_refs(v, pat, new_ref) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_rewrite_refs(v, pat, new_ref) for v in obj]
        return obj

    content_map = {}   # (sha256, size) -> 保留的包内路径
    dedup_map = {}     # 被去重路径 -> 保留路径
    for dst_rel in sorted(plan):
        src = plan[dst_rel]
        _h = hashlib.sha256()
        try:
            with open(src, "rb") as fh:
                for _chunk in iter(lambda: fh.read(1 << 20), b""):
                    _h.update(_chunk)
            key = (_h.hexdigest(), os.path.getsize(src))
        except OSError:
            continue
        if key in content_map and content_map[key] != dst_rel:
            dedup_map[dst_rel] = content_map[key]
        else:
            content_map.setdefault(key, dst_rel)
    # 长路径先改写，配合负向前瞻断言避免前缀误替换（./deps/a.jar vs ./deps/a.jar.bak）
    for old_rel in sorted(dedup_map, key=len, reverse=True):
        keep_rel = dedup_map[old_rel]
        pat = re.compile(re.escape("./" + old_rel) + r"(?![A-Za-z0-9._~%/-])")
        new_ref = "./" + keep_rel
        for _i, (name, cfg) in enumerate(docs):
            docs[_i] = (name, _rewrite_refs(cfg, pat, new_ref))
        if top_spider and pat.match(top_spider):
            top_spider = pat.sub(new_ref, top_spider)
        plan.pop(old_rel, None)
    if dedup_map:
        log("内容级去重：%d 个重复依赖（sha256+大小双条件一致），引用已改写：%s"
            % (len(dedup_map), "; ".join(f"{o} → {k}" for o, k in sorted(dedup_map.items())[:5])))

    n_bytes = sum(os.path.getsize(v) for v in plan.values())
    log("依赖：%d 个文件 / %.1f MB（真缺失 %d）"
        % (len(plan), n_bytes / 1048576, len(unresolvable)))

    # ---------- 5. 组包 ----------
    build = os.path.join(args.out, "build")
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(build)
    for name, cfg in docs:
        json.dump(cfg, open(os.path.join(build, name), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    copy_fail = []
    for dst_rel, src in sorted(plan.items()):
        dst = os.path.join(build, dst_rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.copyfile(src, dst)
        except (OSError, ValueError) as e:
            copy_fail.append((dst_rel, str(e)[:60]))

    readme = f"""TVBox 本地接口包（生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}）
================================================================
离线自洽包：所有相对路径依赖已随包附带，解压到任意目录导入即可。

【导入方法】
1. 解压本 zip 到手机/盒子任意目录（保持目录结构，tvbox.json 与 deps/ 同层）
2. 打开 TVBox/影视仓 → 设置/配置 → 本地导入
3. 选择解压目录里对应的 json：
   tvbox.json  点播主配置（{len(kept)} 个站点，推荐）
   live.json   直播专版（{len(lv_kept)} 条直播源）
   short.json  短剧专版（{len(short_sites)} 个短剧站点）
   {('adult.json  成人专版（' + str(len(cfg_adult['sites'])) + ' 个站点）') if cfg_adult else ''}

【口径说明】
- 已剔除：实测五关/连通性确认失效（dead）的站点与直播源；引用依赖缺失的站点
- 未测过的新站（unknown）保留，健康状态标注在站点 _health 字段
- _health/_latency_ms/_level/_checked_at 为实测信息，TVBox 自动忽略，不影响导入
- 少数 jar/js 为远程 URL 引用，TVBox 运行时自动联网加载，属标准行为

【目录】
deps/ lib/ js/ lives/ —— 配置引用的依赖（jar 爬虫 / js 规则 / 直播源），请整体存放
"""
    open(os.path.join(build, "使用说明.txt"), "w", encoding="utf-8").write(readme)

    # P1-2 卫生修复（2026-09-22）：zip 改固定名，Release 端 --clobber 原地覆盖，
    # 不再按日期累积（此前 TVBox接口包_YYYYMMDD.zip 逐日堆积 70MB+，Release 资产膨胀）。
    # 生成日期记录在包内「使用说明.txt」与 pack_report.json，不丢可追溯性。
    zip_path = os.path.join(args.out, "tvbox-latest.zip")
    if os.path.isfile(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dirpath, _, files in os.walk(build):
            for f in files:
                fp = os.path.join(dirpath, f)
                z.write(fp, os.path.relpath(fp, build).replace(os.sep, "/"))
    zsize = os.path.getsize(zip_path)

    # ---------- 6. 完整性校验：包内配置的每个引用必须命中包内文件 ----------
    bad = []
    for name, _ in docs:
        cfg = json.load(open(os.path.join(build, name), encoding="utf-8"))
        r2 = set()
        collect_rel_refs(cfg, r2)
        if top_spider:
            r2.add(top_spider)
        for r in r2:
            if not os.path.isfile(os.path.join(build, r[2:].replace("/", os.sep))):
                bad.append((name, r))
    if bad:
        log("!! 完整性校验失败 %d 处：" % len(bad))
        for n, r in bad[:10]:
            log("   %s → %s" % (n, r))
    else:
        log("完整性校验通过：包内所有相对路径引用均可解析")

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "zip": os.path.basename(zip_path), "zip_size_mb": round(zsize / 1048576, 2),
        "tvbox": {"sites": len(kept), "lives": len(lives_kept), "parses": len(parses_kept),
                  "drop_dead": drop_dead, "drop_missing_dep": drop_dep},
        "short": len(short_sites),
        "live": {"kept": len(lv_kept), "drop_dead": lv_drop},
        "adult": len(cfg_adult["sites"]) if cfg_adult else None,
        "dep_files": len(plan), "dep_mb": round(n_bytes / 1048576, 1),
        "copy_fail": len(copy_fail), "unresolvable": len(unresolvable),
        "integrity": "ok" if not bad else "FAIL(%d)" % len(bad),
    }
    json.dump(report, open(os.path.join(args.out, "pack_report.json"), "w",
                           encoding="utf-8"), ensure_ascii=False, indent=1)
    if copy_fail:
        log("复制失败 %d 个（Windows 非法文件名等）：" % len(copy_fail))
        for r, e in copy_fail[:8]:
            log("   %s (%s)" % (r, e))
    shutil.rmtree(build, ignore_errors=True)
    log("完成：%s（%.1f MB）" % (zip_path, zsize / 1048576))
    return 0 if not bad and not copy_fail else 2


if __name__ == "__main__":
    sys.exit(main())
