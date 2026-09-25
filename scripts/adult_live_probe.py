#!/usr/bin/env python3
"""adult_live_probe.py — adult 直播池探活瘦身（CI 版）。

目标：adult_live_channels/cat*.txt 全量 URL 探活，原地剔除死链，联动清理
adult_live.json（删除变空的 cat 源、更新 channels 计数）与
adult_live_channels.json（剔除死链频道），最后刷新 adult.m3u。

判活：HTTP Range GET（0-4095），最终 2xx = 活；连接异常 / 5xx 重试一次。
守卫：整体存活率 < 3% 判定为探活环境异常（如 Runner 出网被拦），
      直接退出不写任何文件（exit 2），防止全量误删。

用法：python scripts/adult_live_probe.py [--dry-run]
输出：state/adult_live_probe_report.json
"""
import argparse
import asyncio
import glob
import json
import os
import re
import ssl
import subprocess
import sys
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL_DIR = os.path.join(ROOT, "adult_live_channels")
REPORT = os.path.join(ROOT, "state", "adult_live_probe_report.json")

CONCURRENCY = 96
TIMEOUT = httpx.Timeout(8.0, connect=5.0)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
    "Range": "bytes=0-4095",
}
URL_RE = re.compile(r"https?://\S+")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

MIN_ALIVE_RATE = 0.03


