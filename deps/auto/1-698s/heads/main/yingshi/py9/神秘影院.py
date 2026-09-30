# -*- coding: utf-8 -*-
"""
神秘影院 - WebHTV/CatVod Python Spider

修复内容:
  1. SSL连接: 添加 verify=False + 自定义SSL上下文 (SECLEVEL=0)
  2. 域名可配置: 通过 extend 参数指定自定义域名/IP, 绕过DNS污染
     用法:
       spider.init("https://newdomain.com")        -> 使用该域名作为主站
       spider.init("1.2.3.4")                       -> https://1.2.3.4 (带原Host头)
       spider.init("https://h.com|https://v.com|https://i.com")  -> 分别指定主站/视频/图片域名
  3. urllib回退: 无requests时自动使用urllib
  4. 播放地址修复: 从详情页提取实际m3u8地址而非硬编码
     - 直接查找m3u8链接
     - XOR 128解密后查找
     - 解析data属性/iframe/script变量
     - 失败时回退到默认构造
  5. header格式: 返回JSON字符串而非dict
  6. localProxy格式: 返回list格式 [code, content_type, content]
  7. 正则修复: 修复 \[] 无效正则为 /vid/(\\d+)\\.html
  8. 重试机制: HTTP请求失败自动重试2次
  9. 代理禁用: trust_env=False 避免系统代理干扰
"""

import re
import ssl
import json
import time
import sys

sys.path.append('..')
try:
    from base.spider import Spider as BaseSpile
except ImportError:
    class BaseSpile:
        def getProxyUrl(self):
            return None

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.ssl_ import create_urllib3_context
    _HAS_REQUESTS = True
except ImportError:
    requests = None
    _HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    BeautifulSoup = None
    _HAS_BS4 = False

# 禁用 urllib3 SSL 警告
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

_DEFAULT_HOST = "https://h4ivs.sm431.vip"
_DEFAULT_VIDEO_HOST = "https://38.je:38"
_DEFAULT_IMAGE_HOST = "https://36.je:36"
_UA = (
    "Mozilla/5.0 (Linux; Android 13; 22127RK46C Build/TKQ1.220905.001; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/104.0.5112.97 Mobile Safari/537.36"
)


