#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canary_promote.py — 直播 canary 池准入/晋升（P1-B，方案 docs/iptvorg-adapter-plan.md §4）。

职责：
  --probe    对 canary 池条目逐条探活（Range GET 4KB，复用 live_probe.http_get 的
             TLS/超时/UA 语义），结果以 {"date","success","latency_ms","via"} 追加进
             probe_history（每日一条，同日重跑覆盖）
  --promote  三道闸门评估（方案 §4.1）：
               闸1 稳定天数：probe_history >= canary.STABILITY_DAYS(7) 天，
                   且近 7 天失败数 <= canary.MAX_FAILURES(默认 0/7，弱网放宽路径见参数表)
               闸2 探测命中率：近 7 天成功率 >= canary.HIT_RATE_THRESHOLD(0.6)
               闸3 labels 反证：含 Geo-blocked / Not 24/7 不收
             通过 -> state/upstreams/iptvorg.normal.json（标准上游形态，source=iptv-org，
                     下一次 live_aggregate 跑批汇入 live_verified.txt）；
             连续 21 天未通过 -> state/canary/iptvorg_rejected.json（打 reject_reason）。
  --dry-run  只评估输出判定，不写任何文件。

输出：canary 池 JSON state/canary/iptvorg.json（meta.gate_params 留档当日阈值）。

回滚锚点（方案 §7）：删除 state/canary/iptvorg.json 即回到未接入状态。
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

from live_probe import http_get  # 复用既有探针的 TLS 上下文/限流读取/UA 语义（设计同源）

CANARY_POOL = os.path.join(REPO, "state", "canary", "iptvorg.json")
REJECTED_PATH = os.path.join(REPO, "state", "canary", "iptvorg_rejected.json")
PROMOTED_PATH = os.path.join(REPO, "state", "upstreams", "iptvorg.normal.json")

# 闸门参数（方案 §4.2 参数表；环境变量可覆盖）
STABILITY_DAYS = int(os.environ.get("canary.STABILITY_DAYS", "7"))
HIT_RATE_THRESHOLD = float(os.environ.get("canary.HIT_RATE_THRESHOLD", "0.6"))
MAX_FAILURES = int(os.environ.get("canary.MAX_FAILURES", "0"))       # 0/7；弱网放宽到 1/7（小补丁路径）
REJECT_LABELS = {"Geo-blocked", "Not 24/7"}
REJECT_AFTER_DAYS = int(os.environ.get("canary.REJECT_AFTER_DAYS", "21"))
PROBE_WORKERS = int(os.environ.get("canary.PROBE_WORKERS", "8"))
PROBE_TIMEOUT = int(os.environ.get("canary.PROBE_TIMEOUT", "8"))

TZ = timezone(timedelta(hours=8))

# 探活响应判定：JSON/HTML/text 拒，音频/视频魔数或 m3u8 文本放行（与 v27 内容校验同思路）
_MAGIC = (b"#EXTM3U", b"#EXT-X", b"RIFF", b"\x1aE\xdf\x80", b"\x00\x00\x00", b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xf1", b"OggS", b"fLaC")


def _today():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _days_since(date_str):
    try:
        return (datetime.now(TZ) - datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ)).days
    except ValueError:
        return 0


def looks_like_stream(body: bytes) -> bool:
    if not body:
        return False
    low = body[:2048].lstrip().lower()
    if low.startswith((b"<html", b"<!doctype", b"{", b"[{\"")):
        return False
    # MPEG-TS：0x47 同步字节 + 188 字节周期复现（单字节 0x47='G' 易误放 ASCII 文本）
    if body[0] == 0x47 and (len(body) < 189 or body[188] == 0x47):
        return True
    for m in _MAGIC:
        if body.startswith(m):
            return True
    return False


def probe_one(entry):
    """单条探活：Range GET 4KB，2xx 且非 HTML/JSON 即成功。"""
    url = entry.get("url") or ""
    headers = entry.get("headers") or {}
    ua = headers.get("User-Agent") or None
    t0 = time.time()
    status, hdrs, body = http_get(url, PROBE_TIMEOUT, rng="0-4095", ua=ua)
    latency = int((time.time() - t0) * 1000)
    ok = 200 <= status < 300 and looks_like_stream(body or b"")
    return {"date": _today(), "success": bool(ok), "latency_ms": latency, "via": "canary_promote.py", "status": status}


def cmd_probe(pool, limit):
    entries = pool.get("entries", [])
    if limit:
        # 只探未晋升且当日未探过的（重跑幂等：同日已有记录的跳过）
        todo = [e for e in entries if not e.get("admitted") and
                not (e.get("probe_history") or [{}])[-1].get("date") == _today()]
        todo = todo[:limit]
    else:
        todo = [e for e in entries if not e.get("admitted") and
                not (e.get("probe_history") or [{}])[-1].get("date") == _today()]
    print("[probe] 待探 %d / 池 %d（并发 %d，超时 %ds）" % (len(todo), len(entries), PROBE_WORKERS, PROBE_TIMEOUT))
    ok_n = 0
    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as ex:
        futs = {ex.submit(probe_one, e): e for e in todo}
        for fu in as_completed(futs):
            e = futs[fu]
            try:
                r = fu.result()
            except Exception as ex_err:  # 单条失败不中断
                r = {"date": _today(), "success": False, "latency_ms": -1, "via": "canary_promote.py", "status": 0, "error": str(ex_err)[:80]}
            hist = e.setdefault("probe_history", [])
            hist.append(r)
            ok_n += 1 if r["success"] else 0
    print("[probe] 成功 %d / %d" % (ok_n, len(todo)))
    return ok_n


def gate_verdict(entry, stability_days=STABILITY_DAYS, hit_rate=HIT_RATE_THRESHOLD,
                 max_failures=MAX_FAILURES, reject_labels=REJECT_LABELS):
    """三道闸门（方案 §4.1）。返回 (admitted: bool, reason: str|None)。"""
    labels = set(entry.get("labels") or [])
    hit = labels & set(reject_labels)
    if hit:
        return False, "labels 反证: %s" % ",".join(sorted(hit))          # 闸 3（先判：与历史无关的硬反证）
    hist = entry.get("probe_history") or []
    recent = [p for p in hist if p.get("success") is not None][-stability_days:]
    if len(recent) < stability_days:
        return False, "稳定天数不足 (%d/%d)" % (len(recent), stability_days)  # 闸 1
    fails = sum(1 for p in recent if not p["success"])
    if fails > max_failures:
        return False, "近 %d 天失败 %d 次 > 容错 %d" % (stability_days, fails, max_failures)  # 闸 1b
    rate = sum(1 for p in recent if p["success"]) / float(len(recent))
    if rate < hit_rate:
        return False, "命中率 %.0f%% < %.0f%%" % (rate * 100, hit_rate * 100)  # 闸 2
    return True, None


def cmd_promote(pool, dry_run, pool_path=CANARY_POOL):
    entries = pool.get("entries", [])
    promoted, rejected_now, kept = [], [], []
    for e in entries:
        if e.get("admitted"):
            kept.append(e)
            continue
        ok, reason = gate_verdict(e)
        if ok:
            e["admitted"] = True
            e["admit_date"] = _today()
            e["reject_reason"] = None
            promoted.append(e)
        else:
            e["reject_reason"] = reason
            first = (e.get("probe_history") or [{}])[0].get("date") or _today()
            days_in = _days_since(first)
            if days_in >= REJECT_AFTER_DAYS:
                e["rejected_at"] = _today()
                rejected_now.append(e)
            else:
                kept.append(e)
    # 晋升产物：标准上游形态（方案 §3.3 / §4.4）
    up_entries = []
    for e in promoted:
        up_entries.append({
            "name": e.get("title") or e.get("channel_name") or "",
            "url": e["url"],
            "tvg_id": e.get("iptv_channel_id") or "",
            "headers": e.get("headers") or {},
            "quality": e.get("quality"),
            "labels": e.get("labels") or [],
            "source": "iptv-org",
        })
    if not dry_run:
        pool["meta"]["last_promote"] = {
            "at": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "gate_params": {"stability_days": STABILITY_DAYS, "hit_rate_threshold": HIT_RATE_THRESHOLD,
                            "max_failures": MAX_FAILURES, "reject_labels": sorted(REJECT_LABELS),
                            "reject_after_days": REJECT_AFTER_DAYS},
            "promoted": len(promoted), "rejected_out": len(rejected_now), "kept": len(kept),
        }
        if promoted:
            os.makedirs(os.path.dirname(PROMOTED_PATH), exist_ok=True)
            cur = {"generated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"), "upstreams": []}
            if os.path.exists(PROMOTED_PATH):
                try:
                    cur = json.load(open(PROMOTED_PATH, encoding="utf-8"))
                except Exception:
                    pass
            known = {u["url"] for u in cur.get("upstreams", [])}
            for u in up_entries:
                if u["url"] not in known:
                    cur["upstreams"].append(u)
                    known.add(u["url"])
            cur["generated_at"] = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
            tmp = PROMOTED_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=1)
            os.replace(tmp, PROMOTED_PATH)
        if rejected_now:
            os.makedirs(os.path.dirname(REJECTED_PATH), exist_ok=True)
            rej = {"updated": _today(), "entries": []}
            if os.path.exists(REJECTED_PATH):
                try:
                    rej = json.load(open(REJECTED_PATH, encoding="utf-8"))
                except Exception:
                    pass
            known = {x["stream_id"] for x in rej.get("entries", [])}
            for e in rejected_now:
                if e["stream_id"] not in known:
                    rej["entries"].append(e)
            rej["updated"] = _today()
            with open(REJECTED_PATH, "w", encoding="utf-8") as f:
                json.dump(rej, f, ensure_ascii=False, indent=1)
        pool["entries"] = kept + [e for e in promoted]  # 晋升条目留在池内标记 admitted（审计），不再探活
        tmp = pool_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=1)
        os.replace(tmp, pool_path)
    print("[promote] 通过闸门 %d / 淘汰出池 %d（>%d 天未过）/ 继续观测 %d%s"
          % (len(promoted), len(rejected_now), REJECT_AFTER_DAYS, len(kept),
             "（dry-run 未写盘）" if dry_run else ""))
    for e in promoted[:10]:
        print("  + %s %s" % (e.get("title") or e.get("channel_name"), e["url"][:70]))
    return 0


def load_pool():
    if not os.path.exists(CANARY_POOL):
        print("[canary] 池文件不存在 %s，先跑 live_iptvorg_adapter.py daily" % CANARY_POOL)
        return None
    try:
        return json.load(open(CANARY_POOL, encoding="utf-8"))
    except Exception as e:
        print("[canary] 池文件损坏：%s" % e)
        return None


def main():
    ap = argparse.ArgumentParser(description="直播 canary 池准入/晋升（三道闸门）")
    ap.add_argument("--probe", action="store_true", help="对未晋升条目逐日探活（同日重跑幂等跳过）")
    ap.add_argument("--probe-limit", type=int, default=0, help="本轮探活条数上限（0=全部）")
    ap.add_argument("--promote", action="store_true", help="执行三道闸门评估与晋升")
    ap.add_argument("--dry-run", action="store_true", help="只评估输出，不写盘")
    args = ap.parse_args()
    if not args.probe and not args.promote:
        args.probe = args.promote = True  # 默认全流程
    pool = load_pool()
    if pool is None:
        return 1
    if args.probe:
        cmd_probe(pool, args.probe_limit)
    if args.promote:
        # dry-run 探活后不落盘时，评估基于内存历史即可
        rc = cmd_promote(pool, args.dry_run)
        return rc
    if not args.dry_run:
        tmp = CANARY_POOL + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CANARY_POOL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
