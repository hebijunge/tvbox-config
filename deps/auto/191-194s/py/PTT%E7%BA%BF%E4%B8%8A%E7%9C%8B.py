# -*- coding: utf-8 -*-
# ============ 71us 模板 v7.5 / ptt2.my(枫林网系 成人站) ============
# 站点: https://ptt2.my (繁中, Yii2 框架, 非 MacCMS; 裸 / 是"继续访问"入口门且返回 500)
# 路由: 首页 /enter | 分类 /p/{1电影,3电视剧,4动漫,2综艺,66短剧,53体育} | 二级 /p/{t}/c/{n}(电影用 ?area_id={n})
#       年份 ?year=YYYY | 分页 ?page=N | 详情 /{id} | 播放 /{id}/{集}/{线路}
# 字段: 详情页 JSON-LD(application/ld+json) 一次给全 name/description/thumbnailUrl/uploadDate/contentUrl
# 播放: <source src=".../index.m3u8"> 明文内嵌, CDN 裸请求 200 + #EXTM3U, 无防盗链 -> 直连输出
# 搜索: /node/search 恒 503(站方下线), /?wd= 不透传过滤 -> searchContent 优雅返空
# 分页: Yii2 LinkPager 仅显示 current±2 且越界页码被 clamp 到末页 -> 探测 ?page=999999 读 active 页号
# 定版: 71us模板v7.4(555骨架+能力层) + 勃士13接口四壳协议 | 2026-09-07
# 13接口=init/homeContent/categoryContent/detailContent/searchContent/playerContent/localProxy/isVideoFormat/manualVideoCheck/getDependence/destroy/progressVideo/setVideoFlags
# 四壳通用: TVBox/T4(只认555五接口) / 海阔/影视仓1.x(额外调扩展钩子) / 独立加载(无base.spider走兜底)
# ★自动调用协议(套本模板写源/修复/重构/逆向=自动触发, 先过清单再动手, 缺一不可):
# ①记忆库检索: query_memory『知识库/影视源开发』→《py源开发技能清单v18》(v18>v17>v16), 开工即查
# ②技能包12包分层调度(/sdcard/Download/Operit/skills/):
#   L0骨架 tvbox-py-v73(本模板) | L1入口 pySkill(spider-create全类型7内容) | L2攻坚 gpt56全家桶(eni/INDEX.md路由90项+kit冷咖啡+five_blade五刃)+reverse-skill(87技能逆向路由)+遮天九秘_破甲版(zhetian.py/cf-bypass/aes-decrypt)+遮天法3.0(3.0+规范/十铁律/v3.1十五修复/角色卡) | L3质量 adaptive四工作台(播放契约/响应边界/图片资源/清洗规范化)并行套用 | L4交付 wei-ai-xiao-ge(影视仓加载契约/测试矩阵)+jk-lingyu-spider(MacCMS/Txmojia样本)
# ③交付铁律: py_compile → 555契约字段(coding/sys.path/class Spider(Spider)/init(extend)/homeContent/homeVideoContent/searchContent/categoryContent/playerContent) → 模拟T4全调用链 → 播放链验证 → 双份md5一致
# 用法: 只改 ★ 区(CONFIG/init), 其余通用; 站点无某项能力直接省略对应方法调用
# 加载契约: 首行coding/sys.path.append('..')/from base.spider import Spider(带兜底)/class Spider(Spider)
# ★版本兼容铁律: 全文件禁3.9+API(random.randbytes/removeprefix/removesuffix等; OK影视内置Python≤3.8教训2026-09), 随机字节用bytes([random.randrange(1,256)]), 交付前grep -n 'randbytes'自查
# ★分隔符铁律: $=名称/地址 | #=选集 | $$$=线路; 严禁$$或$连选集; 线路名与地址$$$段数必须相等
# ★链路策略v4: 资源默认直连输出, 仅403/防盗链/KEY404/需特殊头才走 localProxy 兜底
import sys, re, json, time, base64, hashlib, threading, http.server, socket, struct, unicodedata
from urllib.parse import urljoin, quote, unquote, urlencode
from concurrent.futures import ThreadPoolExecutor
import requests

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = requests.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r

