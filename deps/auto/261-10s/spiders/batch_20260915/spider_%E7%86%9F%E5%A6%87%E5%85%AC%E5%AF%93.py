# -*- coding: utf-8 -*-
# 熟妇公寓 四壳通用Python Spider
# 基于探测自动生成，苹果CMS架构
# 生成时间: 2026-09-15 13:24:48

import json
import re
import os
import sys

# 清除代理环境变量
for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
    os.environ.pop(k, None)

# 尝试导入curl_cffi, 失败则用requests
try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

try:
    import requests as req_requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def __init__(self):
            self.extend = {{}}
        def init(self, extend):
            self.extend = extend

# 未成年关键词过滤(铁律13)
MINOR_KEYWORDS = ['萝莉', '幼女', '少女', '童', 'teen', 'loli', 'schoolgirl', '豆蔻', '玉蕊', '碧玉', '稚子']


def is_minor_content(text):
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in MINOR_KEYWORDS)


class Spider(Spider):
    site_name = '熟妇公寓'
    base_url = 'https://mrt.sfgy9.fit'
    site_path = '/cn/home/web'
    ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1'

    categories = [
        {'type_id': '20', 'type_name': '美女写真' },
        {'type_id': '21', 'type_name': '国产精品' },
        {'type_id': '22', 'type_name': '无码专区' },
        {'type_id': '23', 'type_name': '中文字幕' },
        {'type_id': '24', 'type_name': '强奸乱伦' },
        {'type_id': '25', 'type_name': '人妻熟女' },
        {'type_id': '26', 'type_name': '亚洲情色' },
        {'type_id': '27', 'type_name': '制服丝袜' },
        {'type_id': '28', 'type_name': 'SM捆绑' },
        {'type_id': '29', 'type_name': '自淫系列' },
        {'type_id': '30', 'type_name': '三级伦理' },
    ]

    def init(self, extend):
        self.extend = extend
        if isinstance(extend, dict):
            if extend.get('siteUrl'):
                self.base_url = extend['siteUrl'].rstrip('/')
            if extend.get('direct'):
                pass

    def get_url(self, path):
        if path.startswith('http'):
            return path
        if path.startswith('/'):
            return self.base_url + path
        return self.base_url + '/' + path

    def fetch(self, url, timeout=15):
        headers = {{
            'User-Agent': self.ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }}
        if HAS_CFFI:
            try:
                r = cffi_requests.get(url, impersonate='safari17_2_ios', headers=headers, timeout=timeout, verify=False)
                if r.status_code == 200:
                    return r.text
            except Exception:
                pass
        if HAS_REQUESTS:
            try:
                import urllib3
                urllib3.disable_warnings()
                r = req_requests.get(url, headers=headers, timeout=timeout, verify=False)
                if r.status_code == 200:
                    return r.text
            except Exception:
                pass
        try:
            import ssl
            import urllib.request
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
            return resp.read().decode('utf-8', errors='replace')
        except Exception:
            return ''

    def homeContent(self, *args):
        classes = [{{'type_id': c['type_id'], 'type_name': c['type_name']}} for c in self.categories]
        filter_list = {{}}
        for cat in self.categories:
            filter_list[cat['type_id']] = []
        html = self.fetch(self.base_url + self.site_path + '/')
        videos = self.parse_video_list(html)
        return {{'class': classes, 'list': videos, 'filters': filter_list}}

    def categoryContent(self, tid, pg, *args):
        try:
            page = int(pg) if pg else 1
        except (ValueError, TypeError):
            page = 1
        url = f'{{self.base_url}}{{self.site_path}}/index.php/vod/type/id/{{tid}}.html?page={{page}}'
        html = self.fetch(url)
        videos = self.parse_video_list(html)
        pagecount = 1
        total = len(videos)
        limit = 20
        pg_match = re.search(r'共(\d+)页', html)
        if pg_match:
            pagecount = int(pg_match.group(1))
        total_match = re.search(r'共(\d+)条', html)
        if total_match:
            total = int(total_match.group(1))
        return {{'page': page, 'pagecount': pagecount, 'limit': limit, 'total': total, 'list': videos}}

    def detailContent(self, ids, *args):
        if not ids:
            return {{'list': []}}
        if isinstance(ids, str):
            ids = [ids]
        videos = []
        for vod_id in ids:
            play_url = f'{{self.base_url}}{{self.site_path}}/index.php/vod/play/id/{{vod_id}}/sid/1/nid/1.html'
            html = self.fetch(play_url)
            if not html:
                continue
            title = ''
            title_match = re.search(r'<title>([^<]+)</title>', html)
            if title_match:
                title = title_match.group(1).split('-')[0].strip()
            vod_play_url = ''
            pd_match = re.search(r'player_data\s*=\s*(\{{[^{{}}]*\}})', html)
            if pd_match:
                try:
                    pd = json.loads(pd_match.group(1))
                    vod_play_url = pd.get('url', '')
                except Exception:
                    pass
            if not vod_play_url:
                m3u8_match = re.search(r'(https?://[^\s"'<>]+\.m3u8[^\s"'<>]*)', html)
                if m3u8_match:
                    vod_play_url = m3u8_match.group(1)
            pic = ''
            pic_match = re.search(r'<img[^>]+src="([^"]+)"[^>]*alt="{re.escape(title)}"', html) if title else None
            if pic_match:
                pic = pic_match.group(1)
            if not pic:
                pic_match2 = re.search(r'poster=["']([^"']+)["']', html)
                if pic_match2:
                    pic = pic_match2.group(1)
            if is_minor_content(title):
                continue
            videos.append({{
                'vod_id': vod_id,
                'vod_name': title,
                'vod_pic': pic,
                'type_name': '',
                'vod_year': '',
                'vod_area': '',
                'vod_remarks': '',
                'vod_actor': '',
                'vod_director': '',
                'vod_content': '',
                'vod_play_from': '线路1',
                'vod_play_url': f'{{title}}${{vod_play_url}}',
            }})
        return {{'list': videos}}

    def playerContent(self, flag, id, vipFlags, *args):
        return {{
            'parse': 0,
            'playUrl': '',
            'url': id,
            'header': {{'User-Agent': self.ua}},
        }}

    def searchContent(self, key, quick, pg="1", *args):
        try:
            page = int(pg) if pg else 1
        except (ValueError, TypeError):
            page = 1
        url = f'{{self.base_url}}{{self.site_path}}/index.php/vod/search.html?wd={{quote(key)}}&page={{page}}'
        html = self.fetch(url)
        videos = self.parse_video_list(html)
        return {{'list': videos}}

    def searchContentPage(self, key, quick, pg="1", *args):
        return self.searchContent(key, quick, pg)

    def localProxy(self, param):
        return [200, "video/MP2T", "", {{}}]

    def parse_video_list(self, html):
        videos = []
        if not html:
            return videos
        # 通用列表解析: 尝试多种常见模式
        patterns = [
            r'<a[^>]+href=["']([^"']*(?:vod/detail|voddetail|video|movie|play)/(?:id/)?(\w+)[^"']*)["'][^>]*>.*?<img[^>]+(?:src|data-src|data-original)=["']([^"']+)["'][^>]*alt=["']([^"']*)["']',
            r'<a[^>]+href=["']([^"']*(?:detail|vod|video)[^"']*/(\d+)[^"']*)["'][^>]*>.*?<img[^>]+(?:src|data-src|data-original)=["']([^"']+)["'][^>]*>.*?<[^>]*>([^<]{2,50})</[^>]*>',
            r'<li[^>]*>.*?<a[^>]+href=["']([^"']*(?:id|detail)[^"']*/(\w+)[^"']*)["'][^>]*>.*?<img[^>]+(?:src|data-src)=["']([^"']+)["'][^>]*>.*?(?:<h[1-6][^>]*>|<p[^>]*>|<span[^>]*>)([^<]{2,50})</',
        ]
        seen = set()
        for pat in patterns:
            for m in re.finditer(pat, html, re.DOTALL | re.IGNORECASE):
                href = m.group(1)
                vid = m.group(2)
                pic = m.group(3)
                title = m.group(4).strip()
                if not vid or not title or vid in seen:
                    continue
                if is_minor_content(title):
                    continue
                seen.add(vid)
                # 处理相对URL
                if pic.startswith('//'):
                    pic = 'https:' + pic
                elif pic.startswith('/'):
                    pic = self.base_url + pic
                videos.append({{
                    'vod_id': vid,
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_remarks': '',
                }})
            if videos:
                break
        return videos[:50]

    def liveContent(self, *args):
        return {{'list': []}}
