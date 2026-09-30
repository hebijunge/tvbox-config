#!/usr/bin/python
# -*- coding: utf-8 -*-
# 修复说明：原版 playerContent 直接返回片名作为 URL，TMDB 不提供视频流导致无法播放。
# 修复方案：detailContent 通过 CMS 聚合站（量子/暴风/速播/非凡/最大/卧龙/红牛/天空/闪电）搜索真实播放地址，
# playerContent 根据 URL 类型自动设置 parse 标志（m3u8 直链 parse=0，嗅探 parse=1）。
# 优化说明：每个内容保留最多3条播放线路，优先 m3u8；增强 CMS 搜索匹配（支持中文/英文名、年份过滤、自动备选搜索）；
#          若无播放源则返回提示线路，避免空源。
# 新增功能：首页第一分类改为“豆瓣TOP”，自动抓取并匹配TMDB，支持分页；增加“热门推荐”分类，基于TMDB趋势。

import json, requests, re, time
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    from base.spider import Spider as BaseSpider
except Exception:
    BaseSpider = object

class Spider(BaseSpider):
    def getName(self):
        return "全球追更"

    def init(self, extend=""):
        self.key = "2894d9a1baf7812b451de03c801b0281"
        self.ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.ua})
        self.img = "https://images.tmdb.org/t/p/w500"
        self.apis = ["https://api.tmdb.org/3"]

        # 类型映射（包含战争片）
        self.genre_map = {
            "action": 28,
            "romance": 10749,
            "horror": 27,
            "mystery": 9648,
            "thriller": 53,
            "documentary": 99,
            "war": 10752
        }
        # 特殊分类（非类型筛选）
        self.special_map = {
            "long": "runtime",      # 超长大片（时长≥120分钟）
            "toprated": "top_rated",
            "nowplaying": "now_playing",
            "upcoming": "upcoming"
        }

        # 首页导航分类（顺序即显示顺序）- 第一个改为豆瓣TOP，增加热门推荐
        self.platforms = [
            {"id": "douban_top", "name": "📈 豆瓣TOP", "network": ""},
            {"id": "hot", "name": "🔥 热门推荐", "network": ""},
            {"id": "war", "name": "⚔️ 战争片", "network": ""},
            {"id": "long", "name": "⏳ 超长大片", "network": ""},
            {"id": "toprated", "name": "🏆 高分经典", "network": ""},
            {"id": "nowplaying", "name": "🔥 正在热映", "network": ""},
            {"id": "upcoming", "name": "🚀 即将上映", "network": ""},
            {"id": "action", "name": "🎬 动作片", "network": ""},
            {"id": "romance", "name": "💕 爱情片", "network": ""},
            {"id": "horror", "name": "👻 恐怖片", "network": ""},
            {"id": "mystery", "name": "🔍 悬疑片", "network": ""},
            {"id": "thriller", "name": "⚡ 惊悚片", "network": ""},
            {"id": "documentary", "name": "🎥 纪录片", "network": ""},
            {"id": "domestic", "name": "国内聚合", "network": "2007|1419|1330|1605|1631"},
            {"id": "netflix", "name": "Netflix", "network": "213"},
            {"id": "hbo", "name": "HBO Max", "network": "49"},
            {"id": "disney", "name": "Disney+", "network": "2739"},
            {"id": "appletv", "name": "Apple TV+", "network": "2552"},
            {"id": "amazon", "name": "Amazon Prime", "network": "1024"},
            {"id": "hulu", "name": "Hulu", "network": "453"},
            {"id": "paramount", "name": "Paramount+", "network": "4330"}
        ]

        self.cache = {}
        self.cms_cache = {}
        self.douban_cache = None  # 豆瓣TOP缓存

        # CMS 聚合采集站（9个）
        self.cms_sites = [
            ("量子", "https://cj.lziapi.com/api.php/provide/vod/"),
            ("暴风", "https://bfzyapi.com/api.php/provide/vod/"),
            ("速播", "https://www.subocaiji.com/api.php/provide/vod/"),
            ("非凡", "https://cj.ffzyapi.com/api.php/provide/vod/"),
            ("最大", "https://cj.zdzyapi.com/api.php/provide/vod/"),
            ("卧龙", "https://cj.wolongzy.com/api.php/provide/vod/"),
            ("红牛", "https://cj.hongniuzy.com/api.php/provide/vod/"),
            ("天空", "https://cj.tiankongzy.com/api.php/provide/vod/"),
            ("闪电", "https://cj.shandianzy.com/api.php/provide/vod/"),
        ]

    # ---------- 辅助方法 ----------
    def _get(self, endpoint, params=None):
        params = params or {}
        params["api_key"] = self.key
        for base in self.apis:
            try:
                r = self.session.get(base + endpoint, params=params, timeout=15)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                continue
        return {}

    def _today(self):
        import datetime
        return datetime.datetime.now().strftime("%Y-%m-%d")

    def _filters(self):
        # 保留原过滤器
        return [
            {"key": "sort", "name": "🔥 动态追踪", "value": [
                {"n": "📅 追更模式", "v": "next_episode"},
                {"n": "📆 今日播出", "v": "daily_airing"},
                {"n": "🆕 最新上线", "v": "first_air_date.desc"},
                {"n": "⭐ 综合热度", "v": "popularity.desc"}
            ]},
            {"key": "type", "name": "📺 内容类型", "value": [
                {"n": "🎥 电视剧集", "v": "tv"},
                {"n": "🎬 电影作品", "v": "movie"},
                {"n": "🌸 动漫动画", "v": "anime"},
                {"n": "🎤 综艺节目", "v": "variety"}
            ]}
        ]

    def _pic(self, p):
        return self.img + p if p else ""

    def _has_cjk(self, s):
        return any("\u4e00" <= x <= "\u9fff" for x in (s or ""))

    def _vod(self, item, typ, sort="popularity.desc"):
        mid = str(item.get("id", ""))
        name = item.get("name") or item.get("title") or ""
        remark = "⭐" + str(round(float(item.get("vote_average") or 0), 1))
        date = item.get("first_air_date") or item.get("release_date") or "1900-01-01"
        ck = "info_" + typ + "_" + mid + "_" + sort
        if ck in self.cache:
            return self.cache[ck]

        if not self._has_cjk(name):
            d = self._get(("/movie/" if typ == "movie" else "/tv/") + mid,
                          {"language": "zh-CN", "append_to_response": "alternative_titles,external_ids"})
            alt = ((d.get("alternative_titles") or {}).get("titles") or
                   (d.get("alternative_titles") or {}).get("results") or [])
            for t in alt:
                if t.get("iso_3166_1") == "CN" and t.get("title"):
                    name = t.get("title")
                    break

        if typ != "movie" and sort in ["next_episode", "daily_airing", "first_air_date.desc"]:
            d = self._get("/tv/" + mid, {"language": "zh-CN"})
            ep = d.get("next_episode_to_air") or d.get("last_episode_to_air")
            if ep:
                date = ep.get("air_date") or date
                remark = ("🕒" if d.get("next_episode_to_air") else "✅") + date[5:] + " S" + str(
                    ep.get("season_number") or 0).zfill(2) + "E" + str(ep.get("episode_number") or 0).zfill(2)

        vod = {"vod_id": typ + ":" + mid, "vod_name": name, "vod_pic": self._pic(item.get("poster_path")),
               "vod_remarks": remark, "_date": date}
        self.cache[ck] = vod
        return vod

    # ---------- 豆瓣抓取与TMDB匹配 ----------
    def _fetch_douban_all(self):
        """抓取豆瓣TOP250全部影片，缓存到self.douban_cache"""
        if self.douban_cache is not None:
            return self.douban_cache

        all_movies = []
        for start in range(0, 250, 25):
            try:
                url = f"https://movie.douban.com/top250?start={start}"
                r = self.session.get(url, timeout=10)
                if r.status_code != 200:
                    continue
                html = r.text
                # 提取每个item
                items = re.findall(r'<div class="item">(.*?)</div>\s*</div>', html, re.S)
                for item_html in items:
                    # 名称
                    name_match = re.search(r'<a.*?title="(.*?)"', item_html)
                    if not name_match:
                        name_match = re.search(r'<img.*?alt="(.*?)"', item_html)
                    name = name_match.group(1) if name_match else ""
                    # 年份
                    year_match = re.search(r'<p class="">.*?(\d{4})', item_html, re.S)
                    year = year_match.group(1) if year_match else ""
                    # 评分
                    rating_match = re.search(r'<span class="rating_num".*?>(.*?)</span>', item_html)
                    rating = rating_match.group(1).strip() if rating_match else "0.0"
                    # 图片
                    pic_match = re.search(r'<img.*?src="(.*?)"', item_html)
                    pic = pic_match.group(1) if pic_match else ""
                    if name:
                        all_movies.append({
                            "name": name,
                            "year": year,
                            "rating": rating,
                            "pic": pic
                        })
                time.sleep(0.5)  # 防反爬
            except Exception:
                continue
        self.douban_cache = all_movies
        return all_movies

    def _search_tmdb_best(self, name, year):
        """通过TMDB搜索，返回最匹配的电影结果（dict），若未找到返回None"""
        try:
            params = {"query": name, "year": year, "language": "zh-CN"}
            data = self._get("/search/movie", params)
            results = data.get("results", [])
            if not results:
                # 尝试无年份搜索
                params.pop("year", None)
                data = self._get("/search/movie", params)
                results = data.get("results", [])
            if not results:
                return None
            return results[0]  # 取第一个
        except Exception:
            return None

    # ---------- CMS搜索 ----------
    def _search_cms(self, name, year="", alt_name=""):
        """通过 CMS 聚合采集站搜索真实播放地址，支持中文名与英文名备选，返回最多3条线路，优先 m3u8"""
        if not name:
            return []
        search_names = [name]
        if alt_name and alt_name != name:
            search_names.append(alt_name)

        for query in search_names:
            cache_key = query + "|" + year
            if cache_key in self.cms_cache:
                return self.cms_cache[cache_key]

            all_lines = []

            def fetch(site_name, site_url):
                try:
                    # 先尝试 detail 查询
                    r = self.session.get(site_url, params={"ac": "detail", "wd": query}, timeout=10)
                    if r.status_code != 200:
                        return []
                    data = r.json()
                    items = data.get("list", [])
                    if not items:
                        r2 = self.session.get(site_url, params={"ac": "search", "wd": query}, timeout=10)
                        if r2.status_code != 200:
                            return []
                        data2 = r2.json()
                        search_items = data2.get("list", [])
                        if not search_items:
                            return []
                        first_id = search_items[0].get("vod_id")
                        if first_id:
                            r3 = self.session.get(site_url, params={"ac": "detail", "ids": first_id}, timeout=10)
                            if r3.status_code == 200:
                                data = r3.json()
                                items = data.get("list", [])
                    if not items:
                        return []

                    candidates = []
                    for item in items:
                        vod_name = item.get("vod_name", "")
                        vod_year = item.get("vod_year", "")
                        if any(kw in vod_name for kw in ["解说", "预告", "幕后", "花絮", "福利"]):
                            continue
                        clean_name = ''.join(c for c in name if c.isalnum())
                        clean_vod = ''.join(c for c in vod_name if c.isalnum())
                        if clean_name and clean_vod:
                            if clean_name in clean_vod or clean_vod in clean_name:
                                score = 100 - abs(len(clean_name) - len(clean_vod))
                            else:
                                common = len(set(clean_name) & set(clean_vod))
                                score = common * 10 / max(len(clean_name), 1)
                        else:
                            score = 0
                        if year and vod_year:
                            try:
                                if int(vod_year[:4]) == int(year):
                                    score += 30
                            except:
                                pass
                        candidates.append((score, item))
                    if not candidates:
                        return []
                    candidates.sort(key=lambda x: -x[0])
                    best = candidates[0][1]
                    play_from = best.get("vod_play_from", "")
                    play_url = best.get("vod_play_url", "")
                    if not play_url:
                        return []
                    froms = play_from.split("$$$")
                    urls = play_url.split("$$$")
                    lines = []
                    for f, u in zip(froms, urls):
                        if u.strip():
                            line_name = site_name + "-" + f
                            lines.append((line_name, u))
                    return lines
                except Exception:
                    return []

            with ThreadPoolExecutor(max_workers=len(self.cms_sites)) as executor:
                futures = {executor.submit(fetch, sn, su): (sn, su) for sn, su in self.cms_sites}
                for future in as_completed(futures):
                    lines = future.result()
                    if lines:
                        all_lines.extend(lines)

            seen = set()
            unique_lines = []
            for ln, url in all_lines:
                if url not in seen:
                    seen.add(url)
                    unique_lines.append((ln, url))
            m3u8_lines = [(ln, url) for ln, url in unique_lines if ".m3u8" in url.lower()]
            other_lines = [(ln, url) for ln, url in unique_lines if ".m3u8" not in url.lower()]
            result = (m3u8_lines + other_lines)[:3]

            self.cms_cache[cache_key] = result
            if result:
                return result
        return []

    # ---------- 首页、分类、详情、搜索、播放 ----------
    def homeContent(self, filter, *args):
        fs = self._filters()
        # 为每个分类设置过滤器，豆瓣和热门推荐分类单独置空（无筛选）
        filter_dict = {p["id"]: fs for p in self.platforms}
        filter_dict["douban_top"] = []
        filter_dict["hot"] = []
        return {
            "class": [{"type_id": p["id"], "type_name": p["name"]} for p in self.platforms],
            "filters": filter_dict,
            "list": []
        }

    def categoryContent(self, tid, pg, filter, extend, *args):
        page = int(pg or 1)

        # ---------- 1. 豆瓣TOP ----------
        if tid == "douban_top":
            all_movies = self._fetch_douban_all()
            if not all_movies:
                return {"page": page, "pagecount": 1, "limit": 20, "total": 0, "list": []}
            total = len(all_movies)
            pagecount = (total + 19) // 20
            start = (page - 1) * 20
            end = min(start + 20, total)
            page_movies = all_movies[start:end]

            # 并发搜索TMDB，提升速度
            vod_list_sorted = [None] * len(page_movies)
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_idx = {}
                for idx, movie in enumerate(page_movies):
                    future = executor.submit(self._search_tmdb_best, movie["name"], movie["year"])
                    future_to_idx[future] = idx
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    movie = page_movies[idx]
                    tmdb_result = future.result()
                    if tmdb_result:
                        vod = self._vod(tmdb_result, "movie", "popularity.desc")
                        vod["vod_remarks"] = "豆瓣评分 " + movie["rating"]
                        vod_list_sorted[idx] = vod
                    else:
                        vod_list_sorted[idx] = {
                            "vod_id": "movie:0",
                            "vod_name": movie["name"] + " (未匹配)",
                            "vod_pic": movie["pic"],
                            "vod_remarks": "豆瓣评分 " + movie["rating"]
                        }
            return {
                "page": page,
                "pagecount": pagecount,
                "limit": 20,
                "total": total,
                "list": vod_list_sorted
            }

        # ---------- 2. 热门推荐（基于TMDB趋势） ----------
        if tid == "hot":
            endpoint = "/trending/all/week"
            params = {"page": page, "language": "zh-CN"}
            data = self._get(endpoint, params)
            items = data.get("results", [])
            vod_list = []
            for i in items:
                media_type = i.get("media_type")
                if media_type not in ["movie", "tv"]:
                    continue
                vod = self._vod(i, media_type, "popularity.desc")
                vod_list.append(vod)
            return {
                "page": page,
                "pagecount": data.get("total_pages", 1),
                "limit": 20,
                "total": data.get("total_results", 0),
                "list": vod_list
            }

        # ---------- 3. 类型分类（动作/爱情/恐怖/悬疑/惊悚/纪录片/战争） ----------
        if tid in self.genre_map:
            genre_id = self.genre_map[tid]
            endpoint = "/discover/movie"
            params = {
                "language": "zh-CN",
                "page": page,
                "sort_by": "popularity.desc",
                "with_genres": str(genre_id)
            }
            data = self._get(endpoint, params)
            items = data.get("results", [])
            return {
                "page": page,
                "pagecount": data.get("total_pages", 1),
                "limit": 20,
                "total": data.get("total_results", 0),
                "list": [self._vod(i, "movie", "popularity.desc") for i in items]
            }

        # ---------- 4. 特殊分类（超长大片/高分经典/正在热映/即将上映） ----------
        if tid in self.special_map:
            special = self.special_map[tid]
            if special == "runtime":
                endpoint = "/discover/movie"
                params = {
                    "language": "zh-CN",
                    "page": page,
                    "sort_by": "popularity.desc",
                    "with_runtime.gte": 120
                }
            elif special == "top_rated":
                endpoint = "/movie/top_rated"
                params = {"page": page, "language": "zh-CN"}
            elif special == "now_playing":
                endpoint = "/movie/now_playing"
                params = {"page": page, "language": "zh-CN"}
            elif special == "upcoming":
                endpoint = "/movie/upcoming"
                params = {"page": page, "language": "zh-CN"}
            else:
                return {"page": page, "pagecount": 1, "limit": 20, "total": 0, "list": []}
            data = self._get(endpoint, params)
            items = data.get("results", [])
            return {
                "page": page,
                "pagecount": data.get("total_pages", 1),
                "limit": 20,
                "total": data.get("total_results", 0),
                "list": [self._vod(i, "movie", "popularity.desc") for i in items]
            }

        # ---------- 5. 原有平台网络筛选（Netflix/HBO/Disney+ 等） ----------
        p = next((x for x in self.platforms if x["id"] == tid), None)
        if not p:
            return {"page": page, "pagecount": 1, "limit": 20, "total": 0, "list": []}
        sort = (extend or {}).get("sort") or "popularity.desc"
        typ = (extend or {}).get("type") or "tv"
        media = "movie" if typ == "movie" else "tv"
        endpoint = "/discover/movie" if media == "movie" else "/discover/tv"
        base = {"language": "zh-CN", "page": page,
                "sort_by": "popularity.desc" if sort in ["daily_airing", "next_episode"] else sort}
        if typ == "anime":
            base["with_genres"] = "16"
        if typ == "variety":
            base["with_genres"] = "10764|10767"
        if sort == "daily_airing":
            base["air_date.gte"] = self._today()
            base["air_date.lte"] = self._today()

        items, seen = [], set()
        for net in p["network"].split("|"):
            q = dict(base)
            q["with_networks"] = net
            data = self._get(endpoint, q)
            for i in data.get("results", []):
                mid = str(i.get("id", ""))
                if mid and mid not in seen:
                    seen.add(mid)
                    items.append(i)

        if sort in ["next_episode", "daily_airing", "first_air_date.desc"]:
            items.sort(key=lambda x: x.get("first_air_date") or x.get("release_date") or "", reverse=True)
        else:
            items.sort(key=lambda x: float(x.get("popularity") or 0), reverse=True)

        return {
            "page": page,
            "pagecount": 100,
            "limit": 20,
            "total": 2000,
            "list": [self._vod(i, media, sort) for i in items[:20]]
        }

    def detailContent(self, ids, *args):
        raw = ids[0] if isinstance(ids, list) else ids
        arr = str(raw).split(":", 1)
        typ, mid = (arr[0], arr[1]) if len(arr) == 2 else ("tv", str(raw))
        data = self._get(("/movie/" if typ == "movie" else "/tv/") + mid,
                         {"language": "zh-CN", "append_to_response": "credits,alternative_titles"})
        if not data and typ != "movie":
            typ = "movie"
            data = self._get("/movie/" + mid, {"language": "zh-CN", "append_to_response": "credits,alternative_titles"})
        if not data:
            return {"list": []}

        name = data.get("name") or data.get("title") or ""
        original_name = data.get("original_name") or data.get("original_title") or ""
        year = (data.get("release_date") or data.get("first_air_date") or "")[:4]

        cn_name = name
        if not self._has_cjk(name):
            alt = ((data.get("alternative_titles") or {}).get("titles") or
                   (data.get("alternative_titles") or {}).get("results") or [])
            for t in alt:
                if t.get("iso_3166_1") == "CN" and t.get("title"):
                    cn_name = t["title"]
                    break

        area = ", ".join([c.get("name", "") for c in data.get("production_countries", [])])
        actor = ", ".join([c.get("name", "") for c in (data.get("credits") or {}).get("cast", [])[:8]])
        director = ", ".join([c.get("name", "") for c in (data.get("credits") or {}).get("crew", [])
                              if c.get("job") == "Director"][:3])

        sources = self._search_cms(cn_name, year, original_name)
        if sources:
            play_from = "$$$".join([s[0] for s in sources])
            play_url = "$$$".join([s[1] for s in sources])
        else:
            play_from = "提示"
            play_url = "暂无播放源，请尝试其他资源"

        return {"list": [{
            "vod_id": typ + ":" + mid,
            "vod_name": cn_name,
            "vod_pic": self._pic(data.get("poster_path")),
            "type_name": "电影" if typ == "movie" else "电视剧",
            "vod_year": year,
            "vod_area": area,
            "vod_remarks": "电影" if typ == "movie" else ("已完结" if data.get("status") == "Ended" else "连载中"),
            "vod_actor": actor,
            "vod_director": director,
            "vod_content": data.get("overview") or "暂无剧情简介",
            "vod_play_from": play_from,
            "vod_play_url": play_url
        }]}

    def searchContent(self, key, quick, pg="1", *args):
        page = int(pg or 1)
        data = self._get("/search/multi", {"query": key, "page": page, "language": "zh-CN"})
        return {
            "list": [{
                "vod_id": i.get("media_type", "tv") + ":" + str(i.get("id", "")),
                "vod_name": i.get("title") or i.get("name") or key,
                "vod_pic": self._pic(i.get("poster_path")),
                "vod_remarks": "电影" if i.get("media_type") == "movie" else "剧集"
            } for i in data.get("results", []) if i.get("media_type") in ["movie", "tv"]],
            "page": page,
            "pagecount": data.get("total_pages", 1),
            "total": data.get("total_results", 0)
        }

    def playerContent(self, flag, id, vipFlags, *args):
        if "暂无播放源" in id:
            return {"parse": 0, "url": "", "header": ""}
        parse = 0 if ".m3u8" in id else 1
        return {"parse": parse, "url": id, "header": ""}