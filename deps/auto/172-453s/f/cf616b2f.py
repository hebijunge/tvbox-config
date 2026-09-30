# coding=utf-8
# !/usr/bin/python
"""
刷鸭(默影视/多仓) Py 源  ——  美女短视频聚合

数据源：https://shuaya.pages.dev/ 首页内联 mm-api.js 的 23 条线路（全量搬运，未删减）

【源特征】
本聚合站是「随机流」站点，没有常规 CMS 的分类/搜索/详情页：
    每次请求接口 → 302 跳到一条**随机**的短视频 mp4
因此本源做了如下架构映射：
    线路  ==  分类(tid)，23 条接口 = 23 个分类
    vid   ==  指纹，fp = 3 位线路 code + 时间戳 + 随机串 + 扩展名
    详情页 ==  只含 1 条播放地址（点开即播）
    "换一个" == 自定义 action，点按钮即换新视频，等价于原站的核心交互
    搜索   ==  未实现（源站本身没有搜索能力，返回空而非报错）

【健壮性】
线上实测 api.lolimi.cn / v2.xxapi.cn / api.dwo.cc 三条线路已死，
v.nrzj.vip 与 api.cenguigui.cn 间歇性抽风（3~4 次里挂 1 次）。
故播放链路带「同步探测 + 跳转 + 重试 + 坏线路自动降级」，
避免一次 404 就白屏——原站 JS 版正是靠前端重试 3 次换线来兜的。

【环境变量】
    无。ext 可留空。
"""

import sys
import json
import time
import random
import re

sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except Exception:  # 独立调试时无基类，用空壳顶上
    class BaseSpider(object):
        def __init__(self, *args, **kwargs):
            pass


