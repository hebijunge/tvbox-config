# -*- coding: utf-8 -*-
"""
射我里面(spider for shewo) 爬虫
适配域名: kdlt8i1n.shewo39.cc 等同系列
专为 PeekPro / 羊壳 / TVBox 等各类壳子进行兼容性优化
"""
import sys
import re
import json
import requests
import urllib3
import time
import random
import html  # 用于解码 HTML 实体字符
from urllib.parse import quote, urljoin, unquote, urlparse

urllib3.disable_warnings()
sys.path.append('..')
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    # 主域名，自动从页面获取或手动更新
    hosts = ['https://kdlt8i1n.shewo39.cc']
    host = hosts[0]
    session = requests.Session()
    _debug = True
    _categories = []

    # 广告过滤黑名单：标题包含以下关键词的条目将被丢弃
    AD_TITLE_FILTER = ['广告', '推广', '合作', 'APP', '下载', '注册', '菠菜', '博彩', '棋牌']
    # 播放线路名称过滤：包含这些关键词的线路按钮将被跳过
    AD_LINE_FILTER = ['广告', '推广', 'APP', '下载', '合作', '菠菜', '博彩']
    # 播放地址域名黑名单（常见广告域名片段）
    AD_DOMAIN_FILTER = ['doubleclick', 'adservice', 'adsystem', 'adnxs', 'openx', 'casalemedia']

    def _log(self, msg):
        if self._debug:
            print(f'[shewo] {msg}')

    def getName(self):
        return '射我里面'

    def isVideoFormat(self, url):
        return url and ('.m3u8' in url or '.mp4' in url or '.ts' in url)

    def manualVideoCheck(self):
        return False

    def destroy(self):
        if hasattr(self, 'session'):
            try:
                self.session.close()
            except:
                pass
            self.session = None

    # ---------- 本地代理（仅做图片代理） ----------
    def localProxy(self, param):
        EMPTY_GIF = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        if not param or not param.startswith('http'):
            return [200, 'image/gif', EMPTY_GIF]
        try:
            r = self.session.get(param, headers={
                'User-Agent': 'Mozilla/5.0',
                'Referer': self.host + '/'
            }, timeout=(10, 15))
            r.raise_for_status()
            content_type = r.headers.get('Content-Type', 'application/octet-stream')
            return [200, content_type, r.content]
        except:
            return [200, 'image/gif', EMPTY_GIF]

    def _get_headers(self, referer=None):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': referer or self.host + '/'
        }

    def _fetch(self, url, referer=None, retries=3):
        for attempt in range(retries):
            try:
                if attempt > 0:
                    time.sleep(random.uniform(0.5, 1.5))
                r = self.session.get(url, headers=self._get_headers(referer), timeout=(10, 20), verify=False)
                r.encoding = 'utf-8'
                if r.status_code == 200:
                    return r.text
                else:
                    self._log(f'请求失败 [{r.status_code}] {url}')
                    return ''
            except Exception as e:
                self._log(f'请求异常 {e}，重试 {attempt+1}')
                continue
        return ''

    # ---------- 核心辅助：强转 HTML 实体 / Unicode 乱码为真实字符 ----------
    def _clean_text(self, text):
        if not text:
            return ''
        # 1. 剥离 HTML 标签
        clean = re.sub(r'<[^>]+>', '', text)
        # 2. 暴力解决 &#21508; 十进制 Unicode 转义
        clean = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), clean)
        # 3. 暴力解决 &#x5404; 十六进制 Unicode 转义
        clean = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), clean)
        # 4. 双重反转义基础实体 (&quot;, &amp;等)
        clean = html.unescape(clean)
        clean = html.unescape(clean)
        # 5. 换行符/制表符/多余连续空格全部压平为单个普通空格
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    # ---------- 分类解析 ----------
    def _parse_categories(self, html_str):
        cats = []
        mato_match = re.search(r'<div[^>]+class="mato"[^>]*>(.*?)</div>', html_str, re.S)
        links_html = mato_match.group(1) if mato_match else html_str
        links = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', links_html, re.S)
        for href, text in links:
            m = re.search(r'/vodtype/(\d+)\.html', href)
            if not m:
                continue
            tid = str(m.group(1))
            name = self._clean_text(text)
            if not name or len(name) > 15:
                continue
            if name in ('首页', '搜索', '全部', '更多', '排行', '留言', '帮助', '返回首页', '发布页', '传送门'):
                continue
            if any(k in name for k in self.AD_TITLE_FILTER):
                continue
            cats.append({
                'type_id': tid,
                'type_name': name,
                'type': 'vod'
            })
        return self._dedup(cats)

    def _dedup(self, cats):
        seen = set()
        unique = []
        for c in cats:
            tid = c['type_id']
            if tid not in seen:
                seen.add(tid)
                unique.append(c)
        return unique

    def init(self, extend=''):
        self._log('正在初始化...')
        if hasattr(self, 'session'):
            try:
                self.session.close()
            except:
                pass
        self.session = requests.Session()
        html_str = self._fetch(self.host + '/')
        if html_str:
            cats = self._parse_categories(html_str)
            if cats:
                self._categories = cats
                self._log(f'分类获取成功: {len(cats)} 个')
                return
        html_str = self._fetch(self.host + '/vodtype/55.html')
        if html_str:
            cats = self._parse_categories(html_str)
            if cats:
                self._categories = cats
                self._log(f'备用页分类获取成功: {len(cats)} 个')
                return
        self._categories = [
            {'type_id': '55', 'type_name': '国产精品', 'type': 'vod'},
            {'type_id': '63', 'type_name': '华语精品', 'type': 'vod'},
            {'type_id': '58', 'type_name': '黑料吃瓜', 'type': 'vod'},
            {'type_id': '60', 'type_name': '欧美大屌', 'type': 'vod'},
            {'type_id': '57', 'type_name': '动漫禁漫', 'type': 'vod'},
            {'type_id': '65', 'type_name': '学生合集', 'type': 'vod'},
            {'type_id': '64', 'type_name': '乱伦精品', 'type': 'vod'},
            {'type_id': '61', 'type_name': '探花约炮', 'type': 'vod'},
            {'type_id': '86', 'type_name': '日本无码', 'type': 'vod'},
            {'type_id': '80', 'type_name': '日本有码', 'type': 'vod'},
            {'type_id': '81', 'type_name': '主播网红', 'type': 'vod'},
            {'type_id': '12', 'type_name': '国产色情', 'type': 'vod'},
            {'type_id': '20', 'type_name': '日本无码', 'type': 'vod'},
            {'type_id': '21', 'type_name': '自拍偷拍', 'type': 'vod'},
            {'type_id': '22', 'type_name': '人妻熟女', 'type': 'vod'},
            {'type_id': '23', 'type_name': '黑人洋屌', 'type': 'vod'},
            {'type_id': '24', 'type_name': '欧美精品', 'type': 'vod'},
            {'type_id': '69', 'type_name': '卡通动漫', 'type': 'vod'},
            {'type_id': '70', 'type_name': '乱伦中出', 'type': 'vod'},
            {'type_id': '71', 'type_name': '传媒原创', 'type': 'vod'},
            {'type_id': '72', 'type_name': '口爆颜射', 'type': 'vod'},
            {'type_id': '25', 'type_name': '岛国女优', 'type': 'vod'},
            {'type_id': '26', 'type_name': '萝莉少女', 'type': 'vod'},
            {'type_id': '88', 'type_name': '重口调教', 'type': 'vod'},
            {'type_id': '56', 'type_name': '国产直播', 'type': 'vod'},
            {'type_id': '73', 'type_name': '岛国群交', 'type': 'vod'},
            {'type_id': '74', 'type_name': '日本有码', 'type': 'vod'},
            {'type_id': '75', 'type_name': '中文字幕', 'type': 'vod'},
            {'type_id': '76', 'type_name': '吃瓜爆料', 'type': 'vod'},
            {'type_id': '77', 'type_name': '角色扮演', 'type': 'vod'},
            {'type_id': '78', 'type_name': '淫娃自慰', 'type': 'vod'},
            {'type_id': '84', 'type_name': '韩国直播', 'type': 'vod'},
            {'type_id': '85', 'type_name': '公开漏出', 'type': 'vod'},
            {'type_id': '89', 'type_name': '户外打野', 'type': 'vod'},
        ]
        self._log('使用硬编码分类')

    # ---------- 视频列表解析（PeekPro/羊壳 终极极客适配版） ----------
    def _parse_video_list(self, html_str):
        items = []
        blocks = re.findall(r'<div[^>]+class="pornkvideos"[^>]*>(.*?)</div>\s*</div>', html_str, re.S)
        if not blocks:
            blocks = re.findall(r'<div[^>]+class="[^"]*pornkvideos[^"]*"[^>]*>(.*?)(?=<div[^>]+class="pornkvideos|$)', html_str, re.S)
        
        for block in blocks:
            link_match = re.search(r'<a[^>]+href="(/voddetail/(\d+)\.html)"', block)
            img_match = re.search(r'<img[^>]+(?:data-src|src)="([^"]*)"', block)
            title_match = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.S)
            if not link_match or not title_match:
                continue
                
            vid = link_match.group(2)
            href = link_match.group(1)
            img = img_match.group(1) if img_match else ''
            
            # 使用超级清洗算法强解标题中的 Unicode 十进制/十六进制编码
            title = self._clean_text(title_match.group(1))

            # ===== 1. 抓取更新日期 (放宽正则逻辑) =====
            time_str = ''
            vlength_match = re.search(r'class="vlength"[^>]*>\s*([\s\S]*?)\s*</div>', block)
            if vlength_match:
                raw_time = self._clean_text(vlength_match.group(1))
                if raw_time:
                    time_str = f"📅 {raw_time}"

            # ===== 2. 抓取观看人数 (放宽正则逻辑) =====
            views = ''
            eyehits_match = re.search(r'class="[^"]*eyehits[^"]*"[^>]*>\s*([\s\S]*?)\s*</div>', block)
            if eyehits_match:
                raw_views = self._clean_text(eyehits_match.group(1))
                if raw_views:
                    v_num = f"{raw_views}次" if raw_views.isdigit() else raw_views
                    views = f"👁 {v_num}"

            # ===== 3. 组装副标题 =====
            remarks_parts = []
            if time_str:
                remarks_parts.append(time_str)
            if views:
                remarks_parts.append(views)

            remarks = ' '.join(remarks_parts) if remarks_parts else ''

            # ----- 过滤广告逻辑 -----
            if any(k in title for k in self.AD_TITLE_FILTER):
                continue
            if img and any(ad_domain in img.lower() for ad_domain in self.AD_DOMAIN_FILTER):
                continue
            if href and not href.startswith('/voddetail/'):
                continue

            if img and not img.startswith('http'):
                img = urljoin(self.host, img)
                
            items.append({
                'vod_id': str(vid),
                'vod_name': str(title),
                'vod_pic': str(img),
                'vod_remarks': str(remarks),
            })
        return items

    # ---------- 首页内容 ----------
    def homeContent(self, filter=False):
        try:
            if not self._categories:
                self.init()
            html_str = self._fetch(self.host + '/')
            items = self._parse_video_list(html_str) if html_str else []
            return {'class': self._categories, 'list': items[:20]}
        except Exception as e:
            self._log(f'homeContent 异常: {e}')
            return {'class': [], 'list': []}

    def homeVideoContent(self):
        html_str = self._fetch(self.host + '/')
        items = self._parse_video_list(html_str) if html_str else []
        return {'list': items[:20]}

    # ---------- 分类列表 ----------
    def categoryContent(self, tid, pg, filter=False, extend=''):
        try:
            page = int(pg) if pg else 1
            if page > 1:
                url = f'{self.host}/vodtype/{tid}-{page}.html'
            else:
                url = f'{self.host}/vodtype/{tid}.html'
            html_str = self._fetch(url)
            items = self._parse_video_list(html_str) if html_str else []
            total_pages = page
            if html_str:
                page_links = re.findall(r'/vodtype/{}[-_](\d+)\.html'.format(tid), html_str)
                if page_links:
                    total_pages = max(int(p) for p in page_links)
                else:
                    total_pages = page + 1
            return {'list': items, 'page': page, 'pagecount': max(total_pages, page)}
        except Exception as e:
            self._log(f'categoryContent 异常: {e}')
            return {'list': [], 'page': int(pg) if pg else 1, 'pagecount': 1}

    # ---------- 播放地址提取 ----------
    def _extract_m3u8(self, html_str):
        urls = []
        if not html_str:
            return urls
        player_match = re.search(r'var\s+player_aaaa\s*=\s*({.*?});', html_str, re.S)
        if player_match:
            try:
                data = json.loads(player_match.group(1))
                raw = data.get('url', '')
                if raw:
                    decoded = unquote(raw).replace('\\/', '/')
                    if decoded.startswith('http'):
                        urls.append(decoded)
            except:
                pass
        direct = re.findall(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\' injection]*)', html_str)
        urls.extend(direct)
        iframe_src = re.findall(r'<iframe[^>]+src="([^"]*)"', html_str)
        for src in iframe_src:
            if '.m3u8' in src:
                urls.append(src)
        json_urls = re.findall(r'''["\']url["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']''', html_str)
        urls.extend(json_urls)

        seen = set()
        clean = []
        for u in urls:
            u = u.replace('\\/', '/')
            if not u.startswith('http'):
                continue
            if any(ad in u.lower() for ad in self.AD_DOMAIN_FILTER):
                self._log(f'过滤广告播放地址: {u}')
                continue
            if u not in seen:
                seen.add(u)
                clean.append(u)
        return clean

    # ---------- 视频详情 ----------
    def detailContent(self, ids):
        try:
            vid = str(ids[0] if isinstance(ids, list) else ids)
            html_str = self._fetch(f'{self.host}/voddetail/{vid}.html')
            if not html_str:
                return {'list': [{'vod_id': str(vid), 'vod_name': '未知影片', 'vod_play_from': '错误', 'vod_play_url': ''}]}
            return self._video_detail(vid, html_str)
        except Exception as e:
            self._log(f'detailContent 异常: {e}')
            return {'list': [{'vod_id': str(vid), 'vod_name': '错误', 'vod_play_from': '错误', 'vod_play_url': ''}]}

    def _video_detail(self, vid, html_str):
        # 标题提取
        title = ''
        m = re.search(r'<h1[^>]*>(.*?)</h1>', html_str, re.S)
        if m:
            title = self._clean_text(m.group(1))
        if not title:
            m = re.search(r'<title>(.*?)</title>', html_str)
            if m:
                title = self._clean_text(m.group(1))

        # 封面
        cover = ''
        m = re.search(r'<img[^>]*data-src="([^"]*)"', html_str)
        if m:
            cover = m.group(1)
        if not cover:
            m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html_str)
            if m:
                cover = m.group(1)
        if cover and not cover.startswith('http'):
            cover = urljoin(self.host, cover)

        # 详情页：抓取播放量 & 时间
        views_detail = ''
        time_detail = ''
        t_m = re.search(r'(?:更新|时间|发布)\s*[:：]?\s*(\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}|\d+\s*(?:分钟|小时|天|周|个月|年)前|\d{2}[-/\.]\d{2})', html_str)
        if t_m:
            time_detail = f'📅 {self._clean_text(t_m.group(1))}'
        v_m = re.search(r'(?:播放|观看|点击|热度)\s*[:：]?\s*([\d\.\w\+万千]+)', html_str)
        if v_m:
            views_detail = f'👁 {self._clean_text(v_m.group(1))}'

        remarks_list = [p for p in [time_detail, views_detail] if p]
        vod_remarks = ' '.join(remarks_list)

        # 播放线路解析
        play_links = re.findall(r'href="(/vodplay/\d+-\d+-\d+\.html)"[^>]*>(.*?)</a>', html_str)
        if not play_links:
            play_links = re.findall(r'href="(/vodplay/\d+[^"]*)"[^>]*>(.*?)</a>', html_str)
        if not play_links:
            play_links = [(f'/vodplay/{vid}-1-1.html', '基础线路')]

        line_map = {}
        cache = {}
        for href, btn_name in play_links:
            btn_name = self._clean_text(btn_name) or '播放线路'
            if any(k in btn_name for k in self.AD_LINE_FILTER):
                self._log(f'过滤广告线路: {btn_name}')
                continue

            play_url = urljoin(self.host, href)

            if href not in cache:
                play_html = self._fetch(play_url)
                m3u8_list = self._extract_m3u8(play_html) if play_html else []
                cache[href] = m3u8_list
                self._log(f'播放页 {href} 提取到 {len(m3u8_list)} 个地址')
            else:
                m3u8_list = cache[href]

            if m3u8_list:
                for i, m3u8 in enumerate(m3u8_list):
                    name = btn_name if i == 0 else f'{btn_name}_{i+1}'
                    line_map.setdefault(btn_name, []).append((name, m3u8))
            else:
                line_map.setdefault(btn_name, []).append((btn_name, play_url))

        if not line_map:
            return {'list': [{
                'vod_id': str(vid),
                'vod_name': str(title),
                'vod_pic': str(cover),
                'vod_remarks': str(vod_remarks),
                'vod_play_from': '错误',
                'vod_play_url': '未找到播放地址'
            }]}

        # 组装 TVBox / PeekPro 标准格式
        from_lines = []
        url_lines = []
        for line_name, episodes in line_map.items():
            from_lines.append(str(line_name))
            ep_str = '#'.join([f'{ep_name}${ep_url}' for ep_name, ep_url in episodes])
            url_lines.append(ep_str)
        vod_play_from = '#'.join(from_lines)
        vod_play_url = '$$$'.join(url_lines)

        return {'list': [{
            'vod_id': str(vid),
            'vod_name': str(title),
            'vod_pic': str(cover),
            'vod_remarks': str(vod_remarks),
            'vod_play_from': str(vod_play_from),
            'vod_play_url': str(vod_play_url)
        }]}

    # ---------- 播放器接口 ----------
    def playerContent(self, flag, id, vipFlags=None):
        if id:
            id = id.replace('\\/', '/')
        if any(ad in id.lower() for ad in self.AD_DOMAIN_FILTER):
            self._log(f'播放器过滤广告地址: {id}')
            return {'parse': 0, 'url': '', 'header': {}}
        if id.startswith('http') and ('.m3u8' in id or '.mp4' in id or '.ts' in id):
            return {'parse': 0, 'url': id, 'header': {'Referer': self.host, 'User-Agent': 'Mozilla/5.0'}}
        else:
            return {'parse': 1, 'url': id, 'header': {'Referer': self.host, 'User-Agent': 'Mozilla/5.0'}}

    # ---------- 搜索功能 ----------
    def searchContent(self, key, quick, pg='1'):
        try:
            page = int(pg) if pg else 1
            url = f'{self.host}/vodsearch/-------------.html?wd={quote(key)}&page={page}'
            html_str = self._fetch(url)
            items = self._parse_video_list(html_str) if html_str else []
            return {'list': items, 'page': page, 'pagecount': page + 1}
        except Exception as e:
            self._log(f'searchContent 异常: {e}')
            return {'list': [], 'page': int(pg) if pg else 1, 'pagecount': 1}
