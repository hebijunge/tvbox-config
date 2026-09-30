# coding: utf-8
import re
import json
import ssl
import urllib.request
import urllib.parse
from urllib.parse import quote
from bs4 import BeautifulSoup

# 1. 宿主环境基类降级保护（兼容 OK 影视 / CatVod 反射调用）
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def init(self, extend=""): pass
        def homeContent(self, filter=None): return {}
        def homeVideoContent(self): return {}
        def categoryContent(self, tid, pg, filter=None, extend=None): return {}
        def detailContent(self, ids): return {}
        def searchContent(self, key, quick, pg="1"): return {}
        def playerContent(self, flag, id, vipFlags): return {}
        def isVideoFormat(self, url): return False
        def manualVideoCheck(self): return False, ""
        def localProxy(self, param): return []

class Spider(Spider):
    HOST = "https://shise.me"
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

    def getName(self):
        return "视色"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url

    def manualVideoCheck(self):
        return False, ""

    def get_headers(self):
        return {
            "User-Agent": self.UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"{self.HOST}/"
        }

    def _fix_pic_url(self, pic):
        """修复图片绝对路径并拼接图片防盗链 Header"""
        if not pic:
            return ""
        pic = pic.strip("'\" ")
        if pic.startswith("//"):
            pic = "https:" + pic
        elif pic.startswith("/"):
            pic = self.HOST + pic
        elif not pic.startswith("http"):
            pic = self.HOST + "/" + pic

        # 拼装客户端图片防盗链请求头
        return f"{pic}#User-Agent${self.UA}#Referer${self.HOST}/"

    def action_fetch(self, url):
        """原生 urllib 网络请求，完全替换掉 requests/urllib3，防止 OK 影视崩溃"""
        try:
            req = urllib.request.Request(url, headers=self.get_headers())
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            with urllib.request.urlopen(req, context=ctx, timeout=12) as response:
                return response.read().decode('utf-8', errors='ignore')
        except Exception:
            return ""

    # 1. 分类与筛选（去掉了【推荐】分类）
    def homeContent(self, filter=None):
        classes = [
            {"type_name": "中文AV", "type_id": "series-63824a975d8ae"},
            {"type_name": "日本AV", "type_id": "series-6206216719462"},
            {"type_name": "模特私拍", "type_id": "series-6030196781d85"},
            {"type_name": "业余拍摄", "type_id": "series-617d3e7acdcc8"},
            {"type_name": "情色电影", "type_id": "series-61c4d9b653b6d"},
            {"type_name": "其他影片", "type_id": "series-60192e83c9e05"},
            {"type_name": "AI视频", "type_id": "series-69f3977abc9f7"}
        ]

        sort_options = [
            {"n": "更新时间", "v": ""},
            {"n": "观看最多", "v": "sort-read"},
            {"n": "评论最多", "v": "sort-comment"},
            {"n": "最近评论", "v": "sort-recent"},
            {"n": "时长最长", "v": "sort-length"}
        ]

        sub_categories = {
            "series-63824a975d8ae": [
                {"n": "全部", "v": ""},
                {"n": "麻豆传媒", "v": "series-5f904550b8fcc"},
                {"n": "独立创作者", "v": "series-61bf6e439fed6"},
                {"n": "糖心Vlog", "v": "series-61014080dbfde"},
                {"n": "蜜桃传媒", "v": "series-5fe8403919165"},
                {"n": "星空传媒", "v": "series-6054e93356ded"},
                {"n": "天美传媒", "v": "series-60153c49058ce"},
                {"n": "果冻传媒", "v": "series-5fe840718d665"}
            ],
            "series-6206216719462": [
                {"n": "全部", "v": ""},
                {"n": "有码AV", "v": "series-6395aba3deb74"},
                {"n": "无码AV", "v": "series-6395ab7fee104"}
            ]
        }

        filters = {}
        for cls in classes:
            cid = cls["type_id"]
            filters[cid] = [
                {"key": "sub", "name": "子分类", "value": sub_categories.get(cid, [{"n": "全部", "v": ""}])},
                {"key": "by", "name": "排序", "value": sort_options}
            ]

        return {"class": classes, "filters": filters}

    # 2. 软件自带的首页推荐数据注入
    def homeVideoContent(self):
        html = self.action_fetch(self.HOST)
        return self._parse_video_list(html, 1)

    # 3. 分类页
    def categoryContent(self, tid, pg, filter=None, extend=None):
        try:
            page = int(pg)
        except Exception:
            page = 1

        ext = {}
        if isinstance(extend, dict):
            ext = extend
        elif isinstance(extend, str) and extend.strip():
            try:
                ext = json.loads(extend)
            except Exception:
                ext = {}

        sub_id = ext.get("sub", "")
        by = ext.get("by", "")
        target_cid = sub_id if sub_id else tid

        if by:
            url = f"{self.HOST}/videos/{target_cid}/{by}/{page}.html"
        else:
            url = f"{self.HOST}/videos/{target_cid}/{page}.html"

        html = self.action_fetch(url)
        return self._parse_video_list(html, page)

    # 4. 搜索页
    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg)
        except Exception:
            page = 1

        encoded_kw = quote(key)
        url = f"{self.HOST}/videos/keyword-{encoded_kw}/{page}.html"
        html = self.action_fetch(url)
        return self._parse_video_list(html, page)

    # 5. 核心解析逻辑：BS4(CSS选择器) + 正则防爆二次兜底
    def _parse_video_list(self, html, current_page):
        if not html:
            return {"page": current_page, "pagecount": 0, "limit": 0, "total": 0, "list": []}

        videos = []
        
        # --- 策略 A: 先尝试 BS4 (CSS 选择器) ---
        try:
            soup = BeautifulSoup(html, "html.parser")
            items = soup.select(".video-list .item, .list.video-list .item, .item.video, div.item, .col-md-3, .col-xs-6, a[href*='/video/']")
            
            for item in items:
                try:
                    a_tag = item if item.name == 'a' else (item.select_one("a[href*='/video/']") or item.select_one("a[title]") or item.select_one("a"))
                    if not a_tag:
                        continue

                    title = a_tag.get("title", "") or a_tag.get_text(strip=True)
                    href = a_tag.get("href", "")
                    if not href or not title:
                        continue

                    if "/video/" not in href and "id-" not in href:
                        continue

                    v_id_match = re.search(r"id-([a-zA-Z0-9]+)", href)
                    vod_id = v_id_match.group(1) if v_id_match else href

                    raw_pic = ""
                    img_node = item.select_one(".img, img")
                    if img_node:
                        style = img_node.get("style", "")
                        if "url(" in style:
                            pic_match = re.search(r"url\(['\"]?(.*?)['\"]?\)", style)
                            if pic_match:
                                raw_pic = pic_match.group(1)
                        if not raw_pic:
                            raw_pic = img_node.get("data-original") or img_node.get("data-src") or img_node.get("src") or ""

                    pic = self._fix_pic_url(raw_pic)

                    remarks = ""
                    clock_icon = item.select_one(".fa-clock, .duration, .time")
                    if clock_icon and clock_icon.parent:
                        remarks = clock_icon.parent.get_text(strip=True)

                    videos.append({
                        "vod_id": vod_id,
                        "vod_name": title.strip(),
                        "vod_pic": pic,
                        "vod_remarks": remarks
                    })
                except Exception:
                    continue
        except Exception:
            pass

        # --- 策略 B: 正则表达式（如果 CSS 选择器没拿到数据，启动正则兜底） ---
        if not videos:
            pattern = re.compile(r'<a[^>]+href=["\']([^"\']*/video/[^"\']+)["\'][^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
            matches = pattern.findall(html)
            for href, content in matches:
                try:
                    title_match = re.search(r'title=["\']([^"\']+)["\']', content) or re.search(r'alt=["\']([^"\']+)["\']', content)
                    title = title_match.group(1) if title_match else re.sub(r'<[^>]+>', '', content).strip()
                    if not title or len(title) < 2:
                        continue

                    v_id_match = re.search(r"id-([a-zA-Z0-9]+)", href)
                    vod_id = v_id_match.group(1) if v_id_match else href

                    pic_match = (
                        re.search(r'data-original=["\']([^"\']+)["\']', content) or
                        re.search(r'data-src=["\']([^"\']+)["\']', content) or
                        re.search(r'src=["\']([^"\']+)["\']', content) or
                        re.search(r'url\([\'"]?(.*?)[\'"]?\)', content)
                    )
                    raw_pic = pic_match.group(1) if pic_match else ""
                    pic = self._fix_pic_url(raw_pic)

                    videos.append({
                        "vod_id": vod_id,
                        "vod_name": title.strip(),
                        "vod_pic": pic,
                        "vod_remarks": ""
                    })
                except Exception:
                    continue

        # 去重
        seen = set()
        unique_videos = []
        for v in videos:
            if v["vod_id"] not in seen:
                seen.add(v["vod_id"])
                unique_videos.append(v)

        page_count = current_page + 1 if len(unique_videos) > 0 else current_page

        return {
            "page": current_page,
            "pagecount": page_count,
            "limit": len(unique_videos),
            "total": len(unique_videos) * page_count if unique_videos else 0,
            "list": unique_videos
        }

    # 6. 详情页解析
    def detailContent(self, array):
        if not array:
            return {"list": []}

        vod_id = array[0]
        url = vod_id if vod_id.startswith("http") else f"{self.HOST}/video/id-{vod_id}.html"

        html = self.action_fetch(url)
        if not html:
            return {"list": []}

        try:
            title = "未知片名"
            raw_pic = ""

            soup = BeautifulSoup(html, "html.parser")
            title_node = (
                soup.select_one(".video-header h1") or 
                soup.select_one("h1.title") or 
                soup.select_one(".panel-heading h1") or 
                soup.select_one("h1")
            )
            if title_node:
                title = title_node.get_text(strip=True)

            og_pic = soup.select_one("meta[property='og:image']")
            if og_pic:
                raw_pic = og_pic.get("content", "")

            if title == "未知片名":
                title_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
                if title_match:
                    title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

            play_url = ""
            m3u8_match = re.search(r'(https?://[^\s"\']+\.(?:m3u8|mp4)[^\s"\']*)', html)
            if m3u8_match:
                play_url = m3u8_match.group(1)

            if not play_url:
                source_tag = soup.select_one("video source")
                if source_tag and source_tag.get("src"):
                    play_url = source_tag["src"]

            pic = self._fix_pic_url(raw_pic)

            vod = {
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_content": "",
                "vod_play_from": "视色播放",
                "vod_play_url": f"正片${play_url}" if play_url else ""
            }

            return {"list": [vod]}
        except Exception:
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        return {
            "parse": 0,
            "url": id,
            "header": self.get_headers()
        }

    def localProxy(self, param):
        pass
