# coding=utf-8
import json
import re
import sys
from html import unescape
from urllib.parse import quote, urlencode

sys.path.append('..')
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    def getName(self):
        return '爱看机器人'

    def init(self, extend=''):
        self.host = 'https://www.aikanbot.vip'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
            'Referer': self.host + '/',
        }
        self.classes = [
    {
        "type_id": "1",
        "type_name": "电影"
    },
    {
        "type_id": "2",
        "type_name": "剧集"
    },
    {
        "type_id": "18",
        "type_name": "动漫"
    },
    {
        "type_id": "19",
        "type_name": "综艺"
    },
    {
        "type_id": "20",
        "type_name": "纪录片"
    }
]

    def _fetch(self, url):
        try:
            r = self.fetch(url, headers=self.headers)
            return r.text or ''
        except Exception:
            return ''

    def _cards(self, html):
        out = []
        seen = set()
        for m in re.finditer(r'<a[^>]+href="/play/(\d+)"[^>]*>(.*?)</a>', html, re.S):
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            seg = m.group(2)
            pic = ''
            img = re.search(r'<img[^>]+(?:data-src|src)="([^"]+)"', seg)
            if img and 'data:image' not in img.group(1) and 'logo' not in img.group(1):
                pic = img.group(1)
            name = ''
            p = re.search(r'<p[^>]*>(.*?)</p>', seg, re.S)
            if p:
                name = unescape(re.sub(r'<[^>]+>', '', p.group(1))).strip()
            if not name and img:
                alt = re.search(r'alt="([^"]*)"', seg)
                if alt:
                    name = unescape(alt.group(1)).strip()
            if not name:
                name = unescape(re.sub(r'<[^>]+>', ' ', seg))
                name = re.sub(r'\s+', ' ', name).strip()
            out.append({'vod_id': vid, 'vod_name': name, 'vod_pic': pic, 'vod_remarks': ''})
        return out

    def homeContent(self, filter=False):
        return {'class': self.classes, 'filters': {}}

    def homeVideoContent(self):
        return {'list': self._cards(self._fetch(self.host + '/category/'))}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg)
        url = self.host + '/category/%s?p=%d' % (tid, pg)
        return {'list': self._cards(self._fetch(url)), 'page': pg, 'pagecount': 9999, 'limit': 60, 'total': 999999}

    def _token(self, html, cid):
        e = re.search(r'id="e_token"[^>]*value="([^"]*)"', html)
        c = re.search(r'id="current_id"[^>]*value="([^"]*)"', html)
        if not e or not c:
            return ''
        cur = c.group(1) or cid
        s = e.group(1)
        parts = []
        for ch in cur[-4:]:
            try:
                off = int(ch) % 3 + 1
            except Exception:
                off = 1
            parts.append(s[off:off + 8])
            s = s[off + 8:]
        return ''.join(parts)

    def detailContent(self, ids):
        vid = str(ids[0])
        html = self._fetch(self.host + '/play/%s' % vid)
        t = re.search(r'<title>([^<]*)</title>', html, re.S)
        name = ''
        if t:
            name = t.group(1).split('-免费在线观看')[0].strip()
        pic = ''
        og = re.search(r'property="og:image" content="([^"]+)"', html)
        if og:
            pic = og.group(1)
        mt = re.search(r'id="mtype"[^>]*value="([^"]*)"', html)
        mtype = mt.group(1) if mt else '1'
        actor = ''
        am = re.search(r'<h3 class="meta">(.*?)</h3>', html, re.S)
        if am:
            actor = unescape(re.sub(r'<[^>]+>', '', am.group(1))).strip()
        year = ''
        ym = re.search(r'\b(19|20)\d{2}\b', html)
        if ym:
            year = ym.group(0)
        token = self._token(html, vid)
        sources = []
        urls = []
        try:
            params = urlencode({'videoId': vid, 'mtype': mtype, 'token': token})
            txt = self._fetch(self.host + '/api/getResN?' + params)
            obj = json.loads(txt) if txt else {}
            lines = ((obj.get('data') or {}).get('list')) or []
            for line in lines:
                try:
                    res = json.loads(line.get('resData') or '[]')
                except Exception:
                    res = []
                for item in res:
                    flag = item.get('flag') or ('线路%s' % line.get('siteId'))
                    raw_url = item.get('url') or ''
                    eps = []
                    for part in raw_url.split('#'):
                        part = part.strip()
                        if not part:
                            continue
                        if '$' in part:
                            nm, u = part.split('$', 1)
                            nm = nm.strip() or '正片'
                        else:
                            nm, u = '正片', part
                        if u.strip():
                            eps.append('%s$%s' % (nm, u.strip()))
                    good = [e for e in eps if '.m3u8' in e.split('$', 1)[1]]
                    use = good if good else eps
                    if use:
                        sources.append(flag)
                        urls.append('#'.join(use))
        except Exception:
            pass
        vod = {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': pic,
            'vod_year': year,
            'vod_area': '',
            'vod_actor': actor,
            'vod_director': '',
            'type_name': '',
            'vod_content': name,
            'vod_play_from': '$$$'.join(sources),
            'vod_play_url': '$$$'.join(urls),
        }
        return {'list': [vod]}

    def playerContent(self, flag, id, vipFlags):
        return {'parse': 0, 'playUrl': '', 'url': id, 'header': self.headers}

    def searchContent(self, key, quick, pg='1'):
        pg = int(pg)
        url = self.host + '/search?q=' + quote(key)
        if pg > 1:
            url += '&p=%d' % pg
        return {'list': self._cards(self._fetch(url)), 'page': pg}
