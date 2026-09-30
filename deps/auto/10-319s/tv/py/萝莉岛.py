# -*- coding: utf-8 -*-
"""
Lolida / 萝莉岛 
"""
import base64
import hashlib
import json
import re
import time
import random
import string
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
except Exception:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        _AES_IMPL = "cryptography"
    except Exception:
        AES = None
        _AES_IMPL = None

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def __init__(self):
            pass

# 接口域名(只放 API 后端)。注意 d1q6v0m0fmxvl0 是网页前端(H5 静态站),
# 任何路径都回 index.html, 不能当 API 用 —— 它只用来扒前端 JS 看接口调法
WEB_SITE = "https://d1q6v0m0fmxvl0.cloudfront.net"
API_CANDIDATES = [
    "https://d1w3p997s8acw6.cloudfront.net",
    "https://d2m0k739byzwun.cloudfront.net",
]
PAGE_SIZE = 20                           # 每页条数(和官方 App 一致, 100 会明显拖慢加载)
PARAM_KEY = b"BxJand%xf5h3sycH"          # parameterKey = parameterIv
IFKEY = "0a958fb9ac062420af6ba5f4caad779f".encode()  # interfaceKey
IMGKEY = b"2019ysapp7527"                # 封面 XOR key
UA_BASE = "BuildID=com.abc.Butterfly;SysType=iPhone14,5;DevID=%s;Ver=1.0.0;DevType=iPhone;Terminal=2;IsH5=1"
UA_WEB = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"


def _sha256(b):
    return hashlib.sha256(b).digest()


def _aes_encrypt(obj):
    d = pad(json.dumps(obj, ensure_ascii=False).encode("utf-8"), 16)
    c = AES.new(PARAM_KEY, AES.MODE_CBC, PARAM_KEY)
    return base64.b64encode(c.encrypt(d)).decode()


def _aes_decrypt(tdata):
    n = base64.b64decode(tdata)
    r = IFKEY + n[:12]
    o = len(r) // 2
    s = _sha256(r)[8:24]
    u = _sha256(s + r[:o])
    h = _sha256(r[o:] + s)
    key = u[:8] + h[8:24] + u[24:]
    iv = h[:4] + u[12:20] + h[28:]
    c = AES.new(key, AES.MODE_CBC, iv)
    return json.loads(unpad(c.decrypt(n[12:]), 16))


def _img_decode(blob):
    """封面解密: 前 100 字节 XOR imgKey"""
    out = bytearray(blob)
    for i in range(min(100, len(out))):
        out[i] ^= IMGKEY[i % len(IMGKEY)]
    return bytes(out)


def _mime_by_url(u):
    u = u.lower()
    if ".png" in u:
        return "image/png"
    if ".webp" in u:
        return "image/webp"
    if ".gif" in u:
        return "image/gif"
    return "image/jpeg"


