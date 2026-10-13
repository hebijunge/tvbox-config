#!/usr/bin/python
# coding=utf-8
import re, json, time, random, hashlib, os, tempfile
try:
    import requests as _requests
except Exception:
    _requests = None

USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; Lenovo TB-J606L) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/4.0 TV Safari/537.36",
]
KG_SEARCH_API = "https://songsearch.kugou.com/song_search_v2"
KG_HOT_API = "https://mobileservice.kugou.com/api/v3/search/hot"
RESOLVE_FALLBACK = [
    "https://musicserver.haitangw.cc/v1/music/resolve-url",
    "https://musicapi.haitangw.net/v1/music/resolve-url",
]
CATEGORIES = [
    ("hot", "🔥热门推荐", None),
    ("pop", "🎵流行", "流行歌曲"),
    ("rock", "🎸摇滚", "摇滚"),
    ("pure", "🎹纯音乐", "纯音乐"),
    ("cantonese", "🎤粤语", "粤语歌曲"),
    ("electronic", "🎧电音", "电音"),
    ("classical", "🎻古典", "古典音乐"),
    ("kids", "👶儿歌", "儿歌大全"),
    ("ost", "🎬影视原声", "影视原声"),
    ("folk", "🪕民谣", "民谣"),
    ("dj", "💿DJ舞曲", "DJ舞曲"),
    ("ancient", "🏮古风", "古风歌曲"),
]
QUALITIES = [("流畅", "standard"), ("高清", "exhigh"), ("无损", "lossless")]
PAGE_SIZE = 20
SEARCH_PAGESIZE = 30
CACHE_TTL = 1800
CACHE_VERSION = "v2"


def _clean_em(t):
    return re.sub(r"</?em>", "", t or "").strip()


def _fmt_duration(sec):
    try:
        sec = int(sec)
    except Exception:
        return ""
    m, s = divmod(sec, 60)
    return "%d:%02d" % (m, s)