# ============ ★ CONFIG ============
# ★ 模板档位(源出处自证): 'adult'=成人站全量脱敏档 | 'normal'=正常站精简脱敏档
#   写源时按站型设定; 接手/读源时据此判断脱敏档; 两档不得混用(见 SKILL.md)
TEMPLATE_MODE = 'adult'
HOSTS = ['https://ptt2.my']  # ★ 主域(本站裸 / 是入口门, 列表一律走 /enter 或 /p/{t})
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
CATEGORIES = {'1': '电影', '3': '电视剧', '4': '动漫', '2': '综艺', '66': '短剧', '53': '体育'}  # ★ 一级
# ★ 筛选表(静态, 实测 2026-10-06 抓各分类页得到; 站方改 id 时同步更新)
#   tid -> [(key, 显示名, [(项名, 值片段)...])]; 值片段 'c/19'->路径 /p/3/c/19, 'area_id=2'->查询
FILTERS_RAW = {
    '1': [('area', '地区', [('全部', ''), ('大陆', 'area_id=2'), ('香港', 'area_id=5'), ('台湾', 'area_id=4'),
                            ('韩国', 'area_id=17'), ('日本', 'area_id=18'), ('欧美', 'area_id=6'),
                            ('泰国', 'area_id=10'), ('印度', 'area_id=14'), ('其他', 'area_id=3')])],
    '2': [('area', '地区', [('全部', ''), ('大陆', 'c/15'), ('台湾', 'c/89'), ('香港', 'c/88'),
                            ('日本', 'c/90'), ('韩国', 'c/91'), ('欧美', 'c/18'), ('其他', 'c/16')])],
    '3': [('area', '地区', [('全部', ''), ('大陆', 'c/19'), ('香港', 'c/20'), ('台湾', 'c/81'),
                            ('日本', 'c/83'), ('韩国', 'c/82'), ('欧美', 'c/22'), ('泰国', 'c/92'),
                            ('其他', 'c/23')])],
    '4': [('area', '地区', [('全部', ''), ('大陆', 'c/26'), ('日本', 'c/86'), ('韩国', 'c/87'),
                            ('欧美', 'c/27'), ('其他', 'c/28')])],
    '66': [('area', '类型', [('全部', ''), ('爽剧', 'c/67'), ('言情', 'c/68'), ('穿越', 'c/70'),
                             ('悬疑', 'c/71'), ('古装', 'c/73'), ('都市', 'c/80'), ('甜宠', 'c/84'),
                             ('恋爱', 'c/85'), ('其他', 'c/74')])],
    '53': [('area', '类型', [('全部', ''), ('足球', 'c/54'), ('篮球', 'c/55'), ('游戏', 'c/59'),
                             ('撞球', 'c/63'), ('网球', 'c/64'), ('其他', 'c/93')])],
}
FILTER_YEARS = [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016]  # ★ 实测站点提供 11 个年份
PK = ''  # ★ 无签名/无加密
REFERER = 'https://ptt2.my/enter'  # ★ 请求 Referer
PIC_REFERER = ''  # ★ 图片防盗链Referer(空=无)
# ★★ 图片转码代理: 本站封面 **100% 是 .avif**(实测 list/detail/首页 共 122 张全是 avif, 站内无 jpg/webp 变体,
#    也不认 ?format=jpg 之类的转码参数), 而不少壳/播放器(Android<12 的 Glide、Flutter Skia 等)解不了 AVIF
#    -> 表现为"封面图全不显示/裂图". 这里用公共图片 CDN 服务端转成 JPEG 再给壳.
#    实测(i0.wp.com = WordPress Photon): 真封面 -> 有效 JPEG(0xffd8ff), 24~31KB, .cc 源 0.6s.
#    - 前缀式: 'https://i0.wp.com/'  (i1/i2/i3 同效, 可轮换)
#    - 模板式: 'https://wsrv.nl/?url={url}&output=jpg'  (注意 wsrv 封禁 .cc, 需配 IMG_HOST='ptt2.my', 约 7s)
#    - 置 '' 则直连原图(输出 AVIF, 只有能解 AVIF 的壳才显示)
IMG_PROXY = 'https://i0.wp.com/'
# ★ 图片 CDN 主机: 列表卡片用的就是它(pttimg.*.cc); 详情页 JSON-LD 给的是 ptt2.my/images(实测慢 3~6s), 统一换过来
IMG_HOST = 'pttimg.7132p.cc'
FD_ZONE = 0  # ★ 无 .fd 分片协议
PROBE = 0  # ★ 详情多线路实测排序开关 1/0
PAGE_MINLEN = 4000  # ★ 本站响应偶发截断(列表页正常约 57KB, 详情 60~70KB), 低于 4KB 视为截断重试
SITE_KEY = 'ptt2'  # ★ 壳源标识
VIDEO_EXTS = 'm3u8|mp4|flv|mkv|avi|ts'  # ★ isVideoFormat判定扩展名(竖线分隔)

# ============ ★ 脱敏词黑名单(固化v2.1, 全源通用) ============
# 命中即丢弃该条目(vod_name); 分类名/简介 命中同样丢弃; detailContent 命中直接返回空; 宁多勿漏
# v2 增强(词库固化): NFKC归一 + 零宽字符剥离 + 间隔符压缩 + 变体/黑话/emoji 命中,
#   可拦 '鸡·巴' / 'ｊｂ' / '🍆' / '骨 科' 一类规避写法; 单字(上/做/进/含)不参与判定, 防误伤
# 扩展方式: 往 BLOCK_KW(主词) 或 BLOCK_VAR(变体黑话) 加词即全源生效;
#   BLOCK_CIDS 填站点级需屏蔽的分类标识(写法: '8' / 'cate25' / '/category/xyfq/' / '618013.xyz_8');
#   v2.1 起母版已内置 _cid_blocked(), homeContent/categoryContent 自动拦截, 站点侧无需再手写
BLOCK_KW = [
    # —— 未成年 / 幼态 ——
    '幼女', '幼齿', '萝莉', '未成年', '小学生', '中学生', '儿童', '小孩子', '女童', '男童',
    '正太', '少男', '童装', '稚嫩', '学生妹', '幼态', '童颜', '萝莉控', '幼幼', '幼交',
    # —— 非自愿 / 迷药 / 偷拍 ——
    '强奸', '轮奸', '迷奸', '下药', '迷药', '迷晕', '昏迷', '捡尸', '偷拍', '偷窥',
    '针孔', '试衣间', '更衣室', '厕所偷', '迷魂', '催情', '春药', '听话水', '乖乖水',
    '非自愿', '强上', '强暴', '霸王硬上弓',
    # —— 乱伦 / 近亲 ——
    '乱伦', '母子', '父女', '兄妹', '姐弟', '近亲',
    # —— 兽交 ——
    '兽交', '人兽', '动物交', '兽奸',
    # —— 违法事件 ——
    '门事件', '艳照门', '艳照',
    # —— 器官(直白, 命中即成人内容) ——
    '鸡巴', '肉棒', '阳具', '大屌', '龟头', '小穴', '骚穴', '肉缝', '后穴',
    '淫水', '爱液', '精液', '白浊', '奶子', '巨乳', '爆乳', '阴蒂',
    # —— 行为(直白) ——
    '口交', '肛交', '深喉', '口活', '口爆', '内射', '颜射', '射精',
    '潮吹', '打飞机', '自慰', '抽插', '乳交', '足交', '群交', '轮交',
    # —— 状态 / 口味 ——
    '发骚', '发浪', '浪叫', '娇喘',
    # —— 道具 / 发行 ——
    '跳蛋', '按摩棒', '假阳具', '肛塞', '情趣用品', '无码', '里番',
    # —— 补充: 站点分类名泛化黑话(源自实战源, 已剔除正常剧名高频词, 低误伤) ——
    '福利姬', '母狗', '性奴', '成人综艺', '鬼父', '淫母', '嫂子诱惑', '小姨子',
    '爷孙', '臀后', '拳交', '凌辱', '调教', '媚黑', '骚逼', '人妖', '伪娘',
    '禁漫', '性爱', '淫娃', '淫欲', '情趣', '骚播',
]
BLOCK_VAR = [
    # 变体 / 黑话 / 谐音(归一压缩后匹配, 纯中文, 防误伤)
    '骨科', '近亲相奸', '母子乱', '父女乱', '兄妹乱', '姐弟乱',
    '视奸', '迷魂水', '苍蝇水', '厕所偷窥', '走光偷拍',
    '牛头人', '绿帽', '群p', '多p', '双飞',
    '几把', '牛子', '品玉', '舔穴', '观音坐莲', '毒龙钻',
    '制服诱惑', '原味内裤', '开档', '成人片', '成人影片', '成人视频', 'av女优',
]
BLOCK_CIDS = set()  # ★ 站点级: 需屏蔽的分类标识(如未成年专区), 按站填; 写法兼容见 _cid_tail