class Spider(BaseSpider):
    def __init__(self):
        super().__init__()
        self.api = None
        self.token = ""
        self.dev = "tvid" + "".join(random.choices(string.ascii_lowercase + string.digits, k=14))
        self._domains = None
        self._timeout = 20

    # ---------- 基础 ----------
    def init(self, extend=""):
        try:
            if isinstance(extend, dict):
                self.dev = str(extend.get("deviceId") or self.dev)
        except Exception:
            pass

    def getName(self):
        return "萝莉岛"

    def _hdrs(self):
        return {
            "User-Agent": UA_WEB,
            "X-User-Agent": UA_BASE % self.dev,
            "temp": "test",
        }

    def _play_headers(self):
        # 关键: m3u8 接口对带浏览器 User-Agent 的请求回 13.5s 预览,
        # 只带 App 身份 X-User-Agent 才回完整分片列表
        return {
            "X-User-Agent": UA_BASE % self.dev,
            "temp": "test",
        }

    def _req(self, method, path, params=None):
        if not self.api:
            self._pick_api()
        h = self._hdrs()
        if self.token:
            h["Authorization"] = self.token
        if method == "GET":
            url = self.api + "/api/app" + path
            if params:
                enc = {k: str(v) for k, v in params.items() if v is not None}
                url += "?" + urllib.parse.urlencode({"data": _aes_encrypt(enc)})
            req = urllib.request.Request(url, headers=h)
        else:
            url = self.api + "/api/app" + path
            body = {"data": _aes_encrypt({k: v for k, v in params.items() if v is not None})} if params else {}
            req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(),
                                         headers={**h, "Content-Type": "application/json"}, method="POST")
        r = urllib.request.urlopen(req, timeout=self._timeout)
        j = json.loads(r.read().decode("utf-8", "replace"))
        if isinstance(j, dict) and j.get("code") == 200 and j.get("hash"):
            try:
                return _aes_decrypt(j["data"])
            except Exception:
                return j.get("data")
        if isinstance(j, dict):
            return j.get("data") or j
        return j

    def _pick_api(self):
        """并发探测所有候选域名, 取最先响应的那个(串行探测在首个域名失效时会白等)"""
        if self.api:
            return

        def _probe(cand):
            try:
                req = urllib.request.Request(cand + "/api/app/ping/check", headers=self._hdrs())
                r = urllib.request.urlopen(req, timeout=6)
                # 前端静态站对任何路径都回 HTML, 必须验证是 JSON 才算真 API
                if "json" not in (r.headers.get("Content-Type") or "").lower():
                    return None
                j = json.loads(r.read().decode())
                return cand if j.get("code") == 200 else None
            except Exception:
                return None

        try:
            with ThreadPoolExecutor(max_workers=len(API_CANDIDATES)) as ex:
                for got in ex.map(_probe, API_CANDIDATES):
                    if got:
                        self.api = got
                        return
        except Exception:
            pass
        self.api = API_CANDIDATES[0]

    def _login(self):
        try:
            r = self._req("POST", "/mine/login/h5",
                          {"devID": self.dev, "sysType": "iPhone14,5", "cutInfos": None, "isAppStore": False})
            if isinstance(r, dict) and r.get("token"):
                self.token = r["token"]
                return True
        except Exception:
            pass
        return False

    def _fetch_domains(self):
        if self._domains is None:
            self._domains = {"IMAGE": "", "VID": ""}
            try:
                r = self._req("GET", "/ping/domain/h5", {"devID": self.dev})
                for sl in (r or {}).get("sourceList") or []:
                    if self._domains.get(sl.get("type")):
                        continue
                    ds = sl.get("domain") or []
                    u = next((d.get("url") for d in ds if d.get("url")), "")
                    if u and sl.get("type") in self._domains:
                        self._domains[sl["type"]] = u
            except Exception:
                pass
        return self._domains

    def _guarantee(self):
        if not self.token:
            self._login()

    # ---------- 组装 ----------
    def _pic(self, path):
        if not path:
            return ""
        if str(path).startswith("http"):
            url = str(path)
        else:
            url = (self._fetch_domains().get("IMAGE") or "") + "/" + str(path).lstrip("/")
        base = self.getProxyUrl() if hasattr(self, "getProxyUrl") else ""
        if not base:
            return url
        b64 = base64.b64encode(url.encode()).decode()
        return base + ("&" if "?" in base else "?") + "type=img&url=" + urllib.parse.quote(b64)

    def _play_url(self, source_url):
        doms = self._fetch_domains()
        vid_domain = doms.get("VID") or ""
        base = self.api + "/api/app/vid/h5/m3u8/" + str(source_url).lstrip("/")
        q = "?token=" + self.token + "&c=" + urllib.parse.quote(vid_domain, safe="")
        return base + q

    @staticmethod
    def _fmt_time(sec):
        """秒 → 时长文本 34:36 / 1:12:05"""
        try:
            sec = int(sec or 0)
        except Exception:
            return ""
        if sec <= 0:
            return ""
        h, rem = divmod(sec, 3600)
        mi, ss = divmod(rem, 60)
        if h:
            return "%d:%02d:%02d" % (h, mi, ss)
        return "%d:%02d" % (mi, ss)

    @staticmethod
    def _fmt_count(n):
        """播放数 → 3.6万 / 1.2亿"""
        try:
            n = int(n or 0)
        except Exception:
            return "0"
        if n >= 100000000:
            return "%.1f亿" % (n / 100000000.0)
        if n >= 10000:
            return "%.1f万" % (n / 10000.0)
        return str(n)

    def _vod(self, v):
        try:
            return {
                "vod_id": str(v.get("id") or ""),
                "vod_name": v.get("title") or "",
                "vod_pic": self._pic(v.get("cover") or v.get("coverThumb") or ""),
                # 副标题: 视频时长
                "vod_remarks": self._fmt_time(v.get("playTime")),
                # 角标: 播放数
                "vod_year": self._fmt_count(v.get("playCount")),
                "vod_play_from": "萝莉岛",
                "vod_play_url": "%s$%s" % (v.get("title") or "第1集", v.get("id") or ""),
            }
        except Exception:
            return {}

    # 视频分类(type=1 有视频);动漫(4)/漫画(5) 是 mediaType=image 图片番,TVBox 无法播放,剔除
    _VIDEO_TYPE = (1,)

    # moduleSort 排序 ID → 中文名(接口 haiJiaoStyle.sortList 给出可用值)
    _SORT_MAP = {
        1: "最新",
        2: "最热",
        3: "最多播放",
        4: "最多收藏",
        5: "最多评论",
        6: "最多点赞",
        7: "本周热门",
        8: "本月热门",
    }

    def _build_filters(self, mod):
        """为单个模块生成 TVBox 筛选组: 子分类(section) + 排序(sort)。
        顺带把该模块第 1 页的视频带回来, 首页就不用再多发一次请求"""
        tid = mod.get("id") or ""
        groups = []
        vids = []
        # --- 子分类: 来自 /vid/module/{tid} 的 allSection ---
        try:
            r = self._req("GET", "/vid/module/" + tid,
                          {"pageNumber": 1, "pageSize": PAGE_SIZE, "moduleSort": 1})
            secs = (r or {}).get("allSection") or []
            vids = (r or {}).get("allVideoInfo") or []
        except Exception:
            secs = []
        if secs:
            vals = [{"n": "全部", "v": ""}]
            for s in secs:
                n = (s.get("sectionName") or "").strip()
                v = s.get("sectionID") or ""
                if n and v:
                    vals.append({"n": n, "v": v})
            if len(vals) > 1:
                groups.append({"key": "section", "name": "分类", "value": vals})
        # --- 排序: 模块列表用 moduleSort(数字), 子分类用 sortType(new/hot) ---
        sort_list = (mod.get("haiJiaoStyle") or {}).get("sortList") or []
        if sort_list:
            vals = []
            for sid in sort_list:
                try:
                    sid = int(sid)
                except Exception:
                    continue
                vals.append({"n": self._SORT_MAP.get(sid, "排序%d" % sid), "v": str(sid)})
            if vals:
                groups.append({"key": "sort", "name": "排序", "value": vals})
        # 子分类内的排序(section 接口只认 new/hot)
        groups.append({"key": "secsort", "name": "子排序",
                       "value": [{"n": "最新", "v": "new"}, {"n": "最热", "v": "hot"}]})
        return tid, groups, vids

    # ---------- 标准接口 ----------
    def homeContent(self, filter=False):
        try:
            self._guarantee()
            r = self._req("GET", "/modules/list")
            classes = []
            mods = []
            for mod in (r or {}).get("homePage") or []:
                if mod.get("type") not in self._VIDEO_TYPE:
                    continue
                classes.append({"type_id": mod.get("id") or "", "type_name": mod.get("moduleName") or ""})
                mods.append(mod)
            # 图片/视频域名单独起线程预取, 与下面的筛选请求并行(否则组装封面时要多等 1.5s)
            dom_ex = ThreadPoolExecutor(max_workers=1)
            dom_fut = dom_ex.submit(self._fetch_domains)
            # 并发拉各分类的子分类(顺带取回第 1 页视频, 首页列表直接复用)
            filters = {}
            first_vids = {}
            try:
                with ThreadPoolExecutor(max_workers=10) as ex:
                    for tid, groups, vids in ex.map(self._build_filters, mods):
                        if not tid:
                            continue
                        if groups:
                            filters[tid] = groups
                        if vids:
                            first_vids[tid] = vids
            except Exception:
                pass
            try:
                dom_fut.result(timeout=10)
            except Exception:
                pass
            finally:
                dom_ex.shutdown(wait=False)
            # 首页推荐: 用第一个有内容的分类
            videos = []
            for c in classes:
                vs = first_vids.get(c["type_id"]) or []
                if vs:
                    videos = [self._vod(v) for v in vs]
                    break
            return {"class": classes, "list": videos, "filters": filters}
        except Exception:
            return {"class": [], "list": [], "filters": {}}

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        try:
            self._guarantee()
            if not tid:
                return {"list": [], "page": 1, "pagecount": 1, "total": 0}
            ext = extend if isinstance(extend, dict) else {}
            section = str(ext.get("section") or "").strip()
            secsort = str(ext.get("secsort") or "new").strip() or "new"
            try:
                msort = int(ext.get("sort") or 1)
            except Exception:
                msort = 1
            _pg = int(pg or 1)
            videos = []
            has_next = False
            if section:
                # 子分类走 /vid/section/{id}。关键: 该接口只认 sortType=new|hot,
                # 传 moduleSort 会让 pageNumber>=2 返回空(前端也是这么调的)
                r = self._req("GET", "/vid/section/" + section,
                              {"pageNumber": _pg, "pageSize": PAGE_SIZE, "sortType": secsort})
                videos = [self._vod(v) for v in (r or {}).get("videos") or []]
                has_next = bool((r or {}).get("hasNext", False))
                return {"list": videos, "page": _pg,
                        "pagecount": (_pg + 1) if has_next else _pg,
                        "limit": PAGE_SIZE, "total": 999999 if has_next else len(videos)}
            else:
                r = self._req("GET", "/vid/module/" + str(tid),
                              {"pageNumber": _pg, "pageSize": PAGE_SIZE, "moduleSort": msort})
                videos = [self._vod(v) for v in (r or {}).get("allVideoInfo") or []]
                has_next = bool((r or {}).get("hasNext", False))
                # 兜底: 该模块无直接视频时, 把其 sections 的视频聚合进来(动漫/漫画类)
                if not videos:
                    for sec in (r or {}).get("allSection") or []:
                        try:
                            ss = self._req("GET", "/vid/section/%s" % sec["sectionID"],
                                           {"pageNumber": _pg, "pageSize": PAGE_SIZE, "sortType": "new"})
                            for v in (ss or {}).get("videos") or []:
                                videos.append(self._vod(v))
                        except Exception:
                            continue
                        if len(videos) >= PAGE_SIZE:
                            break
            return {"list": videos, "page": _pg,
                    "pagecount": (_pg + 1) if has_next else _pg,
                    "limit": PAGE_SIZE, "total": 999999 if has_next else len(videos)}
        except Exception:
            return {"list": [], "page": int(pg or 1), "pagecount": 1}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            self._guarantee()
            r = self._req("POST", "/search/list",
                          {"keyWords": [str(key)], "pageNumber": int(pg or 1),
                           "pageSize": 20, "realm": "SP", "sortType": 0})
            videos = [self._vod(v) for v in ((r or {}).get("list") or [])]
            return {"list": videos, "page": int(pg or 1)}
        except Exception:
            return {"list": []}

    def detailContent(self, ids):
        try:
            self._guarantee()
            vid = str(ids[0]) if isinstance(ids, (list, tuple)) else str(ids)
            r = self._req("GET", "/vid/info", {"videoID": vid})
            if not isinstance(r, dict):
                return {"list": []}
            desc = "%s\n播放:%s 点赞:%s 评论:%s 金币:%s" % (
                r.get("content") or "",
                r.get("playCount") or 0, r.get("likeCount") or 0,
                r.get("commentCount") or 0, r.get("coins") or 0)
            d = {
                "vod_id": vid,
                "vod_name": r.get("title") or "",
                "vod_pic": self._pic(r.get("cover") or ""),
                "vod_content": desc.strip(),
                "vod_play_from": "萝莉岛",
                "vod_play_url": "%s$%s" % (r.get("title") or "第1集", str(r.get("sourceURL") or vid)),
                "vod_remarks": self._fmt_time(r.get("playTime")),
                "vod_year": self._fmt_count(r.get("playCount")),
            }
            return {"list": [d]}
        except Exception:
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            self._guarantee()
            value = str(id or "").rsplit("$", 1)[-1].strip()
            if not value:
                return {"parse": 0, "playUrl": "", "url": "", "header": {}}
            play = self._play_url(value)
            base = self.getProxyUrl() if hasattr(self, "getProxyUrl") else ""
            if base:
                b64 = base64.b64encode(play.encode()).decode()
                play = base + ("&" if "?" in base else "?") + "type=play&url=" + urllib.parse.quote(b64)
            return {"parse": 0, "playUrl": "", "url": play, "header": {}}
        except Exception:
            return {"parse": 0, "playUrl": "", "url": "", "header": {}}

    def localProxy(self, param):
        try:
            t = param.get("type")
            url = base64.b64decode(urllib.parse.unquote(param.get("url", "")) + "===").decode()
            if t == "img":
                r = urllib.request.urlopen(urllib.request.Request(url, headers=self._hdrs()), timeout=self._timeout)
                blob = _img_decode(r.read())
                return [200, _mime_by_url(url), blob, {"Content-Length": str(len(blob))}]
            if t == "play":
                # 用 App 身份(X-User-Agent, 无浏览器 UA)拉完整 m3u8
                r = urllib.request.urlopen(urllib.request.Request(url, headers=self._play_headers()), timeout=self._timeout)
                txt = r.read().decode("utf-8", "replace")
                # 把相对 KEY URI 改写为绝对地址。实测密钥端点是 /api/app/vid/m3u8sec
                # (不是 /vid/sec, 两者返回的 16B 密钥不同), 这里统一按相对路径通配改写,
                # 免得端点改名又播不了
                txt = re.sub(r'URI="(/[^"]*)"', lambda mt: 'URI="%s%s"' % (self.api, mt.group(1)), txt)
                body = txt.encode("utf-8")
                return [200, "application/vnd.apple.mpegurl; charset=utf-8", body,
                        {"Content-Length": str(len(body))}]
        except Exception:
            pass
        return [500, "text/plain", b"fetch fail", {"Content-Length": "10"}]

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return ".m3u8" in u or ".mp4" in u or ".flv" in u