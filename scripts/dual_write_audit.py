#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dual_write_audit.py — 双库双写对账（P0-5；P1-C 建议 3 扩展，2026-09-25）。

每日核心产物双写 GitHub（releases + raw）与飞书云盘（按日目录）后，本脚本做
逐文件 sha256 双向对账，产出 exports/dual_write_report_YYYYMMDD.json + 控制台
对账表，进日报。对账失败（哈希不一致/取回失败）exit 2；连续 3 个对账失败日
升级 exit 3（P1-C 建议 3：3 连败才升级，避免单日网络抖动误报）。

对账逻辑：
  1) GitHub 侧基准 = 仓库工作区文件本身（提交前运行时即为待提交内容）；
     --check-raw 时另对 raw.githubusercontent.com HEAD 200 验活。
  2) 飞书侧基准 = --feishu-dir 目录（agent 用 lark-cli 上传后再下载回来的副本，
     下载回路本身就是云盘完整性的实读校验）。
  3) 每文件状态（P1-C 扩展：区分对账失败与取回失败）：
       ok             — sha256 一致
       sha256_mismatch— 两侧文件都在但哈希不一致（真对账缺口）
       fetch_failed   — 飞书副本缺失 / --feishu-dir 缺失（取回失败，非哈希不一致）
       missing_repo   — 仓库侧清单文件缺失
       raw_unreachable— raw 验活网络失败（--check-raw）
  4) 对账清单（P1-C 建议 3）：--preset delivery 按全交付清单驱动，覆盖
     词表 / rules / lives 分组产物 / 核心产物 / 本地包及其包内 manifest；
     本地包 zip 额外做包内 manifest.json 自校验（entry sha256 逐条对）。
     兼容旧用法 --files。
  5) 连续失败日升级：exports/dual_write_history.jsonl 逐日留痕，今天 FAIL 且
     此前已连续 ≥2 个 FAIL 日（合计 3 连败）→ escalated=true、exit 3。

用法：
  python scripts/dual_write_audit.py --preset delivery \
    --feishu-dir .dualcheck/feishu_20260925 [--check-raw] [--out exports/dual_write_report.json]
  # 兼容旧用法：
  python scripts/dual_write_audit.py --files tvbox.json,rules --feishu-dir ...
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime

RAW_BASE = "https://raw.githubusercontent.com/hebijunge/tvbox-config/main/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join("exports", "dual_write_history.jsonl")
ESCALATE_AFTER_FAIL_DAYS = 3

# 词表（事实源，单源）
VOCAB_FILES = [
    "state/vocab/categories.json",
    "state/vocab/normalization.json",
    "state/vocab/normalization.iptvorg_additions.json",
]
# 核心产物（与 daily.yml 提交清单同口径）
CORE_PRODUCTS = ["tvbox.json", "vod.json", "live.json", "short.json",
                 "list.json", "status.json", "checks.json"]
# 本地包
PACK_FILES = ["packs/tvbox-latest.zip"]


def build_delivery_list(root):
    """全交付清单（P1-C 建议 3）：词表 + rules + lives 分组产物 + 核心产物
    + 本地包。存在的才进清单；目录存在但空则不进。"""
    rels = []
    rels += [f for f in VOCAB_FILES if os.path.isfile(os.path.join(root, f))]
    for d, suffix in (("rules", ".json"),):
        dp = os.path.join(root, d)
        if os.path.isdir(dp):
            rels += sorted(os.path.join(d, f).replace(os.sep, "/")
                           for f in os.listdir(dp) if f.endswith(suffix))
    lp = os.path.join(root, "lives", "groups")
    if os.path.isdir(lp):
        rels += sorted(os.path.join("lives", "groups", f).replace(os.sep, "/")
                       for f in os.listdir(lp) if f.endswith(".m3u"))
    rels += [f for f in CORE_PRODUCTS if os.path.isfile(os.path.join(root, f))]
    rels += [f for f in PACK_FILES if os.path.isfile(os.path.join(root, f))]
    return rels


