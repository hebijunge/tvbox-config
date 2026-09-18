#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_probe.py — 直播源清洗与真实测活模块（供 fetch_merge.py 复用）。

三级验证：
  L1 URL 清洗  — 剔除本地代理(127.0.0.1/内网)、相对路径、破损双协议 URL、空 URL
  L2 格式验证  — HTTP 拉取，校验 m3u / tvbox txt 直播格式，统计频道数
  L3 流抽样    — 每个直播源抽最多 N 条频道流，Range GET 实测返回是否为有效流内容

返回状态：
  ok          — L2 通过且 L3 至少 1 条流有效
  format_only — L2 通过但 L3 全部无效（保留但降级标注）
  dead        — L2 拉取失败/格式无效
  blocked     — 沙箱网关 502（无法判定，不算死）
"""
import json
import re
import time
import ssl
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "okhttp/3.15"
STREAM_SAMPLE = 5
SOURCE_TIMEOUT = 10
STREAM_TIMEOUT = 6

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

LOCAL_HOST_RE = re.compile(
    r"^https?://(127\.0\.0\.1|localhost|0\.0\.0\.0|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[::1\]|host\.docker)",
    re.I)
DOUBLE_SCHEME_RE = re.compile(r"^(https?://)\1+", re.I)
RELATIVE_RE = re.compile(r"^\.{0,2}/[^/]", re.I)

M3U_URL_RE = re.compile(r"^[A-Za-z][\w\+\-\.]*://\S+$")


def _idna_host(host: str) -> str:
    if host.isascii():
        return host
    labels = []
    for lab in host.split("."):
        labels.append(lab if lab.isascii() else
                      "xn--" + lab.encode("punycode").decode())
    return ".".join(labels)


def _read_capped(r, cap, deadline):
    """限流读取：单次 read 有 socket 超时兜底，总时长受 deadline 墙钟约束。"""
    chunks, total = [], 0
    while total < cap:
        if time.time() > deadline:
            break
        b = r.read(65536)
        if not b:
            break
        chunks.append(b)
        total += len(b)
    return b"".join(chunks)


def http_get(url: str, timeout: int, rng: str = None):
    """返回 (status, headers, body_bytes)；任何异常返回 (0, None, None)。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        **({"Range": rng} if rng else {}),
    })
    deadline = time.time() + timeout
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            body = _read_capped(r, 1 << 20, deadline)
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, dict(e.headers or {}), body
    except Exception:
        return 0, None, None


def is_gateway_blocked(status: int, headers) -> bool:
    if status == 502 and headers:
        server = str(headers.get("Server") or "")
        return "trustlayer" in server.lower()
    return False


def sanitize_live_url(u):
    """L1：返回清洗后的 URL 或 (None, 原因)。"""
    if not isinstance(u, str) or not u.strip():
        return None, "empty"
    u = u.strip()
    if DOUBLE_SCHEME_RE.match(u):
        u = DOUBLE_SCHEME_RE.sub(lambda m: m.group(1), u)
    if LOCAL_HOST_RE.match(u):
        return None, "local_proxy"
    if RELATIVE_RE.match(u) or "://" not in u:
        return None, "relative_path"
    if not u.lower().startswith(("http://", "https://")):
        return None, "bad_scheme"
    # 中文域名 punycode
    m = re.match(r"^(https?://)([^/]+)(/.*)?$", u)
    if m and not m.group(2).isascii():
        try:
            u = m.group(1) + _idna_host(m.group(2)) + (m.group(3) or "")
        except Exception:
            return None, "idna_error"
    return u, None


