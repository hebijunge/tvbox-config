# coding: utf-8
import sys
import html
import re
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from base.spider import Spider

sys.path.append('..')

class Spider(Spider):
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
    }
    
    site_url = 'https://jiuse.io'

    def getName(self):
        return "九色"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def homeContent(self, filter):
        result = {}
        cate_names = "最近更新&高清视频&最近加精&当前最热&最近得分&非付费&91原创&10分钟以上&20分钟以上&本月讨论&本月收藏&收藏最多&本月最热&上月最热".split("&")
        cate_ids = "latest&hd&recent-favorite&hot-list&recent-rating&nonpaid&ori&long-list&longer-list&month-discuss&top-favorite&most-favorite&top-list&top-last".split("&")
        
        classes = []
        for name, cid in zip(cate_names, cate_ids):
            classes.append({
                'type_name': name,
                'type_id': cid
            })
            
        result['class'] = classes
        
        try:
            url = f"{self.site_url}/video"
            rsp = self.fetch(url, headers=self.headers)
            soup = BeautifulSoup(rsp.text, 'html.parser')
            
            videos = []
            container = soup.select_one('#rd5')
            if container:
                articles = container.select('article')
                for article in articles:
                    vod = self._parse_article(article)
                    if vod:
                        videos.append(vod)
            result['list'] = videos
        except Exception as e:
            result['list'] = []
            
        return result

    def homeVideoContent(self):
        return self.homeContent(False)

    def categoryContent(self, tid, pg, filter, extend):
        result = {}
        if not pg or pg == '0':
            pg = '1'
            
        url = f"{self.site_url}/video/category/{tid}/{pg}"
        try:
            rsp = self.fetch(url, headers=self.headers)
            soup = BeautifulSoup(rsp.text, 'html.parser')
            
            videos = []
            container = soup.select_one('#rd5')
            if container:
                articles = container.select('article')
                for article in articles:
                    vod = self._parse_article(article)
                    if vod:
                        videos.append(vod)
                        
            result['list'] = videos
            result['page'] = int(pg)
            result['pagecount'] = int(pg) + 1
            result['limit'] = 20
            result['total'] = 999
        except Exception as e:
            result['list'] = []

        return result

    def detailContent(self, array):
        vod_id = array[0]
        page_url = vod_id if vod_id.startswith('http') else f"{self.site_url}{vod_id}"
        
        vod = {
            'vod_id': vod_id,
            'vod_name': '视频详情',
            'vod_pic': '',
            'vod_remarks': '',
            'vod_content': '',
            'vod_play_from': '九色直连',
            'vod_play_url': f'高清原画${page_url}' # 默认兜底，如果解析成功会替换
        }
        
        try:
            rsp = self.fetch(page_url, headers=self.headers)
            html_text = rsp.text
            soup = BeautifulSoup(html_text, 'html.parser')
            
            # 1. 基础 Meta 信息解析
            meta_title = soup.select_one('meta[property="og:title"]')
            if meta_title and meta_title.get('content'):
                vod['vod_name'] = meta_title['content'].strip()
            else:
                h1_node = soup.select_one('h1') or soup.select_one('.video-title')
                if h1_node:
                    vod['vod_name'] = h1_node.get_text(strip=True)

            meta_img = soup.select_one('meta[property="og:image"]')
            if meta_img and meta_img.get('content'):
                vod['vod_pic'] = meta_img['content']

            meta_desc = soup.select_one('meta[property="og:description"]')
            if meta_desc and meta_desc.get('content'):
                vod['vod_content'] = meta_desc['content'].strip()

            # 2. 【核心优化】在详情页提前解析出真实 m3u8 播放地址，实现秒播
            real_m3u8 = None
            video_tag = soup.select_one('video#video-play') or soup.select_one('video[data-src]')
            if video_tag and video_tag.get('data-src'):
                real_m3u8 = video_tag.get('data-src')

            if not real_m3u8:
                match = re.search(r'id=["\']video-play["\'][^>]*data-src=["\']([^"\']+)["\']', html_text)
                if not match:
                    match = re.search(r'data-src=["\']([^"\']+\.m3u8[^"\']*)["\']', html_text)
                if match:
                    real_m3u8 = match.group(1)

            if real_m3u8:
                real_m3u8 = html.unescape(real_m3u8)
                # 如果成功获取 m3u8 直链，直接写入 play_url，省去 playerContent 的二次请求
                vod['vod_play_url'] = f'高清原画${real_m3u8}'

        except Exception as e:
            pass
            
        return {'list': [vod]}

    def searchContent(self, key, quick):
        encoded_key = quote_plus(key)
        url = f"{self.site_url}/search?keywords={encoded_key}"
        
        result = {}
        try:
            rsp = self.fetch(url, headers=self.headers)
            soup = BeautifulSoup(rsp.text, 'html.parser')
            
            videos = []
            container = soup.select_one('#rd5')
            if container:
                articles = container.select('article')
                for article in articles:
                    vod = self._parse_article(article)
                    if vod:
                        videos.append(vod)
            result['list'] = videos
        except Exception as e:
            result['list'] = []
            
        return result

    def playerContent(self, flag, id, vipFlags):
        # 如果详情页未能提前解析出直链，id 会传过来页面链接，这里保留兜底解析
        play_url = id if id.startswith('http') else f"{self.site_url}{id}"
        
        result = {
            "parse": 0,
            "playUrl": "",
            "url": "",
            "header": {
                'User-Agent': self.headers['User-Agent'],
                'Referer': self.site_url
            }
        }
        
        # 如果 id 本身已经是 m3u8 地址，直接返回播放
        if '.m3u8' in play_url:
            result["url"] = play_url
            return result

        # 兜底：如果传来的还是网页链接，则再次尝试解析
        try:
            rsp = self.fetch(play_url, headers=self.headers)
            html_text = rsp.text
            soup = BeautifulSoup(html_text, 'html.parser')
            
            real_m3u8 = None
            video_tag = soup.select_one('video#video-play') or soup.select_one('video[data-src]')
            if video_tag and video_tag.get('data-src'):
                real_m3u8 = video_tag.get('data-src')

            if not real_m3u8:
                match = re.search(r'id=["\']video-play["\'][^>]*data-src=["\']([^"\']+)["\']', html_text)
                if not match:
                    match = re.search(r'data-src=["\']([^"\']+\.m3u8[^"\']*)["\']', html_text)
                if match:
                    real_m3u8 = match.group(1)

            if real_m3u8:
                result["url"] = html.unescape(real_m3u8)
            else:
                result["parse"] = 1
                result["url"] = play_url
                
        except Exception as e:
            result["parse"] = 1
            result["url"] = play_url

        return result

    def localProxy(self, param):
        pass

    def _parse_article(self, article):
        try:
            title_node = article.select_one('h4 a')
            if not title_node:
                return None
            title = title_node.get_text(strip=True)
            
            a_node = article.select_one('a')
            if not a_node or not a_node.get('href'):
                return None
            href = a_node['href']
            
            if '/viewhd/' in href:
                href = href.replace('/viewhd/', '/view/')
                
            link = f"{self.site_url}{href}" if not href.startswith('http') else href
            
            img_node = article.select_one('img')
            pic = img_node.get('src', '') if img_node else ''
            
            duration_node = article.select_one('.duration')
            time_node = article.select_one('time')
            
            duration = duration_node.get_text(strip=True) if duration_node else ''
            pub_time = time_node.get_text(strip=True) if time_node else ''
            
            remarks = f"⏱️{duration} 📆{pub_time}".strip()
            
            return {
                'vod_id': link,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': remarks
            }
        except Exception:
            return None
