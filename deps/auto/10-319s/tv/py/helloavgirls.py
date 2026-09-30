# coding: utf-8
import json
from urllib.parse import quote
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    # 类级缓存
    _cache = {}

    def __init__(self):
        self.base_url = "https://www.helloavgirls.com"
        self.api_base = "https://www.helloavgirls.com/api"
        self.limit = 20
        self.ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36'
        self.headers = {
            'User-Agent': self.ua,
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        }
        self.classes = [
            {"type_id": "recommend", "type_name": "🔥 推荐"},
            {"type_id": "label_251", "type_name": "涼森玲夢"},
            {"type_id": "label_245", "type_name": "瀬戸環奈"},
            {"type_id": "label_227", "type_name": "神木麗"},
            {"type_id": "label_230", "type_name": "本庄鈴"},
            {"type_id": "label_17", "type_name": "中文字幕"},
            {"type_id": "label_41", "type_name": "中出"},
            {"type_id": "label_51", "type_name": "顏射"},
            {"type_id": "label_34", "type_name": "乳交"},
            {"type_id": "label_164", "type_name": "S1"},
            {"type_id": "label_171", "type_name": "SOD"},
            {"type_id": "label_165", "type_name": "蚊香社"},
            {"type_id": "label_197", "type_name": "無碼破壞版"},
            {"type_id": "label_43", "type_name": "美少女"},
            {"type_id": "label_57", "type_name": "女教師"},
            {"type_id": "label_63", "type_name": "辦公室OL"},
            {"type_id": "label_32", "type_name": "女女互愛"},
            {"type_id": "label_70", "type_name": "旅館"},
            {"type_id": "label_84", "type_name": "家裡"},
            {"type_id": "label_96", "type_name": "運動"},
        ]
        self.filters = {}

    def getName(self):
        return "HelloAV Girls"

    def getDependence(self):
        return []

    def init(self, extend=''):
        pass

    def homeContent(self, filter=False):
        classes = []
        for c in self.classes:
            classes.append({
                "type_id": c["type_id"],
                "type_name": c["type_name"]
            })
        return {"class": classes, "filters": self.filters}

    def homeVideoContent(self):
        try:
            data = self._fetch_json(self.api_base + '/content?with_images=true&with_labels=true&limit=12&offset=0&sort_by=id&order_by=desc')
            if data and isinstance(data, list):
                videos = []
                for item in data:
                    video = self._parse_video_item(item)
                    if video:
                        videos.append(video)
                        Spider._cache[video["vod_id"]] = item
                return {"list": videos}
        except:
            pass
        return {"list": []}

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        videos = []
        page = int(pg) if pg else 1
        offset = (page - 1) * self.limit
        
        try:
            if tid == "recommend":
                url = self.api_base + f'/content?with_images=true&with_labels=true&limit={self.limit}&offset={offset}&sort_by=id&order_by=desc'
            elif tid.startswith("label_"):
                label_id = tid.replace("label_", "")
                url = self.api_base + f'/content?with_images=true&with_labels=true&limit={self.limit}&offset={offset}&sort_by=id&order_by=desc&labels={label_id}'
            else:
                url = self.api_base + f'/content?with_images=true&with_labels=true&limit={self.limit}&offset={offset}&sort_by=id&order_by=desc'
            
            data = self._fetch_json(url)
            if data and isinstance(data, list):
                for item in data:
                    video = self._parse_video_item(item)
                    if video:
                        videos.append(video)
                        Spider._cache[video["vod_id"]] = item
        except:
            pass
        
        total = 1000
        pagecount = (total + self.limit - 1) // self.limit
        
        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": self.limit,
            "total": total
        }

    def detailContent(self, ids):
        vid = None
        if ids is None:
            return {"list": []}
        if isinstance(ids, list):
            vid = str(ids[0]) if ids else None
        elif isinstance(ids, str):
            vid = ids.split(",")[0] if ids else None
        else:
            vid = str(ids)
        
        if not vid:
            return {"list": []}
        
        data = Spider._cache.get(vid)
        
        if not data:
            return {"list": []}
        
        if data and isinstance(data, dict):
            play_from = "线路1"
            play_url = ""
            
            base_link = data.get("base_link", "")
            video_options = data.get("video_options", [])
            
            # 修复搜索数据的域名和路径
            base_link, video_options = self._fix_search_data(base_link, video_options)
            
            if isinstance(video_options, str):
                try:
                    video_options = json.loads(video_options)
                except:
                    video_options = [video_options]
            
            if video_options and len(video_options) > 0:
                for idx, opt in enumerate(video_options):
                    if opt:
                        m3u8_url = self._build_m3u8_url(base_link, opt, vid)
                        if play_url:
                            play_url += "$$$" + "播放$" + m3u8_url
                        else:
                            play_url = "播放$" + m3u8_url
                if "$$$" in play_url:
                    play_from = "线路1$$$线路2"
            
            pic_url = data.get("cover", "")
            if not pic_url:
                images = data.get("images", [])
                if images and len(images) > 0:
                    pic_url = images[0].get("url", "")
            
            title = data.get("title", "")
            text = data.get("text", "")
            
            vod = {
                "vod_id": str(data.get("id", vid)),
                "vod_name": title,
                "vod_pic": pic_url,
                "vod_content": text or "",
                "vod_play_from": play_from,
                "vod_play_url": play_url
            }
            return {"list": [vod]}
        
        return {"list": []}

    def searchContent(self, key, quick=False, pg=1):
        try:
            page = int(pg) if pg else 1
            offset = (page - 1) * self.limit
            url = self.api_base + f'/content?q={quote(key)}&limit={self.limit}&offset={offset}'
            data = self._fetch_json(url)
            if data and isinstance(data, list):
                videos = []
                for item in data:
                    item_id = str(item.get("id", ""))
                    if not item_id:
                        continue
                    
                    # 存入缓存，供 detailContent 使用
                    Spider._cache[item_id] = item
                    
                    title = item.get("title", "")
                    pic = item.get("cover", "")
                    if not pic:
                        images = item.get("images", [])
                        if images and len(images) > 0:
                            pic = images[0].get("url", "")
                    
                    video = {
                        "vod_id": item_id,
                        "vod_name": title,
                        "vod_pic": pic,
                        "vod_remarks": "",
                        "vod_play_url": ""  # 由 detailContent 处理
                    }
                    videos.append(video)
                
                total = 1000
                pagecount = (total + self.limit - 1) // self.limit
                return {"list": videos, "pagecount": pagecount}
        except:
            pass
        return {"list": [], "pagecount": 0}

    def playerContent(self, flag, id, vipFlags=None):
        raw_id = str(id or '').replace('\\/', '/')
        if raw_id.startswith('播放$'):
            raw_id = raw_id[3:]
        
        if raw_id.startswith('http://') or raw_id.startswith('https://'):
            return {
                "parse": 0,
                "url": raw_id,
                "header": json.dumps({
                    "User-Agent": self.ua,
                    "Referer": self.base_url,
                    "Origin": self.base_url
                })
            }
        else:
            return {
                "parse": 1,
                "url": self.base_url + "/av/" + raw_id,
                "header": json.dumps({
                    "User-Agent": self.ua,
                    "Referer": self.base_url
                })
            }

    def destroy(self):
        Spider._cache.clear()

    def _fetch_json(self, url):
        try:
            r = self.fetch(url, headers=self.headers, timeout=10)
            if r and r.text:
                return json.loads(r.text)
        except:
            pass
        return None

    def _fix_search_data(self, base_link, video_options):
        """修复搜索返回的无效域名和路径"""
        if 'v5.helloavgirls.com' in base_link:
            base_link = base_link.replace('v5.helloavgirls.com', 'v4.helloavgirls.com')
        
        if isinstance(video_options, str):
            if '/original/hls/' in video_options:
                video_options = video_options.replace('/original/hls/', '/480p/hls/')
        elif isinstance(video_options, list):
            video_options = [opt.replace('/original/hls/', '/480p/hls/') if isinstance(opt, str) else opt for opt in video_options]
        
        return base_link, video_options

    def _build_m3u8_url(self, base_link, path, vid):
        if not path:
            return ""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        path = path.lstrip('/')
        return f"{base_link.rstrip('/')}/{vid}/{path}"

    def _parse_video_item(self, item):
        vid = str(item.get("id", ""))
        if not vid:
            return None
        
        title = item.get("title", "")
        
        pic = item.get("cover", "")
        if not pic:
            images = item.get("images", [])
            if images and len(images) > 0:
                pic = images[0].get("url", "")
        
        base_link = item.get("base_link", "")
        video_options = item.get("video_options", [])
        
        # 修复数据
        base_link, video_options = self._fix_search_data(base_link, video_options)
        
        if isinstance(video_options, str):
            try:
                video_options = json.loads(video_options)
            except:
                video_options = [video_options]
        
        play_url = ""
        if video_options and len(video_options) > 0:
            play_url = "播放$" + self._build_m3u8_url(base_link, video_options[0], vid)
        
        return {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": pic,
            "vod_remarks": "",
            "vod_play_url": play_url
        }


def getSpider():
    return Spider()

def get_class():
    return Spider