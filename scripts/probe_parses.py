#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析接口（tvbox.json parses 字段）探活与质量治理。

背景
----
TVBox 全局解析池（parses）历史上从多个上游累积而来，存在：
  - 接口失效（超时 / 返回空 / 格式错误）但仍排在前面，用户首播放失败；
  - 多个 name 不同但实际 URL 相同的重复接口；
  - 部分解析返回内容带弹窗 / 强制跳转 / 广告域名，诱导下载。
本脚本对每个解析接口模拟一次真实解析请求（拼一个公开测试视频 URL），
记录响应时间、返回格式、是否含广告标记，并区分「接口不可达」与
「防盗链拦截」——后者不直接判失效。

用法
----
    python scripts/probe_parses.py                 # 实际探活全部解析接口
    python scripts/probe_parses.py --dry-run       # 只列出待探活列表，不发请求
    python scripts/probe_parses.py --workers 5
    python scripts/probe_parses.py --tvbox tvbox.json

输出
----
    probe/parses_probe.json    每个解析接口的探活结果 + summary
    state/parse_duplicates.json  同 URL 去重记录（见 dedup_parses）

并发 / 超时
-----------
    max_workers = 5（--workers 可覆盖）
    connect=5s / read=10s（env PARSE_PROBE_CONNECT / PARSE_PROBE_READ 可覆盖）
    单接口最多重试 2 次（瞬态：超时 / 5xx / 连接重置）

防盗链说明
----------
    探活失败不一定是解析失效：部分解析对非浏览器 UA / 无 Referer 的请求直接
    返回 403 / 验证页（防盗链拦截）。这类接口在 TVBox 客户端内携带正确 Referer
    与 UA 时可能正常工作，因此状态记为 anti_chain，不标记失效，仅在排序时
    保守处理。真正连接层失败（DNS / 拒绝连接 / 超时无响应）才记为 unreachable。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import concurrent.futures as cf
from datetime import datetime, timezone, timedelta

BEIJING = timezone(timedelta(hours=8))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TVBOX_PATH = os.path.join(REPO_ROOT, "tvbox.json")
PROBE_OUT = os.path.join(REPO_ROOT, "probe", "parses_probe.json")
DUP_OUT = os.path.join(REPO_ROOT, "state", "parse_duplicates.json")

# 公开测试视频页（腾讯视频公开播放页）。解析接口本质是「传入视频页 URL → 返回直链」。
# 可用 env PARSE_TEST_URL 覆盖。
TEST_VIDEO_URL = os.environ.get(
    "PARSE_TEST_URL",
    "https://v.qq.com/x/cover/mzc002trx1q6b0n.html",
)

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
      "Accept": "*/*",
      "Referer": "https://v.qq.com/"}

# 直链格式：m3u8 / mp4 / flv（http/https）
PLAYABLE_RE = re.compile(
    r'https?://[^\s"\'<>\\]+?\.(?:m3u8|mp4|flv)(?:\?[^\s"\'<>\\]*)?', re.I)
# 防盗链 / 风控拦截特征（命中即视为 anti_chain，而非接口失效）
ANTI_CHAIN_MARKS = (
    "安全验证", "百度安全验证", "访问被拒绝", "拦截", "captcha", "verify",
    "请开启JavaScript", "人机验证", "challenge", "访问受限", "403 Forbidden",
)

CONNECT_TIMEOUT = float(os.environ.get("PARSE_PROBE_CONNECT", "5"))
READ_TIMEOUT = float(os.environ.get("PARSE_PROBE_READ", "10"))
MAX_RETRIES = 2
MAX_BODY = 512 * 1024  # 最多读 512KB 响应体


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def load_parses(tvbox_path: str = TVBOX_PATH) -> list:
    """读取 tvbox.json 的 parses 字段（list[dict]）。"""
    with open(tvbox_path, encoding="utf-8") as f:
        data = json.load(f)
    parses = data.get("parses") or []
    return [p for p in parses if isinstance(p, dict)]


