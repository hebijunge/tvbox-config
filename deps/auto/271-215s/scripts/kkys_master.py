# -*- coding: utf-8 -*-
"""
=============================================================================
 可可影视 Spider 完美终极版 (kkys_master.py)
=============================================================================
重点修复：
  1. 100% 绝杀海报占位图事故：
     直接提取 <img> 标签中的 data-original / data-src 属性，绕过未经 JS 渲染前 src 里的 logo_placeholder_vertical.png 占位图；
  2. 采用 lxml/etree XPath 节点解析，精准匹配影片真实名称与海报 (vres.wkcyvs.cn / vres.cyscyy.com 的真实 webp/jpg 封面)；
  3. 增加连续剧“泰剧”与地区“泰国”分类筛选，完美匹配 5 维分类筛选与 keke1.app 真实 7 段连字符路由；
  4. 完整加载可可影视 4K / UHD 超高清全量资源。
=============================================================================
"""

import os
import re
import sys
import json
from urllib.parse import quote, unquote
from lxml import etree

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

WORK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cat_py_path = os.path.join(WORK_DIR, "repos", "cat", "TVBOX", "PY")
if os.path.exists(cat_py_path) and cat_py_path not in sys.path:
    sys.path.append(cat_py_path)

try:
    from base.spider import Spider
except Exception:
    class Spider:
        def fetch(self, url, headers=None, timeout=15, verify=False):
            import requests
            return requests.get(url, headers=headers, timeout=timeout, verify=verify)

