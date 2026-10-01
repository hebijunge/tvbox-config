#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5g：type 4 推送/解析端点探针（国内本机跑；产物 probe/endpoint_probe.json）。

为什么需要它：main 产物里 type=4 的源有 133 个（网盘推送/搜索、catbox 一类解析端点），
**现有探针一路都不管它们**——5a 的取景是 `type in (0,1) 且 api 以 http 开头`，type 4 天生
进不去；5b 只管 type 3 jar；5c/5e 是 JS；5f 是 py。于是这 133 个站永远记 unknown，
"unknown 是不是测不了"的答案在它们身上确实是"没人测"。

只测端点在不在、有没有在应答，**不测内容能不能播**：
  * 这些端点不是 maccms 采集口，拿 vod_id 当存活判据会把它们全判死（假死）；
  * 反过来，200 + 一个 HTML 落地页也不构成"能用"的证据；
  * 所以只有"应答且给出结构化/非 HTML 内容"才落 degraded，其余一律不夸大。

等级口径（store.classify 里映射）：
  E2 degraded  2xx/3xx 且响应体能解析出**非空 JSON 结构**（dict/list 有内容）——端点确实在出数据
  E1 unknown   端点存在但证据不足：401/403 需鉴权、405/501 方法不符、200 却只回
               HTML 壳/落地页、空结构、一句"参数错误"这类非 JSON 文本
  E0 dead      404/410 路径失效（域名活着、这个口已经撤了）；或域名彻底无解析记录
               ——必须本机 + DoH（阿里 223.5.5.5 / Google）两个出口一致才判死
  E? unknown   超时/连接被拒/连接被断/TLS/5xx；以及解析失败但 DoH 说域还在（环境性）；
               还有 127.0.0.1、内网地址这类"本地端点不适用远端实测"
               ——手机上是用户自己起的助手，PC 测不到不代表死

网络整体故障时不覆写上一轮好数据：远端可测样本里判出等级（E0/E1/E2）的比例低于
ENDPOINT_MIN_VERDICT_RATE（默认 0.3）就拒绝写盘并 exit 1（drpy 沙箱缺失把产物刷成全 D0
的同类事故，这里是同一族防法）。

用法（cwd=仓库根）：
  py -3.12 scripts/probe_endpoints.py
  py -3.12 scripts/probe_endpoints.py --limit 20 --concurrency 8 --out /tmp/ep.json
