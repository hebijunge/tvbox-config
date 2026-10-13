# coding=utf-8
import re
from urllib.parse import quote, unquote
import requests
from base.spider import Spider


class Spider(Spider):
    def getName(self):
        return "七猫短剧"

    def init(self, extend=""):
        self.host = "https://7maoduanju.com"
        if isinstance(extend, str) and extend.strip().startswith("http"):
            self.host = extend.strip().rstrip("/")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Referer": self.host + "/",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _get(self, url):
        try:
            r = self.session.get(url, headers=self.headers, timeout=15, verify=False)
            r.encoding = "utf-8"
            if r.status_code == 200 and r.text:
                return r.text
        except Exception:
            pass
        return ""

    def _api(self, path):
        try:
            r = self.session.get(self.host + path, headers=self.headers, timeout=15, verify=False)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []

    def _badge(self, cls):
        return {"free": "免费", "vip": "会员", "coin": "金币"}.get(cls or "", "")

    def _cards(self, html):
        items = []
        for m in re.finditer(r'<a class="drama-card-link" href="(/drama/[0-9a-f-]{36}/?)">(.*?)</a>', html or "", re.S):
            body = m.group(2)
            did = re.search(r"/drama/([0-9a-f-]{36})", m.group(1)).group(1)
            img = re.search(r'<img[^>]+src="([^"]+)"[^>]*alt="([^"]*)"', body)
            if not img:
                continue
            badge = re.search(r'drama-card-link__access--([a-z]+)', body)
            heat = re.search(r'drama-card-link__heat">[^0-9]*([0-9.万千]+)<', body)
            update = re.search(r'drama-card-link__update">([^<]+)<', body)
            remarks = " ".join(x for x in (
                self._badge(badge.group(1)) if badge else "",
                update.group(1) if update else "",
                ("热度" + heat.group(1)) if heat else "",
            ) if x)
            items.append({"vod_id": did, "vod_name": img.group(2).strip(), "vod_pic": img.group(1), "vod_remarks": remarks})
        return items

    def _sections(self, html):
        secs = []
        for m in re.finditer(
                r'<section class="home-block">.*?<h2 class="home-block__title">([^<]+)</h2><a class="home-block__more" href="/category/([^"/]+)/?"',
                html or "", re.S):
            secs.append({"type_id": unquote(m.group(2)), "type_name": m.group(1).strip(), "html": m.group(0)})
        return secs

    def homeContent(self, filter):
        html = self._get(self.host + "/")
        classes = [{"type_id": s["type_id"], "type_name": s["type_name"]} for s in self._sections(html)]
        return {"class": classes, "filters": {}, "list": self._cards(html)}

    def homeVideoContent(self):
        return {"list": self._cards(self._get(self.host + "/"))}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        if pg > 1:
            return {"page": pg, "pagecount": 1, "limit": 0, "total": 0, "list": []}
        items = self._cards(self._get(self.host + "/category/" + quote(str(tid or ""), safe="") + "/"))
        return {"page": 1, "pagecount": 1, "limit": len(items), "total": len(items), "list": items}

    def _episodes_json(self, html):
        eps = []
        for m in re.finditer(
                r'\\"id\\":\\"([0-9a-f-]{36})\\",\\"indexNo\\":(\d+),\\"title\\":\\"([^\\]+?)\\",\\"locked\\":(true|false)(?:[^}]*?\\"seoContentUrl\\":\\"([^\\]+?)\\")?',
                html or ""):
            eps.append({"id": m.group(1), "no": int(m.group(2)), "title": m.group(3),
                        "locked": m.group(4) == "true", "url": m.group(5) or ""})
        return eps

    def _episodes_anchor(self, html):
        eps = []
        for m in re.finditer(
                r'<a class="drama-detail__ep[^"]*" title="(第\d+集)，([^"]+)"[^>]*href="(/play/[0-9a-f-]{36}/\?episodeId=[0-9a-f-]{36})"',
                html or ""):
            no = re.search(r"\d+", m.group(1))
            eps.append({"id": "", "no": int(no.group()) if no else 0, "title": m.group(1),
                        "locked": "免费" not in m.group(2), "url": "", "play": m.group(3)})
        return eps

    def _unlock(self, eps):
        base, width = "", 2
        for e in eps:
            m = re.search(r"^(.*/)(ep(\d+)/ep\d+\.m3u8)$", e["url"] or "")
            if m:
                base, width = m.group(1), len(m.group(3))
                break
        if not base:
            return
        for e in eps:
            if not e["url"] and e["no"] > 0:
                n = str(e["no"]).zfill(width)
                e["url"] = "%sep%s/ep%s.m3u8" % (base, n, n)

    def _detail_api(self, did):
        d = self._api("/api/toc/v1/dramas/" + did)
        if not isinstance(d, dict) or not d.get("id"):
            return None, []
        meta = {
            "title": d.get("title", ""),
            "cover": d.get("coverUrl", ""),
            "desc": d.get("description", ""),
            "tags": ",".join(d.get("tags") or []),
            "heat": str(d.get("heat") or ""),
            "pay": {"vip_only": "会员", "coin_only": "金币", "both": "免费"}.get(d.get("payMode") or "", ""),
        }
        eps = []
        for e in d.get("episodes") or []:
            if not isinstance(e, dict):
                continue
            eps.append({"id": e.get("id", ""), "no": int(e.get("indexNo") or 0),
                        "title": e.get("title") or ("第%s集" % e.get("indexNo")),
                        "locked": bool(e.get("locked")), "url": e.get("seoContentUrl") or ""})
        return meta, eps

    def _detail_html(self, html):
        meta = self._detail_meta(html)
        title = ""
        m = re.search(r"<title>《(.+?)》短剧", html or "")
        if m:
            title = m.group(1)
        if not title:
            m = re.search(r'\\"title\\":\\"([^\\]+?)\\"', html or "")
            if m:
                title = m.group(1)
        meta["title"] = title
        eps = self._episodes_json(html)
        if not eps:
            eps = self._episodes_anchor(html)
            for e in eps:
                if not e["locked"] and e.get("play"):
                    ph = self._get(self.host + e["play"])
                    u = re.search(r'\\"seoContentUrl\\":\\"(https?://[^\\]+\.m3u8)\\"', ph or "")
                    if u:
                        e["url"] = u.group(1)
                        break
        return meta, eps

    def _detail_meta(self, html):
        meta = {}
        seg = html or ""
        m = re.search(r'\\"coverUrl\\":\\"([^\\]+)\\"', seg)
        if m:
            meta["cover"] = m.group(1)
        m = re.search(r'\\"description\\":\\"((?:[^\\]|\\.)*?)\\"', seg)
        if m:
            meta["desc"] = m.group(1).replace("\\n", "\n").replace('\\"', '"').replace("\\/", "/")
        m = re.search(r'\\"tags\\":\[([^\]]*)\]', seg)
        if m:
            meta["tags"] = ",".join(re.findall(r'\\"([^\\]+)\\"', m.group(1)))
        m = re.search(r'\\"heat\\":(\d+)', seg)
        if m:
            meta["heat"] = m.group(1)
        m = re.search(r'\\"payMode\\":\\"([a-z_]+)\\"', seg)
        if m:
            meta["pay"] = {"vip_only": "会员", "coin_only": "金币", "both": "免费"}.get(m.group(1), "")
        if not meta.get("desc"):
            m = re.search(r'<meta name="description" content="([^"]+)"', seg)
            if m:
                meta["desc"] = m.group(1)
        return meta

    def detailContent(self, ids):
        did = str(ids[0]).strip() if ids else ""
        if not re.fullmatch(r"[0-9a-f-]{36}", did):
            m = re.search(r"[0-9a-f-]{36}", did)
            did = m.group() if m else ""
        if not did:
            return {"list": []}
        meta, eps = self._detail_api(did)
        if not eps:
            html = self._get(self.host + "/drama/" + did + "/")
            if not html:
                return {"list": []}
            meta, eps = self._detail_html(html)
        self._unlock(eps)
        vod = {
            "vod_id": did,
            "vod_name": meta.get("title", ""),
            "vod_pic": meta.get("cover", ""),
            "type_name": meta.get("tags", ""),
            "vod_year": "",
            "vod_area": "",
            "vod_remarks": " ".join(x for x in (
                ("更新至%d集" % len(eps)) if eps else "",
                meta.get("pay", ""),
                ("热度" + meta["heat"]) if meta.get("heat") else "",
            ) if x),
            "vod_actor": "",
            "vod_director": "",
            "vod_content": meta.get("desc", ""),
        }
        names, urls = [], []
        for e in sorted(eps, key=lambda x: x["no"]):
            if not e["url"]:
                continue
            names.append("七猫短剧")
            urls.append("%s$%s" % (e["title"], e["url"]))
        if names:
            vod["vod_play_from"] = "$$$".join(names)
            vod["vod_play_url"] = "#".join(urls)
        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        items = []
        for d in self._api("/api/toc/v1/search?q=" + quote(str(key or ""), safe="")) or []:
            if not isinstance(d, dict) or not d.get("id"):
                continue
            pay = {"vip_only": "会员", "coin_only": "金币", "both": "免费"}.get(d.get("payMode") or "", "")
            remarks = " ".join(x for x in (
                pay,
                ("共%d集" % d["episodeCount"]) if d.get("episodeCount") else "",
                ("热度%d" % d["heat"]) if d.get("heat") else "",
            ) if x)
            items.append({"vod_id": d["id"], "vod_name": d.get("title", ""),
                          "vod_pic": d.get("coverUrl", ""), "vod_remarks": remarks})
        return {"page": 1, "pagecount": 1, "limit": len(items), "total": len(items), "list": items}

    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()
        if not url.startswith("http"):
            return {"parse": 0, "playUrl": "", "url": "", "header": self.headers}
        header = dict(self.headers)
        header["Referer"] = self.host + "/"
        return {"parse": 0, "playUrl": "", "url": url, "header": header}
