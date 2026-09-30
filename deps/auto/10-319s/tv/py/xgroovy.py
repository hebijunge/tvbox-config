# coding: utf-8
import re
import json
from urllib.parse import urljoin, quote, unquote
from bs4 import BeautifulSoup
from base.spider import Spider

class Spider(Spider):

    def getName(self):
        return "xgroovy"

    def init(self, tid):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def getHeaders(self):
        return {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Referer': 'https://cn.xgroovy.com/'
        }

    # =========================================================
    # 1. 顶级分类定义 (第 1 层)
    # =========================================================
    def homeContent(self, filter):
        result = {}
        classes = [
            {"type_id": "new", "type_name": "🔥 最新"},
            {"type_id": "best", "type_name": "🏆 最佳影片"},
            {"type_id": "folder::pornstars", "type_name": "💃 模特列表"},
            {"type_id": "folder::categories", "type_name": "📂 视频分类"},
            {"type_id": "folder::tags", "type_name": "🏷️ 标签"}
        ]
        result['class'] = classes
        return result

    # 2. 首页推荐数据
    def homeVideoContent(self):
        url = "https://cn.xgroovy.com"
        rsp = self.fetch(url, headers=self.getHeaders())
        return {'list': self._parse_list(rsp.text)}

    # =========================================================
    # 3. 分类/穿透路由控制 (第 2 层 和 第 3 层)
    # =========================================================
    def categoryContent(self, tid, pg, filter, extend):
        if tid.startswith("folder::"):
            folder_type = tid.split("::")[1]
            
            if folder_type == "pornstars":
                page_url = "https://cn.xgroovy.com/pornstars/" if int(pg) == 1 else f"https://cn.xgroovy.com/pornstars/{pg}/"
                rsp = self.fetch(page_url, headers=self.getHeaders())
                return {
                    'page': int(pg),
                    'pagecount': 999,
                    'limit': 24,
                    'total': 9999,
                    'list': self._parse_models_folder(rsp.text)
                }

            elif folder_type == "categories":
                page_url = "https://cn.xgroovy.com/categories/" if int(pg) == 1 else f"https://cn.xgroovy.com/categories/{pg}/"
                rsp = self.fetch(page_url, headers=self.getHeaders())
                return {
                    'page': int(pg),
                    'pagecount': 999,
                    'limit': 100,
                    'total': 9999,
                    'list': self._parse_categories_folder(rsp.text)
                }

            elif folder_type == "tags":
                page_url = "https://cn.xgroovy.com/tags/" if int(pg) == 1 else f"https://cn.xgroovy.com/tags/{pg}/"
                rsp = self.fetch(page_url, headers=self.getHeaders())
                return {
                    'page': int(pg),
                    'pagecount': 999,
                    'limit': 100,
                    'total': 9999,
                    'list': self._parse_tags_folder(rsp.text)
                }

        cateId = extend.get('cateId', tid)
        clean_cate = cateId.strip('/')
        
        if clean_cate.startswith('http'):
            base_url = clean_cate
        else:
            base_url = f"https://cn.xgroovy.com/{clean_cate}"

        if int(pg) == 1:
            url = f"{base_url}/"
        else:
            url = f"{base_url}/{pg}/"

        rsp = self.fetch(url, headers=self.getHeaders())
        video_list = self._parse_list(rsp.text)

        if not video_list and ("tags" in clean_cate or "tag" in clean_cate):
            tag_keyword = clean_cate.split('/')[-1]
            tag_keyword = unquote(tag_keyword)
            
            if int(pg) == 1:
                search_url = f"https://cn.xgroovy.com/search/{quote(tag_keyword)}/"
            else:
                search_url = f"https://cn.xgroovy.com/search/{quote(tag_keyword)}/{pg}/"
                
            rsp_search = self.fetch(search_url, headers=self.getHeaders())
            video_list = self._parse_list(rsp_search.text)

        return {
            'page': int(pg),
            'pagecount': 999,
            'limit': 24,
            'total': 9999,
            'list': video_list
        }

    # =========================================================
    # 4. 详情页解析 (第 4 层) - 多清晰度选集优化
    # =========================================================
    def detailContent(self, ids):
        vod_id = ids[0]
        url = vod_id if vod_id.startswith('http') else urljoin("https://cn.xgroovy.com", vod_id)
        
        rsp = self.fetch(url, headers=self.getHeaders())
        soup = BeautifulSoup(rsp.text, 'html.parser')

        title = ""
        title_node = soup.select_one("h1, .title, meta[property='og:title']")
        if title_node:
            title = title_node.get('content', '') or title_node.text.strip()

        pic = ""
        img_node = soup.select_one("video[poster], meta[property='og:image']")
        if img_node:
            pic = img_node.get('poster') or img_node.get('content', '')

        # 匹配视频标签下的所有 source 获得多清晰度
        play_sources = []
        sources = soup.select("video#main_video source, #kt_player source, video source")
        
        for source in sources:
            quality = source.get('title') or source.get('id', '清晰度')
            src_url = source.get('src')
            if src_url:
                play_sources.append(f"{quality}${src_url}")

        if play_sources:
            play_url_str = "#".join(play_sources)
        else:
            play_url_str = f"在线播放${vod_id}"

        vod = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "type_name": "视频",
            "vod_year": "",
            "vod_area": "",
            "vod_remarks": "",
            "vod_actor": "",
            "vod_director": "",
            "vod_content": "",
            "vod_play_from": "Xgroovy",
            "vod_play_url": play_url_str
        }

        return {"list": [vod]}

    # 5. 搜索功能
    def searchContent(self, key, quick):
        url = f"https://cn.xgroovy.com/search/{quote(key)}/"
        rsp = self.fetch(url, headers=self.getHeaders())
        return {'list': self._parse_list(rsp.text)}

    # =========================================================
    # 6. 播放直链提取
    # =========================================================
    def playerContent(self, flag, id, vipFlags):
        if id.startswith('http'):
            return {
                "parse": 0,
                "url": id,
                "header": self.getHeaders()
            }
        
        url = urljoin("https://cn.xgroovy.com", id)
        rsp = self.fetch(url, headers=self.getHeaders())
        soup = BeautifulSoup(rsp.text, 'html.parser')
        
        video_url = ""
        source_node = soup.select_one("video#main_video source[src], #kt_player source[src]")
        if source_node:
            video_url = source_node.get('src')
        else:
            match = re.search(r'(https?://[^\s"\']+\.(?:m3u8|mp4)[^\s"\']*)', rsp.text)
            if match:
                video_url = match.group(1)

        if video_url:
            return {
                "parse": 0,
                "url": video_url,
                "header": self.getHeaders()
            }
        else:
            return {
                "parse": 1,
                "url": url,
                "header": self.getHeaders()
            }

    # =========================================================
    # 内部 HTML 解析提取方法
    # =========================================================

    def _parse_models_folder(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        folders = []
        
        items = soup.select(".list-models .item, .list-performers .item, .list-pornstars .item, .item-model")
        if not items:
            items = soup.select("a[href*='/models/'], a[href*='/pornstars/']")

        for item in items:
            a_tag = item if item.name == 'a' else item.select_one("a")
            if not a_tag:
                continue

            href = a_tag.get('href', '')
            if not href or href.strip('/') in ['models', 'pornstars', 'categories', 'tags', '']:
                continue

            title_tag = item.select_one(".title, .name")
            title = title_tag.text.strip() if title_tag else (a_tag.get('title', '') or a_tag.text.strip())
            
            img_tag = item.select_one("img")
            pic = img_tag.get('data-src') or img_tag.get('src', '') if img_tag else ""

            count_tag = item.select_one(".videos, .count, .rating")
            remarks = count_tag.text.strip() if count_tag else "模特"

            folders.append({
                "vod_id": href.lstrip('/'),
                "vod_name": title,
                "vod_pic": pic,
                "vod_tag": "folder",
                "vod_remarks": remarks
            })

        return folders

    def _parse_categories_folder(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        folders = []
        items = soup.select(".list-categories .item, a[href*='/categories/']")
        for item in items:
            a_tag = item if item.name == 'a' else item.select_one("a")
            if not a_tag: continue
            
            href = a_tag.get('href', '')
            if not href or href.strip('/') in ['categories', '']: continue
            
            title = a_tag.get('title', '') or a_tag.text.strip()
            img_tag = item.select_one("img")
            pic = img_tag.get('data-src') or img_tag.get('src', '') if img_tag else ""

            folders.append({
                "vod_id": href.lstrip('/'),
                "vod_name": title,
                "vod_pic": pic,
                "vod_tag": "folder",
                "vod_remarks": "分类"
            })
        return folders

    def _parse_tags_folder(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        folders = []
        items = soup.select(".list-tags-simple li")

        for item in items:
            a_tag = item.select_one("a")
            if not a_tag:
                continue

            href = a_tag.get('href', '').strip()
            clean_href = href.strip('/')

            if not clean_href:
                continue

            span_tag = a_tag.select_one("span")
            remarks = span_tag.text.strip() if span_tag else "标签"

            tag_name = ""
            if a_tag.contents:
                tag_name = str(a_tag.contents[0]).strip()
            
            if not tag_name:
                tag_name = re.sub(r'\(.*?\)', '', a_tag.text).strip()

            folders.append({
                "vod_id": clean_href,
                "vod_name": tag_name,
                "vod_pic": "",
                "vod_tag": "folder",
                "vod_remarks": remarks
            })

        return folders

    def _parse_list(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        videos = []
        
        items = soup.select("#list_videos_custom_all_videos_items .item")
        if not items:
            items = soup.select(".list-videos .item, .list-videos:has(img) .item, .item-video")
        
        for item in items:
            a_tag = item.select_one("a.popito") or item.select_one("a")
            if not a_tag:
                continue

            href = a_tag.get('href', '')
            if not href or href == '/':
                continue

            title_tag = item.select_one("strong.title") or item.select_one(".title")
            img_tag = item.select_one("img.thumb") or item.select_one("img")
            
            title = ""
            if title_tag:
                title = title_tag.text.strip()
            elif img_tag and img_tag.get('alt'):
                title = img_tag.get('alt').strip()
            else:
                title = a_tag.get('title', '').strip() or a_tag.text.strip()

            pic = ""
            if img_tag:
                pic = img_tag.get('data-jpg') or img_tag.get('src') or img_tag.get('data-src') or ""
                if pic.startswith('//'):
                    pic = 'https:' + pic

            duration_tag = item.select_one(".duration")
            views_tag = item.select_one(".views")
            
            duration = duration_tag.text.strip() if duration_tag else ""
            views = views_tag.text.strip() if views_tag else ""
            
            remarks = f"{duration} {views}".strip()

            videos.append({
                "vod_id": href,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks
            })

        return videos