class Spider:
    def __init__(self):
        self.site = "https://q-16a.pages.dev"
        self.name = "Q16音乐"
        self.header = {
            "User-Agent": USER_AGENTS[0],
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://q-16a.pages.dev/",
            "Origin": "https://q-16a.pages.dev",
        }
        self.s = self.session = self.sess = _requests.Session() if _requests else None
        self._extend = {}
        self._home = None
        self.cookies = {}
        self.verified = False
        self.proxy = None
        self.timeout = 20
        self.cache_dir = os.path.join(tempfile.gettempdir(), "q16music_cache")
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception:
            pass

    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return True

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower().split("?")[0]
        if u.endswith((".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg")):
            return True
        return "kugou.com" in u or "music.126.net" in u

    def destroy(self):
        pass

    def action(self, action):
        return {}

    def _uh(self, extra=None):
        h = dict(self.header)
        h["User-Agent"] = random.choice(USER_AGENTS)
        if self.cookies:
            h["Cookie"] = "; ".join("%s=%s" % (k, v) for k, v in self.cookies.items())
        if extra:
            h.update(extra)
        return h

    def _proxies(self):
        return {"http": self.proxy, "https": self.proxy} if self.proxy else None

    def _get(self, url, params=None):
        h = self._uh()
        if self.s is not None:
            try:
                r = self.s.get(url, params=params, headers=h, timeout=self.timeout, proxies=self._proxies())
                if r.status_code < 400:
                    return r
            except Exception:
                pass
        try:
            import urllib.request, urllib.parse
            q = ("?" + urllib.parse.urlencode(params)) if params else ""
            req = urllib.request.Request(url + q, headers=h)
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            class _R:
                pass
            r = _R()
            r.status_code = resp.getcode()
            r._body = resp.read()
            r.json = lambda: json.loads(r._body.decode("utf-8", "ignore"))
            r.text = r._body.decode("utf-8", "ignore")
            return r
        except Exception:
            return None

    def _post_json(self, url, data):
        body = json.dumps(data).encode("utf-8")
        h = self._uh({"User-Agent": random.choice(USER_AGENTS), "Content-Type": "application/json"})
        if self.s is not None:
            try:
                r = self.s.post(url, data=body, headers=h, timeout=self.timeout, proxies=self._proxies())
                if r.status_code < 400:
                    return r.json()
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(url, data=body, headers=h, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "ignore"))
        except Exception:
            return None

    def _cache_path(self, key):
        return os.path.join(self.cache_dir, CACHE_VERSION + "_" + hashlib.md5(key.encode("utf-8")).hexdigest() + ".json")

    def _cache_get(self, key):
        try:
            p = self._cache_path(key)
            if not os.path.exists(p):
                return None
            if time.time() - os.path.getmtime(p) > CACHE_TTL:
                return None
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _cache_set(self, key, data):
        try:
            with open(self._cache_path(key), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def _norm_ids(self, ids):
        v = ids
        if isinstance(ids, (list, tuple)):
            v = ids[0] if ids else ""
        v = str(v or "").strip()
        if v.startswith("["):
            try:
                a = json.loads(v)
                if isinstance(a, list) and a:
                    v = str(a[0]).strip()
            except Exception:
                pass
        if "$" in v:
            v = v.split("$")[-1].strip()
        return v

    def _search_songs(self, keyword, page=1, pagesize=SEARCH_PAGESIZE):
        if _requests is None and self.s is None:
            pass
        ck = "s:%s:%s:%s" % (keyword, page, pagesize)
        cached = self._cache_get(ck)
        if cached is not None:
            return cached
        songs = []
        try:
            params = {"keyword": keyword, "page": page, "pagesize": pagesize, "userid": 0,
                      "clientver": "", "platform": "WebFilter", "tag": "em",
                      "filter": 2, "iscorrection": 1, "privilege_filter": 0}
            r = self._get(KG_SEARCH_API, params=params)
            data = r.json() if r is not None else {}
            for it in (data.get("data") or {}).get("lists") or []:
                fh = it.get("FileHash")
                if not fh:
                    continue
                name = _clean_em(it.get("FileName"))
                singer = _clean_em(it.get("SingerName"))
                title = name
                if " - " in name:
                    title = name.split(" - ", 1)[1].strip() or name
                songs.append({"filehash": fh, "album_id": it.get("AlbumID") or "",
                              "title": title, "singer": singer,
                              "album": _clean_em(it.get("AlbumName")),
                              "duration": it.get("Duration") or 0,
                              "pic": (it.get("Image") or "").replace("{size}", "400")})
        except Exception:
            pass
        if songs:
            self._cache_set(ck, songs)
        return songs

    def _hot_keywords(self, count=8):
        cached = self._cache_get("hot_kw")
        if cached:
            return cached[:count]
        kws = []
        try:
            r = self._get(KG_HOT_API, params={"format": "json", "plat": 0, "count": 30})
            data = r.json() if r is not None else {}
            for it in (data.get("data") or {}).get("info") or []:
                kw = (it.get("keyword") or "").strip()
                if kw and len(kw) < 20:
                    kws.append(kw)
        except Exception:
            pass
        if kws:
            self._cache_set("hot_kw", kws)
            return kws[:count]
        return ["周杰伦", "林俊杰", "邓紫棋"]

    def _resolve_url(self, filehash, level="standard", source="kg"):
        payload = {"source": source, "rid": str(filehash), "level": level}
        for api in RESOLVE_FALLBACK:
            try:
                d = self._post_json(api, payload)
                if not d:
                    continue
                if d.get("code") in (0, 200) or d.get("message") == "ok":
                    url = ((d.get("data") or {}).get("url") or d.get("url") or "").strip()
                    if url:
                        return url
            except Exception:
                continue
        return ""

    def _to_vod(self, s):
        remark = " ".join(x for x in [s.get("singer"), _fmt_duration(s.get("duration"))] if x)
        return {"vod_id": "%s|%s" % (s["filehash"], s.get("album_id") or ""),
                "vod_name": s.get("title") or "未知歌曲",
                "vod_pic": s.get("pic") or "",
                "vod_remarks": remark}

    def _is_good_song(self, s):
        title, singer = s.get("title") or "", s.get("singer") or ""
        if not title or not singer:
            return False
        if len(title) > 30 or "_" in title:
            return False
        return not any(k in title for k in ("独家首发", "首发", "试听", "伴奏", "铃声"))

    def init(self, extend=""):
        cfg = {}
        try:
            if isinstance(extend, dict):
                cfg = extend
            elif isinstance(extend, str) and extend.strip().startswith("{"):
                cfg = json.loads(extend)
            elif isinstance(extend, str) and "=" in extend:
                from urllib.parse import parse_qsl
                cfg = dict(parse_qsl(extend, keep_blank_values=True))
        except Exception:
            cfg = {}
        if isinstance(cfg, dict):
            self._extend = cfg
            if cfg.get("proxy"):
                self.proxy = cfg.get("proxy")
            try:
                self.timeout = int(cfg.get("timeout", self.timeout))
            except Exception:
                pass
            for k in ("site", "host"):
                if cfg.get(k):
                    self.site = str(cfg[k]).rstrip("/")
                    self.header["Referer"] = self.site + "/"
                    self.header["Origin"] = self.site

    def homeContent(self, filter=None):
        return {"class": [{"type_id": t, "type_name": n} for t, n, q in CATEGORIES],
                "filters": {}}

    def homeVideoContent(self):
        try:
            kws = ["周杰伦", "林俊杰", "邓紫棋", "陈奕迅", "薛之谦"]
            try:
                kws += [k for k in self._hot_keywords(6) if k != "独家首发"]
            except Exception:
                pass
            videos, seen = [], set()
            for kw in kws[:6]:
                try:
                    songs = self._search_songs(kw, page=1, pagesize=10)
                except Exception:
                    continue
                for s in songs:
                    fh = s.get("filehash")
                    if not fh or fh in seen or not self._is_good_song(s) or not s.get("pic"):
                        continue
                    seen.add(fh)
                    videos.append(self._to_vod(s))
                    if len(videos) >= 18:
                        break
                if len(videos) >= 18:
                    break
            return {"list": videos}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        try:
            pg = max(int(pg), 1)
        except Exception:
            pg = 1
        tid = str(tid or "").strip()
        if tid == "hot":
            kws = self._hot_keywords(10) or ["周杰伦"]
            kw = kws[(pg - 1) % len(kws)]
            songs = self._search_songs(kw, page=1, pagesize=SEARCH_PAGESIZE)
            pagecount = len(kws)
        else:
            query = next((q for t, n, q in CATEGORIES if t == tid), "流行歌曲") or "流行歌曲"
            songs = self._search_songs(query, page=pg, pagesize=SEARCH_PAGESIZE)
            pagecount = 10
        items = [self._to_vod(s) for s in songs[:PAGE_SIZE]]
        return {"list": items, "page": pg, "pagecount": pagecount,
                "limit": PAGE_SIZE, "total": len(songs)}

    def detailContent(self, ids):
        vid = self._norm_ids(ids)
        fh, album_id = (vid.split("|", 1) + [""])[:2]
        if not fh or fh == "__diag__":
            return {"list": [{"vod_id": "__diag__", "vod_name": "⚠️组件异常",
                              "vod_pic": "", "type_name": "系统诊断",
                              "vod_content": "歌曲标识解析失败",
                              "vod_play_from": "说明", "vod_play_url": "确定$__diag__|help"}]}
        title, singer, album, duration, pic = "", "", "", 0, ""
        try:
            for fname in os.listdir(self.cache_dir):
                if not fname.endswith(".json") or fname.startswith(CACHE_VERSION + "_hot"):
                    continue
                try:
                    with open(os.path.join(self.cache_dir, fname), "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue
                if not isinstance(data, list):
                    continue
                for s in data:
                    if isinstance(s, dict) and s.get("filehash") == fh:
                        title, singer = s.get("title") or "", s.get("singer") or ""
                        album, pic = s.get("album") or "", s.get("pic") or ""
                        duration = s.get("duration") or 0
                        break
                if title:
                    break
        except Exception:
            pass
        if not title:
            title, singer = fh[:12], "未知歌手"
        eps = ["%s$%s|%s" % (qn, fh, lv) for qn, lv in QUALITIES]
        return {"list": [{"vod_id": vid, "vod_name": title, "vod_pic": pic,
                          "type_name": "音乐", "vod_year": "", "vod_area": "华语",
                          "vod_remarks": _fmt_duration(duration), "vod_actor": singer,
                          "vod_director": "",
                          "vod_content": "歌手: %s\n专辑: %s\n时长: %s" % (
                              singer or "未知", album or "未知", _fmt_duration(duration)),
                          "vod_play_from": "Q16音乐", "vod_play_url": "#".join(eps)}]}

    def searchContent(self, key, quick=False, pg="1"):
        key = (key or "").strip()
        if not key:
            return {"list": []}
        try:
            pg = max(int(pg), 1)
        except Exception:
            pg = 1
        if quick:
            songs = self._search_songs(key, page=1, pagesize=10)
            return {"list": [self._to_vod(s) for s in songs]}
        songs = self._search_songs(key, page=pg, pagesize=SEARCH_PAGESIZE)
        return {"list": [self._to_vod(s) for s in songs[:PAGE_SIZE]],
                "page": pg, "pagecount": 10, "limit": PAGE_SIZE, "total": len(songs)}

    def playerContent(self, flag, ids, vipFlags=None):
        vid = self._norm_ids(ids)
        if not vid or vid.startswith("__diag__"):
            return {"parse": 0, "url": ""}
        if "|" in vid:
            fh, want_lv = vid.split("|", 1)
        else:
            fh, want_lv = vid, "standard"
        lv_order = [lv for _, lv in QUALITIES]
        try:
            start = lv_order.index(want_lv)
        except ValueError:
            start = 0
        url = ""
        for lv in lv_order[start:]:
            url = self._resolve_url(fh, level=lv)
            if url:
                break
        if not url:
            return {"parse": 0, "url": ""}
        return {"parse": 0, "url": url, "header": {"User-Agent": random.choice(USER_AGENTS),
                                                  "Referer": "https://q-16a.pages.dev/",
                                                  "Origin": "https://q-16a.pages.dev"}}

    def localProxy(self, param):
        u = param.get("url", "") if isinstance(param, dict) else ""
        if not u:
            return [403, "text/plain", b"", None]
        h = dict(self.header)
        if self.s is not None:
            try:
                r = self.s.get(u, headers=h, timeout=15)
                return [200, r.headers.get("Content-Type", "application/octet-stream"), r.content, None]
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(u, headers=h)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return [200, resp.headers.get("Content-Type", "application/octet-stream"), resp.read(), None]
        except Exception:
            return [403, "text/plain", b"", None]


def _html_unescape(s):
    import html as _h
    return _h.unescape(s) if s else s
