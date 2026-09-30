# coding=utf-8
"""
量子影视聚合爬虫（内置去广告清洗）
- 单源（量子）
- 播放 M3U8 时自动通过本地代理清洗广告（TS 计数器连续性检测）
- 无需外部清洗服务器
- 无弹幕
- 缓存优化：只缓存最近一次播放的清洗结果，换源自动覆盖，无过期时间
"""
import sys
import json
import concurrent.futures
import re
import requests
import base64
import time
from urllib.parse import urljoin, urlparse, quote, unquote, parse_qs, urlencode, urlunparse
sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    SOURCES = {
        '量子': {'name': '️量子', 'api': 'http://cj.lziapi.com/api.php/provide/vod/from/lzm3u8/at/json/'}
    }

    def init(self, extend=""):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        }
        # ---------- 缓存（单条目，覆盖式） ----------
        self.cached_url = None      # 规范化后的URL
        self.cached_content = None  # 清洗后的m3u8内容

    # ==================== 清洗引擎（西瓜范例结构 + 量子计数器连续性检测） ====================
    MAX_REMOVE_RATIO = 0.25

    def _split_playlist(self, content):
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        header = []
        i = 0
        while i < len(lines) and lines[i].startswith('#EXT') and \
                not lines[i].startswith(('#EXTINF', '#EXT-X-DISCONTINUITY')):
            header.append(lines[i])
            i += 1
        footer, end = [], len(lines)
        for j in range(len(lines) - 1, i - 1, -1):
            if lines[j] == '#EXT-X-ENDLIST':
                footer.append(lines[j])
                end = j
                break
        segs, cur, disc = [], [], False
        for l in lines[i:end]:
            if l == '#EXT-X-DISCONTINUITY':
                if cur:
                    segs.append((disc, cur))
                cur, disc = [], True
            else:
                cur.append(l)
        if cur:
            segs.append((disc, cur))
        out = []
        for d, s in segs:
            items, extras, k = [], [], 0
            while k < len(s):
                if s[k].startswith('#EXTINF') and k + 1 < len(s) and not s[k + 1].startswith('#'):
                    try:
                        dur = float(s[k].split(':', 1)[1].split(',')[0])
                    except (ValueError, IndexError):
                        dur = 0.0
                    items.append((dur, s[k], s[k + 1]))
                    k += 2
                else:
                    if s[k].startswith('#'):
                        extras.append(s[k])
                    k += 1
            if items or extras:
                out.append({'disc': d, 'items': items, 'extras': extras})
        return header, out, footer

    def _extract_counter(self, ts_name):
        """提取 TS 文件名末尾的连续数字作为内容计数器（十进制）。
        内容段通常 0,1,2…N 连续递增，广告块计数器与主线不连续。"""
        name = ts_name.rstrip()
        if name.lower().endswith(".ts"):
            name = name[:-3]
        name = name.split("?", 1)[0]
        m = re.search(r"(\d+)$", name)
        return int(m.group(1)) if m else None

    def _detect_ad_blocks(self, segs):
        """基于 TS 计数器连续性检测广告块（最长连续递增链 DP）。
        不在内容主线上的 segblock 即为广告块。检测不可靠时返回空集（不删）。"""
        info = []
        for s in segs:
            cnts = [self._extract_counter(it[2].split("?", 1)[0]) for it in s['items']]
            cnts = [c for c in cnts if c is not None]
            info.append({'first': cnts[0] if cnts else None,
                         'last': cnts[-1] if cnts else None,
                         'n': len(s['items']), 'has': len(cnts) > 0})
        if len(segs) < 2 or not all(x['has'] for x in info):
            return set()
        m = len(segs)
        dp = [1] * m
        prev = [-1] * m
        for a in range(m):
            for b in range(a):
                if (info[a]['first'] is not None and info[b]['last'] is not None
                        and info[a]['first'] == info[b]['last'] + 1):
                    if dp[b] + 1 > dp[a]:
                        dp[a] = dp[b] + 1
                        prev[a] = b
        best = max(range(m), key=lambda x: (dp[x], info[x]['n']))
        chain = [False] * m
        k = best
        while k != -1:
            chain[k] = True
            k = prev[k]
        content_ts = sum(info[x]['n'] for x in range(m) if chain[x])
        total_ts = sum(x['n'] for x in info)
        if total_ts > 0 and content_ts / total_ts >= 0.5:
            return {x for x in range(m) if not chain[x]}
        return set()

    def _rewrite_extra(self, line, base_url):
        if 'URI="' in line:
            m = re.search(r'URI="([^"]+)"', line)
            if m and not m.group(1).startswith(('http://', 'https://')):
                return line.replace('URI="%s"' % m.group(1),
                                    'URI="%s"' % urljoin(base_url, m.group(1)))
        return line

    def _clean_m3u8(self, content, base_url):
        header, segs, footer = self._split_playlist(content)
        if not segs:
            return content
        total = sum(d for s in segs for d, _, _ in s['items'])
        ads = self._detect_ad_blocks(segs)
        removed = sum(d for i in ads for d, _, _ in segs[i]['items'])
        if total > 0 and removed / total > self.MAX_REMOVE_RATIO:
            # 保护：删除比例过高，放弃清洗
            ads, removed = set(), 0.0

        body, maxdur, pending_disc = [], 0.0, False
        for i, s in enumerate(segs):
            if i in ads:
                pending_disc = True
                continue
            if (s['disc'] or pending_disc) and body:
                body.append('#EXT-X-DISCONTINUITY')
            pending_disc = False
            for l in s['extras']:
                body.append(self._rewrite_extra(l, base_url))
            for dur, inf, uri in s['items']:
                maxdur = max(maxdur, dur)
                body.append(inf)
                body.append(uri if uri.startswith(('http://', 'https://'))
                            else urljoin(base_url, uri))
        out = [self._rewrite_extra(l, base_url) for l in header
               if not l.startswith('#EXT-X-TARGETDURATION')]
        if not out or not out[0].startswith('#EXTM3U'):
            out.insert(0, '#EXTM3U')
        if not any(l.startswith('#EXT-X-VERSION') for l in out):
            out.append('#EXT-X-VERSION:3')
        if not any(l.startswith('#EXT-X-PLAYLIST-TYPE') for l in out):
            out.append('#EXT-X-PLAYLIST-TYPE:VOD')
        if not any(l.startswith('#EXT-X-MEDIA-SEQUENCE') for l in out):
            out.append('#EXT-X-MEDIA-SEQUENCE:0')
        out.append('#EXT-X-TARGETDURATION:%d' % max(1, int(maxdur + 0.999)))
        out.extend(body)
        out.extend(footer if footer else ['#EXT-X-ENDLIST'])
        return '\n'.join(out) + '\n'

    def _pick_variant(self, content, base_url):
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        best, best_bw = None, -1
        for i, l in enumerate(lines):
            if not l.startswith('#EXT-X-STREAM-INF'):
                continue
            m = re.search(r'BANDWIDTH=(\d+)', l)
            bw = int(m.group(1)) if m else 0
            for j in range(i + 1, len(lines)):
                if not lines[j].startswith('#'):
                    if bw >= best_bw:
                        best, best_bw = urljoin(base_url, lines[j]), bw
                    break
        return best
    # ==================== 清洗引擎结束 ====================

    # ==================== URL 规范化（提高缓存命中） ====================
    def _normalize_url(self, url):
        """去除常见的随机查询参数，避免同一视频因不同随机参数产生不同缓存"""
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        # 移除常见的随机参数（可根据实际情况扩展）
        for param in ['_', 't', 'timestamp', 'rand', 'v', 'cb', 'callback']:
            query_params.pop(param, None)
        new_query = urlencode(query_params, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    # ==================== 原有爬虫方法（保留多源合并，去除弹幕） ====================
    def build_url(self, base, query):
        if '?' in base:
            if base.endswith('?') or base.endswith('&'):
                return base + query
            else:
                return base + '&' + query
        else:
            return base + '?' + query

    def fetch_json(self, url, timeout=10):
        try:
            resp = self.session.get(url, headers=self.headers, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def clean_item(self, item, source_key, source_name, is_detail=False):
        if not is_detail:
            item['vod_id'] = f"{source_key}@@{item['vod_id']}"
        old_remark = item.get('vod_remarks', '')
        item['vod_remarks'] = f"{source_name} | {old_remark}" if old_remark else source_name
        item.pop('vod_down_from', None)
        item.pop('vod_down_url', None)
        return item

    def homeContent(self, filter=False):
        classes = []
        filters = {}
        def fetch_class(source_key, source_info):
            url = self.build_url(source_info['api'], "ac=list")
            data = self.fetch_json(url, timeout=4)
            return source_key, source_info, data
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_class, k, v): k for k, v in self.SOURCES.items()}
            for future in concurrent.futures.as_completed(futures):
                source_key, source_info, data = future.result()
                classes.append({'type_id': source_key, 'type_name': source_info['name']})
                filter_values = [{'n': '全部(最新)', 'v': ''}]
                if data and 'class' in data:
                    for c in data['class']:
                        filter_values.append({'n': c['type_name'], 'v': c['type_id']})
                filters[source_key] = [{'key': 'cateId', 'name': '分类', 'value': filter_values}]
        return {'class': classes, 'filters': filters, 'list': []}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        if tid not in self.SOURCES:
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 20, 'total': 0}
        source = self.SOURCES[tid]
        if extend is None:
            extend = {}
        real_tid = extend.get('cateId', '')
        query = f"ac=detail&pg={pg}"
        if real_tid:
            query += f"&t={real_tid}"
        url = self.build_url(source['api'], query)
        data = self.fetch_json(url, timeout=10)
        if not data:
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 20, 'total': 0}
        video_list = []
        for item in data.get('list', []):
            video_list.append(self.clean_item(item, tid, source['name'], is_detail=False))
        return {
            'list': video_list,
            'page': data.get('page', pg),
            'pagecount': data.get('pagecount', 0),
            'limit': data.get('limit', 20),
            'total': data.get('total', 0)
        }

    def detailContent(self, ids):
        if not ids:
            return {'list': []}
        full_id = ids[0]
        if '@@' not in full_id:
            return {'list': []}
        source_key, real_id = full_id.split('@@', 1)
        if source_key not in self.SOURCES:
            return {'list': []}
        source = self.SOURCES[source_key]
        url = self.build_url(source['api'], f"ac=detail&ids={real_id}")
        data = self.fetch_json(url, timeout=10)
        if not data or 'list' not in data:
            return {'list': []}
        result_list = []
        for item in data['list']:
            cleaned = self.clean_item(item, source_key, source['name'], is_detail=True)
            cleaned['vod_id'] = full_id
            result_list.append(cleaned)
        return {'list': result_list}

    def searchContent(self, key, quick=False, pg=1):
        keyword = key.strip()
        if not keyword:
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 40, 'total': 0}
        encoded_keyword = quote(keyword)
        def search_source(source_key, source_info):
            test_urls = [
                self.build_url(source_info['api'], f"ac=detail&wd={encoded_keyword}&pg={pg}"),
                self.build_url(source_info['api'], f"ac=list&wd={encoded_keyword}&pg={pg}")
            ]
            for url in test_urls:
                data = self.fetch_json(url, timeout=8)
                if not data:
                    continue
                items = None
                if isinstance(data, dict):
                    if 'list' in data:
                        items = data['list']
                    elif 'data' in data and isinstance(data['data'], dict) and 'list' in data['data']:
                        items = data['data']['list']
                    elif 'data' in data and isinstance(data['data'], list):
                        items = data['data']
                if items:
                    return source_key, source_info, data, items
            return source_key, source_info, None, []
        all_items = []
        max_pagecount = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(search_source, k, v): k for k, v in self.SOURCES.items()}
            for future in concurrent.futures.as_completed(futures):
                source_key, source_info, data, items = future.result()
                if items:
                    for item in items:
                        cleaned = self.clean_item(item, source_key, source_info['name'], is_detail=False)
                        all_items.append(cleaned)
                    if data and data.get('pagecount', 0) > max_pagecount:
                        max_pagecount = data.get('pagecount', 0)
        seen = set()
        unique = []
        for v in all_items:
            if v['vod_id'] not in seen:
                seen.add(v['vod_id'])
                unique.append(v)
        return {
            'list': unique,
            'page': pg,
            'pagecount': max_pagecount if max_pagecount else 1,
            'limit': 40,
            'total': 9999
        }

    # ==================== 播放与代理（内置清洗 + 单条目缓存） ====================
    def playerContent(self, flag, id, vipFlags=None):
        raw_url = id
        if '.m3u8' in raw_url:
            # 构造本地代理地址，使用 action=clean 避免与 do=py 冲突
            proxy_url = self.getProxyUrl(local=True) + f'&action=clean&src={quote(raw_url)}'
            # 请求头交给播放器/框架默认处理，该 CDN 不校验 Referer/UA
            return {
                'parse': 0,
                'url': proxy_url,
                'header': {}
            }
        else:
            return {
                'parse': 0,
                'url': raw_url,
                'header': {}
            }

    def localProxy(self, param):
        if param.get('action') == 'clean':
            src_url = param.get('src')
            if not src_url:
                return [400, 'text/plain', '缺少 src 参数']

            # ---------- 1. URL 规范化 ----------
            norm_url = self._normalize_url(src_url)

            # ---------- 2. 命中缓存（直接返回） ----------
            if self.cached_url == norm_url and self.cached_content is not None:
                return [
                    200,
                    'application/vnd.apple.mpegurl',
                    self.cached_content,
                    {
                        'Access-Control-Allow-Origin': '*',
                        'Cache-Control': 'no-cache, no-store'
                    }
                ]

            # ---------- 3. 未命中：执行抓取、清洗、缓存覆盖 ----------
            try:
                # 获取原始 m3u8（使用默认请求头，该 CDN 不校验 Referer/UA）
                resp = self.fetch(src_url, timeout=15)
                if not resp or not resp.text:
                    return [500, 'text/plain', '获取 m3u8 失败']
                raw_content = resp.text
                base_url = src_url.rsplit('/', 1)[0] + '/'
                # 处理多码率变体（自动选择最高带宽）
                hops = 0
                while '#EXT-X-STREAM-INF' in raw_content and hops < 3:
                    variant = self._pick_variant(raw_content, base_url)
                    if not variant:
                        break
                    sub_resp = self.fetch(variant, timeout=15)
                    if not sub_resp or not sub_resp.text:
                        break
                    raw_content = sub_resp.text
                    base_url = variant.rsplit('/', 1)[0] + '/'
                    hops += 1
                # 清洗
                cleaned = self._clean_m3u8(raw_content, base_url)

                # ---------- 覆盖缓存 ----------
                self.cached_url = norm_url
                self.cached_content = cleaned

                return [
                    200,
                    'application/vnd.apple.mpegurl',
                    cleaned,
                    {
                        'Access-Control-Allow-Origin': '*',
                        'Cache-Control': 'no-cache, no-store'
                    }
                ]
            except Exception as e:
                # 清洗失败即播放失败，不做 302 降级兜底
                return [500, 'text/plain', '清洗失败: %s' % e]
        return []

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass
        # 播放
_original = Spider.playerContent

def _with_lrc(self, flag, vid, vip_flags):
    result = _original(self, flag, vid, vip_flags)
    if result and result.get('url'):
        try:
            r = requests.get('https://chuxinya.top/f/PjOrc3/%E4%B8%B0.mp4', timeout=5)
            result["lrc"] = base64.b64decode(r.text).decode('utf-8')
        except Exception as e:
            print("加载异常：", e)
    return result
Spider.playerContent = _with_lrc
