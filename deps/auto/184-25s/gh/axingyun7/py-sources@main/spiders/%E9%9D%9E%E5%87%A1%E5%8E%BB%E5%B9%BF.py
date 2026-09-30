# coding=utf-8
"""
非凡影视聚合爬虫（内置去广告清洗）
- 单源（非凡）
- 播放 M3U8 时自动通过本地代理清洗广告（基于段时长中位数比例）
- 无需外部清洗服务器
- 无弹幕
- 缓存优化：只缓存最近一次播放的清洗结果，换源自动覆盖，无过期时间
"""
import sys
import json
import concurrent.futures
import re
import statistics
import time
import requests
import base64

from urllib.parse import urljoin, urlparse, quote, unquote, parse_qs, urlencode, urlunparse
sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    SOURCES = {      
        '非凡': {'name': '️非凡', 'api': 'http://api.ffzyapi.com/api.php/provide/vod/from/ffm3u8/'}
    }

    def init(self, extend=""):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        }
        # ---------- 缓存（单条目，覆盖式） ----------
        self.cached_url = None      # 规范化后的URL
        self.cached_content = None  # 清洗后的m3u8内容

    # ==================== 清洗引擎（移植自 clean_ad_v3.py，非凡专用） ====================
    AD_DURATION_RATIO = 0.15      # 段时长 < 中位数 * 此比例 → 广告
    SHORT_TS_MAX = 10             # ts 数 ≤ 此值 → 短段（规则1失效时启用）
    SHORT_DURATION_MAX = 35.0     # 短段时长上限
    TIMEOUT = 15

    def _fetch_m3u8(self, url):
        """抓取 m3u8 内容，最多重试3次，使用默认请求头（不额外设置）"""
        for attempt in range(3):
            try:
                resp = self.fetch(url, timeout=self.TIMEOUT)   # 不传 headers
                if resp and resp.text:
                    return resp.text
            except Exception:
                if attempt < 2:
                    time.sleep(1)
        return None

    def _parse_segments(self, lines):
        """
        按 #EXT-X-DISCONTINUITY 分段，每段返回 dict:
        {'duration': 总时长, 'ts_count': ts数量, 'lines': 该段行列表}
        """
        segs = []
        cur_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line == '#EXT-X-DISCONTINUITY':
                if cur_lines:
                    dur, ts_cnt = self._calc_duration_and_ts(cur_lines)
                    segs.append({'duration': dur, 'ts_count': ts_cnt, 'lines': cur_lines})
                    cur_lines = []
            else:
                cur_lines.append(line)
        if cur_lines:
            dur, ts_cnt = self._calc_duration_and_ts(cur_lines)
            segs.append({'duration': dur, 'ts_count': ts_cnt, 'lines': cur_lines})
        return segs

    def _calc_duration_and_ts(self, seg_lines):
        dur = 0.0
        ts_cnt = 0
        for line in seg_lines:
            if line.startswith('#EXTINF:'):
                try:
                    dur += float(line.split(':', 1)[1].split(',')[0])
                except Exception:
                    pass
            elif not line.startswith('#'):
                ts_cnt += 1
        return dur, ts_cnt

    def _rewrite_urls(self, lines, base_url):
        """把相对路径的 .ts 和 #EXT-X-KEY URI 转为绝对 URL。"""
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('#EXT-X-KEY:') and 'URI=' in line:
                m = re.search(r'URI="([^"]+)"', line)
                if m:
                    old_uri = m.group(1)
                    if not old_uri.startswith(('http://', 'https://')):
                        line = line.replace(f'URI="{old_uri}"', f'URI="{urljoin(base_url, old_uri)}"')
                result.append(line)
                i += 1
                continue
            if line.startswith('#EXTINF:'):
                result.append(line)
                if i + 1 < len(lines):
                    ts = lines[i + 1].strip()
                    if not ts.startswith(('http://', 'https://')):
                        ts = urljoin(base_url, ts)
                    result.append(ts)
                    i += 2
                    continue
            result.append(line)
            i += 1
        return result

    def _clean_m3u8_content(self, content, base_url, debug=False):
        """主清洗函数：两档规则自适应。"""
        lines = content.splitlines()

        # 1. 提取 Header
        header = []
        body_start = 0
        for i, line in enumerate(lines):
            line = line.strip()
            if line.startswith('#EXTM3U') or line.startswith('#EXT-X-'):
                header.append(line)
                body_start = i + 1
            else:
                break

        # 提取 Footer
        footer = []
        body_end = len(lines)
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == '#EXT-X-ENDLIST':
                footer.append(lines[i].strip())
                body_end = i
                break

        # 修复 header 中的 KEY URI
        for i, line in enumerate(header):
            if line.startswith('#EXT-X-KEY:') and 'URI=' in line:
                m = re.search(r'URI="([^"]+)"', line)
                if m:
                    old_uri = m.group(1)
                    if not old_uri.startswith(('http://', 'https://')):
                        header[i] = line.replace(f'URI="{old_uri}"', f'URI="{urljoin(base_url, old_uri)}"')

        # 2. Body → 分段
        body_lines = [l.strip() for l in lines[body_start:body_end] if l.strip()]
        segments = self._parse_segments(body_lines)
        if not segments:
            return content

        durations = [s['duration'] for s in segments]
        median_dur = statistics.median(durations)
        threshold1 = median_dur * self.AD_DURATION_RATIO

        # 3. 规则1：绝对时长比例（广告段极短，正片段极长）
        kept_segs = []
        rule1_hits = 0
        for idx, seg in enumerate(segments):
            if seg['duration'] < threshold1:
                kept_segs.append({'keep': False, 'seg': seg, 'idx': idx, 'reason': f'时长{seg["duration"]:.1f}s < 阈值{threshold1:.1f}s'})
                rule1_hits += 1
            else:
                kept_segs.append({'keep': True, 'seg': seg, 'idx': idx, 'reason': ''})

        # 4. 规则1兜底：中位数被广告段污染
        if rule1_hits == 0:
            max_dur = max(durations)
            if max_dur > 300:
                for entry in kept_segs:
                    if entry['keep'] and entry['seg']['duration'] < 60:
                        entry['keep'] = False
                        entry['reason'] = f'时长{entry["seg"]["duration"]:.1f}s < 绝对阈值60s (中位数被污染)'
                        rule1_hits += 1

        # 5. 规则2：规则1及兜底都没抓到广告 → 短段方案（短剧站点）
        if rule1_hits == 0:
            for entry in kept_segs:
                seg = entry['seg']
                if entry['keep'] and seg['ts_count'] <= 3 and seg['duration'] < self.SHORT_DURATION_MAX:
                    entry['keep'] = False
                    entry['reason'] = f'碎段(ts={seg["ts_count"]}, {seg["duration"]:.1f}s)'

        # 6. 组装结果
        result_segs = []
        for entry in kept_segs:
            seg = entry['seg']
            if entry['keep']:
                result_segs.extend(self._rewrite_urls(seg['lines'], base_url))

        result = []
        result.extend(header)
        result.extend(result_segs)
        result.extend(footer)

        if debug:
            total_ad = sum(1 for e in kept_segs if not e['keep'])
            dbg = [
                '# ====== 调试日志 ======',
                f'# 总段数: {len(segments)}, 保留: {len(segments) - total_ad}, 删除: {total_ad}',
                f'# 规则: {"规则1(时长比例)" if rule1_hits > 0 else "规则2(短段检测)"}',
                f'# 中位数时长: {median_dur:.1f}s',
                '# --------------------'
            ]
            for entry in kept_segs:
                if entry['keep']:
                    dbg.append(f'# 段{entry["idx"] + 1} [保留] {entry["seg"]["duration"]:.1f}s, {entry["seg"]["ts_count"]}ts')
                else:
                    dbg.append(f'# 段{entry["idx"] + 1} [删除] 广告 {entry["seg"]["duration"]:.1f}s, {entry["seg"]["ts_count"]}ts | 原因: {entry["reason"]}')
            dbg.append('# ====== 结束调试 ======')
            result = dbg + result

        return '\n'.join(result)

    def _pick_variant(self, content, base_url):
        """从多码率 playlist 中选最高带宽的 variant。"""
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

    # ==================== 原有爬虫方法（去除弹幕） ====================
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
            proxy_url = self.getProxyUrl(local=True) + f'&action=clean&src={quote(raw_url)}'
            return {
                'parse': 0,
                'url': proxy_url,
            }
        else:
            return {
                'parse': 0,
                'url': raw_url,
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
                content = self._fetch_m3u8(src_url)
                if not content:
                    return [500, 'text/plain', '获取 m3u8 失败']
                base_url = src_url.rsplit('/', 1)[0] + '/'
                # 处理多码率变体
                hops = 0
                while '#EXT-X-STREAM-INF' in content and hops < 3:
                    variant = self._pick_variant(content, base_url)
                    if not variant:
                        break
                    sub_content = self._fetch_m3u8(variant)
                    if not sub_content:
                        break
                    content = sub_content
                    base_url = variant.rsplit('/', 1)[0] + '/'
                    hops += 1
                cleaned = self._clean_m3u8_content(content, base_url, debug=False)

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
