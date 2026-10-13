# 黄瓜短剧 | OK影视专用爬虫插件 | 基于base.spider
import sys
import re
import json
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
requests.packages.urllib3.disable_warnings()

from base.spider import Spider

class Spider(Spider):
    def getName(self):
        return "黄瓜短剧"

    def init(self, extend=""):
        super().init(extend)
        self.site_url = "https://hgdju.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Referer": self.site_url
        }
        self.sess = requests.Session()
        self.sess.headers.update(self.headers)
        self.sess.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])))
        self.sess.mount("http://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])))
        self.page_size = 24
        self.total = 9999

    def fetch(self, url, timeout=15):
        try:
            res = self.sess.get(url, timeout=timeout, verify=False)
            res.encoding = "utf-8"
            if res.status_code == 200:
                return res
            else:
                return None
        except Exception as e:
            return None

    def homeContent(self, filter):
        cate_list = [
            {"type_name": "全部短剧", "type_id": "all"},
            {"type_name": "魔改短剧", "type_id": "mogai"},
            {"type_name": "真人短剧", "type_id": "zhenren"},
            {"type_name": "AI短剧", "type_id": "aiduanju"}
        ]
        return {"class": cate_list}

    def _extract_cover_image(self, html_content):
        """专门提取封面图片URL"""
        if not html_content:
            return ""
        
        # 专门匹配 /static/covers/ 路径的图片
        cover_patterns = [
            r'["\']([^"\']*static/covers/[^"\']+)["\']',
            r'["\']([^"\']*covers/[^"\']+\.jpg[^"\']*)["\']',
            r'["\']([^"\']*covers/[^"\']+\.png[^"\']*)["\']',
            r'["\']([^"\']*covers/[^"\']+\.webp[^"\']*)["\']'
        ]
        
        for pattern in cover_patterns:
            match = re.search(pattern, html_content, re.I)
            if match:
                img_url = match.group(1).strip()
                # 处理URL
                if img_url.startswith('//'):
                    return 'https:' + img_url
                elif img_url.startswith('/'):
                    return self.site_url + img_url
                elif img_url.startswith('http://'):
                    return img_url.replace('http://', 'https://', 1)
                elif img_url.startswith('https://'):
                    return img_url
                else:
                    return self.site_url + '/' + img_url.lstrip('/')
        
        return ""

    def _parse_cards(self, html):
        """通用卡片解析：提取视频信息"""
        video_list = []
        if not html:
            return video_list
        
        # 查找所有包含视频链接的a标签，并获取完整的内容块
        link_pattern = r'<a[^>]*href=["\']([^"\']*(?:play|video|detail|watch|vod)[^"\']*)["\'][^>]*>(.*?)</a>'
        matches = re.findall(link_pattern, html, re.S)
        
        if matches:
            for link, content in matches:
                vod_id = link
                
                # 提取标题 - 改进标题提取逻辑
                vod_name = ""
                
                # 1. 尝试从title属性提取
                title_match = re.search(r'title=["\']([^"\']+)["\']', content)
                if title_match:
                    vod_name = title_match.group(1).strip()
                
                # 2. 尝试从alt属性提取
                if not vod_name:
                    alt_match = re.search(r'alt=["\']([^"\']+)["\']', content)
                    if alt_match:
                        vod_name = alt_match.group(1).strip()
                
                # 3. 尝试从链接文本提取（去掉HTML标签）
                if not vod_name:
                    text_match = re.search(r'>([^<]+)<', content)
                    if text_match:
                        vod_name = text_match.group(1).strip()
                
                # 4. 尝试从图片标签的alt或title属性提取
                if not vod_name:
                    img_alt_match = re.search(r'<img[^>]*(?:alt|title)=["\']([^"\']+)["\']', content, re.I)
                    if img_alt_match:
                        vod_name = img_alt_match.group(1).strip()
                
                # 5. 如果标题还是空的，在更大的范围查找
                if not vod_name:
                    pos = html.find(vod_id)
                    if pos > 0:
                        start = max(0, pos - 1000)
                        end = min(len(html), pos + 1000)
                        nearby_html = html[start:end]
                        
                        # 查找class包含title的元素
                        class_title_match = re.search(r'class=["\'][^"\']*title[^"\']*["\'][^>]*>([^<]+)<', nearby_html, re.I)
                        if class_title_match:
                            vod_name = class_title_match.group(1).strip()
                        
                        # 查找h2/h3标签
                        if not vod_name:
                            h_tag_match = re.search(r'<h[23][^>]*>([^<]+)</h[23]>', nearby_html, re.I)
                            if h_tag_match:
                                vod_name = h_tag_match.group(1).strip()
                        
                        # 查找name类
                        if not vod_name:
                            name_match = re.search(r'class=["\'][^"\']*name[^"\']*["\'][^>]*>([^<]+)<', nearby_html, re.I)
                            if name_match:
                                vod_name = name_match.group(1).strip()
                
                # 如果还是没找到标题，跳过这个视频
                if not vod_name or vod_name == "":
                    continue
                
                # 提取图片 - 使用专门的封面提取方法
                vod_pic = self._extract_cover_image(content)
                
                # 如果从content中没找到，在链接附近查找
                if not vod_pic:
                    pos = html.find(vod_id)
                    if pos > 0:
                        # 向前向后查找更大范围
                        start = max(0, pos - 3000)
                        end = min(len(html), pos + 3000)
                        nearby_html = html[start:end]
                        vod_pic = self._extract_cover_image(nearby_html)
                
                # 提取集数信息
                vod_remarks = ""
                remark_patterns = [
                    r'class="[^"]*(?:ep|num|remark|update|score|status)[^"]*"[^>]*>([^<]+)<',
                    r'(?:更新至|全)\s*([\d]+)\s*(?:集|话|期)',
                    r'<span[^>]*>([\d]+)\s*(?:集|话|期)</span>',
                    r'([\d]+)\s*集',
                    r'全\s*([\d]+)\s*集',
                    r'更新至\s*([\d]+)\s*集'
                ]
                
                for pattern in remark_patterns:
                    remark_match = re.search(pattern, content, re.I)
                    if remark_match:
                        if remark_match.lastindex:
                            vod_remarks = f"{remark_match.group(1)}集"
                        else:
                            vod_remarks = remark_match.group(0)
                        vod_remarks = re.sub(r'集+', '集', vod_remarks)
                        break
                
                # 处理完整URL
                full_url = vod_id
                if full_url.startswith("/"):
                    full_url = self.site_url + full_url
                elif not full_url.startswith(("http://", "https://")):
                    full_url = self.site_url + "/" + full_url
                
                video_list.append({
                    "vod_id": full_url,
                    "vod_name": vod_name,
                    "vod_pic": vod_pic,
                    "vod_remarks": vod_remarks,
                    "style": {"type": "rect", "ratio": 0.75}
                })
        
        # 去重
        seen = set()
        unique_list = []
        for item in video_list:
            if item["vod_id"] not in seen:
                seen.add(item["vod_id"])
                unique_list.append(item)
        
        return unique_list

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        
        if tid == "all":
            url_patterns = [
                f"{self.site_url}/",
                f"{self.site_url}/index.html",
                f"{self.site_url}/home",
                f"{self.site_url}/all",
                f"{self.site_url}/browse",
                f"{self.site_url}/list"
            ]
        elif tid == "home":
            url_patterns = [
                f"{self.site_url}/browse?page={pg}",
                f"{self.site_url}/?page={pg}"
            ]
        else:
            url_patterns = [
                f"{self.site_url}/{tid}?page={pg}",
                f"{self.site_url}/category/{tid}?page={pg}",
                f"{self.site_url}/type/{tid}?page={pg}",
                f"{self.site_url}/{tid}/{pg}"
            ]
        
        video_list = []
        
        for url in url_patterns:
            res = self.fetch(url)
            if res and res.ok:
                temp_list = self._parse_cards(res.text)
                if temp_list:
                    video_list = temp_list
                    break
        
        # 如果没有从列表页获取到集数信息，尝试从详情页获取
        if video_list and not any(item.get("vod_remarks") for item in video_list):
            for i, video in enumerate(video_list[:5]):
                try:
                    detail_res = self.fetch(video["vod_id"])
                    if detail_res and detail_res.ok:
                        detail_html = detail_res.text
                        ep_matches = re.findall(r'第[\d]+集', detail_html)
                        if ep_matches:
                            total_eps = len(ep_matches)
                            video_list[i]["vod_remarks"] = f"全{total_eps}集"
                        else:
                            total_match = re.search(r'(?:totalEp|total_ep|total|episodes)\s*[=:]\s*["\']?(\d+)', detail_html, re.I)
                            if total_match:
                                video_list[i]["vod_remarks"] = f"全{total_match.group(1)}集"
                except Exception as e:
                    pass
        
        pagecount = pg + 1 if len(video_list) >= self.page_size else pg
        
        return {
            "list": video_list,
            "page": pg,
            "pagecount": pagecount,
            "limit": self.page_size,
            "total": self.total if video_list else 0
        }

    def detailContent(self, ids):
        vod_id = ids[0] if ids else ""
        if not vod_id:
            return {"list": [{"vod_name": "视频ID为空"}]}
        
        if not vod_id.startswith("http"):
            vod_id = self.site_url + vod_id
        
        res = self.fetch(vod_id)
        
        if res and res.ok:
            html = res.text
            
            # 提取标题
            title = ""
            title_patterns = [
                r'<title>([^<]+)</title>',
                r'<h1[^>]*>([^<]+)</h1>',
                r'class="[^"]*title[^"]*"[^>]*>([^<]+)<',
                r'<meta[^>]*property="og:title"[^>]*content=["\']([^"\']+)["\']'
            ]
            for pattern in title_patterns:
                m = re.search(pattern, html, re.I)
                if m:
                    title = m.group(1).strip()
                    if title:
                        break
            
            # 提取播放地址
            play_urls = []
            
            # 查找JSON数据中的播放地址
            json_patterns = [
                r'window\.HG_PLAY\s*=\s*(\{.*?\});',
                r'var\s+HG_PLAY\s*=\s*(\{.*?\});',
                r'const\s+HG_PLAY\s*=\s*(\{.*?\});',
                r'window\.player\s*=\s*(\{.*?\});',
                r'var\s+player\s*=\s*(\{.*?\});',
                r'window\.playData\s*=\s*(\{.*?\});',
                r'var\s+playData\s*=\s*(\{.*?\});'
            ]
            
            for pattern in json_patterns:
                json_match = re.search(pattern, html, re.S)
                if json_match:
                    try:
                        data = json.loads(json_match.group(1))
                        
                        def extract_urls(obj):
                            urls = []
                            if isinstance(obj, dict):
                                for key, value in obj.items():
                                    if isinstance(value, str) and ('m3u8' in value or 'mp4' in value):
                                        urls.append(value)
                                    else:
                                        urls.extend(extract_urls(value))
                            elif isinstance(obj, list):
                                for item in obj:
                                    urls.extend(extract_urls(item))
                            return urls
                        
                        urls = extract_urls(data)
                        if urls:
                            play_urls.extend(urls)
                            break
                    except Exception as e:
                        pass
            
            # 查找m3u8和mp4链接
            if not play_urls:
                m3u8_matches = re.findall(r'["\']([^"\']*\.m3u8[^"\']*)["\']', html)
                play_urls.extend(m3u8_matches)
                
                if not play_urls:
                    mp4_matches = re.findall(r'["\']([^"\']*\.mp4[^"\']*)["\']', html)
                    play_urls.extend(mp4_matches)
            
            # 处理播放地址
            processed_urls = []
            for url in play_urls:
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = self.site_url + url
                elif url.startswith("http://"):
                    url = url.replace("http://", "https://")
                
                if url not in processed_urls:
                    processed_urls.append(url)
            
            # 构造播放列表
            if processed_urls:
                play_list = []
                for i, url in enumerate(processed_urls):
                    play_list.append(f"第{i+1}集${url}")
                play_url = "#".join(play_list)
            else:
                play_url = ""
            
            # 提取图片 - 使用专门的封面提取方法
            vod_pic = self._extract_cover_image(html)
            
            # 确定集数信息
            total_eps = len(processed_urls)
            if total_eps > 0:
                vod_remarks = f"全{total_eps}集"
            else:
                total_match = re.search(r'(?:totalEp|total_ep|total|episodes)\s*[=:]\s*["\']?(\d+)', html, re.I)
                if total_match:
                    vod_remarks = f"全{total_match.group(1)}集"
                else:
                    vod_remarks = ""
            
            return {
                "list": [{
                    "vod_id": vod_id,
                    "vod_name": title or "未知名称",
                    "vod_pic": vod_pic,
                    "vod_remarks": vod_remarks,
                    "type_name": "短剧",
                    "vod_play_from": "主线路",
                    "vod_play_url": play_url
                }]
            }
        
        return {"list": [{"vod_id": vod_id, "vod_name": "视频详情解析失败"}]}

    def searchContent(self, key, quick, pg=1):
        pg = int(pg) if str(pg).isdigit() else 1
        
        search_urls = [
            f"{self.site_url}/search?q={requests.utils.quote(key)}&page={pg}",
            f"{self.site_url}/search?keyword={requests.utils.quote(key)}&page={pg}",
            f"{self.site_url}/so?q={requests.utils.quote(key)}&page={pg}"
        ]
        
        video_list = []
        
        for search_url in search_urls:
            res = self.fetch(search_url)
            if res and res.ok:
                temp_list = self._parse_cards(res.text)
                if temp_list:
                    video_list = temp_list
                    break
        
        pagecount = pg + 1 if len(video_list) >= self.page_size else pg
        
        return {
            "list": video_list,
            "page": pg,
            "pagecount": pagecount,
            "limit": self.page_size,
            "total": len(video_list) if video_list else 0
        }

    def playerContent(self, flag, id, vipFlags):
        if "$" in id:
            parts = id.split("$")
            play_url = parts[1] if len(parts) > 1 else ""
        else:
            play_url = id
        
        if not play_url:
            return {"parse": 0, "url": "", "header": self.headers}
        
        if play_url.startswith("//"):
            play_url = "https:" + play_url
        elif play_url.startswith("/"):
            play_url = self.site_url + play_url
        elif play_url.startswith("http://"):
            play_url = play_url.replace("http://", "https://")
        
        if '.m3u8' in play_url or '.mp4' in play_url:
            play_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Origin": self.site_url,
                "Referer": self.site_url
            }
            
            return {
                "parse": 0,
                "url": play_url,
                "header": play_headers
            }
        else:
            return {
                "parse": 1,
                "url": play_url,
                "header": self.headers
            }