def _cid_tail(x):
    """取分类标识末段: 'cate25/'->'cate25' | '/category/xyfq/'->'xyfq' | '618013.xyz_8'->'8'"""
    s = str(x or '').strip().strip('/')
    if not s:
        return ''
    s = s.split('/')[-1]
    if '_' in s:
        s = s.split('_')[-1]
    return s.lower()


def _cid_blocked(tid):
    """站点级分类屏蔽: 与 BLOCK_CIDS 任一元素末段相同即拦截
    兼容 '8' / 'cate25' / '/category/xyfq/' / '618013.xyz_8' / 'cate25/' 多种写法;
    纯数字 tid 额外与 'cate{num}' 互认(如 tid='25' 命中 BLOCK_CIDS={'cate25'})"""
    t = _cid_tail(tid)
    if not t:
        return False
    for c in BLOCK_CIDS:
        ct = _cid_tail(c)
        if ct and (ct == t or (t.isdigit() and ct == 'cate' + t)):
            return True
    return False


# 零宽字符(最常见的规避手法, 肉眼不可见): U+200B/200C/200D/FEFF/2060 + 软连字符
_BLOCK_ZW = '\u200b\u200c\u200d\ufeff\u2060\u00ad'
# 间隔符: 压缩后再匹配, 破 '鸡·巴' / '鸡 巴' / '鸡*巴' / '鸡。巴' 类插符规避
_BLOCK_SEP = '\u00b7\u2022.*-_=~|/\\+ \t\r\n\u3000\u3001\u3002'
# emoji 强信号(成人内容惯用替代写法)
_BLOCK_EMOJI = '\U0001F346\U0001F34C\U0001F952\U0001F414\U0001F351\U0001F4A6\U0001F445\U0001F336'
_BLOCK_ZW_RE = re.compile('[' + _BLOCK_ZW + ']')
_BLOCK_SEP_RE = re.compile('[' + re.escape(_BLOCK_SEP) + ']')
# 英文/拼音缩写: 必须带词边界, 防 'mp3player' 命中 '3p' / 'contra' 命中 'ntr'
_BLOCK_ASCII_RE = re.compile(r'(?<![a-z0-9])(?:j8|jb|3p|4p|5p|ntr|lolita|loli)(?![a-z0-9])')


def _norm(text):
    """归一化: NFKC(全角转半角/兼容字符展开) + 剥零宽字符 + 转小写"""
    t = unicodedata.normalize('NFKC', str(text))
    return _BLOCK_ZW_RE.sub('', t).lower()


def _blocked(text):
    """脱敏词命中判定: 命中返回 True(应丢弃); 抗 全角/零宽/间隔符/黑话/emoji 规避"""
    if not text:
        return False
    raw = str(text)
    if _BLOCK_ZW_RE.search(raw):        # 夹零宽字符 = 刻意规避, 直接丢
        return True
    t = _norm(raw)
    sq = _BLOCK_SEP_RE.sub('', t)       # 压缩间隔符: '鸡·巴' -> '鸡巴'
    for k in BLOCK_KW:
        if k in t or k in sq:
            return True
    for k in BLOCK_VAR:
        if k in t or k in sq:
            return True
    if _BLOCK_ASCII_RE.search(t):       # 英文缩写(带词边界)
        return True
    for e in _BLOCK_EMOJI:              # emoji 强信号
        if e in raw:
            return True
    return False


