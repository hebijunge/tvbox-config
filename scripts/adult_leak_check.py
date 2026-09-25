#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adult_leak_check.py — 常规产物 adult 零泄漏一票否决（P0-2 红线门禁）。

扫描全部「常规消费通路」产物，任一命中 adult 特征即整体 FAIL（exit 2），
daily.yml 在提交步之前硬门禁执行（无 continue-on-error）——泄漏即拦截发布。

三重判定与扫描口径同 live_aggregate（单一事实源）：
  - 频道/站点名：is_adult()（词表/番号/括号标/纯数字台位）
  - URL：is_adult_url()（域名黑名单）+ ADULT_SOURCE_RE（整源标记）
  - 文本文件（README/index.html 等）：ADULT_SOURCE_RE 原文命中

扫描范围（lives 分类/主配置/清单/店铺/导航页/本地包/测速快照）：
  tvbox.json vod.json live.json short.json list.json live_channels.json
  lives/**（含 groups/*.m3u）stores/*.json index.html README.md
  packs/*.zip（zip 内文件名 + 内嵌 json/text 配置）
  state/live_checks.json state/live_test_progress.jsonl（新通路抽样）
排除（隔离通道本体与状态归档，不属于「常规文件」）：
  adult.json adult_live.json adult_live_channels/** rules/（adult 词表本体）
  snapshot/**（历史快照存档，逐日只增不改，非消费通路——泄漏治理面向产出侧，
  历史快照不回改；如需审计可加 --include-snapshot）

产出：state/adult_leak_report.json（逐文件命中明细 + 结论），日报可引用。
用法：python scripts/adult_leak_check.py [--include-snapshot] [--report state/adult_leak_report.json]
"""
import argparse
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import live_aggregate as la  # noqa: E402

TOP_FILES = ["tvbox.json", "vod.json", "live.json", "short.json", "list.json",
             "live_channels.json", "index.html", "README.md"]
STATE_FILES = ["state/live_checks.json", "state/live_check_meta.json",
               "state/live_test_progress.jsonl"]

_SITE_NAME_KEYS = ("name",)
_SITE_URL_KEYS = ("api", "url", "jar", "playUrl", "ext")


def _iter_site_fields(obj):
    """递归产出 (name, url) 字段对：dict 中 name 键 + 各 URL 键。"""
    if isinstance(obj, dict):
        names = [v for k, v in obj.items() if k in _SITE_NAME_KEYS and isinstance(v, str)]
        urls = [v for k, v in obj.items() if k in _SITE_URL_KEYS and isinstance(v, str)]
        for n in names:
            for u in urls or [""]:
                yield n, u
        for v in obj.values():
            yield from _iter_site_fields(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _iter_site_fields(x)


def _name_reason(n):
    """返回 (matched_bool, rule_label)；rule_label 仅在 matched 时有意义。"""
    return la.is_adult(n), la.adult_rule_of(n)


def _url_reason(u):
    if not u:
        return False, ""
    if la.is_adult_url(u):
        return True, "host_blacklist"
    m = la.ADULT_SOURCE_RE.search(u)
    if m:
        return True, "source_pattern:%s" % m.group(0)[:32]
    return False, ""


def scan_json(path, hits):
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        hits.append({"file": path, "where": "<json-load>", "err": str(e)[:80]})
        return
    stack = [(doc, "")]
    while stack:
        node, where = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _SITE_NAME_KEYS and isinstance(v, str):
                    ok, rule = _name_reason(v)
                    if ok:
                        hits.append({"file": path, "where": where + "/" + k,
                                     "kind": "name", "value": v[:60], "rule": rule})
                elif k in _SITE_URL_KEYS and isinstance(v, str):
                    ok, rule = _url_reason(v)
                    if ok:
                        hits.append({"file": path, "where": where + "/" + k,
                                     "kind": "url", "value": v[:80], "rule": rule})
                if isinstance(v, (dict, list)):
                    stack.append((v, where + "/" + str(k)))
        elif isinstance(node, list):
            for i, x in enumerate(node):
                if isinstance(x, (dict, list)):
                    stack.append((x, where + "/%d" % i))


def scan_text(path, hits, re_only=False):
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        hits.append({"file": path, "where": "<read>", "err": str(e)[:80]})
        return
    for m in la.ADULT_SOURCE_RE.finditer(txt):
        s = max(0, m.start() - 40)
        hits.append({"file": path, "where": "@%d" % m.start(),
                     "kind": "text", "value": txt[s:m.end() + 40].replace("\n", " "),
                     "rule": "source_pattern"})
    if re_only:
        return
    # 行级 name/url 扫描（txt/m3u 格式：name,url 或 #EXTINF 行）
    for i, ln in enumerate(txt.splitlines(), 1):
        ln = ln.strip()
        if not ln or ln.startswith("#EXTM3U"):
            continue
        if ln.startswith("#EXTINF"):
            nm = ln.rsplit(",", 1)[-1].strip()
            ok, rule = _name_reason(nm)
            if ok:
                hits.append({"file": path, "where": "L%d" % i,
                             "kind": "name", "value": nm[:60], "rule": rule})
            mu = re.search(r"https?://\S+", ln)
            if mu:
                ok, rule = _url_reason(mu.group(0))
                if ok:
                    hits.append({"file": path, "where": "L%d" % i,
                                 "kind": "url", "value": mu.group(0)[:80], "rule": rule})
            continue
        parts = ln.split(",", 1)
        nm = parts[0].strip()
        u = parts[1].strip() if len(parts) > 1 else ""
        if ln.endswith("#genre#"):
            nm = ln[:-len("#genre#")].rstrip(",")
        if nm:
            ok, rule = _name_reason(nm)
            if ok:
                hits.append({"file": path, "where": "L%d" % i,
                             "kind": "name", "value": nm[:60], "rule": rule})
        if u:
            ok, rule = _url_reason(u)
            if ok:
                hits.append({"file": path, "where": "L%d" % i,
                             "kind": "url", "value": u[:80], "rule": rule})


def scan_zip(path, hits):
    try:
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                nm = info.filename
                if la.ADULT_SOURCE_RE.search(nm) or la.is_adult(os.path.basename(nm)):
                    hits.append({"file": path, "where": "zip-name",
                                 "kind": "name", "value": nm,
                                 "rule": la.adult_rule_of(os.path.basename(nm)) or "source_pattern"})
                if nm.lower().endswith((".json", ".txt", ".m3u", ".html")):
                    try:
                        txt = z.read(info).decode("utf-8", errors="replace")
                    except Exception:  # noqa: BLE001
                        continue
                    for m in la.ADULT_SOURCE_RE.finditer(txt):
                        hits.append({"file": path, "where": "zip:%s@%d" % (nm, m.start()),
                                     "kind": "text", "value": m.group(0)[:60],
                                     "rule": "source_pattern"})
                    if nm.lower().endswith(".json"):
                        try:
                            doc = json.loads(txt)
                        except Exception:  # noqa: BLE001
                            continue
                        sub = []
                        scan_json_into(doc, os.path.basename(path) + "::" + nm, sub)
                        hits.extend(sub)
    except zipfile.BadZipFile as e:
        hits.append({"file": path, "where": "<zip>", "err": str(e)[:80]})


def scan_json_into(doc, path, hits):
    stack = [(doc, "")]
    while stack:
        node, where = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _SITE_NAME_KEYS and isinstance(v, str):
                    ok, rule = _name_reason(v)
                    if ok:
                        hits.append({"file": path, "where": where + "/" + k,
                                     "kind": "name", "value": v[:60], "rule": rule})
                elif k in _SITE_URL_KEYS and isinstance(v, str):
                    ok, rule = _url_reason(v)
                    if ok:
                        hits.append({"file": path, "where": where + "/" + k,
                                     "kind": "url", "value": v[:80], "rule": rule})
                if isinstance(v, (dict, list)):
                    stack.append((v, where + "/" + str(k)))
        elif isinstance(node, list):
            for i, x in enumerate(node):
                if isinstance(x, (dict, list)):
                    stack.append((x, where + "/%d" % i))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-snapshot", action="store_true")
    ap.add_argument("--report", default=os.path.join("state", "adult_leak_report.json"))
    args = ap.parse_args()
    os.chdir(ROOT)
    hits = []

    for f in TOP_FILES + STATE_FILES:
        if os.path.isfile(f):
            if f.endswith(".json"):
                scan_json(f, hits)
            else:
                scan_text(f, hits, re_only=(f in ("index.html", "README.md")))

    for dirp in ("lives", "stores"):
        if not os.path.isdir(dirp):
            continue
        for dp, _dn, fs in os.walk(dirp):
            for f in fs:
                p = os.path.join(dp, f)
                if f.endswith(".json"):
                    scan_json(p, hits)
                else:
                    scan_text(p, hits)

    if os.path.isdir("packs"):
        for f in sorted(os.listdir("packs")):
            if f.endswith(".zip"):
                scan_zip(os.path.join("packs", f), hits)

    if args.include_snapshot and os.path.isdir("snapshot"):
        for dp, _dn, fs in os.walk("snapshot"):
            for f in fs:
                p = os.path.join(dp, f)
                if f.endswith(".json"):
                    scan_json(p, hits)
                else:
                    scan_text(p, hits)

    report = {
        "verdict": "PASS" if not hits else "FAIL",
        "total_hits": len(hits),
        "hits": hits[:200],
        "scope": {"top": TOP_FILES + STATE_FILES, "dirs": ["lives", "stores", "packs"],
                  "include_snapshot": bool(args.include_snapshot),
                  "excluded": ["adult.json", "adult_live.json", "adult_live_channels/",
                               "rules/", "snapshot/"]},
    }
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    if hits:
        print("[adult-leak] FAIL：%d 处命中（一票否决，阻断发布）" % len(hits))
        for h in hits[:20]:
            rule = h.get("rule") or h.get("kind") or ""
            val = h.get("value") or h.get("err") or ""
            print("  %s %s  rule=%s  value=%s" % (
                h.get("file", "?"), h.get("where", "?"), rule, val[:50]))
        print("报告：%s" % args.report)
        return 2
    print("[adult-leak] PASS：常规产物零泄漏（%d 文件域扫描通过）" % (
        len(TOP_FILES) + len(STATE_FILES) + 2))
    print("报告：%s" % args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
