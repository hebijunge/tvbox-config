#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sehuav.cc 爬虫 (hipy/drpy2-py 风格, 兼容 FongMi / OK影视 / 羊壳)

站点要点(2026-08-24 实测):
- 页面是 document.write(decodeURIComponent("...")) 包裹的 HTML, 文本全是 HTML 数字实体(&#x....;)
- 分类: /category/<tid>, 分页 /category/<tid>/<pg>/
- 搜索: /search/<关键词>, 分页 /search/<关键词>/<pg>/  (不是 ?key=)
- 详情: /view/<hex-id>, 视频地址在页内脚本 var url="https://res-msXX.vofixkw.com/m3u8/.../index.m3u8?sign=..."
- m3u8 与封面均要求 Referer: 站点首页, 否则 403
- 封面 <img data-original="https://res-msXX.vofixkw.com/image/img/....dat"> 内容是 BASE64(WEBP)
"""

import re
import json
import time
import html as _html
import base64
import ssl
import threading
import urllib.request
import urllib.parse

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    try:
        from drpy2.spider import Spider as BaseSpider
    except ImportError:
        try:
            from spider_base import Spider as BaseSpider
        except ImportError:
            BaseSpider = object

UA = 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
DEFAULT_HOST = 'https://sehuav.cc'

# 发布页保底地址（当前域名失效时从这里获取最新入口）
PUBLISH_URL = 'https://1.s2689hu.cc/'

# 分类 tid -> 名称 (取自站内导航, 顺序即导航顺序)
CATS = [
    ('1', '大陆'), ('2', '日韩'), ('3', '欧美'), ('4', '动漫'), ('5', '综艺'),
    ('6', '国产传媒'), ('7', '偷拍自拍'),
    ('35', '绿帽偷情'), ('36', 'JK萝莉'), ('37', '强奸迷奸'), ('38', '网红主播'),
    ('39', '吃瓜黑料'), ('10', '日韩无码'), ('11', '中文字幕'), ('12', '日韩杂类'),
    ('19', '欧美无码'), ('20', '黑白专区'), ('23', '少女动漫'), ('30', '网爆黑料'),
    ('28', '其他综艺'),
]
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_PIC_CACHE = {}          # url -> data:URI 字符串
_PIC_LOCK = threading.Lock()
_RE_BLOCK_SPLIT = re.compile(r'item-vide-n')

# 发布页解析缓存
_PUB_CACHE = {'host': '', 'ts': 0}
_PUB_LOCK = threading.Lock()
_PUB_TTL = 1800          # 发布页结果缓存 30 分钟


def _hms(sec):
    try:
        sec = int(sec)
    except Exception:
        return ''
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return '%d:%02d:%02d' % (h, m, s) if h else '%d:%02d' % (m, s)


class Spider(BaseSpider):

    def __init__(self):
        self.host = DEFAULT_HOST
        self._has_proxy = None   # 延迟探测壳的 localProxy 能力
        self.force_proxy = None  # None=自动探测, True/False=ext 强制

    # ---------- 发布页保底 ----------
    def _fetch_publish_host(self):
        """访问发布页，提取最新可用入口地址（优先带端口的 https）"""
        with _PUB_LOCK:
            now = time.time()
            if _PUB_CACHE['host'] and now - _PUB_CACHE['ts'] < _PUB_TTL:
                return _PUB_CACHE['host']
        try:
            req = urllib.request.Request(PUBLISH_URL, headers={
                'User-Agent': UA,
                'Accept-Language': 'zh-CN,zh;q=0.9',
            })
            raw = urllib.request.urlopen(req, timeout=10, context=_CTX).read()
            # 发布页同样是 document.write(decodeURIComponent(...)) 包裹
            html = self._unwrap(raw.decode('utf-8', 'replace'))
            # 提取所有 href 中的 https 链接
            links = re.findall(r'href="(https?://[^"]+)"', html)
            # 优先使用带端口的（如 :8888）
            for link in links:
                if re.search(r':\d+', link):
                    host = link.rstrip('/')
                    with _PUB_LOCK:
                        _PUB_CACHE['host'] = host
                        _PUB_CACHE['ts'] = now
                    return host
            # 兜底：任意 https 链接
            for link in links:
                if link.startswith('https://'):
                    host = link.rstrip('/')
                    with _PUB_LOCK:
                        _PUB_CACHE['host'] = host
                        _PUB_CACHE['ts'] = now
                    return host
        except Exception:
            pass
        # 网络异常时返回过期缓存（如果有）或空
        with _PUB_LOCK:
            return _PUB_CACHE['host']

    # ---------- 基础请求 ----------
    def init(self, ext=''):
        if ext:
            try:
                cfg = json.loads(ext) if isinstance(ext, str) else ext
                if isinstance(cfg, dict):
                    host = (cfg.get('host') or '').strip()
                    if host and host.startswith('http'):
                        self.host = host.rstrip('/')
                    if 'proxy' in cfg:
                        self.force_proxy = bool(int(cfg.get('proxy')))
                elif str(ext).strip().startswith('http'):
                    self.host = str(ext).strip().rstrip('/')
            except Exception:
                if isinstance(ext, str) and ext.strip().startswith('http'):
                    self.host = ext.strip().rstrip('/')
        # 不再主动访问发布页，优先使用默认域名或 ext 传入的域名

    def getName(self):
        return '色虎AV'

    def _fetch_raw(self, path, referer=None, timeout=8, retry=2):
        """轻量通道: 封面等小资源"""
        url = path if path.startswith('http') else self.host + path
        last = None
        for i in range(retry + 1):
            try:
                req = urllib.request.Request(url, headers={
                    'User-Agent': UA,
                    'Referer': referer or (self.host + '/'),
                })
                return urllib.request.urlopen(req, timeout=timeout, context=_CTX).read()
            except Exception as e:
                last = e
                time.sleep(0.5 * (i + 1))
        raise last

    def _get(self, path, timeout=12, retry=3):
        """页面通道: 带重试，首次失败时自动从发布页刷新 host"""
        url = path if path.startswith('http') else self.host + path
        last = None
        refreshed = False
        for i in range(retry):
            try:
                req = urllib.request.Request(url, headers={
                    'User-Agent': UA,
                    'Referer': self.host + '/',
                    'Accept-Language': 'zh-CN,zh;q=0.9',
                })
                raw = urllib.request.urlopen(req, timeout=timeout, context=_CTX).read()
                return self._unwrap(raw.decode('utf-8', 'replace'))
            except Exception as e:
                last = e
                # 首次失败且尚未刷新过 host，尝试从发布页获取新地址
                if not refreshed:
                    refreshed = True
                    new_host = self._fetch_publish_host()
                    if new_host and new_host != self.host:
                        self.host = new_host
                        url = path if path.startswith('http') else self.host + path
                        continue  # 立即用新 host 重试，不 sleep
                time.sleep(0.6 * (i + 1))
        return ''

    @staticmethod
    def _unwrap(text):
        """还原 document.write(decodeURIComponent(\"...\")) 包裹的真实 HTML 并解码实体"""
        m = re.search(r'document\.write\(decodeURIComponent\("(.*?)"\)\)', text, re.S)
        if m:
            text = urllib.parse.unquote(m.group(1))
        return _html.unescape(text)

    # ---------- 封面 ----------
    def _detect_proxy(self):
        """getProxyUrl 可能是 Spider 实例方法(base/drpy2 壳), 也可能注入在 globals 或 builtins"""
        scopes = [self, globals()]
        try:
            import builtins as _b
            scopes.append(_b)
        except Exception:
            pass
        for scope in scopes:
            for name in ('getProxyUrl', 'getProxyUrlLocal', 'localProxyUrl'):
                fn = getattr(scope, name, None)
                if callable(fn):
                    return fn
        return None

    def _cover(self, dat_url):
        """.dat 是 BASE64(WEBP)。优先走壳本地代理, 否则解码为 data:URI 内嵌。"""
        if not dat_url:
            return ''
        if self.force_proxy is False:
            pass
        else:
            if self._has_proxy is None:
                self._has_proxy = self._detect_proxy()
            if self._has_proxy:
                try:
                    purl = self._has_proxy()
                    # 注意: 不能再加第二个 do= 参数, 壳靠 do=py 路由,
                    # 重复键会覆盖导致路由不到本 spider
                    return '%s&action=pic&url=%s' % (
                        purl, urllib.parse.quote_plus(dat_url))
                except Exception:
                    self._has_proxy = False
        with _PIC_LOCK:
            hit = _PIC_CACHE.get(dat_url)
        if hit:
            return hit
        try:
            raw = self._fetch_raw(dat_url)
            mime = self._img_mime(raw)
            if mime == 'b64':
                raw = base64.b64decode(raw.strip())
                mime = self._img_mime(raw)
            uri = 'data:%s;base64,' % (mime or 'image/webp')
            uri += base64.b64encode(raw).decode()
            with _PIC_LOCK:
                if len(_PIC_CACHE) > 600:
                    _PIC_CACHE.clear()
                _PIC_CACHE[dat_url] = uri
            return uri
        except Exception:
            return ''

    # ---------- 列表解析 ----------
    def _parse_list(self, html_text):
        from concurrent.futures import ThreadPoolExecutor
        videos, chunks = [], []

        for chunk in _RE_BLOCK_SPLIT.split(html_text)[1:]:
            vm = re.search(r'href="/view/([0-9a-f]+)"', chunk)
            if not vm:
                continue
            tm = re.search(r'class="rank-title"[^>]*>(.*?)</div>', chunk, re.S)
            pm = re.search(r'data-original="([^"]+)"', chunk)
            dm = re.search(r'secondsToHMS\((\d+)\)', chunk)
            if not tm:
                continue
            chunks.append((vm.group(1), _clean(tm.group(1)),
                           pm.group(1) if pm else '',
                           _hms(dm.group(1)) if dm else ''))

        seen = set()

        def work(item):
            vid, title, pic, dur = item
            return {
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': self._cover(pic),
                'vod_remarks': dur,
            }

        uniq = []
        for it in chunks:
            if it[0] not in seen:
                seen.add(it[0])
                uniq.append(it)
        with ThreadPoolExecutor(max_workers=8) as ex:
            videos = list(ex.map(work, uniq))
        return videos

    # ---------- 首页 ----------
    def homeContent(self, filter=False):
        return {'class': [{'type_id': t, 'type_name': n} for t, n in CATS]}

    def homeVideoContent(self):
        txt = self._get('/')
        vids = self._parse_list(txt)
        # 只取第一个板块(今日推荐)的前几部
        return {'list': vids[:12]} if vids else {'list': []}

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        path = '/category/%s' % tid if pg <= 1 else '/category/%s/%d/' % (tid, pg)
        txt = self._get(path)
        vids = self._parse_list(txt)
        has_more = bool(re.search(r'href="/category/%s/%d/"' % (tid, pg + 1), txt))
        return {
            'list': vids,
            'page': pg,
            'pagecount': pg + 1 if has_more else pg,
            'limit': len(vids),
            'total': pg * 18,
        }

    # ---------- 详情 ----------
    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else str(ids)
        txt = self._get('/view/' + vid)
        tm = re.search(r'class="video-title"[^>]*>(.*?)</div>', txt, re.S)
        title = _clean(tm.group(1)) if tm else vid
        play = ''
        pm = re.search(r'var\s+url\s*=\s*"([^"]+)"', txt)
        if pm:
            play = pm.group(1)
        # 封面取相关推荐第一张作展示图(详情页自身无封面)
        pic = ''
        pm2 = re.search(r'data-original="([^"]+)"', txt)
        if pm2:
            pic = self._cover(pm2.group(1))
        ep = title.replace('$', ' ').replace('#', ' ')[:60] or '播放'
        node = {
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': pic,
            'type_name': '',
            'vod_year': '',
            'vod_area': '',
            'vod_remarks': '',
            'vod_actor': '',
            'vod_director': '',
            'vod_content': title,
            'vod_play_from': '色虎AV',
            'vod_play_url': '%s$%s' % (ep, play),
        }
        # FongMi/OK影视/hipy 系壳统一要求 {'list':[vod]}
        return {'list': [node]}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick=False, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        kw = urllib.parse.quote(str(key))
        path = '/search/%s' % kw if pg <= 1 else '/search/%s/%d/' % (kw, pg)
        txt = self._get(path)
        vids = self._parse_list(txt)
        has_more = bool(re.search(r'href="/search/[^"]*/%d/"' % (pg + 1), txt))
        return {
            'list': vids,
            'page': pg,
            'pagecount': pg + 1 if has_more else pg,
            'limit': len(vids),
            'total': pg * 18,
        }

    # ---------- 播放 ----------
    def playerContent(self, flag, pid, vipFlags=None):
        # pid 即直链 m3u8
        # 实测: m3u8 和每个 .ts 分片都必须带 Referer, 否则 403。
        # 个别壳读取 'headers' 而非 'header', 两个键都给, 保证头能传到分片请求上。
        hd = {
            'User-Agent': UA,
            'Referer': self.host + '/',
            'Origin': self.host,
        }
        return {
            'parse': 0,
            'playUrl': '',
            'url': pid,
            'header': dict(hd),
            'headers': dict(hd),
        }

    def isVideoFormat(self, url):
        return True

    def manualVideoCheck(self):
        return False

    # ---------- 本地代理(可选) ----------
    def localProxy(self, param):
        # 壳约定: 返回 [code, MIME字符串, bytes]
        try:
            if isinstance(param, str):
                # 先 unquote 防止 URL 编码的 & 干扰分割
                param = urllib.parse.unquote(param)
                param = dict(p.split('=', 1) for p in param.split('&') if '=' in p)
            url = urllib.parse.unquote(param.get('url') or param.get('pic') or '')
            if not url:
                return [404, 'text/plain', b'Missing URL']
            raw = self._fetch_raw(url)
            mime = self._img_mime(raw)
            if mime == 'b64':
                # .dat 是 BASE64(WEBP) 文本, 必须解码成真图片
                try:
                    raw = base64.b64decode(raw.strip())
                    mime = self._img_mime(raw)
                except Exception:
                    pass
            if not mime or mime == 'b64':
                return [404, 'text/plain', b'invalid image']
            return [200, mime, raw]
        except Exception:
            return [404, 'text/plain', b'error']

    @staticmethod
    def _img_mime(d):
        if not d or len(d) < 12:
            return ''
        if d[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        if d[:2] == b'\xff\xd8':
            return 'image/jpeg'
        if d[:4] == b'RIFF' and d[8:12] == b'WEBP':
            return 'image/webp'
        if d[:6] in (b'GIF87a', b'GIF89a'):
            return 'image/gif'
        # 修复 BASE64 检测：使用正则匹配合法字符集，避免 +/ 被错误过滤
        s = d[:128].strip()
        if len(s) >= 16:
            line = s.split(b'\n')[0]
            if re.match(br'^[A-Za-z0-9+/]+={0,2}$', line):
                return 'b64'
        return ''


def _clean(s):
    s = re.sub(r'<[^>]+>', '', s or '')
    return re.sub(r'\s+', ' ', s).strip()


if __name__ == '__main__':
    import sys
    sp = Spider()
    sp.init('')
    print(json.dumps(sp.homeVideoContent(), ensure_ascii=False)[:300])
