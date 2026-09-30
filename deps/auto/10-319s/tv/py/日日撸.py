# -*- coding: utf-8 -*-
import json
import re
import sys
import urllib.parse
from bs4 import BeautifulSoup
import requests

# 导入基类（兼容 CatVod / TVBox 蜘蛛框架）
try:
    from base.spider import Spider
except ImportError:

    class Spider:
        pass


class Spider(Spider):
    site_url = "https://ririlu.cc"
    
    # 模拟移动端用户代理（响应 JSON 规则中的“请求头参数: 手机”）
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
        )
    }

    def getName(self):
        return "日日撸"

    def init(self, extend=""):
        pass

    def isVideo(self, url):
        pass

    def destroy(self):
        pass

    # 分类列表 & 筛选数据定义
    def homeContent(self, filter):
        result = {}
        classes = [
            {"type_name": "中文字幕", "type_id": "/vodshow/28"},
            {"type_name": "国产", "type_id": "/vodshow/20"},
            {"type_name": "日本有码", "type_id": "/vodshow/21"},
            {"type_name": "日本无码", "type_id": "/vodshow/22"},
            {"type_name": "欧美", "type_id": "/vodshow/23"},
            {"type_name": "动漫", "type_id": "/vodshow/24"},
            {"type_name": "伦理", "type_id": "/vodshow/25"},
            {"type_name": "韩国", "type_id": "/vodshow/36"},
            {"type_name": "另类", "type_id": "/vodshow/41"},
        ]
        result["class"] = classes

        # 配置筛选数据 (Filters)
        if filter:
            result["filters"] = {
                "/vodshow/28": [
                    {
                        "key": "cateId",
                        "name": "分类",
                        "value": [
                            {"n": "全部", "v": "/vodshow/28"},
                            {"n": "日本中字", "v": "/vodshow/51"},
                        ],
                    },
                    {
                        "key": "by",
                        "name": "排序",
                        "value": [
                            {"n": "最新", "v": "time"},
                            {"n": "热门", "v": "hits_week"},
                        ],
                    },
                ],
                "/vodshow/20": [
                    {
                        "key": "cateId",
                        "name": "分类",
                        "value": [
                            {"n": "全部", "v": "/vodshow/20"},
                            {"n": "国产精品", "v": "/vodshow/26"},
                            {"n": "国产剧情", "v": "/vodshow/27"},
                            {"n": "国产自拍", "v": "/vodshow/29"},
                            {"n": "国产主播", "v": "/vodshow/35"},
                            {"n": "国模私拍", "v": "/vodshow/85"},
                            {"n": "网红明星", "v": "/vodshow/91"},
                            {"n": "国产SM", "v": "/vodshow/105"},
                            {"n": "台湾辣妹", "v": "/vodshow/107"},
                            {"n": "香港正妹", "v": "/vodshow/108"},
                        ],
                    },
                    {
                        "key": "by",
                        "name": "排序",
                        "value": [
                            {"n": "最新", "v": "time"},
                            {"n": "热门", "v": "hits_week"},
                        ],
                    },
                ],
                "/vodshow/21": [
                    {
                        "key": "cateId",
                        "name": "分类",
                        "value": [
                            {"n": "全部", "v": "/vodshow/21"},
                            {"n": "人妻", "v": "/vodshow/31"},
                            {"n": "素人", "v": "/vodshow/44"},
                            {"n": "口爆颜射", "v": "/vodshow/46"},
                            {"n": "萝莉少女", "v": "/vodshow/47"},
                            {"n": "美乳巨乳", "v": "/vodshow/48"},
                            {"n": "制服诱惑", "v": "/vodshow/52"},
                            {"n": "调教", "v": "/vodshow/57"},
                            {"n": "出轨", "v": "/vodshow/58"},
                            {"n": "有码精品", "v": "/vodshow/101"},
                        ],
                    },
                    {
                        "key": "by",
                        "name": "排序",
                        "value": [
                            {"n": "最新", "v": "time"},
                            {"n": "热门", "v": "hits_week"},
                        ],
                    },
                ],
                "/vodshow/22": [
                    {
                        "key": "cateId",
                        "name": "分类",
                        "value": [
                            {"n": "全部", "v": "/vodshow/22"},
                            {"n": "无码精品", "v": "/vodshow/102"},
                        ],
                    },
                    {
                        "key": "by",
                        "name": "排序",
                        "value": [
                            {"n": "最新", "v": "time"},
                            {"n": "热门", "v": "hits_week"},
                        ],
                    },
                ],
                "/vodshow/23": [
                    {
                        "key": "cateId",
                        "name": "分类",
                        "value": [
                            {"n": "全部", "v": "/vodshow/23"},
                            {"n": "欧美精品", "v": "/vodshow/104"},
                        ],
                    },
                    {
                        "key": "by",
                        "name": "排序",
                        "value": [
                            {"n": "最新", "v": "time"},
                            {"n": "热门", "v": "hits_week"},
                        ],
                    },
                ],
                "/vodshow/24": [
                    {
                        "key": "cateId",
                        "name": "分类",
                        "value": [
                            {"n": "全部", "v": "/vodshow/24"},
                            {"n": "动漫精品", "v": "/vodshow/103"},
                        ],
                    },
                    {
                        "key": "by",
                        "name": "排序",
                        "value": [
                            {"n": "最新", "v": "time"},
                            {"n": "热门", "v": "hits_week"},
                        ],
                    },
                ],
                "/vodshow/25": [
                    {
                        "key": "cateId",
                        "name": "分类",
                        "value": [
                            {"n": "全部", "v": "/vodshow/25"},
                            {"n": "综合三级", "v": "/vodshow/39"},
                        ],
                    },
                    {
                        "key": "by",
                        "name": "排序",
                        "value": [
                            {"n": "最新", "v": "time"},
                            {"n": "热门", "v": "hits_week"},
                        ],
                    },
                ],
                "/vodshow/36": [
                    {
                        "key": "cateId",
                        "name": "分类",
                        "value": [
                            {"n": "全部", "v": "/vodshow/36"},
                            {"n": "韩国主播", "v": "/vodshow/37"},
                        ],
                    },
                    {
                        "key": "by",
                        "name": "排序",
                        "value": [
                            {"n": "最新", "v": "time"},
                            {"n": "热门", "v": "hits_week"},
                        ],
                    },
                ],
                "/vodshow/41": [
                    {
                        "key": "cateId",
                        "name": "分类",
                        "value": [
                            {"n": "全部", "v": "/vodshow/41"},
                            {"n": "Cosplay", "v": "/vodshow/106"},
                        ],
                    },
                    {
                        "key": "by",
                        "name": "排序",
                        "value": [
                            {"n": "最新", "v": "time"},
                            {"n": "热门", "v": "hits_week"},
                        ],
                    },
                ],
            }
        return result

    # 首页推荐数据
    def homeVideoContent(self):
        result = {"list": []}
        try:
            url = f"{self.site_url}/label/rank/"
            res = requests.get(url, headers=self.headers, timeout=10)
            res.encoding = "utf-8"
            soup = BeautifulSoup(res.text, "html.parser")

            items = soup.select(".list-content a")
            videos = []
            for item in items:
                href = item.get("href", "")
                if not href:
                    continue

                title_el = item.select_one(".desc")
                title = title_el.get_text(strip=True) if title_el else ""

                img_el = item.select_one("img")
                pic = img_el.get("data-src") or img_el.get("src") if img_el else ""

                read_el = item.select_one(".read")
                remark = f"▶️{read_el.get_text(strip=True)}" if read_el else ""

                videos.append(
                    {
                        "vod_id": urllib.parse.urljoin(self.site_url, href),
                        "vod_name": title,
                        "vod_pic": urllib.parse.urljoin(self.site_url, pic) if pic else "",
                        "vod_remarks": remark,
                    }
                )
            result["list"] = videos
        except Exception:
            pass
        return result

    # 分类列表数据 (支持筛选与页码)
    def categoryContent(self, tid, pg, filter, extend):
        result = {
            "list": [],
            "page": pg,
            "pagecount": 999,
            "limit": 20,
            "total": 9999,
        }
        try:
            # 扩展参数处理
            cate_id = extend.get("cateId", tid) if extend else tid
            by_sort = extend.get("by", "time") if extend else "time"

            # 对应分类链接规则: https://ririlu.cc{cateId}--{by}------{catePg}---/
            url = f"{self.site_url}{cate_id}--{by_sort}------{pg}---/"
            res = requests.get(url, headers=self.headers, timeout=10)
            res.encoding = "utf-8"
            soup = BeautifulSoup(res.text, "html.parser")

            items = soup.select(".list-content a")
            videos = []
            for item in items:
                href = item.get("href", "")
                if not href:
                    continue

                title_el = item.select_one(".desc")
                title = title_el.get_text(strip=True) if title_el else ""

                img_el = item.select_one("img")
                pic = img_el.get("data-src") or img_el.get("src") if img_el else ""

                read_el = item.select_one(".read")
                remark = f"▶️{read_el.get_text(strip=True)}" if read_el else ""

                videos.append(
                    {
                        "vod_id": urllib.parse.urljoin(self.site_url, href),
                        "vod_name": title,
                        "vod_pic": urllib.parse.urljoin(self.site_url, pic) if pic else "",
                        "vod_remarks": remark,
                    }
                )
            result["list"] = videos
        except Exception:
            pass
        return result

    # 详情页数据解析
    def detailContent(self, array):
        vod_url = array[0]
        vod = {
            "vod_id": vod_url,
            "vod_name": "视频详情",
            "vod_play_from": "默认线路",
            "vod_play_url": f"正片${vod_url}",
        }
        try:
            res = requests.get(vod_url, headers=self.headers, timeout=10)
            res.encoding = "utf-8"
            soup = BeautifulSoup(res.text, "html.parser")

            # 提取标题
            title_el = soup.select_one("h1") or soup.select_one("title")
            if title_el:
                vod["vod_name"] = title_el.get_text(strip=True)

            # 提取图片
            img_el = soup.select_one('meta[property="og:image"]') or soup.select_one("img")
            if img_el:
                pic = img_el.get("content") or img_el.get("src") or ""
                vod["vod_pic"] = urllib.parse.urljoin(self.site_url, pic) if pic else ""

            # 解析线路与播放列表
            line_els = soup.select(".play-btn-group .line")
            if line_els:
                play_from_list = []
                play_url_list = []
                for idx, line in enumerate(line_els):
                    line_title_el = line.select_one("a")
                    line_title = (
                        f"📽️{line_title_el.get_text(strip=True)}📺"
                        if line_title_el
                        else f"📽️线路{idx+1}📺"
                    )

                    play_links = line.select("a")
                    url_items = []
                    for link in play_links:
                        p_name = link.get_text(strip=True)
                        p_href = link.get("href", "")
                        if p_href:
                            full_href = urllib.parse.urljoin(self.site_url, p_href)
                            url_items.append(f"{p_name}${full_href}")

                    if url_items:
                        play_from_list.append(line_title)
                        play_url_list.append("#".join(url_items))

                if play_from_list and play_url_list:
                    vod["vod_play_from"] = "$$$".join(play_from_list)
                    vod["vod_play_url"] = "$$$".join(play_url_list)

        except Exception:
            pass

        return {"list": [vod]}

    # 搜索页数据解析
    def searchContent(self, key, quick):
        result = {"list": []}
        try:
            # 根据 JSON 对应 AJAX 搜索接口: https://ririlu.cc/index.php/ajax/suggest?mid=1&wd={wd}
            url = f"{self.site_url}/index.php/ajax/suggest?mid=1&wd={urllib.parse.quote(key)}"
            res = requests.get(url, headers=self.headers, timeout=10)
            data = res.json()

            videos = []
            if "list" in data and isinstance(data["list"], list):
                for item in data["list"]:
                    v_id = item.get("id", "")
                    v_name = item.get("name", "")
                    v_pic = item.get("pic", "")

                    # JSON 中前缀: https://ririlu.cc/vodplay/ 后缀: -1-1/
                    play_href = f"{self.site_url}/vodplay/{v_id}-1-1/"

                    videos.append(
                        {
                            "vod_id": play_href,
                            "vod_name": v_name,
                            "vod_pic": urllib.parse.urljoin(self.site_url, v_pic) if v_pic else "",
                            "vod_remarks": "",
                        }
                    )
            result["list"] = videos
        except Exception:
            pass
        return result

    # 播放地址解析
    def playerContent(self, flag, id, vipFlags):
        play_header = {
            "User-Agent": self.headers["User-Agent"],
            "Referer": id,
        }
        result = {"parse": 0, "url": "", "header": play_header}

        try:
            res = requests.get(id, headers=self.headers, timeout=10)
            res.encoding = "utf-8"
            html_text = res.text

            # 抓取播放页面源码中的直链链接 (嗅探规则: .m3u8#.mp4，过滤词: baidu.com)
            m3u8_matches = re.findall(
                r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html_text
            )
            mp4_matches = re.findall(
                r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', html_text
            )

            filtered_m3u8 = [u for u in m3u8_matches if "baidu.com" not in u]
            filtered_mp4 = [u for u in mp4_matches if "baidu.com" not in u]

            video_url = None
            if filtered_m3u8:
                video_url = filtered_m3u8[0]
            elif filtered_mp4:
                video_url = filtered_mp4[0]

            if video_url:
                result["url"] = video_url
                result["parse"] = 0
            else:
                # 若未正则到直链，则开启手动嗅探或依赖客户端解析
                result["url"] = id
                result["parse"] = 1

        except Exception:
            result["url"] = id
            result["parse"] = 1

        return result

    def localProxy(self, param):
        pass
