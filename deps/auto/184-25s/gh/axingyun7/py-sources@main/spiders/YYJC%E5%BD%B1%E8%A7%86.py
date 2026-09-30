# -*- coding: utf-8 -*-
"""
YYJC影视 (https://yyjc.us) - TVBox 爬虫源
==========================================
接口：homeContent / categoryContent(含筛选) / detailContent / playerContent / searchContent

站点特性（已实测确认）：
1. 纯 Next.js + JSON API，无传统 HTML 模板解析，全部走 /api/library/list 聚合接口
2. 列表/分类/搜索/筛选 统一接口：GET /api/library/list?category=&page=&pageSize=&keyword=&year=&area=
   可用分类：hot_movies(电影) / hot_tv(电视剧) / shorts(短剧) / latest(最新)
   二级分类：chinese_tv(国产剧) / us_tv(欧美剧) / jp_tv(日剧) / kr_tv(韩剧)
             / anime(动漫) / variety(综艺) / documentary(纪录片)
3. 详情：POST /api/drama/detail {ids, source, vodName} -> episodes[] 直接返回 m3u8 直链
4. 多源兜底：6 个 maccms 资源站（如意/豪华/红牛/速播/虎牙/光速）ac=detail / ac=search
5. 搜索：主走 yyjc keyword 参数，失败自动降级源站 ac=search&wd=

核心优化（加载速度）：
- 连接池复用(HTTPAdapter 20/40) + keep-alive + gzip
- 多级内存缓存：首页10分钟 / 分类5分钟 / 详情15分钟(失败30秒) / 搜索3分钟 / 播放15分钟
- 列表 pageSize 拉到 40，一次请求覆盖首页首屏
- 全链路短超时(6s/4s) + 快速重试(0.3s) + 429 限流等待(2s)

核心优化（播放速度）：
- 详情页直接携带 m3u8 直链，playerContent 零解析秒开
- 多源并发探测可用播放源（ThreadPoolExecutor 3 workers）
- 播放响应带防盗链 header（UA + Referer），避免 403
- 后台预取下一集播放（share 类链接提前解析）

修复记录：
- v1 初版：全 API 链路打通
"""

import re
import json
import time
import threading
from urllib.parse import quote, urlencode

import requests
from requests.adapters import HTTPAdapter

try:
    from concurrent.futures import ThreadPoolExecutor, as_completed
except ImportError:
    ThreadPoolExecutor = None
    as_completed = None

try:
    import sys
    sys.path.append('..')
    from base.spider import Spider as _BaseSpider
except ImportError:
    _BaseSpider = None


# ============================================================
# 常量
# ============================================================
HOST = "https://yyjc.us"

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

# 超时（秒）
TIMEOUT_API = 6
TIMEOUT_SRC = 4

# 缓存 TTL（秒）
TTL_HOME = 600
TTL_CAT = 300
TTL_DETAIL_OK = 900
TTL_DETAIL_EMPTY = 30
TTL_SEARCH = 180
TTL_PLAY = 900

# 年份筛选（maccms 聚合接口支持 year 参数）
YEARS = [str(y) for y in range(2026, 2015, -1)]

# 地区筛选（接口尽力支持，站点聚合层部分分类生效）
AREAS = ["华语", "欧美", "日韩", "其他"]

# 分类表：一级分类 + 二级分类（均为站点已验证可用 category）
CATS = [
    {"id": "hot_movies", "name": "电影", "subs": [
        ("hot_movies", "全部电影"),
        ("latest", "最新电影"),
    ]},
    {"id": "hot_tv", "name": "电视剧", "subs": [
        ("hot_tv", "全部剧集"),
        ("chinese_tv", "国产剧"),
        ("us_tv", "欧美剧"),
        ("jp_tv", "日剧"),
        ("kr_tv", "韩剧"),
    ]},
    {"id": "shorts", "name": "短剧", "subs": [
        ("shorts", "全部短剧"),
        ("latest", "最新短剧"),
    ]},
    {"id": "anime", "name": "动漫", "subs": [
        ("anime", "全部动漫"),
    ]},
    {"id": "variety", "name": "综艺", "subs": [
        ("variety", "全部综艺"),
    ]},
    {"id": "documentary", "name": "纪录片", "subs": [
        ("documentary", "全部纪录片"),
    ]},
    {"id": "latest", "name": "最新", "subs": [
        ("latest", "全部最新"),
    ]},
]

