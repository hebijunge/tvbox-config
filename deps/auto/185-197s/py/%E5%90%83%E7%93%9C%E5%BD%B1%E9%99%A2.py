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
        self.site = "https://www.chiguafilm.com"
        self.name = "吃瓜影院"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": self.site,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.s = self.session = self.sess = _requests.Session() if _requests else None
        self.cates = [
            ("1", "电影"), ("2", "连续剧"), ("3", "综艺"), ("4", "动漫"),
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
        for m in re.finditer(
                r'<a[^>]+class="[^"]*vodlist_thumb[^"]*"[^>]+href="(/index\.php/vod/detail/id/(\d+)\.html)"[^>]*title="([^"]+)"[^>]*>',
                html):
            href, vid, title = m.group(1), m.group(2), self._tx(m.group(3))
            if not title or vid in seen:
                continue
            seen.add(vid)
            pm = re.search(r'data-original="([^"]+)"', m.group(0))
            if not pm:
                pm = re.search(r'data-original="([^"]+)"', html[m.end():m.end() + 600])
            pic = self._u(pm.group(1)) if pm else ""
            seg = html[m.end():m.end() + 600]
            rm = re.search(r'<span class="pic_text[^"]*">([^<]{1,24})</span>', seg)
            remarks = self._tx(rm.group(1)) if rm else ""
            items.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
            })
        return items

    def _filters(self):
        fclass = [{"n": "全部", "v": ""}]
        for n in ["喜剧", "爱情", "恐怖", "动作", "科幻", "伦理", "剧情", "战争",
                  "警匪", "犯罪", "动画", "奇幻", "武侠", "冒险", "枪战", "悬疑",
                  "惊悚", "经典", "青春", "文艺", "微电影", "古装", "历史", "运动",
                  "农村", "儿童", "网络电影"]:
            fclass.append({"n": n, "v": n})
        area = [{"n": "全部", "v": ""}]
        for n in ["大陆", "香港", "台湾", "美国", "法国", "英国", "日本",
                  "韩国", "德国", "泰国", "印度", "意大利", "西班牙", "加拿大", "其他"]:
            area.append({"n": n, "v": n})
        year = [{"n": "全部", "v": ""}] + [{"n": str(y), "v": str(y)} for y in range(2026, 2009, -1)]
        flt = [{"key": "class", "name": "类型", "value": fclass},
               {"key": "area", "name": "地区", "value": area},
               {"key": "year", "name": "年份", "value": year}]
        return {cid: flt for cid, _name in self.cates}

    def _get_extend(self, extend, key):
        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except Exception:
                return ""
        v = (extend or {}).get(key, "")
        return v if isinstance(v, str) else ""

    def _has_filter(self, extend):
        return any(self._get_extend(extend, k) for k in ("class", "area", "year"))

    def _show_url(self, tid, pg, extend):
        from urllib.parse import quote
        parts = ["index.php/vod/show"]
        cls = self._get_extend(extend, "class")
        area = self._get_extend(extend, "area")
        year = self._get_extend(extend, "year")
        if cls:
            parts.append("class/" + quote(cls, safe=""))
        if area:
            parts.append("area/" + quote(area, safe=""))
        if year:
            parts.append("year/" + year)
        parts.append("id/" + tid)
        if pg > 1:
            parts.append("page/" + str(pg))
        return self.site + "/" + "/".join(parts) + ".html"

    def init(self, extend=""):
        return None

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

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        tid = str(tid).strip()
        if self._has_filter(extend):
            url = self._show_url(tid, pg, extend)
        elif pg <= 1:
            url = "{0}/index.php/vod/type/id/{1}.html".format(self.site, tid)
        else:
            url = "{0}/index.php/vod/type/id/{1}/page/{2}.html".format(self.site, tid, pg)
        try:
            html = self._get(url)
        except Exception:
            html = ""
        items = self._parse_cards(html) if html else []
        pagecount = pg + 1 if len(items) >= 20 else pg
        return {"list": items, "page": pg, "pagecount": pagecount,
                "limit": 24, "total": pagecount * 24}

    def _parse_lines(self, html):
        # 从播放页解析全部线路：NumTab 名称 <-> play_list_box 选集（按 div 切分，兼容多线路）
        names = []
        m = re.search(r'id="NumTab">(.*?)</div>', html, re.S)
        if m:
            names = [self._tx(n) for n in re.findall(r'&nbsp;([^<]{1,16})</a>', m.group(1))]
        chunks = re.split(r'<div class="play_list_box[^"]*">', html)
        lines = []
        for i, box in enumerate(chunks[1:], 1):
            by_sid, order = {}, []
            for em in re.finditer(
                    r'href="(/index\.php/vod/play/id/\d+/sid/(\d+)/nid/(\d+)\.html)"[^>]*>([^<]{1,32})</a>',
                    box):
                sid = em.group(2)
                name = self._tx(em.group(4)) or ("第%s集" % em.group(3))
                u = self._u(em.group(1))
                if sid not in by_sid:
                    by_sid[sid] = ([], set())
                    order.append(sid)
                eps, seen = by_sid[sid]
                if u in seen:
                    continue
                seen.add(u)
                eps.append("{0}${1}".format(name, u))
            for sid in order:
                eps = by_sid[sid][0]
                if not eps:
                    continue
                lname = names[i - 1].strip() if i - 1 < len(names) and names[i - 1].strip() else "线路%s" % sid
                lines.append((lname, eps))
        # 兜底：box 切分失败时整页按 sid 分组
        if not lines:
            by_sid, order = {}, []
            for em in re.finditer(
                    r'href="(/index\.php/vod/play/id/\d+/sid/(\d+)/nid/(\d+)\.html)"[^>]*>([^<]{1,32})</a>',
                    html):
                sid = em.group(2)
                name = self._tx(em.group(4)) or ("第%s集" % em.group(3))
                u = self._u(em.group(1))
                if sid not in by_sid:
                    by_sid[sid] = ([], set())
                    order.append(sid)
                eps, seen = by_sid[sid]
                if u in seen:
                    continue
                seen.add(u)
                eps.append("{0}${1}".format(name, u))
            for j, sid in enumerate(order):
                eps = by_sid[sid][0]
                lname = names[j].strip() if j < len(names) and names[j].strip() else "线路%s" % sid
                lines.append((lname, eps))
        return lines

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else str(ids)
        m0 = re.search(r"(\d+)", str(vid))
        if not m0:
            return {"list": []}
        vid = m0.group(1)
        try:
            html = self._get("{0}/index.php/vod/detail/id/{1}.html".format(self.site, vid))
        except Exception:
            return {"list": []}
        if not html:
            return {"list": []}
        tm = re.search(r"<title>([^<]{2,60})</title>", html)
        title = self._tx(tm.group(1)).split(" - ")[0] if tm else vid
        title = re.sub(r"\s*\(\d{4}\)\s*", "", title).strip() or vid
        pm = re.search(r'class="vodlist_thumb lazyload"[^>]+data-original="([^"]+)"', html)
        pic = self._u(pm.group(1)) if pm else ""
        am = re.search(r"<span>主演：</span>(.*?)</li>", html, re.S)
        actor = self._tx(am.group(1)) if am else ""
        dm = re.search(r"<span>导演：</span>(.*?)</li>", html, re.S)
        director = self._tx(dm.group(1)) if dm else ""
        ym = re.search(r"\((\d{4})\)", tm.group(1)) if tm else None
        year = ym.group(1) if ym else ""
        ds = re.search(r"剧情简介[：:](.*?)(?:</div>|<div class=\"btn)", html, re.S)
        desc = self._tx(ds.group(1)) if ds else ""
        # 选集在播放页：取首个播放入口进播放页解析全部线路
        play_from, play_url = [], []
        pm2 = re.search(r'href="(/index\.php/vod/play/id/\d+/sid/\d+/nid/\d+\.html)"', html)
        if pm2:
            try:
                ph = self._get(self._u(pm2.group(1)), referer=self.site)
            except Exception:
                ph = ""
            if ph:
                for lname, eps in self._parse_lines(ph):
                    play_from.append(lname)
                    play_url.append("#".join(eps))
        vod = {
            "vod_id": vid, "vod_name": title, "vod_pic": pic,
            "vod_year": year, "vod_actor": actor, "vod_director": director,
            "vod_content": desc,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }
        return {"list": [vod]}

    def searchContent(self, key, quick=False, pg="1"):
        # 站方 /vod/search.html POST 极慢，改走 suggest 联想接口
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
        found = ""
        if html:
            # 播放地址藏在 xgplayer iframe 的 url 参数里
            m = re.search(r'<iframe[^>]*src="([^"]*xgplayer[^"]+)"', html)
            if m:
                try:
                    from urllib.parse import unquote, urlparse, parse_qs
                    src = _html_unescape(m.group(1))
                    q = parse_qs(urlparse(src).query)
                    if q.get("url"):
                        found = q["url"][0]
                    else:
                        m2 = re.search(r"[?&]url=([^&]+)", src)
                        if m2:
                            found = unquote(m2.group(1))
                except Exception:
                    pass
            if not found:
                m3 = re.search(r'(https?://[^\\s"\'<>]+\.m3u8[^\\s"\'<>]*)', html)
                if m3:
                    found = _html_unescape(m3.group(1))
        return {"parse": 0, "url": found, "header": dict(self.header)}

    def localProxy(self, param):
        return None