def read_lines(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return [l.rstrip("\n").rstrip("\r") for l in f]


def write_lines(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


async def probe_one(client, sem, url):
    async with sem:
        for attempt in range(2):
            try:
                r = await client.get(url, headers=HEADERS, follow_redirects=True)
                if 200 <= r.status_code < 300:
                    return True, r.status_code
                if r.status_code < 500 and r.status_code != 429:
                    return False, r.status_code  # 4xx 明确死，不重试（429 限流除外）
            except Exception:
                pass
            if attempt == 0:
                await asyncio.sleep(1.0)
        return False, 0


async def probe_all(urls):
    sem = asyncio.Semaphore(CONCURRENCY)
    verdict = {}
    limits = httpx.Limits(max_connections=CONCURRENCY + 16, max_keepalive_connections=CONCURRENCY)
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=CTX, limits=limits) as client:
        CHUNK = CONCURRENCY * 20
        for i in range(0, len(urls), CHUNK):
            batch = urls[i:i + CHUNK]
            t0 = time.monotonic()
            res = await asyncio.gather(*[probe_one(client, sem, u) for u in batch])
            for u, (ok, code) in zip(batch, res):
                verdict[u] = {"ok": ok, "code": code}
            done = min(i + CHUNK, len(urls))
            print("[probe] %d/%d  alive=%d  %.0fs" % (
                done, len(urls), sum(1 for v in verdict.values() if v["ok"]),
                time.monotonic() - t0), flush=True)
    return verdict


def line_alive(line, verdict):
    urls = URL_RE.findall(line)
    if not urls:
        return True, None  # 无 URL 的行（如纯名称）不动
    ok = any(verdict.get(u, {}).get("ok") for u in urls)
    return ok, urls


def slim_cat_file(path, verdict):
    """返回 (原行数, 新行数, 剔除频道行数, 是否整体为空应删除)。"""
    lines = read_lines(path)
    if not any(l.strip() for l in lines):
        return len(lines), 0, 0, True
    out, cur_group, cur_keep = [], None, []
    blocks = []  # [(header_line_or_None, [channel_lines])]
    for l in lines:
        s = l.strip()
        if not s:
            continue
        if s.endswith("#genre#"):
            if cur_group is not None or cur_keep:
                blocks.append((cur_group, cur_keep))
            cur_group, cur_keep = l, []
        else:
            cur_keep.append(l)
    if cur_group is not None or cur_keep:
        blocks.append((cur_group, cur_keep))
    removed = 0
    for header, chans in blocks:
        keep = []
        for c in chans:
            ok, _ = line_alive(c, verdict)
            if ok:
                keep.append(c)
            else:
                removed += 1
        if keep:
            if header:
                out.append(header)
            out.extend(keep)
    new_lines = len(out)
    empty = new_lines == 0
    if not empty:
        write_lines(path, out)
    return len(lines), new_lines, removed, empty


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    t0 = time.monotonic()

    cat_files = sorted(glob.glob(os.path.join(POOL_DIR, "cat*.txt")))
    if not cat_files:
        print("no cat files", flush=True)
        return 2

    # 1) 收集全量唯一 URL
    url_map = {}  # url -> set of file
    for p in cat_files:
        for l in read_lines(p):
            s = l.strip()
            if not s or s.endswith("#genre#"):
                continue
            for u in URL_RE.findall(s):
                url_map.setdefault(u, set()).add(os.path.basename(p))
    urls = sorted(url_map)
    print("[probe] files=%d urls=%d" % (len(cat_files), len(urls)), flush=True)

    # 2) 探活
    verdict = asyncio.run(probe_all(urls))
    alive = sum(1 for v in verdict.values() if v["ok"])
    dead = len(verdict) - alive
    rate = alive / len(verdict) if verdict else 0
    print("[probe] alive=%d dead=%d rate=%.1f%%" % (alive, dead, rate * 100), flush=True)
    if rate < MIN_ALIVE_RATE:
        print("ABORT: alive rate %.1f%% < %.0f%%, probe env abnormal, no writes" % (
            rate * 100, MIN_ALIVE_RATE * 100), flush=True)
        return 2

    # 3) 瘦身 cat 文件
    per_file, removed_files = {}, []
    for p in cat_files:
        fn = os.path.basename(p)
        total, kept, removed, empty = slim_cat_file(p, verdict)
        per_file[fn] = {"before": total, "after": kept, "removed": removed}
        if empty:
            os.remove(p)
            removed_files.append(fn)
        print("[slim] %s %d -> %d (-%d)%s" % (
            fn, total, kept, removed, " [DELETED]" if empty else ""), flush=True)

    # 4) adult_live.json 联动：删空源 + 更新 channels 计数
    live_path = os.path.join(ROOT, "adult_live.json")
    live = json.load(open(live_path, encoding="utf-8"))
    kept_lives, pruned = [], 0
    for entry in live.get("lives", []):
        url = entry.get("url", "")
        m = re.search(r"adult_live_channels/(cat\d+\.txt)", url)
        if m and m.group(1) in removed_files:
            pruned += 1
            continue
        if m:
            fn = m.group(1)
            path = os.path.join(POOL_DIR, fn)
            if "channels" in entry:
                n = 0
                for l in read_lines(path):
                    s = l.strip()
                    if s and not s.endswith("#genre#"):
                        n += 1
                entry["channels"] = n
        kept_lives.append(entry)
    live["lives"] = kept_lives
    if not args.dry_run:
        write_lines(live_path, json.dumps(live, ensure_ascii=False, indent=2).split("\n"))
    print("[live] lives pruned=%d kept=%d" % (pruned, len(kept_lives)), flush=True)

    # 5) adult_live_channels.json 联动：剔除死链频道（仅剔除「已探过且死」的 URL；
    #    未在本池 cat 文件中出现、未探过的 URL 一律保留，防止误删）
    ch_path = os.path.join(ROOT, "adult_live_channels.json")
    ch = json.load(open(ch_path, encoding="utf-8"))
    chans = ch.get("channels", [])

    def chan_alive(c):
        urls = URL_RE.findall(json.dumps(c, ensure_ascii=False))
        if not urls:
            return True
        known = [verdict[u]["ok"] for u in urls if u in verdict]
        return any(known) if known else True

    kept_ch = [c for c in chans if chan_alive(c)]
    ch["channels"] = kept_ch
    if not args.dry_run:
        write_lines(ch_path, json.dumps(ch, ensure_ascii=False, indent=2).split("\n"))
    print("[chan] %d -> %d" % (len(chans), len(kept_ch)), flush=True)

    # 6) 刷新 adult.m3u
    if not args.dry_run:
        try:
            subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_adult_m3u.py")],
                           check=False, capture_output=True)
        except Exception as e:
            print("[m3u] rebuild skipped: %s" % e, flush=True)

    # 7) 报告
    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_s": round(time.monotonic() - t0, 1),
        "files": len(cat_files),
        "urls": len(verdict),
        "alive": alive,
        "dead": dead,
        "alive_rate": round(rate, 4),
        "removed_lines": sum(v["removed"] for v in per_file.values()),
        "removed_files": removed_files,
        "lives_pruned": pruned,
        "channels_json": {"before": len(chans), "after": len(kept_ch)},
        "per_file": per_file,
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    write_lines(REPORT, json.dumps(report, ensure_ascii=False, indent=2).split("\n"))
    print("[done] report -> %s" % REPORT, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
