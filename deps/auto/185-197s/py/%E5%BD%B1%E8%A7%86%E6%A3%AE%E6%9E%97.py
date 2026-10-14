import re, json, base64
try:
    import requests as _requests
except Exception:
    _requests = None


def _html_unescape(s):
    import html as _h
    return _h.unescape(s) if s else s


class Spider:
    def __init__(self):
        self.site = "https://www.imtlink.com"
        self.name = "影视森林"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": self.site,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.s = self.session = self.sess = _requests.Session() if _requests else None
        self.cates = [
            ("dsj", "电视剧"), ("dianying", "电影"), ("dongman", "动漫"),
            ("zongyi", "综艺"), ("remenduanju", "热门短剧"), ("tiyusaishi", "体育赛事"),
            ("guochanju", "国产剧"), ("oumeiju", "欧美剧"), ("riju", "日剧"),
            ("hanju", "韩剧"), ("gangju", "港剧"), ("taiju", "台剧"),
            ("haiwaiju", "海外剧"), ("xijupian", "喜剧片"), ("dongzuopian", "动作片"),
            ("aiqingpian", "爱情片"), ("kehuanpian", "科幻片"), ("kongbupian", "恐怖片"),
            ("juqingpian", "剧情片"), ("zhanzhengpian", "战争片"), ("xuanyipian", "悬疑片"),
            ("fanzuipian", "犯罪片"), ("maoxianpian", "冒险片"), ("donghuapian", "动画片"),
            ("jingsongpian", "惊悚片"), ("qihuanpian", "奇幻片"), ("jilupian", "纪录片"),
            ("guochandongman", "国产动漫"), ("rihandongman", "日韩动漫"),
            ("oumeidongman", "欧美动漫"), ("gangtaidongman", "港台动漫"),
            ("haiwaidongman", "海外动漫"), ("shuangwenduanju", "爽文短剧"),
            ("lanqiu", "篮球"), ("zuqiu", "足球"),
        ]

    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def action(self, action):
        return {}

    def _get(self, url, referer=None):
        h = dict(self.header)
        if referer:
            h["Referer"] = referer
        if self.s is not None:
            try:
                r = self.s.get(url, headers=h, timeout=12, allow_redirects=True)
                if r.status_code < 400:
                    return r.text
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=12) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def _post(self, url, data):
        h = dict(self.header)
        if self.s is not None:
            try:
                r = self.s.post(url, headers=h, data=data, timeout=12, allow_redirects=True)
                if r.status_code < 400:
                    return r.text
            except Exception:
                pass
        try:
            import urllib.request, urllib.parse
            body = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=h)
            with urllib.request.urlopen(req, timeout=12) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def _u(self, u):
        if not u:
            return u
        u = u.strip()
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        if u.startswith("/"):
            m = re.match(r"(https?://[^/]+)", self.site)
            return (m.group(1) if m else self.site) + u
        return self.site.rstrip("/") + "/" + u.lstrip("/")

    def _tx(self, s):
        return re.sub(r"<[^>]+>", "", _html_unescape(s or "")).strip()

    def _parse_cards(self, html):
        items, seen = [], set()
        for m in re.finditer(r'<a[^>]+href="(/voddetail/(\d+)\.html)"[^>]*title="([^"]+)"[^>]*>', html):
            vid, title = m.group(2), self._tx(m.group(3))
            if not title or vid in seen:
                continue
            seen.add(vid)
            seg = html[m.end():m.end() + 800]
            pm = re.search(r'data-original="([^"]+)"', seg) or re.search(r'data-background="([^"]+)"', seg)
            pic = self._u(pm.group(1)) if pm else ""
            items.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": "",
            })
        return items

    def init(self, extend=""):
        return None

    def _filters(self):
        by = [{"n": "最近更新", "v": "time"}, {"n": "最多播放", "v": "hits"}, {"n": "最好评", "v": "score"}]
        area = [{"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "内地", "v": "内地"},
                {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"}, {"n": "日本", "v": "日本"},
                {"n": "韩国", "v": "韩国"}, {"n": "美国", "v": "美国"}, {"n": "英国", "v": "英国"},
                {"n": "法国", "v": "法国"}, {"n": "德国", "v": "德国"}, {"n": "泰国", "v": "泰国"},
                {"n": "新加坡", "v": "新加坡"}, {"n": "其他", "v": "其他"}]
        cls = [{"n": "全部", "v": ""}, {"n": "剧情", "v": "剧情"}, {"n": "喜剧", "v": "喜剧"},
               {"n": "爱情", "v": "爱情"}, {"n": "动作", "v": "动作"}, {"n": "科幻", "v": "科幻"},
               {"n": "恐怖", "v": "恐怖"}, {"n": "战争", "v": "战争"}, {"n": "犯罪", "v": "犯罪"},
               {"n": "悬疑", "v": "悬疑"}, {"n": "奇幻", "v": "奇幻"}, {"n": "古装", "v": "古装"},
               {"n": "武侠", "v": "武侠"}, {"n": "冒险", "v": "冒险"}, {"n": "动画", "v": "动画"},
               {"n": "纪录", "v": "纪录"}, {"n": "家庭", "v": "家庭"}]
        lang = [{"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"},
                {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"},
                {"n": "日语", "v": "日语"}, {"n": "其它", "v": "其它"}]
        year = [{"n": "全部", "v": ""}] + [{"n": str(y), "v": str(y)} for y in range(2026, 2009, -1)]
        flt = [{"key": "by", "name": "排序", "value": by},
               {"key": "area", "name": "地区", "value": area},
               {"key": "class", "name": "类型", "value": cls},
               {"key": "lang", "name": "语言", "value": lang},
               {"key": "year", "name": "年份", "value": year}]
        return {cid: flt for cid, _name in self.cates}

    def homeContent(self, filter=None):
        cats = [{"type_id": cid, "type_name": name} for cid, name in self.cates]
        try:
            html = self._get(self.site)
            vod_list = self._parse_cards(html) if html else []
        except Exception:
            vod_list = []
        return {"class": cats, "filters": self._filters(), "list": vod_list}

    def homeVideoContent(self):
        try:
            html = self._get(self.site)
            return {"list": self._parse_cards(html) if html else []}
        except Exception:
            return {"list": []}

    def _get_extend(self, extend, key):
        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except Exception:
                return ""
        v = (extend or {}).get(key, "")
        return v if isinstance(v, str) else ""

    def _show_url(self, tid, pg, extend):
        from urllib.parse import quote
        area = quote(self._get_extend(extend, "area"), safe="")
        by = self._get_extend(extend, "by")
        cls = quote(self._get_extend(extend, "class"), safe="")
        lang = quote(self._get_extend(extend, "lang"), safe="")
        year = self._get_extend(extend, "year")
        parts = [tid, area, by, cls, lang, "", "", "", str(pg), "", "", year]
        return "{0}/vodshow/{1}.html".format(self.site, "-".join(parts))

    def _has_filter(self, extend):
        for k in ("by", "area", "class", "lang", "year"):
            if self._get_extend(extend, k):
                return True
        return False

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        tid = str(tid).strip()
        if self._has_filter(extend):
            url = self._show_url(tid, pg, extend)
        elif pg <= 1:
            url = "{0}/vodtype/{1}.html".format(self.site, tid)
        else:
            url = "{0}/vodtype/{1}-{2}.html".format(self.site, tid, pg)
        try:
            html = self._get(url)
        except Exception:
            html = ""
        items = self._parse_cards(html) if html else []
        pagecount = pg + 1 if len(items) >= 20 else pg
        return {"list": items, "page": pg, "pagecount": pagecount,
                "limit": 24, "total": pagecount * 24}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else str(ids)
        m0 = re.search(r"(\d+)", str(vid))
        if not m0:
            return {"list": []}
        vid = m0.group(1)
        try:
            html = self._get("{0}/voddetail/{1}.html".format(self.site, vid))
        except Exception:
            return {"list": []}
        if not html:
            return {"list": []}
        tm = re.search(r'<h3><a href="/voddetail/\d+\.html">([^<]+)</a></h3>', html)
        title = self._tx(tm.group(1)) if tm else ""
        if not title:
            tm2 = re.search(r'《([^》]{1,40})》', html)
            title = tm2.group(1).strip() if tm2 else vid
        pm = re.search(r'<div class="pic"><img[^>]+data-original="([^"]+)"', html)
        pic = self._u(pm.group(1)) if pm else ""
        am = re.search(r'主演：(.*?)</span>', html, re.S)
        actor = ",".join(re.findall(r'>([^<>]{1,16})</a>', am.group(1))) if am else ""
        ym = re.search(r'年份：<a[^>]*>([^<]+)</a>', html)
        year = ym.group(1).strip() if ym else ""
        dm = re.search(r'导演：(.*?)</span>', html, re.S)
        director = ",".join(re.findall(r'>([^<>]{1,16})</a>', dm.group(1))) if dm else ""
        rm = re.search(r'地区：<a[^>]*>([^<]+)</a>', html)
        area = rm.group(1).strip() if rm else ""
        ds = re.search(r'简介：([\s\S]{2,800}?)</div>', html)
        desc = ""
        if ds:
            raw = _html_unescape(ds.group(1))
            raw = re.sub(r"(&amp;\s*;?\s*)+", "", raw)
            desc = self._tx(raw)
        tabs = re.findall(r'data-target="#ewave-playlist-(\d+)">([^<]{1,20})<', html)
        play_from, play_url = [], []
        for sid, label in tabs:
            sec = html.split('id="ewave-playlist-{0}"'.format(sid), 1)
            sec = sec[1].split('id="ewave-playlist-')[0] if len(sec) > 1 else ""
            eps, seen = [], set()
            for em in re.finditer(r'href="(/vodplay/\d+-{0}-\d+\.html)"[^>]*>([^<]{{1,32}})</a>'.format(sid), sec):
                name = self._tx(em.group(2)) or "播放"
                u = self._u(em.group(1))
                if (name, u) in seen:
                    continue
                seen.add((name, u))
                eps.append("{0}${1}".format(name, u))
            if eps:
                play_from.append(label.strip() or "线路{0}".format(sid))
                play_url.append("#".join(eps))
        vod = {
            "vod_id": vid, "vod_name": title, "vod_pic": pic,
            "vod_year": year, "vod_area": area, "vod_actor": actor,
            "vod_director": director, "vod_content": desc,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }
        return {"list": [vod]}

    def searchContent(self, key, quick=False, pg="1"):
        # 注：站方 /vodsearch.html 页面搜索已坏（返回 0 结果），改走 suggest 联想接口
        try:
            from urllib.parse import quote
            txt = self._get("{0}/index.php/ajax/suggest?mid=1&wd={1}".format(
                self.site, quote(str(key), safe="")))
            data = json.loads(txt) if txt else {}
        except Exception:
            return {"list": []}
        items = []
        if isinstance(data, dict) and data.get("code") == 1:
            for it in data.get("list") or []:
                try:
                    vid = str(it.get("id", ""))
                    name = str(it.get("name", "")).strip()
                    if not vid or not name:
                        continue
                    items.append({
                        "vod_id": vid,
                        "vod_name": name,
                        "vod_pic": self._u(it.get("pic", "")),
                        "vod_remarks": "",
                    })
                except Exception:
                    continue
        return {"list": items}

    def playerContent(self, flag, ids, vipFlags=None):
        url = ids[0] if isinstance(ids, (list, tuple)) and ids else str(ids or "")
        url = url.strip()
        if not url:
            return {"parse": 0, "url": "", "header": dict(self.header)}
        if not url.startswith("http"):
            url = self._u(url)
        try:
            html = self._get(url, referer=self.site)
        except Exception:
            html = ""
        if not html:
            return {"parse": 0, "url": "", "header": dict(self.header)}
        found, encrypt = "", "0"
        m = re.search(r"var\s+player_aaaa\s*=\s*(\{.*?\})\s*;?\s*</script>", html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                found = str(data.get("url", "") or "").strip()
                encrypt = str(data.get("encrypt", "0"))
            except Exception:
                found = ""
        if not found:
            m2 = re.search(r'var\s+player_aaaa\s*=\s*\{[^}]*?"url"\s*:\s*"([^"]+)"', html)
            if m2:
                found = m2.group(1)
        if encrypt == "1" and found:
            try:
                from urllib.parse import unquote
                found = unquote(found)
            except Exception:
                pass
        elif encrypt == "2" and found:
            try:
                found = base64.b64decode(found).decode("utf-8", "replace").strip()
            except Exception:
                pass
        if found.startswith("//"):
            found = "https:" + found
        elif found and not found.startswith("http"):
            found = self._u(found)
        return {"parse": 0, "url": found, "header": dict(self.header)}

    def localProxy(self, param):
        return None