def expand_files(specs, root="."):
    out = []
    for s in specs:
        s = s.rstrip("/")
        p = os.path.join(root, s)
        if os.path.isdir(p):
            for dp, _dn, fs in os.walk(p):
                for f in sorted(fs):
                    out.append(os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/"))
        elif os.path.isfile(p):
            out.append(s)
        else:
            out.append("::__MISSING__::" + s)
    return sorted(set(out))


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_zip_manifest(zp):
    """本地包 manifest 自校验：包内 manifest.json 的 entries 逐条 sha256 对比。
    返回 (n_ok, n_bad, bad_names)。manifest 缺失返回 (0, -1, [])。"""
    try:
        with zipfile.ZipFile(zp) as z:
            if "manifest.json" not in z.namelist():
                return 0, -1, []
            entries = json.loads(z.read("manifest.json").decode("utf-8")).get("entries") or []
            bad = []
            ok = 0
            have = set(z.namelist())
            for e in entries:
                n = e.get("name")
                if n not in have:
                    bad.append(n + " (absent)")
                    continue
                if hashlib.sha256(z.read(n)).hexdigest() != e.get("sha256"):
                    bad.append(n)
                else:
                    ok += 1
            return ok, len(bad), bad
    except Exception as e:  # noqa: BLE001
        return 0, -2, ["zip-open-failed:%s" % str(e)[:60]]


def load_history(path=HISTORY_PATH):
    """读对账历史 [{date,verdict,...}]，坏行跳过。"""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:  # noqa: BLE001
                    continue
    except FileNotFoundError:
        pass
    return rows


def consecutive_fail_days(rows, today):
    """纯决策函数（单测覆盖点）：截至 today 之前（不含 today）连续 FAIL 的天数。
    同日多条记录按最后一条计。today 自身不计（escalate 判定由调用方并入）。"""
    by_date = {}
    for r in rows:
        d = r.get("date")
        if d:
            by_date[d] = r.get("verdict")
    n = 0
    lookback = 0
    try:
        cur = datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        return 0
    from datetime import timedelta
    while lookback < 60:  # 回溯上限：超 60 天无记录视为无连败
        lookback += 1
        cur = cur - timedelta(days=1)
        v = by_date.get(cur.isoformat())
        if v == "FAIL":
            n += 1
        elif v is None:
            continue  # 当日未跑（跳过日）不中断连败计数
        else:
            break
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", default="", help="逗号分隔的文件/目录清单（兼容旧用法）")
    ap.add_argument("--preset", default="", choices=["", "delivery"],
                    help="delivery=全交付清单（词表/rules/lives 分组/核心产物/本地包）")
    ap.add_argument("--feishu-dir", default="", help="飞书上传后下载回的副本目录")
    ap.add_argument("--out", default="")
    ap.add_argument("--check-raw", action="store_true", help="对 raw 通道做 HTTP 200 验活")
    args = ap.parse_args()
    os.chdir(ROOT)

    if args.preset == "delivery":
        files = build_delivery_list(".")
    elif args.files:
        files = expand_files([x for x in args.files.split(",") if x], ".")
    else:
        print("需要 --preset delivery 或 --files", file=sys.stderr)
        return 2

    rows = []
    n_ok = n_mismatch = n_fetch = n_missing = 0
    for rel in files:
        if rel.startswith("::__MISSING__::"):
            rows.append({"file": rel[len("::__MISSING__::"):], "status": "missing_repo"})
            n_missing += 1
            continue
        if not os.path.isfile(rel):
            rows.append({"file": rel, "status": "missing_repo"})
            n_missing += 1
            continue
        h_repo = sha256_file(rel)
        if args.feishu_dir and os.path.isdir(args.feishu_dir):
            fp = os.path.join(args.feishu_dir, rel.replace("/", "_"))
        else:
            fp = None
        if not fp or not os.path.isfile(fp):
            # P1-C：飞书副本取不到 = fetch_failed（与哈希不一致区分开）
            rows.append({"file": rel, "sha256_repo": h_repo, "status": "fetch_failed"})
            n_fetch += 1
            continue
        h_fs = sha256_file(fp)
        status = "ok" if h_repo == h_fs else "sha256_mismatch"
        if status == "ok":
            n_ok += 1
        else:
            n_mismatch += 1
        row = {"file": rel, "sha256_repo": h_repo, "sha256_feishu": h_fs, "status": status}
        if args.check_raw:
            try:
                req = urllib.request.Request(RAW_BASE + urllib.parse.quote(rel), method="HEAD")
                with urllib.request.urlopen(req, timeout=15) as r:
                    row["raw_http"] = r.status
            except Exception as e:  # noqa: BLE001
                row["raw_http"] = "ERR:%s" % str(e)[:60]
                status = "raw_unreachable"
        # 本地包：包内 manifest 自校验（P1-C 建议 3「本地包 manifest」入对账）
        if rel.endswith(".zip"):
            zok, zbad, bad_names = check_zip_manifest(rel)
            row["pack_manifest_ok"] = zok
            row["pack_manifest_bad"] = zbad
            if zbad < 0:
                row["pack_manifest_note"] = (bad_names[0] if bad_names
                                             else "no manifest.json")
            elif zbad:
                row["pack_manifest_names"] = bad_names[:10]
                status = "sha256_mismatch"
        rows.append(row)

    today = datetime.now().strftime("%Y-%m-%d")
    # verdict：哈希不一致 / 清单缺失 / 取回失败任一非零即 FAIL——fetch_failed 也计入
    # 失败日（3 连败升级规则正是为了吸收其网络抖动噪声，单日 FAIL exit 2 不升级）
    verdict = "PASS" if (n_mismatch == 0 and n_missing == 0 and n_fetch == 0) else "FAIL"
    # 3 连败升级：今天 FAIL 且此前已连续 ≥ ESCALATE_AFTER_FAIL_DAYS-1 个 FAIL 日
    streak_before = consecutive_fail_days(load_history(), today)
    escalated = verdict == "FAIL" and streak_before + 1 >= ESCALATE_AFTER_FAIL_DAYS
    report = {"date": today, "github_sha": _git_sha(), "total": len(rows),
              "ok": n_ok, "sha256_mismatch": n_mismatch, "fetch_failed": n_fetch,
              "missing": n_missing, "verdict": verdict,
              "consecutive_fail_days": streak_before + (1 if verdict == "FAIL" else 0),
              "escalated": escalated,
              "escalate_rule": "连续 %d 个对账失败日才升级（P1-C 建议 3）"
                               % ESCALATE_AFTER_FAIL_DAYS,
              "rows": rows}
    outp = args.out or os.path.join("exports", "dual_write_report_%s.json"
                                    % today.replace("-", ""))
    os.makedirs(os.path.dirname(outp) or ".", exist_ok=True)
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    # 历史留痕（升级判定的数据源）
    os.makedirs("exports", exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": today, "verdict": verdict,
                            "sha256_mismatch": n_mismatch, "fetch_failed": n_fetch,
                            "missing": n_missing, "total": len(rows),
                            "escalated": escalated}) + "\n")

    print("| 文件 | GitHub sha256 | 飞书 sha256 | 对账 |")
    print("|---|---|---|---|")
    for r in rows:
        if r["status"] == "ok":
            print("| %s | %s | %s | ✅一致 |" % (r["file"], r.get("sha256_repo", "-")[:16],
                                                r.get("sha256_feishu", "-")[:16]))
        else:
            print("| %s | %s | %s | ❌%s |" % (r["file"], r.get("sha256_repo", "-")[:16],
                                               r.get("sha256_feishu", "-")[:16], r["status"]))
    print("结论：%s（%d 一致 / %d 哈希不一致 / %d 取回失败 / %d 清单缺失）→ %s"
          % (verdict, n_ok, n_mismatch, n_fetch, n_missing, outp))
    if escalated:
        print("⚠️ 升级：已连续 %d 个对账失败日（≥%d），需人工介入"
              % (report["consecutive_fail_days"], ESCALATE_AFTER_FAIL_DAYS))
        return 3
    return 0 if verdict == "PASS" else 2


def _git_sha():
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


if __name__ == "__main__":
    sys.exit(main())
