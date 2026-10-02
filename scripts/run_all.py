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
  2. 全网发现（默认五路）     continue-on-error（Gitee 路需 --gitee 才开）
  3. 候选评估 + canary 收编  continue-on-error
  4. 拉取合并（必须成功）    失败则中止
  5. 探针实测（当天拉当天测） continue-on-error：HTTP/spider/js/同库去重/drpy
  6. 依赖完整性闸门         continue-on-error
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
sys.path.insert(0, HERE)
import pipeline_step_stats as _pss  # 分步成果文件生成器（每步跑完落盘 state/pipeline_steps/）
PY = sys.executable or "python"

STAGES = [
    # (stage_id, 展示名, [cmd...], continue_on_fail, extra_env)
    # 2026-09-29 流程重排（与 daily.yml 严格对齐）：探针整体后置到拉取合并之后，
    # 当天拉当天测；入库后的当日结论经 export_healthy 进 exports/，主产物不带健康标注。
    ("1", "镜像测速择优", ["scripts/mirror_probe.py"], True, {}),
    ("2", "全网发现(五路)", ["scripts/discover_upstreams.py", "--pages", "2"], True,
     {"GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "")}),
    ("3", "候选评估+canary收编", ["scripts/evaluate_candidates.py", "--min-unique", "3", "--write-canary"], True, {}),
    ("4", "拉取合并(必须成功)", ["scripts/fetch_merge.py"], False,
     {"EXTRA_UPSTREAMS": "1", "CONCURRENCY": "24"}),
    ("5a", "探针: HTTP L1-L3", ["scripts/probe_sites.py", "--only", "http", "--concurrency", "20"], True, {}),
    ("5b", "探针: type3 连通性", ["scripts/probe_spiders.py", "--concurrency", "20"], True, {}),
    ("5c", "探针: JS 分类页", ["scripts/probe_js.py", "--concurrency", "20"], True, {}),
    ("5d", "同库镜像去重", ["scripts/dedup_mirrors.py"], True, {}),
    ("5e", "drpy 沙箱五关", ["scripts/drpy_probe.py", "--workers", "5"], True, {}),
    ("5f", "探针: py 插件静态结构", ["scripts/probe_py.py"], True, {}),
    ("5g", "探针: type4 推送/解析端点", ["scripts/probe_endpoints.py", "--concurrency", "16"], True, {}),
    # 5h 判的是「远程 ext 规则在国内到底取不到取不到」——真机侧这类站永远 homeContent 空串
    # （spider 自己吞掉拉规则的失败），只有从国内直接证伪才拿得到结论。必须在带 root 真机的
    # 本机跑，和 5a-5g 同一个出口口径；CI 只消费 csp_probe.json，不重跑这一步。
    ("5h", "探针: csp 远程 ext 可达性", ["csp-device/csp_device_batch.py", "ext"], True, {}),
    ("6", "依赖完整性闸门", ["scripts/dep_repair.py", "--workers", "8"], True, {}),
    ("7a", "入库(接口/直播/检测/依赖)", ["scripts/store.py", "--ingest-sites", "tvbox.json",
                                    "--ingest-lives", "tvbox.json", "--probe-lives",
                                    "--ingest-probes", "probe/sites_probe.json",
                                    "probe/spider_probe.json", "probe/js_probe.json",
                                    "probe/csp_probe.json", "probe/drpy_probe.json",
                                    "probe/py_probe.json",
                                    "probe/endpoint_probe.json",
                                    "--prune", "--stats"], True, {}),
    ("7b", "导出清单", ["scripts/export_healthy.py"], True, {}),
    ("7c", "直播死源剔除(P1-4 只剔404)", ["scripts/live_dead_prune.py", "--workers", "8"], True, {}),
    ("7d", "健康日报", ["scripts/health_report.py"], True, {}),
    ("7e", "依赖审计", ["scripts/dep_audit.py"], True, {}),
    ("8", "采集入口可达性探测", ["scripts/probe_sources.py", "--concurrency", "20"], True, {}),
    ("9", "本地接口包(离线zip)", ["scripts/pack_local.py"], True, {}),
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
    for sid, name, cmd, cont, extra_env in STAGES:
        # --from N：从指定序号的阶段开始（前面的阶段产物视为新鲜，直接复用）。
        # sid 形如 "2a"，序号取前导数字（int("2a") 会抛 ValueError 导致失效）
        m = re.match(r"\d+", sid)
        if m and int(m.group()) < int(args.from_stage):
            log(f, f"---- 跳过 {name}（--from {args.from_stage}）")
            continue
        if args.skip_drpy and sid == "5e":
            log(f, f"---- 跳过 {name}")
            results.append((name, "SKIP", 0, sid))
            _pss.write_step_file(sid, "SKIP", 0.0, cmd=" ".join(cmd))
            continue
        if args.skip_probes and sid.startswith("5"):
            log(f, f"---- 跳过 {name}")
            results.append((name, "SKIP", 0, sid))
            _pss.write_step_file(sid, "SKIP", 0.0, cmd=" ".join(cmd))
            continue
        env = dict(os.environ)
        # Windows 中文环境子进程 stdout 默认 cp936，站点名含 emoji/♥ 会 UnicodeEncodeError
        # 崩掉探针（CI Linux UTF-8 不复现）；统一强制 UTF-8 输出，与日志文件编码一致。
        env["PYTHONIOENCODING"] = "utf-8"
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
        # 每步跑完立即落盘成果文件（state/pipeline_steps/step_<sid>.json）
        _pss.write_step_file(sid, status, el, cmd=" ".join(cmd))
        results.append((name, status, el, sid))
        if not ok and not cont:
            log(f, "关键阶段失败，中止后续流程")
            break

    # 全链路汇总 + 生成总报告（json + 人读版 md）
    log(f, "==== 全链路汇总 ====")
    total = sum(el for _, _, el, _ in results)
    for name, status, el, _sid in results:
        log(f, f"  [{status:4}] {name:26} {el:6.0f}s")
    log(f, f"总耗时 {total:.0f}s；日志 -> {os.path.relpath(log_path, REPO)}")
    try:
        jp, mp = _pss.write_pipeline_report()
        log(f, f"分步成果文件 -> state/pipeline_steps/ ；总报告 -> {os.path.relpath(jp, REPO)} / {os.path.relpath(mp, REPO)}")
    except Exception as e:  # noqa: BLE001
        log(f, f"生成总报告失败（不影响主流程）: {e}")
    f.close()
    bad = [n for n, s, _el, _sid in results if s == "FAIL"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
