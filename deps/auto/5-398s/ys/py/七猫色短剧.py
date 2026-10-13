# coding=utf-8
"""
七猫短剧 Spider（无限向下翻页版）
------------------------------------------------------------------
翻页原理：
  七猫 SSR 页面只有首屏 24 条，offset 参数无效。
  真正的翻页通过 Next.js RSC (React Server Components) 请求：
    - 请求头带  RSC: 1
    - Accept:   text/x-component
    - 每次需带上一次响应里拿到的 _rsc hash
    - 参数追加 offset=（已加载数量）
  RSC 响应是一个 JSON/文本流，里面包含新一批 items 的 JSON。
  从 Flight Data 里解析出 items 数组即可。

本脚本的策略：
  1. 首次请求（不带 RSC）拿首屏 HTML，同时抓取 _rsc hash 备用；
  2. 每次翻页请求带 RSC 头 + _rsc hash + offset=N*24；
  3. 从响应的 Flight Data 中解析新增 items；
  4. 若 items 为空或 hasMore=false，则结束；
  5. categoryContent 每次只返回本页 24 条，pagecount=pg+1 驱动播放器继续翻页。
"""
import re
import json
import requests
from urllib.parse import quote, unquote
from base.spider import Spider


class Spider(Spider):
    def getName(self):
        return "七猫短剧"

    def init(self, extend=""):
        self.host = "https://7maoduanju.com"
        if isinstance(extend, str) and extend.strip().startswith("http"):
            self.host = extend.strip().rstrip("/")

        self.base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Referer": self.host + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        self.rsc_headers = dict(self.base_headers)
        self.rsc_headers["RSC"] = "1"
        self.rsc_headers["Accept"] = "text/x-component"

        self.session = requests.Session()
        self.session.headers.update(self.base_headers)

        self.page_size = 24
        # 缓存每个分类的 _rsc hash（首次请求后写入）
        self._rsc_cache = {}

        # ============ 筛选标签配置 ============
        self.content_lines = [
            {"n": "全部",     "v": ""},
            {"n": "热门短剧", "v": "10000000-0000-4000-8000-0000000000c0"},
            {"n": "原创短剧", "v": "10000000-0000-4000-8000-000000000002"},
            {"n": "AI 短剧",  "v": "10000000-0000-4000-8000-0000000000b3"},
            {"n": "AI 漫剧",  "v": "10000000-0000-4000-8000-000000000003"},
            {"n": "AI 魔改",  "v": "10000000-0000-4000-8000-0000000000b1"},
            {"n": "擦边短剧", "v": "10000000-0000-4000-8000-000000000005"},
            {"n": "真人短剧", "v": "10000000-0000-4000-8000-0000000000b0"},
            {"n": "AI 换脸",  "v": "10000000-0000-4000-8000-0000000000b2"},
            {"n": "影视综艺", "v": "10000000-0000-4000-8000-0000000000b4"},
        ]
        self.status_list = [
            {"n": "全部",   "v": ""},
            {"n": "连载中", "v": "ongoing"},
            {"n": "已完结", "v": "completed"},
        ]
        self.sort_list = [
            {"n": "最热", "v": ""},
            {"n": "最新", "v": "latest"},
        ]

    # ==================== HTTP 辅助 ====================
    def _get(self, url, rsc=False):
        headers = self.rsc_headers if rsc else self.base_headers
        try:
            r = self.session.get(url, headers=headers, timeout=20, verify=False)
            r.encoding = "utf-8"
            if r.status_code == 200 and r.text:
                return r.text
        except Exception:
            pass
        return ""

    def _api(self, path):
        try:
            r = self.session.get(self.host + path, headers=self.base_headers,
                                 timeout=15, verify=False)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []

    # ==================== 卡片解析 ====================
    _CARD_RE = re.compile(
        r'<a\s+class="drama-card-link"\s+href="(/drama/([0-9a-f-]{36})/?)"[^>]*>(.*?)</a>',
        re.S,
    )

    def _card_from_html(self, html):
        """从 SSR HTML 里解析卡片"""
        items = []
        for m in self._CARD_RE.finditer(html or ""):
            did = m.group(2)
            body = m.group(3)
            img = re.search(r'<img[^>]+src="([^"]+)"[^>]*alt="([^"]*)"', body)
            if not img:
                img = re.search(r'<img[^>]+alt="([^"]*)"[^>]*src="([^"]+)"', body)
                if img:
                    alt, src = img.group(1), img.group(2)
                else:
                    continue
            else:
                src, alt = img.group(1), img.group(2)

            badge = re.search(r'drama-card-link__access--([a-z]+)', body)
            heat = re.search(r'drama-card-link__heat">[^0-9]*([0-9.万千]+)<', body)
            update = re.search(r'drama-card-link__update">([^<]+)<', body)
            remarks = " ".join(x for x in (
                {"free": "免费", "vip": "会员", "coin": "金币"}.get(badge.group(1), "") if badge else "",
                update.group(1) if update else "",
                ("热度" + heat.group(1)) if heat else "",
            ) if x)
            items.append({
                "vod_id": did,
                "vod_name": alt.strip(),
                "vod_pic": src,
                "vod_remarks": remarks,
            })
        return items

    def _card_from_flight(self, text):
        """从 Flight Data 里解析 items 数组"""
        items = []
        # 找形如 [{"id":"...","title":"...","coverUrl":"...",...}, ...] 的数组
        # 用括号平衡法逐个提取对象
        for m in re.finditer(r'\{\\?"id\\?":\\?"[0-9a-f-]{36}\\?"', text or ""):
            start = m.start()
            # 向前找最近的 '{'
            obj_start = text.rfind('{', 0, start + 1)
            if obj_start < 0:
                continue
            obj = self._balanced_obj(text, obj_start)
            if not obj:
                continue
            try:
                # 反转义 \" → "
                obj2 = obj.replace('\\"', '"').replace('\\/', '/')
                d = json.loads(obj2)
            except Exception:
                continue
            if not isinstance(d, dict) or not d.get("id"):
                continue
            items.append({
                "vod_id": d.get("id"),
                "vod_name": d.get("title", ""),
                "vod_pic": d.get("coverUrl", ""),
                "vod_remarks": " ".join(x for x in (
                    {"vip_only": "会员", "coin_only": "金币", "both": "免费"}.get(d.get("payMode") or "", ""),
                    ("更新至%d集" % d["episodeCount"]) if d.get("episodeCount") else "",
                    ("热度%d" % d["heat"]) if d.get("heat") else "",
                ) if x),
            })
        # 去重
        seen = set()
        out = []
        for it in items:
            if it["vod_id"] in seen:
                continue
            seen.add(it["vod_id"])
            out.append(it)
        return out

    @staticmethod
    def _balanced_obj(text, start):
        """从 text[start]='{' 开始提取配平的对象字符串"""
        if start < 0 or start >= len(text) or text[start] != '{':
            return ""
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
        return ""

    # ==================== RSC hash 提取 ====================
    @staticmethod
    def _extract_rsc(html):
        """从 HTML 里提取 _rsc hash"""
        for pat in (r'[?&]_rsc=([A-Za-z0-9_\-]+)', r'"_rsc":"([A-Za-z0-9_\-]+)"'):
            m = re.search(pat, html or "")
            if m:
                return m.group(1)
        return ""

    # ==================== 首页 ====================
    def _sections(self, html):
        secs = []
        for m in re.finditer(
                r'<section class="home-block">.*?<h2 class="home-block__title">([^<]+)</h2>'
                r'<a class="home-block__more" href="/category/([^"/]+)/?"',
                html or "", re.S):
            secs.append({"type_id": unquote(m.group(2)), "type_name": m.group(1).strip()})
        return secs

    def homeContent(self, filter):
        html = self._get(self.host + "/")
        sections = self._sections(html)

        classes, seen = [], set()
        for s in sections:
            if s["type_id"] not in seen:
                seen.add(s["type_id"])
                classes.append({"type_id": s["type_id"], "type_name": s["type_name"]})

        preset = [
            {"type_id": "全部",     "type_name": "全部"},
            {"type_id": "热门短剧", "type_name": "热门短剧"},
            {"type_id": "原创短剧", "type_name": "原创短剧"},
            {"type_id": "AI 短剧",  "type_name": "AI 短剧"},
            {"type_id": "AI 漫剧",  "type_name": "AI 漫剧"},
            {"type_id": "AI 魔改",  "type_name": "AI 魔改"},
            {"type_id": "擦边短剧", "type_name": "擦边短剧"},
            {"type_id": "真人短剧", "type_name": "真人短剧"},
            {"type_id": "AI 换脸",  "type_name": "AI 换脸"},
            {"type_id": "影视综艺", "type_name": "影视综艺"},
        ]
        for p in preset:
            if p["type_id"] not in seen:
                seen.add(p["type_id"])
                classes.append(p)

        filters = {c["type_id"]: [
            {"key": "status", "name": "状态",   "value": self.status_list},
            {"key": "sort",   "name": "排序",   "value": self.sort_list},
            {"key": "line",   "name": "内容线", "value": self.content_lines},
        ] for c in classes}

        return {"class": classes, "filters": filters, "list": self._card_from_html(html)}

    def homeVideoContent(self):
        return {"list": self._card_from_html(self._get(self.host + "/"))}

    # ==================== 分类浏览 ====================
    def _build_browse_url(self, tid, extend):
        """构造基础浏览 URL（不含 offset / _rsc）"""
        tid = str(tid or "").strip()
        extend = extend or {}

        # tid 是 uuid → 走 /browse/?line=<uuid>
        if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", tid):
            base = self.host + "/browse/"
            params = {"line": tid}
        elif tid and tid != "全部":
            base = self.host + "/category/" + quote(tid, safe="") + "/"
            params = {}
        else:
            base = self.host + "/browse/"
            params = {}

        line_v = extend.get("line", "") or params.get("line", "")
        if line_v:
            params["line"] = line_v
        if extend.get("status"):
            params["status"] = extend["status"]
        if extend.get("sort"):
            params["sort"] = extend["sort"]

        if params:
            sep = "&" if "?" in base else "?"
            base += sep + "&".join("%s=%s" % (k, quote(str(v), safe=""))
                                    for k, v in params.items())
        return base

    def categoryContent(self, tid, pg, filter, extend):
        """
        无限向下翻页：
          pg=1 → 请求首屏 HTML（不带动 offset），解析 24 条
          pg>=2 → 请求 RSC 接口（带 _rsc + offset），解析新增 24 条
        """
        pg = int(pg) if str(pg).isdigit() else 1
        base_url = self._build_browse_url(tid, extend)
        cache_key = base_url

        # -------- 第一页 --------
        if pg == 1:
            html = self._get(base_url)  # 普通 SSR
            items = self._card_from_html(html)

            # 保存 _rsc hash 供后续翻页使用
            rsc = self._extract_rsc(html)
            if rsc:
                self._rsc_cache[cache_key] = rsc

            if not items:
                return {"page": 1, "pagecount": 1, "limit": 0, "total": 0, "list": []}

            return {
                "page": 1,
                "pagecount": 2,        # 只要本页满 24 条，就让播放器请求第 2 页
                "limit": self.page_size,
                "total": self.page_size * 2,
                "list": items,
            }

        # -------- 第 N 页（RSC） --------
        offset = (pg - 1) * self.page_size
        rsc = self._rsc_cache.get(cache_key, "")

        # 拼接 RSC 请求 URL
        rsc_url = base_url + ("&" if "?" in base_url else "?") + "offset=%d" % offset
        if rsc:
            rsc_url += "&_rsc=" + rsc

        # 用 RSC 头请求
        text = self._get(rsc_url, rsc=True)
        if not text:
            # 回退：直接请求普通 HTML（虽然大概率仍是首屏，但保底）
            text = self._get(rsc_url)

        # 从 Flight Data 里解析 items
        items = self._card_from_flight(text)
        if not items:
            # 保底：也尝试从 HTML 里解
            items = self._card_from_html(text)

        if not items:
            # 到底
            return {
                "page": pg, "pagecount": pg,
                "limit": 0,
                "total": (pg - 1) * self.page_size,
                "list": [],
            }

        # 更新 hash（每次响应可能返回新 hash）
        new_rsc = self._extract_rsc(text)
        if new_rsc:
            self._rsc_cache[cache_key] = new_rsc

        # 到底判定：本页不足 24 条 或 hasMore=false
        has_more = None
        m = re.search(r'"hasMore"\s*:\s*(true|false)', text)
        if m:
            has_more = (m.group(1) == "true")

        if has_more is False or len(items) < self.page_size:
            pagecount = pg
        else:
            pagecount = pg + 1

        return {
            "page": pg,
            "pagecount": pagecount,
            "limit": self.page_size,
            "total": pagecount * self.page_size,
            "list": items,
        }

    # ==================== 详情 ====================
    def _episodes_json(self, html):
        eps = []
        for m in re.finditer(
                r'\\"id\\":\\"([0-9a-f-]{36})\\",\\"indexNo\\":(\d+),\\"title\\":\\"([^\\]+?)\\",'
                r'\\"locked\\":(true|false)(?:[^}]*?\\"seoContentUrl\\":\\"([^\\]+?)\\")?',
                html or ""):
            eps.append({"id": m.group(1), "no": int(m.group(2)), "title": m.group(3),
                        "locked": m.group(4) == "true", "url": m.group(5) or ""})
        return eps

    def _episodes_anchor(self, html):
        eps = []
        for m in re.finditer(
                r'<a class="drama-detail__ep[^"]*" title="(第\d+集)，([^"]+)"[^>]*'
                r'href="(/play/[0-9a-f-]{36}/\?episodeId=[0-9a-f-]{36})"',
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

    # ==================== 搜索 ====================
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

    # ==================== 播放 ====================
    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()
        if not url.startswith("http"):
            return {"parse": 0, "playUrl": "", "url": "", "header": self.base_headers}
        header = dict(self.base_headers)
        header["Referer"] = self.host + "/"
        return {"parse": 0, "playUrl": "", "url": url, "header": header}