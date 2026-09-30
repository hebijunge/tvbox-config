#coding=utf-8

import sys
import re
import json
import time
import threading
import urllib.parse
import html as html_module

import requests

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):

    def getName(self):
        return '短剧巴士'

    def init(self, extend=''):
        self.host = 'https://www.duanju84.com'
        self.ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        self.headers = {
            'User-Agent': self.ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.host + '/',
        }
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(self.headers)
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass

        self.cate_manual = [
            ('短剧', '27'),
            ('男频爽剧', 'label_boy'),
            ('女频爽剧', 'label_girl'),
            ('热门推荐', 'label_hot'),
        ]
        self.class_fallback = [
            '重生', '民国', '穿越', '年代', '现代', '言情', '反转', '爽文',
            '女恋', '总裁', '闪婚', '离婚', '都市', '脑洞', '古装', '仙侠',
        ]

        self.from_names = {
            'bfzym3u8': '暴风', 'lzm3u8': '量子', 'ffm3u8': '非凡',
            'snm3u8': '闪电', 'tkm3u8': '天空', 'hnm3u8': '海纳',
            'jsm3u8': '极速', 'dbm3u8': '多宝', 'lem3u8': '乐视',
            'wjm3u8': '无尽', 'ukm3u8': '优酷', 'play': '默认',
        }
        self._filter_cache = None
        self._search_gap = 3.2
        self._search_lock = threading.Lock()
        self._last_search = 0.0
        return self

    def isVideoFormat(self, url):
        if not url:
            return False
        url = url.split('?')[0].lower()
        return any(url.endswith(x) for x in ('.m3u8', '.mp4', '.flv', '.ts', '.mkv', '.avi'))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    def localProxy(self, param):
        return None

    def homeVideoContent(self):
        html = self._get(self.host + '/')
        return {'list': self._parse_list(html)}

    def _get(self, url, retry=2):
        for i in range(retry + 1):
            try:
                r = self.session.get(url, timeout=15, verify=False)
                r.encoding = 'utf-8'
                if r.status_code == 200:
                    return r.text
            except Exception:
                if i == retry:
                    break
        return ''

    def _search_get(self, url, retry=2):
        with self._search_lock:
            for i in range(retry + 1):
                wait = self._search_gap - (time.time() - self._last_search)
                if wait > 0:
                    time.sleep(wait)
                html = self._get(url, retry=1)
                self._last_search = time.time()
                if html and '频繁操作' not in html:
                    return html
                if i == retry:
                    break
            return ''

    def _clean(self, text):
        if not text:
            return ''
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        text = text.replace('\xa0', ' ').replace('&nbsp;', ' ')
        return ' '.join(text.split()).strip()

    def _abs(self, url):
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.host + url
        if url.startswith('http'):
            return url
        return self.host + '/' + url

    @staticmethod
    def _max_page(html, pattern):
        pages = [int(x) for x in re.findall(pattern, html or '')]
        return max(pages) if pages else 1

    @staticmethod
    def _seg_pagecount(html, route, seg_len, page_idx):
        pages = []
        for href in re.findall(r'/%s/([^"\'<>]+?)\.html' % route, html or ''):
            seg = href.split('-')
            if len(seg) == seg_len and seg[page_idx].isdigit():
                pages.append(int(seg[page_idx]))
        return max(pages) if pages else 1

    def _parse_list(self, html):
        videos = []
        if not html:
            return videos
        seen = set()
        # <li><a href="/duanju/109547.html" title="xxx"><span><img data-original="封面"></span>...
        blocks = re.findall(
            r'<a\s+href="(/duanju/(\d+)\.html)"\s+title="([^"]*)"[^>]*>(.*?)</a>',
            html, re.S)
        for href, vid, name, inner in blocks:
            if vid in seen:
                continue
            seen.add(vid)
            name = self._clean(name)
            if not name:
                m = re.search(r'<p class="txt-ov">(.*?)</p>', inner, re.S)
                name = self._clean(m.group(1)) if m else ''
            # 过滤无效项：标题为空，或标题是外链广告
            if not name or name.startswith('http') or len(name) < 2:
                continue
            pic = ''
            m = re.search(r'data-original="([^"]+)"', inner)
            if m:
                pic = self._abs(m.group(1).strip())
            if not pic:
                m = re.search(r'<img[^>]+src="([^"]+)"', inner)
                if m and 'load.png' not in m.group(1):
                    pic = self._abs(m.group(1).strip())
            videos.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': '',
            })
        return videos

    def homeContent(self, filter):
        result = {}
        classes = [{'type_id': tid, 'type_name': name} for name, tid in self.cate_manual]
        result['class'] = classes
        result['filters'] = self._build_filters()
        result['list'] = self.homeVideoContent().get('list', [])
        return result

    def _fetch_classes(self):
        html = self._get(self.host + '/list/27.html')
        names = []
        for enc, title in re.findall(
                r'href="/show/27---([^-"]*)-{8}\.html"\s+title="([^"]*)"', html or ''):
            name = self._clean(title)
            if not name or name == '全部':
                continue
            raw = urllib.parse.unquote_plus(enc).strip()
            if raw and raw not in [v for _, v in names]:
                names.append((name, raw))
        if not names:
            names = [(n, n) for n in self.class_fallback]
        return names

    def _build_filters(self):
        if self._filter_cache is not None:
            return self._filter_cache

        cls_opts = [{'n': '全部', 'v': ''}]
        for name, value in self._fetch_classes():
            cls_opts.append({'n': name, 'v': value})

        by_opts = [
            {'n': '最新', 'v': 'time'},
            {'n': '人气', 'v': 'hits'},
            {'n': '评分', 'v': 'score'},
        ]
        year_opts = [{'n': '全部', 'v': ''}] + \
                    [{'n': y, 'v': y} for y in ['2026', '2025', '2024', '2023', '2022', '2021', '2020']]

        show_filters = [
            {'key': 'class', 'name': '类型', 'value': cls_opts},
            {'key': 'by', 'name': '排序', 'value': by_opts},
            {'key': 'year', 'name': '年份', 'value': year_opts},
        ]
        filters = {'27': show_filters}
        self._filter_cache = filters
        return filters

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if str(pg).isdigit() else 1
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        extend = extend or {}

        if str(tid).startswith('label_'):
            html, pagecount = self._label_page(str(tid)[6:], pg)
        else:
            html, pagecount = self._show_page(str(tid), pg, extend)

        videos = self._parse_list(html)
        return {
            'list': videos,
            'page': pg,
            'pagecount': pagecount,
            'limit': len(videos) if videos else 30,
            'total': (pagecount * len(videos)) if videos else 0,
        }

    def _show_page(self, tid, pg, extend):
        """
        MacCMS show 路由，共 12 段：
        /show/{0:id}-{1:area}-{2:by}-{3:class}-{4:lang}-{5:letter}-{6:}-{7:}-{8:page}-{9:}-{10:}-{11:year}.html
        """
        seg = [''] * 12
        seg[0] = tid
        seg[1] = self._enc(extend.get('area', ''))
        seg[2] = self._enc(extend.get('by', ''))
        seg[3] = self._enc(extend.get('class', ''))
        seg[4] = self._enc(extend.get('lang', ''))
        seg[8] = str(pg)
        seg[11] = self._enc(extend.get('year', ''))
        url = '%s/show/%s.html' % (self.host, '-'.join(seg))
        html = self._get(url)
        pagecount = self._seg_pagecount(html, 'show', 12, 8)
        return html, max(pagecount, pg)

    def _label_page(self, tag, pg):
        if pg <= 1:
            url = '%s/label/%s.html' % (self.host, tag)
        else:
            url = '%s/label/%s/page/%d.html' % (self.host, tag, pg)
        html = self._get(url)
        pagecount = self._max_page(html, r'/label/[^"/]+/page/(\d+)\.html')
        return html, max(pagecount, pg)

    @staticmethod
    def _enc(value):
        if not value:
            return ''
        return urllib.parse.quote_plus(str(value).strip())

    def detailContent(self, ids):
        vid = str(ids[0])
        html = self._get('%s/duanju/%s.html' % (self.host, vid))
        if not html:
            return {'list': []}
        name = ''
        m = re.search(r'<div class="detail-title[^"]*"[^>]*>\s*<h1[^>]*>(.*?)</h1>', html, re.S)
        if m:
            name = self._clean(m.group(1))
        if not name:
            m = re.search(r'<title>(.*?)</title>', html, re.S)
            name = self._clean(m.group(1)).split('-')[0].strip() if m else ''
        pic = ''
        m = re.search(r'<div class="detail-pic[^"]*"[^>]*>\s*<img[^>]+data-original="([^"]+)"', html, re.S)
        if m:
            pic = self._abs(m.group(1))
        if not pic:
            m = re.search(r'data-original="(https?://[^"]+)"', html)
            pic = self._abs(m.group(1)) if m else ''
        actor, vclass, remarks = '', '', ''
        for dt, dd in re.findall(r'<dt>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>', html, re.S):
            key = self._clean(dt).rstrip('：:')
            val = self._clean(dd)
            if key in ('主角', '主演'):
                actor = val
            elif key == '分类':
                vclass = val.replace(' ', ' / ')
            elif key in ('状态', '备注'):
                remarks = val
        content = ''
        m = re.search(r'<div class="content-info[^"]*"[^>]*>(.*?)</div>', html, re.S)
        if m:
            content = self._clean(m.group(1))
        content = re.sub(r'^《%s》\s*' % re.escape(name), '', content) if name else content
        year = ''
        m = re.search(r'((?:19|20)\d{2})年上映', content)
        if m:
            year = m.group(1)
        if not year:
            m = re.search(r'/upload/vod/((?:19|20)\d{2})\d{4}', pic or '')
            if m:
                year = m.group(1)

        play_from, play_url = self._parse_plays(vid, html)

        vod = {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': pic,
            'vod_year': year,
            'vod_area': '中国大陆',
            'vod_lang': '国语',
            'vod_remarks': remarks,
            'vod_actor': actor,
            'vod_director': '',
            'type_name': vclass,
            'vod_content': content or '暂无简介',
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }
        return {'list': [vod]}

    def _parse_plays(self, vid, detail_html):
        play_from, play_url = [], []
        phtml = self._get('%s/djplay/%s-1-1.html' % (self.host, vid))

        if phtml:
            tabs = re.findall(
                r'<section class="tab clearfix" id="play_tab">(.*?)</section>', phtml, re.S)
            names = re.findall(r'<li[^>]*><a[^>]*>(.*?)</a></li>', tabs[0], re.S) if tabs else []
            names = [self._clean(x) for x in names]

            boxes = re.findall(
                r'<section class="tab_box[^"]*" id="play_tab_box">(.*?)</section>', phtml, re.S)
            items = re.findall(
                r'<div class="item[^"]*">\s*<div class="video_list[^"]*">(.*?)</div>',
                boxes[0], re.S) if boxes else []

            alt = ''
            if not names:
                fm = re.search(r'"from"\s*:\s*"([^"]*)"', phtml)
                if fm:
                    code = fm.group(1)
                    alt = self.from_names.get(code, code or '')

            for idx, item in enumerate(items):
                eps = self._parse_eps(item)
                if not eps:
                    continue
                if idx < len(names) and names[idx]:
                    src = names[idx]
                elif idx == 0 and alt:
                    src = alt
                else:
                    src = '线路%d' % (idx + 1)
                play_from.append(src)
                play_url.append('#'.join(eps))

        if not play_from:
            box = re.search(
                r'id="play_tab_box">\s*<div class="video_list[^"]*">(.*?)</div>',
                detail_html or '', re.S)
            eps = self._parse_eps(box.group(1)) if box else []
            if eps:
                play_from.append('默认')
                play_url.append('#'.join(eps))

        if not play_from:
            play_from.append('默认')
            play_url.append('')
        return play_from, play_url

    def _parse_eps(self, chunk):
        eps = []
        for href, title in re.findall(r'<a href="(/djplay/[^"]+)"[^>]*>(.*?)</a>', chunk or '', re.S):
            t = self._clean(title)
            if not t:
                continue
            eps.append('%s$%s' % (t.replace('#', '').replace('$', ''), href))
        return eps

    def playerContent(self, flag, id, vipFlags):
        header = {'User-Agent': self.ua, 'Referer': self.host + '/'}
        url = self._abs(id)
        result = {'parse': 1, 'playUrl': '', 'url': url, 'header': header}

        html = self._get(url)
        real = ''
        if html:
            # 方式1: var url = 'https://...m3u8' (新版)
            m = re.search(r"var\s+url\s*=\s*'([^']+\.m3u8[^']*)'", html)
            if m:
                real = m.group(1)
            # 方式2: var player_aaaa = {...} (旧版)
            if not real:
                m = re.search(r'var\s+player_aaaa\s*=\s*(\{.*?\})\s*</script>', html, re.S)
                if not m:
                    m = re.search(r'player_aaaa\s*=\s*(\{.*?\})\s*</script>', html, re.S)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        real = data.get('url') or ''
                    except Exception:
                        mm = re.search(r'"url"\s*:\s*"(.*?)"', m.group(1))
                        real = mm.group(1).replace('\\/', '/') if mm else ''
            # 方式3: 裸 m3u8 链接
            if not real:
                mm = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', html)
                real = mm.group(1).replace('\\/', '/') if mm else ''

        if real:
            real = real.replace('\\/', '/')
            if real.startswith('//'):
                real = 'https:' + real
            result['parse'] = 0
            result['url'] = real
            result['header'] = header
        return result

    def searchContent(self, key, quick, pg='1'):
        try:
            pg = int(pg) if str(pg).isdigit() else 1
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        seg = [''] * 14
        seg[0] = urllib.parse.quote_plus(key)
        seg[10] = str(pg)
        url = '%s/search/%s.html' % (self.host, '-'.join(seg))
        html = self._search_get(url)
        videos = self._parse_list(html)
        pagecount = self._seg_pagecount(html, 'search', 14, 10)
        return {
            'list': videos,
            'page': pg,
            'pagecount': max(pagecount, pg),
            'limit': len(videos) if videos else 9,
            'total': (pagecount * len(videos)) if videos else 0,
        }
