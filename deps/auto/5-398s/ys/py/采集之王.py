# -*- coding: utf-8 -*-
import json
import re
import time
import warnings
import threading

import requests
from urllib.parse import quote, unquote
try:
    warnings.filterwarnings('ignore')
    requests.packages.urllib3.disable_warnings()
except Exception:
    pass

from base.spider import Spider

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

SOURCES = [
    {'key': 'dyttzy', 'name': '电影天堂', 'api': 'https://caiji.dyttzyapi.com/api.php/provide/vod'},
    {'key': 'ruyi', 'name': '如意资源', 'api': 'https://cj.rycjapi.com/api.php/provide/vod'},
    {'key': 'bfzy', 'name': '暴风资源', 'api': 'https://bfzyapi.com/api.php/provide/vod'},
    {'key': 'ffzy', 'name': '非凡资源', 'api': 'https://ffzy5.tv/api.php/provide/vod'},
    {'key': 'zy360', 'name': '360资源',  'api': 'https://360zy.com/api.php/provide/vod'},
    {'key': 'jisu', 'name': '极速资源', 'api': 'https://jszyapi.com/api.php/provide/vod'},
    {'key': 'zuid', 'name': '最大资源', 'api': 'https://api.zuidapi.com/api.php/provide/vod'},
    {'key': 'lzi', 'name': '量子资源', 'api': 'https://cj.lziapi.com/api.php/provide/vod'},
    {'key': 'ty', 'name': '天涯资源', 'api': 'https://tyyszyapi.com/api.php/provide/vod'},
    {"key":"hhzy","name":"火狐资源","api":"https://hhzyapi.com/api.php/provide/vod"},
   {"key":"hwzy","name":"华为资源","api":"https://cjhwba.com/api.php/provide/vod"},
   {"key":"mtzy","name":"茅台资源","api":"https://caiji.maotaizy.cc/api.php/provide/vod"},
   {"key":"myzy","name":"猫眼资源","api":"https://api.maoyanapi.top/api.php/provide/vod"},
   {"key":"wsyzy","name":"无水印资源","api":"https://api.wsyzy.net/api.php/provide/vod"}
]

TIMEOUT = 8             
MAX_WORKERS = 16         
AUX_TIMEOUT = 3
CATEGORIES = [
    '短剧',
    'AI漫剧',
    '国产剧',
    '香港剧',
    '韩国剧',
    '欧美剧',
    '日本剧',
    '台湾剧',
    '泰国剧',
    '海外剧',
    '动作片',
    '喜剧片',
    '爱情片',
    '科幻片',
    '恐怖片',
    '剧情片',
    '战争片',
    '动画片',
    '纪录片',
    '电影解说',
    '大陆综艺',
    '港台综艺',
    '日韩综艺',
    '欧美综艺',
    '国产动漫',
    '日韩动漫',
    '欧美动漫',
    '伦理片',
]

_TAG = re.compile(r'<[^>]+>')
_LOCK = threading.Lock()


def _clean(text):
    if not text:
        return ''
    text = _TAG.sub('', str(text))
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', text).strip()

def _is_direct(url):
    """只检测 m3u8 和 mp4 格式"""
    if not url:
        return False
    u = str(url).split('?')[0].lower()
    return u.endswith('.m3u8') or u.endswith('.mp4')

def _same_name(a, b):
    def norm(s):
        s = re.sub(r'[\s·•：:，,。！？!?（）()【】\[\]]', '', _clean(s)).lower()
        return re.sub(r'(国语版|高清版|完整版|全集|正片)$', '', s)
    x, y = norm(a), norm(b)
    return bool(x and y and (x == y or x in y or y in x))
def _category_same(a, b):
    aliases = {'纪录片': '记录片', '记录片': '纪录片', '动漫': '动漫片', '动漫片': '动漫'}
    x = _clean(a)
    y = _clean(b)
    return x == y or aliases.get(x) == y


