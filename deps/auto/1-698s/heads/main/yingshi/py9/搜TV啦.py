# coding=utf-8
import re
import json
import requests
from urllib.parse import quote, urlparse, parse_qs
from lxml import etree
from base.spider import Spider


class Spider(Spider):
    # 这些资源站返回的是第三方平台页面，需要解析器，普通播放器无法直接播放
    PARSER_SOURCES = {'QY', 'QQ', 'YK', 'MG', 'BZ', 'RR'}
    # 搜索结果中的来源文案黑名单（对应 PARSER_SOURCES 的资源站）
    PARSER_REMARKS = {'无广告资源', '爱奇艺资源', '腾讯资源', '优酷资源', '芒果资源', '百赞资源', '人人资源'}

    # 该站是搜索引擎，没有真正的分类页。用子类关键词搜索，可得到带直链的结果。
    CATEGORY_KEYWORDS = {
        "1": ["动作片", "喜剧片", "爱情片", "科幻片", "恐怖片", "剧情片"],      # 电影
        "2": ["韩剧", "美剧", "日剧", "泰剧", "港剧"],                          # 电视剧
        "3": ["真人秀", "脱口秀", "演唱会"],                                     # 综艺
        "4": ["日本动画", "动画电影", "宫崎骏", "奥特曼", "火影忍者"],          # 动漫
        "26": ["霸道总裁", "赘婿", "穿越短剧", "甜宠短剧"]                      # 短剧
    }

    def __init__(self):
        self.name = "sotvla"
        self.host = "https://www.sotvla.cc"
        self.header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.host
        }
        self.session = requests.Session()
        self.session.headers.update(self.header)

    def getName(self):
        return self.name

    def init(self, extend=''):
        pass

    def _get(self, url, params=None):
        r = self.session.get(url, params=params, timeout=15)
        r.encoding = 'utf-8'
        return r.text

    def _post(self, url, data=None):
        r = self.session.post(url, data=data, timeout=15)
        r.encoding = 'utf-8'
        return r.text

    def _fix_url(self, url):
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.host + url
        return url

    def _parse_text(self, elem):
        if elem is None:
            return ''
        return ''.join(elem.itertext()).strip()

    def _parse_pic(self, elem):
        pic = ''
        if elem is None:
            return pic
        if elem.tag == 'img':
            pic = elem.get('src') or ''
        else:
            imgs = elem.xpath('.//img')
            if imgs:
                pic = imgs[0].get('src') or ''
        if pic and pic.startswith('data:image'):
            pic = ''
        return self._fix_url(pic)

    def _extract_vod_id(self, href):
        """detail.php?api_id=1&vod_id=88345 -> 1-88345"""
        m = re.search(r'[?&]api_id=(\d+)&vod_id=(\d+)', href)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        return None

    def _split_vod_id(self, vod_id):
        """1-88345 -> (1, 88345)"""
        if '-' in vod_id:
            parts = vod_id.split('-', 1)
            if parts[0].isdigit() and parts[1].isdigit():
                return parts[0], parts[1]
        return None, None

    def _is_parser_remark(self, remark):
        """判断搜索结果来源文案是否来自需要解析器的资源站"""
        if not remark:
            return False
        for bad in self.PARSER_REMARKS:
            if bad in remark:
                return True
        return False

    def _is_parser_source(self, source_name):
        """判断详情页线路代码是否来自需要解析器的资源站"""
        code = source_name.strip().upper()
        # 去掉常见后缀，如 "QY高清" -> "QY"
        code = re.sub(r'[^A-Z0-9]', '', code)
        return code in self.PARSER_SOURCES

    def _parse_search_item(self, article):
        """解析搜索结果条目"""
        a = article.xpath('.//a[@class="sr-title"]')
        if not a:
            a = article.xpath('.//a[contains(@href, "detail.php")]')
        if not a:
            return None
        a = a[0]
        href = a.get('href', '')
        vod_id = self._extract_vod_id(href)
        if not vod_id:
            return None
        vod_name = self._parse_text(a)

        # 封面
        poster = article.xpath('.//a[@class="sr-poster"]//img')
        vod_pic = self._parse_pic(poster[0]) if poster else ''

        # 更新日期 / 播放源
        remark = ''
        src_line = article.xpath('.//div[contains(@class, "sr-source-line")]//span[@class="sr-value"]/text()')
        if src_line:
            remark = src_line[0].strip()
        if not remark:
            date_line = article.xpath('.//div[contains(@class, "sr-meta-grid")]//span[@class="sr-value"]/text()')
            if date_line:
                remark = date_line[-1].strip()

        return {
            "vod_id": vod_id,
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "vod_remarks": remark
        }

    def homeContent(self, filter):
        result = {"class": []}
        classes = [
            {"type_name": "电影", "type_id": "1"},
            {"type_name": "电视剧", "type_id": "2"},
            {"type_name": "综艺", "type_id": "3"},
            {"type_name": "动漫", "type_id": "4"},
            {"type_name": "短剧", "type_id": "26"}
        ]
        result["class"] = classes

        # 搜索引擎站点，筛选条件仅做展示/学习用途
        filters = {}
        year_vals = [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"},
            {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"},
            {"n": "2022", "v": "2022"}
        ]
        for c in classes:
            filters[c['type_id']] = [
                {"key": "year", "name": "年份", "value": year_vals}
            ]
        result["filters"] = filters
        return result

    def homeVideoContent(self):
        """首页热播：调用热榜 API，再反查第一条搜索结果获取 vod_id，并过滤掉只有解析源的资源"""
        videos = []
        try:
            url = f"{self.host}/api/hot_movie.php"
            html = self._get(url)
            data = json.loads(html)
            items = data.get('items', [])
            for item in items:
                try:
                    title = item.get('title', '').strip()
                    pic = self._fix_url(item.get('pic', ''))
                    if not title:
                        continue
                    # 通过搜索反查 vod_id
                    search_url = f"{self.host}/search.php"
                    params = {"q": title}
                    search_html = self._get(search_url, params=params)
                    root = etree.HTML(search_html)
                    arts = root.xpath('//article[@class="search-result-item"]')
                    if not arts:
                        continue
                    for art in arts:
                        video = self._parse_search_item(art)
                        if not video:
                            continue
                        # 过滤掉来源文案明显是解析源的结果
                        if self._is_parser_remark(video.get('vod_remarks', '')):
                            continue
                        # 热榜 API 的封面质量更高，优先使用
                        if pic:
                            video['vod_pic'] = pic
                        videos.append(video)
                        break
                except Exception:
                    pass
        except Exception:
            pass
        return {"list": videos}

    def categoryContent(self, tid, pg, filter, extend):
        """分类：用子类关键词搜索，并过滤掉只有解析源（无法直接播放）的资源"""
        videos = []
        try:
            keywords = self.CATEGORY_KEYWORDS.get(str(tid), [])
            if not keywords:
                return {'list': [], 'page': int(pg), 'pagecount': 0, 'limit': 0, 'total': 0}

            # 按页码轮询子类关键词，让不同页显示不同内容
            idx = (int(pg) - 1) % len(keywords)
            keyword = keywords[idx]

            url = f"{self.host}/search.php"
            params = {"q": keyword, "page": str(pg)}
            html = self._get(url, params=params)
            root = etree.HTML(html)
            arts = root.xpath('//article[@class="search-result-item"]')

            for art in arts:
                try:
                    video = self._parse_search_item(art)
                    if not video:
                        continue
                    # 搜索结果文案是解析源，直接跳过
                    if self._is_parser_remark(video.get('vod_remarks', '')):
                        continue
                    # 进一步校验详情页是否至少有一条可直接播放的线路
                    detail = self.detailContent([video['vod_id']])
                    if not detail.get('list'):
                        continue
                    d = detail['list'][0]
                    if not d.get('vod_play_url'):
                        continue
                    videos.append(video)
                except Exception:
                    pass

            total = 0
            total_elem = root.xpath('//span[@id="search-result-total"]/text()')
            if total_elem:
                total = int(re.sub(r'\D', '', total_elem[0]) or '0')
            limit = max(len(videos), 16)
            pagecount = (total + limit - 1) // limit if total > 0 else 1

            return {
                'list': videos,
                'page': int(pg),
                'pagecount': pagecount,
                'limit': limit,
                'total': total
            }
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 0, 'limit': 0, 'total': 0}

    def detailContent(self, ids):
        try:
            vod_id = ids[0]
            api_id, vid = self._split_vod_id(vod_id)
            if not api_id or not vid:
                return {'list': []}

            detail_url = f"{self.host}/detail.php?api_id={api_id}&vod_id={vid}"
            html = self._get(detail_url)
            root = etree.HTML(html)

            # 标题
            vod_name = ''
            h1 = root.xpath('//div[contains(@class, "detail-info")]//h1/text()')
            if h1:
                vod_name = h1[0].strip()
            if not vod_name:
                title = root.xpath('//title/text()')
                if title:
                    vod_name = title[0].split('·')[0].strip()

            # 封面
            vod_pic = ''
            poster = root.xpath('//div[contains(@class, "detail-poster")]//img')
            if poster:
                vod_pic = self._parse_pic(poster[0])

            # 年代 / 地区 / 演员 / 导演 / 简介
            vod_year = ''
            vod_area = ''
            vod_actor = ''
            vod_director = ''
            vod_content = ''

            info = root.xpath('//div[contains(@class, "detail-info")]')
            if info:
                info_text = self._parse_text(info[0])
                # 年代
                m = re.search(r'年代\s*([0-9]{4})', info_text)
                if m:
                    vod_year = m.group(1)
                # 地区
                m = re.search(r'地区\s*([^\s\n]+)', info_text)
                if m:
                    vod_area = m.group(1).strip()

            # meta-list 中逐行提取
            for div in root.xpath('//div[contains(@class, "detail-info")]//div[@class="meta-list"]/div'):
                txt = self._parse_text(div)
                if txt.startswith('演员'):
                    vod_actor = txt.replace('演员', '').strip().strip('：').strip(':').strip()
                elif txt.startswith('导演'):
                    vod_director = txt.replace('导演', '').strip().strip('：').strip(':').strip()

            blurb = root.xpath('//div[contains(@class, "detail-info")]//p[contains(@class, "blurb")]')
            if blurb:
                vod_content = self._parse_text(blurb[0])

            # 播放源与选集：过滤掉只能走解析器的线路
            vod_play_from = []
            vod_play_url = []

            section = root.xpath('//section[contains(@class, "play-list-section")]')
            if section:
                sec = section[0]
                # 线路按钮
                tabs = sec.xpath('.//button[contains(@class, "play-source-tab")]')
                # 选集面板
                panels = sec.xpath('.//div[contains(@class, "play-ep-panel")]')
                for idx, tab in enumerate(tabs):
                    source_name = self._parse_text(tab)
                    source_name = re.sub(r'\s+', ' ', source_name).strip()
                    if not source_name:
                        source_name = f"线路{idx + 1}"

                    # 跳过爱奇艺/腾讯/优酷/芒果/百赞/人人等解析源
                    if self._is_parser_source(source_name):
                        continue

                    panel = None
                    for p in panels:
                        if p.get('data-src-panel') == str(idx):
                            panel = p
                            break
                    if panel is None and idx < len(panels):
                        panel = panels[idx]
                    if panel is None:
                        continue

                    links = panel.xpath('.//a[contains(@href, "play.php")]')
                    play_list = []
                    for a in links:
                        ep_name = self._parse_text(a)
                        href = a.get('href', '')
                        if not ep_name or not href:
                            continue
                        play_url = self._fix_url(href)
                        play_list.append(f"{ep_name}${play_url}")

                    if play_list:
                        vod_play_from.append(source_name)
                        vod_play_url.append("#".join(play_list))

            if vod_play_from:
                vod_play_from_str = "$$$".join(vod_play_from)
                vod_play_url_str = "$$$".join(vod_play_url)
            else:
                vod_play_from_str = ""
                vod_play_url_str = ""

            detail = {
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_year": vod_year,
                "vod_area": vod_area,
                "vod_actor": vod_actor,
                "vod_director": vod_director,
                "vod_content": vod_content,
                "vod_play_from": vod_play_from_str,
                "vod_play_url": vod_play_url_str
            }
            return {'list': [detail]}
        except Exception:
            return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        """播放：该站为聚合搜索，播放页 iframe 嵌入第三方解析。
        若 iframe 参数里携带 m3u8/mp4 直链则直接播放，否则返回解析地址。"""
        try:
            html = self._get(id)
            real_url = None

            # 1. 优先提取 JS 里的 iframe 地址
            m = re.search(r'var\s+embedAutoOn\s*=\s*"([^"]+)"', html)
            if m:
                real_url = m.group(1).encode('utf-8').decode('unicode_escape')
                real_url = real_url.replace('\\/', '/')
            else:
                # 2. 兼容 iframe 标签
                iframe_match = re.search(r'<iframe[^>]+src\s*=\s*"([^"]+)"', html, re.I)
                if iframe_match:
                    real_url = iframe_match.group(1)

            if real_url:
                real_url = self._fix_url(real_url)
                # 尝试从 iframe 参数中提取直链
                parsed = urlparse(real_url)
                qs = parse_qs(parsed.query)
                direct_url = ''
                for k in ['url', 'v', 'src']:
                    if k in qs:
                        for v in qs[k]:
                            if v and v.strip():
                                direct_url = v.strip()
                # 如果参数里就是直链视频地址，直接播放
                if direct_url and self.isVideoFormat(direct_url):
                    return {"parse": 0, "playUrl": "", "url": direct_url, "header": json.dumps(self.header)}
                return {"parse": 1, "playUrl": "", "url": real_url, "header": json.dumps(self.header)}

            # 兜底：返回播放页地址让播放器自行解析
            return {"parse": 1, "playUrl": "", "url": id, "header": json.dumps(self.header)}
        except Exception:
            return {"parse": 0, "playUrl": "", "url": ""}

    def searchContent(self, key, quick, pg='1'):
        videos = []
        try:
            url = f"{self.host}/search.php"
            params = {"q": key, "page": str(pg)}
            html = self._get(url, params=params)
            root = etree.HTML(html)
            arts = root.xpath('//article[@class="search-result-item"]')
            for art in arts:
                try:
                    video = self._parse_search_item(art)
                    if not video:
                        continue
                    # 根据搜索结果来源文案过滤明显无法直接播放的解析源
                    if self._is_parser_remark(video.get('vod_remarks', '')):
                        continue
                    videos.append(video)
                except Exception:
                    pass

            total = 0
            total_elem = root.xpath('//span[@id="search-result-total"]/text()')
            if total_elem:
                total = int(re.sub(r'\D', '', total_elem[0]) or '0')
            limit = max(len(videos), 16)
            pagecount = (total + limit - 1) // limit if total > 0 else 1

            return {
                'list': videos,
                'page': int(pg),
                'pagecount': pagecount,
                'limit': limit,
                'total': total
            }
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 0, 'limit': 0, 'total': 0}

    def isVideoFormat(self, url):
        return any(url.lower().endswith(fmt) for fmt in ['.m3u8', '.mp4', '.flv', '.ts'])

    def manualVideoCheck(self):
        pass

    def localProxy(self, params):
        return None

    def destroy(self):
        pass