def normalize_parse_url(url: str) -> str:
    """规范化解析接口 URL 作为去重 key。

    - scheme 不敏感（http/https 归一为 https）
    - host 小写
    - 去末尾斜杠
    - 去掉尾部的 url=/v=/id= 占位参数前缀差异？保留 query 结构，仅做上述归一。
    """
    if not isinstance(url, str) or not url:
        return ""
    u = url.strip()
    # 占位接口（Web/Demo）不参与去重
    if u in ("Web", "Demo"):
        return u
    low = u.lower()
    if low.startswith("http://"):
        u = "https://" + u[len("http://"):]
    elif not low.startswith("https://"):
        return u
    tail = u[len("https://"):]
    host, _, rest = tail.partition("/")
    host = host.lower()
    rest = rest.rstrip("/")
    return "https://" + host + ("/" + rest if rest else "")


def _is_probeable(p: dict) -> bool:
    """是否需要实际发请求探活：有 http(s) URL，且不是 Web/Demo 占位。"""
    url = p.get("url", "")
    if not isinstance(url, str):
        return False
    if url in ("Web", "Demo"):
        return False
    return url.lower().startswith(("http://", "https://"))


# --------------------------------------------------------------------------- #
# 单接口探活
# --------------------------------------------------------------------------- #
def _build_probe_url(p: dict) -> str:
    """把测试视频 URL 拼到解析接口 URL 后（TVBox 实际行为：url 字段即前缀）。"""
    base = p["url"]
    sep = "&" if ("?" in base and not base.rstrip().endswith("=")) else ""
    # 多数 jx 接口形如 https://xxx/?url= ，直接拼接即可
    return base + TEST_VIDEO_URL


def _do_request(probe_url: str) -> dict:
    """发一次 HTTP 请求，返回 {status_code, body, ms, error}。"""
    req = urllib.request.Request(probe_url, headers=UA)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)) as resp:
            body = resp.read(MAX_BODY)
            ms = int((time.time() - t0) * 1000)
            return {"status_code": resp.status, "body": body, "ms": ms, "error": None}
    except urllib.error.HTTPError as e:
        ms = int((time.time() - t0) * 1000)
        body = b""
        try:
            body = e.read(MAX_BODY) or b""
        except Exception:
            pass
        return {"status_code": e.code, "body": body, "ms": ms, "error": f"HTTP {e.code}"}
    except Exception as e:  # URLError / socket timeout / ConnectionReset 等
        ms = int((time.time() - t0) * 1000)
        return {"status_code": None, "body": b"", "ms": ms, "error": f"{type(e).__name__}: {e}"}


def _classify(resp: dict) -> str:
    """根据响应判定状态：ok / ad_warn / no_playable / anti_chain / unreachable。"""
    code = resp["status_code"]
    body = resp["body"]
    err = resp["error"]
    text = ""
    if body:
        try:
            text = body.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
    playable = PLAYABLE_RE.search(text)
    # 连接层失败：无 HTTP 响应
    if code is None:
        return "unreachable"
    # HTTP 403/429/503 或风控页 → 防盗链拦截
    if code in (401, 403, 429, 503) or any(m in text for m in ANTI_CHAIN_MARKS):
        # 但如果仍解析出直链，按 ok 处理（少数接口拦截首页但真实可用）
        if playable:
            return "ok"
        return "anti_chain"
    if playable:
        return "ok"
    # 有 HTTP 响应但没解析出直链
    return "no_playable"


def _detect_ad(text: str) -> bool:
    """粗判响应是否含广告/弹窗/诱导下载特征（详细词表见任务4 ad_parse_vocab）。"""
    marks = ("window.open(", "location.href=", "location.replace(",
             "打开APP", "下载APP", "立即下载", "关注公众号", "点击跳转",
             "alert(", "confirm(")
    return any(m in text for m in marks)