class _PermissiveSSLAdapter(HTTPAdapter if _HAS_REQUESTS else object):
    """自定义 HTTPS 适配器: 放宽密码套件限制, 不验证证书。"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=0')
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


class VideoDecryptor:
    """XOR 128 解密"""
    @staticmethod
    def decrypt(text):
        if not text:
            return ""
        try:
            return ''.join(chr(128 ^ ord(c)) for c in text)
        except Exception:
            return text

    @staticmethod
    def from_js(js):
        m = re.search(r"document\.write\(l\('([^']+)'\)\)", js)
        return VideoDecryptor.decrypt(m.group(1)) if m else ""


class Spider(BaseSpile):

    def getName(self):
        return "神秘影院"

    def init(self, extend=""):
        # 解析 extend 参数: 支持自定义域名或 IP, 绕过 DNS 污染
        # 格式1: "https://newdomain.com"            -> 主站域名
        # 格式2: "1.2.3.4"                           -> https://1.2.3.4 (带原Host头)
        # 格式3: "https://h|https://v|https://i"     -> 分别指定 主站|视频|图片 域名
        self._host = _DEFAULT_HOST
        self._video_host = _DEFAULT_VIDEO_HOST
        self._image_host = _DEFAULT_IMAGE_HOST
        self._custom_ip = None
        self._original_host = "h4ivs.sm431.vip"

        if extend:
            extend = extend.strip()
            parts = extend.split("|")

            # 主站域名
            host_part = parts[0].strip() if parts else ""
            if host_part:
                if re.match(r'^\d+\.\d+\.\d+\.\d+$', host_part):
                    # 纯 IP 地址
                    self._custom_ip = host_part
                    self._host = "https://" + host_part
                elif host_part.startswith("http"):
                    self._host = host_part.rstrip("/")
                    m = re.match(r'https?://([^/:]+)', host_part)
                    if m:
                        self._original_host = m.group(1)
                else:
                    self._host = "https://" + host_part
                    self._original_host = host_part

            # 视频域名
            if len(parts) > 1 and parts[1].strip():
                v = parts[1].strip()
                self._video_host = v if v.startswith("http") else "https://" + v
                self._video_host = self._video_host.rstrip("/")

            # 图片域名
            if len(parts) > 2 and parts[2].strip():
                i = parts[2].strip()
                self._image_host = i if i.startswith("http") else "https://" + i
                self._image_host = self._image_host.rstrip("/")

        self.headers = {
            "User-Agent": _UA,
            "Referer": self._host,
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        # 初始化 HTTP 会话
        if _HAS_REQUESTS:
            self.session = requests.Session()
            self.session.mount('https://', _PermissiveSSLAdapter())
            self.session.headers.update(self.headers)
            self.session.trust_env = False  # 禁用系统代理, 避免 DNS 污染干扰
            if self._custom_ip:
                self.session.headers["Host"] = self._original_host
        else:
            self.session = None

        self.cache = {}
        self._detail_cache = {}  # 详情页 HTML 缓存, 供 playerContent 使用

    # ═══════════ HTTP 请求封装 (带重试和SSL绕过) ═══════════

    def _fetch(self, url, retries=2):
        """带重试和 SSL 绕过的 HTTP GET"""
        last_err = None
        for attempt in range(retries + 1):
            try:
                if _HAS_REQUESTS:
                    return self._fetch_requests(url)
                else:
                    return self._fetch_urllib(url)
            except Exception as e:
                last_err = e
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
        return ""

    def _fetch_requests(self, url):
        r = self.session.get(url, timeout=15, verify=False,
                             proxies={"http": None, "https": None})
        r.raise_for_status()
        r.encoding = "utf-8"
        return r.text

    def _fetch_urllib(self, url):
        from urllib.request import Request, urlopen

        headers = dict(self.headers)
        if self._custom_ip:
            headers["Host"] = self._original_host

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers('DEFAULT@SECLEVEL=0')

        req = Request(url, headers=headers)
        with urlopen(req, timeout=15, context=ctx) as resp:
            data = resp.read()
            try:
                return data.decode("utf-8")
            except Exception:
                return data.decode("latin-1")

    def get(self, url):
        """兼容旧接口的 HTTP GET"""
        return self._fetch(url)

    # ═══════════ 图片URL格式化 ═══════════

    def img_url(self, url):
        """格式化图片URL"""
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = self._image_host + url
        return f"{url}@User-Agent={self.headers['User-Agent']}@Referer={self._host}/"

    # ═══════════ 卡片解析 ═══════════

    def parse(self, el):
        """解析卡片"""
        a = el if el.name == 'a' else el.find('a')
        if not a or not (href := a.get("href", "")):
            return None

        href = self._host + href if href.startswith("/") else href
        if not (vid := re.search(r"/vid/(\d+)", href)):
            return None

        vid = vid.group(1)
        title = ""

        # 解密标题
        if p := el.find('p'):
            if s := p.find('script'):
                if s.string:
                    title = VideoDecryptor.from_js(s.string)
            title = title or p.get_text(strip=True)

        if not title:
            for attr in ['data-title', 'data-name', 'title']:
                if el.has_attr(attr) and (val := el[attr]):
                    if (de := VideoDecryptor.decrypt(val)) and len(de) > 3:
                        title = de
                        break

        title = title or "未知标题"
        if title != "未知标题":
            self.cache[vid] = title

        # 图片
        img = ""
        if node := el.select_one("img"):
            img = node.get("data-src") or node.get("src") or ""
        img = img or f"{self._image_host}/{vid}.jpg"

        return {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": self.img_url(img),
            "vod_remarks": "",
        }

    def get_title(self, vid):
        """从缓存或首页获取标题"""
        if vid in self.cache:
            return self.cache[vid]

        if html := self.get(self._host):
            if _HAS_BS4:
                soup = BeautifulSoup(html, "html.parser")
                for link in soup.select('a[href*="/vid/"]'):
                    if f'/vid/{vid}' in link.get('href', ''):
                        if p := link.find('p'):
                            if s := p.find('script'):
                                if s.string and (t := VideoDecryptor.from_js(s.string)):
                                    self.cache[vid] = t
                                    return t
                            if t := p.get_text(strip=True):
                                self.cache[vid] = t
                                return t
        return None

    # ═══════════ 首页 ═══════════

    def homeContent(self, filter):
        return {
            "class": [
                {"type_name": "国产", "type_id": "1"},
                {"type_name": "日本", "type_id": "2"},
                {"type_name": "韩国", "type_id": "3"},
                {"type_name": "欧美", "type_id": "4"},
                {"type_name": "三级", "type_id": "5"},
                {"type_name": "动漫", "type_id": "6"},
            ]
        }

    def _parse_videos_from_html(self, html):
        """从 HTML 中解析视频列表 (修复正则 bug)"""
        videos = []
        if _HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            videos = [v for v in (self.parse(el) for el in soup.select(
                ".vodbox, .stui-vodlist__box, .vodlist__box, .video-card, .item")) if v]

        if not videos:
            # 修复: 原 \[]\(/vid/(\d+)\.html\) 是无效正则
            # 改为直接查找 /vid/数字.html 模式
            vids = re.findall(r'/vid/(\d+)\.html', html)
            videos = [{"vod_id": v, "vod_name": "未知标题",
                       "vod_pic": self.img_url(f"{self._image_host}/{v}.jpg"),
                       "vod_remarks": ""} for v in vids]
        return videos

    def homeVideoContent(self):
        if not (html := self.get(self._host)):
            return {"list": []}
        return {"list": self._parse_videos_from_html(html)}

    # ═══════════ 分类列表 ═══════════

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if str(pg).isdigit() else 1
        except (ValueError, TypeError):
            pg = 1

        if tid == "0":
            url = self._host if pg == 1 else f"{self._host}/page/{pg}.html"
        else:
            url = f"{self._host}/list/{tid}.html" if pg == 1 else f"{self._host}/list/{tid}/{pg}.html"

        if not (html := self.get(url)):
            return {"list": [], "page": pg, "pagecount": 1, "limit": 30, "total": 0}

        videos = self._parse_videos_from_html(html)

        last = pg
        if _HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            last = max([int(m.group(1)) for a in soup.select("a[href*='list/']")
                        if (m := re.search(r"/list/\d+/(\d+)\.html", a.get("href", "")))], default=pg)

        return {"list": videos, "page": pg, "pagecount": max(last, 1), "limit": 30, "total": 99999}

    # ═══════════ 搜索 ═══════════

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg) if str(pg).isdigit() else 1
        except (ValueError, TypeError):
            pg = 1

        url = f"{self._host}/so.html"
        params = {"wd": key}
        if pg > 1:
            params["page"] = str(pg)

        html = ""
        # 尝试 GET 和 POST
        for method in ["GET", "POST"]:
            try:
                if _HAS_REQUESTS:
                    if method == "GET":
                        r = self.session.get(url, params=params, timeout=15, verify=False,
                                             proxies={"http": None, "https": None})
                    else:
                        r = self.session.post(url, data=params, timeout=15, verify=False,
                                              proxies={"http": None, "https": None})
                    r.raise_for_status()
                    r.encoding = "utf-8"
                    html = r.text
                else:
                    from urllib.request import Request, urlopen
                    from urllib.parse import urlencode

                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    ctx.set_ciphers('DEFAULT@SECLEVEL=0')

                    if method == "GET":
                        full_url = url + "?" + urlencode(params)
                        req = Request(full_url, headers=self.headers)
                    else:
                        data = urlencode(params).encode("utf-8")
                        h = dict(self.headers)
                        h["Content-Type"] = "application/x-www-form-urlencoded"
                        req = Request(url, data=data, headers=h, method="POST")

                    with urlopen(req, timeout=15, context=ctx) as resp:
                        html = resp.read().decode("utf-8", errors="ignore")

                if html:
                    break
            except Exception:
                continue

        if not html:
            return {"list": []}

        videos = self._parse_videos_from_html(html)

        last = pg
        if _HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            last = max([int(m.group(1)) for a in soup.select(
                "a[href*='so.html'], .pagination a, .page-link")
                if (m := re.search(r"[?&]page=(\d+)", a.get("href", "")))], default=pg)

        return {"list": videos, "page": pg, "pagecount": max(last, 1), "limit": 30, "total": 99999}

    # ═══════════ 详情 ═══════════

    def detailContent(self, ids):
        vid = str(ids[0]) if ids else ""
        if not vid:
            return {"list": []}

        html = self.get(f"{self._host}/vid/{vid}.html")
        if not html:
            return {"list": []}

        # 缓存详情页 HTML 供 playerContent 使用
        self._detail_cache[vid] = html

        if not _HAS_BS4:
            # 无 BeautifulSoup 时返回基本信息
            title = self.cache.get(vid, f"视频{vid}")
            return {"list": [{
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": self.img_url(f"{self._image_host}/{vid}.jpg"),
                "vod_content": "",
                "vod_play_from": "神秘影院",
                "vod_play_url": f"正片${vid}@@0@@1",
            }]}

        soup = BeautifulSoup(html, "html.parser")

        # 标题
        title = self.get_title(vid)
        if not title:
            if t := soup.find('title'):
                title = re.sub(r'\s*[-_|]\s*.{0,20}$', '', t.get_text(strip=True)).strip()

            if not title or len(title) < 5:
                for sel in ['h1', 'h2', '.video-title', '.title']:
                    if (el := soup.select_one(sel)) and (txt := el.get_text(strip=True)) and len(txt) > 5:
                        title = txt
                        break

        title = title or f"视频{vid}"

        # 图片
        pic = ""
        for sel in ['.picbox img', '.vodimg img', '.video-pic img', '.poster img', 'img[data-id]']:
            if (node := soup.select_one(sel)) and (p := node.get("data-src") or node.get("src")) and 'favicon' not in p.lower():
                pic = p
                break

        if not pic or 'favicon' in pic.lower():
            if meta := soup.select_one('meta[property="og:image"]'):
                pic = meta.get('content', '')

        pic = pic or f"{self._image_host}/{vid}.jpg"

        # 简介
        desc_node = soup.select_one(".vodinfo, .video-info, .content, .intro, .description")
        desc = desc_node.get_text(strip=True) if desc_node else ""

        return {"list": [{
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": self.img_url(pic),
            "vod_content": desc,
            "vod_play_from": "神秘影院",
            "vod_play_url": f"正片${vid}@@0@@1",
        }]}

    # ═══════════ 播放地址提取 (核心修复) ═══════════

    def _normalize_url(self, url):
        """将相对URL转为绝对URL"""
        if not url:
            return ""
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self._host + url
        return self._host + "/" + url

    def _extract_m3u8(self, vid):
        """从详情页提取实际 m3u8 播放地址 (多种方法尝试)"""
        # 使用缓存的详情页 HTML
        html = self._detail_cache.get(vid, "")
        if not html:
            html = self.get(f"{self._host}/vid/{vid}.html")
        if not html:
            return ""

        # 方法1 (最高优先): 从 JavaScript bfz 变量提取 (DPlayer 模式)
        # 神秘影院详情页 JS: let bfz='https://38.je:38/'+vid.dataset.id+'/index.m3u8';
        if m := re.search(
                r"bfz\s*=\s*['\"]([^'\"]+)['\"]\s*\+\s*vid\.dataset\.id\s*\+\s*['\"]([^'\"]*)['\"]",
                html):
            prefix = m.group(1)
            suffix = m.group(2)
            return prefix + vid + suffix

        # 方法1b: DPlayer video.url 直接赋值
        # const dp = new DPlayer({...video:{url:'https://...m3u8'...}})
        if m := re.search(r"video\s*:\s*\{[^}]*url\s*:\s*['\"]([^'\"]+)['\"]", html):
            url = m.group(1)
            if 'm3u8' in url or '/hls/' in url:
                return url

        # 方法2: 直接查找完整 m3u8 URL
        m3u8s = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
        if m3u8s:
            return m3u8s[0]

        # 方法3: XOR 128 解密后查找 m3u8
        xor_matches = re.findall(r"document\.write\(l\('([^']+)'\)\)", html)
        for enc in xor_matches:
            dec = VideoDecryptor.decrypt(enc)
            # 在解密内容中查找完整 m3u8 URL
            m3u8s = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', dec)
            if m3u8s:
                return m3u8s[0]
            # 检查是否包含 /hls/ 路径
            if '/hls/' in dec:
                paths = re.findall(r'[^\s"\'<>]*/hls/[^\s"\'<>]+', dec)
                if paths:
                    p = paths[0]
                    if p.startswith("http"):
                        return p
                    if p.startswith("//"):
                        return "https:" + p
                    return self._video_host + "/" + p.lstrip("/")

        # 方法4: 解析 HTML 中的 data 属性
        if _HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all(True):
                for attr in ['data-url', 'data-src', 'data-play', 'data-video',
                             'data-m3u8', 'data-source', 'data-stream']:
                    val = tag.get(attr, "")
                    if val and ('m3u8' in val.lower() or '/hls/' in val):
                        return self._normalize_url(val)

            # 方法5: 查找 iframe
            for iframe in soup.find_all('iframe'):
                src = iframe.get('src', '')
                if src and ('m3u8' in src.lower() or 'player' in src.lower() or '/hls/' in src):
                    return self._normalize_url(src)

            # 方法6: 查找 script 中的 player 变量
            for script in soup.find_all('script'):
                text = script.string or ""
                if not text:
                    continue

                # player_aaaa = {...}
                if m := re.search(r'player_aaaa\s*=\s*(\{[^}]+\})', text):
                    try:
                        pdata = json.loads(m.group(1))
                        if url := pdata.get('url', ''):
                            return url
                    except Exception:
                        pass

                # var url/playUrl/videoUrl/source = "..."
                for var_name in ['url', 'playUrl', 'videoUrl', 'source', 'play_url', 'm3u8url']:
                    if m := re.search(
                            rf'(?:var\s+)?{var_name}\s*=\s*["\']([^"\']+)["\']', text):
                        url = m.group(1)
                        if 'm3u8' in url.lower() or '/hls/' in url:
                            return self._normalize_url(url)

                # 查找 script 中的 .m3u8 字符串
                m3u8s = re.findall(r'["\']([^"\']*\.m3u8[^"\']*)["\']', text)
                if m3u8s:
                    url = m3u8s[0]
                    if url.startswith("http"):
                        return url
                    if url.startswith("//"):
                        return "https:" + url
                    if url.startswith("/"):
                        return self._host + url
                    return self._video_host + "/" + url.lstrip("/")

        # 方法7: 查找 video_host + /hls/ 路径模式
        if '/hls/' in html:
            paths = re.findall(r'(/[^"\s<>]*/hls/[^"\s<>]+)', html)
            if paths:
                return self._video_host + paths[0]

        return ""

    def playerContent(self, flag, id, vipFlags):
        vid = str(id).split("@@")[0]

        # 从详情页提取实际 m3u8 地址
        m3u8_url = self._extract_m3u8(vid)

        # 如果提取失败, 使用默认构造 (URL 模式: {video_host}/{vid}/index.m3u8)
        if not m3u8_url:
            m3u8_url = f"{self._video_host}/{vid}/index.m3u8"

        # header 必须是 JSON 字符串 (非 dict)
        header_str = json.dumps(self.headers, ensure_ascii=False)

        return {
            "parse": 0,
            "url": m3u8_url,
            "header": header_str,
        }

    # ═══════════ 其他接口 ═══════════

    def localProxy(self, param):
        # 返回 list 格式: [code, content_type, content]
        return [200, "text/plain", ""]

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(?:m3u8|mp4|flv)', url or "", re.I))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass
