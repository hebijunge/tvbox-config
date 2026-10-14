# -*- coding: utf-8 -*-
"""
起点有声网 (qdysw.com) TVBox Spider  —— 修复版

修复内容：
1. 处理 cookie 反爬：播放页首次返回混淆 JS，需提取 token 设置 cookie 后刷新
2. 增强音频地址提取：支持 iframe 内拼接式 URL (urlXXXX + '.mp3')
3. 清理章节标题中的特殊字符，防止破坏播放列表格式
4. 获取不到音频地址时返回空地址，避免触发播放器嗅探导致卡屏闪退
"""

import re
import sys
import time
import base64
import requests

sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        pass


class Spider(BaseSpider):

    def getName(self):
        return self.name

    def init(self, extend=''):
        self.name = '起点有声网'
        self.site = 'https://www.qdysw.com'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.site + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self._cache = {}
        self.CACHE_TTL = 900

    # ---------- 通用 ----------

    def _cache_get(self, key):
        item = self._cache.get(key)
        if item and item[0] > time.time():
            return item[1]
        return None

    def _cache_set(self, key, data, ttl=None):
        self._cache[key] = (time.time() + (ttl or self.CACHE_TTL), data)

    def _get(self, url, timeout=15):
        """通用 GET，自动处理 cookie 反爬保护"""
        r = self.session.get(url, timeout=timeout)
        r.encoding = 'utf-8'
        html = r.text

        # 检测并处理 cookie 反爬（reversed 混淆 JS）
        m = re.search(r'var reversed = "([^"]+)"', html)
        if m:
            rev = m.group(1)
            b64 = rev[::-1]
            try:
                code = base64.b64decode(b64).decode('utf-8')
                tm = re.search(r"var token = '([^']+)'", code)
                if tm:
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc
                    self.session.cookies.set('pt_guid', tm.group(1), domain=domain)
                    r = self.session.get(url, timeout=timeout)
                    r.encoding = 'utf-8'
                    html = r.text
            except Exception:
                pass

        return html

    def _clean_title(self, title):
        if not title:
            return title
        return re.sub(r'有声小说$', '', title).strip()

    def _clean_chapter_title(self, title):
        """清理章节标题，移除会破坏 TVBox 播放列表格式的特殊字符"""
        if not title:
            return '未知章节'
        title = re.sub(r'[|$#@]', '', title)
        title = re.sub(r'<[^>]+>', '', title)
        title = re.sub(r'\s+', ' ', title)
        return title.strip()

    # ---------- 首页 ----------

    def homeContent(self, filter):
        class_list = [
            {'type_id': 'xhqh', 'type_name': '玄幻奇幻'},
            {'type_id': 'ysyz', 'type_name': '影视原著'},
            {'type_id': 'wxxx', 'type_name': '武侠仙侠'},
            {'type_id': 'cyjk', 'type_name': '穿越架空'},
            {'type_id': 'xytl', 'type_name': '悬疑推理'},
            {'type_id': 'khjj', 'type_name': '科幻竞技'},
            {'type_id': 'lsjs', 'type_name': '历史军事'},
            {'type_id': 'xdyq', 'type_name': '现代言情'},
            {'type_id': 'qcxy', 'type_name': '青春校园'},
            {'type_id': 'hxyq', 'type_name': '幻想言情'},
            {'type_id': 'gdyq', 'type_name': '古代言情'},
            {'type_id': 'wxmz', 'type_name': '文学名著'},
            {'type_id': 'ertong', 'type_name': '儿童频道'},
            {'type_id': 'xsqy', 'type_name': '相声曲艺'},
        ]
        filters = {}
        for c in class_list:
            filters[c['type_id']] = [{
                'key': 'sort',
                'name': '排序',
                'value': [
                    {'n': '最近更新', 'v': 'lastupdate'},
                    {'n': '最新发布', 'v': 'postdate'},
                    {'n': '人气最高', 'v': 'allvisit'},
                    {'n': '时长最长', 'v': 'duration'},
                ]
            }]
        return {'class': class_list, 'filters': filters}

    # ---------- 分类 ----------

    def categoryContent(self, cid, page, filter, ext):
        try:
            pg = int(str(page).strip() or 1)
        except (TypeError, ValueError):
            pg = 1
        sort = 'lastupdate'
        if isinstance(ext, dict) and ext.get('sort'):
            sort = ext['sort']

        if pg == 1:
            url = '%s/book/%s/%s.html' % (self.site, cid, sort)
        else:
            url = '%s/book/%s/%s/%d.html' % (self.site, cid, sort, pg)

        try:
            html = self._get(url)
        except Exception as e:
            print('categoryContent error:', e)
            return {'list': [], 'page': pg, 'pagecount': 1, 'total': 0}

        videos = []
        items = re.findall(
            r'<a[^>]*href="(/book/\d+\.html)"[^>]*title="([^"]*)"[^>]*>.*?'
            r'data-original="([^"]*)"',
            html, re.DOTALL
        )
        seen = set()
        for link, title, pic in items:
            m = re.search(r'/book/(\d+)\.html', link)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            videos.append({
                'vod_id': m.group(1),
                'vod_name': self._clean_title(title.strip()),
                'vod_pic': self.site + pic if pic.startswith('/') else pic,
                'vod_remarks': '',
            })

        pagecount = 1
        pages = re.findall(r'/book/%s/%s/(\d+)\.html' % (cid, sort), html)
        if pages:
            pagecount = max(int(p) for p in pages)

        return {
            'list': videos,
            'page': pg,
            'pagecount': pagecount,
            'total': pagecount * 20,
            'parse': 0,
            'jx': 0,
        }

    # ---------- 目录页：抓完整章节 ----------

    def _get_full_chapters(self, book_id, dir_url):
        """循环翻页 /bookdir/xxx/xxx.html?page=N&sort=asc 抓全部章节"""
        cache_key = 'chapters:%s' % book_id
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        chapters = []
        seen_ids = set()
        page = 1
        max_page = 1

        while page <= max_page:
            if '?' in dir_url:
                url = '%s&page=%d&sort=asc' % (dir_url, page)
            else:
                url = '%s?page=%d&sort=asc' % (dir_url, page)
            try:
                html = self._get(url)
            except Exception as e:
                print('dir page %d error: %s' % (page, e))
                break

            if page == 1:
                nums = re.findall(r'[?&]page=(\d+)', html)
                if nums:
                    max_page = max(int(n) for n in nums)

            items = re.findall(
                r"<a[^>]*href=['\"]/tingshu/%s/(\d+)\.html['\"][^>]*>([^<]+)</a>" % book_id,
                html
            )
            if not items:
                items = re.findall(
                    r"href=['\"]/tingshu/%s/(\d+)\.html['\"][^>]*>([^<]+)<" % book_id,
                    html
                )
            if not items:
                break

            new_count = 0
            for cid, title in items:
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                chapters.append({
                    'id': cid,
                    'title': self._clean_chapter_title(title),
                })
                new_count += 1

            if new_count == 0:
                break
            page += 1

        chapters.sort(key=lambda x: int(x['id']))
        self._cache_set(cache_key, chapters)
        return chapters

    # ---------- 详情 ----------

    def detailContent(self, did):
        vid = str(did[0])
        url = '%s/book/%s.html' % (self.site, vid)
        try:
            html = self._get(url)
        except Exception as e:
            print('detailContent error:', e)
            return {'list': [], 'msg': str(e)[:80]}

        name_m = re.search(r'<h1 class="book-title"[^>]*>\s*([^<]+)', html)
        name = self._clean_title(name_m.group(1).strip()) if name_m else '专辑%s' % vid

        pic_m = re.search(r'data-original="([^"]*)"[^>]*alt="[^"]*有声小说"', html)
        pic = pic_m.group(1) if pic_m else ''
        if pic and pic.startswith('/'):
            pic = self.site + pic

        desc_m = re.search(r'<div class="book-des">\s*(.*?)\s*</div>', html, re.DOTALL)
        content = ''
        if desc_m:
            content = re.sub(r'<[^>]+>', '', desc_m.group(1)).replace('&nbsp;', ' ').strip()

        actor_list = re.findall(r'<a[^>]*href="/boyin/\d+\.html"[^>]*>([^<]+)</a>', html)
        actor = '、'.join(actor_list[:5]) if actor_list else ''

        dir_m = re.search(r'href="(/bookdir/[^"]+\.html)"', html)
        chapters = []
        if dir_m:
            dir_url = self.site + dir_m.group(1)
            chapters = self._get_full_chapters(vid, dir_url)

        if not chapters:
            items = re.findall(
                r"<a[^>]*href=['\"]/tingshu/%s/(\d+)\.html['\"][^>]*>([^<]+)</a>" % vid,
                html
            )
            for cid, title in items:
                chapters.append({'id': cid, 'title': self._clean_chapter_title(title)})
            chapters.sort(key=lambda x: int(x['id']))

        play_urls = ['%s$%s|%s' % (c['title'], vid, c['id']) for c in chapters]

        if len(play_urls) > 5000:
            print('Warning: book %s has %d chapters, may cause performance issues' % (vid, len(play_urls)))

        info = {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': pic,
            'vod_actor': actor,
            'vod_content': content or '暂无简介',
            'vod_play_from': '起点有声网',
            'vod_play_url': '#'.join(play_urls),
        }
        return {'list': [info], 'parse': 0, 'jx': 0}

    # ---------- 搜索 ----------

    def searchContent(self, key, quick, page='1'):
        videos = []
        try:
            r = self.session.post(
                self.site + '/search.html',
                data={'searchword': key},
                timeout=15
            )
            r.encoding = 'utf-8'
            html = r.text
        except Exception as e:
            print('searchContent error:', e)
            return {'list': [], 'parse': 0, 'jx': 0}

        items = re.findall(
            r'<a[^>]*href="(/book/\d+\.html)"[^>]*title="([^"]*)"[^>]*>.*?'
            r'data-original="([^"]*)"',
            html, re.DOTALL
        )
        seen = set()
        for link, title, pic in items:
            m = re.search(r'/book/(\d+)\.html', link)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            videos.append({
                'vod_id': m.group(1),
                'vod_name': self._clean_title(title.strip()),
                'vod_pic': self.site + pic if pic.startswith('/') else pic,
                'vod_remarks': '',
            })
        return {'list': videos[:50], 'parse': 0, 'jx': 0}

    # ---------- 播放 ----------

    def _extract_iframe_audio(self, page_url):
        """从 iframe 播放器中提取音频地址"""
        # _get 已自动处理 cookie 反爬，直接使用即可
        html = self._get(page_url)

        iframe_m = re.search(r'<iframe[^>]*src="([^"]+)"', html)
        if not iframe_m:
            return None

        iframe_src = iframe_m.group(1)
        if iframe_src.startswith('/'):
            iframe_src = self.site + iframe_src

        iframe_html = self._get(iframe_src)

        # 模式1: 优先从 jplayer setMedia 中直接提取完整 mp3 URL
        # 站点有时会直接嵌入完整 URL，有时用变量拼接
        mp3_direct = re.search(r"mp3:'(https?://[^']+)'", iframe_html)
        if mp3_direct:
            return mp3_direct.group(1)

        # 模式2: 提取拼接式变量
        url_vars = re.findall(r"(url\d+)\s*=\s*'([^']+)'", iframe_html)
        murl_vars = re.findall(r"(murl\d+)\s*=\s*'([^']+)'", iframe_html)
        if url_vars:
            # 反向遍历，优先取以 http 开头的值
            for var_name, var_val in reversed(url_vars):
                if var_val.startswith('http'):
                    base_url = var_val
                    break
            else:
                base_url = url_vars[-1][1]
            suffix = '.mp3'
            if murl_vars:
                suffix = murl_vars[-1][1]
            if base_url.endswith(suffix):
                return base_url
            return base_url + suffix

        # 兜底：直接音频地址
        patterns = [
            r'(https?://[^\s"\'<>]+\.(?:mp3|m4a|aac|ogg|wav)(?:\?[^\s"\'<>]*)?)',
            r'var\s+(?:url|playUrl|audioUrl|musicUrl|src|videoUrl)\s*=\s*["\'](https?://[^"\']+)["\']',
            r'"url"\s*:\s*"(https?://[^"]+\.(?:mp3|m4a|aac|ogg|wav)[^"]*)"',
            r'"src"\s*:\s*"(https?://[^"]+\.(?:mp3|m4a|aac|ogg|wav)[^"]*)"',
            r'<audio[^>]*src=["\'](https?://[^"\']+)["\']',
            r'<source[^>]*src=["\'](https?://[^"\']+)["\']',
            r'data-url=["\'](https?://[^"\']+)["\']',
            r'data-src=["\'](https?://[^"\']+)["\']',
            r'file\s*:\s*["\'](https?://[^"\']+)["\']',
        ]

        for pat in patterns:
            m = re.search(pat, iframe_html)
            if m:
                return m.group(1)

        return None

    def playerContent(self, flag, pid, vipFlags):
        parts = str(pid).split('|')
        if len(parts) != 2:
            print('Invalid pid format:', pid)
            return {'url': '', 'parse': 0, 'jx': 0, 'header': self.headers}

        book_id, chapter_id = parts
        page_url = '%s/tingshu/%s/%s.html' % (self.site, book_id, chapter_id)

        try:
            play_url = self._extract_iframe_audio(page_url)
        except Exception as e:
            print('playerContent error:', e)
            play_url = None

        if play_url:
            return {
                'url': play_url,
                'parse': 0,
                'jx': 0,
                'header': {
                    'User-Agent': self.headers['User-Agent'],
                    'Referer': page_url,
                },
            }

        # 获取失败时返回空地址，绝不让播放器嗅探 HTML 页面
        print('No play url found for:', page_url)
        return {'url': '', 'parse': 0, 'jx': 0, 'header': self.headers}


if __name__ == '__main__':
    s = Spider()
    s.init()
    detail = s.detailContent(['13382'])
    d = detail['list'][0]
    eps = d['vod_play_url'].split('#') if d['vod_play_url'] else []
    print('专辑:', d['vod_name'])
    print('章节数:', len(eps))
    print('第1集:', eps[0][:60] if eps else '无')
    print('最后1集:', eps[-1][:60] if eps else '无')
    if eps:
        player = s.playerContent('起点有声网', eps[0].split('$')[-1], '')
        print('播放地址:', player.get('url', '无')[:80])
