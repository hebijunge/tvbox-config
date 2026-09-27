#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live-speedtest 快照成人兜底清洗（繁简归一口径，2026-09-27）。

背景（live-speedtest run 36270538085 门禁失败实证，task 7690005691204947122）：
B 站轮播房间标题瞬态为繁体 JAV 片名「母亲节特别企划/義母亂倫童貞畢業/tz-056」，
live_aggregate ingest 层 is_adult(名) 用简体词表查繁体名漏网（亂倫 != 乱伦），
而 cmap 聚合键 dedup_key 内 to_simp 转简体后写进 live_channels.json /
state/live_checks.json 的 channels key——adult_leak_check 门禁扫 key 命中
porn_kw:乱伦，exit 2 一票否决阻断提交（门禁行为正确，但 run 红灯、该 shard
实测产物全部报废）。

本脚本在测速落盘之后、门禁之前跑：对快照与分组产物按「to_simp(名) 再判
adult」的口径做兜底剔除（与本仓 fetch_merge._scrub_snapshot 消费侧清洗同理念）：
  ① state/live_checks.json：channels 剔成人键 + verified 同步剔行；
  ② live_channels.json（.gitignore 本地产物，不入库）：channels 剔成人键；
  ③ lives/groups/*.txt / *.m3u / lives/live_precise.txt：剔成人频道行（含线路）。
剔除口径 = adult_rule_of(to_simp(段))（与 ingest 同一套词表，仅补繁简归一）；
URL 一律 is_adult_url 域名黑名单复查（词表滞后窗口双保险，同 b960bfd 输出层防御）。
清洗只删不增；被删频道若属误杀，应走词表白名单复核流程，本脚本不做放行。

门禁 adult_leak_check 仍是一票否决权威：本脚本只做前置兜底，漏网新形态由
门禁拦截（run 红灯），不因本脚本存在而放宽门禁语义。

约束：不改 live_aggregate.py（并行任务在跑，改动面隔离）；本脚本随
live-speedtest.yml 一起仅在测速工作流内调用。
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

# import live_aggregate 仅复用其词表/繁简工具（无网络副作用：import 不触发聚合）
import live_aggregate as la  # noqa: E402


def _t2s(s):
    """繁→简；to_simp 不可用或失败时原样返回（此时行为退化为与 ingest 同口径）。"""
    if not s:
        return s or ""
    try:
        return la.to_simp(s)
    except Exception:
        return s


def _is_adult_t2s(name):
    """成人判定（繁简归一）：整名 + 逐「/」段，先 to_simp 再过 adult 词表；
    任一段命中即成人。与门禁扫描的 key 形态（dedup_key 已转简）对齐。"""
    if not name:
        return False
    segs = [name] + [x for x in name.split("/") if x]
    for seg in segs:
        if la.adult_rule_of(_t2s(seg)):
            return True
    return False


# ---- ① ② JSON 快照清洗 ----

def _scrub_live_checks(path):
    """state/live_checks.json：channels 剔成人键，verified 同步剔行；
    同步改写 live_check_meta.json 的 channels/verified_channels 计数。"""
    n_ch = n_vd = 0
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    chs = doc.get("channels")
    if isinstance(chs, dict):
        drop = [k for k, v in chs.items()
                if _is_adult_t2s(k) or _is_adult_t2s((v or {}).get("name") or k)]
        for k in drop:
            chs.pop(k, None)
        n_ch = len(drop)
    vd = doc.get("verified")
    if isinstance(vd, dict):
        for k in [k for k in vd if _is_adult_t2s(k)]:
            vd.pop(k, None)
            n_vd += 1
        # 键内线路：成人域名 URL 行剔除
        for k, urls in vd.items():
            if isinstance(urls, list):
                kept = [u for u in urls if not la.is_adult_url(u)]
                if len(kept) != len(urls):
                    n_vd += len(urls) - len(kept)
                    vd[k] = kept
    if n_ch or n_vd:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        # 同目录 meta 计数对齐（时间戳不动）；channels==0 会被门禁校验步拦截，
        # 属极端场景，保持门禁语义不做放行
        meta_p = os.path.join(os.path.dirname(path), "live_check_meta.json")
        try:
            with open(meta_p, encoding="utf-8") as f:
                meta = json.load(f)
            if isinstance(chs, dict):
                meta["channels"] = len(chs)
            if isinstance(vd, dict):
                meta["verified_channels"] = len(vd)
            with open(meta_p, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=1)
        except Exception as _e:  # noqa: BLE001  meta 计数失败不影响清洗本身
            print("[speedtest-scrub] meta 计数更新失败（忽略）: %s" % _e, flush=True)
    print("[speedtest-scrub] %s 剔除 %d 频道 / %d verified 项" % (path, n_ch, n_vd), flush=True)
    return n_ch


def _scrub_channels_json(path):
    """live_channels.json（本地产物）：channels 剔成人键。"""
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    chs = doc.get("channels")
    if not isinstance(chs, dict):
        return 0
    drop = [k for k in chs if _is_adult_t2s(k)]
    for k in drop:
        chs.pop(k, None)
    if drop:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
    print("[speedtest-scrub] %s 剔除 %d 频道" % (path, len(drop)), flush=True)
    return len(drop)


# ---- ③ 文本产物清洗（口径同 fetch_merge._scrub_txt_file/_scrub_m3u_file，判名换 t2s）----

def _scrub_txt_file(path):
    """tvbox 分组 txt 成人行剔除（含其全部线路；#genre# 组头保留）。"""
    n = 0
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    kept = []
    for ln in lines:
        if not ln or ln.endswith(",#genre#"):
            kept.append(ln)
            continue
        name = ln.split(",", 1)[0].strip()
        if _is_adult_t2s(name):
            n += 1
            continue
        kept.append(ln)
    if n:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))
    print("[speedtest-scrub] %s 剔除 %d 行" % (os.path.basename(path), n), flush=True)
    return n


def _scrub_m3u_file(path):
    """m3u 成人频道剔除：#EXTINF 判名，命中连其后 URL 行一起删。"""
    n = 0
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    kept, adult_cur = [], False
    for ln in lines:
        if ln.startswith("#EXTINF"):
            name = ln.rsplit(",", 1)[-1].strip()
            adult_cur = _is_adult_t2s(name)
            if adult_cur:
                n += 1
                continue
            kept.append(ln)
        elif ln.startswith("#"):
            adult_cur = False  # 其他元信息行不影响后续条目
            kept.append(ln)
        else:
            if adult_cur:
                n += 1
                continue
            kept.append(ln)
    if n:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))
    print("[speedtest-scrub] %s 剔除 %d 条目" % (os.path.basename(path), n), flush=True)
    return n


def main(repo=None):
    repo = repo or os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
    total = 0
    # ① 测速快照（提交物）
    try:
        total += _scrub_live_checks(os.path.join(repo, "state", "live_checks.json"))
    except FileNotFoundError:
        print("[speedtest-scrub] state/live_checks.json 不存在（跳过）", flush=True)
    # ② 本地明细（.gitignore，不入库，但门禁会扫）
    try:
        total += _scrub_channels_json(os.path.join(repo, "live_channels.json"))
    except Exception as e:  # noqa: BLE001
        print("[speedtest-scrub] live_channels.json 清洗异常（门禁兜底）: %s" % e, flush=True)
    # ③ 分组与精准版产物
    for p in sorted(glob.glob(os.path.join(repo, "lives", "groups", "*.txt"))):
        try:
            total += _scrub_txt_file(p)
        except Exception as e:  # noqa: BLE001
            print("[speedtest-scrub] %s 清洗异常（门禁兜底）: %s" % (p, e), flush=True)
    for p in sorted(glob.glob(os.path.join(repo, "lives", "groups", "*.m3u"))):
        try:
            total += _scrub_m3u_file(p)
        except Exception as e:  # noqa: BLE001
            print("[speedtest-scrub] %s 清洗异常（门禁兜底）: %s" % (p, e), flush=True)
    try:
        total += _scrub_txt_file(os.path.join(repo, "lives", "live_precise.txt"))
    except Exception as e:  # noqa: BLE001
        print("[speedtest-scrub] live_precise.txt 清洗异常（门禁兜底）: %s" % e, flush=True)
    print("[speedtest-scrub] 完成，共剔除 %d 处" % total, flush=True)
    return 0


if __name__ == "__main__":
    # 清洗属兜底性质：任何异常不使 run 红灯——门禁 adult_leak_check 是最终防线
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("[speedtest-scrub] 异常（交由门禁兜底）: %s" % e, flush=True)
        sys.exit(0)
