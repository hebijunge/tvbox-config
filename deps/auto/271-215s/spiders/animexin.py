# -*- coding: utf-8 -*-
import re
import requests
import json
import time
import base64
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from base.spider import Spider

class Spider(Spider):
    def init(self, extend=""):
        self.site = 'https://animexin.dev'
        
        self.site_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.google.com/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        
        self.cache = {}
        self.session = requests.Session()
        
        self.log("ANIMEXIN Spider Started - Optimized Version")

    def getName(self):
        return "🇨🇳 ANIMEXIN"

    def isVideoFormat(self, url):
        return any(ext in url.lower() for ext in ['.m3u8', '.mp4'])

    # ===== 中文标题：静态映射 + 规则（离线零依赖，不调翻译接口）=====
    CN_TITLES = {
        'perfect world': '完美世界', 'wanmei shijie': '完美世界',
        'renegade immortal': '仙逆', 'xian ni': '仙逆',
        'soul land': '斗罗大陆', 'douluo dalu': '斗罗大陆',
        'soul land 2: the peerless tang sect': '斗罗大陆2绝世唐门',
        'battle through the heavens': '斗破苍穹', 'doupo cangqiong': '斗破苍穹',
        'swallowed star': '吞噬星空', 'tunshi xingkong': '吞噬星空',
        'martial universe': '武动乾坤', 'the great ruler': '大主宰', 'great ruler': '大主宰',
        'a will eternal': '一念永恒', 'fanren xiuxian chuan': '凡人修仙传',
        "a record of a mortal's journey to immortality": '凡人修仙传',
        'jade dynasty': '诛仙', 'tales of demons and gods': '妖神记',
        'apotheosis': '百炼成神', 'stellar transformations': '星辰变',
        'martial peak': '武炼巅峰', 'against the gods': '逆天邪神',
        'shrouding the heavens': '遮天', 'i shall seal the heavens': '我欲封天',
        'the daily life of the immortal king': '仙王的日常生活',
        'link click': '时光代理人', "heaven official's blessing": '天官赐福',
        'grandmaster of demonic cultivation': '魔道祖师',
        'scumbag system': '人渣反派自救系统', "the scum villain's self-saving system": '人渣反派自救系统',
        "the king's avatar": '全职高手', "king's avatar": '全职高手',
        'fog hill of five elements': '雾山五行', 'the outcast': '一人之下',
        'hitori no shita': '一人之下', 'rakshasa street': '镇魂街', 'zhen hun jie': '镇魂街',
        'scissor seven': '伍六七', 'the legend of hei': '罗小黑战记',
        'white cat legend': '大理寺日志', 'yao-chinese folktales': '中国奇谭',
        'lord of mysteries': '诡秘之主', 'throne of seal': '神印王座',
        'ze tian ji': '择天记', 'way of choices': '择天记',
        'legend of exorcism': '天宝伏妖录', 'tales of herding gods': '牧神记',
        'spare me, great lord': '大王饶命', 'spiritual realm walker': '灵境行者',
        'ne zha': '哪吒', 'nezha': '哪吒', 'white snake': '白蛇：缘起',
        'new gods: yang jian': '新神榜：杨戬', 'deep sea': '深海',
        "chang'an": '长安三万里', 'changan': '长安三万里',
        'big fish & begonia': '大鱼海棠', 'jiang ziya': '姜子牙',
    }

    @staticmethod
    def _num_cn(n):
        d = {'1': '一', '2': '二', '3': '三', '4': '四', '5': '五',
             '6': '六', '7': '七', '8': '八', '9': '九', '10': '十'}
        if n in d:
            return d[n]
        if n.isdigit():
            v = int(n)
            if 11 <= v <= 19:
                return '十' + d[str(v - 10)]
            if 20 <= v <= 99 and v % 10 == 0:
                return d[str(v // 10)] + '十'
        return n

    def _cn_name(self, name):
        key = name.strip().lower()
        if key in self.CN_TITLES:
            return self.CN_TITLES[key]
        if key.startswith('the '):
            key2 = key[4:]
            if key2 in self.CN_TITLES:
                return self.CN_TITLES[key2]
        return None

    def _cn_title(self, title):
        if not title:
            return title
        t = title.strip()
        if re.search(r'[\u4e00-\u9fff]', t):
            return t
        t = re.sub(r'\s*\[[^\]]*\]', '', t).strip()
        for _ in range(3):
            nt = re.sub(r'\s*(!+|Information)\s*$', '', t, flags=re.I)
            nt = re.sub(r'\s*\b(Indonesia|English)\b[\s,]*\b(Sub|Subs|Subtitle|Subtitles)\b\s*$', '', nt, flags=re.I)
            nt = re.sub(r'\s*\bSub\s*Indo\b\s*$', '', nt, flags=re.I)
            nt = re.sub(r'\s*\bDonghua\b\s*$', '', nt, flags=re.I)
            nt = re.sub(r'\s*\b(Indonesia|English)\b\s*$', '', nt, flags=re.I)
            nt = re.sub(r'[\s,，、]+$', '', nt)
            if nt == t:
                break
            t = nt.strip()
        low = t.lower()
        if low in self.CN_TITLES:
            return self.CN_TITLES[low]
        m = re.match(r'^(.*?)\s+Episode\s+(\d+)\s*$', t, re.I)
        if m:
            cn = self._cn_name(m.group(1))
            return f"{cn}第{m.group(2)}集" if cn else t
        m = re.match(r'^(.*?)\s+Season\s+(\d+)\s+Part\s+(\d+)\s*$', t, re.I)
        if m:
            cn = self._cn_name(m.group(1))
            if cn:
                return f"{cn}第{self._num_cn(m.group(2))}季·第{self._num_cn(m.group(3))}部"
            return t
        m = re.match(r'^(.*?)\s+Season\s+(\d+)\s*(Final\s+Season)?\s*$', t, re.I)
        if m:
            cn = self._cn_name(m.group(1))
            if cn:
                tail = '最终季' if m.group(3) else ''
                return f"{cn}第{self._num_cn(m.group(2))}季{tail}"
            return t
        m = re.match(r'^(.*?)\s+Movie\s*(?::\s*(.+))?$', t, re.I)
        if m:
            cn = self._cn_name(m.group(1))
            if cn:
                return f"{cn}剧场版：{m.group(2)}" if m.group(2) else f"{cn}剧场版"
            return t
        m = re.match(r'^(.*?)\s+Part\s+(\d+)\s*$', t, re.I)
        if m:
            cn = self._cn_name(m.group(1))
            return f"{cn}第{self._num_cn(m.group(2))}部" if cn else t
        m = re.match(r'^(.*?):\s*(.+)$', t)
        if m:
            cn = self._cn_name(m.group(1))
            if cn:
                return f"{cn}：{m.group(2).strip()}"
        cn = self._cn_name(t)
        return cn if cn else t

    def homeContent(self, filter):
        return {
            'class': [
                {'type_name': '📋 动漫列表', 'type_id': 'anime'},
                {'type_name': '🔥 最火的', 'type_id': 'trending'},
                {'type_name': '🆕 最新添加', 'type_id': 'latest'},
                {'type_name': '📈 受欢迎的', 'type_id': 'popular'},
                {'type_name': '⏳ 进行中', 'type_id': 'ongoing'},
                {'type_name': '✅ 完结的', 'type_id': 'completed'},
                {'type_name': '🎬 电影', 'type_id': 'movie'},
                {'type_name': '⚔️ 动作', 'type_id': 'action'},
                {'type_name': '🌿 养成', 'type_id': 'cultivation'},
                {'type_name': '💕 浪漫', 'type_id': 'romance'},
                {'type_name': '✨ 幻想', 'type_id': 'fantasy'},
                {'type_name': '🥋 武术', 'type_id': 'martial-arts'},
                {'type_name': '😂 喜剧', 'type_id': 'comedy'},
                {'type_name': '🎭 戏剧', 'type_id': 'drama'},
                {'type_name': '☯️ 仙侠', 'type_id': 'xianxia'},
            ],
            'filters': {}
        }

    def homeVideoContent(self):
        try:
            url = f"{self.site}/"
            html = self.fetch(url).text
            soup = BeautifulSoup(html, 'html.parser')
            
            items = []
            seen = set()
            
            listupd = soup.find('div', class_='listupd') or soup.find('div', class_='releases')
            
            if listupd:
                for article in listupd.find_all('article', class_='bs'):
                    try:
                        link = article.find('a', href=True)
                        if not link: continue
                        
                        href = link.get('href')
                        if href in seen: continue
                        
                        title = ''
                        tt_div = article.find('div', class_='tt')
                        if tt_div:
                            h2 = tt_div.find('h2')
                            title = h2.text.strip() if h2 else tt_div.text.strip()
                        
                        if not title:
                            title = link.get('title', '')
                        
                        img_tag = article.select_one('div.limit img')
                        img = img_tag.get('src') or img_tag.get('data-src') or '' if img_tag else ''
                        
                        epx = article.find('span', class_='epx')
                        remarks = epx.text.strip() if epx else 'Ongoing'
                        
                        items.append({
                            'vod_id': href,
                            'vod_name': self._cn_title(title),
                            'vod_pic': self._proxy_img(urljoin(self.site, img)),
                            'vod_remarks': remarks
                        })
                        seen.add(href)
                    except:
                        continue
            
            return {'list': items}
        except Exception as e:
            self.log(f"Home error: {e}")
            return {'list': []}

    def _get_page_url(self, tid, pg):
        base_urls = {
            'home': '/', 'anime': '/anime/', 'release-date': '/release-date/', 'genres': '/genres/',
            'trending': '/anime/?order=popular', 'latest': '/anime/?order=latest',
            'popular': '/anime/?order=popular', 'ongoing': '/anime/?status=ongoing',
            'completed': '/anime/?status=completed', 'movie': '/anime/?type=movie',
            'action': '/anime/?genre[]=action', 'cultivation': '/anime/?genre[]=cultivation',
            'romance': '/anime/?genre[]=romance', 'fantasy': '/anime/?genre[]=fantasy',
            'martial-arts': '/anime/?genre[]=martial-arts', 'comedy': '/anime/?genre[]=comedy',
            'drama': '/anime/?genre[]=drama', 'xianxia': '/anime/?genre[]=xianxia',
        }
        base_path = base_urls.get(tid, '/anime/')
        
        if tid in ['home', 'release-date', 'genres']:
            if int(pg) > 1:
                return f"{self.site}{base_path.rstrip('/')}/page/{pg}/"
            return f"{self.site}{base_path}"
        
        if '?' in base_path:
            base_url, query = base_path.split('?', 1)
            if int(pg) > 1:
                return f"{self.site}{base_url}/?page={pg}&{query}"
            return f"{self.site}{base_url}/?{query}"
        
        if int(pg) > 1:
            return f"{self.site}{base_path}?page={pg}"
        return f"{self.site}{base_path}"

    def categoryContent(self, tid, pg, filter, extend):
        try:
            url = self._get_page_url(tid, pg)
            self.log(f"Category '{tid}' page {pg}: {url}")
            
            html = self.fetch(url).text
            soup = BeautifulSoup(html, 'html.parser')
            
            items = []
            seen = set()
            
            listupd = soup.find('div', class_='listupd') or soup.find('div', class_='releases')
            
            if listupd:
                for article in listupd.find_all('article', class_='bs'):
                    try:
                        link = article.find('a', href=True)
                        if not link: continue
                        
                        href = link.get('href')
                        if href in seen: continue
                        
                        tt_div = article.find('div', class_='tt')
                        title = ''
                        if tt_div:
                            h2 = tt_div.find('h2')
                            title = h2.text.strip() if h2 else tt_div.text.strip()
                        
                        if not title:
                            title = link.get('title', '')
                        
                        img_tag = article.select_one('div.limit img')
                        img = img_tag.get('src') or img_tag.get('data-src') or '' if img_tag else ''
                        
                        epx = article.find('span', class_='epx')
                        remarks = epx.text.strip() if epx else 'Ongoing'
                        
                        items.append({
                            'vod_id': href,
                            'vod_name': self._cn_title(title),
                            'vod_pic': self._proxy_img(urljoin(self.site, img)),
                            'vod_remarks': remarks
                        })
                        seen.add(href)
                    except:
                        continue
            
            total_pages = int(pg)
            max_page = 0
            hpage = soup.find('div', class_='hpage')
            if hpage:
                for a in hpage.find_all('a'):
                    if a.text.strip().isdigit():
                        max_page = max(max_page, int(a.text.strip()))
                    href = a.get('href', '')
                    page_match = re.search(r'page[=/](\d+)', href)
                    if page_match:
                        max_page = max(max_page, int(page_match.group(1)))
                if max_page > 0:
                    total_pages = max_page
            
            return {'list': items, 'page': int(pg), 'pagecount': total_pages, 'limit': 30}
        except Exception as e:
            self.log(f"Category error: {e}")
            return {'list': []}

    def detailContent(self, ids):
        try:
            url = ids[0] if ids[0].startswith('http') else urljoin(self.site, ids[0])
            self.log(f"Detail: {url}")
            
            html = self.fetch(url).text
            soup = BeautifulSoup(html, 'html.parser')
            
            title = ''
            title_elem = soup.find('h1', class_='entry-title')
            if title_elem:
                title = title_elem.text.strip()
            
            img = ''
            meta_img = soup.find('meta', property='og:image')
            if meta_img:
                img = meta_img.get('content', '')
            
            desc = ''
            desc_elem = soup.find('div', class_='entry-content')
            if desc_elem:
                desc = desc_elem.get_text(strip=True)[:500]
            
            year = ''
            year_match = re.search(r'20\d{2}', html)
            if year_match:
                year = year_match.group(0)
            
            episodes = []
            eplister = soup.find('div', class_='eplister')
            if eplister:
                for li in eplister.find_all('li'):
                    link = li.find('a', href=True)
                    if not link: continue
                    ep_href = link.get('href')
                    ep_num = None
                    num_div = li.find('div', class_='epl-num')
                    if num_div:
                        nums = re.findall(r'\d+', num_div.text)
                        if nums:
                            ep_num = nums[0]
                    if ep_num:
                        episodes.append(f"{ep_num}${ep_href}")
            
            episodes.sort(key=lambda x: int(x.split('$')[0]))
            play_url = '#'.join(f"第{p.split('$')[0]}集${p.split('$')[1]}" for p in episodes) if episodes else f"第1集${url}"
            
            return {'list': [{'vod_id': url, 'vod_name': self._cn_title(title), 'vod_pic': self._proxy_img(img), 'vod_year': year, 'vod_content': desc, 'vod_remarks': 'Ongoing', 'vod_play_from': 'ANIMEXIN', 'vod_play_url': play_url}]}
        except Exception as e:
            self.log(f"Detail error: {e}")
            return {'list': []}

    def searchContent(self, key, quick, pg="1"):
        try:
            url = f"{self.site}/page/{pg}/?s={quote(key)}" if int(pg) > 1 else f"{self.site}/?s={quote(key)}"
            html = self.fetch(url).text
            soup = BeautifulSoup(html, 'html.parser')
            
            items = []
            listupd = soup.find('div', class_='listupd')
            if listupd:
                for article in listupd.find_all('article', class_='bs'):
                    try:
                        link = article.find('a', href=True)
                        if not link: continue
                        href = link.get('href')
                        tt_div = article.find('div', class_='tt')
                        title = ''
                        if tt_div:
                            h2 = tt_div.find('h2')
                            title = h2.text.strip() if h2 else tt_div.text.strip()
                        if not title:
                            title = link.get('title', '')
                        img_tag = article.select_one('div.limit img')
                        img = img_tag.get('src') or img_tag.get('data-src') or '' if img_tag else ''
                        epx = article.find('span', class_='epx')
                        remarks = epx.text.strip() if epx else ''
                        items.append({'vod_id': href, 'vod_name': self._cn_title(title), 'vod_pic': self._proxy_img(urljoin(self.site, img)), 'vod_remarks': remarks})
                    except:
                        continue
            
            total_pages = int(pg)
            hpage = soup.find('div', class_='hpage')
            if hpage:
                for a in hpage.find_all('a'):
                    if a.text.strip().isdigit():
                        total_pages = max(total_pages, int(a.text.strip()))
            return {'list': items, 'page': int(pg), 'pagecount': total_pages}
        except Exception as e:
            self.log(f"Search error: {e}")
            return {'list': []}

    # ========== PLAYER CERDAS DENGAN PRIORITAS SERVER INDONESIA ==========
    def playerContent(self, flag, id, vipFlags):
        """
        Player cerdas - Memprioritaskan server Indonesia (Subtitle Indonesia)
        Urutan prioritas:
        1. Server Indonesia + Dailymotion
        2. Server Indonesia + Platform lain (Odysee, Ok.ru, Rumble, dll)
        3. Server Dailymotion biasa
        4. Fallback: m3u8 atau iframe langsung
        """
        try:
            self.log(f"Player requested for: {id}")
            
            session = requests.Session()
            session.headers.update(self.site_headers)
            
            # Request halaman episode
            resp = session.get(id, timeout=15)
            resp.raise_for_status()
            html = resp.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # Headers untuk streaming video
            stream_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.dailymotion.com/',
                'Origin': 'https://www.dailymotion.com',
                'Accept': '*/*',
                'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
            }
            
            # ===== 1. CARI SELECTOR MIRROR =====
            mirror_select = soup.find('select', class_='mirror')
            if mirror_select:
                options = mirror_select.find_all('option')
                
                # Kata kunci untuk server Indonesia
                indonesia_keywords = [
                    'indonesia', 'indo', 'sub indo', 'subtitle indonesia',
                    'hardsub indonesia', 'indonesian', 'sub indo donghua'
                ]
                
                # PRIORITAS 1: Server Indonesia + Dailymotion
                for option in options:
                    option_text = option.text.strip().lower()
                    option_value = option.get('value', '')
                    
                    if not option_value:
                        continue
                    
                    is_indonesia = any(keyword in option_text for keyword in indonesia_keywords)
                    is_dailymotion = 'dailymotion' in option_text
                    
                    if is_indonesia and is_dailymotion:
                        self.log(f"✅ [PRIORITY 1] Found Indonesia Dailymotion: {option.text}")
                        
                        try:
                            # Decode base64
                            decoded = base64.b64decode(option_value).decode('utf-8')
                            self.log(f"Decoded HTML length: {len(decoded)} chars")
                            
                            # Cari src dari iframe
                            src_match = re.search(r'src=["\'](.*?)["\']', decoded)
                            if src_match:
                                video_url = src_match.group(1)
                                if video_url.startswith('//'):
                                    video_url = 'https:' + video_url
                                
                                self.log(f"Dailymotion iframe URL: {video_url}")
                                
                                # Extract video ID dari URL Dailymotion
                                video_id_match = re.search(r'video[=/]([a-zA-Z0-9]+)', video_url)
                                if video_id_match:
                                    video_id = video_id_match.group(1)
                                    api_url = f"https://www.dailymotion.com/player/metadata/video/{video_id}"
                                    
                                    try:
                                        api_resp = session.get(api_url, timeout=10, headers=stream_headers)
                                        if api_resp.status_code == 200:
                                            api_data = api_resp.json()
                                            if 'qualities' in api_data:
                                                # Cari kualitas tertinggi yang tersedia
                                                for quality in ['auto', '1080', '720', '480', '360']:
                                                    if quality in api_data['qualities'] and api_data['qualities'][quality]:
                                                        streams = api_data['qualities'][quality]
                                                        if streams and len(streams) > 0:
                                                            m3u8_url = streams[0].get('url')
                                                            if m3u8_url:
                                                                self.log(f"✅ Got m3u8 from Dailymotion API: {quality}")
                                                                return {'parse': 1, 'url': m3u8_url, 'header': stream_headers}
                                    except Exception as e:
                                        self.log(f"Dailymotion API error: {e}")
                                
                                # Jika API gagal, langsung return URL iframe
                                return {'parse': 1, 'url': video_url, 'header': stream_headers}
                        except Exception as e:
                            self.log(f"Decode error: {e}")
                            continue
                
                # PRIORITAS 2: Server Indonesia (non-Dailymotion) - Odysee, Ok.ru, Rumble, dll
                for option in options:
                    option_text = option.text.strip().lower()
                    option_value = option.get('value', '')
                    
                    if not option_value:
                        continue
                    
                    is_indonesia = any(keyword in option_text for keyword in indonesia_keywords)
                    
                    if is_indonesia:
                        self.log(f"✅ [PRIORITY 2] Found Indonesia server: {option.text}")
                        
                        try:
                            decoded = base64.b64decode(option_value).decode('utf-8')
                            
                            # Cari iframe src
                            src_match = re.search(r'src=["\'](.*?)["\']', decoded)
                            if src_match:
                                video_url = src_match.group(1)
                                if video_url.startswith('//'):
                                    video_url = 'https:' + video_url
                                
                                # Sesuaikan referer berdasarkan platform
                                platform_headers = stream_headers.copy()
                                if 'odysee' in video_url:
                                    platform_headers['Referer'] = 'https://odysee.com/'
                                elif 'ok.ru' in video_url:
                                    platform_headers['Referer'] = 'https://ok.ru/'
                                elif 'rumble' in video_url:
                                    platform_headers['Referer'] = 'https://rumble.com/'
                                
                                self.log(f"Alternative platform URL: {video_url}")
                                return {'parse': 1, 'url': video_url, 'header': platform_headers}
                        except Exception as e:
                            self.log(f"Decode error for alternative: {e}")
                            continue
                
                # PRIORITAS 3: Server Dailymotion biasa (tanpa label Indonesia)
                for option in options:
                    option_text = option.text.strip().lower()
                    if 'dailymotion' in option_text:
                        self.log(f"⚠️ [PRIORITY 3] Fallback Dailymotion: {option.text}")
                        try:
                            decoded = base64.b64decode(option.get('value', '')).decode('utf-8')
                            src_match = re.search(r'src=["\'](.*?)["\']', decoded)
                            if src_match:
                                video_url = src_match.group(1)
                                if video_url.startswith('//'):
                                    video_url = 'https:' + video_url
                                return {'parse': 1, 'url': video_url, 'header': stream_headers}
                        except:
                            continue
            
            # ===== 2. FALLBACK: Cari direct video URL dari HTML =====
            # Cari pattern m3u8
            m3u8_patterns = [
                r'(https?://[^\s"\']+\.m3u8[^\s"\']*)',
                r'"(https?://[^"]+\.m3u8[^"]*)"',
                r"(https?://[^']+\.m3u8[^']*)",
            ]
            
            for pattern in m3u8_patterns:
                matches = re.findall(pattern, html, re.I)
                for match in matches:
                    if match and match.startswith('http'):
                        self.log(f"✅ Found direct m3u8: {match[:100]}...")
                        return {'parse': 1, 'url': match, 'header': stream_headers}
            
            # Cari iframe biasa
            iframe_pattern = r'<iframe.*?src=["\'](.*?)["\']'
            matches = re.findall(iframe_pattern, html, re.I | re.S)
            for iframe_url in matches:
                if iframe_url.startswith('//'):
                    self.log(f"Found iframe (protocol-relative): {iframe_url}")
                    return {'parse': 1, 'url': 'https:' + iframe_url, 'header': self.site_headers}
                elif iframe_url.startswith('http'):
                    self.log(f"Found iframe: {iframe_url}")
                    return {'parse': 1, 'url': iframe_url, 'header': self.site_headers}
            
            # ===== 3. LAST RESORT: Return original URL =====
            self.log("⚠️ No video source found, returning original URL")
            return {'parse': 1, 'url': id}
            
        except requests.exceptions.RequestException as e:
            self.log(f"Network error in player: {e}")
            return {'parse': 1, 'url': id}
        except Exception as e:
            self.log(f"Player error: {e}")
            return {'parse': 1, 'url': id}

    def _proxy_img(self, url):
        # 站点图片防盗链(Referer 必须为站内)，封面全部走 localProxy 中转
        if not url:
            return ''
        try:
            b64 = base64.urlsafe_b64encode(url.encode('utf-8')).decode('ascii')
            pb = self.getProxyUrl(local=True)
            sep = '&' if '?' in pb else '?'
            return f"{pb}{sep}m=img&u={b64}"
        except Exception:
            return url

    def localProxy(self, param):
        if isinstance(param, str):
            try:
                param = json.loads(param)
            except Exception:
                param = {}
        if not isinstance(param, dict) or param.get('m') != 'img':
            return [404, 'text/plain', b'']
        u = (param.get('u') or '').strip()
        if not u:
            return [404, 'text/plain', b'']
        try:
            raw = base64.urlsafe_b64decode(u + '=' * (-len(u) % 4)).decode('utf-8')
        except Exception:
            return [404, 'text/plain', b'']
        try:
            headers = dict(self.site_headers)
            headers['Referer'] = self.site + '/'
            r = self.session.get(raw, headers=headers, timeout=15)
            if r.status_code != 200 or not r.content:
                return [404, 'text/plain', b'']
            ct = (r.headers.get('Content-Type', '') or 'image/jpeg').split(';')[0].strip() or 'image/jpeg'
            return [200, ct, r.content]
        except Exception as e:
            self.log(f"img proxy error: {e}")
            return [404, 'text/plain', b'']

    def fetch(self, url, timeout=15, max_retries=3):
        for attempt in range(max_retries):
            try:
                time.sleep(1)
                resp = self.session.get(url, headers=self.site_headers, timeout=timeout)
                resp.raise_for_status()
                return resp
            except requests.exceptions.Timeout:
                self.log(f"Timeout attempt {attempt+1}/{max_retries}: {url}")
                if attempt == max_retries - 1:
                    class Dummy:
                        text = ''
                    return Dummy()
            except Exception as e:
                self.log(f"Fetch attempt {attempt+1} failed: {e}")
                if attempt == max_retries - 1:
                    class Dummy:
                        text = ''
                    return Dummy()
                time.sleep(2)
        class Dummy:
            text = ''
        return Dummy()

    def log(self, msg):
        print(f"[ANIMEXIN] {msg}")

    def destroy(self):
        if self.session:
            self.session.close()