# coding=utf-8
import re
import sys
import urllib.parse
import requests
from pyquery import PyQuery as pq

sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    def __init__(self):
        self.name = 'sae8视频'
        self.author = '飞鱼'
        # 主页/发布页地址
        self.host = 'https://yogamen.net'
        
        self.session = requests.Session()
        # 【全局加固】：在此处直接把 Referer 和 Origin 写入全局 headers，确保所有请求都自带防盗链标识
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 15; 2407FRK8EC Build/AP3A.240617.008; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.127 Mobile Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            'Referer': f"{self.host}/",
            'Origin': self.host
        }
        
        # 一级及二级分类映射
        self.class_map = {
            '最新': 'news',
            '自拍黑料吃瓜': 'category/自拍黑料吃瓜',
            'AV精选': 'category/AV精选',
            '中文字幕AI消码': 'category/中文字幕AI消码',
            '稀缺资源': 'category/稀缺资源',
            '全部分类': 'discover'
        }

    def getName(self):
        return self.name

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        return any(ext in (url or '') for ext in ['.m3u8', '.mp4', '.ts', '.flv'])

    def manualVideoCheck(self):
        return False

    def _abs_url(self, path):
        if not path:
            return ''
        if path.startswith('http'):
            return path
        return f"{self.host.rstrip('/')}/{path.lstrip('/')}"

    # 通用 HTTP 请求封装
    def _fetch(self, url, headers=None, timeout=15):
        req_headers = self.headers.copy()
        if headers:
            req_headers.update(headers)
        try:
            resp = self.session.get(url, headers=req_headers, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                resp.encoding = 'utf-8'
                if resp.url:
                    parsed_host = re.match(r'^(https?://[^/]+)', resp.url)
                    if parsed_host:
                        self.host = parsed_host.group(1)
                        # 动态更新全局 headers 里的 host 映射
                        self.headers['Referer'] = f"{self.host}/"
                        self.headers['Origin'] = self.host
            return resp
        except Exception:
            return type('obj', (object,), {'text': '', 'status_code': 500})()

    # 解析卡片列表数据
    def _parse_video_items(self, html_text):
        vlist = []
        if not html_text:
            return vlist

        doc = pq(html_text)
        cards = doc('.videos-lists .movie-card, .videos-lists .uk-card, div.movie-card')
        
        is_category_card = False
        if not cards:
            cards = doc('.videos-box a, .category-box a, .uk-grid a.uk-card')
            is_category_card = True

        for item in cards.items():
            try:
                a_tag = item if item.is_('a') else item('a')
                href = a_tag.attr('href') or ''
                if not href:
                    continue
                
                full_href = self._abs_url(href)
                img = item('img')
                pic = img.attr('src') or img.attr('data-src') or ''
                pic = self._abs_url(pic) if pic else f"{self.host}/img/uikit-logo.svg"

                title = img.attr('alt') or item('.uk-card-title').text().strip() or a_tag.text().strip()
                if not title:
                    title = "未知标题"

                remarks = item('.uk-hottype').text().strip() or item('.badge').text().strip()
                if is_category_card and not remarks:
                    remarks = "分类"

                vlist.append({
                    'vod_id': full_href,
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_remarks': remarks
                })
            except Exception:
                continue

        seen = set()
        unique_list = []
        for v in vlist:
            if v['vod_id'] not in seen:
                seen.add(v['vod_id'])
                unique_list.append(v)

        return unique_list

    def _parse_pagecount(self, doc):
        try:
            nums = []
            for a in doc('.uk-pagination a, .pagination a').items():
                href = a.attr('href') or ''
                m = re.search(r'page=(\d+)', href)
                if m:
                    nums.append(int(m.group(1)))
            return max(nums) if nums else 1
        except Exception:
            return 1

    def homeContent(self, filter):
        result = {'class': [{'type_name': k, 'type_id': v} for k, v in self.class_map.items()]}
        try:
            resp = self._fetch(self.host)
            result['list'] = self._parse_video_items(resp.text)
        except Exception:
            result['list'] = []
        return result

    def homeVideoContent(self):
        return []

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        try:
            if tid.startswith('http'):
                url = f"{tid}?page={pg}" if '?' not in tid else f"{tid}&page={pg}"
            else:
                clean_tid = tid.lstrip('/')
                url = f"{self.host}/cn/{clean_tid}?page={pg}"
            
            if extend and 'by' in extend:
                url += f"&by={extend['by']}"

            resp = self._fetch(url)
            doc = pq(resp.text)
            vlist = self._parse_video_items(resp.text)

            return {
                'list': vlist,
                'page': pg,
                'pagecount': self._parse_pagecount(doc),
                'limit': len(vlist),
                'total': 9999
            }
        except Exception:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0}

    def searchContent(self, key, quick, pg=1):
        pg = int(pg or 1)
        if not key:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0}

        try:
            encoded_key = urllib.parse.quote(key.strip())
            search_url = f"{self.host}/search?q={encoded_key}&page={pg}"
            
            resp = self._fetch(search_url)
            doc = pq(resp.text)
            vlist = self._parse_video_items(resp.text)

            return {
                'list': vlist,
                'page': pg,
                'pagecount': self._parse_pagecount(doc),
                'limit': len(vlist),
                'total': 9999
            }
        except Exception:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0}

    # 4. 详情页解析
    def detailContent(self, ids):
        if not ids or not ids[0]:
            return {'list': []}

        vod_id = ids[0].strip()
        detail_url = self._abs_url(vod_id)

        try:
            resp = self._fetch(detail_url)
            html = resp.text
        except Exception:
            html = ''

        doc = pq(html)
        title = doc('title').text().strip() or doc('h1').text().strip() or "未知视频"

        img_elem = doc('.uk-cover, .movie-poster img, .uk-card-media-top img, .detail-pic img')
        pic = img_elem.attr('src') or img_elem.attr('data-src') or ''
        pic = self._abs_url(pic) if pic else ''

        content = doc('.uk-description, .movie-desc, .content, p.uk-text-meta').text().strip()
        if not content:
            content = detail_url

        play_url = detail_url  

        try:
            m3u8_match = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
            if m3u8_match:
                play_url = m3u8_match.group(1)
            else:
                fv_match = re.search(r'var\s+flashvars\s*=\s*\{([^}]+)\};', html)
                if fv_match:
                    fv_str = fv_match.group(1)
                    rnd_m = re.search(r"rnd\s*:\s*['\"]([^'\"]+)['\"]", fv_str)
                    rnd_val = rnd_m.group(1) if rnd_m else ""

                    url_m = re.search(r"_url\s*:\s*['\"]([^'\"]+)['\"]", fv_str)
                    url_path = url_m.group(1) if url_m else ""

                    if url_path:
                        play_url = f"{self.host}/function/0/{url_path.strip('/')}/?rnd={rnd_val}"
                else:
                    general_match = re.search(r'["\'](https?://[^"\']+\.(mp4|flv|m3u8)[^"\']*)["\']', html)
                    if general_match:
                        play_url = general_match.group(1)
        except Exception:
            pass

        if '|' in play_url:
            play_url = play_url.split('|')[0]

        return {'list': [{
            'vod_id': vod_id,
            'vod_name': title,
            'vod_pic': pic,
            'vod_play_from': 'SAE8视频',
            'vod_play_url': f'在线播放${play_url}',
            'vod_content': content
        }]}

    # 5. 播放配置输出：确保标准头随 header 字典完美下发
    def playerContent(self, flag, id, vipFlags):
        is_direct = any(ext in id for ext in ['.m3u8', '.mp4', '.ts', '.flv'])
        
        headers = {
            'User-Agent': self.headers['User-Agent'],
            'Referer': self.headers['Referer'],
            'Origin': self.headers['Origin']
        }
        
        return {
            'parse': 0 if is_direct else 1,  # 直链不走嗅探，网页或接口走内置嗅探
            'url': id,
            'header': headers
        }

    def localProxy(self, param):
        return [404, 'text/plain', '']