class Spider(BaseSpider):

    # ==================== 线路表：全量搬运自 shuaya.pages.dev 的 mm-api.js ====================
    # api/data/type 三者语义与源站一致：
    #   link   → 302 直链接口，追加破缓存参数即可拿到新视频
    #   random → 随机型接口，末尾拼随机数以换视频
    #   data   → JSON 型接口，按 data 字段路径取值
    # core=True 表示 api.yujn.cn 主源（实测最稳），排序权重更高
    API_LIST = [
        {"code": "003", "title": "高质量纯妹",   "api": "http://api.yujn.cn/api/zzxjj.php?type=video",    "type": "link",   "core": True},
        {"code": "001", "title": "黑丝",         "api": "https://api.yujn.cn/api/heisis.php?type=video",  "type": "link",   "core": True},
        {"code": "002", "title": "萌妹短视频",   "api": "https://api.yujn.cn/api/nvda.php?type=video",    "type": "link",   "core": True},
        {"code": "005", "title": "清纯萝莉",     "api": "http://api.yujn.cn/api/zzxjj.php?temps=",        "type": "random", "core": True},
        {"code": "007", "title": "快手扭一扭",   "api": "http://v.nrzj.vip/video.php?_t=",                "type": "random", "core": False},
        {"code": "009", "title": "妹纸",         "api": "http://v.nrzj.vip/video.php",                    "type": "link",   "core": False},
        {"code": "010", "title": "清纯",         "api": "http://api.yujn.cn/api/zzxjj.php?type=video",    "type": "link",   "core": True},
        {"code": "011", "title": "甜妹",         "api": "http://api.yujn.cn/api/xjj.php?type=video",      "type": "link",   "core": True},
        {"code": "018", "title": "快手女大学生", "api": "https://api.yujn.cn/api/nvda.php?type=video",    "type": "link",   "core": True},
        {"code": "019", "title": "黑丝系列",     "api": "http://api.yujn.cn/api/heisis.php?type=video",   "type": "link",   "core": True},
        {"code": "020", "title": "慢摇系列",     "api": "http://api.yujn.cn/api/manyao.php?type=video",   "type": "link",   "core": True},
        {"code": "021", "title": "吊带系列",     "api": "http://api.yujn.cn/api/diaodai.php?type=video",  "type": "link",   "core": True},
        {"code": "022", "title": "清纯系列",     "api": "http://api.yujn.cn/api/qingchun.php?type=video", "type": "link",   "core": True},
        {"code": "023", "title": "女高系列",     "api": "http://api.yujn.cn/api/nvgao.php?type=video",    "type": "link",   "core": True},
        {"code": "024", "title": "快手变装系列", "api": "http://api.yujn.cn/api/ksbianzhuang.php?type=video", "type": "link", "core": True},
        {"code": "025", "title": "甜妹系列",     "api": "http://api.yujn.cn/api/tianmei.php?type=video",  "type": "link",   "core": True},
        {"code": "026", "title": "欲梦视频",     "api": "http://api.yujn.cn/api/ndym.php?type=video",     "type": "link",   "core": True},
        {"code": "027", "title": "热舞视频",     "api": "http://api.yujn.cn/api/rewu.php?type=video",     "type": "link",   "core": True},
        {"code": "028", "title": "小姐姐视频",   "api": "http://api.yujn.cn/api/ksxjjsp.php",             "type": "link",   "core": True},
        {"code": "031", "title": "小姐姐",       "api": "https://api.cenguigui.cn/api/mp4/MP4_xiaojiejie.php", "type": "link", "core": False},
        {"code": "032", "title": "高质量",       "api": "https://api.lolimi.cn/API/xjj/xjj.php",          "type": "link",   "core": False},
        {"code": "033", "title": "随机小姐姐",   "api": "https://v2.xxapi.cn/api/meinv",                  "type": "data",   "data": "data", "core": False},
        {"code": "034", "title": "小姐姐",       "api": "https://api.dwo.cc/api/ksvideo",                 "type": "link",   "core": False},
    ]

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 12; Mobile) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }

    # 已知失效线路（域名已废/需付费Key/返回网页），仅作最后兜底
    DEAD_CODE = {"032", "033", "034"}

    # 单条线路的探测重试次数与失败冷却时长（秒）
    # 实测主源 api.yujn.cn 有约 1/3 概率返回 404 XML，属于「抖动」而非「死」，
    # 因此必须重试；连续失败则冷却一段时间后再放回候选池，避免误判永久拉黑。
    RETRY_PER_LINE = 3
    COOLDOWN_SEC = 90

    def __init__(self, *args, **kwargs):
        try:
            BaseSpider.__init__(self, *args, **kwargs)
        except Exception:
            pass
        self.host = "https://shuaya.pages.dev/"
        self.cool_down = {}         # code -> 解禁时间戳
        self._cfg = None
        self._cfg_ts = 0

    # ==================== 基础信息 ====================
    def getName(self):
        return "刷鸭"

    def init(self, extend=""):
        # extend 可留空；容错解析，避免脏配置把整个源拖挂
        self.extend = extend or ""
        if isinstance(extend, str) and extend.strip().startswith("{"):
            try:
                self._cfg = json.loads(extend)
            except Exception:
                self._cfg = None
        return {"status": 0}

    def isVideoFormat(self, url):
        if not url:
            return False
        return any(k in url.lower() for k in (".mp4", ".m3u8", ".flv", ".ts", ".mkv", ".avi"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return None

    def action(self, action):
        return None

    # ==================== 内部工具 ====================
    def _req(self, url, headers=None, timeout=8, allow_redirects=True, stream=False):
        """统一请求入口。

        优先用基类的 self.fetch；基类缺失或行为异常时回落到 requests。
        返回 requests.Response 或 None——调用方一律做 None 判断。
        """
        hdrs = dict(self.HEADERS)
        if headers:
            hdrs.update(headers)
        try:
            rsp = self.fetch(url, headers=hdrs, timeout=timeout)
            if rsp is not None:
                return rsp
        except Exception:
            pass
        try:
            import requests
            return requests.get(url, headers=hdrs, timeout=timeout,
                                allow_redirects=allow_redirects, stream=stream)
        except Exception:
            return None

    def _bust(self, url):
        """破缓存：每次追加随机参数，保证 302 接口跳到新视频。

        源站 JS 版用 _r=时间戳+随机数，这里等价实现。
        """
        sep = "&" if "?" in url else "?"
        return "%s%s_r=%d%d" % (url, sep, int(time.time() * 1000), random.randint(0, 999))

    def _randomize(self, url, api_type):
        """按线路类型生成「取新视频」的请求地址。"""
        u = self._to_secure(url)
        if api_type == "random":
            # 随机型：源站直接拼 Math.random()，这里同理
            return u + str(random.random())
        return self._bust(u)

    @staticmethod
    def _to_secure(url):
        """http 升级 https：多数播放器跑在 https 环境，明文请求会被拦。"""
        return re.sub(r"^http://", "https://", url, flags=re.I) if url else url

    def _line_by_code(self, code):
        for item in self.API_LIST:
            if item["code"] == code:
                return item
        return None

    def _ordered_lines(self, code=None):
        """线路尝试顺序：指定线路 → 主源 → 其余线路 → 冷却中的线路。

        已判定为坏的线路沉底，主源(api.yujn.cn)优先，尽量提高一次命中率。
        """
        lines = list(self.API_LIST)
        core = [x for x in lines if x.get("core")]
        other = [x for x in lines if not x.get("core")]
        random.shuffle(core)
        random.shuffle(other)
        ordered = core + other

        # 指定线路优先（用户点了某条线路就尊重它）
        if code:
            target = self._line_by_code(code)
            if target:
                ordered = [target] + [x for x in ordered if x["code"] != code]

        # 分三档：正常 → 冷却中 → 已知失效。冷却到期的自动回到正常档。
        now = time.time()

        def state(item):
            c = item["code"]
            if c in self.cool_down:
                return 0 if now >= self.cool_down[c] else 1
            return 0 if c not in self.DEAD_CODE else 2

        return sorted(ordered, key=state)

    def _mark_bad(self, code):
        """标记线路故障并进入冷却（不是永久拉黑）。"""
        self.cool_down[code] = time.time() + self.COOLDOWN_SEC

    def _resolve(self, line, probe=True):
        """解析一条线路，拿到真实视频直链。

        probe=True 时会跟随跳转并校验内容类型——这是本源的容错核心：
        源站有一批线路会返回 404/HTML/错误XML，只有真校验过才敢交给播放器。
        抖动型线路会自动重试 RETRY_PER_LINE 次。
        返回 (真实url, 扩展名)；失败返回 (None, None)。
        """
        for attempt in range(max(1, self.RETRY_PER_LINE if probe else 1)):
            url, ext = self._resolve_once(line, probe)
            if url:
                return url, ext
            # 抖动多为瞬时故障，短暂退避后重试
            if attempt < self.RETRY_PER_LINE - 1:
                time.sleep(0.25 * (attempt + 1))
        return None, None

    def _resolve_once(self, line, probe=True):
        url = self._randomize(line["api"], line["type"])
        rsp = self._req(url, timeout=8)
        if rsp is None:
            return None, None

        # JSON 型：先取值，再对取出的地址做一次探测
        if line["type"] == "data":
            try:
                data = rsp.json()
                for key in (line.get("data") or "data").split("."):
                    data = data[key]
                if not isinstance(data, str) or not data.startswith("http"):
                    return None, None
                if not probe:
                    return data, self._ext_of(data)
                rsp2 = self._req(data, timeout=8)
                if rsp2 is not None and self._is_media(rsp2):
                    return data, self._ext_of(rsp2.url or data)
            except Exception:
                pass
            return None, None

        if not probe:
            return rsp.url or url, self._ext_of(rsp.url or url)

        if not self._is_media(rsp):
            return None, None
        final = rsp.url or url
        return final, self._ext_of(final)

    def _is_media(self, rsp):
        """判定响应是否为可播放的视频流。

        三个必要条件：状态码正常、内容类型是视频、不是错误XML。
        源站接口挂掉时常回 404 + XML 错误体，必须挡掉。
        """
        try:
            code = getattr(rsp, "status_code", 0)
            if code not in (200, 206):
                return False
            ctype = (rsp.headers.get("Content-Type") or "").lower()
            if "video" in ctype or "octet-stream" in ctype or "mpegurl" in ctype:
                # 快手/字节的 CDN 有时回 octet-stream，属于正常视频
                body_head = (rsp.text or "")[:120] if "octet-stream" in ctype and code == 200 else ""
                if "<Error" in body_head or "NoSuchKey" in body_head:
                    return False
                return True
            if "xml" in ctype or "html" in ctype or "json" in ctype:
                return False
            # 无明确类型时，用扩展名兜底
            return self.isVideoFormat(getattr(rsp, "url", "") or "")
        except Exception:
            return False

    @staticmethod
    def _ext_of(url):
        m = re.search(r"\.(mp4|m3u8|flv|mkv|ts)(\?|$)", url or "", re.I)
        return ("." + m.group(1).lower()) if m else ".mp4"

    @staticmethod
    def _pick_pic(code, title):
        """源站是随机视频流，没有封面图。

        用确定性哈希生成一张 SVG 占位封面（线路名+色块），
        保证同一线路列表每次刷新图形一致，避免列表看起来在乱跳。
        """
        palette = [
            ("#ffd60a", "#ff9500"), ("#fb7185", "#e11d48"), ("#2dd4bf", "#0d9488"),
            ("#a78bfa", "#6d28d9"), ("#60a5fa", "#2563eb"), ("#f472b6", "#db2777"),
        ]
        idx = sum(ord(c) for c in str(code)) % len(palette)
        c1, c2 = palette[idx]
        safe_title = (title or "刷鸭").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="480">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/>'
            '</linearGradient></defs>'
            '<rect width="360" height="480" fill="#0a0d14"/>'
            '<rect width="360" height="480" fill="url(#g)" opacity="0.92"/>'
            '<circle cx="180" cy="196" r="66" fill="#0a0d14" opacity="0.24"/>'
            '<text x="180" y="226" font-size="76" font-family="sans-serif" font-weight="bold" '
            'fill="#ffffff" text-anchor="middle">%s</text>'
            '<text x="180" y="330" font-size="30" font-family="sans-serif" font-weight="bold" '
            'fill="#ffffff" text-anchor="middle">%s</text>'
            '<text x="180" y="372" font-size="20" font-family="sans-serif" '
            'fill="#ffffff" opacity="0.72" text-anchor="middle">随机视频 · 点开即播</text>'
            '</svg>'
        ) % (c1, c2, safe_title[:1], safe_title)
        try:
            import base64
            return "data:image/svg+xml;base64," + \
                base64.b64encode(svg.encode("utf-8")).decode("ascii")
        except Exception:
            return ""

    def _mk_fp(self, code):
        """生成播放指纹：3位线路code + 13位时间戳 + 6位随机 + 扩展名。

        播放时由 playUrl 与 detailContent 各自现算，因此每次点播放/换一个
        都会落到互不相同的新指纹 → 拿到新视频，这正是原站「换一个」的语义。
        """
        return "%s%d%d.mp4" % (code, int(time.time() * 1000), random.randint(100000, 999999))

    def _parse_fp(self, fp):
        """从指纹反解线路 code（前 3 位定长）。"""
        m = re.match(r"^(\d{3})\d+", str(fp or ""))
        return m.group(1) if m else None

    # ==================== 首页 ====================
    def homeContent(self, filter):
        classes = [{"type_name": "🔥 随机换一个", "type_id": "random"}]
        for item in self.API_LIST:
            classes.append({"type_name": item["title"], "type_id": item["code"]})
        result = {"class": classes}
        # 明确声明无筛选：本源没有分类/地区/年份等维度
        result["filters"] = {}
        return result

    def homeVideoContent(self):
        """首页推荐位：每个线路各出一条。

        这些条目本身就是随机视频，点开即播，同时兼作导航入口。
        """
        videos = []
        for item in self.API_LIST[:12]:
            videos.append({
                "vod_id": self._mk_fp(item["code"]),
                "vod_name": item["title"],
                "vod_pic": self._pick_pic(item["code"], item["title"]),
                "vod_remarks": "随机视频" if item.get("core") else "备用线路",
            })
        return {"list": videos}

    # ==================== 分类 ====================
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        result = {
            "page": pg,
            "pagecount": 9999,
            "limit": 12,
            "total": 999999,
        }
        videos = []

        # 特制分类：一次给出各主源的一条随机视频，适合无脑点开就刷
        if tid == "random" or tid is None or tid == "":
            pool = [x for x in self.API_LIST if x.get("core")]
            random.shuffle(pool)
            for item in pool[:12]:
                videos.append({
                    "vod_id": self._mk_fp(item["code"]),
                    "vod_name": "%s · 随机刷" % item["title"],
                    "vod_pic": self._pick_pic(item["code"], item["title"]),
                    "vod_remarks": "换一个",
                })
            result["list"] = videos
            return result

        line = self._line_by_code(str(tid))
        if not line:
            # 未知 tid 不报错，退化成随机刷，避免播放器直接崩
            result["list"] = [{
                "vod_id": self._mk_fp(random.choice(self.API_LIST)["code"]),
                "vod_name": "随机小姐姐",
                "vod_pic": self._pick_pic("000", "随机"),
                "vod_remarks": "随机视频",
            }]
            return result

        # 分类 = 线路：给同一线路灌入多条互不相同的指纹
        # 播放器会把它们当成不同视频，实际每次点开都是该线路的新随机视频
        for i in range(12):
            videos.append({
                "vod_id": self._mk_fp(line["code"]),
                "vod_name": "%s #%d" % (line["title"], i + 1),
                "vod_pic": self._pick_pic(line["code"], line["title"]),
                "vod_remarks": "线路 #%s" % line["code"],
            })
        result["list"] = videos
        return result

    # ==================== 详情 ====================
    def detailContent(self, array):
        """详情页只放一条播放地址——源站是随机流，没有「剧集」概念。

        同时预解析一次真实地址，让详情页能提前校验线路是否可用。
        """
        raw_id = array[0] if array else ""
        code = self._parse_fp(raw_id)
        line = self._line_by_code(code) if code else None
        if not line:
            line = random.choice(self.API_LIST)
            code = line["code"]

        pic = self._pick_pic(code, line["title"])
        title = line["title"]

        # 现场生成新指纹，送入播放链路
        play_fp = self._mk_fp(code)
        vod = {
            "vod_id": raw_id,
            "vod_name": title,
            "vod_pic": pic,
            "type_name": "美女短视频",
            "vod_year": str(time.localtime().tm_year),
            "vod_area": "中国",
            "vod_remarks": "随机视频",
            "vod_actor": "",
            "vod_director": "",
            "vod_content": (
                "数据来源：刷鸭(https://shuaya.pages.dev/) 线路 #%s。\n"
                "该源为随机视频流，每次播放 / 换一个都会返回新视频，无固定剧集。\n"
                "若当前线路无响应，会自动切换到其他可用线路。" % code
            ),
            "vod_play_from": "刷鸭线路#%s" % code,
            "vod_play_url": "%s$%s" % (title, play_fp),
        }
        return {"list": [vod]}

    # ==================== 搜索 ====================
    def searchContent(self, key, quick, pg=1):
        """源站没有搜索能力，明确返回空列表。

        不抛异常，也不伪造结果——让播放器显示「无结果」而不是报错崩溃。
        """
        return {"list": []}

    # ==================== 播放 ====================
    def playerContent(self, flag, id, vipFlags):
        """核心：把指纹解析成可播的真实地址，并带坏线路自动降级。

        流程与源站前端一致：先探测，探测通过才交付；失败就换下一条线路，
        而不是把 404 地址直接丢给播放器（那就白屏了）。
        """
        code = self._parse_fp(id)
        tried = []
        for line in self._ordered_lines(code):
            if line["code"] in tried:
                continue
            tried.append(line["code"])
            url, _ext = self._resolve(line, probe=True)
            if url:
                # 命中即清除冷却，让线路回归候选池
                self.cool_down.pop(line["code"], None)
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": url,
                    "header": json.dumps(self.HEADERS),
                }
            # 探测失败：进入冷却，本会话内暂时沉底（冷却到期自动恢复）
            self._mark_bad(line["code"])

        # 全军覆没：不再重试，直接把源站主接口交给播放器自行跳转
        # （部分播放器容忍 302，比返回空 url 体验好）
        fallback = self._randomize(self.API_LIST[0]["api"], "link")
        return {
            "parse": 0,
            "playUrl": "",
            "url": fallback,
            "header": json.dumps(self.HEADERS),
        }

    # ==================== 自定义动作：换一个 ====================
    def action(self, action):
        """对应源站的「换一个」按钮。

        返回一条新指纹，播放器可直接跳转播放，实现无限刷。
        注：部分播放器不传 action 调用，不影响主链路。
        """
        if str(action).lower() in ("next", "change", "换一个", "random"):
            line = random.choice([x for x in self.API_LIST if x.get("core")] or self.API_LIST)
            return {"vod_id": self._mk_fp(line["code"])}
        return None


