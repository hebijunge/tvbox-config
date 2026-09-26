#!/usr/bin/env python3
"""直播池死链剔除（频道级探活瘦身）。

背景：daily-fetch 只做采集合并与清洗，不做逐条链路探活；live-speedtest 是
测速排序定位，受 CI 时间预算限制只实测部分链路，均不删除死链——导致央视等
分组里长期滞留大量 502/500 死源（2026-09-26 实测央视组 893 条仅 33.4% 存活）。

本脚本对直播池全部 URL 做频道级探活，仅删除有真死证据的链路：
  dead  = HTTP 404 / 410 / 5xx（服务端明确报错，与探测点无关）
  keep  = 200 / 206 / 3xx / 4xx（含 403/429：WAF 拦截不可判死）/
          连接失败（code=0，与 adult_live_probe 同口径，宁可漏删不误删）

处理文件（txt: tvbox 分组格式；m3u: EXTINF+URL 对）：
  lives/live_verified.txt  live.json「聚合·分类直播」消费
  lives/live_cat_*.txt     分类中间产物
  lives/live_cctv/weishi/gangtai/other.txt  tvbox.json「Guovin·」条目消费
  lives/live_precise/multicast/live.txt
  lives/live_verified.m3u

输出：state/live_pool_prune_report.json
"""
import asyncio
import collections
import json
import os
import sys
import time

import httpx

CONCURRENCY = 64
TIMEOUT = 8
UA = "okhttp/4.9.3"
RANGE = "bytes=0-4095"
DEAD_CODES = {404, 410} | set(range(500, 600))

TXT_FILES = [
    "lives/live_verified.txt",
    "lives/live_cat_央视.txt",
    "lives/live_cat_卫视.txt",
    "lives/live_cat_地方.txt",
    "lives/live_cat_港台.txt",
    "lives/live_cat_直播.txt",
    "lives/live_cat_轮播.txt",
    "lives/live_cat_其他.txt",
    "lives/live_cctv.txt",
    "lives/live_weishi.txt",
    "lives/live_gangtai.txt",
    "lives/live_other.txt",
    "lives/live_precise.txt",
    "lives/live_multicast.txt",
    "lives/live.txt",
]
M3U_FILES = ["lives/live_verified.m3u"]


def is_stream_url(u):
    return u.startswith("http://") or u.startswith("https://")