class Spider(Spider):

    def getName(self):
        return '采集之王'

    def init(self, extend=''):
        self.header = {'User-Agent': UA}
        self.timeout = TIMEOUT
        self.session = requests.Session()
        self.session.headers.update(self.header)
        self.sources = SOURCES
        try:
            if extend:
                cfg = json.loads(extend) if isinstance(extend, str) else extend
                enabled = cfg.get('enabled')
                if isinstance(enabled, list) and enabled:
                    keep = [s for s in SOURCES if s['key'] in enabled]
                    if keep:
                        self.sources = keep
        except Exception:
            pass
        self.by_key = {s['key']: s for s in self.sources}

    def _fetch(self, source, retry=True, timeout=None, **params):
        attempts = 2 if retry else 1
        for attempt in range(attempts):
            try:
                api = source['api'].split('?', 1)[0]
                r = self.session.get(api, params=params,
                                     timeout=timeout or self.timeout, verify=False)
                j = r.json()
                if isinstance(j, dict):
                    return j
            except Exception:
                if attempt == 0 and attempts > 1:
                    time.sleep(0.15)
        return None

    def _fetch_by_key(self, key, **params):
        src = self.by_key.get(key)
        if not src:
            return None
        return self._fetch(src, **params)

    def _fetch_matches(self, source, name):
        if source.get('key') == 'ty':
            try:
                search_url = 'https://tyyszy.com/index.php/vod/search.html?wd=' + quote(name)
                r = self.session.get(search_url, timeout=AUX_TIMEOUT, verify=False)
                ids = re.findall(r'/index\.php/vod/detail/id/(\d+)\.html[^>]*data-name=["\']([^"\']+)', r.text, re.I)
                for real_id, found_name in ids:
                    if not _same_name(found_name, name):
                        continue
                    result = self._fetch(source, ac='detail', ids=real_id)
                    if result and result.get('list'):
                        return result
            except Exception:
                pass
            return None
        result = self._fetch(source, retry=False, timeout=AUX_TIMEOUT, ac='detail', wd=name)
        if result and result.get('list'):
            return result
        if source.get('key') not in ('mtzy', 'wsyzy'):
            return None
        pages = min(5, int(result.get('pagecount', 5) or 5)) if result else 5
        jobs = [(page, lambda page=page: self._fetch(
            source, retry=False, timeout=AUX_TIMEOUT, ac='list', pg=page))
                for page in range(1, pages + 1)]
        data = self._parallel(jobs)
        for page in range(1, pages + 1):
            page_data = data.get(page)
            if not page_data or not page_data.get('list'):
                continue
            for vod in page_data['list']:
                if _same_name(vod.get('vod_name', ''), name):
                    detail = self._fetch(source, retry=False, timeout=AUX_TIMEOUT,
                                         ac='detail', ids=vod.get('vod_id', ''))
                    if detail and detail.get('list'):
                        return detail
        return None

    def _parallel(self, jobs):
        out = {}
        if not jobs:
            return out
        threads = []

        def run(k, fn):
            try:
                res = fn()
            except Exception:
                res = None
            with _LOCK:
                out[k] = res

        for k, fn in jobs:
            t = threading.Thread(target=run, args=(k, fn))
            t.daemon = True
            threads.append(t)
            if len(threads) >= MAX_WORKERS:
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                threads = []
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return out

    def _item(self, vod, src_key):
        return {
            'vod_id': '%s:%s' % (src_key, vod.get('vod_id', '')),
            'vod_name': _clean(vod.get('vod_name', '')) or '未知影片',
            'vod_pic': vod.get('vod_pic', '') or '',
            'vod_remarks': _clean(vod.get('vod_remarks', '')) or '',
        }

    def homeContent(self, filter):
        result = {'class': [{'type_id': name, 'type_name': name}
                            for name in CATEGORIES],
                  'list': []}
        try:
            result['list'] = self._home_list()
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        try:
            return {'list': self._home_list()}
        except Exception:
            return {}

    def _home_list(self):
        jobs = [(s['key'], lambda s=s: self._fetch(
            s, ac='detail', pg=1)) for s in self.sources]
        data = self._parallel(jobs)
        pools = []
        for key in [s['key'] for s in self.sources]:
            j = data.get(key)
            if j and j.get('list'):
                pools.append([(v, key) for v in j['list']])
        mixed = []
        if pools:
            for i in range(20):
                for pool in pools:
                    if i < len(pool):
                        mixed.append(pool[i])
        return [self._item(v, k) for v, k in mixed[:30]]

    def _category_fetch(self, source, name, page):
        try:
            meta = self._fetch(source, retry=False, timeout=AUX_TIMEOUT, ac='list', pg=1)
            source_tid = ''
            for item in (meta or {}).get('class', []):
                if _category_same(item.get('type_name', ''), name):
                    source_tid = str(item.get('type_id', '')).strip()
                    break
            if not source_tid:
                return None
            return self._fetch(source, ac='detail', t=source_tid, pg=page)
        except Exception:
            return None

    def categoryContent(self, tid, pg, filter, extend):
        try:
            category_name = unquote(str(tid or '')).strip()
            if not category_name or ':' in category_name:
                return {'list': [], 'page': 1, 'pagecount': 0,
                        'limit': 20, 'total': 0}
            known_names = CATEGORIES
            if category_name not in known_names:
                return {'list': [], 'page': 1, 'pagecount': 0,
                        'limit': 20, 'total': 0}
            page = int(pg) if str(pg).isdigit() else 1
            jobs = [(s['key'], lambda s=s: self._category_fetch(
                s, category_name, page)) for s in self.sources]
            data = self._parallel(jobs)
            items = []
            seen = set()
            pagecount = 0
            total = 0
            for s in self.sources:
                j = data.get(s['key'])
                if not j or not j.get('list'):
                    continue
                try:
                    pagecount = max(pagecount, int(j.get('pagecount', 0) or 0))
                    total += int(j.get('total', 0) or 0)
                except Exception:
                    pass
                for vod in j['list']:
                    try:
                        item = self._item(vod, s['key'])
                        mark = item['vod_id']
                        if mark in seen:
                            continue
                        seen.add(mark)
                        items.append(item)
                    except Exception:
                        continue
            return {
                'list': items,
                'page': page,
                'pagecount': pagecount,
                'limit': max(20, sum(1 for s in self.sources if (data.get(s['key']) or {}).get('list')) * 20),
                'total': total,
            }
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 0,
                    'limit': 20, 'total': 0}

    def searchContent(self, key, quick, pg='1'):
        try:
            page = int(pg) if str(pg).isdigit() else 1
            if page > 1:
                return {'list': [], 'page': page}
            jobs = [(s['key'], lambda s=s: self._fetch(
                s, ac='detail', wd=key)) for s in self.sources]
            data = self._parallel(jobs)

            groups = {}
            order = []
            for s in self.sources:
                j = data.get(s['key'])
                if not j or not j.get('list'):
                    continue
                for v in j['list']:
                    name = _clean(v.get('vod_name', ''))
                    if not name:
                        continue
                    year = str(v.get('vod_year', '') or '')
                    gk = (name, year)
                    if gk not in groups:
                        groups[gk] = []
                        order.append(gk)
                    groups[gk].append((s['key'], v))

            def rank(entry):
                src_key, v = entry
                try:
                    score = float(v.get('vod_score', 0) or 0)
                except Exception:
                    score = 0.0
                remarks = _clean(v.get('vod_remarks', ''))
                bonus = 1 if any(w in remarks for w in ('完结', 'HD', '正片')) else 0
                return (bonus, score)

            result_list = []
            for gk in order:
                entries = groups[gk]
                entries.sort(key=rank, reverse=True)
                src_key, v = entries[0]
                item = self._item(v, src_key)
                if len(entries) > 1:
                    note = '·%d源' % len(entries)
                    item['vod_remarks'] = (item['vod_remarks'] + ' ' + note).strip()
                result_list.append(item)

            result_list.sort(key=lambda x: int(re.search(r'(\d+)源', x['vod_remarks']).group(1))
                             if re.search(r'(\d+)源', x['vod_remarks']) else 0,
                             reverse=True)
            return {'list': result_list, 'page': page}
        except Exception:
            return {'list': [], 'page': 1}

    def detailContent(self, ids):
        try:
            if isinstance(ids, str):
                vid = ids
            else:
                vid = str(ids[0]) if ids else ''
            key, sep, real_id = vid.partition(':')
            source_map = {s['key']: s for s in self.sources}
            if not sep or not real_id or key not in source_map:
                return {'list': []}
            main_src = source_map[key]

            j = self._fetch(main_src, ac='detail', ids=real_id)
            if not j or not j.get('list'):
                return {'list': []}
            vod = j['list'][0]
            name = _clean(vod.get('vod_name', ''))
            year = str(vod.get('vod_year', '') or '')

            play_froms = []
            play_urls = []
            self._collect_lines(key, vod, play_froms, play_urls)
            others = [s for s in SOURCES if s['key'] != key]
            jobs = [(s['key'], lambda s=s: self._fetch_matches(s, name)) for s in others]
            data = self._parallel(jobs)

            for s in others:
                j2 = data.get(s['key'])
                if not j2 or not j2.get('list'):
                    continue
                for v2 in j2['list']:
                    n2 = _clean(v2.get('vod_name', ''))
                    if not _same_name(n2, name):
                        continue
                    f2, u2 = [], []
                    self._collect_lines(s['key'], v2, f2, u2)
                    if u2:
                        play_froms.extend(f2)
                        play_urls.extend(u2)
                        break

            unique_froms = []
            unique_urls = []
            seen_names = set()
            seen_groups = set()
            for pf, pu in zip(play_froms, play_urls):
                name_mark = _clean(pf).lower()
                url_mark = _clean(pu).lower()
                if not name_mark or not url_mark or name_mark in seen_names or url_mark in seen_groups:
                    continue
                seen_names.add(name_mark)
                seen_groups.add(url_mark)
                unique_froms.append(_clean(pf))
                unique_urls.append(pu)
            play_froms, play_urls = unique_froms, unique_urls
            pic = vod.get('vod_pic', '') or ''
            try:
                score = str(float(vod.get('vod_score', 0) or 0))
                if score.endswith('.0'):
                    score = score[:-2]
            except Exception:
                score = ''
            d = {
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'type_name': _clean(vod.get('type_name', '')),
                'vod_year': year,
                'vod_area': _clean(vod.get('vod_area', '')),
                'vod_actor': _clean(vod.get('vod_actor', '')),
                'vod_director': _clean(vod.get('vod_director', '')),
                'vod_content': _clean(vod.get('vod_content', '')),
                'vod_remarks': _clean(vod.get('vod_remarks', '')),
                'vod_play_from': '$$$'.join(play_froms),
                'vod_play_url': '$$$'.join(play_urls),
            }
            if score and score != '0':
                d['vod_score'] = score
            return {'list': [d]}
        except Exception:
            return {'list': []}

    def _collect_lines(self, src_key, vod, play_froms, play_urls):
        src = self.by_key.get(src_key) or next((s for s in SOURCES if s.get('key') == src_key), {})
        src_name = _clean(src.get('name', src_key)) or src_key
        if src_name in play_froms:
            return
        from_raw = str(vod.get('vod_play_from', '') or '')
        from_raw = from_raw.replace('$$$', ',').replace('，', ',')
        froms = [x.strip() for x in from_raw.split(',') if x.strip()]
        urls = [x.strip() for x in str(vod.get('vod_play_url', '') or '').split('$$$') if x.strip()]
        episodes = []
        seen_episodes = set()
        for i, url_group in enumerate(urls):
            if not url_group:
                continue
            for episode in url_group.split('#'):
                parts = episode.split('$')
                if len(parts) < 2:
                    continue
                episode_name = _clean(parts[0]) or '第%d集' % (len(episodes) + 1)
                episode_url = parts[-1].strip()
                if not _is_direct(episode_url):
                    continue
                mark = episode_name.lower()
                if mark in seen_episodes:
                    continue
                seen_episodes.add(mark)
                episodes.append('%s$%s' % (episode_name, episode_url))
        if not episodes:
            return
        play_froms.append(src_name)
        play_urls.append('#'.join(episodes))

    def playerContent(self, flag, id, vipFlags):
        try:
            url = str(id or '').strip()
            if url.startswith('//'):
                url = 'https:' + url
            header = {'User-Agent': UA}
            # 检测是否为有效的 m3u8 或 mp4 格式
            if _is_direct(url):
                return {'parse': 0, 'playUrl': '', 'url': url, 'header': header}
            # 非直接播放格式，尝试解析
            return {'parse': 1, 'playUrl': '', 'url': url, 'header': header}
        except Exception:
            return {'parse': 0, 'playUrl': '', 'url': id, 'header': {'User-Agent': UA}}

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return None