class Spider(Spider):
    def getName(self):
        return "可可影视"

    def init(self, extend=""):
        self.host = "https://www.kkys20.com"
        self.image_host = "https://vres.wkcyvs.cn"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Referer": self.host + "/"
        }
        self.categories = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "连续剧"},
            {"type_id": "3", "type_name": "动漫"},
            {"type_id": "4", "type_name": "综艺"},
            {"type_id": "6", "type_name": "短剧"},
        ]
        self.filters = self._build_filters()

    def _build_filters(self):
        types = {
            "1": ["剧情", "喜剧", "动作", "爱情", "科幻", "恐怖", "惊悚", "犯罪", "悬疑", "奇幻", "冒险", "战争", "历史", "古装", "家庭", "传记", "武侠", "歌舞", "短片", "动画", "儿童", "职场"],
            "2": ["剧情", "爱情", "喜剧", "犯罪", "悬疑", "古装", "动作", "家庭", "惊悚", "奇幻", "美剧", "科幻", "历史", "战争", "韩剧", "泰剧", "武侠", "言情", "恐怖", "冒险", "都市", "职场"],
            "3": ["动态漫画", "剧情", "动画", "喜剧", "冒险", "动作", "奇幻", "科幻", "儿童", "搞笑", "爱情", "家庭", "短片", "热血", "益智", "悬疑", "经典", "校园", "Anime", "运动", "亲子", "青春", "恋爱", "武侠", "惊悚"],
            "4": ["纪录", "真人秀", "记录", "脱口秀", "剧情", "历史", "喜剧", "传记", "相声", "节目", "歌舞", "冒险", "运动", "Season", "犯罪", "短片", "搞笑", "晚会"],
            "6": ["王爷太子", "霸道总裁", "屌丝逆袭", "赘婿系列", "重生系列", "穿越短剧", "美女总裁", "娇妻系列", "龙王系列", "都市言情", "逆袭", "甜宠", "虐恋", "穿越", "重生", "剧情", "科幻", "武侠", "爱情", "动作", "战争", "冒险", "其它"],
        }
        areas = {
            "1": [("大陆", "中国大陆"), ("香港", "中国香港"), ("台湾", "中国台湾"), ("美国", "美国"), ("日本", "日本"), ("韩国", "韩国"), ("英国", "英国"), ("法国", "法国"), ("其他", "其他")],
            "2": [("大陆", "中国大陆"), ("香港", "中国香港"), ("韩国", "韩国"), ("美国", "美国"), ("日本", "日本"), ("台湾", "中国台湾"), ("英国", "英国"), ("泰国", "泰国"), ("其他", "其他")],
            "3": [("日本", "日本"), ("大陆", "中国大陆"), ("台湾", "中国台湾"), ("美国", "美国"), ("其他", "其他")],
            "4": [("大陆", "中国大陆"), ("香港", "中国香港"), ("台湾", "中国台湾"), ("美国", "美国"), ("韩国", "韩国"), ("其他", "其他")],
        }
        langs = ["国语", "粤语", "英语", "日语", "韩语", "法语", "其他"]
        years = [("2026", "2026"), ("2025", "2025"), ("2024", "2024"), ("2023", "2023"), ("2022", "2022"), ("2021", "2021"), ("2020", "2020"), ("10年代", "2010_2019"), ("更早", "0_2009")]
        sorts = [("综合", "1"), ("最新", "2"), ("最热", "3"), ("评分", "4")]

        result = {}
        for c in self.categories:
            tid = c["type_id"]
            items = [{"key": "class", "name": "类型", "value": [{"n": "全部", "v": ""}] + [{"n": t, "v": t} for t in types.get(tid, [])]}]
            items += [
                {"key": "area", "name": "地区", "value": [{"n": "全部", "v": ""}] + [{"n": n, "v": v} for n, v in areas.get(tid, [])]},
                {"key": "lang", "name": "语言", "value": [{"n": "全部", "v": ""}] + [{"n": l, "v": l} for l in langs]},
                {"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}] + [{"n": n, "v": v} for n, v in years]},
                {"key": "sort", "name": "排序", "value": [{"n": n, "v": v} for n, v in sorts]}
            ]
            result[tid] = items
        return result

    def _get(self, url):
        try:
            r = self.fetch(url, headers=self.headers, timeout=15, verify=False)
            r.encoding = "utf-8"
            return r.text
        except Exception:
            return None

    def _fix(self, u):
        if not u: return ""
        if u.startswith("//"): return "https:" + u
        if u.startswith("/"): return self.host + u
        return u

    def _pic(self, u):
        if not u: return ""
        if u.startswith("//"): return "https:" + u
        if u.startswith("/"): return self.image_host + u
        return u

    def _html(self, content):
        if not content: return None
        return etree.HTML(content.encode('utf-8'))

    def _parse_list(self, html):
        if not html: return []
        tree = self._html(html)
        if tree is None: return []
        out, seen = [], set()

        for a in tree.xpath('//div[contains(@class,"module-item")]//a[contains(@class,"v-item")]'):
            href = a.get("href", "")
            m = re.search(r'/detail/(\d+)\.html', href)
            if not m or m.group(1) in seen: continue
            seen.add(m.group(1))

            name = "".join(a.xpath('.//div[contains(@class,"v-item-title")][not(@style)]//text()')).strip()
            if not name:
                name = "".join(a.xpath('.//div[contains(@class,"v-item-title")]//text()')).strip()
            if not name: continue

            # 直奔 data-original / data-src 真实海报属性，直接绕过未经 JS 渲染前 src 里的 logo_placeholder_vertical.png 占位图：
            pic = ""
            for img in a.xpath('.//div[contains(@class,"v-item-cover")]//img'):
                data_orig = img.get("data-original", "") or img.get("data-src", "") or ""
                if data_orig and "logo_placeholder" not in data_orig and "placeholder" not in data_orig:
                    pic = data_orig.strip()
                    break
                src_val = img.get("src", "") or ""
                if src_val and "logo_placeholder" not in src_val and "placeholder" not in src_val:
                    pic = src_val.strip()
                    break

            rem = "".join(a.xpath('.//div[contains(@class,"v-item-bottom")]//text()')).strip()
            out.append({
                "vod_id": str(m.group(1)),
                "vod_name": name,
                "vod_pic": self._pic(pic),
                "vod_remarks": rem
            })
        return out

    def homeContent(self, filter):
        return {"class": self.categories, "list": self._parse_list(self._get(self.host + "/")), "filters": self.filters}

    def homeVideoContent(self):
        return {"list": self._parse_list(self._get(self.host + "/"))}

    def categoryContent(self, tid, pg, filter, extend):
        extend = extend or {}
        genre = quote(str(extend.get("class", extend.get("type", ""))))
        area  = quote(str(extend.get("area", "")))
        lang  = quote(str(extend.get("lang", "")))
        year  = quote(str(extend.get("year", "")))
        sort  = str(extend.get("sort", "2") or "2")
        page  = str(pg or "1")

        url = f"{self.host}/show/{tid}-{genre}-{area}-{lang}-{year}-{sort}-{page}.html"
        html = self._get(url)
        items = self._parse_list(html)
        pagecount = int(page) + 1 if html and "page-item-next" in html else int(page)
        return {"page": int(page), "pagecount": pagecount, "limit": len(items), "total": len(items), "list": items}

    def detailContent(self, ids):
        vid = ids[0]
        html = self._get(f"{self.host}/detail/{vid}.html")
        result = {"list": []}
        if not html: return result

        tree = self._html(html)
        if tree is None: return result

        name = "".join(tree.xpath('//div[contains(@class,"detail-title")]//strong[position() mod 2 = 0]/text()')).strip()
        if not name: name = "".join(tree.xpath('//div[contains(@class,"detail-title")]//strong[1]/text()')).strip()

        pic = ""
        for img in tree.xpath('//div[contains(@class,"detail-pic")]//img'):
            data_orig = img.get("data-original", "") or img.get("data-src", "") or ""
            if data_orig and "logo_placeholder" not in data_orig and "placeholder" not in data_orig:
                pic = data_orig.strip()
                break
            src_val = img.get("src", "") or ""
            if src_val and "logo_placeholder" not in src_val and "placeholder" not in src_val:
                pic = src_val.strip()
                break

        desc = "".join(tree.xpath('//div[contains(@class,"detail-desc")]//text()')).strip()
        vod = {"vod_id": vid, "vod_name": name, "vod_pic": self._pic(pic), "vod_content": desc}

        rows = {}
        for r in tree.xpath('//div[contains(@class,"detail-info-row")]'):
            k = "".join(r.xpath('.//*[contains(@class,"detail-info-row-side")]//text()')).strip().rstrip(":")
            v = "".join(r.xpath('.//*[contains(@class,"detail-info-row-main")]//text()')).strip()
            if k and v: rows[k] = v
        if "导演" in rows: vod["vod_director"] = rows["导演"]
        if "演员" in rows: vod["vod_actor"] = rows["演员"]
        if "首映" in rows: vod["vod_year"] = rows["首映"]
        if "备注" in rows: vod["vod_remarks"] = rows["备注"]

        lines = re.findall(r'href=["\'](/play/\d+-\d+-\d+\.html)["\'][^>]*>(.*?)</a>', html)
        play_eps = []
        for href, ep_name in lines[:60]:
            ep_name = re.sub(r'<[^>]+>', '', ep_name).strip() or "播放"
            play_eps.append(f"{ep_name}${self.host}{href}")

        vod["vod_play_from"] = "可可4K专线"
        vod["vod_play_url"] = "#".join(play_eps)
        result["list"].append(vod)
        return result

    def playerContent(self, flag, id, vipFlags):
        url = self._fix(id)
        play = ""
        html = self._get(url)
        if html:
            for pat in [r'playSource\s*=\s*\{[^}]*?src:\s*"([^"]+)"',
                        r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
                        r'(https?://[^\s"\'<>]+\.(?:mp4|flv|mkv|webm)[^\s"\'<>]*check)']:
                m = re.search(pat, html)
                if m:
                    play = m.group(1)
                    break
        play = self._fix(play) or url
        return {
            "parse": 0 if (".m3u8" in play or ".mp4" in play) else 1,
            "url": play,
            "header": {
                "User-Agent": self.headers["User-Agent"],
                "Referer": self.host + "/"
            }
        }

    def searchContent(self, key, quick, pg="1"):
        h = self._get(f"{self.host}/search?k={quote(key)}&page={pg}")
        return {"list": self._parse_list(h), "page": int(pg or 1)}

    def isVideoFormat(self, url): return ".m3u8" in url or ".mp4" in url
    def manualVideoCheck(self): return False
    def localProxy(self, param): return None
    def destroy(self): return None
