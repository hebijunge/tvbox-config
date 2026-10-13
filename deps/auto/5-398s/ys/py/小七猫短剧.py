# coding=utf-8
import re, json, requests
from urllib.parse import quote, unquote
from base.spider import Spider


class Spider(Spider):
    def getName(self):
        return "七猫短剧"

    def init(self, extend=""):
        self.host = "https://7maoduanju.com"
        if isinstance(extend, str) and extend.strip().startswith("http"):
            self.host = extend.strip().rstrip("/")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": self.host + "/",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.classes = [
            {"type_id": "热门短剧", "type_name": "热门短剧"},
            {"type_id": "原创短剧", "type_name": "原创短剧"},
            {"type_id": "AI 短剧", "type_name": "AI 短剧"},
            {"type_id": "AI 漫剧", "type_name": "AI 漫剧"},
            {"type_id": "AI 魔改", "type_name": "AI 魔改"},
            {"type_id": "擦边短剧", "type_name": "擦边短剧"},
            {"type_id": "真人短剧", "type_name": "真人短剧"},
            {"type_id": "AI 换脸", "type_name": "AI 换脸"},
            {"type_id": "影视综艺", "type_name": "影视综艺"},
        ]
        self.content_lines = [
            {"n": "全部", "v": ""},
            {"n": "热门短剧", "v": "10000000-0000-4000-8000-0000000000c0"},
            {"n": "原创短剧", "v": "10000000-0000-4000-8000-000000000002"},
            {"n": "AI 短剧", "v": "10000000-0000-4000-8000-0000000000b3"},
            {"n": "AI 漫剧", "v": "10000000-0000-4000-8000-000000000003"},
            {"n": "AI 魔改", "v": "10000000-0000-4000-8000-0000000000b1"},
            {"n": "擦边短剧", "v": "10000000-0000-4000-8000-000000000005"},
            {"n": "真人短剧", "v": "10000000-0000-4000-8000-0000000000b0"},
            {"n": "AI 换脸", "v": "10000000-0000-4000-8000-0000000000b2"},
            {"n": "影视综艺", "v": "10000000-0000-4000-8000-0000000000b4"},
        ]
        self.status_list = [{"n": "全部", "v": ""}, {"n": "连载中", "v": "ongoing"}, {"n": "已完结", "v": "completed"}]
        self.sort_list = [{"n": "最热", "v": ""}, {"n": "最新", "v": "latest"}]

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

    def _cards(self, html):
        items, seen = [], set()
        for m in re.finditer(r'<a\b[^>]*href="(/drama/([0-9a-fA-F-]{36})/?)"[^>]*>([\s\S]*?)</a\s*>', html or "", re.I):
            did = m.group(2).lower()
            if did in seen:
                continue
            seen.add(did)
            body = m.group(3)
            img = re.search(r'<img[^>]+src="([^"]+)"', body)
            src = img.group(1) if img else ""
            altm = re.search(r'<img[^>]+alt="([^"]*)"', body)
            name = (altm.group(1).strip() if altm and altm.group(1).strip() else "")
            if not name:
                tm = re.search(r'drama-card-link__title[^>]*>([^<]+)<', body)
                name = tm.group(1).strip() if tm else ""
            badge = re.search(r'drama-card-link__access--([a-z]+)', body)
            heat = re.search(r'drama-card-link__heat">[^0-9]*([0-9.万千]+)<', body) or re.search(r'🔥\s*([\d.]+万?)', body)
            update = re.search(r'drama-card-link__update[^>]*>([^<]+)<', body)
            remarks = " ".join(x for x in (
                {"free": "免费", "vip": "会员", "coin": "金币"}.get(badge.group(1), "") if badge else "",
                update.group(1).strip() if update else "",
                ("热度" + heat.group(1)) if heat else "",
            ) if x)
            items.append({"vod_id": did, "vod_name": name or "未知", "vod_pic": src, "vod_remarks": remarks})
        return items

    def _load_classes(self):
        html = self._get(self.host + "/browse/")
        classes, seen = [], set()
        for m in re.finditer(r'<a\b[^>]*href="([^"]*?/browse/\?[^"]*?)"[^>]*>([\s\S]*?)</a\s*>', html or "", re.I):
            href = m.group(1).replace("&amp;", "&")
            lm = re.search(r'[?&]line=([0-9a-fA-F-]{36})', href, re.I)
            if not lm:
                continue
            lid = lm.group(1)
            if lid.lower() in seen:
                continue
            name = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if not name or name in ("首页", "分类"):
                continue
            seen.add(lid.lower())
            classes.append({"type_id": lid, "type_name": name})
        if classes:
            return classes + [{"type_id": "", "type_name": "全部"}]
        return self.classes + [{"type_id": "", "type_name": "全部"}]

    def homeContent(self, filter):
        classes = self._load_classes()
        filters = {c["type_id"]: [
            {"key": "status", "name": "状态", "value": self.status_list},
            {"key": "sort", "name": "排序", "value": self.sort_list},
            {"key": "line", "name": "内容线", "value": self.content_lines},
        ] for c in classes}
        return {"class": classes, "filters": filters, "list": self._cards(self._get(self.host + "/"))}

    def homeVideoContent(self):
        return self.categoryContent("", "1", False, {})

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        if pg < 1:
            pg = 1
        tid = str(tid or "")
        extend = extend or {}
        # 筛选里的 line 优先于 tid
        line = str(extend.get("line") or "")
        if line and re.fullmatch(r"[0-9a-fA-F-]{36}", line):
            tid = line
        q = []
        if re.fullmatch(r"[0-9a-fA-F-]{36}", tid) or tid == "":
            if tid:
                q.append("line=" + quote(tid))
            if extend.get("status"):
                q.append("status=" + quote(str(extend["status"])))
            if extend.get("sort"):
                q.append("sort=" + quote(str(extend["sort"])))
            q.append("page=%d" % pg)
            url = self.host + "/browse/?" + "&".join(q)
        else:
            url = "%s/category/%s/?page=%d" % (self.host, quote(tid), pg)
            if extend.get("status"):
                url += "&status=" + quote(str(extend["status"]))
            if extend.get("sort"):
                url += "&sort=" + quote(str(extend["sort"]))

        html = self._get(url)
        items = self._cards(html)
        pagecount = 1
        for pm in re.finditer(r"[?&]page=(\d+)", html or ""):
            try:
                pagecount = max(pagecount, int(pm.group(1)))
            except Exception:
                pass
        if not items:
            return {"page": pg, "pagecount": pg, "limit": 0, "total": 0, "list": []}
        if pagecount < pg:
            pagecount = pg
        # 若本页仍有内容且 HTML 里出现更大页码，继续允许翻
        if items and pagecount <= pg:
            pagecount = pg + 1
        return {
            "page": pg,
            "pagecount": pagecount,
            "limit": len(items),
            "total": pagecount * len(items),
            "list": items,
        }

    def _detail_api(self, did):
        d = self._api("/api/toc/v1/dramas/" + did)
        if isinstance(d, dict) and d.get("code"):
            d = d.get("detail") or d.get("data") or d
        if not isinstance(d, dict) or not d.get("id"):
            return None, []
        meta = {
            "title": d.get("title", ""), "cover": d.get("coverUrl", ""),
            "desc": d.get("description", ""), "tags": ",".join(d.get("tags") or []),
            "heat": str(d.get("heat") or ""),
            "pay": {"vip_only": "会员", "coin_only": "金币", "both": "免费"}.get(d.get("payMode") or "", ""),
        }
        eps = [{"id": e.get("id", ""), "no": int(e.get("indexNo") or e.get("index") or 0),
                "title": e.get("title") or ("第%s集" % (e.get("indexNo") or e.get("index") or "")),
                "locked": bool(e.get("locked")), "url": e.get("seoContentUrl") or ""}
               for e in (d.get("episodes") or []) if isinstance(e, dict)]
        return meta, eps

    def detailContent(self, ids):
        did = str(ids[0]).strip() if ids else ""
        m = re.search(r"[0-9a-fA-F-]{36}", did)
        did = m.group().lower() if m else ""
        if not did:
            return {"list": []}
        meta, eps = self._detail_api(did)
        if not eps:
            return {"list": []}
        # 尝试补全缺失的 m3u8
        base, width = "", 2
        for e in eps:
            mm = re.search(r"^(.*/)(ep(\d+)/ep\d+\.m3u8)$", e["url"] or "")
            if mm:
                base, width = mm.group(1), len(mm.group(3))
                break
        if base:
            for e in eps:
                if not e["url"] and e["no"] > 0:
                    n = str(e["no"]).zfill(width)
                    e["url"] = "%sep%s/ep%s.m3u8" % (base, n, n)
        vod = {
            "vod_id": did, "vod_name": meta.get("title", ""), "vod_pic": meta.get("cover", ""),
            "type_name": meta.get("tags", ""), "vod_year": "", "vod_area": "",
            "vod_remarks": " ".join(x for x in (
                ("更新至%d集" % len(eps)) if eps else "", meta.get("pay", ""),
                ("热度" + meta["heat"]) if meta.get("heat") else "",
            ) if x),
            "vod_actor": "", "vod_director": "", "vod_content": meta.get("desc", ""),
        }
        names, urls = [], []
        for e in sorted(eps, key=lambda x: x["no"]):
            if e["url"]:
                names.append("七猫短剧")
                urls.append("%s$%s" % (e["title"], e["url"]))
        if names:
            vod["vod_play_from"] = "$$$".join(names)
            vod["vod_play_url"] = "#".join(urls)
        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        items = []
        data = self._api("/api/toc/v1/search?q=" + quote(str(key or ""), safe=""))
        arr = data if isinstance(data, list) else (data.get("items") or data.get("data") or [] if isinstance(data, dict) else [])
        for d in arr:
            if not isinstance(d, dict) or not d.get("id"):
                continue
            pay = {"vip_only": "会员", "coin_only": "金币", "both": "免费"}.get(d.get("payMode") or "", "")
            if not pay and d.get("isVipBadge"):
                pay = "会员"
            remarks = " ".join(x for x in (
                pay, ("共%d集" % d["episodeCount"]) if d.get("episodeCount") else "",
                ("热度%d" % d["heat"]) if d.get("heat") else "",
            ) if x)
            items.append({"vod_id": d["id"], "vod_name": d.get("title", ""),
                          "vod_pic": d.get("coverUrl", ""), "vod_remarks": remarks})
        return {"page": 1, "pagecount": 1, "limit": len(items), "total": len(items), "list": items}

    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()
        # 若是 /play/ 链接，尝试解析真实 m3u8
        m = re.search(r"/play/([0-9a-fA-F-]{36})/[^?]*[?&]episodeId=([0-9a-fA-F-]{36})", url, re.I)
        if m:
            did, eid = m.group(1), m.group(2).lower()
            d = self._api("/api/toc/v1/dramas/" + did)
            if isinstance(d, dict) and d.get("code"):
                d = d.get("detail") or d.get("data") or d
            eps = d.get("episodes") if isinstance(d, dict) else None
            if isinstance(eps, list):
                for e in eps:
                    if isinstance(e, dict) and str(e.get("id", "")).lower() == eid and e.get("seoContentUrl"):
                        url = e["seoContentUrl"]
                        break
        if not url.startswith("http"):
            return {"parse": 0, "playUrl": "", "url": "", "header": self.headers}
        header = dict(self.headers)
        header["Referer"] = self.host + "/"
        return {"parse": 0, "playUrl": "", "url": url, "header": header}