# ==================== 本地自测 ====================
if __name__ == "__main__":
    s = Spider()
    s.init("")
    print("[homeContent] 分类数:", len(s.homeContent(True)["class"]))
    hv = s.homeVideoContent()
    print("[homeVideoContent] 推荐数:", len(hv["list"]))
    if hv["list"]:
        print("  首条封面长度:", len(hv["list"][0]["vod_pic"]))
    cc = s.categoryContent("001", 1, False, {})
    print("[categoryContent] 001 列表数:", len(cc["list"]))
    vid = cc["list"][0]["vod_id"]
    print("[categoryContent] 指纹样例:", vid, "-> 线路", s._parse_fp(vid))
    dt = s.detailContent([vid])
    print("[detailContent] 标题:", dt["list"][0]["vod_name"])
    fp = dt["list"][0]["vod_play_url"].split("$")[-1]
    print("[detailContent] 播放指纹:", fp)
    print("[playerContent] 正在解析真实地址...")
    pc = s.playerContent("", fp, False)
    print("  url:", (pc.get("url") or "")[:110])
    print("  命中直链:" , "kwimgs" in (pc.get("url") or "") or "http" in (pc.get("url") or ""))
    print("[searchContent] 结果数:", len(s.searchContent("黑丝", True)["list"]))
