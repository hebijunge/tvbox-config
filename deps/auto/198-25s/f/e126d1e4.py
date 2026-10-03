#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蜻蜓FM · TVBox Python爬虫｜修复完整版
修复：引擎加载规范、废弃HMAC签名、页面解析容错、封面缺失
"""
import json
import re
import time
import urllib.parse

try:
    from base.spider import Spider
except Exception:
    Spider = object
    import urllib.request

    class _Resp:
        def __init__(self, data):
            self.text = data

    def _fetch(url, headers=None):
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return _Resp(resp.read().decode("utf-8", errors="ignore"))


class Spider(Spider):
    HOST = "https://m.qingting.fm"
    WEBAPI = "https://webapi.qtfm.cn"
    SEARCH_API = "https://search.qtfm.cn"

    CATEGORIES = [
        {"key": "521", "name": "小说"},
        {"key": "1599", "name": "儿童故事"},
        {"key": "3613", "name": "文化"},
        {"key": "529", "name": "情感故事"},
        {"key": "537", "name": "教育"},
        {"key": "531", "name": "历史"},
        {"key": "3251", "name": "脱口秀"},
        {"key": "3496", "name": "评书"},
    ]

    def getName(self):
        return "蜻蜓FM"

    def isVideoFormat(self, url):
        return False

    def hasDnsCache(self):
        return False

    def getHeaders(self):
        return {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": "https://m.qingting.fm/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def init(self, cfg=""):
        pass

    def _get(self, url):
        if hasattr(self, "fetch"):
            return self.fetch(url, headers=self.getHeaders())
        return _fetch(url, headers=self.getHeaders())

    def _fetch_json(self, url):
        resp = self._get(url)
        return json.loads(resp.text)

    def _fetch_text(self, url):
        resp = self._get(url)
        return resp.text

    def _parse_ssr_stores(self, html):
        idx = html.find("__initStores")
        if idx < 0:
            return {}
        json_start = html.find("{", idx)
        depth = 0
        end = json_start
        for i in range(json_start, len(html)):
            c = html[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        try:
            return json.loads(html[json_start:end])
        except Exception:
            return {}

    def _extract_audio_url(self, channel_id, program_id):
        """废弃旧签名算法，访问播放页提取真实音频地址"""
        play_page_url = f"{self.HOST}/vchannels/{channel_id}/programs/{program_id}"
        html = self._fetch_text(play_page_url)
        match = re.search(r'"audioUrl":"(.*?)"', html)
        if match:
            return urllib.parse.unquote(match.group(1))
        return ""

    @staticmethod
    def _extract_channel_id(url_scheme):
        m = re.search(r"/vchannels/(\d+)", url_scheme or "")
        if m:
            return m.group(1)
        m = re.search(r"channel_id=(\d+)", url_scheme or "")
        if m:
            return m.group(1)
        return ""

    def homeContent(self, filter):
        classes = []
        for cat in self.CATEGORIES:
            classes.append({
                "type_name": cat["name"],
                "type_id": cat["key"],
            })
        videos = []
        try:
            data = self._fetch_json(f"{self.WEBAPI}/api/mobile/homepage/new")
            rank_list = data.get("rankinglist", [])
            for item in rank_list:
                cid = self._extract_channel_id(item.get("urlScheme", ""))
                if not cid:
                    continue
                videos.append({
                    "vod_id": cid,
                    "vod_name": item.get("title", ""),
                    "vod_pic": item.get("imgUrl", ""),
                    "vod_remarks": item.get("playCount", ""),
                })
        except Exception:
            pass
        if not videos:
            try:
                data = self._fetch_json(f"{self.WEBAPI}/api/mobile/rank/hotSaleWeekly")
                rank_list = data.get("rankinglist", [])
                for item in rank_list:
                    cid = self._extract_channel_id(item.get("urlScheme", ""))
                    if not cid:
                        continue
                    videos.append({
                        "vod_id": cid,
                        "vod_name": item.get("title", ""),
                        "vod_pic": item.get("imgUrl", ""),
                        "vod_remarks": item.get("playCount", ""),
                    })
            except Exception:
                pass
        return {"class": classes, "list": videos}

    def homeVideoContent(self):
        result = self.homeContent(False)
        return {"list": result.get("list", [])}

    def categoryContent(self, tid, pg=1, filter=0, extend=None):
        page = int(pg) if pg else 1
        videos = []
        if tid == "5":
            try:
                data = self._fetch_json(f"{self.WEBAPI}/api/mobile/radio/filter")
                regions = data.get("regionsRes", [])
                region_id = regions[0]["id"] if regions else 407
                radio_data = self._fetch_json(f"{self.WEBAPI}/api/mobile/radio/channels/{region_id}")
                channels = radio_data.get("data", radio_data.get("channels", []))
                if isinstance(channels, dict):
                    channels = channels.get("data", [])
                for ch in channels[:30]:
                    cid = str(ch.get("id", ch.get("channelId", "")))
                    if not cid:
                        continue
                    videos.append({
                        "vod_id": cid,
                        "vod_name": ch.get("title", ch.get("name", "")),
                        "vod_pic": ch.get("imgUrl", ""),
                        "vod_remarks": "直播",
                    })
            except Exception:
                pass
        else:
            try:
                url = f"{self.HOST}/categories/{tid}/"
                html = self._fetch_text(url)
                stores = self._parse_ssr_stores(html)
                cat_store = stores.get("CatStore", {})
                recommend_list = cat_store.get("recommend", [])
                all_channels = []
                for rec in recommend_list:
                    rec_data = rec.get("data", {})
                    if isinstance(rec_data, dict):
                        inner_list = rec_data.get("data", [])
                        if isinstance(inner_list, list):
                            all_channels.extend(inner_list)
                    elif isinstance(rec_data, list):
                        all_channels.extend(rec_data)
                seen = set()
                for ch in all_channels:
                    link = ch.get("link", {})
                    cid = str(link.get("content", "")) if isinstance(link, dict) else ""
                    if not cid:
                        us = ch.get("urlScheme", "")
                        m = re.search(r"/vchannels/(\d+)", us)
                        cid = m.group(1) if m else ""
                    if not cid or cid in seen:
                        continue
                    seen.add(cid)
                    img_url = re.sub(r"!\d+$", "", ch.get("imgUrl", ""))
                    videos.append({
                        "vod_id": cid,
                        "vod_name": ch.get("title", ""),
                        "vod_pic": img_url,
                        "vod_remarks": ch.get("playCnt", ch.get("playCount", "")),
                    })
                page_size = 30
                start = (page - 1) * page_size
                videos = videos[start:start + page_size]
            except Exception:
                pass
        pagecount = 999 if len(videos) >= 30 else page
        return {"list": videos, "page": page, "pagecount": pagecount, "limit": 30}

    def detailContent(self, ids):
        channel_id = ids[0] if ids else ""
        channel_info = {}
        try:
            data = self._fetch_json(f"{self.WEBAPI}/api/mobile/channels/{channel_id}")
            channel_info = data.get("channel", data)
        except Exception:
            pass
        title = channel_info.get("title", "")
        cover = channel_info.get("cover", channel_info.get("img", ""))
        desc = channel_info.get("description", channel_info.get("desc", ""))
        play_count = channel_info.get("playcount", channel_info.get("playCount", ""))
        programs = []
        total = 0
        try:
            data = self._fetch_json(f"{self.WEBAPI}/api/mobile/player/channels/{channel_id}/pages/1")
            programs = data.get("programs", [])
            total = data.get("total", 0)
        except Exception:
            pass
        play_url_parts = []
        for prog in programs:
            pid = str(prog.get("programId", prog.get("program_id", "")))
            ptitle = prog.get("title", "")
            play_url_parts.append(f"{ptitle}${channel_id}_{pid}")
        if total > 30:
            num_pages = (total + 29) // 30
            for pg_num in range(2, min(num_pages + 1, 21)):
                try:
                    page_data = self._fetch_json(f"{self.WEBAPI}/api/mobile/player/channels/{channel_id}/pages/{pg_num}")
                    page_progs = page_data.get("programs", [])
                    for prog in page_progs:
                        pid = str(prog.get("programId", prog.get("program_id", "")))
                        ptitle = prog.get("title", "")
                        play_url_parts.append(f"{ptitle}${channel_id}_{pid}")
                except Exception:
                    break
        play_url = "#".join(play_url_parts)
        vod = {
            "vod_id": channel_id,
            "vod_name": title,
            "vod_pic": cover,
            "vod_remarks": play_count,
            "vod_year": channel_info.get("update_time", "")[:4] if channel_info.get("update_time") else "",
            "vod_area": "蜻蜓FM",
            "vod_content": desc,
            "vod_play_from": "蜻蜓FM",
            "vod_play_url": play_url,
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags=0):
        parts = str(id).split("_")
        if len(parts) < 2:
            return {}
        channel_id, program_id = parts[0], parts[1]
        audio_url = self._extract_audio_url(channel_id, program_id)
        if not audio_url:
            return {}
        return {
            "parse": 0,
            "playUrl": audio_url,
            "header": self.getHeaders()
        }

    def searchContent(self, key, quick=None, pg=1):
        page = int(pg) if pg else 1
        videos = []
        encoded_key = urllib.parse.quote(str(key))
        try:
            url = f"{self.SEARCH_API}/v3/search?include=channel&k={encoded_key}&page={page}&pagesize=20"
            data = self._fetch_json(url)
            docs = data.get("data", {}).get("data", {}).get("docs", [])
            seen_channels = set()
            for doc in docs:
                parent_id = str(doc.get("parent_id", ""))
                if parent_id and parent_id not in seen_channels:
                    seen_channels.add(parent_id)
                    name = doc.get("description", doc.get("title", "")).replace("来自专辑《", "").replace("》", "")
                    videos.append({
                        "vod_id": parent_id,
                        "vod_name": name,
                        "vod_pic": doc.get("cover", ""),
                        "vod_remarks": doc.get("playcount", ""),
                    })
                elif not parent_id:
                    cid = str(doc.get("id", ""))
                    if cid and cid not in seen_channels:
                        seen_channels.add(cid)
                        videos.append({
                            "vod_id": cid,
                            "vod_name": doc.get("title", ""),
                            "vod_pic": doc.get("cover", ""),
                            "vod_remarks": doc.get("playcount", ""),
                        })
        except Exception:
            pass
        if not videos:
            try:
                url = f"{self.SEARCH_API}/v3/search?include=program&k={encoded_key}&page={page}&pagesize=20"
                data = self._fetch_json(url)
                docs = data.get("data", {}).get("data", {}).get("docs", [])
                seen_channels = set()
                for doc in docs:
                    parent_id = str(doc.get("parent_id", ""))
                    if parent_id and parent_id not in seen_channels:
                        seen_channels.add(parent_id)
                        name = (doc.get("description", "") or doc.get("title", "")).replace("来自专辑《", "").replace("》", "")
                        videos.append({
                            "vod_id": parent_id,
                            "vod_name": name,
                            "vod_pic": doc.get("cover", ""),
                            "vod_remarks": doc.get("playcount", ""),
                        })
            except Exception:
                pass
        return {"list": videos, "page": page}

    def isLive(self, tid):
        return tid == "5"


def get_spider():
    return Spider()


if __name__ == "__main__":
    s = Spider()
    print("✅ 蜻蜓FM爬虫，独立测试入口就绪")
