#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""laowang-template 视频源爬虫（hipy-server / drpy2-py 约定）"""

import base64
import json
import re
import ssl
import time
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36')

DEFAULT_HOST = 'https://hbg.lwaa101.vip:8501'
TIMEOUT = 12

_DECRYPT_MAP = {
    "e": "P", "w": "D", "T": "y", "+": "J", "l": "!", "t": "L", "E": "E", "@": "2",
    "d": "a", "b": "%", "q": "l", "X": "v", "~": "R", "5": "r", "&": "X", "C": "j",
    "]": "F", "a": ")", "^": "m", ",": "~", "}": "1", "x": "C", "c": "(", "G": "@",
    "h": "h", ".": "*", "L": "s", "=": ",", "p": "g", "I": "Q", "1": "7", "_": "u",
    "K": "6", "F": "t", "2": "n", "8": "=", "k": "G", "Z": "]", ")": "b", "P": "}",
    "B": "U", "S": "k", "6": "i", "g": ":", "N": "N", "i": "S", "%": "+", "-": "Y",
    "?": "|", "4": "z", "*": "-", "3": "^", "[": "{", "(": "c", "u": "B", "y": "M",
    "U": "Z", "H": "[", "z": "K", "9": "H", "7": "f", "R": "x", "v": "&", "!": ";",
    "M": "_", "Q": "9", "Y": "e", "o": "4", "r": "A", "m": ".", "O": "o", "V": "W",
    "J": "p", "f": "d", ":": "q", "{": "8", "W": "I", "j": "?", "n": "5", "s": "3",
    "|": "T", "A": "V", "D": "w", ";": "O",
}

CATEGORIES = [
    ("10", "国产"), ("11", "传媒"), ("12", "日韩"), ("14", "无码"), ("15", "欧美"),
    ("16", "动漫"), ("18", "主播"), ("19", "同性"), ("21", "黑白"),
]
MELON_TID = "22"          # 吃瓜频道(接口/图片/播放结构与视频区不同)
MELON_NAME = "吃瓜"
CAT_NAMES = dict(CATEGORIES)
CAT_NAMES[MELON_TID] = MELON_NAME
MELON_GENRES_DEFAULT = [{"n": "全部", "v": "0"}]

PLAY_FLAG = "老王专线"
PUBLISH_PAGES = [                       # 发布页(域名轮换时自动从这里抓新入口)
    "https://www.laowangsp.com/",
    "https://www.laowangsp3.com/",
]
_XOR_KEY = 0x88
_CFG_TTL = 1800
_FILTER_TTL = 6 * 3600
_PIC_CACHE = {}          # serial -> data:URI (进程内缓存, 翻页/重进免重抓)
_PIC_CACHE_MAX = 600

# ---- Spider 基类导入降级 ----
# 不同运行时把宿主基类放在不同包路径下，逐一尝试；都失败则退化为 object，
# 此时 getProxyUrl/localProxy 走内置探测 + data:URI 兜底。
_BaseSpider = object
for _mod, _cls in (
    ("base.spider", "Spider"),        # hipy-server / FongMi 魔改版
    ("drpy2.spider", "Spider"),       # 部分 drpy2-py 后端
    ("spider_base", "Base"),          # 少数分支的自定义命名
):
    try:
        import importlib
        _BaseSpider = getattr(importlib.import_module(_mod), _cls)
        break
    except Exception:
        continue


def decrypt_title(text: str) -> str:
    if not text or not text.startswith("v#"):
        return text or ""
    out = "".join(_DECRYPT_MAP.get(ch, ch) for ch in text)
    return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), out)


def xor_decode_image(data: bytes) -> bytes:
    return bytes(b ^ _XOR_KEY for b in data)


