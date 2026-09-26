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

_GATE_FILE = os.path.join(ROOT, "rules", "gate_criteria.json")


def _gate_scope():
    """P1-A 门禁口径单一定义：扫描范围以 rules/gate_criteria.json 为准（变更须走质检评审）。
    文件缺失/字段不全时退回内置默认（与本文件历史口径一致）并向 stderr 告警。"""
    default_dirs = ["lives", "stores", "json", "sync", "packs"]
    try:
        g = json.load(open(_GATE_FILE, encoding="utf-8"))
        sc = g["adult_zero_leak"]["scan"]
        top, stf, dirs = sc["top_files"], sc["state_files"], sc["dirs"]
        if top and stf and dirs:
            return list(top), list(stf), list(dirs), None
        return TOP_FILES, STATE_FILES, default_dirs, "gate_criteria 字段不全"
    except Exception as e:  # noqa: BLE001
        return TOP_FILES, STATE_FILES, default_dirs, str(e)


_SITE_NAME_KEYS = ("name",)
_SITE_URL_KEYS = ("api", "url", "jar", "playUrl", "ext")


def _whitelist_res(whitelist_path):
    """读误报白名单（每行一条正则，# 注释）。全部命中须可解释——白名单随仓库提交，
    红线规则变更走质检评审（2026-09-25 质检1号独立验证整改项）。"""
    if not whitelist_path or not os.path.isfile(whitelist_path):
        return []
    res = []
    for ln in open(whitelist_path, encoding="utf-8"):
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            res.append(re.compile(ln, re.IGNORECASE))
    return res


def _scan_string(s, where, path, hits, wl):
    """单字符串值扫描（QC 对齐口径：词/域子串命中即报，不做字段裁剪）。
    URL 形态字符串另跑域名黑名单判定。命中且命中白名单时以 kind=guarded
    显式记录（不静默跳过）——供质检复核白名单合理性；未命中不产生记录。"""
    low = s.lower()
    rule = None
    for kw in la.PORN_KW:
        if kw.lower() in low:
            rule = "porn_kw:%s" % kw[:16]
            break
    if rule is None and "://" in s and la.is_adult_url(s):
        rule = "host_blacklist"
    if rule is None:
        m = la.ADULT_SOURCE_RE.search(s)
        if m:
            rule = "source_pattern:%s" % m.group(0)[:24]
    if rule is None:
        return
    kind = "guarded" if (wl and any(rx.search(s) for rx in wl)) else "word"
    hits.append({"file": path, "where": where, "kind": kind,
                 "value": s[:80], "rule": rule})


def _iter_strings(node, where, path, hits, wl):
    """全字段递归：任意 string 值都扫（含 categories/notes/嵌套 ext），不再限 name/url 子集。"""
    if isinstance(node, str):
        _scan_string(node, where or "$", path, hits, wl)
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str):
                _scan_string(k, where + "/<key:%s>" % k[:24] if len(where) < 120 else where,
                             path, hits, wl)
            _iter_strings(v, (where + "/" + str(k))[:160] if len(where) < 150 else where,
                          path, hits, wl)
    elif isinstance(node, list):
        for i, x in enumerate(node):
            _iter_strings(x, "%s[%d]" % (where, i) if len(where) < 150 else where,
                          path, hits, wl)


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


def scan_json(path, hits, wl=()):
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        hits.append({"file": path, "where": "<json-load>", "err": str(e)[:80]})
        return
    _iter_strings(doc, "", path, hits, wl)