"""
import argparse
import ipaddress
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
from concurrent import futures as cf

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

DEFAULT_OUT = os.path.join(REPO, "probe", "endpoint_probe.json")
MIN_VERDICT_RATE = float(os.environ.get("ENDPOINT_MIN_VERDICT_RATE", "0.3"))
VERDICT_LEVELS = ("E0", "E1", "E2")          # 真拿到证据的等级（E? 不算）
MAX_BYTES = 60_000                            # 端点应答都不长，超大 body 只取前 60KB

HTML_RX = re.compile(r"^\s*<(!doctype\s+)?html\b", re.I)
JSONISH_RX = re.compile(r"^\s*[\{\[]")


def is_endpoint_site(site):
    """取景：type 4 且 api 是 http(s) URL。

    只认 type==4：这是 TVBox 里"解析/推送"接口的约定类型，与 5a 的 type 0/1 互补，
    两条线合起来才覆盖全部 http 型站点。
    """
    return site.get("type") == 4 and str(site.get("api") or "").lower().startswith(("http://", "https://"))


def local_endpoint(url):
    """是否本地/内网端点：这类不该由 PC 远端实测下结论。"""
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return True
    h = host.lower()
    if h in ("localhost", "") or h.endswith((".local", ".internal")):
        return True
    if h in ("::1",) or h.startswith("127."):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def classify_response(status, ctype, raw):
    """把一次应答折成等级。返回 (level, reason)。"""
    body = raw or b""
    text = None
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            text = body.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = body.decode("utf-8", "replace")
    ct = (ctype or "").lower()
    stripped = text.strip()
    length = len(stripped)

    if status in (404, 410):
        return "E0", "HTTP %s 路径失效" % status
    if status in (401, 403):
        return "E1", "HTTP %s 需鉴权（端点在，但拿不到东西）" % status
    if status in (405, 501):
        return "E1", "HTTP %s 方法不符（路径在，形态不认）" % status
    if 200 <= status < 400:
        # 判据落在"能不能解析出非空结构"上，不落 Content-Type 上：
        # 实测 so.yinpai.xyz 一类回 Content-Type: text/json 的 4 字节 body 其实是中文
        # "参数错误"，按 ct 判会把一句报错当成"端点在工作"（E2）。
        from probe_sites import load_json
        try:
            doc = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            doc = load_json(body) if length else None
        if isinstance(doc, (dict, list)) and len(doc) > 0:
            return "E2", "应答非空 JSON 结构（%d 项/%d 字节）" % (len(doc), length)
        if isinstance(doc, (dict, list)):
            return "E1", "HTTP %s 应答空结构（%s）" % (status, "无数据" if doc == {} or doc == [] else "空对象")
        if "json" in ct or JSONISH_RX.match(stripped):
            return "E1", "HTTP %s 声称 JSON 但无结构（%r）" % (status, stripped[:24])
        if HTML_RX.match(stripped):
            return "E1", "HTTP %s 只有 HTML 壳/落地页，不构成可用证据" % status
        return "E1", "HTTP %s 非 JSON 文本应答（%d 字节，形态不明）" % (status, length)
    if 500 <= status < 600:
        return "E?", "HTTP %s 服务端错误" % status
    return "E?", "HTTP %s 未归类" % status


def get_status(url, timeout, max_bytes=MAX_BYTES):
    """GET 并返回 (status, body, ms, ctype)；4xx/5xx 也算应答（urlopen 会抛 HTTPError）。"""
    from probe_sites import http_get          # 复用统一出口（URL 归一 + gzip + 宽松证书）
    t0 = time.time()
    try:
        status, raw, _ms, ctype = http_get(url, timeout, max_bytes)
        return status, raw, int((time.time() - t0) * 1000), ctype
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(max_bytes) if hasattr(e, "read") else b""
        except Exception:
            raw = b""
        ctype = e.headers.get("Content-Type", "") if e.headers else ""
        return e.code, raw, int((time.time() - t0) * 1000), ctype


def doh_has_record(host, timeout):
    """用 DoH 复核域名到底有没有 A 记录。返回 (verdict, detail)：
    verdict True 有记录 / False 确认没有 / None 无法验证。

    为什么要复核：getaddrinfo 失败有两种完全不同的原因——域真撤了（注册到期、zone 删了），
    和本机/运营商解析出问题。前者对用户就是死站，后者不该拿工装环境冒充站点质量。
    只凭本机一台解析器判死 = 2026-09-29 那次"本地网络误杀 adult.json 104 站"的同款事故。
    所有**有效应答**的出口都说 NOERROR 且无答案才算"确认无记录"；一个有效应答都拿不到则不下结论。
    detail 记下到底哪几个出口应答了——判死的理由要能复盘，不能笼统写"一致确认"。
    """
    endpoints = (("ali", "https://223.5.5.5/resolve?name=%s&type=A"),
                 ("google", "https://dns.google/resolve?name=%s&type=A"))
    from probe_sites import load_json
    responded, empty_only = [], True
    for tag, tpl in endpoints:
        url = tpl % urllib.parse.quote(host)
        try:
            status, raw, _ms, _ct = get_status(url, timeout)
        except Exception as e:
            responded.append("%s:无应答(%s)" % (tag, type(e).__name__))
            continue
        if status != 200:
            responded.append("%s:HTTP%s" % (tag, status))
            continue
        doc = load_json(raw) or {}
        if "Status" not in doc:
            responded.append("%s:响应无Status" % tag)
            continue
        responded.append("%s:NOERROR%s" % (tag, "/有答案" if (doc.get("Answer") or []) else "/空"))
        if any((a.get("data") or "") for a in (doc.get("Answer") or [])):
            return True, " ".join(responded)
    valid = [r for r in responded if "NOERROR" in r]
    if not valid:
        return None, " ".join(responded)
    empty_only = all(r.endswith("/空") for r in valid)
    return (False if empty_only else None), " ".join(responded)


DOH_CACHE = {}
DOH_LOCK = threading.Lock()


def doh_cached(host, timeout):
    """同域多站共用一次复核：catbox.n13.club 一个域就挂着 62 个站。"""
    with DOH_LOCK:
        if host in DOH_CACHE:
            return DOH_CACHE[host]
    pair = doh_has_record(host, timeout)
    with DOH_LOCK:
        DOH_CACHE[host] = pair
    return pair


NXDOMAIN_RX = re.compile(r"getaddrinfo failed|11001|Name or service not known|"
                         r"Temporary failure in name resolution|nodename nor servname", re.I)


def probe_one(site, timeout):
    r = {"key": site.get("key"), "name": (site.get("name") or "")[:24], "kind": "endpoint",
         "api": str(site.get("api") or "")[:160]}
    api = str(site.get("api") or "")
    if local_endpoint(api):
        r.update({"level": "E?", "reason": "本地/内网端点，不适用远端实测（手机上是本机助手）"})
        return r
    try:
        status, body, ms, ctype = get_status(api, timeout)
    except Exception as e:                      # URLError/超时/DNS/TLS/连接被拒
        msg = "%s: %s" % (type(e).__name__, str(e)[:110])
        level, reason = "E?", msg
        if NXDOMAIN_RX.search(msg):
            host = urllib.parse.urlsplit(api).hostname or ""
            verdict, detail = doh_cached(host, timeout)
            if verdict is False:
                level = "E0"
                reason = "域名无解析记录（%s；DoH 复核 %s）" % (host, detail)
            elif verdict is True:
                reason = "本机 DNS 解析失败但 DoH 有记录（%s，环境性，不判死；DoH %s）" % (host, detail)
            else:
                reason = "解析失败且 DoH 无法验证（%s，不判死；DoH %s）" % (host, detail)
        r.update({"level": level, "reason": reason})
        return r
    level, reason = classify_response(status, ctype, body)
    r.update({"level": level, "reason": reason, "status": status, "ms": ms,
              "bytes": len(body or b"")})
    return r


def verdict_rate(results):
    """远端可测样本里真拿到等级（E0/E1/E2）的比例；本地端点不参与，它们本就不该有结论。"""
    remote = [x for x in results if "本地/内网" not in (x.get("reason") or "")]
    if not remote:
        return 1.0
    return sum(1 for x in remote if x.get("level") in VERDICT_LEVELS) / len(remote)


def should_refuse_write(rate, out_path, force, min_rate=MIN_VERDICT_RATE):
    """网络性故障不留痕：判出等级率过低、且上一轮产物还在，就拒绝覆写。

    首次运行（没有旧产物）照写——那时写不写都是 unknown，没有"把好数据刷成坏数据"的风险。
    """
    if force or rate >= min_rate:
        return False
    return os.path.isfile(out_path)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--input", default="tvbox.json")
    ap.add_argument("--out", default=os.path.relpath(DEFAULT_OUT, REPO))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--force", action="store_true", help="跳过写盘保护，照常覆写")
    args = ap.parse_args()

    path = os.path.join(args.repo, args.input)
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    sites = [s for s in (doc.get("sites") or []) if is_endpoint_site(s)]
    if args.limit:
        sites = sites[: args.limit]
    print(f"[5g] type4 端点站 {len(sites)} 个（并发 {args.concurrency}，超时 {args.timeout}s）", flush=True)

    results = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(args.concurrency) as ex:
        futs = {ex.submit(probe_one, s, args.timeout): s for s in sites}
        for fu in cf.as_completed(futs):
            s = futs[fu]
            try:
                results.append(fu.result())
            except Exception as e:
                results.append({"key": s.get("key"), "name": (s.get("name") or "")[:24],
                                "kind": "endpoint", "level": "E?", "reason": type(e).__name__})
    results.sort(key=lambda x: (x.get("key") or ""))

    from collections import Counter
    lv = Counter(x.get("level") for x in results)
    rate = verdict_rate(results)
    print("[5g] 等级分布: %s（%.1fs，有结论率 %.0f%%）"
          % (dict(lv), time.time() - t0, 100 * rate), flush=True)

    out_path = os.path.join(args.repo, args.out)
    if should_refuse_write(rate, out_path, args.force):
        print("[5g] 拒绝写盘：有结论率 %.0f%% 低于 %.0f%%，疑似本机网络故障，"
              "保留上一轮判定（--force 可强行覆写）"
              % (100 * rate, 100 * MIN_VERDICT_RATE), flush=True)
        return 1

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {"total": len(results), "levels": dict(lv),
                    "verdict_rate": round(rate, 3),
                    "note": "type4 推送/解析端点实测：E2=应答有结构化内容(degraded)，"
                            "E0=404/410 路径失效(dead)，E1/E?=形态不符或本机不可达(unknown)；"
                            "不测内容能否播放"},
        "sites": results,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("[5g] 产物 -> %s" % args.out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
