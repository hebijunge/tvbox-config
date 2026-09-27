#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deps/ 下 JS 依赖静态安全扫描（只报告，不删除）。

背景
----
deps/ 里的 js 全部来自上游第三方仓库，内容不可控。其中可能夹带：
  - 用 ``eval(atob(...))`` 做的混淆载荷；
  - 主动连 websocket 回传数据；
  - 读取 ``localStorage/sessionStorage``（可能含登录态）后外发；
  - 硬编码可疑域名（暗网/已知恶意 C2/短链）；
  - 加密挖矿（WebAssembly/miner 关键字、hashcash/cryptonight 特征）。

TVBox 类客户端会直接执行这些 js，一旦夹带恶意代码，用户设备即被控。本脚本做一层
低成本正则静态扫描，把可疑文件列出来交人工确认——**绝不自动删除**（误删会导致
站点直接加载失败）。

规则
----
每条规则给出 (id, 描述, 正则, 风险等级)。命中即记录到该文件的 findings。
风险等级：high / medium。high 命中的文件整体标为高危。

用法
----
    python scripts/dep_security_scan.py
    python scripts/dep_security_scan.py --deps deps --out state/dep_security_report.json
"""
import argparse
import datetime
import json
import os
import re
import sys
from typing import Dict, List, Tuple

# (规则id, 描述, 正则, 等级)
RULES: List[Tuple[str, str, str, str]] = [
    ("eval_atob", "eval+atob 组合（混淆载荷）",
     r"eval\s*\(\s*atob\s*\(", "high"),
    ("eval_document_write", "document.write 注入脚本",
     r"document\.write\s*\(\s*unescape\s*\(", "medium"),
    ("websocket", "主动建立 WebSocket 连接",
     r"new\s+WebSocket\s*\(", "medium"),
    ("storage_exfil", "读 localStorage 后外发到网络",
     r"(localStorage|sessionStorage)\s*\.\s*(getItem|(get|set)Item)?[\s\S]{0,200}(fetch|XMLHttpRequest|axios|\.post\s*\()",
     "high"),
    ("hardcoded_suspicious_domain", "硬编码可疑/已知恶意域名",
     r"https?://[a-zA-Z0-9.\-]*(?:\.onion|\.i2p|\.tk\b|\.ml\b|\.ga\b|pastebin\.com|ngrok\.io|herokuapp\.com|vercel\.app|netlify\.app|workers\.dev)",
     "medium"),
    ("miner_wasm", "挖矿 WASM / 已知矿池域名特征",
     r"(?:cryptonight|stratum\+tcp|monero\.com|supportxmr\.com|pool\.minexmr\.com|coinhive|deepminer|webminer)",
     "high"),
    ("obfuscator_heap", "javascript-obfuscator 高密度十六进制/数组混淆",
     r"(?:\\x[0-9a-fA-F]{2}){16,}", "medium"),
    ("atob_bulk", "大量 atob/base64 解码后执行",
     r"(?:atob\s*\(|fromCharCode)[\s\S]{0,400}(?:Function\s*\(|eval\s*\()", "high"),
    ("fetch_exfil", "可疑 fetch 外发到非白名单域名",
     r"fetch\s*\(\s*['\"](https?://(?!.*(?:github|gitee|gitlab|tvbox|drpy|127\.0\.0\.1|localhost)))[^'\"]+['\"]",
     "medium"),
]

COMPILED = [(rid, desc, re.compile(pat, re.IGNORECASE), level)
            for rid, desc, pat, level in RULES]

HIGH_RULES = {rid for rid, _, _, lvl in RULES if lvl == "high"}


def scan_file(path: str) -> List[dict]:
    """对单个 .js 文件跑全部规则，返回命中列表。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return []
    hits: List[dict] = []
    for rid, desc, rx, level in COMPILED:
        m = rx.search(content)
        if not m:
            continue
        # 取命中位置前后一小段作为证据
        s = max(0, m.start() - 40)
        e = min(len(content), m.end() + 40)
        evidence = content[s:e].replace("\n", " ")[:160]
        hits.append({"rule": rid, "desc": desc, "level": level, "evidence": evidence})
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="deps/ JS 静态安全扫描（只报告不删除）")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--deps", default="deps")
    ap.add_argument("--out", default="state/dep_security_report.json")
    ap.add_argument("--max-list", type=int, default=50)
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    dep_dir = os.path.join(repo, args.deps)

    findings: Dict[str, List[dict]] = {}
    high_files: List[str] = []
    scanned = 0
    if os.path.isdir(dep_dir):
        for root, _, names in os.walk(dep_dir):
            for n in names:
                if not n.lower().endswith(".js"):
                    continue
                p = os.path.join(root, n)
                scanned += 1
                hits = scan_file(p)
                if hits:
                    rel = os.path.relpath(p, repo).replace("\\", "/")
                    findings[rel] = hits
                    if any(h["rule"] in HIGH_RULES for h in hits):
                        high_files.append(rel)

    doc = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "scanned_js_files": scanned,
        "flagged_files": len(findings),
        "high_risk_files": sorted(set(high_files)),
        "high_risk_count": len(set(high_files)),
        "rules": [{"id": rid, "desc": desc, "level": lvl}
                  for rid, desc, _, lvl in RULES],
        "findings": dict(sorted(findings.items())[:args.max_list]),
        "note": "仅静态正则扫描，可能有误报。高危文件需人工确认，脚本不自动删除。",
    }
    out_path = os.path.join(repo, args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print(f"[sec] 扫描 {scanned} 个 .js 文件")
    print(f"[sec] 命中 {len(findings)} 个文件，其中高危 {len(set(high_files))} 个")
    for hf in sorted(set(high_files))[:10]:
        print(f"  [HIGH] {hf}")
    print(f"[sec] 报告 -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