def scan_text(path, hits, re_only=False):
    """文本/类文本扫描。装入时做二进制嗅探（前 8KB 含 NUL 即视为二进制）：
    压缩/加密/图像等二进制字节流在文本正则会随机命中（ADULT_SOURCE_RE/substr），
    造成「门禁扫二进制 zip/image 命中几千条 source_pattern」的伪阳性——本类不属
    文本消费通路内容，二进制结构化扫描由 scan_zip 覆盖，跳过此类以恢复门禁语义
    唯一性（2026-09-25 门禁 vs 合并词表漂移整改）。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8192)
        if b"\x00" in head:
            return
        txt = head + open(path, "rb").read()[8192:] if len(head) == 8192 else head
        txt = txt.decode("utf-8", errors="replace")
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
        # name,url 形式的 txt/m3u（仅当明显可解析为「名,url」时跑 name reason）
        # ——纯 url 行（无逗号）跳过 name 判定，避免 1024/jav 等 url 路径数字被错杀
        parts = ln.split(",", 1)
        nm = parts[0].strip()
        u = parts[1].strip() if len(parts) > 1 else ""
        if ln.endswith("#genre#"):
            nm = ln[:-len("#genre#")].rstrip(",")
        # 名称侧必须非空且不含协议头（防止把裸 URL 误当名称）才跑 name reason
        if nm and not nm.startswith(("http://", "https://", "rtmp://", "rtsp://")):
            ok, rule = _name_reason(nm)
            if ok:
                hits.append({"file": path, "where": "L%d" % i,
                             "kind": "name", "value": nm[:60], "rule": rule})
        if u:
            ok, rule = _url_reason(u)
            if ok:
                hits.append({"file": path, "where": "L%d" % i,
                             "kind": "url", "value": u[:80], "rule": rule})


def scan_zip(path, hits, wl=()):
    """zip 结构化扫描（包内条目语义与磁盘常规文件对齐，2026-09-26）：
      - rules/ 与 state/vocab/ 前缀条目跳过——这两个目录是门禁 adult 词表本体，
        磁盘侧本就不在扫描域（rules/ 显式排除、state/vocab 不入域）；打包进 zip
        不改变其性质，逐字扫描词表只会命中词表自己（205+202 处伪阳性）。
      - json 条目全字段扫描传入白名单 wl——与磁盘 top/dirs 文件同口径：
        「白名单命中不计一票否决」不应因载体是 zip 而失效（ext 密文 blob 的
        mmz/1024 随机子串、manifest sha256 hex 在磁盘侧均 guarded）。"""
    try:
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                nm = info.filename
                if nm.startswith(("rules/", "state/vocab/")):
                    continue
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
                        scan_json_into(doc, os.path.basename(path) + "::" + nm, sub, wl)
                        hits.extend(sub)
    except zipfile.BadZipFile as e:
        hits.append({"file": path, "where": "<zip>", "err": str(e)[:80]})


def scan_json_into(doc, path, hits, wl=()):
    _iter_strings(doc, "", path, hits, wl)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-snapshot", action="store_true")
    ap.add_argument("--report", default=os.path.join("state", "adult_leak_report.json"))
    ap.add_argument("--whitelist", default=os.path.join("state", "adult_leak_whitelist.txt"),
                    help="误报白名单（正则逐行，# 注释；默认 state/adult_leak_whitelist.txt，"
                         "存在才加载。白名单命中以 kind=guarded 显式入报告，供质检复核）")
    args = ap.parse_args()
    os.chdir(ROOT)
    wl = _whitelist_res(args.whitelist)
    hits = []
    top_files, state_files, scan_dirs, gate_err = _gate_scope()
    if gate_err:
        print("[adult-leak] WARN 门禁口径文件不可用，退回内置默认扫描范围：%s" % gate_err,
              file=sys.stderr)

    for f in top_files + state_files:
        if os.path.isfile(f):
            if f.endswith(".json"):
                scan_json(f, hits, wl)
            else:
                scan_text(f, hits, re_only=(f in ("index.html", "README.md")))

    # 2026-09-25 质检整改：json/（解析规则库，曾漏 pornhub.json）与 sync/（飞书线同步
    # 配置，daily-fetch 每日作为上游吸收——此处泄漏等于每日撤销清洗结论）纳入扫描域。
    scanned_zips = set()
    for dirp in scan_dirs:
        if not os.path.isdir(dirp):
            continue
        for dp, _dn, fs in os.walk(dirp):
            for f in fs:
                p = os.path.join(dp, f)
                if f.endswith(".zip"):
                    # 压缩包走结构化扫描（zip 名 + 内嵌 json/txt/m3u/html）；
                    # 不再让 scan_text 把压缩字节当文本扫（会随机命中）。
                    scan_zip(p, hits, wl)
                    scanned_zips.add(os.path.abspath(p))
                elif f.endswith(".json"):
                    scan_json(p, hits, wl)
                else:
                    scan_text(p, hits)

    if os.path.isdir("packs"):
        for f in sorted(os.listdir("packs")):
            if f.endswith(".zip"):
                p = os.path.join("packs", f)
                # gate_criteria dirs 含 packs 时上方已扫过——去重防双扫伪计数
                if os.path.abspath(p) in scanned_zips:
                    continue
                scan_zip(p, hits, wl)

    if args.include_snapshot and os.path.isdir("snapshot"):
        for dp, _dn, fs in os.walk("snapshot"):
            for f in fs:
                p = os.path.join(dp, f)
                if f.endswith(".json"):
                    scan_json(p, hits, wl)
                else:
                    scan_text(p, hits)

    # 2026-09-25 质检整改：白名单命中（kind=guarded）不计入一票否决，
    # 单独计数入报告供质检复核白名单合理性；verdict 只看真实命中。
    real = [h for h in hits if h.get("kind") != "guarded"]
    guarded = [h for h in hits if h.get("kind") == "guarded"]
    report = {
        "verdict": "PASS" if not real else "FAIL",
        "total_hits": len(hits),
        "violation_count": len(real),
        "whitelisted_count": len(guarded),
        "hits": real[:200],
        "whitelisted": guarded[:800],
        "scope": {"top": top_files + state_files, "dirs": scan_dirs,
                  "scope_source": None if gate_err else "rules/gate_criteria.json",
                  "scope_fallback_reason": gate_err,
                  "whitelist": args.whitelist if __import__("os").path.isfile(args.whitelist) else None,
                  "include_snapshot": bool(args.include_snapshot),
                  "excluded": ["adult.json", "adult_live.json", "adult_live_channels/",
                               "rules/", "snapshot/"]},
    }
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    if real:
        print("[adult-leak] FAIL：%d 处命中（一票否决，阻断发布）" % len(real))
        for h in real[:20]:
            rule = h.get("rule") or h.get("kind") or ""
            val = h.get("value") or h.get("err") or ""
            print("  %s %s  rule=%s  value=%s" % (
                h.get("file", "?"), h.get("where", "?"), rule, val[:50]))
        print("白名单拦截 %d 处（guard 记录入报告，待质检复核）" % len(guarded))
        print("报告：%s" % args.report)
        return 2
    print("[adult-leak] PASS：常规产物零泄漏（白名单拦截 %d 处，guard 明细入报告）" % len(guarded))
    print("报告：%s" % args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
