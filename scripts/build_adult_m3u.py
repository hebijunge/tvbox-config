#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_adult_m3u.py — adult 组独立 m3u（P0-1 第七组 / P0-2 物理隔离）。

数据源 = 仓库内 adult 实际产物（adult_live_channels.json 频道级验活全量 +
adult_live.json 源级条目），非人工编造。产出 adult_live_channels/adult.m3u：
  - 只落在 adult 隔离通道目录（不进 lives/、不进 Release 白名单 / Pages / 本地包）；
  - group-title=adult；频道名含 ms（加载耗时）按速度升序（同 live 线口径）。

用法：python scripts/build_adult_m3u.py [--out adult_live_channels/adult.m3u]
接入：静态产物生成脚本（与 adult_live_channels/cat*.txt 同级同纪律，daily 不覆写）。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("adult_live_channels", "adult.m3u"))
    args = ap.parse_args()
    os.chdir(ROOT)

    rows = []
    # ① 频道级验活产物（含 ms 速度标记，按速度升序）
    p1 = "adult_live_channels.json"
    if os.path.isfile(p1):
        doc = json.load(open(p1, encoding="utf-8"))
        for c in doc.get("channels", []):
            u, nm = c.get("url"), c.get("name")
            if not u or not nm:
                continue
            rows.append((float(c.get("ms") or 999), nm, u))
    # ② 源级产物条目（adult_live.json lives[].url）
    p2 = "adult_live.json"
    if os.path.isfile(p2):
        doc = json.load(open(p2, encoding="utf-8"))
        for l in doc.get("lives", []):
            u, nm = l.get("url"), l.get("name")
            if u and nm:
                rows.append((998.0, nm, u))
    # 去重（同名同 URL），按速度升序
    seen, final = set(), []
    for ms, nm, u in sorted(rows, key=lambda x: x[0]):
        if (nm, u) in seen:
            continue
        seen.add((nm, u))
        final.append((nm, u))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for nm, u in final:
            f.write('#EXTINF:-1 group-title="adult",%s\n%s\n' % (nm, u))
    print("[adult-m3u] %s: %d entries (in=%d, dedup=%d)"
          % (args.out, len(final), len(rows), len(rows) - len(final)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