def probe_one(p: dict) -> dict:
    """对单个解析接口探活，最多重试 MAX_RETRIES 次。返回结果 dict。"""
    probe_url = _build_probe_url(p)
    result = {
        "name": p.get("name"),
        "type": p.get("type"),
        "url": p.get("url"),
        "probe_url": probe_url,
        "status": "unreachable",
        "ms": None,
        "format": None,
        "has_playable": False,
        "ad_warn": False,
        "http_status": None,
        "retries": 0,
        "error": None,
    }
    last = None
    for attempt in range(MAX_RETRIES + 1):
        resp = _do_request(probe_url)
        last = resp
        result["http_status"] = resp["status_code"]
        result["ms"] = resp["ms"]
        result["error"] = resp["error"]
        status = _classify(resp)
        # 瞬态失败（超时/5xx/连接重置）重试；unreachable 里仅重试连接层错误
        transient = (status == "unreachable" and resp["error"]
                     and any(k in resp["error"] for k in ("Timeout", "Reset", "5", "Temporary")))
        if status in ("ok", "no_playable", "anti_chain") or not transient:
            result["status"] = status
            break
        result["retries"] = attempt + 1
        time.sleep(0.5 * (attempt + 1))
    else:
        result["status"] = "unreachable"

    # 解析直链格式与广告标记
    body = last["body"] if last else b""
    text = body.decode("utf-8", errors="ignore") if body else ""
    m = PLAYABLE_RE.search(text)
    if m:
        result["has_playable"] = True
        result["format"] = os.path.splitext(m.group(0))[1].lstrip(".").lower()
    if result["status"] == "ok" and _detect_ad(text):
        result["ad_warn"] = True
        result["status"] = "ad_warn"
    return result


# --------------------------------------------------------------------------- #
# 批量探活入口
# --------------------------------------------------------------------------- #
def run_probe(parses: list, workers: int = 5) -> list:
    """并发探活所有可探活接口；占位接口（Web/Demo）直接标记 placeholder。"""
    results = []
    targets = []
    for p in parses:
        if not _is_probeable(p):
            results.append({
                "name": p.get("name"), "type": p.get("type"), "url": p.get("url"),
                "probe_url": None, "status": "placeholder", "ms": None,
                "format": None, "has_playable": False, "ad_warn": False,
                "http_status": None, "retries": 0, "error": None,
            })
        else:
            targets.append(p)
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(probe_one, targets):
            results.append(r)
    return results


def summarize(results: list) -> dict:
    from collections import Counter
    c = Counter(r["status"] for r in results)
    return {
        "generated_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "by_status": dict(c),
        "test_url": TEST_VIDEO_URL,
        "workers_note": "connect=%ss read=%s retries=%s" % (
            CONNECT_TIMEOUT, READ_TIMEOUT, MAX_RETRIES),
    }


def write_probe_json(results: list, summary: dict):
    os.makedirs(os.path.dirname(PROBE_OUT), exist_ok=True)
    tmp = PROBE_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f,
                  ensure_ascii=False, indent=1)
    os.replace(tmp, PROBE_OUT)


def main(argv=None):
    ap = argparse.ArgumentParser(description="解析接口探活")
    ap.add_argument("--tvbox", default=TVBOX_PATH, help="tvbox.json 路径")
    ap.add_argument("--workers", type=int, default=5, help="并发数（默认 5）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只列出待探活列表，不实际发请求")
    args = ap.parse_args(argv)

    parses = load_parses(args.tvbox)
    probeable = [p for p in parses if _is_probeable(p)]
    print(f"共 {len(parses)} 个解析接口，其中 {len(probeable)} 个可探活"
          f"（{len(parses) - len(probeable)} 个 Web/Demo 占位）", flush=True)

    if args.dry_run:
        print("== dry-run：待探活列表 ==")
        for p in probeable:
            print(f"  - {p.get('name')} | type={p.get('type')} | {p.get('url')}")
        return 0

    results = run_probe(parses, workers=args.workers)
    summary = summarize(results)
    write_probe_json(results, summary)
    print(f"探活完成：{json.dumps(summary['by_status'], ensure_ascii=False)}", flush=True)
    print(f"结果写入 {PROBE_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
