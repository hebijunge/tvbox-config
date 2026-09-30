import sys
import json
import re
from urllib.parse import quote, unquote

# 依赖 requests 库处理网络请求
import requests

# 引入 TVBox Python 爬虫基础类
sys.path.append('..')
from base.spider import Spider



## 自营4k60帧 mujizybf08.com  不能直连
class Spider(Spider):
    HOST = "https://4k01.pianku.online"
    PARSE_API_URL = "https://svip.qlplayer.cyou/?url="
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    HEADERS = {
        "User-Agent": UA,
        "Referer": HOST
    }

    def getName(self):
        return "片库网"

    def mylog(self, *args):
        """日志打印封装，便于在日志面板快速定位"""
        msg = " ".join([str(arg) for arg in args])
        print(f"[{self.getName()}] {msg}")

    def init(self, extend=""):
        self.mylog("Spider Init Done")

    def build_url(self, path):
        if not path:
            return ""
        if path.startswith("http"):
            return path
        return self.HOST + ("" if path.startswith("/") else "/") + path

    def fetch(self, url, headers=None):
        """网络请求封装"""
        try:
            req_headers = self.HEADERS.copy()
            if headers:
                req_headers.update(headers)
            res = requests.get(url, headers=req_headers, timeout=10)
            res.encoding = 'utf-8'
            return res.text
        except Exception as e:
            self.mylog(f"请求失败 [{url}]: {str(e)}")
            return ""

    def get_vod_list(self, html):
        """从 HTML 中提取视频列表"""
        if not html:
            return []
        vod_list = []
        regex = r'<div class="vod-item">[\s\S]*?<a href="\/voddetail\/(\d+)\.html" title="(.*?)"[\s\S]*?<img src="(.*?)"[\s\S]*?<span class="remarks">(.*?)<\/span>'
        matches = re.findall(regex, html)
        for match in matches:
            vod_list.append({
                "vod_id": match[0],
                "vod_name": match[1],
                "vod_pic": self.build_url(match[2]),
                "vod_remarks": match[3].strip()
            })
        self.mylog(f"共提取到 {len(vod_list)} 条数据")
        return vod_list

    def homeContent(self, filter):
        self.mylog(f"开始加载首页，filter={filter}")
        classes = [
            {"type_id": "20", "type_name": "电影"},
            {"type_id": "37", "type_name": "剧集"},
            {"type_id": "43", "type_name": "动漫"},
            {"type_id": "45", "type_name": "综艺"}
        ]

        filters = {
            "20": [{
                "key": "tid",
                "name": "分类",
                "value": [
                    {"n": "全部", "v": "20"}, {"n": "动作片", "v": "21"}, {"n": "喜剧片", "v": "22"},
                    {"n": "爱情片", "v": "23"}, {"n": "科幻片", "v": "24"}, {"n": "恐怖片", "v": "25"},
                    {"n": "剧情片", "v": "26"}, {"n": "战争片", "v": "27"}, {"n": "惊悚片", "v": "28"},
                    {"n": "犯罪片", "v": "29"}, {"n": "冒险篇", "v": "30"}, {"n": "动画片", "v": "31"},
                    {"n": "悬疑片", "v": "32"}, {"n": "武侠片", "v": "33"}, {"n": "奇幻片", "v": "34"},
                    {"n": "纪录片", "v": "35"}, {"n": "其他片", "v": "36"}
                ]
            }]
        }

        try:
            html = self.fetch(self.HOST)
            vod_list = self.get_vod_list(html)

            result = {
                "class": classes,
                "list": vod_list
            }
            if filter:
                result["filters"] = filters

            return result
        except Exception as e:
            self.mylog(f"homeContent 异常: {str(e)}")
            return {"class": [], "list": []}

    def homeVideoContent(self):
        """首页推荐视频"""
        self.mylog("获取首页推荐视频")
        try:
            html = self.fetch(self.HOST)
            vod_list = self.get_vod_list(html)
            return {"list": vod_list}
        except Exception as e:
            self.mylog(f"homeVideoContent 异常: {str(e)}")
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        real_tid = extend.get("tid", tid) if extend else tid
        page = str(pg) if pg else "1"
        url = f"{self.HOST}/vodtype/{real_tid}.html" if page == "1" else f"{self.HOST}/vodtype/{real_tid}-{page}.html"

        self.mylog(f"请求分类 URL: {url}")
        try:
            html = self.fetch(url)
            vod_list = self.get_vod_list(html)

            pagecount = int(page) + 1
            total = 0
            page_match = re.search(r'尾页.*?href=".*?-(\d+)\.html"', html)
            if page_match:
                pagecount = int(page_match.group(1))
                total = pagecount * 24

            return {
                "list": vod_list,
                "page": int(page),
                "pagecount": pagecount,
                "limit": 24,
                "total": total
            }
        except Exception as e:
            self.mylog(f"categoryContent 异常: {str(e)}")
            return {"list": [], "page": 1, "pagecount": 1, "limit": 24, "total": 0}

    def detailContent(self, array):
        id = array[0]
        url = f"{self.HOST}/voddetail/{id}.html"
        self.mylog(f"获取详情页 URL: {url}")

        try:
            html = self.fetch(url)
            if not html:
                return {"list": []}

            # 获取基础文本信息
            title_match = re.search(r'<h1[^>]*class="detail-title"[^>]*>(.*?)(?:<span|</h1)', html, re.S)
            title = title_match.group(1).strip() if title_match else ""

            pic_match = re.search(r'class="detail-poster"[^>]*>[\s\S]*?<img src="(.*?)"', html)
            pic = self.build_url(pic_match.group(1)) if pic_match else ""

            remarks_match = re.search(r'class="detail-remarks"[^>]*>(.*?)<\/span>', html)
            remarks = remarks_match.group(1).strip() if remarks_match else ""

            content_match = re.search(r'class="detail-desc"[^>]*>[\s\S]*?<p>(.*?)</p>', html, re.S)
            content = content_match.group(1).strip() if content_match else ""

            # 提取导演、主演、地区、年份
            director, actor, area, year = "", "", "", ""
            meta_matches = re.findall(r'<(?:span|p|div)[^>]*>(?:导演|主演|地区|年份)[：:](.*?)(?:<\/span>|<\/p>|<\/div>)', html)
            meta_full = re.findall(r'<(?:span|p|div)[^>]*>((?:导演|主演|地区|年份))[：:]', html)
            
            for key, val in zip(meta_full, meta_matches):
                val = val.strip()
                if "导演" in key:
                    director = val
                elif "主演" in key:
                    actor = val
                elif "地区" in key:
                    area = val
                elif "年份" in key:
                    year = val

            # 提取播放线路
            play_from_list = re.findall(r'class="source-tab-item[^"]*"[^>]*>(.*?)<\/span>', html)
            
            # 过滤并替换线路名称（针对自营4k60帧添加直连提醒与特殊符号）
            processed_play_from = []
            for item in play_from_list:
                name = item.strip()
                if "自营4K60帧" in name:
                    processed_play_from.append(f"⚡ {name}（注意直连）")
                else:
                    processed_play_from.append(name)
            play_from_list = processed_play_from

            # 提取播放剧集列表
            play_url_list = []
            pane_matches = re.findall(r'<div[^>]*class="source-pane[^"]*"[^>]*>([\s\S]*?)<\/div>\s*(?=<div[^>]*class="source-pane|<\/section|<\/div>)', html)

            for pane_html in pane_matches:
                episodes = []
                ep_matches = re.findall(r'href="(\/vodplay\/[^"]+)"[^>]*>(.*?)<\/a>', pane_html)
                for ep_url, ep_name in ep_matches:
                    clean_name = re.sub(r'<[^>]+>', '', ep_name).strip()
                    full_ep_url = self.build_url(ep_url)
                    episodes.append(f"{clean_name}${full_ep_url}")
                if episodes:
                    play_url_list.append("#".join(episodes))

            # 补全线路
            if not play_from_list and play_url_list:
                play_from_list = [f"线路 {i+1}" for i in range(len(play_url_list))]

            vod = {
                "vod_id": id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_type_name": "",
                "vod_year": year,
                "vod_area": area,
                "vod_remarks": remarks,
                "vod_actor": actor,
                "vod_director": director,
                "vod_content": content,
                "vod_play_from": "$$$".join(play_from_list),
                "vod_play_url": "$$$".join(play_url_list)
            }

            self.mylog(f"成功解析视频详情: {title}")
            return {"list": [vod]}
        except Exception as e:
            self.mylog(f"detailContent 异常: {str(e)}")
            return {"list": []}
    def searchContent(self, key, quick, pg="1"):
        encoded_key = quote(key)
        url = f"{self.HOST}/vodsearch/-------------.html?wd={encoded_key}"
        self.mylog(f"开始搜索关键词: {key} -> URL: {url}")

        try:
            html = self.fetch(url)
            vod_list = self.get_vod_list(html)

            return {
                "list": vod_list,
                "page": 1,
                "pagecount": 1
            }
        except Exception as e:
            self.mylog(f"searchContent 异常: {str(e)}")
            return {"list": []}

    def parse_video_url(self, url):
        """二次解析视频真实的播放地址"""
        try:
            resolve_url = self.PARSE_API_URL + url
            self.mylog("解析地址", resolve_url)

            html1 = self.fetch(resolve_url)
            api_token_match = re.search(r'apiToken\s*:\s*["\']([^"\']+)["\']', html1)
            api_token = api_token_match.group(1) if api_token_match else None

            if not api_token:
                return ""

            parse_token_url = f"https://svip.qlplayer.cyou/api/resolve.php?token={quote(api_token)}"
            self.mylog("parseTTokenUrl", parse_token_url)

            data_str = self.fetch(parse_token_url)
            data = json.loads(data_str)

            self.mylog("data", data)
            raw_url = data.get("url", "")
            # 格式化 URL
            final_url = raw_url.replace("\\", "")
            final_url = re.sub(r'^(https?:/)((?!/))', r'\1/', final_url, flags=re.I)

            self.mylog("finalUrl", final_url)
            return final_url
        except Exception as e:
            self.mylog(f"视频解析失败: {str(e)}")
            return ""

    def playerContent(self, flag, id, vipFlags):
        play_url = self.build_url(id)
        self.mylog(f"开始获取播放地址: {play_url}")

        try:
            html = self.fetch(play_url)
            # 匹配 player_aaaa 后面的 JSON 对象
            match = re.search(r'player_aaaa\s*=\s*(\{[\s\S]*?\})', html)

            if match:
                json_string = match.group(1)
                player_data = json.loads(json_string)
                target_url = player_data.get("url", "")
                final_play_url = self.parse_video_url(target_url)

                return {
                    "parse": 0,
                    "url": final_play_url
                }
            else:
                self.mylog("未在网页 HTML 中找到 player_aaaa 匹配项")
        except Exception as e:
            self.mylog(f"网络请求失败: {str(e)}")

        return {"parse": 0, "url": ""}

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass