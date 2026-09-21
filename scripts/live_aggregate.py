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
    "xuy132", "svefnz",
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


# ---- 2026-09-21 直播线融合（第六批 P1/P2，借鉴 ineed2underfit/hk-iptv + Collect-IPTV）----
# 港台白名单清洗：与 hk-iptv 全量白名单制不同，本仓「港台」组同时承载台湾频道，
# 严格白名单会清空台湾，故采用三分制：黑名单剔除 → 港白名单组首（收视习惯排序）→
# 台湾次级 → 其余组尾保留。RTHK 官方静态源兜底见 write_verified_txt。
HK_BLOCK_KW = (
    # 大陆伪装/地方误入（hk-iptv 日志分析来源）
    "浙江", "杭州", "西湖", "广东", "廣東", "珠江", "大湾区", "大灣區",
    "澳门", "澳門", "macau", "福建", "延时", "延時", "测试", "測試", "星河", "华丽", "華麗",
    # 澳门频道防误入
    "澳广视", "澳廣視", "澳亞", "tdm",
    # 大陆注册落地港频道（hk-iptv 口径；如需保留凤凰可从黑名单移除）
    "凤凰", "鳳凰",
    # 英文广告/ pseudo 台
    "fox", "pluto", "nbc", "cbs", "abc", "axs", "snowy", "reuters", "mirror",
    "et now", "the now", "right now", "news now", "chopper", "wow", "uhd",
    "8k", "career", "comics", "movies", "cbtv", "ihoy", "ihoi",
)

# 港人收视习惯排序（hk-iptv ORDER_KEYWORDS 口径，每组一个优先级档，组内保持原序）
HK_ORDER_KW = (
    ("翡翠", "tvb"),                       # TVB 主频
    ("无线新闻", "無線新聞"),               # TVB 新闻
    ("明珠",),                             # TVB 明珠
    ("j2",), ("j5",), ("财经", "財經"),     # TVB 副频
    ("viutv", "viu"),                      # ViuTV 系
    ("hoy", "奇妙"),                       # HOY 系
    ("有线", "有線"),                      # 香港有线
    ("港台电视31", "港台電視31", "rthk31", "rthk 31"),
    ("港台电视32", "港台電視32", "rthk32", "rthk 32"),
    ("now新闻", "now新聞", "now直播"),      # Now 系
)

# 台湾频道次级保留关键词（不参与排序，仅保证不被当杂牌沉底后遗忘）
TW_KW = ("台湾", "臺灣", "民视", "民視", "三立", "东森", "東森", "中天", "台视", "台視",
         "中视", "中視", "华视", "華視", "公视", "公視", "八大", "纬来", "緯來",
         "龙华", "龍華", "靖天", "大爱", "大愛", "壹电视", "壹電視", "年代", "tvbs",
         "momo", "镜新闻", "鏡新聞", "寰宇", "好消息")

# RTHK 官方静态源（hk-iptv STATIC_CHANNELS 原文，测速全挂时兜底，不参与删除）
RTHK_STATIC = (
    ("港台電視31 (官方)", "https://rthklive1-lh.akamaihd.net/i/rthk31_1@167495/index_2052_av-b.m3u8"),
    ("港台電視32 (官方)", "https://rthklive2-lh.akamaihd.net/i/rthk32_1@168450/index_2052_av-b.m3u8"),
)

# ---- 频道名归一化别名表（第六批 P2，借鉴 Collect-IPTV：繁简映射 + 别名 + 后缀剥离）----
# 繁→简字符映射（覆盖频道名常见繁体字；内置表而非 OpenCC，避免 CI 新增 pip 依赖）
S2T_MAP = {
    "臺": "台", "灣": "湾", "鳳": "凤", "無": "无", "線": "线", "綫": "线", "電": "电",
    "視": "视", "廣": "广", "東": "东", "門": "门", "體": "体", "聞": "闻", "財": "财",
    "經": "经", "娛": "娱", "樂": "乐", "戲": "戏", "劇": "剧", "歷": "历", "綜": "综",
    "藝": "艺", "資": "资", "訊": "讯", "龍": "龙", "緯": "纬", "來": "来", "華": "华",
    "愛": "爱", "環": "环", "衛": "卫", "頻": "频", "網": "网", "絡": "络", "場": "场",
    "實": "实", "況": "况", "賽": "赛", "國": "国", "際": "际", "標": "标", "靈": "灵",
    "話": "话", "亞": "亚", "歐": "欧", "聲": "声", "韓": "韩", "億": "亿", "萬": "万",
    "豐": "丰", "澤": "泽", "輝": "辉", "創": "创", "學": "学", "奧": "奥", "運": "运",
    "動": "动", "畫": "画", "兒": "儿", "親": "亲", "寶": "宝", "貝": "贝", "頭": "头",
    "條": "条", "聯": "联", "傳": "传", "區": "区", "職": "职", "業": "业", "籃": "篮",
    "誌": "志", "質": "质", "選": "选", "譯": "译", "談": "谈", "靚": "靓", "購": "购",
    "賣": "卖", "廠": "厂", "銷": "销", "麗": "丽", "間": "间", "雙": "双",
}