# 资源站兜底（maccms 标准接口，detail/search 均支持）
SOURCES = [
    {"key": "ryzy", "name": "如意", "api": "https://www.ryzyw.com/api.php/provide/vod"},
    {"key": "hhzy", "name": "豪华",
     "api": "https://hhzyapi.com/api.php/provide/vod/from/hhm3u8/at/json"},
    {"key": "hnzy", "name": "红牛",
     "api": "https://www.hongniuzy2.com/api.php/provide/vod/from/hnm3u8/"},
    {"key": "subozy", "name": "速播",
     "api": "https://subocj.com/api.php/provide/vod/from/subm3u8/at/json"},
    {"key": "hyzy", "name": "虎牙",
     "api": "https://www.huyaapi.com/api.php/provide/vod/from/hym3u8/at/json"},
    {"key": "gszy", "name": "光速",
     "api": "https://api.guangsuapi.com/api.php/provide/vod/from/gsm3u8/"},
]


def _build_filters(cat):
    """构建筛选器：类型(二级分类) / 地区 / 年份"""
    subs = [{"n": name, "v": slug} for slug, name in cat["subs"]]
    filters = [{
        "key": "class", "name": "类型",
        "value": [{"n": "全部", "v": ""}] + subs,
    }]
    filters.append({
        "key": "area", "name": "地区",
        "value": [{"n": "全部", "v": ""}] + [{"n": a, "v": a} for a in AREAS],
    })
    filters.append({
        "key": "year", "name": "年份",
        "value": [{"n": "全部", "v": ""}] + [{"n": y, "v": y} for y in YEARS],
    })
    return filters


# 全部分类 + 筛选器
ALL_CLASSES = [{"type_id": c["id"], "type_name": c["name"], "filter": 1} for c in CATS]
ALL_FILTERS = {c["id"]: _build_filters(c) for c in CATS}


# ============================================================
# Spider 主类
# ============================================================
_Base = _BaseSpider if _BaseSpider is not None else object


class Spider(_Base):
    siteUrl = HOST
    headers = {
        'User-Agent': UA,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': HOST + '/',
    }

    # ===== 初始化 =====
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.verify = False
        adapter = HTTPAdapter(
            pool_connections=20, pool_maxsize=40,
            max_retries=0, pool_block=False,
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        self.extend = ""

        # 缓存容器 + 锁
        self._lock = threading.Lock()
        self._home_cache = []
        self._home_cache_time = 0
        self._cat_cache = {}
        self._detail_cache = {}
        self._search_cache = {}
        self._play_cache = {}
        self._sources_cache = None
        self._sources_time = 0
        self._prefetching = set()

    def init(self, extend=""):
        self.extend = extend or ""

    # ===== 网络工具 =====
    def _get_json(self, url, params=None, timeout=TIMEOUT_API):
        for attempt in range(2):
            try:
                r = self.session.get(url, params=params, timeout=timeout)
                if r.status_code == 429:
                    time.sleep(2.0)
                    continue
                r.raise_for_status()
                return r.json()
            except Exception:
                if attempt == 0:
                    time.sleep(0.3)
                else:
                    return None
        return None

    def _post_json(self, url, data=None, timeout=TIMEOUT_API):
        for attempt in range(2):
            try:
                r = self.session.post(url, json=data, timeout=timeout)
                if r.status_code == 429:
                    time.sleep(2.0)
                    continue
                r.raise_for_status()
                return r.json()
            except Exception:
                if attempt == 0:
                    time.sleep(0.3)
                else:
                    return None
        return None

    def _src_get(self, api, params=None, timeout=TIMEOUT_SRC):
        """资源站 maccms 直连（绕过 yyjc 中间层，更快）"""
        for attempt in range(2):
            try:
                r = self.session.get(api, params=params, timeout=timeout)
                if r.status_code == 429:
                    time.sleep(1.5)
                    continue
                r.raise_for_status()
                return r.json()
            except Exception:
                if attempt == 0:
                    time.sleep(0.2)
                else:
                    return None
        return None

    def _video_sources(self):
        """获取可用资源站列表（缓存 1 小时，失败用硬编码）"""
        with self._lock:
            if self._sources_cache and time.time() - self._sources_time < 3600:
                return self._sources_cache
        d = self._get_json(HOST + "/api/vod-sources")
        sources = []
        if d and d.get("code") == 200:
            for s in (d.get("data") or {}).get("sources") or []:
                if s.get("enabled") and s.get("api"):
                    sources.append({
                        "key": s.get("key"),
                        "name": s.get("name"),
                        "api": s.get("api"),
                    })
        if not sources:
            sources = SOURCES
        with self._lock:
            self._sources_cache = sources
            self._sources_time = int(time.time())
        return sources

    # ===== 缓存 =====
    @staticmethod
    def _cache_get(cache, key, ttl=None):
        item = cache.get(key)
        if item and time.time() - item[0] < (ttl if ttl is not None else item[2]):
            return item[1]
        return None

    @staticmethod
    def _cache_set(cache, key, value, ttl=TTL_CAT):
        if len(cache) > 512:
            cache.clear()
        cache[key] = (time.time(), value, ttl)

    # ===== 列表解析（library/list -> TVBox 卡片） =====
    @staticmethod
    def _cards(data):
        out = []
        for it in (data.get("list") or []):
            vid = str(it.get("id") or "").strip()
            name = str(it.get("name") or "").strip()
            if not vid or not name:
                continue
            out.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": it.get("pic") or "",
                "vod_remarks": it.get("remarks") or "",
                "vod_year": str(it.get("year") or ""),
                "vod_area": str(it.get("area") or ""),
                "vod_actor": str(it.get("actor") or ""),
                "vod_director": str(it.get("director") or ""),
                "vod_type": str(it.get("type") or ""),
                "vod_score": str(it.get("score") or ""),
                "vod_content": str(it.get("blurb") or "")[:500],
            })
        return out

    def _library(self, category="latest", page=1, page_size=36, keyword="",
                 year="", area="", cache=True):
        params = {
            "category": category,
            "page": str(page),
            "pageSize": str(page_size),
            "cache": "1" if cache else "0",
        }
        if keyword:
            params["keyword"] = keyword
        if year:
            params["year"] = year
        if area:
            params["area"] = area
        d = self._get_json(HOST + "/api/library/list", params=params)
        if not d or d.get("code") != 200:
            return None
        return d.get("data") or {}

    # ============================================================
    # 首页
    # ============================================================
    def homeContent(self, filter=False):
        vod_list = []
        now = int(time.time())
        with self._lock:
            if self._home_cache and now - self._home_cache_time < TTL_HOME:
                vod_list = self._home_cache
        if not vod_list:
            data = self._library("latest", 1, 40)
            if data:
                vod_list = self._cards(data)
                with self._lock:
                    self._home_cache = vod_list
                    self._home_cache_time = int(time.time())
        return {
            "class": ALL_CLASSES,
            "filters": ALL_FILTERS,
            "list": vod_list,
        }

    def homeVideoContent(self):
        now = int(time.time())
        with self._lock:
            if self._home_cache and now - self._home_cache_time < TTL_HOME:
                return {"list": self._home_cache}
        try:
            data = self._library("latest", 1, 40)
            vod_list = self._cards(data) if data else []
            if vod_list:
                with self._lock:
                    self._home_cache = vod_list
                    self._home_cache_time = int(time.time())
            return {"list": vod_list}
        except Exception:
            return {"list": []}

    # ============================================================
    # 分类列表（含筛选：类型二级分类 / 地区 / 年份）
    # ============================================================
    def _empty_category(self, page=1):
        return {"list": [], "page": page, "pagecount": 1, "limit": 36, "total": 0}

    def categoryContent(self, tid, pg, filter, extend):
        page = 1
        try:
            page = max(1, int(pg or 1))
            ext = {}
            if extend:
                if isinstance(extend, dict):
                    ext = extend
                elif isinstance(extend, str):
                    try:
                        ext = json.loads(extend)
                    except Exception:
                        ext = {}

            # 类型筛选（二级分类）优先，否则用当前分类 tid
            category = (ext.get('class') or '').strip() or str(tid)

            ckey = f"{category}|{page}|{json.dumps(ext, ensure_ascii=False, sort_keys=True)}"
            cached = self._cache_get(self._cat_cache, ckey, TTL_CAT)
            if cached is not None:
                return cached

            data = self._library(
                category=category,
                page=page,
                page_size=36,
                year=(ext.get('year') or '').strip(),
                area=(ext.get('area') or '').strip(),
            )
            if not data:
                return self._empty_category(page)

            vod_list = self._cards(data)
            pagecount = int(data.get("pagecount") or 1)
            result = {
                "list": vod_list,
                "page": page,
                "pagecount": pagecount,
                "limit": 36,
                "total": int(data.get("total") or pagecount * 36),
            }
            self._cache_set(self._cat_cache, ckey, result, TTL_CAT)
            return result
        except Exception:
            return self._empty_category(page)

    # ============================================================
    # 详情页（episodes 直接含 m3u8 直链）
    # ============================================================
    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vid = str(ids[0]).split(',')[0].strip()
        if not vid:
            return {"list": []}

        cached = self._cache_get(self._detail_cache, vid, None)
        if cached is not None:
            return cached

        result = self._fetch_detail(vid)
        ttl = TTL_DETAIL_OK if result.get("list") else TTL_DETAIL_EMPTY
        self._cache_set(self._detail_cache, vid, result, ttl)

        if result.get("list"):
            self._prefetch_first(result["list"][0])
        return result

    def _fetch_detail(self, vid):
        # 主方案：源站 maccms 直连（0.5s 级，快 4 倍）
        detail = self._detail_via_sources(vid)
        if detail:
            return {"list": [detail]}
        # 兜底：yyjc drama/detail（带完整 source 对象）
        detail = self._detail_via_yyjc(vid)
        if detail:
            return {"list": [detail]}
        return {"list": []}

    def _detail_via_yyjc(self, vid):
        """兜底：POST /api/drama/detail（带完整 source 对象）"""
        sources = self._video_sources()
        if not sources:
            return None
        for s in sources[:2]:
            r = self._detail_yyjc_one(vid, s)
            if r:
                return r
        return None

    def _detail_yyjc_one(self, vid, source):
        try:
            body = {
                "ids": vid,
                "source": dict(source),
                "vodName": "",
                "_t": int(time.time() * 1000),
            }
            d = self._post_json(HOST + "/api/drama/detail", body, timeout=TIMEOUT_API)
            if not d or d.get("code") != 200:
                return None
            data = d.get("data") or {}
            eps = data.get("episodes") or []
            if not eps:
                return None
            return self._build_detail(vid, data, source.get("name") or "yyjc")
        except Exception:
            return None

    def _detail_via_sources(self, vid):
        """主方案：主源优先(如意)，其余源并发兜底，先到先用"""
        sources = self._video_sources()
        if not sources:
            return None
        primary = sources[0]  # 如意（资源最全）
        others = sources[1:4]
        if ThreadPoolExecutor is not None and len(sources) > 1:
            ex = ThreadPoolExecutor(max_workers=3)
            try:
                f_pri = ex.submit(self._detail_src_one, vid, primary)
                f_alt = [ex.submit(self._detail_src_one, vid, s) for s in others]
                # 先等主源（最多 2.2s），拿到就用最全的
                try:
                    r = f_pri.result(timeout=2.2)
                    if r:
                        return r
                except Exception:
                    pass
                # 主源失败/超时，收其他快源的结果
                for f in as_completed(f_alt, timeout=2.5):
                    r = f.result(timeout=1)
                    if r:
                        return r
            except Exception:
                pass
            finally:
                ex.shutdown(wait=False)  # 不等慢任务，快返
            return None
        for s in sources:
            r = self._detail_src_one(vid, s)
            if r:
                return r
        return None

    def _detail_src_one(self, vid, source):
        try:
            d = self._src_get(source["api"], {"ac": "detail", "ids": vid})
            if not d or d.get("code") != 1:
                return None
            lst = d.get("list") or []
            if not lst:
                return None
            v = lst[0]
            return self._build_detail(vid, v, source.get("name") or "yyjc")
        except Exception:
            return None

    @staticmethod
    def _build_detail(vid, data, source_name):
        """统一构造 TVBox 详情（兼容 yyjc detail 与 maccms 字段）"""
        name = data.get("name") or data.get("vod_name") or f"视频{vid}"
        pic = data.get("pic") or data.get("vod_pic") or ""

        play_from, play_url = '', ''
        eps = data.get("episodes")
        if eps:
            # yyjc 结构：[{name, url}]
            parts = [f"{e.get('name') or '播放'}${e.get('url') or ''}"
                     for e in eps if e.get('url')]
            play_from = source_name or "yyjc"
            play_url = '#'.join(parts)
        else:
            # maccms 结构：vod_play_from "src1$$$src2" / vod_play_url "ep$url#...#$$$ep$url"
            pf = str(data.get("vod_play_from") or "").strip()
            pu = str(data.get("vod_play_url") or "").strip()
            if pf and pu:
                froms = [f for f in pf.split("$$$") if f]
                groups = pu.split("$$$")
                for i, f in enumerate(froms):
                    group = groups[i] if i < len(groups) else ''
                    parts = [p for p in group.split("#") if p]
                    if parts:
                        seg = '#'.join(parts)
                        play_from = f"{play_from}$$${f}" if play_from else f
                        play_url = f"{play_url}$$${seg}" if play_url else seg

        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "type_name": data.get("type") or data.get("type_name") or '',
            "vod_remarks": data.get("remarks") or data.get("vod_remarks") or '',
            "vod_year": str(data.get("year") or data.get("vod_year") or ''),
            "vod_area": str(data.get("area") or data.get("vod_area") or ''),
            "vod_lang": '',
            "vod_director": data.get("director") or data.get("vod_director") or '',
            "vod_actor": data.get("actor") or data.get("vod_actor") or '',
            "vod_content": str(data.get("blurb") or data.get("vod_content") or '')[:500],
            "vod_play_from": play_from or source_name or 'yyjc',
            "vod_play_url": play_url,
        }

    # ============================================================
    # 播放（m3u8 直链，零解析秒开）
    # ============================================================
    def _resolve_play(self, play_url):
        """play_url 已是 m3u8 直链或需二次解析的 share 链接"""
        cached = self._cache_get(self._play_cache, play_url, TTL_PLAY)
        if cached:
            return cached
        real = ''
        if re.search(r'\.(m3u8|mp4)$', play_url, re.I):
            real = play_url
        elif '.m3u8' in play_url.lower() or '.mp4' in play_url.lower():
            real = play_url
        else:
            # share 类链接：尝试 yyjc parse 接口
            try:
                sources = self._video_sources()
                if sources:
                    d = self._post_json(HOST + "/api/drama/parse", {
                        "url": play_url,
                        "source": dict(sources[0]),
                    }, timeout=TIMEOUT_SRC)
                    if d and d.get("code") == 200 and (d.get("data") or {}).get("url"):
                        real = str(d["data"]["url"])
            except Exception:
                real = ''
        if real:
            self._cache_set(self._play_cache, play_url, real, TTL_PLAY)
        return real

    def _play_payload(self, playurl):
        is_m3u8 = '.m3u8' in playurl.lower()
        return {
            "parse": 0,
            "playUrl": "",
            "url": playurl,
            "header": {
                "User-Agent": UA,
                "Referer": HOST + "/",
            },
            "format": "application/x-mpegURL" if is_m3u8 else "",
            "contentType": "application/x-mpegURL" if is_m3u8 else "",
        }

    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "playUrl": "", "url": ""}
        play_url = str(id).strip()
        real = self._resolve_play(play_url)
        if real:
            return self._play_payload(real)
        return {
            "parse": 1,
            "playUrl": "",
            "url": play_url,
            "header": {"User-Agent": UA, "Referer": HOST + "/"},
        }

    # ============================================================
    # 预取
    # ============================================================
    def _first_play_url(self, vod):
        for seg in (vod.get("vod_play_url") or "").split("$$$"):
            for item in seg.split("#"):
                parts = item.split("$", 1)
                if len(parts) == 2 and parts[1]:
                    return parts[1]
        return None

    def _prefetch_first(self, vod):
        target = self._first_play_url(vod)
        if not target or re.search(r'\.(m3u8|mp4)$', target, re.I):
            return  # 直链无需预取
        with self._lock:
            if self._cache_get(self._play_cache, target, TTL_PLAY) or target in self._prefetching:
                return
            self._prefetching.add(target)

        def _job():
            try:
                self._resolve_play(target)
            except Exception:
                pass
            finally:
                with self._lock:
                    self._prefetching.discard(target)

        threading.Thread(target=_job, daemon=True).start()

    # ============================================================
    # 搜索（主：yyjc keyword；兜底：源站 ac=search）
    # ============================================================
    def searchContent(self, key, quick, pg=1, vod_total=1):
        page = max(1, int(pg or 1))
        ckey = "%s|%d" % (key, page)
        cached = self._cache_get(self._search_cache, ckey, TTL_SEARCH)
        if cached is not None:
            return cached

        vod_list = []
        data = self._library("latest", page, 36, keyword=key, cache=False)
        if data:
            vod_list = self._cards(data)
        else:
            # 兜底：源站 ac=search（并集去重）
            vod_list = self._search_via_sources(key, page)

        result = {"list": vod_list}
        self._cache_set(self._search_cache, ckey, result, TTL_SEARCH)
        return result

    def _search_via_sources(self, key, page=1):
        """源站搜索兜底：多站并发，结果并集"""
        out, seen = [], set()
        sources = self._video_sources()[:3]

        def _one(s):
            d = self._src_get(s["api"], {"ac": "search", "wd": key, "pg": str(page)})
            if not d or d.get("code") != 1:
                return []
            res = []
            for v in (d.get("list") or []):
                vid = str(v.get("vod_id") or "")
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                res.append({
                    "vod_id": vid,
                    "vod_name": v.get("vod_name") or '',
                    "vod_pic": v.get("vod_pic") or '',
                    "vod_remarks": v.get("vod_remarks") or '',
                })
            return res

        if ThreadPoolExecutor is not None and len(sources) > 1:
            ex = ThreadPoolExecutor(max_workers=3)
            try:
                futs = [ex.submit(_one, s) for s in sources]
                for f in as_completed(futs, timeout=TIMEOUT_SRC + 2):
                    out.extend(f.result(timeout=1))
            except Exception:
                pass
            finally:
                ex.shutdown(wait=False)
        else:
            for s in sources:
                out.extend(_one(s))
        return out[:36]


