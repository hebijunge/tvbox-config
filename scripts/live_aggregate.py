#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_aggregate.py — 频道级聚合：规范化、分类、多线路合并、逐线路实测。

输入：源级测活通过的 m3u/tvbox-txt 源清单
输出：lives/live_verified.txt（tvbox txt 分组格式，多线路 # 合并）
     + lives/live_verified.m3u（第十三批：fanmingming/live 台标/EPG 引用层）
     + live_channels.json 明细
"""
import datetime
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

# ---- 第十三批吸收实施（batch11 P1-1 / batch12 建议落地）：fanmingming/live 台标引用层 ----
# 只做引用（URL 拼接），不镜像资产——fanmingming/live 为 GPL-3.0（28k+★，生态事实标准，
# zhi35/kilvn/hehonghui 等 m3u 均引用其台标/EPG），镜像分发有许可与时效双重问题。
# 命名口径与生态实证一致（zhi35 m3u 原文）：台标文件名 = tvg-name；
# CCTV 系取「CCTV1」形态（CCTV-1→CCTV1，CCTV-5+→CCTV5+），其余频道用显示名原文
# 不转义（与 zhi35 的 https://live.fanmingming.cn/tv/湖南卫视.png 写法一致）；
# 个别小众频道文件缺失时播放器侧仅无台标，不影响播放（引用层 best-effort）。
FMM_TV_BASE = "https://live.fanmingming.cn/tv/"
# 第十五批吸收实施（batch9 P1「EPG 直链四件套」剩余三条）：多源冗余，播放器按序取用；
# 三条新源均为 2026-09-22 沙箱实测 200 且可解析（xmltv channel/programme 齐全）：
#   kuke31/xmlgz all.xml.gz 1.3MB 521 频道/128230 条节目；plsy1/epg seven-days.xml.gz 552KB
#   162 频道/54764 条节目（运营商机顶盒抓取，display-name 带「CCTV1综合」别名双挂）；
#   mytv-android/myEPG epg.gz（master 分支）2.3MB 852 频道/168909 条节目。
# 仅头部引用（x-tvg-url），运行时不抓取，无 CI 成本。
FMM_EPG_URLS = ("https://live.fanmingming.cn/e.xml",       # fanmingming e.xml（batch12 三源 EPG 惯例首位）
                "https://e.erw.cc/all.xml.gz",
                "http://epg.51zmt.top:8000/e.xml.gz",
                "https://epg.zsdc.eu.org/t.xml.gz",        # batch9 suzukua/epg 备源（2026-09-22 沙箱实测 200/500799B）
                "https://raw.githubusercontent.com/kuke31/xmlgz/main/all.xml.gz",        # batch9 kuke31（七天回看）
                "https://raw.githubusercontent.com/plsy1/epg/main/e/seven-days.xml.gz",  # batch9 plsy1（运营商抓取）
                "https://raw.githubusercontent.com/mytv-android/myEPG/master/output/epg.gz")  # batch9 myEPG（每日 Actions 构建，master 分支）
FMM_CATCHUP = 'catchup="append" catchup-source="?playseek=${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}"'


def fmm_logo_name(std):
    """fanmingming 台标文件名（不含 .png）。第十五批适配增强（对库内 929 个 tv 台标名
    离线量化验证：真实频道名池 1374 个，核心缺口为「CCTV-1 综合」副标题形态与画质后缀）：
    1) 剥尾部括号标注（「港台電視31 (官方)」→「港台電視31」，与 dedup_key 同口径）；
    2) 去全部空白；
    3) CCTV/CGTN 编号+副标题 → 紧凑形态（「CCTV-1 综合」→CCTV1、「CCTV-5+ 体育赛事」→
       CCTV5+、「CCTV-4K 超高清」→CCTV4K、CGTN 同理；库内形态 CCTV1/CCTV5+/CCTV4K）；
    4) CETV-N 去连字符（CETV-1→CETV1，库内无连字符形态）；
    5) 尾部画质后缀剥离（高清/超清/标清/蓝光/超高清/4K/8K/FHD/HD，「北京卫视高清」→北京卫视；
       仅剥尾部 token，不伤「CHC高清电影」这类库内本名）；
    6) NEWTV/IHOT 大小写归一（库内 NEWTV东北热剧/IHOT爱体育；库内 viutv 为全小写、
       无大小写可归一的稳定形态，不做 ViuTV 映射）。
    全部 best-effort：库缺名时播放器侧仅无台标，不影响播放。"""
    n = (std or "").strip().replace('"', "'")
    n = re.sub(r"[（(][^()（）]*[)）]$", "", n).strip()
    n = re.sub(r"\s+", "", n)
    m = re.match(r"^(CCTV|CGTN)[-·]?(\d+[K+]?)(?=[\u4e00-\u9fffA-Za-z]|$)", n, re.I)
    if m:
        return m.group(1).upper() + m.group(2)
    m = re.match(r"^CETV[-·]?(\d+)$", n, re.I)
    if m:
        return "CETV" + m.group(1)
    n = re.sub(r"(?:高清|超清|标清|蓝光|超高清|4K|8K|FHD|HD)$", "", n) or n
    for pre, up in (("newtv", "NEWTV"), ("ihot", "IHOT")):
        if n.lower().startswith(pre):
            return up + n[len(pre):]
    return n

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


def _build_groups(cmap, verified, extra_keep=6):
    """分组构建（write_verified_txt / write_verified_m3u 共用，第十三批下沉）：
    1) 显示名用 ent['name']（聚合键为归一化去重键后，避免输出去重键当频道名）；
    2) 港台组经 hk_clean_sort 清洗排序（黑名单剔除/白名单收视习惯排序/台湾次级）；
    3) RTHK 官方静态源兜底：港台频道实测未通过或缺失时追加官方源（不删除任何已验证线路）。"""
    groups = OrderedDict()
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
    return groups


def write_verified_txt(cmap, verified, path, extra_keep=6):
    """输出 lives/live_verified.txt。分组构建见 _build_groups（第十三批与 m3u 输出共用）。"""
    groups = _build_groups(cmap, verified, extra_keep)
    ORDER = ["央视", "卫视", "港台", "轮播·一起看", "地方", "电台", "网络·其他"]
    with open(path, "w", encoding="utf-8") as f:
        for cls in ORDER:
            if cls not in groups:
                continue
            f.write("%s,#genre#\n" % cls)
            for std, lines in groups[cls].items():
                f.write("%s,%s\n" % (std, "#".join(lines)))
    return {c: len(chs) for c, chs in groups.items()}


def write_verified_m3u(cmap, verified, path, extra_keep=6):
    """输出 lives/live_verified.m3u（第十三批：fanmingming/live 台标/EPG 引用层）。
    与 txt 同源同数据（_build_groups），仅格式不同：
    header 多源 EPG x-tvg-url（7 源冗余，见 FMM_EPG_URLS）+ catchup（zhi35 m3u 生态实证写法）；
    每频道 tvg-name/tvg-logo 引用 live.fanmingming.cn/tv/{名}.png（只引用不镜像，
    fanmingming/live 为 GPL-3.0；个别文件缺失时播放器仅无台标，不影响播放）。
    返回 {组名: 频道数}。"""
    groups = _build_groups(cmap, verified, extra_keep)
    ORDER = ["央视", "卫视", "港台", "轮播·一起看", "地方", "电台", "网络·其他"]
    with open(path, "w", encoding="utf-8") as f:
        f.write('#EXTM3U x-tvg-url="%s" %s\n' % (",".join(FMM_EPG_URLS), FMM_CATCHUP))
        for cls in ORDER:
            if cls not in groups:
                continue
            for name, lines in groups[cls].items():
                logo = fmm_logo_name(name)
                f.write('#EXTINF:-1 tvg-name="%s" tvg-logo="%s%s.png" group-title="%s",%s\n'
                        % (logo, FMM_TV_BASE, logo, cls, name))
                for u in lines:
                    f.write(u + "\n")
    return {c: len(chs) for c, chs in groups.items()}



# ---------------- 第十四批吸收实施（batch10 融合形态 + batch8 P1-1 组播面）：省级组播附录 ----------------
# batch10 结论：239.x/233.x 组播地址仅对应运营商内网（IPTV 机顶盒网络）可达，公网测活无意义
# （Guovin 式 HTTP 测速对组播无效），故不入 live_verified 主列表，单独输出附录文件并带
# 「内网限定」标注；频道名不做归一化合并（各运营商频道集本就不同），仅同名多线路 # 合并。
# 浙江电信源（LionixQ/Zhejiang_Telecom_IPTV）发布形态是 udpxy 占位模板（{{your_udpxy_address}}），
# 附录输出时把 /udp/{组播组} 路径转写为裸 udp:// 组播地址（内网直连等价形态）。
MULTICAST_SOURCES = [
    ("组播·广东电信(内网)",
     "https://gh-proxy.com/https://raw.githubusercontent.com/Tzwcard/ChinaTelecom-GuangdongIPTV-RTP-List/master/GuangdongIPTV_rtp.m3u8"),
    ("组播·北京联通(内网)",
     "https://gh-proxy.com/https://raw.githubusercontent.com/wuwentao/bj-unicom-iptv/master/bj-unicom-iptv.m3u"),
    ("组播·浙江电信(内网)",
     "https://gh-proxy.com/https://raw.githubusercontent.com/LionixQ/Zhejiang_Telecom_IPTV/main/Zhejiang_Multicast/Zhejiang_Multicast.txt"),
]
MULTICAST_URL_RE = re.compile(r"^(rtp|udp|https?)://", re.I)
UDPXY_RE = re.compile(r"^https?://[^/]+/udp/(\d+\.\d+\.\d+\.\d+:\d+)$", re.I)


def _norm_multicast_url(u):
    """udpxy 占位模板 → 裸 udp:// 组播地址；其余形态原样保留。"""
    m = UDPXY_RE.match(u)
    if m:
        return "udp://" + m.group(1)
    return u


