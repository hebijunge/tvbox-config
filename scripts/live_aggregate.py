#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_aggregate.py — 频道级聚合：规范化、分类、多线路合并、逐线路实测。

输入：源级测活通过的 m3u/tvbox-txt 源清单
输出：lives/live_verified.txt（tvbox txt 分组格式，多线路 # 合并）+ live_channels.json 明细
"""
import json
import os
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed

sys_path = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, sys_path)
from live_probe import http_get, probe_stream  # noqa: E402

MAX_LINES_PER_CH = 6

SOURCE_PRIORITY = [
    "cctv", "satellite", "hkmo_tw", "other",
    "guovin", "mlzlzj", "suxuang", "livefl",
    "zonghe", "kimentanm",
    "yy", "huya", "douyu", "bili", "mgtv", "catvod",
    "fmm_v6",
]

HKTW_KW = ("凤凰", "tvb", "翡翠", "明珠", "香港", "无线", "有线", "hib", "rthk",
           "台湾", "民视", "三立", "东森", "中天", "台视", "中视", "华视", "公视",
           "八大", "纬来", "龙华", "靖天", "大爱", "壹电视", "年代", "澳广视", "澳门",
           "tvbs", "好消息", "uhb", "viutv", "viu")

LUNBO_KW = ("虎牙", "斗鱼", "哔哩", "b站", "bilibili", "咪咕", "歌手", "轮播",
            "一起看", "电竞")

DIFANG_KW = ("北京", "上海", "天津", "重庆", "广东", "珠江", "深圳", "江苏", "浙江",
             "山东", "湖北", "四川", "河南", "河北", "山西", "陕西", "辽宁",
             "吉林", "黑龙江", "安徽", "福建", "江西", "广西", "云南", "贵州", "甘肃",
             "青海", "宁夏", "新疆", "西藏", "内蒙古", "海南", "新闻综合", "都市",
             "剧场", "教育", "少儿", "卡酷", "金鹰", "优漫", "哈哈", "炫动")


def norm_channel(name):
    """规范化频道名，返回 (标准名, 分类)。"""
    n = (name or "").strip()
    if not n:
        return "", ""
    low = n.lower().replace(" ", "").replace("　", "")
    low = re.sub(r"[\[\]()（）【】「」]|超清|高清|标清|蓝光|1080p?|720p?|4k|50fps?|60fps?|hd|sd|fhd|测试", "", low)
    m = re.match(r"^cctv[-−]?(\d+)(\+?)", low)
    if m:
        return "CCTV-%d%s" % (int(m.group(1)), m.group(2)), "央视"
    if low.startswith(("cgtn", "cgtv")):
        return "CGTN", "央视"
    if any(k in low for k in HKTW_KW):
        return n, "港台"
    if "卫视" in low:
        base = low[:low.index("卫视") + 2]
        return base, "卫视"
    if any(k in low for k in LUNBO_KW):
        return n, "轮播·一起看"
    if re.search(r"电台|fm\d*$|广播", low):
        return n, "电台"
    if any(k in low for k in DIFANG_KW):
        return n, "地方"
    return n, "网络·其他"


CLASS_PRIO = {"央视": 0, "港台": 1, "卫视": 2, "轮播·一起看": 3,
              "地方": 4, "电台": 5, "网络·其他": 6}


def parse_m3u(text):
    out = []
    cur = None
    for l in text.splitlines():
        l = l.strip()
        if not l:
            continue
        if l.startswith("#EXTINF"):
            m = re.search(r",\s*(.+)$", l)
            cur = m.group(1).strip() if m else None
        elif l.startswith("#"):
            continue
        elif re.match(r"^https?://", l):
            out.append((cur or "未知频道", l))
            cur = None
    return out


def parse_tvbox_txt(text):
    out = []
    for l in text.splitlines():
        l = l.strip()
        if not l or l.endswith("#genre#") or "," not in l:
            continue
        name, urls = l.rsplit(",", 1)
        for u in urls.split("#"):
            u = u.strip()
            if re.match(r"^https?://", u):
                out.append((name.strip(), u))
    return out


def classify_source(url):
    u = (url or "").lower()
    if "live_cctv" in u:
        return "cctv"
    if "live_satellite" in u:
        return "satellite"
    if "hkmo" in u:
        return "hkmo_tw"
    if "live_other" in u:
        return "other"
    if "guovin/iptv-api" in u:
        return "guovin"
    if "mlzlzj" in u:
        return "mlzlzj"
    if "suxuang" in u:
        return "suxuang"
    if "zeee-u" in u:
        return "livefl"
    if "iptv.php" in u:
        return "zonghe"
    if "kimentanm" in u:
        return "kimentanm"
    if "yylunbo" in u:
        return "yy"
    if "huyayqk" in u:
        return "huya"
    if "douyuyqk" in u:
        return "douyu"
    if "bililive" in u:
        return "bili"
    if "mglist" in u:
        return "mgtv"
    if "live.catvod" in u:
        return "catvod"
    if "fmml_ipv6" in u or "ipv6" in u:
        return "fmm_v6"
    return "misc"


def load_source(sid, url, repo):
    text = None
    if "/hebijunge/tvbox-config/main/lives/" in url and repo:
        fn = url.rsplit("/", 1)[-1]
        p = os.path.join(repo, "lives", fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                text = f.read()
    if text is None:
        status, headers, body = http_get(url, 15)
        if status != 200 or not body:
            return []
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = body.decode("gbk")
            except Exception:
                return []
    if text.lstrip().startswith("#EXTM3U"):
        return parse_m3u(text)
    return parse_tvbox_txt(text)


def build_channel_map(sources, repo):
    cmap = OrderedDict()
    for sid, url in sources:
        chans = load_source(sid, url, repo)
        print("  [%s] %d channels" % (sid, len(chans)), flush=True)
        for name, u in chans:
            std, cls = norm_channel(name)
            if not std:
                continue
            ent = cmap.setdefault(std, {"class": cls, "lines": []})
            if CLASS_PRIO.get(cls, 9) < CLASS_PRIO.get(ent["class"], 9):
                ent["class"] = cls
            ent["lines"].append((sid, u))
    return cmap


def test_channel_lines(cmap, only_classes=("央视", "卫视", "港台"),
                       max_test=MAX_LINES_PER_CH, budget_s=420):
    """核心频道逐线路实测，返回 {标准名: [通过 url]} 与全部明细。"""
    t0 = time.time()
    jobs = []
    for std, ent in cmap.items():
        if ent["class"] not in only_classes:
            continue
        lines = sorted(ent["lines"], key=lambda x: (SOURCE_PRIORITY.index(x[0])
                        if x[0] in SOURCE_PRIORITY else 99))
        seen, uniq = set(), []
        for sid, u in lines:
            if u not in seen:
                seen.add(u)
                uniq.append((sid, u))
        ent["lines"] = uniq
        jobs.append((std, uniq[:max_test]))
    results = {}
    n = [0]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {}
        for std, lines in jobs:
            for sid, u in lines:
                if time.time() - t0 > budget_s:
                    break
                futs[ex.submit(probe_stream, u)] = (std, u)
            if time.time() - t0 > budget_s:
                break
        for fut in as_completed(futs):
            std, u = futs[fut]
            try:
                ok, why = fut.result()
            except Exception:
                ok, why = False, "error"
            results.setdefault(std, []).append((u, ok, why))
            n[0] += 1
            if n[0] % 50 == 0:
                print("  tested %d lines ..." % n[0], flush=True)
    verified = {}
    for std, lst in results.items():
        good = [u for u, ok, _w in lst if ok]
        if good:
            verified[std] = good[:MAX_LINES_PER_CH]
    return verified, results


def write_verified_txt(cmap, verified, path, extra_keep=6):
    groups = OrderedDict()
    ORDER = ["央视", "卫视", "港台", "轮播·一起看", "地方", "电台", "网络·其他"]
    for std, ent in cmap.items():
        groups.setdefault(ent["class"], OrderedDict())
        if std in verified:
            lines = verified[std]
        else:
            lines = [u for _sid, u in ent["lines"][:extra_keep]]
        if lines:
            groups[ent["class"]][std] = lines
    with open(path, "w", encoding="utf-8") as f:
        for cls in ORDER:
            if cls not in groups:
                continue
            f.write("%s,#genre#\n" % cls)
            for std, lines in groups[cls].items():
                f.write("%s,%s\n" % (std, "#".join(lines)))
    return {c: len(chs) for c, chs in groups.items()}


def build_sources(repo):
    sources = []
    for fn, sid in (("live_cctv.txt", "cctv"), ("live_satellite.txt", "satellite"),
                    ("live_hkmo_tw.txt", "hkmo_tw"), ("live_other.txt", "other")):
        if os.path.exists(os.path.join(repo, "lives", fn)):
            sources.append((sid, "https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/lives/" + fn))
    sources.extend([
        ("guovin", "https://ghproxy.net/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u"),
        ("mlzlzj", "https://ghproxy.net/https://raw.githubusercontent.com/mlzlzj/TV/main/output/result.m3u"),
        ("suxuang", "https://ghproxy.net/https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv4.m3u"),
        ("livefl", "https://ghproxy.net/https://raw.githubusercontent.com/zeee-u/lzh06/main/fl.m3u"),
        ("zonghe", "http://193.123.86.190:14888/TV/iptv.php"),
        ("kimentanm", "https://gh.927223.xyz/https://raw.githubusercontent.com/Kimentanm/aptv/master/m3u/iptv.m3u"),
        ("yy", "https://sub.ottiptv.cc/yylunbo.m3u"),
        ("huya", "https://sub.ottiptv.cc/huyayqk.m3u"),
        ("douyu", "https://sub.ottiptv.cc/douyuyqk.m3u"),
        ("bili", "https://sub.ottiptv.cc/bililive.m3u"),
        ("mgtv", "https://mgtv.ottiptv.cc/mglist.m3u"),
        ("fmm_v6", "https://m3u.ibert.me/txt/fmml_ipv6.txt"),
    ])
    return sources


def main(repo=None, out_txt="lives/live_verified.txt", out_json="live_channels.json"):
    repo = repo or os.path.dirname(sys_path)
    sources = build_sources(repo)
    print("loading %d sources ..." % len(sources), flush=True)
    cmap = build_channel_map(sources, repo)
    print("channels: %d" % len(cmap), flush=True)
    t0 = time.time()
    verified, raw = test_channel_lines(cmap, budget_s=420)
    print("line tests done in %.0fs, verified channels: %d" % (time.time() - t0, len(verified)), flush=True)
    stats = write_verified_txt(cmap, verified, os.path.join(repo, out_txt))
    print("groups:", stats, flush=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "verified": verified,
            "group_stats": stats,
            "channels": {k: {"class": v["class"], "n_lines": len(v["lines"]),
                             "lines": [u for _s, u in v["lines"][:10]]}
                         for k, v in cmap.items()},
        }, f, ensure_ascii=False, indent=1)
    return cmap, verified


if __name__ == "__main__":
    main()