# ============ AES 纯Python引擎(Crypto不可用时降级) ============
# ★性能实测(2026-10): 本引擎仅 ~0.02 MB/s。解密接口返回的小串够用;
#   若站点把【图片/大文件】整体AES加密, 纯Python解密一张400KB图要 ~20s, 不可用 ——
#   此时必须走 pycryptodome 快路径:
#     try: from Crypto.Cipher import AES; from Crypto.Util.Padding import unpad
#     except ImportError: AES = None   # 降级到本引擎
#   并对解密结果做 md5 缓存(同一URL不重复解密)。参考实现见 007吃瓜 源。
SBOX = [99, 124, 119, 123, 242, 107, 111, 197, 48, 1, 103, 43, 254, 215, 171, 118, 202, 130, 201, 125, 250, 89, 71, 240, 173, 212, 162, 175, 156, 164, 114, 192, 183, 253, 147, 38, 54, 63, 247, 204, 52, 165, 229, 241, 113, 216, 49, 21, 4, 199, 35, 195, 24, 150, 5, 154, 7, 18, 128, 226, 235, 39, 178, 117, 9, 131, 44, 26, 27, 110, 90, 160, 82, 59, 214, 179, 41, 227, 47, 132, 83, 209, 0, 237, 32, 252, 177, 91, 106, 203, 190, 57, 74, 76, 88, 207, 208, 239, 170, 251, 67, 77, 51, 133, 69, 249, 2, 127, 80, 60, 159, 168, 81, 163, 64, 143, 146, 157, 56, 245, 188, 182, 218, 33, 16, 255, 243, 210, 205, 12, 19, 236, 95, 151, 68, 23, 196, 167, 126, 61, 100, 93, 25, 115, 96, 129, 79, 220, 34, 42, 144, 136, 70, 238, 184, 20, 222, 94, 11, 219, 224, 50, 58, 10, 73, 6, 36, 92, 194, 211, 172, 98, 145, 149, 228, 121, 231, 200, 55, 109, 141, 213, 78, 169, 108, 86, 244, 234, 101, 122, 174, 8, 186, 120, 37, 46, 28, 166, 180, 198, 232, 221, 116, 31, 75, 189, 139, 138, 112, 62, 181, 102, 72, 3, 246, 14, 97, 53, 87, 185, 134, 193, 29, 158, 225, 248, 152, 17, 105, 217, 142, 148, 155, 30, 135, 233, 206, 85, 40, 223, 140, 161, 137, 13, 191, 230, 66, 104, 65, 153, 45, 15, 176, 84, 187, 22]
IS = [0] * 256
for _i, _v in enumerate(SBOX):
    IS[_v] = _i
RCON = [1, 2, 4, 8, 16, 32, 64, 128, 27, 54, 108, 216, 171, 77]
G2 = [0] * 256
G3 = [0] * 256
for _i in range(256):
    _t = _i << 1
    if _i & 128:
        _t ^= 0x11b
    G2[_i] = _t
    G3[_i] = G2[_i] ^ _i


