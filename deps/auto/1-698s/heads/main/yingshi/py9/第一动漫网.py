# -*- coding: utf-8 -*-
import re
import json
import requests
from urllib import parse
import sys
sys.path.append("..")
from base.spider import Spider as BaseSpider

class Spider(BaseSpider):
    """
    第一动漫网 · 纯正则版 · 兼容性强化
    适配 TVBox / PeekPro / FongMi
    """

    def init(self, extend=""):
        self.host = "https://www.1dm5.cc"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.host + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        # 硬编码分类（临字秘兜底）
        self.class_map = {
            "1": "国产动漫",
            "2": "日韩动漫",
            "3": "欧美动漫",
            "4": "港台动漫",
            "5": "动漫电影",
            "6": "里番动漫",
            "7": "海外动漫",
            "13": "AI漫剧",
        }
        # 调试日志（生产可关闭）
        self.debug = True

    def _log(self, msg):
        if self.debug:
            print(f"[1dm5] {msg}")

    def _fetch(self, url):
        try:
            resp = self.session.get(url, timeout=15)
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            self._log(f"请求失败: {e} -> {url}")
            return ""

    def _fix_url(self, url):
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return parse.urljoin(self.host, url)
        if not url.startswith("http"):
            return parse.urljoin(self.host, url)
        return url

    def _clean(self, text):
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'&nbsp;', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()

    # ---------- 首页 ----------
    def homeContent(self, filter=False):
        # 尝试从首页侧边栏动态获取分类
        try:
            html = self._fetch(self.host)
            if html:
                classes = []
                # 匹配侧边栏分类链接
                for m in re.finditer(r'<a href="/list/(\d+)\.html"[^>]*>([^<]+)</a>', html):
                    tid = m.group(1)
                    name = self._clean(m.group(2))
                    if name and name not in ["首页", "动漫明星", "动漫资讯", "动漫合集", "动漫榜单️", "最近更新", "即将上映", "求片留言", "地址发布页"]:
                        classes.append({"type_id": tid, "type_name": name})
                if classes:
                    return {"class": classes}
        except:
            pass
        # 兜底硬编码
        return {"class": [{"type_id": k, "type_name": v} for k, v in self.class_map.items()]}

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter=False, extend=None):
        pg = int(pg) if pg else 1
        # 尝试两种分页格式：/list/{tid}-{pg}.html  和 /list/{tid}.html?page={pg}
        if pg == 1:
            url = f"{self.host}/list/{tid}.html"
        else:
            url = f"{self.host}/list/{tid}-{pg}.html"
        html = self._fetch(url)
        if not html or "404" in html:
            # 备选格式
            url = f"{self.host}/list/{tid}.html?page={pg}" if pg > 1 else f"{self.host}/list/{tid}.html"
            html = self._fetch(url)
        videos = self._parse_video_list(html)
        # 计算总页数（从分页链接提取）
        pagecount = self._extract_page_count(html) or 999
        return {
            "list": videos,
            "page": pg,
            "pagecount": pagecount,
            "limit": 24,
            "total": pagecount * 24
        }

    def _parse_video_list(self, html):
        videos = []
        if not html:
            return videos
        # 匹配 li.list-item 中的卡片（主卡片与精简卡片兼容）
        # 模式1：带图片的主卡片
        pattern1 = r'<li[^>]*class="[^"]*list-item[^"]*"[^>]*>.*?<a[^>]*href="(/detail/(\d+)\.html)"[^>]*>.*?<img[^>]*data-src="([^"]+)"[^>]*>.*?<h3[^>]*>.*?<a[^>]*>([^<]+)</a>.*?<span[^>]*class="[^"]*position-absolute[^"]*"[^>]*>([^<]+)</span>'
        for m in re.finditer(pattern1, html, re.S):
            href = m.group(1)
            vid = m.group(2)
            pic = self._fix_url(m.group(3))
            name = self._clean(m.group(4))
            remark = self._clean(m.group(5))
            videos.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remark
            })
        # 如果没匹配到，尝试精简卡片（底部列表）
        if not videos:
            pattern2 = r'<a[^>]*href="(/detail/(\d+)\.html)"[^>]*>.*?<span[^>]*class="[^"]*text-yes[^"]*"[^>]*>([^<]+)</span>.*?<p[^>]*>([^<]+)</p>'
            for m in re.finditer(pattern2, html, re.S):
                videos.append({
                    "vod_id": m.group(2),
                    "vod_name": self._clean(m.group(3)),
                    "vod_pic": "",
                    "vod_remarks": self._clean(m.group(4))
                })
        return videos

    def _extract_page_count(self, html):
        # 从分页“尾页”或数字链接提取最大页码
        m = re.search(r'<a[^>]*href="[^"]*?/list/\d+-(\d+)\.html"[^>]*>[^<]*尾页', html)
        if m:
            return int(m.group(1))
        # 取所有页码数字
        nums = re.findall(r'/list/\d+-(\d+)\.html', html)
        if nums:
            return max(int(n) for n in nums)
        return 1

    # ---------- 详情 ----------
    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else ids
        if not vid.isdigit():
            # 如果传入的是完整路径，提取数字
            m = re.search(r'/(\d+)\.html', vid)
            if m:
                vid = m.group(1)
        url = f"{self.host}/detail/{vid}.html"
        html = self._fetch(url)
        if not html:
            return {"list": []}

        # 提取标题
        name = ""
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if m:
            name = self._clean(m.group(1))
        if not name:
            m = re.search(r'<title>([^<]+)</title>', html)
            if m:
                name = self._clean(m.group(1)).replace("第一动漫网", "").strip()

        # 提取封面
        pic = ""
        m = re.search(r'<img[^>]*data-src="([^"]+)"[^>]*class="[^"]*poster[^"]*"', html)
        if not m:
            m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if m:
            pic = self._fix_url(m.group(1))

        # 提取简介
        content = ""
        m = re.search(r'<meta name="description" content="([^"]+)"', html)
        if m:
            content = self._clean(m.group(1))

        # ---------- 关键：提取播放源和剧集 ----------
        play_sources = []      # 源名称列表
        play_urls = []         # 对应源剧集字符串

        # 方法1：匹配标准苹果CMS播放块（包含播放源标签和剧集链接）
        # 查找所有播放面板（通常有 class="playlist" 或 "module-play-list"）
        # 先获取所有源名（tab标题）
        source_tabs = re.findall(r'<a[^>]*data-toggle="tab"[^>]*data-target="#playlist(\d+)"[^>]*>([^<]+)</a>', html)
        # 查找所有剧集块
        playlist_blocks = re.findall(r'<div[^>]*id="playlist(\d+)"[^>]*>.*?<ul[^>]*>([\s\S]*?)</ul>', html, re.S)
        if source_tabs and playlist_blocks:
            # 构建映射
            tabs_dict = {pid: name for pid, name in source_tabs}
            for pid, block in playlist_blocks:
                src_name = tabs_dict.get(pid, f"线路{pid}")
                eps = []
                # 匹配剧集链接
                for ep in re.finditer(r'<a[^>]*href="(/play/[^"]+)"[^>]*>([^<]+)</a>', block, re.S):
                    ep_url = self._fix_url(ep.group(1))
                    ep_name = self._clean(ep.group(2))
                    if ep_name and ep_url:
                        eps.append(f"{ep_name}${ep_url}")
                if eps:
                    play_sources.append(src_name)
                    play_urls.append("#".join(eps))

        # 如果方法1未提取到，尝试方法2：直接从页面中收集所有 /play/ 链接（不分源）
        if not play_sources:
            eps = []
            for m in re.finditer(r'<a[^>]*href="(/play/[^"]+)"[^>]*>([^<]+)</a>', html, re.S):
                ep_url = self._fix_url(m.group(1))
                ep_name = self._clean(m.group(2))
                if ep_name and ep_url:
                    eps.append(f"{ep_name}${ep_url}")
            if eps:
                play_sources.append("默认源")
                play_urls.append("#".join(eps))

        # 如果还是没有，尝试提取iframe或video（可能详情页内嵌播放）
        if not play_sources:
            # 查找iframe
            iframe = re.search(r'<iframe[^>]*src="([^"]+)"', html)
            if iframe:
                iframe_url = self._fix_url(iframe.group(1))
                play_sources.append("播放")
                play_urls.append(f"播放${iframe_url}")
            else:
                # 查找video
                video = re.search(r'<video[^>]*src="([^"]+)"', html)
                if video:
                    video_url = self._fix_url(video.group(1))
                    play_sources.append("播放")
                    play_urls.append(f"播放${video_url}")

        # 最终兜底：将详情页URL作为播放源（让playerContent嗅探）
        if not play_sources:
            play_sources.append("详情页")
            play_urls.append(f"播放${url}")

        # 组合
        vod = {
            "vod_id": vid,
            "vod_name": name or "未知",
            "vod_pic": pic,
            "vod_content": content,
            "vod_play_from": "$$$".join(play_sources),
            "vod_play_url": "$$$".join(play_urls)
        }
        self._log(f"详情提取成功：源数={len(play_sources)}，剧集数={sum(len(u.split('#')) for u in play_urls)}")
        return {"list": [vod]}

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None):
        # id可能包含$分割？但我们的detailContent已经组装为 剧名$url，所以直接取url部分
        # 如果id包含$，取最后一部分
        if "$" in id:
            parts = id.split("$")
            if len(parts) > 1:
                id = parts[-1]
        # 如果id不是http开头，补全
        if not id.startswith("http"):
            id = self._fix_url(id)

        self._log(f"playerContent 开始解析: {id}")
        html = self._fetch(id)
        if not html:
            return {"parse": 0, "url": id, "header": self.headers}

        # 1. 提取 player_aaaa
        m = re.search(r'var\s+player_aaaa\s*=\s*({.*?})\s*;', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                real_url = data.get("url", "")
                if real_url:
                    real_url = self._fix_url(real_url)
                    self._log(f"player_aaaa 提取到: {real_url}")
                    return {"parse": 0, "url": real_url, "header": {"Referer": id, "User-Agent": self.headers["User-Agent"]}}
            except Exception as e:
                self._log(f"player_aaaa解析失败: {e}")

        # 2. 提取 var now
        m = re.search(r'var\s+now\s*=\s*["\']([^"\']+)["\']', html)
        if m:
            real_url = self._fix_url(m.group(1))
            self._log(f"var now 提取到: {real_url}")
            return {"parse": 0, "url": real_url, "header": {"Referer": id, "User-Agent": self.headers["User-Agent"]}}

        # 3. 提取 player_data
        m = re.search(r'player_data\s*=\s*({.*?})\s*;', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                real_url = data.get("url", "")
                if real_url:
                    real_url = self._fix_url(real_url)
                    self._log(f"player_data 提取到: {real_url}")
                    return {"parse": 0, "url": real_url, "header": {"Referer": id, "User-Agent": self.headers["User-Agent"]}}
            except Exception as e:
                self._log(f"player_data解析失败: {e}")

        # 4. 直接匹配m3u8/mp4
        m = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', html)
        if m:
            real_url = self._fix_url(m.group(1))
            self._log(f"直链m3u8: {real_url}")
            return {"parse": 0, "url": real_url, "header": {"Referer": id, "User-Agent": self.headers["User-Agent"]}}
        m = re.search(r'(https?://[^\s"\']+\.mp4[^\s"\']*)', html)
        if m:
            real_url = self._fix_url(m.group(1))
            self._log(f"直链mp4: {real_url}")
            return {"parse": 0, "url": real_url, "header": {"Referer": id, "User-Agent": self.headers["User-Agent"]}}

        # 5. 尝试iframe递归
        m = re.search(r'<iframe[^>]*src="([^"]+)"', html)
        if m:
            iframe_url = self._fix_url(m.group(1))
            self._log(f"iframe嵌套: {iframe_url}")
            # 递归解析iframe内容
            iframe_html = self._fetch(iframe_url)
            if iframe_html:
                # 再尝试提取
                return self.playerContent("", iframe_url, None)  # 递归调用
            return {"parse": 0, "url": iframe_url, "header": {"Referer": id, "User-Agent": self.headers["User-Agent"]}}

        # 6. 都失败，返回原链接让TVBox自行处理
        self._log("未提取到有效播放地址，返回原始链接")
        return {"parse": 1, "url": id, "header": self.headers}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick=False, pg="1"):
        pg = int(pg) if pg else 1
        url = f"{self.host}/search/FFWD-------------.html?wd={parse.quote(key)}"
        html = self._fetch(url)
        videos = self._parse_video_list(html)
        return {"list": videos, "page": pg, "pagecount": 1, "limit": 24, "total": len(videos)}

    # ---------- 辅助（可选） ----------
    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|ts)(\?|$)', url or "", re.I))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return [200, "text/plain", b"not used"]

    def destroy(self):
        pass