def parse_multicast(text):
    """解析组播 m3u / tvbox txt：接受 rtp:// udp:// http(s)://，udpxy 模板转写。
    返回 [(频道名, 组播URL)]。"""
    out = []
    cur = None
    for raw in text.splitlines():
        l = raw.strip()
        if not l:
            continue
        if l.startswith("#EXTINF"):
            m = re.search(r",\s*(.+)$", l)
            cur = m.group(1).strip() if m else None
            continue
        if l.startswith("#"):
            continue
        if MULTICAST_URL_RE.match(l) and "," not in l:
            out.append((cur or "未知频道", _norm_multicast_url(l)))
            cur = None
            continue
        if "," in l:
            name, urls = l.rsplit(",", 1)
            for u in urls.split("#"):
                u = u.strip()
                if MULTICAST_URL_RE.match(u):
                    out.append((name.strip(), _norm_multicast_url(u)))
    return out


def write_multicast_txt(path):
    """输出省级组播附录（lives/live_multicast.txt）。
    不测速（组播公网不可达，测速无意义）、不做跨源频道归一化；
    每组内同名多线路 # 合并；头部注释写内网限定警示与来源
    （tvbox txt 解析器跳过无逗号行，注释行不干扰解析）。返回 {组名: 频道数}。"""
    groups = OrderedDict()
    for gname, url in MULTICAST_SOURCES:
        try:
            status, _h, body = http_get(url, 15)
        except Exception:  # noqa: BLE001
            status, body = 0, None
        if status != 200 or not body:
            print("  [multicast] %s fetch %s，本轮跳过" % (gname, status or "error"), flush=True)
            continue
        chans = OrderedDict()
        for name, u in parse_multicast(body.decode("utf-8", "replace")):
            if not name:
                continue
            lines = chans.setdefault(name, [])
            if u not in lines:
                lines.append(u)
        if chans:
            groups[gname] = chans
        print("  [%s] %d channels" % (gname, len(chans)), flush=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 省级运营商组播附录（第十四批吸收实施：batch10 融合形态 + batch8 P1-1 组播面）\n")
        f.write("# ⚠ 内网限定：rtp://239.x / udp://233.x 组播地址仅对应运营商内网（IPTV 机顶盒网络）可达，公网环境不可播放\n")
        f.write("# 来源：%s\n" % ";".join(u for _g, u in MULTICAST_SOURCES))
        f.write("# 生成：%s\n" % datetime.date.today().isoformat())
        for gname, chans in groups.items():
            f.write("%s,#genre#\n" % gname)
            for name, lines in chans.items():
                f.write("%s,%s\n" % (name, "#".join(lines)))
    return {g: len(c) for g, c in groups.items()}


# ---------------- 吸收点 P2-1：lives 套壳穿透（设计借鉴自参考仓库调研，代码独立实现） ----------------
# TVBox 配置的 lives 条目可能是「壳」：请求 URL 返回体只有一行指向真实播放列表的
# URL。递归跟随穿透（深度 ≤5、visited 防循环），把真实列表并入聚合源；
# sid 锚定原始条目名（cfg:<name>），保证跨日运行时来源标识稳定。
LIVE_SHELL_DEPTH = int(os.environ.get("LIVE_SHELL_DEPTH", "5"))
LIVE_CFG_SOURCES_MAX = int(os.environ.get("LIVE_CFG_SOURCES_MAX", "20"))


def _is_plain_url_list_body(text: str) -> bool:
    """返回体是否为「单行纯 URL」壳（去首尾空白后仅一行且是 http(s) URL）。"""
    t = (text or "").strip()
    if not t or "\n" in t or len(t) > 512:
        return False
    return bool(re.match(r"^https?://\S+$", t))


def follow_live_shell(url: str, visited: set, timeout: int = 15) -> str:
    """跟随套壳：返回最内层真实列表 URL；请求失败返回 ""（放弃该条）。"""
    for _ in range(LIVE_SHELL_DEPTH):
        if url in visited:
            return ""                 # 循环防护
        visited.add(url)
        try:
            status, _h, body = http_get(url, timeout)
        except Exception:  # noqa: BLE001
            return ""
        if status != 200 or not body:
            return ""
        text = body.decode("utf-8", "replace")
        if not _is_plain_url_list_body(text):
            return url                # 已是真实列表内容（m3u / tvbox txt）
        nxt = text.strip()
        url = nxt if nxt != url else ""
        if not url:
            return ""
    return url                        # 达到深度上限：以最后跟随到的 URL 为准


def collect_config_live_sources(repo, max_entries=None):
    """从仓库 tvbox.json 的 lives 条目收集可穿透的直播源（追加进聚合源清单）。"""
    max_entries = max_entries or LIVE_CFG_SOURCES_MAX
    if not repo:
        return []
    cfg_path = os.path.join(repo, "tvbox.json")
    if not os.path.isfile(cfg_path):
        return []
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:  # noqa: BLE001
        return []
    out, seen_urls, visited = [], set(), set()
    for l in (cfg.get("lives") or []):
        if len(out) >= max_entries:
            break
        if not isinstance(l, dict):
            continue
        name = str(l.get("name") or "").strip()
        urls = l.get("url")
        urls = [urls] if isinstance(urls, str) else (urls if isinstance(urls, list) else [])
        for u in urls:
            if not isinstance(u, str) or not re.match(r"^https?://", u.strip()):
                continue
            real = follow_live_shell(u.strip(), visited)
            if not real or real in seen_urls:
                continue
            seen_urls.add(real)
            sid = "cfg:" + (name or re.sub(r"\W+", "-", real)[-24:])
            out.append((sid, real))
            break                     # 每个 lives 条目只取第一条可用 URL
    return out


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
    # 吸收点 P2-1：配置内 lives 条目套壳穿透后并入聚合源（追加在静态源之后）
    cfg_sources = collect_config_live_sources(repo)
    if cfg_sources:
        print("config lives sources: %d collected" % len(cfg_sources), flush=True)
    sources.extend(cfg_sources)
    return sources


def main(repo=None, out_txt="lives/live_verified.txt",
         out_m3u="lives/live_verified.m3u", out_json="live_channels.json",
         out_multicast="lives/live_multicast.txt"):
    repo = repo or os.path.dirname(sys_path)
    sources = build_sources(repo)
    print("loading %d sources ..." % len(sources), flush=True)
    cmap = build_channel_map(sources, repo)
    print("channels: %d" % len(cmap), flush=True)
    t0 = time.time()
    verified, raw = test_channel_lines(cmap, budget_s=420)
    print("line tests done in %.0fs, verified channels: %d" % (time.time() - t0, len(verified)), flush=True)
    stats = write_verified_txt(cmap, verified, os.path.join(repo, out_txt))
    m3u_stats = write_verified_m3u(cmap, verified, os.path.join(repo, out_m3u))
    mc_stats = write_multicast_txt(os.path.join(repo, out_multicast))
    print("groups:", stats, flush=True)
    print("m3u groups:", m3u_stats, flush=True)
    print("multicast groups:", mc_stats, flush=True)
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
