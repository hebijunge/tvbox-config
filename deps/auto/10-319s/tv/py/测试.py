# -*- coding: utf-8 -*-
import sys
import re
import json
import urllib.parse
from bs4 import BeautifulSoup

# 导入 Spider 基类（CatVod / TVBox 蜘蛛框架标准）
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def init(self, extend=""): pass
        def homeContent(self, filter): return {}
        def homeVideoContent(self): return {}
        def categoryContent(self, tid, pg, filter, extend): return {}
        def detailContent(self, ids): return {}
        def searchContent(self, key, quick): return {}
        def playerContent(self, flag, id, vipFlags): return {}
        def isVideoFormat(self, url): return False
        def manualVideoCheck(self): return False, ""
        def localProxy(self, param): return []

class Spider(Spider):
    HOST = "https://xchina001.online"
    
    # 移动端网络请求头
    UA = "Mozilla/5.0 (Linux; Android 15; 2407FRK8EC Build/AP3A.240617.008; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.127 Mobile Safari/537.36"

    HEADERS = {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    PLAY_HEADERS = {
        "User-Agent": UA,
        "Origin": HOST,
        "Referer": HOST
    }

    def getName(self):
        return "小黄书(飞鱼)"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url

    def manualVideoCheck(self):
        return False, ""

    def _fix_pic_url(self, pic):
        """修复图片绝对路径并加上 TVBox 图片引擎请求头（破解 CDN 防盗链）"""
        if not pic:
            return ""
        
        pic = pic.strip("'\" ")

        if pic.startswith("//"):
            pic = "https:" + pic
        elif pic.startswith("/"):
            pic = self.HOST + pic
        elif not pic.startswith("http"):
            pic = self.HOST + "/" + pic

        # CatVod / TVBox 识别的图片 Request Header 拼装格式
        pic_with_header = f"{pic}#User-Agent${self.UA}#Referer${self.HOST}#Origin${self.HOST}"
        return pic_with_header

    def action_fetch(self, url, headers=None):
        """标准 HTTP GET 封装，忽略 SSL 校验"""
        if headers is None:
            headers = self.HEADERS
        try:
            import requests
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            res = requests.get(url, headers=headers, timeout=15, verify=False)
            res.encoding = 'utf-8'
            return res.text
        except Exception:
            return ""

    def homeContent(self, filter):
        result = {}
        classes = [
            {"type_name": "中文AV", "type_id": "series-63824a975d8ae"},
            {"type_name": "日本AV", "type_id": "series-6206216719462"},
            {"type_name": "模特私拍", "type_id": "series-6030196781d85"},
            {"type_name": "业余拍摄", "type_id": "series-617d3e7acdcc8"},
            {"type_name": "其他影片", "type_id": "series-60192e83c9e05"},
            {"type_name": "情色电影", "type_id": "series-61c4d9b653b6d"},
            {"type_name": "成人影片分类", "type_id": "categories"}
        ]
        
        filters = {
            "series-63824a975d8ae": [
                {"key": "cateId", "name": "厂牌", "value": [{"v": "series-63824a975d8ae", "n": "全部中文AV"}, {"v": "series-5f904550b8fcc", "n": "麻豆传媒"}, {"v": "series-5fe8403919165", "n": "蜜桃传媒"}, {"v": "series-60153c49058ce", "n": "天美传媒"}, {"v": "series-5fe840718d665", "n": "果冻传媒"}, {"v": "series-61014080dbfde", "n": "糖心Vlog"}, {"v": "series-60126bcfb97fa", "n": "精东影业"}, {"v": "series-6054e93356ded", "n": "星空传媒"}, {"v": "series-63490362dac45", "n": "性视界"}, {"v": "series-6072997559b46", "n": "杏吧原版"}, {"v": "series-64e9cce89da21", "n": "IBiZa"}, {"v": "series-6230974ada989", "n": "扣扣传媒"}, {"v": "series-6360ca9706ecb", "n": "萝莉社"}, {"v": "series-63d134c7a0a15", "n": "爱豆传媒"}, {"v": "series-61bf6e439fed6", "n": "OnlyFans"}, {"v": "series-633ef3ef07d33", "n": "SA国际传媒"}, {"v": "series-63986aec205d8", "n": "其他中文AV"}, {"v": "series-6193d27975579", "n": "葫芦影业"}, {"v": "series-637750ae0ee71", "n": "乌托邦"}, {"v": "series-63732f5c3d36b", "n": "ED"}, {"v": "series-60589daa8ff97", "n": "乐播传媒"}, {"v": "series-639c8d983b7d5", "n": "91茄子"}, {"v": "series-6405b6842705b", "n": "爱神传媒"}, {"v": "series-6248705dab604", "n": "抖阴"}, {"v": "series-64458e7da05e6", "n": "哔哩传媒"}, {"v": "series-648e1071386ef", "n": "西瓜影视"}, {"v": "series-64be8551bd0f1", "n": "思春社"}, {"v": "series-64eda52c1c3fb", "n": "YOYO"}, {"v": "series-6560dc053c99f", "n": "映秀传媒"}, {"v": "series-65bcaa9688514", "n": "大象传媒"}, {"v": "series-65e5f74e4605c", "n": "香蕉视频"}]},
                {"key": "by", "name": "排序", "value": [{"n": "按时间", "v": ""}, {"n": "观看最多", "v": "sort-read/"}, {"n": "评论最多", "v": "sort-comment/"}, {"n": "最近评论", "v": "sort-recent/"}, {"n": "时长最长", "v": "sort-length/"}]}
            ],
            "series-6206216719462": [
                {"key": "cateId", "name": "分类", "value": [{"v": "series-6206216719462", "n": "全部日本AV"}, {"v": "series-6395aba3deb74", "n": "有码AV"}, {"v": "series-6395ab7fee104", "n": "无码AV"}, {"v": "series-6608638e5fcf7", "n": "AV解说"}]},
                {"key": "by", "name": "排序", "value": [{"n": "按时间", "v": ""}, {"n": "观看最多", "v": "sort-read/"}, {"n": "评论最多", "v": "sort-comment/"}, {"n": "最近评论", "v": "sort-recent/"}, {"n": "时长最长", "v": "sort-length/"}]}
            ],
            "series-6030196781d85": [
                {"key": "cateId", "name": "分类", "value": [{"v": "series-6030196781d85", "n": "全部模特私拍"}, {"v": "series-63963186ae145", "n": "PANS视频"}, {"v": "series-63963534a9e49", "n": "其他模特私拍"}, {"v": "series-6396315ed2e49", "n": "果哥作品"}, {"v": "series-63ed0f22e9177", "n": "相约中国"}, {"v": "series-6396319e6b823", "n": "风吟鸟唱作品"}, {"v": "series-64edbeccedb2e", "n": "热舞"}]},
                {"key": "by", "name": "排序", "value": [{"n": "按时间", "v": ""}, {"n": "观看最多", "v": "sort-read/"}, {"n": "评论最多", "v": "sort-comment/"}, {"n": "最近评论", "v": "sort-recent/"}, {"n": "时长最长", "v": "sort-length/"}]}
            ],
            "series-617d3e7acdcc8": [
                {"key": "cateId", "name": "分类", "value": [{"v": "series-617d3e7acdcc8", "n": "全部业余拍摄"}, {"v": "series-63965bf7b7f51", "n": "探花现场"}, {"v": "series-63965bd5335fc", "n": "主播现场"}]},
                {"key": "by", "name": "排序", "value": [{"n": "按时间", "v": ""}, {"n": "观看最多", "v": "sort-read/"}, {"n": "评论最多", "v": "sort-comment/"}, {"n": "最近评论", "v": "sort-recent/"}, {"n": "时长最长", "v": "sort-length/"}]}
            ],
            "series-60192e83c9e05": [
                {"key": "cateId", "name": "分类", "value": [{"v": "series-60192e83c9e05", "n": "全部其他影片"}, {"v": "series-63963ea949a82", "n": "其他亚洲影片"}, {"v": "series-63963de3f2a0f", "n": "门事件"}, {"v": "series-6396404e6bdb5", "n": "其他欧美影片"}]},
                {"key": "by", "name": "排序", "value": [{"n": "按时间", "v": ""}, {"n": "观看最多", "v": "sort-read/"}, {"n": "评论最多", "v": "sort-comment/"}, {"n": "最近评论", "v": "sort-recent/"}, {"n": "时长最长", "v": "sort-length/"}]}
            ],
            "series-61c4d9b653b6d": [
                {"key": "cateId", "name": "分类", "value": [{"v": "series-61c4d9b653b6d", "n": "全部情色电影"}, {"v": "series-6396492fdb1a0", "n": "华语电影"}, {"v": "series-6396494584b57", "n": "日韩电影"}, {"v": "series-63964959ddb1b", "n": "欧美电影"}]},
                {"key": "by", "name": "排序", "value": [{"n": "按时间", "v": ""}, {"n": "观看最多", "v": "sort-read/"}, {"n": "评论最多", "v": "sort-comment/"}, {"n": "最近评论", "v": "sort-recent/"}, {"n": "时长最长", "v": "sort-length/"}]}
            ]
        }

        result['class'] = classes
        if filter:
            result['filters'] = filters
        return result

    def homeVideoContent(self):
        html = self.action_fetch(self.HOST)
        return self._parse_video_list(html)

    def categoryContent(self, tid, pg, filter, extend):
        cate_id = tid
        by = ""
        
        if extend:
            if "cateId" in extend and extend["cateId"]:
                cate_id = extend["cateId"]
            if "by" in extend and extend["by"]:
                by = extend["by"]

        if tid == "categories" or cate_id == "categories":
            url = f"{self.HOST}/categories.html"
            html = self.action_fetch(url)
            return self._parse_category_folder_list(html)

        if tid.startswith("subcat_"):
            real_cate = tid.replace("subcat_", "")
            url = f"{self.HOST}/videos/{real_cate}/{by}{pg}.html"
            html = self.action_fetch(url)
            return self._parse_video_list(html, pg)

        url = f"{self.HOST}/videos/{cate_id}/{by}{pg}.html"
        html = self.action_fetch(url)
        return self._parse_video_list(html, pg)

    def _parse_category_folder_list(self, html):
        folders = []
        if not html:
            return {"page": 1, "pagecount": 1, "limit": 100, "total": 0, "list": folders}

        soup = BeautifulSoup(html, 'html.parser')
        items = soup.select(".category-container a")

        for item in items:
            try:
                title = item.text.strip()
                href = item.get("href", "")
                
                cate_match = re.search(r"/videos/(.*?)\.html", href)
                if cate_match:
                    sub_cate_id = cate_match.group(1)
                else:
                    sub_cate_id = href.replace(".html", "").strip("/")

                img_tag = item.select_one("img")
                raw_pic = img_tag.get("src", "") if img_tag else ""
                pic = self._fix_pic_url(raw_pic)

                folders.append({
                    "vod_id": f"subcat_{sub_cate_id}",
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_tag": "folder",
                    "vod_remarks": "分类"
                })
            except Exception:
                continue

        return {
            "page": 1,
            "pagecount": 1,
            "limit": 100,
            "total": len(folders),
            "list": folders
        }

    def _parse_video_list(self, html, pg=1):
        """核心列表解析：精确提取图片、全标题、[厂牌标签] 以及视频时长"""
        videos = []
        if not html:
            return {"page": int(pg), "pagecount": 0, "limit": 20, "total": 0, "list": videos}

        soup = BeautifulSoup(html, 'html.parser')
        items = soup.select(".item.video, .video-list .video")

        for item in items:
            try:
                a_tag = item.select_one("a")
                if not a_tag:
                    continue
                
                # 标题获取
                title = a_tag.get("title", "")
                if not title:
                    title_div = item.select_one(".title a")
                    title = title_div.text.strip() if title_div else a_tag.text.strip()

                href = a_tag.get("href", "")
                
                # 1. 提取封面图片地址
                raw_pic = ""
                img_div = item.select_one("div[role='img'], .img")
                if img_div and img_div.get("style"):
                    img_match = re.search(r"url\((['\"]?)(.*?)\1\)", img_div.get("style"))
                    if img_match:
                        raw_pic = img_match.group(2)
                
                # 备用提取逻辑
                if not raw_pic and item.get("style"):
                    img_match = re.search(r"url\((['\"]?)(.*?)\1\)", item.get("style"))
                    if img_match:
                        raw_pic = img_match.group(2)

                pic = self._fix_pic_url(raw_pic)

                # 2. 提取厂牌标签（如：糖心Vlog）
                tag_text = ""
                tags_container = item.select_one(".tags")
                if tags_container:
                    for tag_div in tags_container.select("div"):
                        # 过滤掉 empty 的占位符与包含图标的时长节点
                        if "empty" not in tag_div.get("class", []) and not tag_div.select_one("i"):
                            text = tag_div.text.strip()
                            if text:
                                tag_text = text
                                break

                # 3. 提取视频时长（如：28:01）
                duration_text = ""
                time_ic = item.select_one(".fa-clock, .far.fa-clock")
                if time_ic and time_ic.parent:
                    duration_text = time_ic.parent.text.strip()

                # 4. 组合副标题备注: [糖心Vlog] 28:01
                if tag_text and duration_text:
                    remark = f"[{tag_text}] {duration_text}"
                elif tag_text:
                    remark = f"[{tag_text}]"
                else:
                    remark = duration_text

                videos.append({
                    "vod_id": href,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remark
                })
            except Exception:
                continue

        return {
            "page": int(pg),
            "pagecount": int(pg) + 1 if len(videos) > 0 else int(pg),
            "limit": 20,
            "total": 999,
            "list": videos
        }

    def detailContent(self, ids):
        vod_id = ids[0]
        url = vod_id if vod_id.startswith("http") else f"{self.HOST}{vod_id}"
        
        html = self.action_fetch(url)
        if not html:
            return {"list": []}

        soup = BeautifulSoup(html, 'html.parser')

        # 视频主标题
        title_tag = soup.select_one("h1") or soup.select_one("title")
        title = title_tag.text.strip() if title_tag else "小黄书视频"

        # 详情页海报图片提取
        raw_pic = ""
        poster_match = re.search(r"poster:\s*['\"](.*?)['\"]", html)
        if poster_match:
            raw_pic = poster_match.group(1)
        pic = self._fix_pic_url(raw_pic)

        # 视频播放流链接提取 (支持 JS 变量提取与正则匹配)
        play_url = ""
        js_match = re.search(r"new\s+VideoPlayer\((.*?)\);", html, re.DOTALL)
        if js_match:
            js_content = js_match.group(1)
            src_match = re.search(r"src:\s*['\"](.*?)['\"]", js_content)
            if src_match:
                play_url = src_match.group(1)

        if not play_url:
            m3u8_match = re.search(r"https?://[^\s'\"]+\.m3u8", html)
            if m3u8_match:
                play_url = m3u8_match.group(0)

        if not play_url:
            play_url = url

        vod_detail = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "type_name": "",
            "vod_year": "",
            "vod_area": "",
            "vod_remarks": "",
            "vod_actor": "",
            "vod_director": "",
            "vod_content": "飞鱼源",
            "vod_play_from": "飞鱼",
            "vod_play_url": f"高清播放${play_url}"
        }

        return {"list": [vod_detail]}

    def searchContent(self, key, quick):
        encoded_key = urllib.parse.quote(key)
        url = f"{self.HOST}/videos/keyword-{encoded_key}/1.html"
        html = self.action_fetch(url)
        return self._parse_video_list(html, 1)

    def playerContent(self, flag, id, vipFlags):
        # 如果是直连 .m3u8/.mp4 文件则关闭内核二次解析
        parse_flag = 0 if (".m3u8" in id or ".mp4" in id) else 1
        
        result = {
            "parse": parse_flag,
            "playUrl": "",
            "url": id,
            "header": self.PLAY_HEADERS
        }
        return result
