# -*- coding: utf-8 -*-
"""把 csp_jar_scan 的全池类清单合进 probe/csp_probe.json（国内本机跑，紧接 csp_jar_scan）。

用法（cwd=仓库根）：py -3.12 scripts/csp_static_merge.py
环境变量：
  CSP_WORKDIR   同 csp_jar_scan（读 <CSP_WORKDIR>/csp_jar_scan.json）
  CSP_MIN_PARSED_JARS（默认 20）池子里至少解析成功多少个 jar 才采信
  CSP_SCAN_MAX_AGE_DAYS（默认 7）报告时效

三条不越界的规定（都是这一轮踩出来的）：
  * 类在全池搜到 → 不写等级（没测过功能，留给真机工装）；
  * 真机给过 C1-C5 的站，不因为「本地池里没有」被降级——那只说明它自带的 jar 我们
    没读到，不是它死的证据（冲突数会打出来）；
  * 判死前必须确认**该站声明的那个 jar 我们真读到过**（deps 账本能把 url 映射到本地
    文件）。9-30 那版把「某一个 jar 里没有」当成「所有 jar 里没有」，一下造出 824 个
    假 C0；收紧到全池 + 自带 jar 可读之后只剩个位数，这才是可用的口径。
"""
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
WORK = os.environ.get("CSP_WORKDIR") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Temp", "csp-harness")
SCAN = os.path.join(WORK, "csp_jar_scan.json")
MAX_AGE_DAYS = int(os.environ.get("CSP_SCAN_MAX_AGE_DAYS", "7"))
MIN_PARSED_JARS = int(os.environ.get("CSP_MIN_PARSED_JARS", "20"))
JAR_HINT = (".jar", ";md5", ".jpg")


def out(msg):
    print(msg, flush=True)


def bare(u):
    m = re.search(r"(https?://raw\.githubusercontent\.com/\S+?)(;md5;.*)?$", u or "")
    if m:
        return m.group(1)
    p = re.sub(r";md5.*", "", u or "")
    if p.startswith("./"):
        p = p[2:]
    i = p.find("raw.githubusercontent.com")
    return ("https://" + p[i:]) if i >= 0 else p


def norm(p):
    return os.path.relpath(p, os.getcwd()).replace("\\", "/") if p else ""


def site_jar_refs(tv):
    """cls -> 该批站点声明的 jar 引用集合（没声明就落到全局 spider）。"""
    fallback = bare(tv.get("spider") or "")
    refs = {}
    for s in tv.get("sites", []):
        api = str(s.get("api") or "")
        if not api.startswith("csp_"):
            continue
        ext = s.get("ext")
        jar = None
        if isinstance(ext, str) and any(h in ext for h in JAR_HINT):
            jar = ext
        elif isinstance(ext, dict):
            jar = ext.get("url") or ext.get("jar")
        refs.setdefault(api[4:], set()).add(bare(jar or fallback))
    return refs


def jar_local_index(manifest="deps/manifest.json"):
    """jar 引用 → 本地已下载文件（读不到就是没读到，宁可不判死）。"""
    idx = {}
    if os.path.exists(manifest):
        for v in json.load(open(manifest, encoding="utf-8")).values():
            if isinstance(v, dict) and v.get("local") and v.get("url"):
                idx.setdefault(bare(v["url"]), norm(v["local"]))
    return idx


def merge(config="tvbox.json", probe_path="probe/csp_probe.json", manifest="deps/manifest.json"):
    if not os.path.exists(SCAN):
        out(f"没有 {SCAN}——先跑 scripts/csp_jar_scan.py。本次不覆写 {probe_path}。")
        return 2
    rep = json.load(open(SCAN, encoding="utf-8"))
    pool = rep.get("pool", {})
    parsed = int(pool.get("parsed") or 0)
    if parsed < MIN_PARSED_JARS:
        out(f"本轮池子只解析成功 {parsed} 个 jar（门槛 {MIN_PARSED_JARS}），不采信、不写等级。")
        return 3
    if not rep.get("pool_files"):
        out("扫描报告没有 pool_files（旧版报告）——重跑 scripts/csp_jar_scan.py 才能核对自带 jar。")
        return 5
    age = datetime.now() - datetime.strptime(rep["generated_at"], "%Y-%m-%dT%H:%M:%S")
    if age > timedelta(days=MAX_AGE_DAYS):
        out(f"扫描报告已 {age.days} 天前（时效 {MAX_AGE_DAYS} 天），先重跑 csp_jar_scan。")
        return 4

    tv = json.load(open(config, encoding="utf-8"))
    probe = json.load(open(probe_path, encoding="utf-8"))
    by_key = {s.get("key"): s for s in probe.get("sites", [])}
    absent = set(rep.get("absent", []))
    pool_files = set(rep["pool_files"])
    refs, idx = site_jar_refs(tv), jar_local_index(manifest)

    def jar_readable(cls):
        """该站声明的每个 jar 都要能在池里找到本地副本，才有资格被判死。"""
        for ref in refs.get(cls) or {""}:
            local = idx.get(ref) or (norm(ref) if ref in pool_files else "")
            if local not in pool_files:
                return False
        return True

    now = datetime.now().isoformat(timespec="seconds")
    added = conflict = unverifiable = 0
    for s in tv.get("sites", []):
        api = str(s.get("api") or "")
        if not api.startswith("csp_"):
            continue
        cls = api[4:]
        if cls not in absent:
            continue
        key = s.get("key") or s.get("name")
        old = by_key.get(key)
        if old:
            if old.get("level") != "C0":
                conflict += 1           # 真机判过能跑：不动它，只计数给人复核
            continue
        if not jar_readable(cls):
            unverifiable += 1           # 自带的 jar 没读到：证据不足，留 unknown
            continue
        by_key[key] = {"key": key, "name": (s.get("name") or "")[:24], "kind": "csp",
                       "cls": cls, "level": "C0", "ms": None,
                       "flags": {"home": False, "cat": False, "search": False},
                       "evidence": {"static": "class-absent-in-local-jar-pool",
                                    "jars_parsed": parsed, "scanned_at": rep["generated_at"]},
                       "err": "static-c0:pool-absent", "probed_at": now}
        added += 1

    probe["sites"] = list(by_key.values())
    probe["generated_at"] = now
    lv = Counter(x.get("level") for x in probe["sites"])
    probe["summary"] = {"total": len(probe["sites"]), "levels": dict(lv),
                        "static_jars_parsed": parsed, "static_added": added,
                        "note": "root 真机五关 + 静态 C0（类在本机可读 jar 全池里都不存在，"
                                "且该站自带 jar 确实读到过）；重跑见 scripts/csp_jar_scan.py"}
    json.dump(probe, open(probe_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out(f"静态 C0 新增 {added} 站（池内解析 {parsed} 个 jar）；真机结论冲突未降级 {conflict}；"
        f"自带 jar 没读到而不判死 {unverifiable}；csp_probe 总 {len(probe['sites'])}，分布 {dict(lv)}")
    return 0


if __name__ == "__main__":
    if getattr(sys.stdout, "encoding", "").lower().replace("-", "") not in ("utf8", "utf-8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(merge())
