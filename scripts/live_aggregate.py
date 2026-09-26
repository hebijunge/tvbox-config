#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_aggregate.py — 频道级聚合：规范化、分类、多线路合并、逐线路实测。

输入：源级测活通过的 m3u/tvbox-txt 源清单
输出：lives/live_verified.txt（tvbox txt 分组格式，大分类 → 频道 → 多线路 # 合并；
     2026-09-23 分类重构：大分类 = 央视/卫视/地方-省(按地区)/港台/轮播/直播/其他，
     小分类 = 频道条目（如央视组下 CCTV-1 各台），每频道多 URL 可切换线路）
     + lives/live_verified.m3u（第十三批：fanmingming/live 台标/EPG 引用层）
     + live_channels.json 明细
"""
import datetime
import hashlib
import json
import os
import re
import time
import urllib.parse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

sys_path = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, sys_path)
from live_probe import http_get, probe_stream  # noqa: E402

MAX_LINES_PER_CH = int(os.environ.get("LIVE_LINES_MAX_PER_CH", "0"))
CAP = MAX_LINES_PER_CH  # 别名保持下游兼容

def cap_lines(lines, n=CAP):
    """返回 lines；n<=0 表示不限。"""  
    return list(lines) if n <= 0 else list(lines)[:n]


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
    # batch18：live.hacks.tools 四分类（hacks_cctv/hacks_weishi/hacks_difang/chunwan），
    # 线路序排在既有源之后——hacks 线路在频道内作为补充线路排列
    "hacks_cctv", "hacks_weishi", "hacks_difang", "chunwan",
]

HKTW_KW = ("凤凰", "tvb", "翡翠", "明珠", "香港", "无线", "有线", "hib", "rthk",
           "台湾", "民视", "三立", "东森", "中天", "台视", "中视", "华视", "公视",
           "八大", "纬来", "龙华", "靖天", "大爱", "壹电视", "年代", "澳广视", "澳门",
           "tvbs", "好消息", "uhb", "viutv", "viu")

# ---- 2026-09-23 分类层级重构（用户目标口径）----
# 大分类固定七类：央视 / 卫视 / 地方(按地区) / 港台 / 轮播 / 直播 / 其他；
# 小分类 = 频道条目（如「央视」组下 CCTV-1…各台）；多线路 = 每频道多 URL `#` 合并可切换。
# 相比旧口径的变化：
#   1) 「地方」按省级关键词落组（地方-湖南 / 地方-广东 …），组名带「地方-」前缀，
#      输出序跟随 PROVINCE_ORDER；落不进任何省的频道进「其他」。
#   2) 旧「轮播·一起看」拆为两类：直播（虎牙/斗鱼/B站/咪咕/电竞 等平台实时直播）
#      与 轮播（轮播/一起看/歌手 等循环轮播频道）。
#   3) 「电台」不再单独成组，折叠进「其他」（且豁免单线路裁剪，见 LIVE_OTHER_MIN_LINES）。
#   4) CCTV 编号主频道（CCTV-1…CCTV-17/CCTV-5+/CGTN）归「央视」；
#      CCTV 付费/专业频道（怀旧剧场/风云剧场/第一剧场 等）归「其他」。
ZHIBO_KW = ("虎牙", "斗鱼", "哔哩", "b站", "bilibili", "咪咕", "电竞")
LUNBO_KW = ("轮播", "一起看", "歌手")

# 省级关键词表（键=组名后缀，值=命中关键词；顺序即输出顺序，且为归组优先序）。
# 每省收录省名/简称 + 主要地级市；县市级频道未命中的落入「其他」（best-effort，宁缺毋滥）。
# 已知歧义接受项：青海「海南州」会落 地方-海南（数据中未出现，风险可忽略）。
PROVINCE_TABLE = (
    ("北京", ("北京", "卡酷")),
    ("天津", ("天津",)),
    ("河北", ("河北", "石家庄", "保定", "唐山", "邯郸", "沧州", "廊坊", "张家口",
              "衡水", "邢台", "秦皇岛", "承德")),
    ("山西", ("山西", "太原", "大同", "晋中", "运城", "临汾", "长治", "忻州", "吕梁",
              "晋城", "朔州", "阳泉", "太谷")),
    ("内蒙古", ("内蒙古", "呼和浩特", "包头", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔",
                "巴彦淖尔", "乌海", "兴安", "锡林郭勒", "乌兰察布", "阿拉善")),
    ("辽宁", ("辽宁", "沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口",
              "阜新", "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛")),
    ("吉林", ("吉林", "长春", "延边", "通化", "四平", "白山", "松原", "白城", "辽源")),
    ("黑龙江", ("黑龙江", "哈尔滨", "齐齐哈尔", "牡丹江", "佳木斯", "大庆", "鸡西",
                "双鸭山", "伊春", "七台河", "鹤岗", "绥化", "黑河", "大兴安岭")),
    ("上海", ("上海", "哈哈", "炫动")),
    ("江苏", ("江苏", "南京", "苏州", "无锡", "常州", "镇江", "南通", "扬州", "盐城",
              "徐州", "连云港", "淮安", "宿迁", "泰州", "优漫")),
    ("浙江", ("浙江", "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州",
              "舟山", "台州", "丽水", "文成")),
    ("安徽", ("安徽", "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆",
              "黄山", "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城", "宿松")),
    ("福建", ("福建", "福州", "厦门", "泉州", "漳州", "莆田", "三明", "南平", "龙岩",
              "宁德")),
    ("江西", ("江西", "南昌", "九江", "赣州", "景德镇", "萍乡", "新余", "鹰潭", "宜春",
              "上饶", "吉安", "抚州")),
    ("山东", ("山东", "济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁",
              "泰安", "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽")),
    ("河南", ("河南", "郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作",
              "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口",
              "驻马店", "济源")),
    ("湖北", ("湖北", "武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感",
              "荆州", "黄冈", "咸宁", "随州", "恩施", "仙桃", "潜江")),
    ("湖南", ("湖南", "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界",
              "益阳", "郴州", "永州", "怀化", "娄底", "湘西", "金鹰")),
    ("广东", ("广东", "广州", "深圳", "珠海", "汕头", "佛山", "韶关", "湛江", "肇庆",
              "江门", "茂名", "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞",
              "中山", "潮州", "揭阳", "云浮", "珠江", "南方")),
    ("广西", ("广西", "南宁", "柳州", "桂林", "梧州", "北海", "防城港", "钦州", "贵港",
              "玉林", "百色", "贺州", "河池", "来宾", "崇左")),
    ("海南", ("海南", "海口", "三亚", "三沙", "儋州")),
    ("重庆", ("重庆",)),
    ("四川", ("四川", "成都", "绵阳", "德阳", "自贡", "攀枝花", "泸州", "广元", "遂宁",
              "内江", "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中",
              "资阳", "阿坝", "甘孜", "凉山", "夹江")),
    ("贵州", ("贵州", "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "黔东南",
              "黔南", "黔西南")),
    ("云南", ("云南", "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧",
              "大理", "红河", "文山", "西双版纳", "楚雄", "德宏", "怒江", "迪庆")),
    ("西藏", ("西藏", "拉萨", "日喀则", "昌都", "林芝", "山南", "那曲")),
    ("陕西", ("陕西", "西安", "宝鸡", "咸阳", "铜川", "渭南", "延安", "汉中", "榆林",
              "安康", "商洛")),
    ("甘肃", ("甘肃", "兰州", "嘉峪关", "金昌", "天水", "武威", "张掖", "平凉", "酒泉",
              "庆阳", "定西", "陇南", "临夏", "甘南")),
    ("青海", ("青海", "西宁", "海东", "海北", "黄南", "果洛", "玉树", "海西")),
    ("宁夏", ("宁夏", "银川", "石嘴山", "吴忠", "固原", "中卫")),
    ("新疆", ("新疆", "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉",
              "巴音郭楞", "阿克苏", "喀什", "和田", "伊犁", "塔城", "阿勒泰", "石河子",
              "兵团")),
)
COUNTY_PROV = {'诸暨': '浙江', '龙游': '浙江', '龙泉': '浙江', '遂昌': '浙江', '衢江': '浙江', '苍南': '浙江', '缙云': '浙江', '洞头': '浙江', '永嘉': '浙江', '武义': '浙江', '松阳': '浙江', '新昌': '浙江', '开化': '浙江', '庆元': '浙江', '平湖': '浙江', '嵊泗': '浙江', '嵊州': '浙江', '兰溪': '浙江', '余杭': '浙江', '余姚': '浙江', '云和': '浙江', '上虞': '浙江', '萧山': '浙江', '象山': '浙江', '之江': '浙江', '中国蓝': '浙江', '新沂': '江苏', '沭阳': '江苏', '涟水': '江苏', '睢宁': '江苏', '泗洪': '江苏', '泗阳': '江苏', '淮阴': '江苏', '溧水': '江苏', '靖江': '江苏', '宜兴': '江苏', '武进': '江苏', '江宁': '江苏', '句容': '江苏', '如东': '江苏', '光山': '河南', '兰考': '河南', '卫辉': '河南', '叶县': '河南', '唐河': '河南', '固始': '河南', '宝丰': '河南', '巩义': '河南', '扶沟': '河南', '新县': '河南', '新蔡': '河南', '桐柏': '河南', '泌阳': '河南', '淅川': '河南', '渑池': '河南', '温县': '河南', '潢川': '河南', '登封': '河南', '禹州': '河南', '西华': '河南', '郏县': '河南', '郸城': '河南', '鄢陵': '河南', '项城': '河南', '邓州': '河南', '荥阳': '河南', '灵宝': '河南', '滑县': '河南', '沁阳': '河南', '永城': '河南', '方城': '河南', '新野': '河南', '新安': '河南', '嵩县': '河南', '宜阳': '河南', '内黄': '河南', '内乡': '河南', '偃师': '河南', '义马': '河南', '郑州': '河南', '清河': '河北', '鹿泉': '河北', '平泉': '河北', '任丘': '河北', '兴隆': '河北', '昌黎': '河北', '乐至': '四川', '剑阁': '四川', '叙永': '四川', '名山': '四川', '旺苍': '四川', '松潘': '四川', '沐川': '四川', '泸县': '四川', '荥经': '四川', '营山': '四川', '汶川': '四川', '利州': '四川', '筠连': '四川', '金川': '四川', '长宁': '四川', '青神': '四川', '马尔康': '四川', '龙泉驿': '四川', '武胜': '四川', '汉源': '四川', '石棉': '四川', '蓬安': '四川', '叙州': '四川', '夹江': '四川', '垫江': '重庆', '万州': '重庆', '江津': '重庆', '万州三峡移民': '重庆', '德惠': '吉林', '九台': '吉林', '靖宇': '吉林', '敦化': '吉林', '龙井': '吉林', '梅河口': '吉林', '桦甸': '吉林', '磐石': '吉林', '舒兰': '吉林', '东丰': '吉林', '双辽': '吉林', '辉南': '吉林', '柳河': '吉林', '汪清': '吉林', '五台': '山西', '怀仁': '山西', '长子': '山西', '高平': '山西', '渭源': '甘肃', '白银': '甘肃', '陇川': '云南', '岷县': '甘肃', '靖远': '甘肃', '秦安': '甘肃', '贵南': '青海', '化隆': '青海', '可克达拉': '新疆', '通海': '云南', '津南': '天津', '云霄': '福建', '宾阳': '广西', '青州': '山东', '灌阳': '广西', '蒙城': '安徽', '内蒙经济': '内蒙古', '内蒙农牧': '内蒙古', '内蒙少儿': '内蒙古', '蒙语文化': '内蒙古', '德宏': '云南', '吉木萨尔': '新疆', '索伦': '内蒙古', '珲春': '吉林', '安图': '吉林'}

PROVINCE_ORDER = [p for p, _k in PROVINCE_TABLE]

# 输出大分类顺序（用户目标口径）：央视 / 卫视 / 地方(按地区) / 港台 / 轮播 / 直播 / 其他
BIG_ORDER = ("央视", "春晚(季节性)", "卫视", "港台", "轮播", "直播", "其他", "地方")  # 2026-09-24 用户指令：港台/轮播/直播/其他放到地方之上；batch18：春晚(季节性)专项组紧随央视（历史春晚轮播，节假日场景）


def big_cat(cls):
    """内部类名 → 输出大分类名（地方-湖南 → 地方；电台折叠进 其他）。"""
    if cls and cls.startswith("地方-"):
        return "地方"
    if cls == "电台":
        return "其他"
    return cls


def group_sort_key(cls):
    """类名 → 输出排序键 (大分类序, 省序)。
    用于频道类名归并优先级与逐线路实测优先级（央视最先、地方随省序、其他殿后）。"""
    bc = big_cat(cls)
    bi = BIG_ORDER.index(bc) if bc in BIG_ORDER else len(BIG_ORDER)
    pi = 0
    if bc == "地方":
        prov = cls[len("地方-"):]
        pi = PROVINCE_ORDER.index(prov) if prov in PROVINCE_ORDER else len(PROVINCE_ORDER)
    return (bi, pi)


# 其他组长尾裁剪阈值：未验证频道的去重线路数低于该值时不入主列表（env 可调）
LIVE_OTHER_MIN_LINES = int(os.environ.get("LIVE_OTHER_MIN_LINES", "2"))


def _fold_group(cls):
    """内部类名 → 输出组键（电台折叠进 其他，其余原样；地方-省 已是组键形态）。"""
    return "其他" if cls == "电台" else cls


# ---- 成人/违规频道黑名单（2026-09-24 立规；2026-09-25 P0 收口集成改为词表驱动）----
# TVBox 主直播源是家用电视直播，本仓「其他」组之前被大量成人/AV/广告台污染（来自
# aptv、zonghe 等综合源），整体屏蔽：含特征码或关键词。
# 【词表消费对齐（P0 收口集成）】事实源 = state/vocab/categories.json（adult 节：
# name_keywords + name_pure_num/bracket/date 三正则 + host 黑名单），与研发1号
# 词表体系（scripts/live_vocab.py）共用一套词表，本文件只加载不再硬编码——
# 避免双轨两套词表漂移。历轮真机产物补漏沉淀的 14 词 / 35 域 / 6 token 已于
# 2026-09-25 迁入 categories.json（见其 source_note）。

def _load_vocab_adult():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "state", "vocab", "categories.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["adult"]


_VOCAB_ADULT = _load_vocab_adult()
PORN_KW = tuple(_VOCAB_ADULT["name_keywords"])
# 仅命中纯数字短名（如 003/114/239）：来自某些 m3u 的「纯编号台位」，其中混编入大量
# 成人频道——历史上 zero-padded 编号（≤3 位）与上述区段强相关，整体屏蔽
ADULT_PURE_NUM = re.compile(_VOCAB_ADULT["name_pure_num_regex"])
# 【水果派】/【免费】前缀 + 日文 A 片标题特征
ADULT_BRACKET_TAG = re.compile(_VOCAB_ADULT["name_bracket_tag_regex"])
# nXXXX/XXXX-XX-XX 编号台名（含连字符的纯数字/月份日期；前缀 n 为上游客编）
ADULT_DATE_CODE = re.compile(_VOCAB_ADULT["name_date_code_regex"])

def is_adult(name: str) -> bool:
    """判断频道名是否属于成人/AV/广告垃圾——整体不进 live_verified.txt。"""
    return bool(adult_rule_of(name))


def adult_rule_of(name: str) -> str:
    """返回命中规则标签（空字符串=非成人）。供门禁报告带规则可读。"""
    if not name:
        return ""
    low = name.lower()
    for kw in PORN_KW:
        if kw in low:
            return "porn_kw:%s" % kw[:16]
    if ADULT_PURE_NUM.match(low.strip()):
        return "pure_number_station"
    if ADULT_BRACKET_TAG.match(name):
        return "bracket_tag"
    if ADULT_DATE_CODE.match(low.strip()):
        return "date_code"
    return ""


# ---- 2026-09-24 源头级 VOD 过滤（用户 2026-09-24 指令）----
# 「live.json 整理还有成人资源，从源头剔除，不然后面一堆归类错的，好多地方里都被污染了」
# 在 parse_m3u / parse_tvbox_txt 出口就丢弃明确的 VOD 视频点播与 AV 番号行——
# 比 build_channel_map 下游 is_adult 过滤早一步，能把 ~30% 的脏数据在聚合前拦掉，
# 大幅降低下游归一化/去重/分组/测速的负担，避免错归类污染其他组。
# 设计要点：
#   1) 只识别「明确属于 VOD/AV」的行——综艺/常规长频道名一律放过（避免误伤歌手/连续剧等）；
#   2) 下游 build_channel_map 的 is_adult() 保留作为兜底，处理厂牌关键词（Carib/1Pondo/FC2 等）；
#   3) AV 番号严格化：dash 后必须 3-8 位数字 + 空白/行尾——避免 CCTV-1/10/11 这种
#      「合法短编号 TV 频道」被误杀（dash 后是 1-2 位数字不命中）；
#   4) 不影响 adult_live 独立通道——ADULT_LIVE_SOURCES / probe_adult_lives / adult.json
#      由 fetch_merge.py 独立维护，不经过此处的 parse_m3u / parse_tvbox_txt。
_VOD_URL_RE = re.compile(
    r"/video/m3u8/\d{4}/\d{2}/\d{2}/"            # 日期桶 CDN：cdn2020.com / ttbfp 等点播 m3u8
    r"|/ph[0-9a-f]{8,}/play\.m3u8"                # 散列文件名点播 m3u8
    r"|/ph5[0-9a-f]{8,}/"                        # ph5 开头 CDN 路径
    r"|cdnedge\.live/file/"                       # cdnedge.live 点播文件
    r"|/file/avple-images/"                       # avple 图床/视频目录
    r"|/video/av\d+"                              # /video/av1234 形式 AV 视频
    r"|slbfsl\.com/\d{8}/"                        # slbfsl 点播日期桶
    r"|\.cdn2020\.com/video/m3u8/"                # cdn2020 视频 m3u8（主命中模式）
    r"|maa1804\.com/f/"                           # maa1804 成人视频 CDN
    # 2026-09-25 用户指令：去掉 .mp4/快手 VOD 规则过滤（kwimgs.com/bs3/video-hls|upic/）
    # ——该规则会误杀 hacks 春晚频道的历史录像（21 条中 19 条为快手 CDN 点播文件）。
    # 点播/失效行由下游逐行探测兜底剔除，不再在源头按 URL 特征丢弃。
    r"|redtraffic\."                              # redtraffic 系列（成人流量统计/广告）
    r"|adultiptv\.net/"                           # adultiptv.net（成人 IPTV 列表）
    r"|/live/(?:pornstar|bigass|hardcore|bbw|amateur|hentai)\.m3u8"  # 明确成人分类直播 m3u8
    r"|/f/[a-z0-9]{10,}\.m3u8$",                  # 短哈希 m3u8 文件
    re.IGNORECASE,
)
# AV 番号严格模式：厂牌 + dash + 3-8 位数字 + 空白/行尾
# 覆盖：SSNI-240/SONE-071/FC2PPV-1209497/MIAA-247/JUFE-104/Heyzo-2094 等
# 不命中：CCTV-1/10/11/12（dash 后 1-2 位数字）/CCTV-5+（带 + 号非纯数字）
_AV_NUMBER_RE = re.compile(r"^[A-Z]{2,6}[-−]\d{3,8}(?:\s|$)", re.IGNORECASE)


def _drop_vod_row(name, url):
    """源头级判定（parse_m3u / parse_tvbox_txt 出口处调用）：
    命中返回丢弃原因字符串，不命中返回 False。综艺/常规长频道名一律不丢。"""
    if not url:
        return False
    if _VOD_URL_RE.search(url):
        return "VOD_URL"
    if name and _AV_NUMBER_RE.match(name):
        return "AV_NUMBER"
    return False


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

# 【词表消费对齐（P0 收口集成）】繁简归一事实源 = state/vocab/normalization.json
# （t2s 表，研发1号词表体系维护）；内置 S2T_MAP 为离线兜底（CI 词表缺失时仍可用）。
# 取并集去重：词表与内置值零冲突（已核对），并集后归一键更全（745+9 字）。
def _load_vocab_t2s():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "state", "vocab", "normalization.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("t2s", {})
    except Exception:  # noqa: BLE001  词表缺失/损坏时退回内置 83 字
        return {}


S2T_MAP.update(_load_vocab_t2s())

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
    """规范化频道名，返回 (标准名, 分类)。
    分类为大分类名或地方子组名（地方-湖南），输出序见 BIG_ORDER/PROVINCE_ORDER：
    央视(CCTV 编号主频道/CGTN) → 港台 → 卫视 → 直播(平台实时) → 轮播(循环频道)
    → 电台 → 地方-省 → 其他（CCTV 付费/专业频道、未命中省份的县市频道、网络频道）。"""
    n = (name or "").strip()
    if not n:
        return "", ""
    low = n.lower().replace(" ", "").replace("\u3000", "")
    # 2026-09-24 修复：先整段剥 [bd]/[hd]/[sd] 等短来源标签（含方括号），防「[BD]cctv1」剥完只剩 bdcctv1、匹配不上 ^cctv 而漏并进 CCTV-1
    low = re.sub(r"\[[a-z0-9]{1,4}\]", "", low)
    # 2026-09-24 修复：剥无括号的 bd/vga 等画质/来源前缀（后跟中文才剥，防误伤英文台名开头）
    # ——freetv.fun 上游产生「bd浙江卫视」「vga宁夏卫视」类变体，不剥会与标准台名分裂（用户截图实证）
    low = re.sub(r"^(?:bd|vga|hd|sd|fhd|uhd|4k|8k)[-–—]?(?=[\u4e00-\u9fff])", "", low)
    # 2026-09-24 兜底：剥残留的 tvg-id= 属性前缀（parse_m3u 已修根因，此处防历史数据/其他路径）
    low = re.sub(r'^tvg-(?:id|name)="?', "", low)
    low = re.sub(r"[\[\]()（）【】「」]|超清|高清|标清|蓝光|1080p?|720p?|4k|50fps?|60fps?|hd|sd|fhd|测试", "", low)
    # 2026-09-26 修复（用户实证 CCTV-1 裂成 5 个名字）：编号主频道归一化提前到
    # startswith 兜底之前——旧代码 startswith("cctv") 提前 return，下方编号正则是
    # 死代码，「CCTV1 / CCTV-1 / CCTV-01咪咕 / CCTV-1综合」从不归一、同一 URL 挂在
    # 多个变体名下。描述性后缀并入主频道；亚洲/欧洲/美洲（CCTV-4 分版）不在后缀
    # 表，保持独立频道不受影响。
    m = re.match(r"^cctv[-−]?0*(\d{1,2})(\+?)"
                 r"(?:咪咕)?(?:综合|财经|综艺|体育|体育赛事|电影|国防军事|电视剧|纪录|科教"
                 r"|戏曲|社会与法|新闻|少儿|音乐|农业农村|奥林匹克|中文国际)?$", low)
    if m and (1 <= int(m.group(1)) <= 17 or m.group(2)):
        return "CCTV-%d%s" % (int(m.group(1)), m.group(2)), "央视"
    m = re.match(r"^cetv[-−]?0*(\d{1,2})"
                 r"(?:咪咕)?(?:综合教育|空中课堂|教育服务|职业教育)?$", low)
    if m and 1 <= int(m.group(1)) <= 5:
        return "CETV-%d" % int(m.group(1)), "央视"
    # 2026-09-24：所有「CCTV」「央视」前缀的频道（含付费/专业频道）一律归「央视」组
    if low.startswith("cctv") or low.startswith("央视") or low.startswith("cetv"):
        return name.strip(), "央视"
    if low.startswith(("cgtn", "cgtv")):
        return "CGTN", "央视"
    if any(k in low for k in HKTW_KW):
        return n, "港台"
    if "卫视" in low:
        base = low[:low.index("卫视") + 2]
        return base, "卫视"
    if any(k in low for k in ZHIBO_KW):
        return n, "直播"
    if any(k in low for k in LUNBO_KW):
        return n, "轮播"
    if re.search(r"电台|fm\d*$|广播", low):
        return n, "电台"
    # 2026-09-24：先按县级表归组（精度高于省级关键词，命中即落省）
    for c, p in COUNTY_PROV.items():
        if c in n:
            return n, "地方-" + p
    for prov, kws in PROVINCE_TABLE:
        if any(k in low for k in kws):
            return n, "地方-" + prov
    return n, "其他"


def parse_m3u(text):
    """解析 m3u 文本，返回 [(频道名, url), ...]。
    2026-09-24 源头级过滤：URL 是 VOD 视频点播或频道名是 AV 番号的行直接丢弃
    ——下游 build_channel_map 早一步拿到干净数据，避免脏数据污染其他组归类。"""
    out = []
    cur = None
    for l in text.splitlines():
        l = l.strip()
        if not l:
            continue
        if l.startswith("#EXTINF"):
            # 2026-09-24 修复：显示名取最后一个逗号之后（rsplit）——上游存在把
            # tvg-id/tvg-name 属性写在第一个逗号后的非标准行（如
            # #EXTINF:-1,tvg-id="河北卫视" ...,河北卫视），旧逻辑取第一个逗号会截到
            # 属性串，产生「tvg-id="河北卫视」脏频道名（用户截图实证）。
            # 标准 m3u 显示名恒在最后一个逗号后；属性含逗号常见、显示名含逗号罕见。
            parts = l.rsplit(",", 1)
            cur = parts[1].strip() if len(parts) == 2 and parts[1].strip() else None
        elif l.startswith("#"):
            continue
        elif re.match(r"^https?://", l):
            if _drop_vod_row(cur, l):
                cur = None
                continue
            out.append((cur or "未知频道", l))
            cur = None
    return out


def parse_tvbox_txt(text):
    """解析 tvbox txt 文本（每行：频道名,url1#url2#url3），返回 [(频道名, url), ...]。
    2026-09-24 源头级过滤：URL 是 VOD 视频点播或频道名是 AV 番号的 url 直接丢弃。"""
    out = []
    for l in text.splitlines():
        l = l.strip()
        if not l or l.endswith("#genre#") or "," not in l:
            continue
        name, urls = l.rsplit(",", 1)
        n = name.strip()
        for u in urls.split("#"):
            u = u.strip()
            if re.match(r"^https?://", u):
                if _drop_vod_row(n, u):
                    continue
                out.append((n, u))
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
    # batch18：live.hacks.tools 分类 URL → sid（供配置穿透等路径识别来源）
    if "live.hacks.tools" in u:
        if "央视" in urllib.parse.unquote(u):
            return "hacks_cctv"
        if "卫视" in urllib.parse.unquote(u):
            return "hacks_weishi"
        if "地方" in urllib.parse.unquote(u):
            return "hacks_difang"
        if "春晚" in urllib.parse.unquote(u):
            return "chunwan"
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


# 2026-09-26：URL 自证频道号提取（cctv5 / cctv5p / cctv5+；cctv4k/cctv1hd 不命中）
_CCTV_URL_TOKEN = re.compile(r"cctv[-_]?0*(\d{1,2})(\+?)(p)?(?:hd)?(?=[\./_?&=\-]|$)")


def _name_url_conflict(std, u):
    """URL 自证频道与归属名冲突检测（用户实证：rthk33 线路混进 CCTV-1、
    cctv5p 线路混进 CCTV-5——URL 自己说明是别的频道时该行必是错误合并）。
    仅对已归一的编号主频道（CCTV-1…17 / CCTV-5+）生效，其余频道一律放行。"""
    lu = (u or "").lower()
    ls = (std or "").lower()
    if not lu.startswith(("http://", "https://")):
        return False
    mn = re.match(r"^cctv-(\d{1,2})(\+?)$", ls)
    if mn:
        if "rthk" in lu or "cetv" in lu or "cgtn" in lu:
            return True
        mu = _CCTV_URL_TOKEN.search(lu)
        if mu:
            if int(mu.group(1)) != int(mn.group(1)):
                return True  # cctv2 的线路挂到 CCTV-1 名下
            url_plus = bool(mu.group(2) or mu.group(3))
            if url_plus != bool(mn.group(2)):
                return True  # cctv5p(=CCTV-5+) 的线路挂到 CCTV-5（或反向）
        return False
    return False


def _merge_channel_rows(cmap, rows, sid):
    """把一组 (频道名, URL) 行按统一口径并入 cmap（build_channel_map 内循环抽取）：
    norm_channel 归类 → is_adult(名) → is_adult_url(URL) → dedup_key 聚合键 →
    URL 级去重。iptvorg 晋升流汇入（merge_iptvorg_promoted）复用同一口径。"""
    for name, u in rows:
        std, cls = norm_channel(name)
        if not std:
            continue
        # batch18：春晚历史轮播专项分组（hacks 春晚源，seasonal）——
        # 「xxxx年春晚」类频道 norm_channel 落不进任何大分类，会散入「其他」；
        # 这里按来源强制落「春晚(季节性)」专项组（组序见 BIG_ORDER）
        if sid == "chunwan" and "春晚" in (name or ""):
            cls = "春晚(季节性)"
        # 2026-09-24：成人/AV/广告台整体剔除（不进 live_verified.txt，也不进 adult.json——后者由 ADULT_LIVE 单独维护）
        if is_adult(std) or is_adult(name):
            continue
        # 2026-09-25 P0-2 成人隔离红线·第三重判定：频道 URL 命中 adult 根域黑名单即整行剔除
        if is_adult_url(u):
            continue
        # 2026-09-26：URL 自证频道与归属名冲突拒收（rthk33 混进 CCTV-1、cctv5p 混进 CCTV-5）
        if _name_url_conflict(std, u):
            continue
        # 2026-09-21 直播线融合：聚合键用归一化去重键（繁简/别名/后缀），
        # 显示名保留首次出现的 std，避免「翡翠台/翡翠/Tvb翡翠」裂成三个频道
        key = dedup_key(std)
        ent = cmap.setdefault(key, {"name": std, "class": cls, "lines": [],
                                    "_seen": set()})
        if group_sort_key(cls) < group_sort_key(ent["class"]):
            ent["class"] = cls
        # 2026-09-23 分类重构：频道内 URL 级去重——同一 URL 被多条上游重复收录
        # 时只记一条（旧口径下未实测频道会出现 6 条一模一样的「假线路」）
        if u not in ent["_seen"]:
            ent["_seen"].add(u)
            ent["lines"].append((sid, u))


def build_channel_map(sources, repo):
    cmap = OrderedDict()
    for sid, url in sources:
        chans = load_source(sid, url, repo)
        print("  [%s] %d channels" % (sid, len(chans)), flush=True)
        _merge_channel_rows(cmap, chans, sid)
    return cmap


# ---- 2026-09-25 P1 收口：iptv-org canary 晋升流汇入 ----
# 数据源：state/upstreams/iptvorg.normal.json（canary_promote.py --promote 产物，
# 形态与 extra_upstreams.json 同构：{"generated_at", "upstreams":[{name,url,...}]}）。
# 汇入口径与 adult 三重红线完全同链：① 每条先过 _is_adult_source(sid,url,name)
# （源级词表正则）；② _merge_channel_rows 内 is_adult(名) + is_adult_url(URL)；
# ③ norm_channel + dedup_key 与其余上游同一聚合键（繁简/别名/后缀归一 + URL 去重）。
# 文件缺失 / 为空 / 损坏一律 no-op（首晋升前 state/upstreams/ 尚不存在，不报错）。
IPTVORG_PROMOTED_PATH = os.path.join("state", "upstreams", "iptvorg.normal.json")


def load_iptvorg_promoted(repo):
    """读 canary 晋升产物，返回 [(name, url)]。缺失/空/损坏 → []（no-op）。"""
    path = os.path.join(repo, IPTVORG_PROMOTED_PATH)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rows = []
        for ent in (data or {}).get("upstreams") or []:
            if not isinstance(ent, dict):
                continue
            u = (ent.get("url") or "").strip()
            name = (ent.get("name") or "").strip()
            if u and name:
                rows.append((name, u))
        return rows
    except FileNotFoundError:
        return []
    except Exception as e:  # noqa: BLE001  损坏不阻断聚合，照常 no-op
        print("[iptvorg] promoted 文件读取失败（忽略，no-op）: %s" % e, flush=True)
        return []


def merge_iptvorg_promoted(cmap, repo):
    """把 iptv-org 晋升频道并入聚合 cmap，返回并入条数（0=文件缺失/全过滤）。"""
    rows = load_iptvorg_promoted(repo)
    if not rows:
        return 0
    kept = [(n, u) for n, u in rows
            if not _is_adult_source("iptvorg", u, n)]
    dropped = len(rows) - len(kept)
    if dropped:
        print("[iptvorg] promoted 源级 adult 过滤剔除 %d 条" % dropped, flush=True)
    if not kept:
        return 0
    before = sum(len(v["lines"]) for v in cmap.values())
    _merge_channel_rows(cmap, kept, "iptvorg")
    after = sum(len(v["lines"]) for v in cmap.values())
    print("[iptvorg] promoted 汇入 %d 条（新增线路 %d）" % (len(kept), after - before),
          flush=True)
    return after - before


def _is_core_class(cls):
    """逐线路实测范围（预算内）：央视 / 卫视 / 港台 / 地方-省。
    轮播/直播/其他 不逐线路实测（量级太大且多为平台源），沿用既有行为口径；
    jobs 按输出序排序后提交，预算耗尽时优先保住央视/卫视/港台的实测覆盖。"""
    return cls in ("央视", "卫视", "港台", "春晚(季节性)") or cls.startswith("地方-")


PROGRESS_PATH = os.environ.get("LIVE_PROGRESS_PATH", os.path.join("state", "live_test_progress.jsonl"))
PROGRESS_TTL_OK_S = int(os.environ.get("LIVE_PROGRESS_TTL_OK_S", str(20 * 3600)))
PROGRESS_TTL_FAIL_S = int(os.environ.get("LIVE_PROGRESS_TTL_FAIL_S", str(4 * 3600)))
SOURCE_HARD_TIMEOUT_S = float(os.environ.get("LIVE_SOURCE_TIMEOUT_S", "40"))


def _pkey(std, u):
    """progress 键：频道归一化键 + URL 的稳定哈希（跨 run 可续跑）。"""
    return hashlib.sha1(("%s|%s" % (std, u)).encode("utf-8")).hexdigest()[:16]


def load_progress(path=PROGRESS_PATH):
    """读 progress.jsonl → {pkey: (ok, ts, ms)}。坏行跳过。"""
    ent = {}
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                    ent[str(r.get("k"))] = (bool(r.get("ok")), float(r.get("ts", 0) or 0),
                                            float(r.get("ms", 0) or 0))
                except Exception:  # noqa: BLE001
                    continue
    except FileNotFoundError:
        pass
    return ent


def append_progress(rows, path=PROGRESS_PATH):
    """追加快测记录行 [{k,ok,ms,why}]。目录不存在自动建。"""
    if not rows:
        return
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    now = time.time()
    with open(path, "a", encoding="utf-8") as f:
        for k, ok, ms, why in rows:
            f.write(json.dumps({"k": k, "ok": bool(ok), "ms": round(ms, 3),
                                "why": why, "ts": now}, ensure_ascii=False) + "\n")


def shard_select(key, shard):
    """分片轮转：shard 形如 "i/n"；按 key 的 sha1 稳定取模。None / "0/1" = 全量。
    跨 run 轮转 i 即可在 n 轮内覆盖全量频道（hash 稳定，与频道增删无关）。"""
    if not shard:
        return True
    try:
        i, n = str(shard).split("/")
        i, n = int(i), int(n)
    except Exception:  # noqa: BLE001
        return True
    if n <= 1:
        return True
    return int(hashlib.sha1(str(key).encode("utf-8")).hexdigest(), 16) % n == i % n


def test_channel_lines(cmap, max_test=MAX_LINES_PER_CH,
                     budget_s=int(os.environ.get("LIVE_PROBE_BUDGET_S", "600")),
                     shard=None, progress=None, progress_path=PROGRESS_PATH):
    """核心频道逐线路实测，返回 {标准名: [通过 url]} 与全部明细。

    P0-3 测速与发布解耦（2026-09-25）：
      - shard "i/n"：频道按归一化键稳定分片，本轮只实测第 i 片（跨 run 轮转覆盖全量）；
      - progress_path：progress.jsonl 可续跑——ok 记录 TTL（默认 20h）内直接消费缓存、
        不再探流；fail 记录短 TTL（默认 4h）内跳过（到期自动重试）；
      - 单源硬超时 LIVE_SOURCE_TIMEOUT_S（默认 40s）：单上游线路累计探流超时后，
        该源剩余线路本轮跳过（记 why=source-timeout，不写 progress，下轮自动重试），
        防止单个慢源吃穿全局预算。"""
    t0 = time.time()
    prog = load_progress(progress_path) if progress is None else dict(progress)
    jobs = []
    n_shard_skip = 0
    for std, ent in cmap.items():
        if not _is_core_class(ent["class"]):
            continue
        if not shard_select(std, shard):
            n_shard_skip += 1
            continue
        lines = sorted(ent["lines"], key=lambda x: (SOURCE_PRIORITY.index(x[0])
                        if x[0] in SOURCE_PRIORITY else 99))
        seen, uniq = set(), []
        for sid, u in lines:
            if u not in seen:
                seen.add(u)
                uniq.append((sid, u))
        ent["lines"] = uniq
        jobs.append((std, cap_lines(uniq, max_test) if max_test > 0 else uniq))
    # 2026-09-23 分类重构：实测任务按输出序（央视→卫视→港台→地方-省）提交，
    # 预算耗尽时优先保证靠前大分类的实测覆盖
    jobs.sort(key=lambda j: group_sort_key(cmap[j[0]]["class"]))
    results = {}
    n = [0]
    n_cached = [0]
    sid_elapsed = {}
    sid_skipped = set()
    prog_rows = []

    def _probe_timed(u):
        """带计时的单线路实测（2026-09-23 线路按速度排序）：
        复用同一次 probe_stream 请求，取成功探流耗时（首包 2KB，秒）作速度依据。"""
        _t = time.time()
        try:
            ok, why = probe_stream(u)
        except Exception:
            ok, why = False, "error"
        return ok, why, time.time() - _t

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {}
        for std, lines in jobs:
            if time.time() - t0 > budget_s:
                break
            for sid, u in lines:
                if time.time() - t0 > budget_s:
                    break
                k = _pkey(std, u)
                hit = prog.get(k)
                if hit is not None:
                    ok, ts, ms = hit
                    ttl = PROGRESS_TTL_OK_S if ok else PROGRESS_TTL_FAIL_S
                    if time.time() - ts < ttl:
                        results.setdefault(std, []).append((u, ok, "cache", ms))
                        n_cached[0] += 1
                        n[0] += 1
                        continue
                # 单源硬超时：该源累计探流耗时超限，本轮剩余线路不再提交（下轮重试）
                if sid in sid_skipped or sid_elapsed.get(sid, 0.0) > SOURCE_HARD_TIMEOUT_S:
                    sid_skipped.add(sid)
                    results.setdefault(std, []).append((u, False, "source-timeout", 0.0))
                    continue
                futs[ex.submit(_probe_timed, u)] = (std, u, sid)
            if time.time() - t0 > budget_s:
                break
        # 2026-09-25 修复：预算只挡提交侧挡不住——submit 非阻塞，全部任务数秒内入队，
        # 4400+ 条以 8 并发实跑 70min 撞死 job 90min 超时（9/23 起多轮 run cancelled 实证）。
        # 收集侧同样受预算约束：预算耗尽即停止收集并取消未起跑任务，确保函数在预算内返回。
        for fut in as_completed(futs):
            if time.time() - t0 > budget_s:
                break
            std, u, sid = futs[fut]
            ok, why, ms = fut.result()
            sid_elapsed[sid] = sid_elapsed.get(sid, 0.0) + ms
            results.setdefault(std, []).append((u, ok, why, ms))
            if why != "source-timeout":
                prog_rows.append({"k": _pkey(std, u), "ok": ok, "ms": ms, "why": why})
            n[0] += 1
            if n[0] % 50 == 0:
                print("  tested %d lines (cached %d) ..." % (n[0], n_cached[0]), flush=True)
        cancelled = sum(1 for f in futs if f.cancel())
    append_progress([tuple(r[k2] for k2 in ("k", "ok", "ms", "why")) if isinstance(r, dict)
                     else r for r in prog_rows], progress_path)
    if prog_rows:
        print("  progress: +%d rows, shard=%s shard_skip_ch=%d, source_timeout=%d"
              % (len(prog_rows), shard or "-", n_shard_skip, len(sid_skipped)), flush=True)
    verified = {}
    for std, lst in results.items():
        # 线路按速度升序：实测通过者按探流耗时小→大排列（同一频道内首条=最快线路，
        # 播放器默认取首条、卡顿可手动切后继线路）；未通过的线路不进 verified。
        good = sorted(((u, ms) for u, ok, _w, ms in lst if ok), key=lambda x: x[1])
        if good:
            verified[std] = cap_lines([u for u, _ms in good])
    return verified, results


def name_sort_key(name):
    """组内频道排序键（2026-09-24 用户指令：所有分组内频道按首字母排序）：
    中文转拼音、英数保留，数字段按数值自然序（CCTV-2 < CCTV-10）。
    pypinyin 转写失败退回原名字典序。"""
    try:
        from pypinyin import lazy_pinyin
        s = "".join(lazy_pinyin(name or "")).lower()
    except Exception:
        s = (name or "").lower()
    parts = re.split(r"(\d+)", s)
    return tuple((1, int(p), "") if p.isdigit() else (0, p, "") for p in parts)


_URL_STATUS_PATH = os.path.join("state", "live_pool_url_status.json")


def _load_url_status():
    """live-pool-prune 持久化的 URL 探活状态 {url: http_code}；缺失/损坏一律空表。"""
    try:
        with open(_URL_STATUS_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _alive_rank(u, status):
    """线路排序键：探活存活(200/206)排前，其余（未测/连不上/403 等）保持原序殿后。"""
    return 0 if status.get(u) in (200, 206) else 1


def _build_groups(cmap, verified, extra_keep=6):
    """分组构建（write_verified_txt / write_verified_m3u 共用，第十三批下沉）：
    1) 显示名用 ent['name']（聚合键为归一化去重键后，避免输出去重键当频道名）；
    2) 组键 = 大分类名或 地方-省 子组（电台折叠进 其他）；
    3) 其他组长尾裁剪（2026-09-23 分类重构）：未验证且去重线路数 < LIVE_OTHER_MIN_LINES
       的频道不入主列表——实测数据 18196 条网络长尾中 17473 条为单去重线路未验证频道，
       全量保留会淹没多线路可用频道；电台豁免（量小且为功能性内容）；
    4) 港台组经 hk_clean_sort 清洗排序（黑名单剔除/白名单收视习惯排序/台湾次级）；
    5) RTHK 官方静态源兜底：港台频道实测未通过或缺失时追加官方源（不删除任何已验证线路）；
    6) 2026-09-24 不限上限：verified 频道保留已实测线路（按速度序），其后补回未实测的剩余
       线路（不限条数），让"有多少可用就显示多少"对未测完频道同样生效。"""
    # 2026-09-26（用户反馈线路排序乱）：未实测线路用 prune 持久化的探活状态排序，
    # 存活(200/206)置顶、原相对顺序不变（稳定排序）；已实测频道的速度序保持不动。
    _status = _load_url_status()
    groups = OrderedDict()
    for key, ent in cmap.items():
        name = ent.get("name") or key
        gk = _fold_group(ent["class"])
        if key in verified:
            tested = list(verified[key])           # 已实测，按速度升序
            tested_set = set(tested)
            untested = [u for _s, u in ent["lines"] if u not in tested_set]
            untested.sort(key=lambda _u: _alive_rank(_u, _status))
            lines = tested + cap_lines(untested, 0)  # 0=无限制
        else:
            n_distinct = len({u for _s, u in ent["lines"]})
            if ent["class"] == "其他" and n_distinct < LIVE_OTHER_MIN_LINES:
                continue  # 其他组长尾裁剪：单线路未验证频道不进主列表
            _ls = [u for _sid, u in ent["lines"]]
            _ls.sort(key=lambda _u: _alive_rank(_u, _status))
            lines = cap_lines(_ls, extra_keep)
        groups.setdefault(gk, OrderedDict())
        if lines:
            groups[gk][name] = lines
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
                    groups["港台"][found] = [static_url] + cap_lines(lines)
            else:
                groups["港台"][nm] = [static_url]
    # 2026-09-24 用户指令：所有分组内频道按首字母（拼音）排序——
    # 统一覆盖各组插入序（含港台组 hk_clean_sort 的习惯序：剔除逻辑保留、排序以拼音为准）
    for gk in groups:
        groups[gk] = OrderedDict(
            sorted(groups[gk].items(), key=lambda kv: name_sort_key(kv[0])))
    return groups


def _iter_ordered_groups(groups):
    """输出序（2026-09-23 用户目标口径）：央视 → 卫视 → 地方-省（按 PROVINCE_ORDER
    华北→东北→华东→中南→西南→西北）→ 港台 → 轮播 → 直播 → 其他。
    产出 (组名, 频道dict)。"""
    for cat in BIG_ORDER:
        if cat == "地方":
            for prov in PROVINCE_ORDER:
                gk = "地方-" + prov
                if groups.get(gk):
                    yield gk, groups[gk]
        elif groups.get(cat):
            yield cat, groups[cat]


def write_verified_txt(cmap, verified, path, extra_keep=CAP):
    """输出 lives/live_verified.txt。分组构建见 _build_groups（第十三批与 m3u 输出共用）。"""
    groups = _build_groups(cmap, verified, extra_keep)
    # 2026-09-23 用户口径修正：同 write_precise_txt，同台名逐行重复（线路1/2/3 可切换）。
    with open(path, "w", encoding="utf-8") as f:
        for gname, chans in _iter_ordered_groups(groups):
            f.write("%s,#genre#\n" % gname)
            for std, lines in chans.items():
                for _u in lines:
                    f.write("%s,%s\n" % (std, _u))
    return {c: len(chs) for c, chs in groups.items()}


def write_precise_txt(cmap, verified, path):
    """输出 lives/live_precise.txt（2026-09-23 用户指令：更精准的版本）。
    只收逐线路实测通过的频道（verified 键），频道内全部线路已按探流耗时升序
    （首条=最快，播放器默认取首条）；未实测/实测未通过的频道一律不入精准版。
    分组与输出序同 live_verified.txt（央视→卫视→地方-省→港台→轮播→直播→其他），
    港台组沿用 hk_clean_sort 清洗排序。返回 {组名: 频道数}。"""
    groups = OrderedDict()
    for std in verified:
        ent = cmap.get(std)
        if not ent:
            continue
        gk = _fold_group(ent["class"])
        name = ent.get("name") or std
        groups.setdefault(gk, OrderedDict())
        groups[gk][name] = list(verified[std])
    if "港台" in groups:
        groups["港台"] = hk_clean_sort(groups["港台"])
    # 2026-09-23 用户口径修正：线路不挤在一行 # 拼接，改为同台名逐行重复——
    # 播放器对同名行自动合并为一个台，切线路时显示「线路1/线路2/线路3」。
    with open(path, "w", encoding="utf-8") as f:
        for gname, chans in _iter_ordered_groups(groups):
            f.write("%s,#genre#\n" % gname)
            for name, lines in chans.items():
                for _i, _u in enumerate(lines, 1):
                    f.write("%s,%s\n" % (name, _u))
    return {c: len(chs) for c, chs in groups.items()}


def write_verified_m3u(cmap, verified, path, extra_keep=CAP):
    """输出 lives/live_verified.m3u（第十三批：fanmingming/live 台标/EPG 引用层）。
    与 txt 同源同数据（_build_groups），仅格式不同：
    header 多源 EPG x-tvg-url（7 源冗余，见 FMM_EPG_URLS）+ catchup（zhi35 m3u 生态实证写法）；
    每频道 tvg-name/tvg-logo 引用 live.fanmingming.cn/tv/{名}.png（只引用不镜像，
    fanmingming/live 为 GPL-3.0；个别文件缺失时播放器仅无台标，不影响播放）。
    返回 {组名: 频道数}。"""
    groups = _build_groups(cmap, verified, extra_keep)
    with open(path, "w", encoding="utf-8") as f:
        f.write('#EXTM3U x-tvg-url="%s" %s\n' % (",".join(FMM_EPG_URLS), FMM_CATCHUP))
        for gname, chans in _iter_ordered_groups(groups):
            for name, lines in chans.items():
                logo = fmm_logo_name(name)
                f.write('#EXTINF:-1 tvg-name="%s" tvg-logo="%s%s.png" group-title="%s",%s\n'
                        % (logo, FMM_TV_BASE, logo, gname, name))
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
            # 2026-09-24 修复：显示名取最后一个逗号之后（rsplit）——上游存在把
            # tvg-id/tvg-name 属性写在第一个逗号后的非标准行（如
            # #EXTINF:-1,tvg-id="河北卫视" ...,河北卫视），旧逻辑取第一个逗号会截到
            # 属性串，产生「tvg-id="河北卫视」脏频道名（用户截图实证）。
            # 标准 m3u 显示名恒在最后一个逗号后；属性含逗号常见、显示名含逗号罕见。
            parts = l.rsplit(",", 1)
            cur = parts[1].strip() if len(parts) == 2 and parts[1].strip() else None
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


# ---- 2026-09-24 源列表级成人过滤(用户指令:仓库名/文件名明显就整源剔除)----
# 高命中源:fish2018/lib(天美/果冻/麻豆/星空/精东/国产传媒/pron/成人传媒/live18/18资源
# /至尊/终极/Jable/18+/成人电影/美腿丝袜/经典/珍藏/绝品/vip源/花活 等)、FGBLH/HKL 与
# FGBLH/fgrjk(日本女优 1-12 / EVILANGEL / FC2-PPV / 午夜剧场 / xxx视频资源 等)、
# atsushi444/iptv-epg/Adult.m3u、
# zwrt/IPTV/Files/Adult.m3u、jable.tv、几个传媒、cloud.7so.top/RO04U5/丽颖琼姿.m3u 等。
# 筛选原则:只放明确的高置信词,防止误伤正常源。
ADULT_SOURCE_RE = re.compile(
    # (Kimentanm/aptv 已于 11:0x 经实测纠正:iptv.m3u 全部为央视28/卫视37/历年春晚44/4K8K11,零成人内容,移回正常源)
    r"/Adult\.m3u8?$"
    r"|fish2018/lib"
    r"|FGBLH/(?:HKL|fgrjk)"
    r"|jable\.tv"
    r"|几个传媒"
    r"|/天美传媒|/果冻传媒|/麻豆传媒|/星空传媒|/精东影业"
    r"|pron\.m3u|国产传媒|成人传媒|live18|18资源丰富|18\+"
    r"|/色播|/大洋马|/大秀|/色诱|/色播聚合|/麻豆视频|/台湾成人"
    r"|FC2-PPV|EVILANGEL|xxx视频资源|午夜剧场|丽颖琼姿"
    r"|jable\.tv/|Jable嗅探|维护成人",
    re.IGNORECASE,
)


def _is_adult_source(sid: str, url: str, name: str = "") -> bool:
    """判定单个上游源是否为明显成人源——sid+url+name 任一命中即整源跳过。"""
    blob = " ".join([sid or "", url or "", name or ""])
    return bool(ADULT_SOURCE_RE.search(blob))


# ---- 2026-09-25 P0-2 adult 隔离红线·第三重判定：域名黑名单 ----
# 域名清单按「实际产物」提取（用户 2026-09-25 指令）：根域来自仓库内 adult 实际产物
# （adult.json / adult_live.json / adult_live_channels.json 5372 频道）的播放/接口域名
# 频次统计，取根域后缀匹配；裸 IP 不入表（无法归因根域）。由 scripts/export_rules.py
# 与本常量同步导出 rules/adult_host_blacklist.json。
# 【词表消费对齐（P0 收口集成）】事实源已迁至 state/vocab/categories.json
# （adult.host_blacklist_exact / host_blacklist_tokens / host_blacklist_pattern /
# shared_cdn_no_blacklist），本文件只加载；iptvxxx.net 因与 shared_cdn_no_blacklist
# 冲突按误伤防护不收黑名单。共用 CDN 白名单命中直接放行（防误伤正常频道）。
ADULT_HOSTS = tuple(_VOCAB_ADULT["host_blacklist_exact"])
# 子串级 token：匹配任意后缀变体（missav.ws / missav.zone …）或出现在 host 中的标记词
ADULT_HOST_TOKENS = tuple(_VOCAB_ADULT["host_blacklist_tokens"])
_ADULT_HOST_RE = re.compile(_VOCAB_ADULT["host_blacklist_pattern"], re.IGNORECASE)
# 精选域名后缀匹配（词表 host_blacklist_exact；生产实证清单，优先级最高、不适用共用 CDN 豁免）
_ADULT_HOST_EXACT_RE = re.compile(
    r"(?:^|\.)(?:" + "|".join(re.escape(h) for h in ADULT_HOSTS) + r")$",
    re.IGNORECASE,
)
_SHARED_CDN_DOMAINS = tuple(_VOCAB_ADULT.get("shared_cdn_no_blacklist", []))


def _is_shared_cdn_host(host: str) -> bool:
    """host 落在共用 CDN 白名单（注册域后缀命中）→ 不按成人 token 处理（防误伤）。"""
    return any(host == d or host.endswith("." + d) for d in _SHARED_CDN_DOMAINS)


def is_adult_url(u: str) -> bool:
    """URL 域名级成人判定（P0-2 第三重判定）。判定序：
    ① 词表精选域名后缀命中 → True（生产实证，不受共用 CDN 豁免影响）；
    ② 共用 CDN 白名单命中 → False（防误伤正常频道）；
    ③ 词表边界正则（含 token）命中 → True；非法 URL 放行给上游判定层。"""
    if not u:
        return False
    try:
        host = (urlparse(u if "//" in u else "//" + u, scheme="http").hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    if not host:
        return False
    if _ADULT_HOST_EXACT_RE.search(host):
        return True
    if _is_shared_cdn_host(host):
        return False
    return bool(_ADULT_HOST_RE.search(host))



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
        if name and _is_adult_source("", "", name):
            print("  [adult-source-skip] name=%s" % name, flush=True)
            continue
        urls = l.get("url")
        urls = [urls] if isinstance(urls, str) else (urls if isinstance(urls, list) else [])
        for u in urls:
            if not isinstance(u, str) or not re.match(r"^https?://", u.strip()):
                continue
            real = follow_live_shell(u.strip(), visited)
            if not real or real in seen_urls:
                continue
            if _is_adult_source("", real, name) or is_adult_url(real):
                print("  [adult-source-skip] url=%s name=%s" % (real[:80], name), flush=True)
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
        # batch18（2026-09-25）吸收实施：live.hacks.tools 四分类（调研批 P0/P1 结论落地，
        # task 7689228802869693633）。当日实测：央视 21 / 卫视 35 / 地方 188 / 春晚 21 条。
        # 该站 Cloudflare 对非 okhttp 指纹返回 400——本仓 http_get 默认 UA okhttp/3.15 实测可通。
        # 路径含中文，一律 percent-encode 供 urllib 直连。
        ("hacks_cctv", "https://live.hacks.tools/tv/ipv4/categories/%E5%A4%AE%E8%A7%86%E9%A2%91%E9%81%93.m3u"),
        ("hacks_weishi", "https://live.hacks.tools/tv/ipv4/categories/%E5%8D%AB%E8%A7%86%E9%A2%91%E9%81%93.m3u"),
        ("hacks_difang", "https://live.hacks.tools/tv/ipv4/categories/%E5%9C%B0%E6%96%B9%E9%A2%91%E9%81%93.m3u"),
        ("chunwan", "https://live.hacks.tools/tv/ipv4/categories/%E6%98%A5%E6%99%9A%E9%A2%91%E9%81%93.m3u"),
    ])
    # 吸收点 P2-1：配置内 lives 条目套壳穿透后并入聚合源（追加在静态源之后）
    cfg_sources = collect_config_live_sources(repo)
    if cfg_sources:
        print("config lives sources: %d collected" % len(cfg_sources), flush=True)
    sources.extend(cfg_sources)
    before = len(sources)
    sources = [(sid, u) for sid, u in sources
               if not _is_adult_source(sid, u, "") and not is_adult_url(u)]
    dropped = before - len(sources)
    if dropped:
        print("  [adult-source-drop] total %d source(s) filtered at build_sources" % dropped, flush=True)
    return sources


def write_group_m3us(cmap, verified, outdir, extra_keep=CAP):
    """P0-1 按组输出独立 m3u 文件（2026-09-25）：lives/groups/<组名>.m3u。
    每文件 = #EXTM3U 头（同 live_verified.m3u 的多源 EPG/catchup）+ 该组全部频道
    （#EXTINF group-title=<组名>，行序/内容与 live_verified.txt 完全同源）。
    大分类组：央视/卫视/港台/轮播/直播/其他 + 春晚(季节性)；地方按省各出
    地方-<省>.m3u。返回 {组名: 频道数}。"""
    groups = _build_groups(cmap, verified, extra_keep)
    os.makedirs(outdir, exist_ok=True)
    stats = {}
    for gname, chans in _iter_ordered_groups(groups):
        fn = os.path.join(outdir, "%s.m3u" % gname)
        with open(fn, "w", encoding="utf-8") as f:
            f.write('#EXTM3U x-tvg-url="%s" %s\n' % (",".join(FMM_EPG_URLS), FMM_CATCHUP))
            for name, lines in chans.items():
                logo = fmm_logo_name(name)
                f.write('#EXTINF:-1 tvg-name="%s" tvg-logo="%s%s.png" group-title="%s",%s\n'
                        % (logo, FMM_TV_BASE, logo, gname, name))
                for u in lines:
                    f.write(u + "\n")
        stats[gname] = len(chans)
    # 清掉本轮已不再产出的旧组文件，防上轮组残留误导消费方
    for fn in os.listdir(outdir):
        if fn.endswith(".m3u") and fn[:-4] not in stats:
            try:
                os.remove(os.path.join(outdir, fn))
            except OSError:
                pass
    return stats


def _save_live_checks(repo, cmap, verified, shard, group_stats, test_meta):
    """测速快照（P0-3 发布/测速解耦的介质）：
    state/live_checks.json = 可离线重建全部直播产物的完整快照（channels 全量 +
    verified 已测线路），state/live_check_meta.json = 轻量新鲜度标记（fetch_merge
    据此决定是否消费最近一次成功测速结果）。"""
    st = os.path.join(repo, "state")
    os.makedirs(st, exist_ok=True)
    # 2026-09-26 修复：本文件为 import datetime 模块导入，此处误写 datetime.now()
    # 令 speedtest shard 实测跑完后在 meta 落盘处崩溃（live-speedtest run #5 实证）
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    doc = {"updated": now, "shard": shard or None, "group_stats": group_stats,
           "test": test_meta,
           "verified": {k: list(v) for k, v in verified.items()},
           "channels": {k: {"name": v.get("name") or k, "class": v.get("class", ""),
                            "lines": [list(x) for x in v.get("lines", [])]}
                        for k, v in cmap.items()}}
    with open(os.path.join(st, "live_checks.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    with open(os.path.join(st, "live_check_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"updated": now, "shard": shard or None,
                   "channels": len(cmap), "verified_channels": len(verified),
                   "test": test_meta}, f, ensure_ascii=False, indent=1)


def _load_live_checks(repo, path=None):
    """读测速快照重建 cmap-lite / verified（--reuse-results 离线重建用）。
    返回 (cmap, verified, meta)；文件缺失/损坏返回 None。"""
    p = path or os.path.join(repo or ".", "state", "live_checks.json")
    try:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        cmap = OrderedDict()
        for k, v in doc["channels"].items():
            cmap[k] = {"name": v.get("name") or k, "class": v.get("class", ""),
                       "lines": [tuple(x) for x in v.get("lines", [])], "_seen": set()}
        return cmap, doc.get("verified", {}), doc
    except Exception:  # noqa: BLE001
        return None


def main(repo=None, out_txt="lives/live_verified.txt",
         out_m3u="lives/live_verified.m3u", out_json="live_channels.json",
         out_multicast="lives/live_multicast.txt",
         out_precise="lives/live_precise.txt",
         shard=None, reuse_results=None):
    """shard: "i/n" 分片轮转实测（None=全量）；reuse_results: 测速快照路径，
    传入则零网络离线重建全部直播产物（自包含重建能力 + 发布消费测速解耦）。"""
    repo = repo or os.path.dirname(sys_path)
    t_start = time.time()
    if reuse_results:
        got = _load_live_checks(repo, reuse_results)
        if not got:
            print("[live] reuse-results 快照不可用（%s），回退完整聚合" % reuse_results, flush=True)
        else:
            cmap, verified, _meta = got
            print("[live] 复用测速快照：%d 频道 / %d 已验证" % (len(cmap), len(verified)), flush=True)
            stats = write_verified_txt(cmap, verified, os.path.join(repo, out_txt))
            write_precise_txt(cmap, verified, os.path.join(repo, out_precise))
            write_verified_m3u(cmap, verified, os.path.join(repo, out_m3u))
            gstats = write_group_m3us(cmap, verified, os.path.join(repo, "lives", "groups"))
            print("groups:", stats, flush=True)
            print("group m3u:", gstats, flush=True)
            _save_live_checks(repo, cmap, verified, "reuse", stats, {"mode": "reuse"})
            return cmap, verified

    sources = build_sources(repo)
    print("loading %d sources ..." % len(sources), flush=True)
    cmap = build_channel_map(sources, repo)
    # 2026-09-25 P1 收口：iptv-org canary 晋升流汇入（adult 三重红线同口径）。
    # 放在其余上游之后并入：norm_channel/dedup_key 聚合键与 URL 级去重会自动
    # 与既有频道合并或新增频道；无晋升产物时 no-op。
    n_iptvorg = merge_iptvorg_promoted(cmap, repo)
    print("channels: %d (iptvorg promoted lines: %d)" % (len(cmap), n_iptvorg),
          flush=True)
    t0 = time.time()
    verified, raw = test_channel_lines(cmap, budget_s=420, shard=shard)
    n_probe = sum(1 for _u, _ok, w, _ms in
                  (x for lst in raw.values() for x in lst) if w not in ("cache", "source-timeout"))
    n_cache = sum(1 for _u, _ok, w, _ms in
                  (x for lst in raw.values() for x in lst) if w == "cache")
    print("line tests done in %.0fs, verified channels: %d" % (time.time() - t0, len(verified)), flush=True)
    stats = write_verified_txt(cmap, verified, os.path.join(repo, out_txt))
    precise_stats = write_precise_txt(cmap, verified, os.path.join(repo, out_precise))
    print("precise groups:", precise_stats, flush=True)
    m3u_stats = write_verified_m3u(cmap, verified, os.path.join(repo, out_m3u))
    gstats = write_group_m3us(cmap, verified, os.path.join(repo, "lives", "groups"))
    mc_stats = write_multicast_txt(os.path.join(repo, out_multicast))
    print("groups:", stats, flush=True)
    print("m3u groups:", m3u_stats, flush=True)
    print("group m3u:", gstats, flush=True)
    print("multicast groups:", mc_stats, flush=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "verified": verified,
            "group_stats": stats,
            "channels": {k: {"class": v["class"], "n_lines": len(v["lines"]),
                             "lines": [u for _s, u in v["lines"][:10]]}
                         for k, v in cmap.items()},
        }, f, ensure_ascii=False, indent=1)
    _save_live_checks(repo, cmap, verified, shard, stats,
                      {"mode": "full", "probed": n_probe, "cached": n_cache,
                       "test_seconds": round(time.time() - t0, 1),
                       "total_seconds": round(time.time() - t_start, 1)})
    return cmap, verified


if __name__ == "__main__":
    _shard = os.environ.get("LIVE_SHARD")
    _reuse = None
    _args = sys.argv[1:]
    if "--reuse-results" in _args:
        _reuse = _args[_args.index("--reuse-results") + 1]
    if "--shard" in _args:
        _shard = _args[_args.index("--shard") + 1]
    main(shard=_shard, reuse_results=_reuse)
