# -*- coding: utf-8 -*-
# 电影-第1页-热剧TV网 数据源
# 站点: https://www.rjtvw.com
# 生成: VideoExtractor v4.0.65 · 2026/9/15 16:44:01
# 识别类型: html
# 判定依据: 通用页面解析（meta 标签 + 链接规律 + 内联播放器变量）
# 用法: 放进壳的 spider 目录（base/spider.py 需存在），即可被加载

import re
import json
import sys
import time
import urllib.parse

sys.path.append("..")
from base.spider import Spider
# ============ 接口加密（自动嗅探，需人工核对） ============
# 嗅探到的算法/密钥：
#  Storage sessionStorage set 输入样例=__SE_NET_www.rjtvw.com = {"t":1789461832926,"url":"https://w
#  Storage sessionStorage set 输入样例=__SE_CRY_www.rjtvw.com = {"t":1789461832928,"list":[{"type":
#  Storage sessionStorage set 输入样例=__SE_NET_www.rjtvw.com = {"t":1789461834427,"url":"https://w
#  Storage sessionStorage set 输入样例=__SE_CRY_www.rjtvw.com = {"t":1789461834428,"list":[{"type":
#  Storage sessionStorage set 输入样例=__SE_NET_www.rjtvw.com = {"t":1789461835928,"url":"https://w
#  Storage sessionStorage set 输入样例=__SE_CRY_www.rjtvw.com = {"t":1789461835928,"list":[{"type":
#  Storage sessionStorage set 输入样例=__SE_NET_www.rjtvw.com = {"t":1789461837429,"url":"https://w
#  Storage sessionStorage set 输入样例=__SE_CRY_www.rjtvw.com = {"t":1789461837430,"list":[{"type":
#  Storage sessionStorage set 输入样例=__SE_NET_www.rjtvw.com = {"t":1789461838930,"url":"https://w
#  Storage sessionStorage set 输入样例=__SE_CRY_www.rjtvw.com = {"t":1789461838931,"list":[{"type":
#  Storage sessionStorage set 输入样例=__SE_NET_www.rjtvw.com = {"t":1789461840431,"url":"https://w
#  Storage sessionStorage set 输入样例=__SE_CRY_www.rjtvw.com = {"t":1789461840431,"list":[{"type":
# 解密示例（按需打开）：
# from Crypto.Cipher import AES
# from Crypto.Util.Padding import pad, unpad
# import base64
#
# KEY = ""
# IV = ""
#
# def _dec(ct_b64):
#     c = AES.new(KEY, AES.MODE_CBC, iv=IV)
#     pt = c.decrypt(base64.b64decode(ct_b64))
#     try:
#         pt = unpad(pt, AES.block_size)
#     except Exception:
#         pt = pt.rstrip(b"\x00")
#     return pt.decode("utf-8", "ignore")
#
# def _enc(plain):
#     c = AES.new(KEY, AES.MODE_CBC, iv=IV)
#     return base64.b64encode(c.encrypt(pad(plain.encode("utf-8"), AES.block_size))).decode()
# ============ 通用页面解析模式 ============
# 不依赖 CSS 选择器：用 meta 标签取元数据、用链接规律找详情页和选集，
# 站点换皮改版基本不失效，最多改下 DETAIL_RE / PLAY_RE 两行正则。
# 详情页规律: /detail/{id}.html
# 播放页规律: /vodshow/{id}-----------{sid}.html
class Spider(Spider):
    LIST_TPL = "https://www.rjtvw.com/vodshow/{cid}--------{pg}---.html"
    DETAIL_RE = re.compile(r"""/detail/([0-9A-Za-z_-]+)\.html""")
    PLAY_RE = re.compile(r"""/[a-z]*play/|\?id=\d+|/[pv][a-z]+-\d+_\d+\.html""")
    CLASSES = [
        {"type_id": "2", "type_name": "电影"},
        {"type_id": "25", "type_name": "日影"},
        {"type_id": "23", "type_name": "韩影"},
        {"type_id": "24", "type_name": "泰影"},
    ]

    def init(self, extend=""):
        self.host = "https://www.rjtvw.com"
        self.site_url = self.host
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36",
            "Referer": "https://www.rjtvw.com/",
        }
        # 需要登录态时打开：
        # 需要登录态/Cookie 时打开：
        # self.headers["Cookie"] = ""

    def getName(self):
        return "电影-第1页-热剧TV网"

    # ---------------- 通用工具 ----------------
    def _get(self, url):
        try:
            r = self.fetch(url, headers=self.headers)
            if r is None:
                return ""
            t = getattr(r, "text", None)
            if t:
                return t
            c = getattr(r, "content", b"")
            return c.decode("utf-8", "ignore") if c else ""
        except Exception:
            return ""

    def _json(self, url):
        try:
            return json.loads(self._get(url) or "{}")
        except Exception:
            return {}

    def _abs(self, url, base=None):
        if not url:
            return ""
        url = str(url).replace("\\/", "/").strip()
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http"):
            url = urllib.parse.urljoin(base or self.host, url)
        return url

    def _links(self, html, base):
        """抓出页面里的 (绝对地址, 文本) 对。兼容 <a href> 和 data-href"""
        out = []
        for m in re.finditer(r"""<a\s[^>]*href=["']?([^"'\s>]+)["']?[^>]*>(.*?)</a>""", html or "", re.I | re.S):
            href = self._abs(m.group(1), base)
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip()
            if href:
                out.append((href, text))
        for m in re.finditer(r"""data-href=["']([^"']+)["']""", html or "", re.I):
            href = self._abs(m.group(1), base)
            if href and not any(x[0] == href for x in out):
                out.append((href, ""))
        return out

    def _meta(self, html, key):
        html = html or ""
        m = re.search(r"""<meta[^>]+(?:property|name)=["']""" + re.escape(key) + r"""["'][^>]*content=["']([^"']*)""", html, re.I)
        if not m:
            m = re.search(r"""<meta[^>]+content=["']([^"']*)["'][^>]*(?:property|name)=["']""" + re.escape(key) + r"""["']""", html, re.I)
        return m.group(1).strip() if m else ""

    def _strip(self, html):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()

    def _title(self, html):
        t = self._meta(html, "og:title") or self._meta(html, "title")
        if t:
            return t
        m = re.search(r"<title>(.*?)</title>", html or "", re.S | re.I)
        return self._strip(m.group(1)) if m else ""

    def _decode(self, s):
        """地址可能是 base64 / hex / urlencode 编过的，全部试一遍"""
        import base64 as _b64
        out = []
        s = str(s or "").replace("\\/", "/")
        if s.startswith("http"):
            return [s]
        try:
            if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", s) and len(s) % 4 == 0 and len(s) > 12:
                d = _b64.b64decode(s).decode("utf-8", "ignore")
                if d.startswith("http"):
                    out.append(d)
                elif re.fullmatch(r"[0-9a-fA-F]{16,}", d):
                    h = bytes.fromhex(d).decode("utf-8", "ignore")
                    if h.startswith("http"):
                        out.append(h)
        except Exception:
            pass
        try:
            if re.fullmatch(r"[0-9a-fA-F]{16,}", s) and len(s) % 2 == 0:
                h = bytes.fromhex(s).decode("utf-8", "ignore")
                if h.startswith("http"):
                    out.append(h)
        except Exception:
            pass
        try:
            d = urllib.parse.unquote(s)
            if d.startswith("http"):
                out.append(d)
        except Exception:
            pass
        return out

    def _media_urls(self, html):
        """从播放页抠真实媒体地址: 优先 player_aaaa/player_data, 再找裸 m3u8/mp4/mpd"""
        html = (html or "").replace("\\/", "/")
        urls = []

        def _norm(u):
            """地址归一: 去转义 + percent-decode + base64 兜底"""
            if not u:
                return ""
            u = str(u).replace("\\/", "/").replace("\\u0026", "&").strip()
            if "%" in u:
                try:
                    d = urllib.parse.unquote(u)
                    if d.startswith("http"):
                        u = d
                except Exception:
                    pass
            if not u.startswith("http"):
                try:
                    import base64 as _b64
                    d = _b64.b64decode(u + "=" * (-len(u) % 4)).decode("utf-8", "ignore")
                    if d.startswith("http"):
                        u = d
                except Exception:
                    pass
            u = u.strip().rstrip(chr(34) + chr(39) + ",;)")
            return u

        def _is_media(u):
            if not u:
                return False
            return bool(re.search(r"[.](?:m3u8|mp4|mpd|flv|m4a)(?:[?]|$)", u, re.I))

        # 1) 结构化播放器变量 (苹果CMS 最稳)
        for varname in ["player_aaaa", "player_data", "MacPlayer", "wdplayer", "PLAYER"]:
            for m in re.finditer(r"(?:%s)\s*=\s*(\{[\s\S]*?\})\s*;?\s*(?:</script>|$)" % varname, html, re.I | re.M):
                raw = m.group(1).replace("\\/", "/").replace("\\u0026", "&")
                try:
                    j = json.loads(raw)
                    for k in ["url", "url_next", "play_url", "m3u8", "playurl"]:
                        v = _norm(j.get(k, ""))
                        if _is_media(v) and v not in urls:
                            urls.append(v)
                except Exception:
                    for mm in re.finditer(r"https?://[^\s]+[.](?:m3u8|mp4|mpd)[^\s]*", raw, re.I):
                        v = _norm(mm.group(0))
                        if _is_media(v) and v not in urls:
                            urls.append(v)
                    for mm in re.finditer(r"%68%74%74%70[%0-9A-Fa-f]{20,}", raw, re.I):
                        v = _norm(mm.group(0))
                        if _is_media(v) and v not in urls:
                            urls.append(v)
        # 2) 裸 m3u8/mp4/mpd 直链
        for u in re.findall(r"https?://[^\s<>]+[.](?:m3u8|mpd|mp4|flv|m4a)(?:[?][^\s<>]*)?", html, re.I):
            v = _norm(u)
            if _is_media(v) and v not in urls:
                urls.append(v)
        # 3) url= / playurl= 等键值
        for m in re.finditer(r"(?:url|playurl|play_url|m3u8|file|src)\s*[:=]\s*([^\s]{8,600})", html, re.I):
            v = _norm(m.group(1))
            if _is_media(v) and v not in urls:
                urls.append(v)
        # 4) percent-encoded 地址(整站密文形式)
        for mm in re.finditer(r"%68%74%74%70[%0-9A-Fa-f]{20,}", html, re.I):
            v = _norm(mm.group(0))
            if _is_media(v) and v not in urls:
                urls.append(v)

        seen, out = set(), []
        for u in urls:
            if u and u.startswith("http") and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _play_from_media(self, url):
        """播放: 直链直接用; 播放页 URL 则先抓页面取真实媒体"""
        if re.search(r"\.(?:m3u8|mp4|mpd|flv|m4a)(?:[?#].*)?$", url, re.I):
            return {"parse": 0, "url": url, "header": self.headers}
        html = self._get(url)
        if html:
            medias = self._media_urls(html)
            if medias:
                return {"parse": 0, "url": medias[0], "header": self.headers}
        return {"parse": 1, "url": url, "header": self.headers}
    def _list_from_html(self, html, base):
        items = []
        for href, (name, pic, remark) in self._card_map(html, base).items():
            items.append({"vod_id": href, "vod_name": name, "vod_pic": pic, "vod_remarks": remark})
        return items
    def _card_map(self, html, base=None):
        """href -> (title, pic, remark)：兼容多 img 取真图、多 title 取非隐藏标题"""
        cards = {}
        if not html:
            return cards
        for m in re.finditer(r"""<a\s[^>]*href=["']?([^"'\s>]+)["']?[^>]*>(.*?)</a>""", html, re.I | re.S):
            href = self._abs(m.group(1), base or self.host)
            if not href or not self.DETAIL_RE.search(href):
                continue
            inner = m.group(2) or ""
            # 标题：优先取 <a> 标签自身的 title 属性（很多卡片标题放在这里）
            text = ""
            tm0 = re.search(r"""<a\s[^>]*title=["']([^"']{1,60})["']""", m.group(0), re.I)
            if tm0 and not re.search(r"kekys|可可影视|水印|logo", tm0.group(1)):
                text = tm0.group(1).strip()
            if not text:
                tm = re.findall(r"""<(?:h[2-4]|div)[^>]*class=["'][^"']*(?:v-item-title|title)[^"']*["'][^>]*>(.*?)</(?:h[2-4]|div)>""", inner, re.I | re.S)
                for t in tm:
                    t2 = self._strip(t)
                    if t2 and not re.search(r"kekys|可可影视|水印|logo", t2):
                        text = t2
                        break
            if not text:
                # 排除 display:none 的标题块
                for hd in re.finditer(r"""<(h[2-4]|div)[^>]*>(.*?)</\1>""", inner, re.I | re.S):
                    if re.search(r"display\s*:\s*none", hd.group(0)):
                        continue
                    t2 = self._strip(hd.group(2))
                    if t2 and not re.search(r"kekys|可可影视|水印|logo", t2):
                        text = t2
                        break
            if not text:
                text = self._strip(inner)
            # 封面：先取 <a> 自身的 data-original，再取 img 的 data-original/src
            pic = ""
            am = re.search(r"""<a\s[^>]*data-original=["']([^"']+)["']""", m.group(0), re.I)
            if am and not re.search(r"placeholder|logo|noimage|no_pic|default\.(?:png|jpg|gif)", am.group(1)):
                pic = self._abs(am.group(1))
            if not pic:
                origs = re.findall(r"""data-original=["']([^"']+)["']""", inner, re.I)
                for u in origs:
                    if re.search(r"placeholder|logo_placeholder|noimage|no_pic|default\.(?:png|jpg|gif)", u):
                        continue
                    pic = self._abs(u)
                    break
            if not pic:
                imgs = re.findall(r"""<img[^>]+(?:data-src|src)=["']([^"']+)["']""", inner, re.I)
                for u in imgs:
                    if re.search(r"placeholder|logo_placeholder|noimage|no_pic|default\.(?:png|jpg|gif)", u):
                        continue
                    pic = self._abs(u)
                    break
            if not pic and origs:
                pic = self._abs(origs[0])
            # 角标/备注：第一个短 span 文本
            remark = ""
            rm = re.search(r"""<span[^>]*>([^<]{1,20})</span>""", inner, re.I)
            if rm:
                remark = rm.group(1).strip()
            # v4.0.57：同一 href 常有多个<a>(缩略图+标题)，合并而非跳过
            if href in cards:
                _ot, _op, _orr = cards[href]
                _nt = _ot if (_ot and _ot != href and len(_ot) >= len(text or "")) else (text or _ot)
                cards[href] = (_nt, _op or pic, _orr or remark)
            else:
                cards[href] = (text or href, pic, remark)
        return cards

    def homeContent(self, filter):
        return {"class": list(self.CLASSES)}

    def homeVideoContent(self):
        return {"list": self._list_from_html(self._get(self.host), self.host)}

    def categoryContent(self, tid, pg, filter, extend):
        if str(tid).startswith("/") or str(tid).startswith("http"):
            # v4.0.57：完整路径/查询串类分类（如 /search.html?searchword=X）
            # 原 URL 已含搜索参数，翻页要追加 page 参数，否则每页返回同一批数据（表现为重复）
            base_url = self._abs(str(tid))
            try:
                _pg = int(pg or 1)
            except Exception:
                _pg = 1
            if _pg > 1:
                if "?" in base_url:
                    if re.search(r"[?&]page=\d+", base_url):
                        url = re.sub(r"([?&]page=)\d+", lambda _m: _m.group(1) + str(_pg), base_url)
                    else:
                        url = base_url + "&page=" + str(_pg)
                else:
                    url = base_url
            else:
                url = base_url
        else:
            # 单字母前缀站（/{cid}-{pg}.html）pg=1 省略页码；标准站（--------{pg}---）不省略
            tpl = self.LIST_TPL.replace("{cid}", str(tid))
            if int(pg or 1) <= 1 and "-{pg}" in self.LIST_TPL and "--------{pg}" not in self.LIST_TPL:
                tpl = tpl.replace("-{pg}", "").replace("{pg}", "")
            url = tpl.replace("{pg}", str(pg)).replace("{page}", str(pg))
        html = self._get(url)
        items = self._list_from_html(html, url)
        # v4.0.61：URL 自愈——拼出的地址 404/无卡片时(type_id 误取段名)，
        # 用分类名回查首页，重新定位真正的分类地址
        if not items:
            _fixed = self._fix_cat_url(tid, pg)
            if _fixed and _fixed != url:
                _h2 = self._get(_fixed)
                _it2 = self._list_from_html(_h2, _fixed)
                if _it2:
                    items = _it2
                    url = _fixed
        # v4.0.57：pagecount 不再写死 9999（会导致 TVBox 无限翻页、每页重复同一批数据）
        # 规则：本页为空 -> 到底；条数少于满页(约20) -> 基本到底；否则留出下一页
        try:
            _pg = int(pg or 1)
        except Exception:
            _pg = 1
        if not items:
            pagecount = max(1, _pg - 1)
        elif len(items) < 18:
            pagecount = _pg
        else:
            pagecount = _pg + 1
        return {"list": items, "page": _pg, "pagecount": pagecount, "limit": len(items), "total": len(items)}
    def _fix_cat_url(self, tid, pg):
        """分类URL自愈: LIST_TPL 拼错时(如 /zywtype/zywtype.html)，回查首页重新定位"""
        try:
            t = str(tid)
            if t.startswith("/") or t.startswith("http"):
                return ""
            # 从 LIST_TPL 里取"段名"(如 zywtype)
            seg = ""
            _m = re.search(r"//[^/]+/([A-Za-z0-9_-]+)/", self.LIST_TPL)
            if _m:
                seg = _m.group(1)
            home = self._get(self.host)
            cands = []
            for _mm in re.finditer(r'href=["\']?(/[A-Za-z0-9_\-./?=&%]+)["\']?', home or "", re.I):
                _h = _mm.group(1)
                if seg and ("/" + seg + "/") in _h and re.search(r"/\d+\.html?$", _h):
                    cands.append(_h)
            if not cands:
                # 退化: 任何 /段/数字.html 形式
                for _mm in re.finditer(r'href=["\']?(/[A-Za-z0-9_-]+/\d+\.html?)["\']?', home or "", re.I):
                    cands.append(_mm.group(1))
            if not cands:
                return ""
            base = cands[0]
            try:
                _pg = int(pg or 1)
            except Exception:
                _pg = 1
            if _pg <= 1:
                return self._abs(base)
            _m2 = re.match(r"^(.*?)(\d+)(\.html?)$", base)
            if _m2:
                return self._abs(_m2.group(1) + _m2.group(2) + "-" + str(_pg) + _m2.group(3))
            return self._abs(base)
        except Exception:
            return ""


    def detailContent(self, ids):
        vid = self._abs(str(ids[0])) if ids else ""
        if not vid:
            return {"list": []}
        html = self._get(vid)
        title = self._title(html)
        pic = self._meta(html, "og:image") or self._meta(html, "image")
        content = self._meta(html, "og:description") or self._meta(html, "description")
        # 是选集吗: 只认纯数字 / 第N集话期 / EPn / 正片等
        def is_ep(text):
            t = (text or "").strip()
            if not t:
                return False
            if re.fullmatch(r"\d{1,4}", t):
                return True
            if re.fullmatch(r"(?:第\s*)?\d{1,4}\s*[集话話期]", t):
                return True
            if re.fullmatch(r"(?i)EP?\s*\d{1,4}", t):
                return True
            if re.fullmatch(r"(?:HD|BD|TS|TC|HDTV|DVDRip|WEB-?DL|BluRay)[-\s]*(?:[\u4e00-\u9fa5]{0,4})?", t, re.I):
                return True
            if re.fullmatch(r"(?:正片|预告|花絮|抢先|完结|先导|特辑|彩蛋|加长版|国语|粤语|中字|无字)", t):
                return True
            return False
        eps_by_sid, order = {}, []
        for href, text in self._links(html, vid):
            if href == vid or "#" in href:
                continue
            if not self.PLAY_RE.search(href):
                continue
            t = (text or "").strip()
            # 排除角标/封面卡片里的非选集链接(如 更新至N集 / 立即播放)
            if re.search(r"(?:更新至|立即播放|全集|详情|更多)", t):
                continue
            if t and not is_ep(t):
                continue
            pm = re.search(r"-(\d+)[-_]\d+\.html?(?:$|\?)", href)
            sid = pm.group(1) if pm else "0"
            nm = re.search(r"[-_](\d+)\.html?(?:$|\?)", href)
            label = t or (nm.group(1) if nm else "播放")
            if sid not in eps_by_sid:
                eps_by_sid[sid] = []
                order.append(sid)
            eps_by_sid[sid].append(label + "$" + href)
        line_names = {}
        for m in re.finditer(r'<a[^>]*href="#(tabs-[^"]+)\s*"\s*>(.*?)</a>', html or "", re.I | re.S):
            label = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            nm2 = re.search(r"([A-Za-z0-9\u4e00-\u9fa5]+源)", label)
            line_names[m.group(1)] = nm2.group(1) if nm2 else label
        if not eps_by_sid:
            eps_by_sid["0"] = ["播放$" + vid]
            order = ["0"]
        try:
            order.sort(key=int)
        except Exception:
            pass
        play_from, play_urls = [], []
        for sid in order:
            play_from.append(line_names.get("tabs-home-" + sid, "线路" + sid))
            play_urls.append("#".join(eps_by_sid[sid]))
        vod = {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": pic,
            "vod_content": content,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_urls),
        }
        return {"list": [vod]}
    def searchContent(self, key, quick, pg="1"):
        url = "https://www.rjtvw.com/vodsearch/-------------.html".replace("{key}", urllib.parse.quote(key)).replace("{pg}", str(pg))
        return {"list": self._list_from_html(self._get(url), url)}

    def playerContent(self, flag, id, vipFlags):
        """播放: id 可能是播放页 URL 或直链, 统一走 _play_from_media"""
        url = self._abs(str(id)) if id else ""
        if not url:
            return {"parse": 1, "url": "", "header": self.headers}
        return self._play_from_media(url)
    def isVideoFormat(self, url):
        return True

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return

    # 需要给媒体请求补 Referer/Cookie 时，把 playerContent 返回的 url 换成 proxy 地址并启用：
    # def localProxy(self, param):
    #     url = param.get("url")
    #     r = self.fetch(url, headers=self.headers)
    #     return [200, "video/MP2T", r.content, {}]