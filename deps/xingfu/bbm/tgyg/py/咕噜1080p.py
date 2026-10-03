#!/usr/bin/python
# @tvbox-source
# -*- coding: utf-8 -*-
import re, json, base64, ssl, urllib.request, urllib.parse

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

try:
    from base.spider import Spider as _SpiderBase
except:
    class _SpiderBase: pass

class csp_GuLu4K(_SpiderBase):
    def getName(self): return "新咕噜4K"
    def init(self, extend=""):
        self.host = "https://guludy.com"
        self.headers = {"User-Agent": "Mozilla/5.0", "Referer": self.host + "/"}
        self.categories = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "3", "type_name": "动漫"},
            {"type_id": "4", "type_name": "综艺"},
            {"type_id": "10", "type_name": "短剧"},
        ]
    def _get(self, url):
        try:
            req = urllib.request.Request(url, headers=self.headers)
            resp = urllib.request.urlopen(req, timeout=15, context=_ctx)
            return resp.read().decode("utf-8", errors="ignore")
        except: return ""
    def _fix(self, url):
        if not url: return ""
        if url.startswith("//"): return "https:" + url
        if url.startswith("/"): return self.host + url
        return url
    def _list(self, html):
        out = []; seen = set()
        for m in re.finditer(r'<li\b.*?</li>', html, re.S):
            block = m.group()
            id_m = re.search(r'vod-read-id-(\d+)\.html', block)
            if not id_m: continue
            vid = id_m.group(1)
            if vid in seen: continue
            seen.add(vid)
            pic_m = re.search(r'<img[^>]*src="([^"]*)"', block)
            pic = self._fix(pic_m.group(1)) if pic_m else ""
            name_m = re.search(r'alt="([^"]*)"', block) or re.search(r'<p><a[^>]*>([^<]*)</a>', block)
            name = name_m.group(1) if name_m else vid
            rem_m = re.search(r'<span>([^<]*)</span>', block)
            remarks = rem_m.group(1).strip() if rem_m else ""
            out.append({"vod_id": vid, "vod_name": name, "vod_pic": pic, "vod_remarks": remarks})
        return out
    def _pagecount(self, html):
        nums = re.findall(r'-p-(\d+)\.html', html)
        return max(int(n) for n in nums) if nums else 1
    def homeContent(self, filter):
        return {"class": self.categories, "list": self._list(self._get(self.host)), "filters": {}}
    def homeVideoContent(self):
        return {"list": self._list(self._get(self.host))}
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        url = f"{self.host}/index.php?s=/vod-show-id-{tid}-p-{pg}.html" if pg > 1 else f"{self.host}/index.php?s=/vod-show-id-{tid}.html"
        html = self._get(url)
        items = self._list(html)
        return {"page": pg, "pagecount": self._pagecount(html), "limit": len(items) or 20, "total": 0, "list": items}
    def detailContent(self, ids):
        out = []
        for vid in ids:
            html = self._get(f"{self.host}/index.php?s=/vod-read-id-{vid}.html")
            if not html: continue
            m = re.search(r'<h1[^>]*>(.*?)<span', html, re.S)
            name = re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else str(vid)
            m = re.search(r'text_img.*?src="([^"]*)"', html, re.S)
            pic = self._fix(m.group(1)) if m else ""
            m = re.search(r'主演：</b>(.*?)</p>', html, re.S)
            actor = re.sub(r'<[^>]+>', '', m.group(1)).replace('&nbsp;', ' ').strip() if m else ""
            m = re.search(r'导演：</b>(.*?)</p>', html, re.S)
            director = re.sub(r'<[^>]+>', '', m.group(1)).replace('&nbsp;', ' ').strip() if m else ""
            m = re.search(r'剧情介绍</h3>.*?<li[^>]*>(.*?)</li>', html, re.S)
            content = m.group(1).strip() if m else ""
            sources = {}
            for sm in re.finditer(r'vod-play-id-\d+-sid-(\d+)-pid-(\d+)\.html[^>]*class=["\']clips["\']>\s*([^<]*)', html):
                sid, pid, ep = sm.group(1), sm.group(2), sm.group(3).strip()
                if '立即播放' in ep: continue
                sources.setdefault(sid, []).append((pid, ep))
            pf, pu = [], []
            for sid in sorted(sources.keys(), key=int):
                pf.append(f"播放源{sid}")
                pu.append("#".join(f"{ep}${vid}-sid-{sid}-pid-{pid}" for pid, ep in sources[sid]))
            out.append({
                "vod_id": str(vid), "vod_name": name, "vod_pic": pic,
                "vod_actor": actor, "vod_director": director, "vod_content": content,
                "vod_play_from": "$$$".join(pf), "vod_play_url": "$$$".join(pu),
            })
        return {"list": out}
    def searchContent(self, key, quick, pg="1"):
        url = f"{self.host}/index.php?s=vod-search-name&wd={urllib.parse.quote(key)}"
        return {"list": self._list(self._get(url)), "page": int(pg) if str(pg).isdigit() else 1}
    def playerContent(self, flag, id, vipFlags):
        html = self._get(f"{self.host}/index.php?s=/vod-play-id-{id}.html")
        m = re.search(r'<iframe[^>]*src="([^"]*)"', html)
        if m:
            iframe_src = m.group(1)
            mu_m = re.search(r'mu=([^&"]+)', iframe_src)
            if mu_m:
                try:
                    mu = urllib.parse.unquote(mu_m.group(1))
                    m3u8 = base64.b64decode(mu).decode("utf-8")
                    return {"parse": 0, "url": m3u8, "header": json.dumps(self.headers)}
                except: pass
            iframe_url = self._fix(iframe_src)
            iframe_html = self._get(iframe_url)
            mm = re.search(r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*', iframe_html)
            if mm:
                return {"parse": 0, "url": mm.group(0), "header": json.dumps(self.headers)}
            return {"parse": 1, "url": iframe_url, "header": json.dumps(self.headers)}
        return {"parse": 1, "url": f"{self.host}/index.php?s=/vod-play-id-{id}.html", "header": json.dumps(self.headers)}

Spider = csp_GuLu4K