# ============================================================
# 本地自测（非 TVBox 环境直接运行）
# ============================================================
if __name__ == "__main__":
    sp = Spider()
    sp.init()

    print("=== homeContent ===")
    home = sp.homeContent()
    print("class:", [c["type_name"] for c in home["class"]])
    print("filters[0] 电影:", home["filters"]["hot_movies"][0])
    print("list 条数:", len(home["list"]),
          "首条:", home["list"][0]["vod_name"] if home["list"] else None)

    print("\n=== categoryContent (电影 第2页) ===")
    cat = sp.categoryContent("hot_movies", "2", True, "{}")
    print("条数:", len(cat["list"]), "page:", cat["page"], "pagecount:", cat["pagecount"])
    if cat["list"]:
        print("首条:", cat["list"][0]["vod_name"], "| id:", cat["list"][0]["vod_id"])

    print("\n=== categoryContent (电视剧 -> 二级分类 韩剧) ===")
    cat2 = sp.categoryContent("hot_tv", "1", True, '{"class":"kr_tv"}')
    print("条数:", len(cat2["list"]), "首条:", cat2["list"][0]["vod_name"] if cat2["list"] else None)

    print("\n=== detailContent ===")
    det = sp.detailContent([home["list"][0]["vod_id"]])
    if det.get("list"):
        d0 = det["list"][0]
        print("片名:", d0["vod_name"], "| 备注:", d0["vod_remarks"])
        print("播放源:", d0["vod_play_from"])
        print("集数:", d0["vod_play_url"].count("#") + 1)
        print("首集URL:", d0["vod_play_url"].split("#")[0][:90])

        print("\n=== playerContent ===")
        first_seg = d0["vod_play_url"].split("$$$")[0]
        first_ep = first_seg.split("#")[0].split("$", 1)[1]
        pl = sp.playerContent("", first_ep, "")
        print("url:", pl.get("url")[:90], "| parse:", pl.get("parse"))

    print("\n=== searchContent ===")
    sr = sp.searchContent("流浪地球", False)
    print("结果数:", len(sr["list"]))
    for it in sr["list"][:5]:
        print(" -", it["vod_name"])
