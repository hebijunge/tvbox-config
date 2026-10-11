
# -*- coding: utf-8 -*-
# 茎洞入口 Spider
# 站点: https://faq.jdrk5.yachts/jdrk/
# 真实结构: <a> + <img data-original> + const rawUrl = 'xxx.m3u8'

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def init(self, extend=""): pass
        def homeContent(self, filter): return {}
        def categoryContent(self, tid, pg, filter, extend): return {}
        def detailContent(self, ids): return {}
        def searchContent(self, key, quick, pg): return {}
        def playerContent(self, flag, id, vipFlags): return {}
        def localProxy(self, param): return [404, "text/plain", ""]
        def isVideoFormat(self, url): return False
        def manualVideoCheck(self): return False
        def getName(self): return ""

class Spider(BaseSpider):

    def init(self, extend=""):
        self.siteUrl = "https://faq.jdrk5.yachts"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": self.siteUrl + "/",
        }

    def homeContent(self, filter):
        result = {}
        class_parse = [
            {"type_name": "国产自拍", "type_id": "20"},
            {"type_name": "制服丝袜", "type_id": "21"},
            {"type_name": "强奸乱伦", "type_id": "22"},
            {"type_name": "教师学生", "type_id": "23"},
            {"type_name": "素人系列", "type_id": "24"},
            {"type_name": "人妻熟女", "type_id": "25"},
            {"type_name": "日韩无码", "type_id": "26"},
            {"type_name": "日韩有码", "type_id": "27"},
            {"type_name": "中文字幕", "type_id": "28"},
            {"type_name": "欧美风情", "type_id": "29"},
            {"type_name": "经典伦理", "type_id": "30"},
            {"type_name": "卡通动漫", "type_id": "31"},
        ]
        result["class"] = class_parse
        result["filters"] = {}
        result["list"] = []
        return result

    def categoryContent(self, tid, pg, filter, extend):
        import urllib.request
        import re
        result = {}
        url = f"{self.siteUrl}/vodtype/{tid}.html"
        if int(pg) > 1:
            url = f"{self.siteUrl}/vodtype/{tid}-{pg}.html"
        req = urllib.request.Request(url, headers=self.headers)
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="ignore")
        
        # 真实结构: <a href="/123.html" title="标题"><img data-original="..."/></a>
        items = re.findall(
            r'<a[^>]*href="(/\d+\.html)"[^>]*title="([^"]*)"[^>]*>.*?data-original="([^"]*)"',
            html, re.S
        )
        
        video_list = []
        for href, title, pic in items[:72]:
            vid = href.replace(".html", "").replace("/", "")
            video_list.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": "",
            })
        result["list"] = video_list
        result["page"] = pg
        result["pagecount"] = 100
        result["limit"] = 72
        result["total"] = 7200
        return result

    def detailContent(self, ids):
        import urllib.request
        import re
        result = {}
        vid = ids[0]
        url = f"{self.siteUrl}/{vid}.html"
        req = urllib.request.Request(url, headers=self.headers)
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="ignore")
        
        # 真实结构: const rawUrl = 'https://xxx.m3u8';
        m3u8_match = re.search(r"const rawUrl\s*=\s*'([^']+\.m3u8)'", html)
        m3u8_url = m3u8_match.group(1) if m3u8_match else ""
        
        # 标题
        title_match = re.search(r'<h1[^>]*>([^<]*)</h1>', html)
        title = title_match.group(1).strip() if title_match else vid
        
        result["list"] = [{
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": "",
            "vod_remarks": "",
            "vod_year": "",
            "vod_area": "",
            "vod_letter": "",
            "vod_class": "",
            "vod_duration": "",
            "vod_content": "",
            "vod_play_from": "高清",
            "vod_play_url": m3u8_url,
        }]
        return result

    def searchContent(self, key, quick, pg):
        result = {}
        result["list"] = []
        result["page"] = pg
        result["pagecount"] = 1
        result["limit"] = 20
        result["total"] = 0
        return result

    def playerContent(self, flag, id, vipFlags):
        result = {}
        result["parse"] = 0
        result["jx"] = 0
        result["url"] = id
        result["header"] = self.headers
        return result

    def localProxy(self, param):
        return [404, "text/plain", ""]

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def getName(self):
        return "茎洞入口"