def load_lines(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()


def collect_urls():
    urls = {}
    for path in TXT_FILES:
        if not os.path.exists(path):
            continue
        for line in load_lines(path):
            if "," in line and "#genre#" not in line:
                u = line.rsplit(",", 1)[-1].strip()
                if is_stream_url(u):
                    urls.setdefault(u, None)
    for path in M3U_FILES:
        if not os.path.exists(path):
            continue
        for line in load_lines(path):
            u = line.strip()
            if is_stream_url(u):
                urls.setdefault(u, None)
    return list(urls)


PROBE_DEADLINE = 12      # 单 URL 硬上限：直播流会持续吐流，httpx 单次读超时永远等不到，必须外层强杀
PROBE_BUDGET = 1500      # 全局探活预算（秒）：到点取消剩余任务，按已探测结果继续剔除


async def probe_one(client, sem, url):
    async with sem:
        try:
            async def _do():
                r = await client.get(url, headers={"Range": RANGE, "User-Agent": UA},
                                     timeout=TIMEOUT, follow_redirects=True)
                return r.status_code
            code = await asyncio.wait_for(_do(), PROBE_DEADLINE)
            return url, code
        except Exception:
            return url, 0


async def probe_all(urls):
    sem = asyncio.Semaphore(CONCURRENCY)
    verdict = {}
    t0 = time.monotonic()
    async with httpx.AsyncClient(http2=False) as client:
        tasks = [asyncio.create_task(probe_one(client, sem, u)) for u in urls]
        done = 0
        for fut in asyncio.as_completed(tasks):
            try:
                url, code = await asyncio.wait_for(
                    fut, PROBE_BUDGET - (time.monotonic() - t0))
            except asyncio.TimeoutError:
                print("BUDGET_EXHAUSTED: 探活预算耗尽，取消剩余 %d 条，未探测链接本轮保留"
                      % (len(urls) - done), flush=True)
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                break
            verdict[url] = code
            done += 1
            if done % 500 == 0:
                print("progress %d/%d" % (done, len(urls)), flush=True)
    return verdict


def guard(verdict):
    """网络级守卫：几乎全部连接失败视为探测环境故障，禁止判死（adult 教训）。"""
    total = len(verdict)
    if not total:
        return False
    zero = sum(1 for c in verdict.values() if c == 0)
    alive = sum(1 for c in verdict.values() if c in (200, 206))
    if total >= 100 and zero > total * 0.9 and alive == 0:
        print("GUARD_ABORT: code=0 占比 %.0f%% 且无存活响应，判定探测环境故障，本轮不剔除"
              % (zero * 100 / total))
        return False
    return True


def prune_txt(path, dead_urls):
    """tvbox 分组格式：剔除死链行，顺带删除清空后的分组头。返回 (removed, lines_before)。"""
    lines = load_lines(path)
    out, removed = [], 0
    cur_header, cur_entries = None, []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if "#genre#" in s:
            if cur_header is not None and cur_entries:
                out.append(cur_header)
                out.extend(cur_entries)
            cur_header, cur_entries = s, []
        elif "," in s:
            u = s.rsplit(",", 1)[-1].strip()
            if u in dead_urls:
                removed += 1
            else:
                cur_entries.append(s)
        else:
            cur_entries.append(s)
    if cur_header is not None and cur_entries:
        out.append(cur_header)
        out.extend(cur_entries)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return removed, len(lines)


def prune_m3u(path, dead_urls):
    """m3u 格式：#EXTINF 行与下一行 URL 成对，死链则整对删除。返回 (removed, lines_before)。"""
    lines = load_lines(path)
    out, removed = [], 0
    i = 0
    while i < len(lines):
        s = lines[i].rstrip("\n")
        if s.startswith("#EXTINF") and i + 1 < len(lines) \
                and is_stream_url(lines[i + 1].strip()):
            url = lines[i + 1].strip()
            if url in dead_urls:
                removed += 1
                i += 2
                continue
            out.append(s)
            out.append(lines[i + 1].rstrip("\n"))
            i += 2
            continue
        out.append(s)
        i += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return removed, len(lines)


def main():
    start = time.time()
    urls = collect_urls()
    print("unique urls: %d" % len(urls), flush=True)
    verdict = asyncio.run(probe_all(urls))
    if not guard(verdict):
        sys.exit(3)

    dead_urls = {u for u, c in verdict.items() if c in DEAD_CODES}
    codes = collections.Counter(verdict.values())
    per_file = {}
    for path in TXT_FILES:
        if not os.path.exists(path):
            continue
        removed, total = prune_txt(path, dead_urls)
        if removed:
            per_file[path] = {"removed": removed, "lines_before": total}
            print("%s: -%d lines" % (path, removed))
    for path in M3U_FILES:
        if not os.path.exists(path):
            continue
        removed, total = prune_m3u(path, dead_urls)
        if removed:
            per_file[path] = {"removed": removed, "lines_before": total}
            print("%s: -%d lines" % (path, removed))

    alive = sum(1 for c in verdict.values() if c in (200, 206))
    report = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S +0000", time.gmtime()),
        "probed": len(verdict),
        "alive": alive,
        "dead": len(dead_urls),
        "kept_unverifiable": len(verdict) - alive - len(dead_urls),
        "alive_rate": round(alive / len(verdict), 4) if verdict else None,
        "codes": {str(k): v for k, v in codes.most_common()},
        "per_file": per_file,
        "removed_total_lines": sum(v["removed"] for v in per_file.values()),
        "dead_sample": sorted(dead_urls)[:50],
        "duration_seconds": round(time.time() - start, 1),
    }
    os.makedirs("state", exist_ok=True)
    with open("state/live_pool_prune_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: report[k] for k in
                      ("probed", "alive", "dead", "kept_unverifiable", "removed_total_lines")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