class Spider(_BaseSpider):
    """hipy-server(drpy2-py) 接口实现。

    继承宿主基类时自动获得 getProxyUrl()/fetch() 等注入能力；
    纯 Python 环境(羊壳直载/离线测试)下降级为独立实现。
    """

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.host = DEFAULT_HOST
        self._cfg = None
        self._cfg_ts = 0.0
        self._filters = {}
        self._filter_ts = {}

    def init(self, ext=""):
        host = ""
        self._use_proxy_pic = True    # 默认优先壳代理(快); ext "proxy":0 强制 data:URI
        try:
            if isinstance(ext, str) and ext.startswith("http"):
                host = ext.strip()
            elif isinstance(ext, str) and ext.startswith("{"):
                e = json.loads(ext)
                host = e.get("host", "")
                self._use_proxy_pic = bool(e.get("proxy", False))
            elif isinstance(ext, dict):
                host = ext.get("host", "")
                self._use_proxy_pic = bool(ext.get("proxy", False))
        except Exception:
            pass
        if host:
            self.host = host.rstrip("/")

    def _get(self, path_or_url, as_json=True):
        url = path_or_url if path_or_url.startswith("http") else self.host + path_or_url
        body = None
        last = None
        for i in range(3):                       # 线路抖动大, 必须重试
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                    body = r.read()
                break
            except Exception as e:
                last = e
                time.sleep(0.4 * (i + 1))
        if body is None:
            raise last
        return json.loads(body.decode("utf-8")) if as_json else body

    def _config(self, force=False):
        now = time.time()
        if not force and self._cfg and now - self._cfg_ts < _CFG_TTL:
            return self._cfg
        try:
            raw = self._get("/data.json", as_json=False).decode("utf-8")
        except Exception:
            # 主域失效 → 发布页自动发现新入口
            new_host = self._discover_host()
            if not new_host:
                raise
            self.host = new_host
            raw = self._get("/data.json", as_json=False).decode("utf-8")
        payload = raw.split("=", 1)[1] if "=" in raw else "{}"
        cfg, _ = json.JSONDecoder().raw_decode(payload.strip())
        self._cfg = {
            "pic_domain": cfg.get("pic_domain", ""),
            "novel_domain": cfg.get("novel_domain", cfg.get("pic_domain", "")),
            "csstime": str(cfg.get("csstime", "")),
        }
        self._cfg_ts = now
        return self._cfg

    def _discover_host(self):
        """从发布页抓最新入口域名并验证可用性。

        发布页把域名写成 HTML 数字实体(&#104;&#98;&#103;...)，先解码再提取；
        逐个候选试拉 /data.json，第一个成功的即为新主域。
        """
        for page in PUBLISH_PAGES:
            try:
                req = urllib.request.Request(page, headers={"User-Agent": UA})
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        html = r.read().decode("utf-8", "replace")
                except urllib.error.HTTPError as e:
                    # 发布页服务器会返回 881 等非标准状态码, 但正文正常
                    html = (e.read() or b"").decode("utf-8", "replace")
                    if len(html) < 500:
                        continue
            except Exception:
                continue
            html = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))),
                          urllib.parse.unquote(html))
            cands = re.findall(
                r"(?:https?://)?[a-zA-Z0-9.-]+\.(?:vip|com|net|top|xyz|cc)(?::\d+)?",
                html)
            seen = set()
            for c in cands:
                host = c if c.startswith("http") else "https://" + c
                host = host.rstrip("/")
                if host in seen or "/www." in host or host.endswith(".com") \
                        and "laowangsp" in host:
                    continue
                seen.add(host)
                try:
                    probe = dict(self.__dict__)
                    probe["host"] = host
                    req = urllib.request.Request(host + "/data.json",
                                                 headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=8) as r:
                        if r.status == 200 and b"Group" in r.read(200):
                            return host
                except Exception:
                    continue
        return ""

    @staticmethod
    def _fetch_raw(url, timeout=8, attempts=2):
        """图片等二进制的轻量快速通道: 短超时+少重试。"""
        last = None
        for i in range(attempts):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                    return r.read()
            except Exception as e:
                last = e
                time.sleep(0.3 * (i + 1))
        raise last

    def _pic_data_uri(self, css_url):
        """抓取 + XOR 解码 + base64 内嵌（带缓存）。"""
        cached = _PIC_CACHE.get(css_url)
        if cached:
            return cached
        import base64 as _b64
        raw = self._fetch_raw(css_url)
        uri = "data:image/webp;base64,{}".format(
            _b64.b64encode(xor_decode_image(raw)).decode("ascii"))
        if len(_PIC_CACHE) < _PIC_CACHE_MAX:
            _PIC_CACHE[css_url] = uri
        return uri

    def pic_url(self, serial_number, melon=False):
        """视频封面 pic/<sn>/thumbnail.css；吃瓜封面 melon_images/<sn>/cover.css。
        均为 XOR-WEBP：优先本地代理解码，否则 data:URI 内嵌。"""
        if not serial_number:
            return ""
        if melon:
            css_url = "{}/melon_images/{}/cover.css".format(
                self._config()["pic_domain"], serial_number)
        else:
            css_url = "{}/pic/{}/thumbnail.css".format(
                self._config()["pic_domain"], serial_number)
        proxy = self._pic_proxy_base() if getattr(self, "_use_proxy_pic", False) else ""
        if proxy:
            # getProxyUrl() 可能自带 "?..." 查询串, 用 & 连接避免双 ?
            sep = "&" if "?" in proxy else "?"
            return "{}{}do=lw&url={}".format(
                proxy, sep, urllib.parse.quote(css_url, safe=""))
        # ---- 免代理降级：data:URI 内嵌（带缓存）----
        try:
            return self._pic_data_uri(css_url)
        except Exception:
            return ""

    def _pic_proxy_base(self):
        """探测顺序：宿主基类绑定的 self.getProxyUrl → builtins → 模块 globals。
        任一处成功即返回；全部失败返回空串（pic_url 再降级 data:URI）。"""
        import builtins
        candidates = [lambda: self.getProxyUrl()] if hasattr(self, "getProxyUrl") else []
        candidates += [
            lambda: builtins.getProxyUrl(),
            lambda: globals()["getProxyUrl"](),
        ]
        for call in candidates:
            try:
                base = call() or ""
            except Exception:
                continue
            if base:
                return base.rstrip("/")
        return ""

    def localProxy(self, param):
        """hipy 本地代理路由: ?do=lw&url=<css> -> 解码后 WEBP。

        返回 [code, content_type, bytes]；失败时抛出/返回 404 由宿主处理。
        """
        p = param if isinstance(param, dict) else dict(urllib.parse.parse_qsl(str(param)))
        url = p.get("url") or p.get("pic") or ""
        if "/pic/" not in url and "/melon_images/" not in url:
            raise ValueError("unexpected proxy target")
        raw = self._get(urllib.parse.unquote(url), as_json=False)
        return [200, "image/webp", xor_decode_image(raw)]

    @staticmethod
    def _videos_of(payload):
        data = payload.get("data")
        if isinstance(data, dict):
            if "melons" in data:                      # 吃瓜列表包络
                return data.get("melons") or [], int(data.get("page_count") or 1)
            return data.get("videos") or [], int(data.get("page_count") or 1)
        return payload.get("videos") or [], int(payload.get("page_count") or 1)

    def _to_vod(self, v, melon=False):
        sn = v.get("serial_number", "")
        return {
            "vod_id": ("m_{}".format(v.get("id")) if melon else str(v.get("id"))),
            "vod_name": decrypt_title(v.get("title", "")),
            "vod_pic": self.pic_url(sn, melon=melon),
            "vod_remarks": v.get("read_number", "") if melon else (v.get("second", "") or ""),
        }

    def _list_result(self, payload, pg, melon=False):
        videos, page_count = self._videos_of(payload)
        # 封面走 data:URI 降级时逐张抓取解码，并发化避免列表超时
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as ex:
                pics = list(ex.map(
                    lambda v: self.pic_url(v.get("serial_number", ""), melon=melon),
                    videos))
        except Exception:
            pics = [self.pic_url(v.get("serial_number", ""), melon=melon)
                    for v in videos]
        vods = []
        for v, pic in zip(videos, pics):
            d = self._to_vod(v, melon=melon)
            if pic:
                d["vod_pic"] = pic
            vods.append(d)
        return {
            "list": vods,
            "page": int(pg),
            "pagecount": page_count,
            "limit": len(videos),
            "total": 0,
        }

    def _m3u8(self, serial_number):
        c = self._config()
        return "{}/m3u8/{}/index_domain.m3u8?{}".format(
            c["novel_domain"], serial_number, c["csstime"])

    def homeContent(self, flag):
        classes = [{"type_id": tid, "type_name": name}
                   for tid, name in CATEGORIES + [(MELON_TID, MELON_NAME)]]
        filters = {}
        now = time.time()
        stale = []
        # 吃瓜频道筛选: melon_genres 来自 /melons_0_1.json
        cached = self._filters.get(MELON_TID)
        if cached is None or now - self._filter_ts.get(MELON_TID, 0) > _FILTER_TTL:
            try:
                payload = self._get("/melons_0_1.json?{}".format(
                    self._config()["csstime"]))
                cached = ([{"n": decrypt_title(g["name"]), "v": str(g["id"])}
                           for g in payload.get("melon_genres", []) if g.get("id")])
                self._filters[MELON_TID] = cached
                self._filter_ts[MELON_TID] = now
            except Exception:
                cached = None
        if cached:
            filters[MELON_TID] = [{"key": "g", "name": "类型",
                                   "value": MELON_GENRES_DEFAULT + cached}]
        for tid, _ in CATEGORIES:
            cached = self._filters.get(tid)
            if cached is None or now - self._filter_ts.get(tid, 0) > _FILTER_TTL:
                stale.append(tid)
            elif cached:
                filters[tid] = [{"key": "g", "name": "类型", "value": cached}]
        # 未缓存/过期的分类并发抓取(串行 10 次请求是首页刷新慢的主因)
        if stale:
            from concurrent.futures import ThreadPoolExecutor

            def load(tid):
                try:
                    payload = self._get("/type/{}_1.json?{}".format(
                        tid, self._config()["csstime"]))
                    genres = payload.get("category", {}).get("genres") or []
                    return tid, [{"n": decrypt_title(g["name"]), "v": str(g["id"])}
                                 for g in genres if g.get("id")]
                except Exception:
                    return tid, None

            with ThreadPoolExecutor(max_workers=8) as ex:
                for tid, cached in ex.map(load, stale):
                    if cached is None:
                        continue
                    self._filters[tid] = cached
                    self._filter_ts[tid] = now
                    if cached:
                        filters[tid] = [{"key": "g", "name": "类型", "value": cached}]
        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        try:
            payload = self._get("/index.json?{}".format(self._config()["csstime"]))
            blocks = payload.get("index_videos") or {}
            first = sorted(blocks.keys())[0] if blocks else ""
            vids = blocks.get(first, {}).get("videos") or []
            return {"list": [self._to_vod(v) for v in vids]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        gid = ""
        try:
            ext = json.loads(extend) if isinstance(extend, str) else (extend or {})
            gid = str(ext.get("g", "") or "")
        except Exception:
            gid = ""
        c = self._config()
        if tid == MELON_TID:                          # 吃瓜: /melons_<genre>_<pg>.json
            path = "/melons_{}_{}.json?{}".format(gid or "0", pg, c["csstime"])
            return self._list_result(self._get(path), pg, melon=True)
        if gid:
            path = "/genre/{}_{}_{}.json?{}".format(tid, gid, pg, c["csstime"])
        else:
            path = "/type/{}_{}.json?{}".format(tid, pg, c["csstime"])
        return self._list_result(self._get(path), pg)

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) else str(ids).split(",")[0]
        c = self._config()
        if str(vid).startswith("m_"):                 # 吃瓜详情
            mid = str(vid)[2:]
            melon = self._get("/melon/{}.json?{}".format(mid, c["csstime"]))
            melon = melon.get("data", {}).get("melon", melon)
            labels = melon.get("labels") or []
            if isinstance(labels, str):
                labels = [x for x in labels.split(",") if x]
            sn = melon.get("serial_number", "")
            eps = []
            for i, mv in enumerate(melon.get("melon_videos") or [], 1):
                url = "{}/melon_m3u8/{}/{}/index_domain.m3u8?{}".format(
                    c["novel_domain"], sn, mv.get("path", "video_0"), c["csstime"])
                name = decrypt_title(mv.get("title", "") or "") or ("第{}集".format(i) if len((melon.get('melon_videos') or [])) > 1 else "正片")
                eps.append("{}${}".format(name, url))
            vod = {
                "vod_id": str(vid),
                "vod_name": decrypt_title(melon.get("title", "")),
                "vod_pic": self.pic_url(sn, melon=True),
                "type_name": MELON_NAME,
                "vod_year": (melon.get("date") or "")[:4],
                "vod_area": "",
                "vod_remarks": "",
                "vod_actor": "",
                "vod_director": "",
                "vod_content": "、".join(labels),
                "vod_play_from": PLAY_FLAG,
                "vod_play_url": "#".join(eps),
            }
            return {"list": [vod]}
        video = self._get("/video/{}.json?{}".format(vid, c["csstime"]))["video"]
        labels = video.get("labels") or []
        if isinstance(labels, str):
            labels = [x for x in labels.split(",") if x]
        play_url = "{}${}".format("正片", self._m3u8(video["serial_number"]))
        vod = {
            "vod_id": str(video["id"]),
            "vod_name": decrypt_title(video.get("title", "")),
            "vod_pic": self.pic_url(video.get("serial_number", "")),
            "type_name": CAT_NAMES.get(str(video.get("category_id")), ""),
            "vod_year": (video.get("date") or "")[:4],
            "vod_area": "",
            "vod_remarks": self._duration(video.get("second")),
            "vod_actor": video.get("actresses") or "",
            "vod_director": "",
            "vod_content": "、".join(labels),
            "vod_play_from": PLAY_FLAG,
            "vod_play_url": play_url,
        }
        return {"list": [vod]}

    @staticmethod
    def _duration(sec):
        try:
            s = int(sec)
        except (TypeError, ValueError):
            return sec if isinstance(sec, str) else ""
        return "{}:{:02d}:{:02d}".format(s // 3600, s % 3600 // 60, s % 60)

    def playerContent(self, flag, pid, vip_flags=""):
        # 详情页只产出直连 HLS(AES-128 由播放器原生解密), parse=0
        referer = self._config().get("novel_domain", self.host)
        return {
            "parse": 0,
            "playUrl": "",
            "url": pid,
            "header": {"User-Agent": UA, "Referer": referer + "/"},
        }

    def searchContent(self, key, quick="0", pg="1"):
        pg = int(pg or 1)
        qs = urllib.parse.urlencode({"search": key, "page": pg})
        return self._list_result(self._get("/search.json?{}".format(qs)), pg)

    def searchContentPage(self, key, quick="0", pg="1"):
        return self.searchContent(key, quick, pg)

    def isVideoFormat(self, result):
        return True

    def result(self, msg):
        return msg


if __name__ == "__main__":
    import sys
    sp = Spider()
    sp.init(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST)
    home = sp.homeContent(True)
    print("classes:", [(c["type_id"], c["type_name"]) for c in home["class"]])
    print("filter sample:", home["filters"].get("10", [{}])[0].get("value", [])[:3])
    page = sp.categoryContent("10", "1", False, "")
    print("cat10:", page["limit"], "items, pagecount", page["pagecount"],
          "| first:", page["list"][0]["vod_name"], page["list"][0]["vod_remarks"])
    det = sp.detailContent([page["list"][0]["vod_id"]])["list"][0]
    print("detail:", det["vod_name"], "|", det["vod_play_url"][:96])
    print("player:", sp.playerContent(det["vod_play_from"],
                                      det["vod_play_url"].split("$")[1]))
    sr = sp.searchContent("探花", quick="0", pg="1")
    print("search:", len(sr["list"]), "results, e.g.",
          sr["list"][0]["vod_name"] if sr["list"] else "-")