# 别名归一（应用于去重键，全词小写匹配；保守条目，只并明显同台异名）
ALIAS_MAP = {
    "tvb翡翠": "翡翠", "tvb明珠": "明珠", "香港翡翠": "翡翠", "香港明珠": "明珠",
    "tvb新闻": "无线新闻", "tvb新聞": "无线新闻",
}


def to_simp(s):
    """繁→简字符级归一化（内置 S2T_MAP，无外部依赖）。"""
    return "".join(S2T_MAP.get(ch, ch) for ch in (s or ""))


def dedup_key(std):
    """频道名去重键：繁归简 → 去空白转小写 → 去尾部括号标注（如“(官方)”）→
    别名表 → 后缀剥离（频道/台，守卫卫视/电台）。
    仅用于 build_channel_map 聚合键，显示名保留首次出现的原名（ent['name']）。"""
    k = to_simp(std or "")
    k = re.sub(r"[\s　]+", "", k).lower()
    k = re.sub(r"[（(][^()（）]*[)）]$", "", k)
    if k in ALIAS_MAP:
        return ALIAS_MAP[k]
    m = re.search(r"(卫视|电台|频道|台)$", k)
    if m and len(k) > len(m.group(1)):
        # 守卫：卫视/电台是完整词不剥离；频道/台 仅在剥离后仍非空时剥
        if m.group(1) not in ("卫视", "电台"):
            k = k[: -len(m.group(1))]
    if k in ALIAS_MAP:
        k = ALIAS_MAP[k]
    return k


def hk_clean_sort(chans):
    """港台组清洗与排序（第六批 P1）。
    chans: {频道名: lines}。返回清洗排序后的 OrderedDict：
    黑名单命中剔除；港白名单命中按 HK_ORDER 收视习惯排组首；台湾频道次级；其余组尾。"""
    def bucket(name):
        low = name.lower()
        if any(k in low for k in HK_BLOCK_KW):
            return (9, 0)
        for prio, kws in enumerate(HK_ORDER_KW):
            if any(k in low for k in kws):
                return (0, prio)
        if any(k in low for k in TW_KW):
            return (1, 0)
        return (2, 0)
    out = OrderedDict()
    for name, lines in sorted(chans.items(), key=lambda kv: bucket(kv[0])):
        if bucket(name)[0] == 9:
            continue  # 黑名单命中：直接剔除（大陆伪装/澳门/测试频道）
        out[name] = lines
    return out


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
    # 2026-09-21 直播线融合：第五批新增聚合上游
    if "xuy132" in u:
        return "xuy132"
    if "svefnz" in u:
        return "svefnz"
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
            # 2026-09-21 直播线融合：聚合键用归一化去重键（繁简/别名/后缀），
            # 显示名保留首次出现的 std，避免「翡翠台/翡翠/Tvb翡翠」裂成三个频道
            key = dedup_key(std)
            ent = cmap.setdefault(key, {"name": std, "class": cls, "lines": []})
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
    """输出 lives/live_verified.txt。2026-09-21 直播线融合增强：
    1) 显示名用 ent['name']（聚合键为归一化去重键后，避免输出去重键当频道名）；
    2) 港台组经 hk_clean_sort 清洗排序（黑名单剔除/白名单收视习惯排序/台湾次级）；
    3) RTHK 官方静态源兜底：港台频道实测未通过或缺失时追加官方源（不删除任何已验证线路）。"""
    groups = OrderedDict()
    ORDER = ["央视", "卫视", "港台", "轮播·一起看", "地方", "电台", "网络·其他"]
    for key, ent in cmap.items():
        name = ent.get("name") or key
        groups.setdefault(ent["class"], OrderedDict())
        if key in verified:
            lines = verified[key]
        else:
            lines = [u for _sid, u in ent["lines"][:extra_keep]]
        if lines:
            groups[ent["class"]][name] = lines
    if "港台" in groups:
        groups["港台"] = hk_clean_sort(groups["港台"])
        # RTHK 官方静态源兜底（第六批 P1）：实测未通过/缺失的港台频道补官方源
        for nm, static_url in RTHK_STATIC:
            k = dedup_key(nm)
            if k in cmap and k in verified:
                continue  # 实测通过，无需兜底
            found = None
            for dname in groups["港台"]:
                if dedup_key(dname) == k:
                    found = dname
                    break
            if found:
                lines = groups["港台"][found]
                if static_url not in lines:
                    groups["港台"][found] = ([static_url] + lines)[:MAX_LINES_PER_CH]
            else:
                groups["港台"][nm] = [static_url]
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
        # 2026-09-21 直播线融合：第五批实测有效上游（xuy132 txt 2648 条 / svefnz 338 频道含港澳台）
        ("xuy132", "https://ghproxy.net/https://raw.githubusercontent.com/xuy132/TV/master/output/result.txt"),
        ("svefnz", "https://ghproxy.net/https://raw.githubusercontent.com/svefnz/IPTVN/Files/IPTV.m3u"),
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