def _ke(k):
    nk = len(k) // 4
    nr = nk + 6
    w = [list(k[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = w[i - 1][:]
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            t = [SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w


def _enc(b, w):
    s = [[b[r + 4 * c] for c in range(4)] for r in range(4)]
    def add(r):
        for i in range(4):
            for j in range(4):
                s[i][j] ^= w[r * 4 + j][i]
    def sub():
        for i in range(4):
            for j in range(4):
                s[i][j] = SBOX[s[i][j]]
    def sh():
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]
    def mx():
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = G2[a[0]] ^ G3[a[1]] ^ a[2] ^ a[3]
            s[1][c] = a[0] ^ G2[a[1]] ^ G3[a[2]] ^ a[3]
            s[2][c] = a[0] ^ a[1] ^ G2[a[2]] ^ G3[a[3]]
            s[3][c] = G3[a[0]] ^ a[1] ^ a[2] ^ G2[a[3]]
    add(0)
    nr = len(w) // 4 - 1
    for rnd in range(1, nr):
        sub()
        sh()
        mx()
        add(rnd)
    sub()
    sh()
    add(nr)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _gm(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        a = (a << 1) ^ 0x11b if a & 0x80 else a << 1
        b >>= 1
    return p & 0xff


def _dec(b, w):
    s = [[b[r + 4 * c] for c in range(4)] for r in range(4)]
    def add(r):
        for i in range(4):
            for j in range(4):
                s[i][j] ^= w[r * 4 + j][i]
    def isub():
        for i in range(4):
            for j in range(4):
                s[i][j] = IS[s[i][j]]
    def ish():
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]
    def imx():
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _gm(a[0], 14) ^ _gm(a[1], 11) ^ _gm(a[2], 13) ^ _gm(a[3], 9)
            s[1][c] = _gm(a[0], 9) ^ _gm(a[1], 14) ^ _gm(a[2], 11) ^ _gm(a[3], 13)
            s[2][c] = _gm(a[0], 13) ^ _gm(a[1], 9) ^ _gm(a[2], 14) ^ _gm(a[3], 11)
            s[3][c] = _gm(a[0], 11) ^ _gm(a[1], 13) ^ _gm(a[2], 9) ^ _gm(a[3], 14)
    nr = len(w) // 4 - 1
    add(nr)
    for rnd in range(nr - 1, 0, -1):
        ish()
        isub()
        add(rnd)
        imx()
    ish()
    isub()
    add(0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def aes_ecb(data, key, mode=1):
    w = _ke(key)
    out = b''
    if mode:
        pad = 16 - len(data) % 16
        data += bytes([pad]) * pad
        for i in range(0, len(data), 16):
            out += _enc(data[i:i + 16], w)
    else:
        for i in range(0, len(data), 16):
            out += _dec(data[i:i + 16], w)
        if out and 0 < out[-1] <= 16:
            out = out[:-out[-1]]
    return out


def aes_cbc(data, key, iv, enc=1):
    w = _ke(key)
    out = b''
    prev = iv
    if enc:
        pad = 16 - len(data) % 16
        data += bytes([pad]) * pad
        for i in range(0, len(data), 16):
            blk = bytes(data[i + j] ^ prev[j] for j in range(16))
            ct = _enc(blk, w)
            out += ct
            prev = ct
    else:
        for i in range(0, len(data), 16):
            blk = _dec(data[i:i + 16], w)
            out += bytes(blk[j] ^ prev[j] for j in range(16))
            prev = data[i:i + 16]
        if out and 0 < out[-1] <= 16:
            out = out[:-out[-1]]
    return out


class Spider(Spider):
    def init(self, extend=''):
        self.base = HOSTS[0].rstrip('/')  # ★ 主域(init内可被重定向更新)
        self.ua = UA
        self.pk = PK
        self.ref = REFERER or self.base
        self.types = dict(CATEGORIES)
        self.filters = {}  # ★ {'1':[{'key':'class','name':'类型','value':[{'n':'剧情','v':'剧情'}]}]}
        self._pc = {}  # 线路probe缓存 {md5:[ts,froms,urls]}
        self._pcm = {}  # ★ 总页数探测缓存 {key: pagecount}
        self._srv = None  # 本地代理线程(延迟启动)
        # ★ 筛选表由静态表构建, 零网络请求 -> 首次加载只依赖 1 个请求(/enter), 避免壳端超时
        self._build_filters()
        # ★ 本站 base 固定, init 内不发任何网络请求(原探测请求会拖慢首次加载)

    # ========== 容灾: 多HOST轮询 + requests双保险 + 自动重试 ==========
    def _get(self, url, headers=None, timeout=15000, retry=3, minlen=0, deadline=None):
        # ★ 容灾 v5(2026-10-06): 失败/超时/空体/截断页 均自动重试(默认 3 次, 退避 0.5s/1.0s)
        #   背景: 不少站点在 Cloudflare 后偶发 stall(响应体已收完但连接不结束→读超时) 或
        #   返回截断页(HTTP 200 但正文只有几 KB) —— 单次请求必失败, 重试几乎必成。
        #   实测: 好看影视 hkys2.cc 单次失败率约 50%, 3 次重试后 6/6 线路全部取到。
        #   minlen>0 时把"短于 minlen 的正文"当截断页重试; 全部失败仍返回最后拿到的正文(不丢页)。
        # ★ 容灾 v6(2026-10-07): 新增 deadline(毫秒) = 该 URL 的总耗时预算, 与 retry 次数解耦。
        #   背景: 站点 stall 时单次请求会烧满 timeout(默认 15s), retry=3 最坏 15*3+1.5≈46s;
        #   壳端首启/首个分类页直接判超时报"加载失败"(实测 ptt2.my /p/1 首次 TimeoutError 15.2s)。
        #   带 deadline 后"最坏耗时"有硬上界, 且预算内仍可多次重试(比单纯调小 timeout 成功率高)。
        #   用法: _get(url, timeout=8000, retry=3, deadline=10000) -> 最多约 10s。
        hd = headers or {'User-Agent': self.ua, 'Referer': self.ref}
        n = retry if retry and retry > 0 else 1
        t_end = (time.time() + deadline / 1000.0) if deadline and deadline > 0 else None
        last = ''
        for _i in range(n):
            to = timeout
            if t_end is not None:
                left = t_end - time.time()
                if left <= 0:
                    break
                to = max(1000, min(timeout, int(left * 1000)))
            try:
                try:
                    r = self.fetch(url, headers=hd, timeout=to)
                except TypeError:
                    r = self.fetch(url, headers=hd)
                t = r.text if hasattr(r, 'text') else str(r)
                if t:
                    last = t
                    if minlen <= 0 or len(t) >= minlen:
                        return t
            except Exception:
                pass
            if _i + 1 < n:
                back = 0.5 * (_i + 1)
                if t_end is not None and time.time() + back >= t_end:
                    break
                time.sleep(back)
        return last

    def _pic(self, u):
        if not u:
            return ''
        if u.startswith('//'):
            u = 'https:' + u
        # ★ 图片 CDN 归一: ptt2.my/images/... 实测慢(3~6s), 换成列表卡片同款 CDN(0.6s)
        if IMG_HOST and '/images/' in u:
            u = re.sub(r'^https?://ptt2\.my/', 'https://' + IMG_HOST + '/', u)
        # ★ AVIF -> JPEG: 经图片代理服务端转码(否则多数壳封面裂图); IMG_PROXY 为空则直连原图
        if IMG_PROXY and '.avif' in u.lower():
            if '{url}' in IMG_PROXY:
                return IMG_PROXY.replace('{url}', quote(u, safe=''))
            return IMG_PROXY + re.sub(r'^https?://', '', u)
        return u

    def _pagecount(self, t, cls='', ex2='', ex=None, cur=1):
        # ★ 本站 Yii2 LinkPager 只渲染 current±2, 且越界页码被 clamp 到末页
        #   -> 请求超大页码, 从 .page-item.active 的 href 直接读出末页号(带缓存)
        key = '%s|%s|%s|%s' % (t, cls, ex2, json.dumps(ex or {}, sort_keys=True, ensure_ascii=False))
        c = self._pcm.get(key)
        if c:
            return c
        pc = max(int(cur or 1), 1) + 1
        # ★ 兜底 = "还有下一页": 探测失败也不至于只剩 1 页让用户无法翻页(探测成功则用真实末页覆盖)
        try:
            # ★ 探测加硬预算(容灾 v6): 末页号只是锦上添花, 绝不能卡住分类页
            h = self._get(self._cat_url(t, 999999, cls, ex2, ex), timeout=5000, retry=2, deadline=6000, minlen=PAGE_MINLEN)
            m = re.search(r'page-item active"><a[^>]*href="[^"]*page=(\d+)"', h)
            if m:
                pc = max(int(m.group(1)), pc)
        except Exception:
            pass
        self._pcm[key] = pc
        return pc

    # ========== 首页 ==========
    def homeContent(self, filter=False):
        # ★ 脱敏: 不良分类(分类名命中词库 / id 命中 BLOCK_CIDS)整体不输出
        r = {'class': [{'type_id': k, 'type_name': v} for k, v in self.types.items()
                        if not _blocked(v) and not _cid_blocked(k)]}
        if filter:
            self._build_filters()   # ★ 零网络 + 幂等(init 已构建则直接返回), 不产生额外请求
            if self.filters:
                r['filters'] = self.filters
        try:
            r['list'] = self.homeVideoContent().get('list', [])
        except Exception:
            r['list'] = []   # ★ 首启绝不抛异常(壳端任何异常都会直接显示"加载失败")
        return r

    def homeVideoContent(self):
        # ★ 首页固定 /enter (裸 / 是入口门, 返回 500)
        # ★ 硬预算(容灾 v6 deadline=8s): 实测站点偶发 stall, 单次就烧满 timeout=15s, 首启直接超时;
        #   带 deadline 后最坏 8s 返回(拿不到就返回空列表), 保证壳端"能加载出来"而不是"加载失败"
        h = self._get(self.base + '/enter', timeout=4000, retry=3, deadline=7000, minlen=PAGE_MINLEN)
        try:
            return {'list': self._items(h) if h else []}
        except Exception:
            return {'list': []}

    # ========== ★ 筛选表(各分类维度不同, 但 id 固定 -> 静态表; 避免首启抓 6 个分类页被限流) ==========
    #   原实现: 首启并发抓 /p/{t} x6 解析筛选 -> 站方限流, 单页 5~18s, 首启 40s 被壳端判"加载失败"
    #   现实现: 直接读 FILTERS_RAW/FILTER_YEARS, 零请求; 站方改 id 时同步更新 CONFIG 区静态表即可
    def _build_filters(self):
        if self.filters:
            return
        for t, grp in FILTERS_RAW.items():
            fl = [{'key': k, 'name': n, 'value': [{'n': a, 'v': b} for a, b in vs]}
                  for k, n, vs in grp]
            fl.append({'key': 'year', 'name': '年份',
                       'value': [{'n': '全部', 'v': ''}] + [{'n': str(y), 'v': 'year=%d' % y}
                                                             for y in FILTER_YEARS]})
            self.filters[t] = fl

    # ========== 分类(1/2/3级展平+筛选+动态翻页) ==========
    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        try:
            pn = max(int(str(pg)), 1)
        except:
            pn = 1
        if _cid_blocked(tid):  # ★ 脱敏: BLOCK_CIDS 命中的分类整类不输出
            return {'page': pn, 'pagecount': 1, 'limit': 42, 'total': 0, 'list': []}
        t, cls, ex2 = str(tid), '', ''
        if '|' in t:
            p = t.split('|')
            t, cls = p[0], p[1] if len(p) > 1 else ''
            ex2 = p[2] if len(p) > 2 else ''
        ex = {}
        if extend:
            try:
                ex = json.loads(extend) if isinstance(extend, str) else dict(extend)
            except:
                ex = {}
        # ★ 硬预算(容灾 v6 deadline=9s): 站点偶发 stall, 单次烧满 15s 会让壳端首个分类页直接超时
        h = self._get(self._cat_url(t, pn, cls, ex2, ex), timeout=5000, retry=3, deadline=8000, minlen=PAGE_MINLEN)
        if not h:
            return {'page': pn, 'pagecount': 1, 'limit': 42, 'total': 0, 'list': []}
        items = self._items(h)
        return {'page': pn, 'pagecount': self._pagecount(t, cls, ex2, ex, pn), 'limit': 42,
                'total': len(items), 'list': items}

    def _cat_url(self, t, pn, cls='', ex2='', ex=None):
        # ★ 本站: /p/{t}  二级: /c/{n}(路径式) 或 ?area_id={n}(电影)  年份 ?year=  分页 ?page=
        ex = ex or {}
        path = '/p/' + str(t)
        qs = []
        area = str(ex.get('area') or '').strip() or str(cls or '').strip()
        if area:
            if '=' in area:
                qs.append(area)
            else:
                path += '/' + area.strip('/')
        year = str(ex.get('year') or '').strip() or str(ex2 or '').strip()
        if year:
            qs.append(year if '=' in year else 'year=' + quote(year, safe=''))
        try:
            n = int(pn)
        except Exception:
            n = 1
        if n > 1:
            qs.append('page=%d' % n)
        return self.base + path + ('?' + '&'.join(qs) if qs else '')

    # ========== 详情(多线路 + probe实测排序) ==========
    def detailContent(self, ids, quick='1'):
        vid = str(ids[0] if isinstance(ids, list) else ids or '')
        m = re.search(r'(\d+)', vid)
        vid = m.group(1) if m else ''
        if not vid:
            return {'list': []}
        # ★ 详情 = /{id}; 硬预算 12s(容灾 v6 deadline)
        h = self._get('%s/%s' % (self.base, vid), timeout=6000, retry=3, deadline=10000, minlen=PAGE_MINLEN)
        if not h:
            return {'list': []}
        d = {'vod_id': vid, 'vod_name': '', 'vod_pic': '', 'vod_year': '', 'vod_area': '',
             'vod_class': '', 'vod_director': '', 'vod_actor': '', 'vod_content': '',
             'vod_remarks': '', 'vod_play_from': '', 'vod_play_url': ''}
        # ★ 本站详情页内嵌 JSON-LD, 一次给全 name/description/thumbnailUrl/uploadDate
        ld = {}
        mld = re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>', h)
        if mld:
            try:
                ld = json.loads(mld.group(1))
            except Exception:
                ld = {}
        d['vod_name'] = str(ld.get('name') or '').strip()
        if not d['vod_name']:
            tn = re.search(r'<title>(.*?)</title>', h, re.S)
            if tn:
                d['vod_name'] = re.split(r'\s*-\s*线上看', re.sub(r'<[^>]+>', '', tn.group(1)))[0].strip()
        if _blocked(d['vod_name']):
            return {'list': []}
        d['vod_pic'] = self._pic(str(ld.get('thumbnailUrl') or ''))
        if not d['vod_pic']:
            p = re.search(r'<meta property="og:image" content="([^"]+)"', h)
            if p:
                d['vod_pic'] = self._pic(p.group(1))
        d['vod_content'] = re.sub(r'\s+', ' ', str(ld.get('description') or '')).strip()[:500]
        if _blocked(d['vod_content']):  # ★ 脱敏: 简介命中词库 → 整条丢弃
            return {'list': []}
        ud = str(ld.get('uploadDate') or '')
        if len(ud) >= 4 and ud[:4].isdigit():
            d['vod_year'] = ud[:4]
        # ★ 面包屑: 首页 / {分类}(/p/N) / {地区或类型}(/p/N/c/M) / 片名
        bc = [(u, n.strip()) for u, n in
              re.findall(r'breadcrumb-item"><a href="([^"]*)"[^>]*>([^<]*)</a>', h) if n.strip() != '首页']
        if len(bc) >= 1:
            d['vod_class'] = bc[0][1]
        if len(bc) >= 2:
            d['vod_area'] = bc[1][1]
        pf, pu = self._play_sources(h, vid)
        if pf:
            if PROBE and len(pf) > 1:
                pf, pu = self._sort_lines(pf, pu)
            d['vod_play_from'] = '$$$'.join(pf)
            d['vod_play_url'] = '$$$'.join(pu)
        return {'list': [d]}

    def _play_sources(self, h, vid):
        # ★ 线路 tab: <ul id="w1"> 内 <a href="/{vid}/1/{line}" title="..">线路名</a>
        lines, seen_l = [], set()
        mtab = re.search(r'<ul id="w1"[\s\S]*?</ul>', h)
        if mtab:
            for mm in re.finditer(r'<a[^>]*href="/%s/1/(\d+)"[^>]*>([^<]*)</a>' % vid, mtab.group(0)):
                lid, nm = mm.group(1), mm.group(2).strip()
                if lid not in seen_l:
                    seen_l.add(lid)
                    lines.append((lid, nm or ('线路' + lid)))
        # ★ 详情页只渲染"当前线路"的选集(seq); 实测各线路集数一致且 URL 同构
        #   (/675149/{集}/96 与 /675149/{集}/61 均为 47 集) -> 解析一次集序列, 套用到每条线路
        seq, seen_e = [], set()
        for mm in re.finditer(r'<a class="seq[^"]*" href="/%s/(\d+)/\d+"[^>]*>([^<]*)</a>' % vid, h):
            ep = int(mm.group(1))
            if ep not in seen_e:
                seen_e.add(ep)
                seq.append((ep, mm.group(2).strip()))
        seq.sort(key=lambda x: x[0])
        pf, pu = [], []
        if lines:
            for lid, nm in lines:
                if seq:
                    lst = [(ep, (t2 or ('第%d集' % ep)), urljoin(self.base, '/%s/%d/%s' % (vid, ep, lid)))
                           for ep, t2 in seq]
                else:  # 电影/单集: 无 seq 区 -> 该线路第 1 集
                    lst = [(1, '正片', urljoin(self.base, '/%s/1/%s' % (vid, lid)))]
                pf.append(nm.replace('$', '|').replace('#', '-'))
                pu.append('#'.join('%s$%s' % (n.replace('#', '-').replace('$', '|'), u) for _, n, u in lst))
        return pf, pu

    def _sort_lines(self, froms, urls):
        key = hashlib.md5('|'.join(froms).encode()).hexdigest()
        c = self._pc.get(key)
        if c and time.time() - c[0] < 300:
            return c[1], c[2]
        def probe(i):
            u = urls[i].split('#')[0].rsplit('$', 1)[-1]
            try:
                r = requests.head(urljoin(self.base, u), headers={'User-Agent': self.ua}, timeout=5)
                return 0 if r.status_code < 400 else 1
            except:
                return 1
        with ThreadPoolExecutor(max_workers=min(len(froms), 8)) as ex:
            res = list(ex.map(probe, range(len(froms))))
        pairs = sorted(zip(froms, urls, res), key=lambda x: x[2])
        out = ([p[0] for p in pairs], [p[1] for p in pairs])
        self._pc[key] = [time.time()] + list(out)
        return out

    # ========== 搜索 ==========
    def searchContent(self, key, quick=False, pg='1'):
        # ★ 本站搜索已下线: /node/search 恒 503(站方), /?wd= 只是透传不过滤
        #   实测 /?wd=爱 返回的 48 条里仅 2 条含"爱" -> 非搜索. 优雅返空, 不报错.
        return {'list': [], 'page': 1}

    # ========== 播放: 直连优先 → 解密 → VIP插槽 ==========
    def playerContent(self, flag, id, vipFlags=None):
        url = str(id) if id else str(flag)
        if '://' in url and re.search(r'\.(m3u8|mp4|flv|mp3)(\?|$)', url, re.I):
            return {'parse': 0, 'url': url}  # 直连
        full = url if url.startswith('http') else urljoin(self.base, url)
        # ★ 硬预算(容灾 v6 deadline=12s)
        h = self._get(full, timeout=6000, retry=3, deadline=10000, minlen=PAGE_MINLEN)
        if not h:
            return {'parse': 0, 'url': ''}
        u = self._parse_play(h, full)
        if not u:
            u = self._vip_try(full, h, vipFlags)  # 会员: 能破则破, 服务端硬锁放弃
        return {'parse': 0, 'url': u}

    def _parse_play(self, h, page_url):
        # ★ 本站: <source src="https://.../index.m3u8" type="application/x-mpegURL">
        m = re.search(r'<source[^>]+src="(https?://[^"]+\.(?:m3u8|mp4|flv))"', h, re.I)
        if m:
            return m.group(1)
        # JSON-LD contentUrl (JSON 内斜杠被转义)
        m2 = re.search(r'"contentUrl"\s*:\s*"([^"]+)"', h)
        if m2:
            u = m2.group(1).replace('\\/', '/')
            if re.search(r'\.(m3u8|mp4|flv)', u, re.I):
                return u
        for m3 in re.finditer(r'(https?://[^\s"\'<>\\]+\.(?:m3u8|mp4|flv))', h):
            return m3.group(1)
        return ''

    def _dec(self, u, page_url):
        u = u.strip()
        if re.search(r'\.(m3u8|mp4|flv)(\?|$)', u, re.I):
            return u
        try:  # base64
            s = u.encode()
            s2 = base64.b64decode(s + b'=' * (-len(s) % 4)).decode('utf-8', 'ignore')
            if re.search(r'\.(m3u8|mp4|flv)(\?|$)', s2, re.I):
                return s2
        except:
            pass
        # ★ AES-CBC 解密插槽: aes_cbc(base64.b64decode(s2), key, iv, 0)
        return u if u.startswith('http') else ''

    def _vip_try(self, page_url, h, vipFlags):
        # ★ 模板插槽: 会员能破则破(拼token/签名/老接口); 服务端硬锁返回''
        return ''

    # ========== 四壳13接口扩展钩子(v7.5): isVideoFormat/manualVideoCheck/getDependence/destroy/progressVideo/setVideoFlags ==========
    def isVideoFormat(self, url):
        if not url:
            return False
        if '.m3u8' in url:
            return True
        return bool(re.search(r'\.(?:%s)(?:\?|$)' % (VIDEO_EXTS or 'm3u8|mp4|flv'), url, re.I))

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return ''

    def destroy(self):
        try:
            self._c.clear()
            self._pc.clear()
            self._srv = None
        except Exception:
            pass

    def progressVideo(self, speed, time, end):
        return False

    def setVideoFlags(self, siteKey, flags):
        try:
            self._siteKey = siteKey or SITE_KEY
            self._vflags = flags or {}
        except Exception:
            pass

    # ========== 本地代理(9979-9988): m3u8 KEY/分片重写 + 图片转码 ==========
    def localProxy(self, param):
        p = param.split('url=', 1)[-1] if 'url=' in param else param
        p = unquote(p) if '%' in p else p
        if re.search(r'\.(jpe?g|png|webp|gif)(\?|$)', p, re.I):
            return self._img(p)
        if '.m3u8' in p:
            return self._rewrite_m3u8(p)
        try:
            r = self.fetch(p, headers={'User-Agent': self.ua, 'Referer': self.ref}, timeout=20000)
            if hasattr(r, 'status_code') and r.status_code != 200:
                return {'code': r.status_code, 'content': b'', 'headers': {}}
            return {'code': 200, 'content': r.content, 'headers': {'Content-Type': r.headers.get('Content-Type', 'application/octet-stream')}}
        except:
            return {'code': 404, 'content': b'', 'headers': {}}

    def _rewrite_m3u8(self, url):
        try:
            r = self.fetch(url, headers={'User-Agent': self.ua, 'Referer': self.ref}, timeout=20000)
            if hasattr(r, 'status_code') and r.status_code != 200:
                return {'code': r.status_code, 'content': b'', 'headers': {}}
            body = r.text if hasattr(r, 'text') else str(r)
        except:
            return {'code': 404, 'content': b'', 'headers': {}}
        base = url.rsplit('/', 1)[0] + '/'
        origin = re.match(r'https?://[^/]+', url)
        origin = origin.group(0) if origin else ''
        out = []
        for ln in body.splitlines():
            if ln.startswith('#EXT-X-KEY'):
                m = re.search(r'URI="([^"]+)"', ln)
                if m:
                    ku = m.group(1)
                    if ku.startswith('/'):
                        ku = origin + ku  # 根相对路径拼origin
                    elif not ku.startswith('http'):
                        ku = base + ku
                    ln = ln.replace('URI="%s"' % m.group(1), 'URI="%s"' % ('proxy?url=' + quote(ku, safe='')))
            elif ln.startswith('http'):
                ln = 'proxy?url=' + quote(ln, safe='')
            elif ln.startswith('/') and not ln.startswith('//'):
                ln = 'proxy?url=' + quote(origin + ln, safe='')
            out.append(ln)
        return {'code': 200, 'content': '\n'.join(out), 'headers': {'Content-Type': 'application/vnd.apple.mpegurl'}}

    def _img(self, u):
        try:
            r = requests.get(u, headers={'User-Agent': self.ua, 'Referer': PIC_REFERER or self.ref}, timeout=15)
            data, ct = r.content, r.headers.get('Content-Type', 'image/jpeg')
            if data[:4] == b'RIFF' or 'webp' in ct:
                try:
                    from PIL import Image
                    import io
                    buf = io.BytesIO()
                    Image.open(io.BytesIO(data)).convert('RGB').save(buf, 'JPEG', quality=85)
                    data, ct = buf.getvalue(), 'image/jpeg'
                except:
                    ct = 'image/webp'
            return {'code': 200, 'content': data, 'headers': {'Content-Type': ct}}
        except:
            return {'code': 404, 'content': b'', 'headers': {}}

    # ========== 列表解析(本站卡片结构) ==========
    def _items(self, h):
        # <a class="visited" href="/{id}"><img class="card-img-top lazyimage" src="{pic}" alt="{name}">
        # 备注: <div class='imagelabel imagelabel-bottom-right'><span class="badge badge-success">共47集</span></div>
        items, seen = [], set()
        for m in re.finditer(r'<a class="visited" href="/(\d+)"><img class="card-img-top[^"]*" src="([^"]*)" alt="([^"]*)"', h):
            vid, pic, name = m.group(1), m.group(2), m.group(3).strip()
            if not name or len(name) > 100 or _blocked(name) or vid in seen:
                continue
            seen.add(vid)
            after = h[m.end():m.end() + 700]
            rm = re.search(r"imagelabel-bottom-right'><span class=\"[^\"]*\">([^<]*)</span>", after) or \
                re.search(r'imagelabel-bottom-right"><span class="[^"]*">([^<]*)</span>', after)
            items.append({'vod_id': vid, 'vod_name': name[:60], 'vod_pic': self._pic(pic),
                          'vod_remarks': rm.group(1).strip() if rm else ''})
        return items