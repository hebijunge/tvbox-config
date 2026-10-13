# coding=utf-8
# ============================================================
# 51吃瓜 海阔视界 py 视频源（自动挡·发布页AES解密版）
# 学习"小心儿悠悠"完整版：发布页 appConfig data+key AES 解密自动取域名
#  发布页: https://www.qcoplglgu.com/ (IV=密文前16字节, key=SHA256(key_str))
#  动态抓分类: 菜单 #menu-menu-1（含下拉子分类）
#  多集播放: dplayer data-config / 子链接并发抓取
# ============================================================
import json, re, sys, hashlib, base64
import urllib.parse
from urllib.parse import urlparse
import requests

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        pass

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    HAS_CRYPTO = True
except Exception:
    HAS_CRYPTO = False

try:
    from pyquery import PyQuery as pq
    HAS_PQ = True
except Exception:
    HAS_PQ = False

# 并发抓子链接播放（羊壳支持 concurrent.futures 则用，否则降级串行）
try:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    HAS_THREAD = True
except Exception:
    HAS_THREAD = False


class Spider(Spider):

    def getName(self):
        return "51吃瓜"

    def init(self, extend=""):
        try:
            self.proxies = json.loads(extend) if extend else {}
        except Exception:
            self.proxies = {}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
        # 🌟 自动域名：发布页 appConfig AES 解密 → 测活（域名换了自动跟上）
        self.host = self.get_working_host()
        if self.host:
            self.headers.update({"Origin": self.host, "Referer": self.host + "/"})
        # 备用入口（发布页失效时直接测活这些）
        self.fallback_hosts = [
            "https://bind.nmhrouqg.cc/",
            "https://ability.vgwtswi.xyz",
            "https://am.vgwtswi.xyz",
        ]
        if not self.host:
            for fh in self.fallback_hosts:
                try:
                    r = requests.get(fh, headers=self.headers, timeout=6, verify=False)
                    if r.status_code == 200 and ("article" in r.text):
                        self.host = fh
                        break
                except Exception:
                    continue
        # 动态抓分类（菜单含子分类）
        self.classes = []
        self._categories_fetched = False
        self._init_classes()
        # 🎛️ 类型筛选（对应 json"类型"字段，|| 按分类顺序分组）
        self.filters_data = {
            "xsxy": [("学生校园", "xsxy"), ("网红黑料", "whhl"), ("热门大瓜", "rdsj"), ("吃瓜榜单", "mrdg"), ("必看大瓜", "bkdg")],
            "cbdj": [("AI成人短剧", "cbdj"), ("看片娱乐", "ysyl"), ("每日大赛", "mrds"), ("伦理道德", "lldd"), ("探花精选", "thjx"), ("国产剧情", "gcjq"), ("网黄合集", "whhj")],
            "snsn": [("骚男骚女", "snsn"), ("明星黑料", "whmx"), ("海外吃瓜", "hwcg"), ("人人吃瓜", "rrcg"), ("领导干部", "ldcg"), ("软萌甜妹", "jpll")],
            "qubk": [("吃瓜看戏", "qubk"), ("擦边聊骚", "dcbq"), ("51涨知识", "zzs"), ("吃瓜新闻", "cgxw")],
            "51by": [("51品茶", "51by"), ("原创博主", "yczq"), ("51剧场", "51djc")],
        }

    def _init_classes(self):
        # 📋 分类 = 6 个主分类（对应 XBPQ json"分类"字段，主分类+类型筛选结构）
        self.classes = [
            {"type_id": "wpcz", "type_name": "今日吃瓜"},
            {"type_id": "xsxy", "type_name": "吃瓜热门"},
            {"type_id": "cbdj", "type_name": "娱乐天地"},
            {"type_id": "snsn", "type_name": "黑料事件"},
            {"type_id": "qubk", "type_name": "吃瓜百科"},
            {"type_id": "51by", "type_name": "51原创"},
        ]
        # 动态补充菜单里的其他主分类（如往期/标签云，若有）
        try:
            if not self.host:
                return
            r = requests.get(self.host, headers=self.headers, timeout=10, verify=False)
            if r.status_code != 200:
                return
            html = r.text
            menu_m = re.search(r'id="menu-menu-1".*?</ul>', html, re.S)
            if not menu_m:
                return
            menu = menu_m.group(0)
            existing = {c["type_id"] for c in self.classes}
            flat = re.findall(r'<li[^>]*>\s*<a[^>]*href="(/category/([^"/]+)/)"[^>]*>\s*([^<]{1,25})<', menu)
            for href, slug, name in flat:
                name = name.strip()
                if name and slug not in existing and "/category/" in href:
                    self.classes.append({"type_name": name, "type_id": slug})
                    existing.add(slug)
        except Exception:
            pass

    # ================= 域名自动解密 =================
    def get_working_host(self):
        # 域名获取：直接测活优先（保留直连可用的第一版方法，不依赖发布页解密）
        candidates = ['https://ability.vgwtswi.xyz', 'https://am.vgwtswi.xyz', 'https://artist.vgwtswi.xyz']
        for url in candidates:
            try:
                resp = requests.get(url, headers=self.headers, proxies=getattr(self,"proxies",None), timeout=8, verify=False)
                if resp.status_code == 200 and ("<article" in resp.text or "article" in resp.text):
                    return url
            except Exception:
                continue
        return ""

    def getpq(self, data):
        try:
            return pq(data)
        except Exception:
            return pq(data.encode("utf-8"))

    def _req(self, url):
        try:
            r = requests.get(url, headers=self.headers, proxies=getattr(self,"proxies",None), timeout=12, verify=False)
            return r.text if r.status_code == 200 else ""
        except Exception:
            return ""

    def _fix_url(self, url):
        if not url:
            return ""
        url = url.replace("\\/", "/").replace("&amp;", "&")
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.host.rstrip("/") + url
        if url.startswith("http"):
            return url
        return self.host.rstrip("/") + "/" + url

    def _clean_html(self, text):
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def e64(self, text):
        try:
            return base64.b64encode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def d64(self, text):
        try:
            return base64.b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    # ================= 列表解析 =================
    def getimg(self, text):
        """loadBannerDirect 明文 URL → 本地代理解密"""
        m = re.search(r"loadBannerDirect\('([^']+)'", text or "")
        if m:
            return self.getProxyUrl() + "&url=" + m.group(1) + "&type=img"
        return ""

    def aesimg(self, word):
        """图片 AES 解密（key/iv 与 json 一致）"""
        if not HAS_CRYPTO:
            return word
        try:
            key = b"f5d965df75336270"
            iv = b"97b60394abc2fbe1"
            cipher = AES.new(key, AES.MODE_CBC, iv)
            return unpad(cipher.decrypt(word), AES.block_size)
        except Exception:
            return word

    def getlist(self, data, tid=""):
        videos = []
        l = "/mrdg" in tid  # 吃瓜榜单 → folder
        for k in data.items():
            a = k.attr("href")
            if not a:
                continue
            title = k("h2").text().strip()
            if not title:
                m = re.search(r"/archives/(\d+)/", a)
                if m:
                    title = "51剧场 #" + m.group(1)
                else:
                    continue
            raw = k('span[itemprop="datePublished"]').text() or k(".post-meta, .entry-meta, time").text()
            if raw:
                raw = re.sub(r"[•·]+\s*$", "", raw).strip()
            videos.append({
                "vod_id": a + ("@folder" if l else ""),
                "vod_name": title.replace("\n", " "),
                "vod_pic": self.getimg(k("script").text()),
                "vod_remarks": raw or "",
                "vod_tag": "folder" if l else "",
                "style": {"type": "rect", "ratio": 1.33},
            })
        return videos

    def homeContent(self, filter):
        try:
            if not self.host:
                return {"class": [], "list": []}
            r = requests.get(self.host, headers=self.headers, proxies=getattr(self,"proxies",None), timeout=12, verify=False)
            if r.status_code != 200:
                return {"class": self.classes, "list": []}
            data = self.getpq(r.text)
            # 🎛️ 类型筛选（hongguo2 风格：filter_dict = {type_id: groups}）
            filters = {}
            for cid, items in self.filters_data.items():
                if items:
                    filters[cid] = [{
                        "key": "类型",
                        "name": "类型",
                        "value": [{"v": "", "n": "全部"}] + [{"v": v, "n": n} for n, v in items],
                    }]
            return {"class": self.classes, "list": self.getlist(data("#index article a")), "filters": filters}
        except Exception:
            return {"class": self.classes, "list": []}

    def homeVideoContent(self):
        try:
            if not self.host:
                return {"list": []}
            r = requests.get(self.host, headers=self.headers, proxies=getattr(self,"proxies",None), timeout=12, verify=False)
            if r.status_code != 200:
                return {"list": []}
            data = self.getpq(r.text)
            return {"list": self.getlist(data("#index article a, #archive article a"))}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            # 🎛️ 筛选合并（hongguo2 写法：for d in [filter, extend] 合并 params，排除 page/pg）
            params = {}
            for d in [filter, extend]:
                if isinstance(d, dict):
                    for k, v in d.items():
                        if v and k not in ("page", "pg"):
                            params[k] = v
            if params.get("类型"):
                tid = str(params["类型"])
            if "@folder" in tid:
                videos = self.getfod(tid.replace("@folder", ""))
                return {"list": videos, "page": pg, "pagecount": 1, "limit": 90, "total": len(videos)}
            url = self._cat_url(tid, pg)
            if not url:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}
            r = requests.get(url, headers=self.headers, proxies=getattr(self,"proxies",None), timeout=12, verify=False)
            if r.status_code != 200:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}
            data = self.getpq(r.text)
            videos = self.getlist(data("#archive article a, #index article a"), tid)
            return {"list": videos, "page": pg, "pagecount": 99999, "limit": 90, "total": 999999}
        except Exception:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 90, "total": 0}

    def _cat_url(self, tid, pg):
        if not self.host:
            return ""
        pg = int(pg)
        if tid == "archives":
            return self.host + "/archives.html" if pg == 1 else self.host + "/archives/page/" + str(pg) + "/"
        if tid == "tags":
            return self.host + "/tags/" + str(pg) + "/"
        return self.host + "/category/" + tid + "/" if pg == 1 else self.host + "/category/" + tid + "/" + str(pg) + "/"

    def getfod(self, id):
        """吃瓜榜单 folder：文章内子链接列表"""
        url = self._fix_url(id)
        html = self._req(url)
        if not html:
            return []
        data = self.getpq(html)
        vdata = data('.post-content[itemprop="articleBody"]')
        for sel in [".txt-apps", ".line", "blockquote", ".tags", ".content-tabs"]:
            try:
                vdata.remove(sel)
            except Exception:
                pass
        p = vdata("p")
        videos = []
        for i, x in enumerate(vdata("h2").items()):
            c = i * 2
            href = p.eq(c)("a").attr("href")
            name = p.eq(c).text()
            pic = ""
            img_attr = p.eq(c + 1)("img").attr("data-xkrkllgl")
            if img_attr:
                pic = self.getProxyUrl() + "&url=" + img_attr + "&type=img"
            if href and name:
                videos.append({
                    "vod_id": href,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": x.text(),
                })
        return videos

    # ================= 详情/播放 =================
    def _extract_title_from_html(self, html_text):
        title = ""
        try:
            doc = self.getpq(html_text)
            title = doc("title").text().strip()
            if not title:
                title = doc('meta[property="og:title"]').attr("content") or ""
            if not title:
                title = doc("h1.post-title").text().strip() or doc("h1").eq(0).text().strip()
        except Exception:
            pass
        if not title:
            m = re.search(r"<title>(.*?)</title>", html_text, re.I | re.S)
            if m:
                title = m.group(1).strip()
        if title:
            title = re.sub(r"\s*[–\-|]\s*(51吃瓜网|51吃瓜|吃瓜).*$", "", title).strip()
        return title

    def _parse_dplayer(self, html_text, data):
        """解析页面里所有 dplayer 的播放地址"""
        result = []
        dplayers = data(".dplayer")
        if not dplayers:
            return result
        for idx, k in enumerate(dplayers.items()):
            cfg = k.attr("data-config")
            if not cfg:
                continue
            try:
                config = json.loads(cfg)
                video_url = config.get("video", {}).get("url", "")
                if not video_url:
                    video_url = config.get("video_h265", {}).get("url", "")
                if video_url:
                    result.append(video_url.replace("\\/", "/"))
            except Exception:
                continue
        return result

    def detailContent(self, ids):
        try:
            if not self.host:
                return {"list": [{"vod_play_from": "51吃瓜", "vod_play_url": "无法获取地址"}]}
            url = ids[0]
            if not url.startswith("http"):
                url = self.host + url
            r = requests.get(url, headers=self.headers, proxies=getattr(self,"proxies",None), timeout=12, verify=False)
            if r.status_code != 200:
                return {"list": [{"vod_play_from": "51吃瓜", "vod_play_url": "页面加载失败$" + url}]}
            data = self.getpq(r.text)
            vod = {"vod_play_from": "51吃瓜"}

            # 标题
            headline = self._extract_title_from_html(r.text)
            if not headline:
                headline = data(".post-title").text().strip() or data("h1").text().strip()
            vod["vod_name"] = headline or "51吃瓜"

            # 图片
            img = self.getimg(data("script").text())
            if not img:
                og = data('meta[property="og:image"]').attr("content")
                if og:
                    img = self.getProxyUrl() + "&url=" + og + "&type=img"
            vod["vod_pic"] = img

            # 播放：dplayer
            plist = []
            dplayers = data(".dplayer")
            if dplayers:
                if len(dplayers) == 1:
                    for u in self._parse_dplayer(r.text, data):
                        plist.append((headline or "51吃瓜", u))
                else:
                    # 多集：匹配"第N集"标题
                    ep_matches = re.findall(r"(第[一二三四五六七八九十百]+集)", r.text)
                    for idx, u in enumerate(self._parse_dplayer(r.text, data)):
                        ep = ep_matches[idx] if idx < len(ep_matches) else "第" + str(idx + 1) + "集"
                        plist.append((ep, u))
            else:
                # 无 dplayer：子链接并发抓播放（合集）
                post_content = data(".post-content")
                sub_links = post_content('a[href^="/archives/"]')
                seen_hrefs = set()
                link_items = []
                for link in sub_links.items():
                    href = link.attr("href")
                    if href and href not in seen_hrefs:
                        seen_hrefs.add(href)
                        link_items.append(href)
                if not link_items:
                    vod["vod_play_url"] = (headline or "51吃瓜") + "$" + url
                    return {"list": [vod]}

                def fetch_video(href, idx):
                    full = href if href.startswith("http") else (self.host + href)
                    if full == url:
                        return idx, None, None
                    try:
                        sub_r = requests.get(full, headers=self.headers, proxies=getattr(self,"proxies",None), timeout=10, verify=False)
                        if sub_r.status_code != 200:
                            return idx, None, None
                        sub_data = self.getpq(sub_r.text)
                        for u in self._parse_dplayer(sub_r.text, sub_data):
                            ep = self._extract_title_from_html(sub_r.text)
                            if not ep:
                                ep = "第" + str(idx + 1) + "集"
                            return idx, ep, u
                        return idx, None, None
                    except Exception:
                        return idx, None, None

                results = []
                if HAS_THREAD:
                    try:
                        with ThreadPoolExecutor(max_workers=8) as executor:
                            futures = [executor.submit(fetch_video, h, i) for i, h in enumerate(link_items)]
                            for future in as_completed(futures):
                                results.append(future.result())
                    except Exception:
                        results = [fetch_video(h, i) for i, h in enumerate(link_items)]
                else:
                    results = [fetch_video(h, i) for i, h in enumerate(link_items)]
                results.sort(key=lambda x: x[0])
                for idx, ep, video_url in results:
                    if ep and video_url:
                        plist.append((ep, video_url))

            if plist:
                vod["vod_play_url"] = "#".join([n + "$" + u for n, u in plist])
            else:
                # 广告文识别
                if "btn-download" in r.text or "下载APP" in r.text:
                    vod["vod_play_url"] = "无视频源（APP专属/引导文）$" + url
                else:
                    vod["vod_play_url"] = "未找到视频源$" + url
            return {"list": [vod]}
        except Exception:
            return {"list": [{"vod_play_from": "51吃瓜", "vod_play_url": "加载失败$" + (ids[0] if ids else "")}]}

    # ================= 搜索 =================
    def searchContent(self, key, quick, pg="1"):
        try:
            if not self.host:
                return {"list": [], "page": pg}
            url = self.host + "/search/" + urllib.parse.quote(key) + "/"
            if pg and pg != "1":
                url = self.host + "/search/" + urllib.parse.quote(key) + "/" + str(pg) + "/"
            r = requests.get(url, headers=self.headers, proxies=getattr(self,"proxies",None), timeout=12, verify=False)
            if r.status_code != 200:
                return {"list": [], "page": pg}
            data = self.getpq(r.text)
            return {"list": self.getlist(data("#archive article a, #index article a")), "page": pg}
        except Exception:
            return {"list": [], "page": pg}

    def searchContentPage(self, key, quick, pg="1"):
        return self.searchContent(key, quick, pg)

    # ================= 播放 =================
    def playerContent(self, flag, id, vipFlags):
        url = id
        p = 1
        if self.isVideoFormat(url):
            if ".m3u8" in url:
                url = self.proxy(url)
            p = 0
        return {"parse": p, "url": url, "header": self.headers}

    def proxy(self, data, type="m3u8"):
        if data and len(self.proxies):
            return self.getProxyUrl() + "&url=" + self.e64(data) + "&type=" + type
        return data

    def localProxy(self, param):
        if param.get("type") == "img":
            res = requests.get(param["url"], headers=self.headers, proxies=getattr(self,"proxies",None), timeout=10, verify=False)
            return [200, res.headers.get("Content-Type"), self.aesimg(res.content)]
        elif param.get("type") == "m3u8":
            return self.m3Proxy(param["url"])
        else:
            return self.tsProxy(param["url"])

    def m3Proxy(self, url):
        url = self.d64(url)
        ydata = requests.get(url, headers=self.headers, proxies=getattr(self,"proxies",None), allow_redirects=False, timeout=10, verify=False)
        data = ydata.content.decode("utf-8")
        if ydata.headers.get("Location"):
            url = ydata.headers["Location"]
            data = requests.get(url, headers=self.headers, proxies=getattr(self,"proxies",None), timeout=10, verify=False).content.decode("utf-8")
        lines = data.strip().split("\n")
        last_r = url[:url.rfind("/")]
        parsed_url = urlparse(url)
        durl = parsed_url.scheme + "://" + parsed_url.netloc
        iskey = True
        for index, string in enumerate(lines):
            if iskey and "URI" in string:
                pattern = r'URI="([^"]*)"'
                match = re.search(pattern, string)
                if match:
                    lines[index] = re.sub(pattern, 'URI="' + self.proxy(match.group(1), "mkey") + '"', string)
                    iskey = False
                    continue
            if "#EXT" not in string:
                if "http" not in string:
                    domain = last_r if string.count("/") < 2 else durl
                    string = domain + ("" if string.startswith("/") else "/") + string
                lines[index] = self.proxy(string, string.split(".")[-1].split("?")[0])
        data = "\n".join(lines)
        return [200, "application/vnd.apple.mpegur", data]

    def tsProxy(self, url):
        url = self.d64(url)
        data = requests.get(url, headers=self.headers, proxies=getattr(self,"proxies",None), stream=True, timeout=10, verify=False)
        return [200, data.headers["Content-Type"], data.content]

    def isVideoFormat(self, url):
        return any(ext in (url or "") for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass
