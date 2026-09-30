# coding: utf-8
import sys
import json
import re
from urllib.parse import quote
from bs4 import BeautifulSoup
from base.spider import Spider

sys.path.append('..')

class Spider(Spider):
    HOST = 'https://bad.news'

    def getName(self):
        return "BAD-Direct"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def action(self, action):
        pass

    # 只保留 User-Agent 请求头
    def getHeader(self):
        return {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Xiaomi 13 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36"
        }

    # 1. 分类菜单
    def homeContent(self, filter):
        try:
            result = {}
            classes = [
                {"type_name": "全部", "type_id": ""},
                {"type_name": "短视频", "type_id": "/tag/porn"},
                {"type_name": "长视频", "type_id": "/tag/long-porn"},
                {"type_name": "动漫", "type_id": "/dm"}
            ]
            result['class'] = classes

            if filter:
                result['filters'] = {
                    "/dm": [
                        {
                            "key": "cateId",
                            "name": "分类",
                            "value": [
                                {"n": "动漫", "v": "/dm"},
                                {"n": "3d动漫", "v": "/dm/type/q-3D"},
                                {"n": "同人作品", "v": "/dm/type/q-%E5%90%8C%E4%BA%BA"},
                                {"n": "Cosplay", "v": "/dm/type/q-Cosplay"}
                            ]
                        }
                    ]
                }
            return result
        except Exception:
            return {'class': []}

    # 2. 首页推荐数据
    def homeVideoContent(self):
        try:
            url = f"{self.HOST}/search/q-%E5%AD%A6%E7%94%9F"
            rsp = self.fetch(url, headers=self.getHeader())
            if not rsp or not rsp.text:
                return {'list': []}
            return {'list': self._parse_list(rsp.text)}
        except Exception:
            return {'list': []}

    # 3. 分类数据
    def categoryContent(self, tid, pg, filter, extend):
        try:
            extend = extend or {}
            cateId = extend.get("cateId", tid) or ""
            by = extend.get("by", "") or ""
            pg_str = str(pg) if pg else "1"
            
            if pg_str == "1":
                url = f"{self.HOST}{cateId}{by}"
            else:
                url = f"{self.HOST}{cateId}{by}/page-{pg_str}"
            
            rsp = self.fetch(url, headers=self.getHeader())
            if not rsp or not rsp.text:
                return {'list': [], 'page': int(pg_str), 'pagecount': 1, 'limit': 20, 'total': 0}

            return {
                'list': self._parse_list(rsp.text),
                'page': int(pg_str),
                'pagecount': 9999,
                'limit': 20,
                'total': 99999
            }
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 20, 'total': 0}

    # 4. 详情页处理
    def detailContent(self, array):
        try:
            if not array or not array[0]:
                return {'list': []}

            raw_id = str(array[0])
            title = "视频详情"
            target_url = raw_id

            if "||" in raw_id:
                parts = raw_id.split("||", 1)
                target_url = parts[0]
                title = parts[1]

            if target_url and not target_url.startswith("http"):
                target_url = f"{self.HOST}{target_url}" if target_url.startswith("/") else f"{self.HOST}/{target_url}"

            play_url = target_url
            if "/dm/play/" in target_url or "/play/" in target_url:
                try:
                    rsp = self.fetch(target_url, headers=self.getHeader())
                    if rsp and rsp.text:
                        soup = BeautifulSoup(rsp.text, 'html.parser')
                        video_tag = soup.select_one("video.my-videos, video")
                        if video_tag:
                            m3u8 = video_tag.get("data-source") or video_tag.get("src") or ""
                            if not m3u8:
                                source_tag = video_tag.select_one("source")
                                if source_tag:
                                    m3u8 = source_tag.get("src") or source_tag.get("data-source") or ""
                            if m3u8:
                                play_url = str(m3u8)
                except Exception:
                    pass

            if play_url and not play_url.startswith("http"):
                play_url = f"{self.HOST}{play_url}" if play_url.startswith("/") else f"{self.HOST}/{play_url}"

            vod = {
                "vod_id": raw_id,
                "vod_name": title,
                "vod_pic": "",
                "type_name": "",
                "vod_year": "",
                "vod_area": "",
                "vod_remarks": "",
                "vod_actor": "",
                "vod_director": "",
                "vod_content": "",
                "vod_play_from": "BAD-Direct",
                "vod_play_url": f"正片${play_url}"
            }

            return {'list': [vod]}
        except Exception:
            return {'list': []}

    # 5. 搜索功能
    def searchContent(self, key, quick, *args, **kwargs):
        try:
            pg = "1"
            if args:
                pg = str(args[0])
            elif "pg" in kwargs:
                pg = str(kwargs["pg"])

            encoded_key = quote(str(key))
            url = f"{self.HOST}/search/t-all/q-{encoded_key}"
            if pg != "1" and pg:
                url = f"{self.HOST}/search/t-all/q-{encoded_key}/page-{pg}"

            rsp = self.fetch(url, headers=self.getHeader())
            if not rsp or not rsp.text:
                return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 20, 'total': 0}

            return {
                'list': self._parse_list(rsp.text),
                'page': int(pg) if pg.isdigit() else 1,
                'pagecount': 9999,
                'limit': 20,
                'total': 99999
            }
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 20, 'total': 0}

    # 6. 纯净播放接口 (只包含 UA 请求头)
    def playerContent(self, flag, id, vipFlags):
        try:
            play_url = str(id) if id else ""
            if "||" in play_url:
                play_url = play_url.split("||")[0]

            if play_url and not play_url.startswith("http"):
                play_url = f"{self.HOST}{play_url}" if play_url.startswith("/") else f"{self.HOST}/{play_url}"

            ua_header = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 13; Xiaomi 13 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36"
            }

            return {
                "parse": 0,
                "jx": 0,
                "playUrl": "",
                "url": play_url,
                "header": ua_header
            }
        except Exception:
            return {"parse": 0, "jx": 0, "playUrl": "", "url": "", "header": {}}

    # 7. 带有广告过滤机制的解析逻辑
    def _parse_list(self, html):
        vod_list = []
        if not html:
            return vod_list

        try:
            soup = BeautifulSoup(html, 'html.parser')

            # 定义常见广告关键词列表
            ad_keywords = ["招聘", "兼职", "博彩", "赌", "客服", "微信", "加群", "广告", "tg", "telegram"]

            # ---- 模式 A：动漫分类列表 ----
            stui_items = soup.select("ul.stui-vodlist > li")
            if stui_items:
                for item in stui_items:
                    # 检查 class 是否包含 ad 标识
                    item_class = " ".join(item.get("class", []))
                    if "ad" in item_class.lower() or "sponsor" in item_class.lower():
                        continue

                    a_tag = item.select_one("a.stui-vodlist__thumb")
                    if not a_tag:
                        continue

                    href = str(a_tag.get("href") or "")
                    if not href:
                        continue

                    title = str(a_tag.get("title") or "")
                    if not title:
                        title_a = item.select_one(".stui-vodlist__detail h4.title a")
                        if title_a:
                            title = title_a.get_text(strip=True)
                    if not title:
                        title = "动漫视频"

                    # 标题广告词过滤
                    if any(kw in title.lower() for kw in ad_keywords):
                        continue

                    pic = str(a_tag.get("data-echo-background") or a_tag.get("data-original") or "")
                    if pic and not pic.startswith("http"):
                        pic = f"{self.HOST}{pic}" if pic.startswith("/") else f"{self.HOST}/{pic}"

                    combined_id = f"{href}||{title}"

                    vod_list.append({
                        "vod_id": combined_id,
                        "vod_name": title,
                        "vod_pic": pic,
                        "vod_remarks": ""
                    })
                return vod_list

            # ---- 模式 B：普通流卡片 (加入广告过滤机制) ----
            cards = soup.select("#item-container > div.twi[data-tid]")
            if not cards:
                cards = soup.select("div.twi.hasMedia[data-tid], div.twi")

            for card in cards:
                # 1. 类名广告识别
                card_class = " ".join(card.get("class", []))
                if "ad" in card_class.lower() or "sponsor" in card_class.lower() or "promote" in card_class.lower():
                    continue

                # 2. 全文本关键词过滤（防止招聘卡片伪装）
                card_text = card.get_text()
                if any(kw in card_text for kw in ad_keywords):
                    continue

                # 3. 提取视频节点
                video_tag = card.select_one("video.my-videos, video")
                if not video_tag:
                    continue

                m3u8_url = str(video_tag.get("data-source") or video_tag.get("src") or "")
                if not m3u8_url:
                    source_tag = video_tag.select_one("source")
                    if source_tag:
                        m3u8_url = str(source_tag.get("src") or source_tag.get("data-source") or "")

                # 如果视频地址为空或包含非法/广告链接
                if not m3u8_url or "javascript" in m3u8_url:
                    continue

                if not m3u8_url.startswith("http"):
                    m3u8_url = f"{self.HOST}{m3u8_url}" if m3u8_url.startswith("/") else f"{self.HOST}/{m3u8_url}"

                title_a = card.select_one("h3 a.auth, h3 a, h4 a")
                title = title_a.get_text(strip=True) if title_a else "无标题"

                pic = str(video_tag.get("poster") or "")
                if not pic:
                    img_tag = card.select_one("img")
                    if img_tag:
                        pic = str(img_tag.get("data-echo") or img_tag.get("src") or "")

                if pic and not pic.startswith("http"):
                    pic = f"{self.HOST}{pic}" if pic.startswith("/") else f"{self.HOST}/{pic}"

                time_node = card.select_one(".ct-time, span.time")
                remarks = time_node.get_text(strip=True) if time_node else ""

                combined_id = f"{m3u8_url}||{title}"

                vod_list.append({
                    "vod_id": combined_id,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remarks
                })

            return vod_list
        except Exception:
            return vod_list