def parse_channels(text: str):
    """解析 m3u / tvbox txt，返回 (channel_count, sample_stream_urls, groups)。"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    streams, groups = [], set()
    if lines and lines[0].startswith("#EXTM3U"):
        for l in lines[1:]:
            if l.startswith("#EXTINF"):
                m = re.search(r'group-title="([^"]*)"', l)
                if m and m.group(1):
                    groups.add(m.group(1))
            elif l and not l.startswith("#") and M3U_URL_RE.match(l):
                streams.append(l)
    else:
        for l in lines:
            if l.endswith("#genre#"):
                g = l.split(",")[0].strip()
                if g:
                    groups.add(g)
                continue
            if "," in l:
                parts = l.rsplit(",", 1)
                if M3U_URL_RE.match(parts[1].strip()):
                    streams.append(parts[1].strip())
    # 去重抽样，保留中段更有代表性的样本
    uniq = list(dict.fromkeys(streams))
    if len(uniq) > STREAM_SAMPLE:
        step = max(1, len(uniq) // STREAM_SAMPLE)
        picks = [uniq[i * step] for i in range(STREAM_SAMPLE)]
        if uniq[-1] not in picks:
            picks[-1] = uniq[-1]
    else:
        picks = uniq
    return len(streams), picks, groups


BAD_BODY_MARKS = (b"<!DOCTYPE", b"<html", b"<HTML", b"<?xml")


def probe_stream(url: str):
    """单条频道流实测：Range GET，检查非 HTML、非空、内容像流。"""
    status, headers, body = http_get(url, STREAM_TIMEOUT, rng="bytes=0-2047")
    if status == 0 or body is None:
        return False, "no_response"
    if status not in (200, 206):
        return False, "http_%s" % status
    if not body:
        return False, "empty_body"
    if any(body.startswith(m) for m in BAD_BODY_MARKS):
        return False, "html_or_xml_page"
    ctype = str((headers or {}).get("Content-Type") or "").lower()
    if "text/html" in ctype:
        return False, "html_content_type"
    # m3u8 一级索引也有效（TVBox 会继续解析内层）
    return True, "ct:%s" % (ctype or "n/a")


def probe_source(entry: dict):
    """完整测一个直播源条目。返回记录 dict。"""
    name = entry.get("name") or ""
    raw_url = entry.get("url") or ""
    rec = {"name": name, "url_raw": raw_url}
    url, why = sanitize_live_url(raw_url)
    if url is None:
        rec.update(status="dropped", reason=why, channels=0)
        return rec
    rec["url"] = url
    for k in ("epg", "ua", "boot", "timeout", "ratio"):
        if entry.get(k):
            rec[k] = entry[k]
    status, headers, body = http_get(url, SOURCE_TIMEOUT)
    if is_gateway_blocked(status, headers):
        rec.update(status="blocked", reason="sandbox_502", channels=0)
        return rec
    if status != 200 or not body:
        rec.update(status="dead", reason="fetch_%s" % (status or "error"), channels=0)
        return rec
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = body.decode("gbk")
        except Exception:
            rec.update(status="dead", reason="binary_body", channels=0)
            return rec
    n_streams, picks, groups = parse_channels(text)
    if n_streams == 0:
        rec.update(status="dead", reason="no_channels", channels=0)
        return rec
    rec["channels"] = n_streams
    rec["groups"] = sorted(groups)[:8]
    rec["bytes"] = len(body)
    verdicts = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(probe_stream, s): s for s in picks}
        for fut in as_completed(futs):
            ok, why = fut.result()
            verdicts.append({"stream": futs[fut][:120], "ok": ok, "why": why})
    rec["stream_tests"] = verdicts
    ok_n = sum(1 for v in verdicts if v["ok"])
    rec["streams_ok"] = ok_n
    if ok_n > 0:
        rec["status"] = "ok"
    else:
        rec["status"] = "format_only"
        rec["reason"] = "no_valid_stream_in_sample"
    return rec


def probe_all(entries, max_workers=6, log=None):
    """并发测多个直播源条目，返回记录列表（保序）。"""
    import sys
    results = [None] * len(entries)
    done = [0]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(probe_source, e): i for i, e in enumerate(entries)}
        for fut in as_completed(futs):
            rec = fut.result()
            results[futs[fut]] = rec
            done[0] += 1
            print("[%d/%d] %s -> %s ch=%s %s" % (
                done[0], len(entries), rec.get("name", "")[:16], rec["status"],
                rec.get("channels", 0), rec.get("reason", rec.get("url", "")[:40])),
                flush=True)
    return results


def probe_all_resumable(entries, out_path, max_workers=6):
    """断点续测：结果逐条追加 jsonl，重跑时跳过已完成（按 name+url 键）。"""
    import hashlib, os
    def key(rec):
        return hashlib.md5((rec.get("name", "") + "|" + rec.get("url_raw", "")).encode()).hexdigest()
    done = {}
    if os.path.exists(out_path):
        with open(out_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    done[key(r)] = r
    todo = [(i, e) for i, e in enumerate(entries)
            if key({"name": e.get("name") or "", "url_raw": e.get("url") or ""}) not in done]
    print("todo %d / total %d (done %d)" % (len(todo), len(entries), len(done)), flush=True)
    if not todo:
        return [done[key({"name": e.get("name") or "", "url_raw": e.get("url") or ""})] for e in entries]
    results = [None] * len(entries)
    cnt = [0]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(probe_source, e): i for i, e in todo}
        with open(out_path, "a") as out:
            for fut in as_completed(futs):
                rec = fut.result()
                results[futs[fut]] = rec
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                cnt[0] += 1
                print("[%d/%d] %s -> %s ch=%s" % (cnt[0], len(todo), rec.get("name", "")[:14], rec["status"], rec.get("channels", 0)), flush=True)
    # 回填已完成项
    for i, e in enumerate(entries):
        if results[i] is None:
            k = key({"name": e.get("name") or "", "url_raw": e.get("url") or ""})
            results[i] = done.get(k)
    return results


if __name__ == "__main__":
    import sys
    from collections import Counter
    path = sys.argv[1] if len(sys.argv) > 1 else "live.json"
    d = json.load(open(path, encoding="utf-8"))
    entries = d.get("lives") or []
    print("probing %d live entries ..." % len(entries), flush=True)
    recs = probe_all_resumable(entries, "live_probe_results.jsonl", max_workers=6)
    with open("live_checks.json", "w", encoding="utf-8") as f:
        json.dump({"entries": [r for r in recs if r]}, f, ensure_ascii=False, indent=1)
    print(Counter(r["status"] for r in recs if r))
