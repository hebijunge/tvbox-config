#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""远端 CI 失败自动上报（CI job: ci-triage）。

由 ``.github/workflows/ci-triage.yml`` 在 ``workflow_run`` 事件里调用：受监控的
workflow 以 failure 结束时，抓出失败的 job 与步骤，按「workflow|job|步骤」的哈希
指纹去重开 issue；同一失败再次出现只在原 issue 追加评论，不重复开新的。

默认只试算（dry-run）不写仓库，``--apply`` 才真正建/评 issue —— 与仓内其它一次性
工装一致，避免探针本身把 issue 列表刷脏。

用法
----
    python scripts/ci_triage.py --repo owner/name --run-id 12345          # 试算
    python scripts/ci_triage.py --repo owner/name --run-id 12345 --apply  # 实际写
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

LABEL = "ci-failure"


def sh(cmd, check=True):
    """执行外部命令，返回 stdout；失败时把 stderr 透出来再退出。"""
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()[:600]
        print(f"[ci_triage] 命令失败: {' '.join(cmd[:3])} ... -> {detail}", file=sys.stderr)
        raise SystemExit(r.returncode)
    return r.stdout


def fetch_failed_steps(repo: str, run_id: str) -> list:
    """返回 [(job 名, [失败步骤名, ...]), ...]；job 失败但无步骤标记时给占位名。"""
    # 不用 --paginate + --jq 组合：多页时 jq 会输出串接的多个 JSON 文档，loads 直接崩。
    out = sh(["gh", "api", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"])
    jobs = json.loads(out).get("jobs", [])
    found = []
    for j in jobs:
        if j.get("conclusion") != "failure":
            continue
        steps = [s.get("name", "?") for s in j.get("steps", [])
                 if s.get("conclusion") == "failure"]
        found.append((j.get("name", "?"), steps or ["（job 级失败，无步骤标记）"]))
    return found


def build_body(meta: dict, job: str, step: str, fp: str, followup: bool = False) -> str:
    kind = "追加上报" if followup else "上报"
    lines = [
        f"远端 CI {kind}：**`{meta['workflow']}`** 失败。",
        "",
        f"- 失败 job：`{job}`",
        f"- 失败步骤：`{step}`",
        f"- 运行：{meta['run_url']}（run #{meta['run_number']}，{meta['event']}，"
        f"{meta['created_at']}）",
        f"- 分支：`{meta['branch']}` @ `{meta['sha'][:10] if meta['sha'] else '?'}`",
        "",
        f"指纹 `{fp}` = sha1(workflow|job|步骤) 前 8 位，同一失败再次出现只在本 issue "
        "追加评论，不重复开新 issue。关闭本 issue 即表示接受它继续红。",
    ]
    return "\n".join(lines)


def find_open_issue(repo: str, fp: str):
    """按指纹在 open 的 ci-failure issue 里找既有编号，没有则返回 None。"""
    out = sh(["gh", "issue", "list", "--repo", repo, "--state", "open",
              "--label", LABEL, "--search", f"{fp} in:title",
              "--json", "number,title"])
    items = json.loads(out)
    return items[0]["number"] if items else None


def ensure_label(repo: str) -> None:
    sh(["gh", "label", "create", LABEL, "--repo", repo, "--color", "d73a4a",
        "--description", "远端 CI 失败自动上报"], check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="CI 失败自动开 issue")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--run-id", default=os.environ.get("RUN_ID", ""))
    ap.add_argument("--apply", action="store_true", help="实际建/评 issue，默认只试算")
    args = ap.parse_args()

    if not args.repo or not args.run_id:
        print("[ci_triage] 缺 --repo 或 --run-id", file=sys.stderr)
        return 2

    run_meta = json.loads(sh(["gh", "api", f"repos/{args.repo}/actions/runs/{args.run_id}"]))
    meta = {
        "workflow": run_meta.get("name", "?"),
        "run_number": run_meta.get("run_number", "?"),
        "event": run_meta.get("event", "?"),
        "created_at": run_meta.get("created_at", "?"),
        "run_url": run_meta.get("html_url", ""),
        "branch": run_meta.get("head_branch", "?"),
        "sha": (run_meta.get("head_commit") or {}).get("id", ""),
    }

    failed = fetch_failed_steps(args.repo, args.run_id)
    if not failed:
        print(f"[ci_triage] {meta['workflow']} run#{meta['run_number']} "
              "没有 conclusion=failure 的 job，跳过")
        return 0

    if args.apply:
        ensure_label(args.repo)

    for job, steps in failed:
        for step in steps:
            fp = hashlib.sha1(f"{meta['workflow']}|{job}|{step}".encode()).hexdigest()[:8]
            title = f"[ci-failure] {meta['workflow']} · {job} · {step} ({fp})"
            existing = find_open_issue(args.repo, fp) if args.apply else None
            body = build_body(meta, job, step, fp, followup=bool(existing))
            if not args.apply:
                print(f"[dry-run] 将{'评论 issue #' + str(existing) if existing else '开新 issue'}: {title}")
                continue
            if existing:
                sh(["gh", "issue", "comment", str(existing), "--repo", args.repo, "-b", body])
                print(f"[ci_triage] 已追加评论到 issue #{existing}: {title}")
            else:
                url = sh(["gh", "issue", "create", "--repo", args.repo,
                          "--title", title, "--body", body, "--label", LABEL]).strip()
                print(f"[ci_triage] 已开 issue {url}: {title}")
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
