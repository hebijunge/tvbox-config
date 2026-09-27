#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_collect_dashboard.py — 采集性能监控仪表盘（C8）。

读三份状态文件，生成单文件 HTML（内联 ECharts CDN），输出 exports/collect_dashboard.html：
  * checks.json                  —— 上游校验状态（ok/dead/disabled/blacklisted 分布）
  * state/upstream_latency.json  —— 各上游 avg_latency / samples
  * state/upstream_failures.json —— 失败类别分布（timeout/ssl/404...）

每日 CI 末尾跑一次（非实时）；纯只读，缺文件降级显示空图。

用法：
    python scripts/gen_collect_dashboard.py
"""
from __future__ import annotations

import json
import os
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)

HTML_TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>采集性能监控 · tvbox-config</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
body{background:#0f1420;color:#e8ecf5;font:14px/1.6 -apple-system,"Microsoft YaHei",sans-serif;margin:0;padding:20px}
h1{font-size:20px} .sub{color:#93a0bb;font-size:12px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#171e2e;border:1px solid #2a3450;border-radius:12px;padding:14px}
.card h3{font-size:14px;margin:0 0 8px;color:#93a0bb;font-weight:500}
.chart{height:280px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style></head><body>
<h1>采集性能监控仪表盘</h1>
<div class="sub">生成于 __GEN_AT__ · 每日 CI 末尾快照（C8）</div>
<div class="grid">
  <div class="card"><h3>上游状态分布</h3><div id="c1" class="chart"></div></div>
  <div class="card"><h3>上游延迟 TOP（avg ms）</h3><div id="c2" class="chart"></div></div>
  <div class="card"><h3>失败类别分布</h3><div id="c3" class="chart"></div></div>
  <div class="card"><h3>关键指标</h3><div id="c4" class="chart"></div></div>
</div>
<script>
var DATA = __DATA__;
function pie(id,d){var c=echarts.init(document.getElementById(id));c.setOption({tooltip:{trigger:'item'},series:[{type:'pie',radius:['40%','70%'],data:d,label:{color:'#ccc'}}]});}
function bar(id,d,ax){var c=echarts.init(document.getElementById(id));c.setOption({tooltip:{},grid:{left:80,right:20,top:10,bottom:20},xAxis:{type:'value',axisLabel:{color:'#93a0bb'}},yAxis:{type:'category',data:ax,axisLabel:{color:'#93a0bb'}},series:[{type:'bar',data:d,itemStyle:{color:'#4f8cff'}}]});}
pie('c1',DATA.statusPie);
bar('c2',DATA.latency.values,DATA.latency.labels);
pie('c3',DATA.failPie);
bar('c4',DATA.metrics.values,DATA.metrics.labels);
</script></body></html>"""


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    checks = load_json("checks.json")
    latency = load_json("state/upstream_latency.json")
    failures = load_json("state/upstream_failures.json")

    s = checks.get("summary", {}) if isinstance(checks, dict) else {}
    status_pie = [
        {"name": "可用", "value": s.get("ok", 0)},
        {"name": "失效", "value": s.get("dead", 0)},
        {"name": "停用", "value": s.get("disabled", 0)},
        {"name": "黑名单", "value": s.get("blacklisted", 0)},
        {"name": "降级", "value": s.get("degraded", 0)},
    ]

    lat = [(os.path.basename(k), v.get("avg_latency", 0))
           for k, v in latency.items() if isinstance(v, dict) and v.get("avg_latency")]
    lat.sort(key=lambda x: -x[1])
    top = lat[:15][::-1]
    latency_data = {"labels": [n for n, _ in top],
                    "values": [round(ms) for _, ms in top]}

    fail_cat = {}
    for v in failures.values():
        if isinstance(v, dict):
            c = v.get("last_category", "other")
            fail_cat[c] = fail_cat.get(c, 0) + 1
    fail_pie = [{"name": k, "value": v} for k, v in fail_cat.items()]

    upstreams = checks.get("upstreams", []) if isinstance(checks, dict) else []
    metrics = {
        "labels": ["上游总数", "可用", "黑名单", "已停用"],
        "values": [s.get("total", 0), s.get("ok", 0),
                   s.get("blacklisted", 0), s.get("disabled", 0)],
    }

    data = {"statusPie": status_pie, "latency": latency_data,
            "failPie": fail_pie, "metrics": metrics}
    html = HTML_TPL.replace("__GEN_AT__", time.strftime("%Y-%m-%d %H:%M:%S")) \
                   .replace("__DATA__", json.dumps(data, ensure_ascii=False))

    os.makedirs("exports", exist_ok=True)
    out = "exports/collect_dashboard.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[collect_dashboard] 上游 {s.get('total', 0)}，失败类别 {len(fail_pie)}，"
          f"延迟 TOP {len(top)} -> {out}")
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
