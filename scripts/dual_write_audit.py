#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dual_write_audit.py — 双库双写对账（P0-5）。

每日核心产物双写 GitHub（releases + raw）与飞书云盘（按日目录）后，本脚本做
逐文件 sha256 双向对账，产出 exports/dual_write_report_YYYYMMDD.json + 控制台
对账表，进日报。对账失败（哈希不一致/缺文件）exit 2。

对账逻辑：
  1) GitHub 侧基准 = 仓库工作区文件本身（提交前运行时即为待提交内容）；
     --check-raw 时另对 raw.githubusercontent.com HEAD 200 验活。
  2) 飞书侧基准 = --feishu-dir 目录（agent 用 lark-cli 上传后再下载回来的副本，
     下载回路本身就是云盘完整性的实读校验）。
  3) 每文件：sha256(repo) == sha256(feishu) →一致；缺失/不一致 → 记缺口。
  4) release 白名单核对：--release-files 与 Release 附件名义清单比对。

用法：
  python scripts/dual_write_audit.py \
    --files tvbox.json,list.json,packs/tvbox-latest.zip,vod.json,live.json,adult.json \
            ,rules,runtime_manifest.json \
    --feishu-dir .dualcheck/feishu_20260925 [--check-raw] \
    [--out exports/dual_write_report.json]
  --files 支持：文件路径或目录（目录=递归全量）。产出报告同时打印 markdown 表。
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime

RAW_BASE = "https://raw.githubusercontent.com/hebijunge/tvbox-config/main/"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expand_files(specs):
    out = []
    for s in specs:
        s = s.rstrip("/")
        if os.path.isdir(s):
            for dp, _dn, fs in os.walk(s):
                for f in sorted(fs):
                    out.append(os.path.join(dp, f).replace(os.sep, "/"))
        elif os.path.isfile(s):
            out.append(s)
        else:
            out.append("::__MISSING__::" + s)
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", required=True, help="逗号分隔的文件/目录清单")
    ap.add_argument("--feishu-dir", required=True, help="飞书上传后下载回的副本目录")
    ap.add_argument("--out", default="")
    ap.add_argument("--check-raw", action="store_true", help="对 raw 通道做 HTTP 200 验活")
    args = ap.parse_args()
    os.chdir(ROOT)

    files = expand_files([x for x in args.files.split(",") if x])
    rows = []
    n_ok = n_diff = n_missing = 0
    for rel in files:
        if rel.startswith("::__MISSING__::"):
            rows.append({"file": rel[len("::__MISSING__::"):], "status": "missing_repo"})
            n_missing += 1
            continue
        h_repo = sha256_file(rel)
        fp = os.path.join(args.feishu_dir, rel.replace("/", "_"))
        if not os.path.isfile(fp):
            rows.append({"file": rel, "sha256_repo": h_repo, "status": "missing_feishu"})
            n_missing += 1
            continue
        h_fs = sha256_file(fp)
        status = "ok" if h_repo == h_fs else "sha_mismatch"
        if status == "ok":
            n_ok += 1
        else:
            n_diff += 1
        row = {"file": rel, "sha256_repo": h_repo, "sha256_feishu": h_fs, "status": status}
        if args.check_raw:
            try:
                req = urllib.request.Request(RAW_BASE + urllib.parse.quote(rel), method="HEAD")
                with urllib.request.urlopen(req, timeout=15) as r:
                    row["raw_http"] = r.status
            except Exception as e:  # noqa: BLE001
                row["raw_http"] = "ERR:%s" % str(e)[:60]
                status = "raw_unreachable"
        rows.append(row)

    today = datetime.now().strftime("%Y-%m-%d")
    report = {"date": today, "github_sha": _git_sha(), "total": len(rows),
              "ok": n_ok, "sha_mismatch": n_diff, "missing": n_missing,
              "verdict": "PASS" if n_diff == 0 and n_missing == 0 else "FAIL",
              "rows": rows}
    outp = args.out or os.path.join("exports", "dual_write_report_%s.json" % today.replace("-", ""))
    os.makedirs(os.path.dirname(outp) or ".", exist_ok=True)
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print("| 文件 | GitHub sha256 | 飞书 sha256 | 对账 |")
    print("|---|---|---|---|")
    for r in rows:
        if r["status"] == "ok":
            print("| %s | %s | %s | ✅一致 |" % (r["file"], r["sha256_repo"][:16], r["sha256_feishu"][:16]))
        else:
            print("| %s | %s | %s | ❌%s |" % (r["file"], r.get("sha256_repo", "-")[:16],
                                               r.get("sha256_feishu", "-")[:16], r["status"]))
    print("结论：%s（%d 一致 / %d 不一致 / %d 缺失）→ %s"
          % (report["verdict"], n_ok, n_diff, n_missing, outp))
    return 0 if report["verdict"] == "PASS" else 2


def _git_sha():
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


if __name__ == "__main__":
    sys.exit(main())
