#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键完整跑通全链路（本地复现 daily.yml 的七阶段编排）。

为什么要有它
------------
CI 上的流程拆在 workflow 的多个 step 里，本地想"从头到尾跑一遍"只能手动敲一长串命令，
容易漏步骤、漏环境变量（比如 EXTRA_UPSTREAMS）。本脚本与 daily.yml 严格对齐，
是本地验证全链路的一键入口。

阶段与失败策略（与 daily.yml 一致）
------------------------------------
  1. 镜像测速择优           continue-on-error
  2. 探针实测（吃上一轮产物） continue-on-error
  3. drpy 沙箱五关实测       continue-on-error
  4. 全网发现（六路）        continue-on-error
  5. 候选评估 + canary 收编  continue-on-error
  6. 拉取合并（必须成功）    失败则中止
  7. 入库 → 导出 → 日报/审计 continue-on-error

日志：logs/run_all_<时间>.log（logs/ 不入库）
用法：python scripts/run_all.py [--skip-drpy] [--skip-probes]
"""
import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
PY = sys.executable or "python"

STAGES = [
    ("1 镜像测速择优", ["scripts/mirror_probe.py"], True, {}),
    ("2a 探针: HTTP L1-L3", ["scripts/probe_sites.py", "--only", "http", "--concurrency", "20"], True, {}),
    ("2b 探针: type3 连通性", ["scripts/probe_spiders.py", "--concurrency", "20"], True, {}),
    ("2c 探针: JS 分类页", ["scripts/probe_js.py", "--concurrency", "20"], True, {}),
    ("2d 同库镜像去重", ["scripts/dedup_mirrors.py"], True, {}),
    ("3 drpy 沙箱五关", ["scripts/drpy_probe.py", "--workers", "5"], True, {}),
    ("4 全网发现(六路)", ["scripts/discover_upstreams.py", "--max-repos", "15", "--pages", "2"], True,
     {"GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "")}),
    ("5 候选评估+canary收编", ["scripts/evaluate_candidates.py", "--min-unique", "3", "--write-canary"], True, {}),
    ("6 拉取合并(必须成功)", ["scripts/fetch_merge.py"], False,
     {"EXTRA_UPSTREAMS": "1", "CONCURRENCY": "24"}),
    ("7a 入库(接口/直播/检测/依赖)", ["scripts/store.py", "--ingest-sites", "tvbox.json",
                                    "--ingest-lives", "tvbox.json", "--probe-lives",
                                    "--ingest-probes", "probe/sites_probe.json",
                                    "probe/spider_probe.json", "probe/js_probe.json",
                                    "probe/csp_probe.json", "probe/drpy_probe.json",
                                    "--prune", "--stats"], True, {}),
    ("7b 导出清单", ["scripts/export_healthy.py"], True, {}),
    ("7c 健康日报", ["scripts/health_report.py"], True, {}),
    ("7d 依赖审计", ["scripts/dep_audit.py"], True, {}),
    ("8 采集入口可达性探测", ["scripts/probe_sources.py", "--concurrency", "20"], True, {}),
    ("9 本地接口包(离线zip)", ["scripts/pack_local.py"], True, {}),
]


def log(f, msg):
    line = f"[run_all {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    f.write(line + "\n")
    f.flush()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-drpy", action="store_true")
    ap.add_argument("--skip-probes", action="store_true")
    ap.add_argument("--from", dest="from_stage", default="1",
                    help="从第几阶段开始跑（阶段序号，如 --from 6 只重跑合并及之后）")
    args = ap.parse_args()

    os.makedirs(os.path.join(REPO, "logs"), exist_ok=True)
    log_path = os.path.join(REPO, "logs",
                            f"run_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    f = open(log_path, "w", encoding="utf-8")
    log(f, f"全链路开始，日志 -> {os.path.relpath(log_path, REPO)}")

    results = []
    for name, cmd, cont, extra_env in STAGES:
        # --from N：从指定序号的阶段开始（前面的阶段产物视为新鲜，直接复用）。
        # 阶段名形如 "2a 探针..."，序号要取前导数字（int("2a") 会抛 ValueError 导致失效）
        m = re.match(r"\d+", name)
        if m and int(m.group()) < int(args.from_stage):
            log(f, f"---- 跳过 {name}（--from {args.from_stage}）")
            continue
        if args.skip_drpy and name.startswith("3 "):
            log(f, f"---- 跳过 {name}")
            results.append((name, "SKIP", 0))
            continue
        if args.skip_probes and name.startswith("2"):
            log(f, f"---- 跳过 {name}")
            results.append((name, "SKIP", 0))
            continue
        env = dict(os.environ)
        env.update({k: v for k, v in extra_env.items() if v})
        log(f, f"---- {name} 开始: {' '.join(cmd)}")
        t0 = time.time()
        try:
            p = subprocess.run([PY, "-u"] + cmd, cwd=REPO, env=env,
                               stdout=f, stderr=subprocess.STDOUT, timeout=3600)
            ok = (p.returncode == 0)
            note = f"rc={p.returncode}"
        except subprocess.TimeoutExpired:
            ok, note = False, "timeout>3600s"
        el = time.time() - t0
        # 关键：一条关键阶段失败就停（与 daily.yml 的"合并必须成功"一致）
        status = "OK" if ok else ("CONT" if cont else "FAIL")
        log(f, f"---- {name} 结束: {status}  耗时 {el:.0f}s  ({note})")
        results.append((name, status, el))
        if not ok and not cont:
            log(f, "关键阶段失败，中止后续流程")
            break

    log(f, "==== 全链路汇总 ====")
    total = sum(el for _, _, el in results)
    for name, status, el in results:
        log(f, f"  [{status:4}] {name:26} {el:6.0f}s")
    log(f, f"总耗时 {total:.0f}s；日志 -> {os.path.relpath(log_path, REPO)}")
    f.close()
    bad = [n for n, s, _ in results if s == "FAIL"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
