# -*- coding: utf-8 -*-
# 全网聚合 Python版
# Cat / TVBox Python Spider

import base64, json, re, time, random
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
from base.spider import Spider

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_UA = "Mozilla/5.0"
_PAGE_SIZE = 12
_WORKERS = 12
_TIMEOUT = 3

class Spider(Spider):

    sources = {
        's1':  {'name': '小姐姐1', 'api': 'https://api.yujn.cn/api/xjj.php?type=video'},
        's2':  {'name': '小姐姐2', 'api': 'http://api.yujn.cn/api/ksxjjsp.php'},
        's3':  {'name': '小姐姐3', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=GaoZhiLiangXiaoJieJie'},
        's4':  {'name': '小姐姐4', 'api': 'https://api.qzqi.com/api/v1/DyRandomVideo?type=mp4'},
        's5':  {'name': 'JK1', 'api': 'https://api.suyanw.cn/api/jksp.php'},
        's6':  {'name': 'JK2', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=jk'},
        's7':  {'name': '高质量', 'api': 'https://api.yujn.cn/api/zzxjj.php?type=video'},
        's8':  {'name': '帅哥', 'api': 'http://api.yujn.cn/api/xgg.php?type=video'},
        's9':  {'name': '热舞1', 'api': 'http://api.yujn.cn/api/rewu.php?type=video'},
        's10': {'name': '热舞2', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=ReWu'},
        's11': {'name': '变装', 'api': 'http://api.yujn.cn/api/bianzhuang.php'},
        's12': {'name': '白丝1', 'api': 'http://api.yujn.cn/api/baisis.php?type=video'},
        's13': {'name': '白丝2', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=BaiSi'},
        's14': {'name': '黑丝', 'api': 'http://api.yujn.cn/api/heisis.php?type=video'},
        's15': {'name': '甜妹', 'api': 'http://api.yujn.cn/api/tianmei.php?type=video'},
        's16': {'name': '萝莉', 'api': 'http://api.yujn.cn/api/luoli.php?type=video'},
        's17': {'name': '穿搭1', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=ChuanDa'},
        's18': {'name': '穿搭2', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=HanFu'},
        's19': {'name': '穿搭3', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=HeiSi'},
        's20': {'name': '穿搭4', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=BianZhuang'},
        's21': {'name': '穿搭5', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=LuoLi'},
        's22': {'name': '穿搭6', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=TianMei'},
        's23': {'name': '女大1', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=NvDa'},
        's24': {'name': '女大2', 'api': 'https://api.qzqi.com/api/v1/Randclip?type=mp4&id=QingCun'},
        's25':  {'name': '小姐姐1', 'api': 'http://av.npcq.cn/pc.php'},
        's26':  {'name': '小姐姐2', 'api': 'https://diskgirl.com/get/get2.php'},
        's27':  {'name': '小姐姐3', 'api': 'https://www.xiaolufx.net/suiji/video.php?_t='},
        's28':  {'name': '小姐姐4', 'api': 'https://www.cunshao.com/666666/api/web.php'},
        's29':  {'name': '小姐姐5', 'api': 'http://api.yujn.cn/api/zzxjj.php'},
        's30':  {'name': '小姐姐6', 'api': 'https://www.cunshao.com/666666/api/pc.php'},
        's31':  {'name': '小姐姐7', 'api': 'https://v.api.aa1.cn/api/api-dy-girl/index.php?aa1=ajdu987hrjfw'},
        's32':  {'name': '小姐姐8', 'api': 'https://api.ksse.cn/API/sp/sjxjj2.php'},
        's33':  {'name': '小姐姐9', 'api': 'https://api.ksse.cn/API/sp/bs.php'},
        's34': {'name': '随机慢摇视频', 'api': 'https://api.bi71t5.cn/api/my.php'},
        's35': {'name': '少妇视频', 'api': 'http://v.nrzj.vip/video.php?_t=0.9'},
        's36': {'name': '高质量小姐姐', 'api': 'http://api.tinise.cn/api/xjjsp'},
        's37': {'name': '抖音小姐姐', 'api': 'http://api.qemao.com/api/douyin/'},
        's38': {'name': '完美身材', 'api': 'http://api.yujn.cn/api/wmsc.php?type=video'},
        's39': {'name': '快手变装', 'api': 'http://api.yujn.cn/api/ksbianzhuang.php?type=video'},
        's40': {'name': '抖音变装', 'api': 'http://api.yujn.cn/api/bianzhuang.php?'},
        's41': {'name': '白丝视频', 'api': 'http://api.yujn.cn/api/baisis.php?type=video'},
        's42': {'name': '美女穿搭', 'api': 'http://api.yujn.cn/api/chuanda.php?type=video'},
        's43': {'name': '随机小姐姐', 'api': 'http://api.yujn.cn/api/xjj.php?type=video'},
        's44': {'name': '黑丝视频', 'api': 'http://api.yujn.cn/api/heisis.php?type=video'},
        's45': {'name': '女大学生', 'api': 'https://api.yujn.cn/api/nvda.php?type=video'},
        's46': {'name': '抖音瞳瞳', 'api': 'https://api.yujn.cn/api/tongtong.php?type=video'},
        's47': {'name': '丝滑舞蹈', 'api': 'http://api.yujn.cn/api/shwd.php?type=video'},
        's48': {'name': '古风系列', 'api': 'http://api.yujn.cn/api/hanfu.php?type=video'},
        's49': {'name': '慢摇系列', 'api': 'http://api.yujn.cn/api/manyao.php?type=video'},
        's50': {'name': '吊带系列', 'api': 'http://api.yujn.cn/api/diaodai.php?type=video'},
        's51': {'name': '清纯系列', 'api': 'http://api.yujn.cn/api/qingchun.php?type=video'},
        's52': {'name': 'COS系列', 'api': 'http://api.yujn.cn/api/COS.php?type=video'},
        's53': {'name': '萝莉系列', 'api': 'http://api.yujn.cn/api/luoli.php?type=video'},
        's54': {'name': '甜妹系列', 'api': 'http://api.yujn.cn/api/tianmei.php?type=video'},
    }

    def getName(self):
        return "全网聚合"

    def init(self, extend=""):
        self._s = requests.Session()
        self._s.headers.update({"User-Agent": _UA})
        self._s.verify = False

    def _fetch_mp4(self, url):
        try:
            r = self._s.get(url, timeout=_TIMEOUT, allow_redirects=True, stream=True)
            ct = r.headers.get("Content-Type", "").lower()
            final = r.url
            cl = 0
            try:
                cl = int(r.headers.get("Content-Length", "0"))
            except Exception:
                pass

            # direct video by Content-Type
            if "video" in ct or "mp4" in ct or "octet-stream" in ct:
                r.close()
                return final, cl

            # redirected to a video URL (check extension)
            if final != url and self._is_video_url(final):
                r.close()
                return final, cl

            r.close()

            # read body
            r2 = self._s.get(url, timeout=_TIMEOUT, allow_redirects=False)
            txt = r2.text.strip()
            r2.close()

            if not txt:
                return "", 0

            # plain URL in body
            if txt.startswith("http"):
                if self._is_video_url(txt):
                    return txt, 0
                # might be a redirect link, try following it
                mp4, sz = self._fetch_mp4(txt)
                if mp4:
                    return mp4, sz
                return "", 0

            # JSON response
            if txt.startswith("{"):
                try:
                    data = json.loads(txt)
                    for key in ("url", "video", "mp4", "data", "src", "link", "href"):
                        v = data.get(key, "")
                        if isinstance(v, str) and v.startswith("http"):
                            return v, 0
                    # nested
                    for key in ("data", "result", "body"):
                        inner = data.get(key)
                        if isinstance(inner, dict):
                            for k2 in ("url", "video", "mp4", "src", "link"):
                                v2 = inner.get(k2, "")
                                if isinstance(v2, str) and v2.startswith("http"):
                                    return v2, 0
                except Exception:
                    pass

            return "", 0
        except Exception:
            return "", 0

    def _is_video_url(self, u):
        u = u.lower()
        return any(u.endswith(ext) for ext in (".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".ts")) or "/video/" in u or "mp4" in u

    def _enc(self, s):
        return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

    def _dec(self, s):
        # add padding back
        pad = 4 - len(s) % 4
        if pad != 4:
            s += "=" * pad
        try:
            return base64.urlsafe_b64decode(s.encode()).decode()
        except Exception:
            return ""

    def _uid(self, sk, mp4):
        # unique id: source + encoded mp4 + random suffix
        return f"{sk}_{self._enc(mp4)}_{random.randint(10000, 99999)}"

    def _fmt_size(self, s):
        if s <= 0:
            return ""
        if s < 1024 * 1024:
            return f"{s / 1024:.0f}KB"
        return f"{s / (1024 * 1024):.1f}MB"

    def _mk_item(self, vid, name, mp4, size, remarks=""):
        sz = self._fmt_size(size)
        rm = f"{remarks} {sz}".strip() if sz else remarks
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": mp4,
            "vod_remarks": rm,
            "vod_play_from": "播放",
            "vod_play_url": "播放$" + mp4,
        }

    # ---------- home ----------
    def homeContent(self, filter):
        classes = []
        for k, s in self.sources.items():
            classes.append({"type_id": k, "type_name": s["name"]})
        return {"class": classes}

    def homeVideoContent(self):
        items = []
        def _load(k, s):
            mp4, size = self._fetch_mp4(s["api"])
            if mp4:
                vid = self._uid(k, mp4)
                items.append(self._mk_item(vid, s["name"], mp4, size, s["name"]))
        with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
            list(ex.map(lambda kv: _load(*kv), self.sources.items()))
        return items

    # ---------- category ----------
    def categoryContent(self, tid, pg="1", extend="", _filter=""):
        sk = tid
        if sk not in self.sources:
            return {"page": 1, "pagecount": 1, "limit": _PAGE_SIZE, "total": 0, "list": []}
        s = self.sources[sk]
        pg_int = int(pg)
        items = []

        def _fetch_one(i):
                mp4, size = self._fetch_mp4(s["api"])
                if mp4:
                    idx = (pg_int - 1) * _PAGE_SIZE + i + 1
                    vid = self._uid(sk, mp4)
                    return self._mk_item(vid, f"{s['name']} #{idx}", mp4, size, s["name"])
                return None

        with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
            futures = [ex.submit(_fetch_one, i) for i in range(_PAGE_SIZE)]
            for f in as_completed(futures):
                item = f.result()
                if item:
                    items.append(item)

        return {
            "page": pg_int,
            "pagecount": 9999,
            "limit": _PAGE_SIZE,
            "total": 999999,
            "list": items,
        }

    # ---------- detail ----------
    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else ids
        parts = vid.split("_", 1)
        sk = parts[0] if len(parts) >= 1 else ""
        sn = self.sources.get(sk, {}).get("name", "") if sk in self.sources else ""

        # decode mp4 from vod_id (second part, before random suffix)
        mp4 = ""
        if len(parts) >= 2:
            # second part may contain random suffix, extract encoded mp4
            encoded = parts[1].rsplit("_", 1)[0] if "_" in parts[1] else parts[1]
            mp4 = self._dec(encoded)

        return {
            "list": [{
                "vod_id": vid,
                "vod_name": sn,
                "vod_pic": mp4,
                "vod_play_from": "播放",
                "vod_play_url": ("播放$" + mp4) if mp4 else "",
            }]
        }

    # ---------- player ----------
    def playerContent(self, vid, ext, flag=""):
        url = ""

        # ext is vod_play_url like "播放$http://..."
        if ext and "$" in ext:
            url = ext.split("$", 1)[-1]
        elif ext and ext.startswith("http"):
            url = ext

        # fallback: decode from vid
        if not url:
            parts = vid.split("_", 1)
            if len(parts) >= 2:
                encoded = parts[1].rsplit("_", 1)[0] if "_" in parts[1] else parts[1]
                url = self._dec(encoded)

        if url and url.startswith("http"):
            return {
                "parse": 0,
                "url": url,
                "header": json.dumps({"User-Agent": _UA}),
            }

        return {"parse": 0, "url": ""}

    # ---------- search ----------
    def searchContent(self, key, quick="", pg="1"):
        return {"page": 1, "pagecount": 1, "limit": 0, "total": 0, "list": []}