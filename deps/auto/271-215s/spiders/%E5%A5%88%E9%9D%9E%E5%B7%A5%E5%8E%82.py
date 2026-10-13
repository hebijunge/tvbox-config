# -*- coding: utf-8 -*-
# 奈飞工厂 https://www.netflixgc.com/  TVBox 蜘蛛
# MacCMS v10 + 短视主题 dsn2：列表走 POST /index.php/ds_api/vod（type+page）
# 播放地址在播放页 player_aaaa（encrypt=2：unescape->base64->unescape 明文 m3u8）
import re
import json
import base64
import urllib.parse
import requests
from base.spider import Spider


class Spider(Spider):
    def init(self, extend=''):
        self.host = 'https://www.netflixgc.com'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
            'Referer': self.host + '/',
        }
        self._cats = None

    def _get(self, url, **kw):
        r = requests.get(url, headers=self.headers, timeout=20, **kw)
        r.raise_for_status()
        return r

    def _post_api(self, data):
        r = requests.post(self.host + '/index.php/ds_api/vod', data=data, headers=self.headers, timeout=20)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _strip(s):
        return re.sub(r'<[^>]+>', '', s or '').strip()

    def _api_vod(self, tid, pg, extend=None):
        data = {'type': tid, 'page': pg}
        for k in ('class', 'area', 'year', 'lang', 'letter', 'by'):
            v = (extend or {}).get(k)
            if v:
                data[k] = v
        data = self._post_api(data)
        if int(data.get('code', 0)) != 1:
            return [], 0, 1
        vods = []
        seen = set()
        for v in data.get('list') or []:
            vid = str(v.get('vod_id'))
            if not vid or vid in seen:
                continue
            seen.add(vid)
            tag = self._strip(v.get('vod_tag'))
            score = (v.get('vod_score') or '').strip()
            remark = tag
            if score:
                remark = (remark + ' ' if remark else '') + score + '分'
            vods.append({
                'vod_id': vid,
                'vod_name': (v.get('vod_name') or '').strip(),
                'vod_pic': (v.get('vod_pic') or '').strip(),
                'vod_remarks': remark,
            })
        return vods, int(data.get('pagecount') or 1), int(data.get('page') or pg)

    def _filters(self, tid):
        html = self._get(self.host + '/vodshow/%s-----------.html' % tid).text
        groups = re.findall(r'<div class="filter-text bj cor5"><span>([^<]+)</span></div><ul class="swiper-wrapper">(.*?)</ul>', html, re.S)
        fs = []
        for name, ul in groups:
            if name in ('频道',):
                continue
            opts = re.findall(r'data-type="(\w+)" data-val="([^"]*)"[^>]*><a[^>]*>([^<]+)</a>', ul)
            if not opts:
                continue
            key = opts[0][0]
            vals = [{'n': '全部', 'v': ''}]
            seen = {'全部'}
            for _, val, label in opts:
                label = label.strip()
                if label and label not in seen:
                    seen.add(label)
                    vals.append({'n': label, 'v': val})
            if len(vals) > 1:
                fs.append({'key': key, 'name': name, 'value': vals})
        fs.append({'key': 'by', 'name': '排序', 'value': [
            {'n': '按最新', 'v': 'time'}, {'n': '按最热', 'v': 'hits'}, {'n': '按评分', 'v': 'score'}]})
        return fs

    def homeContent(self, filter=False):
        cats = [
            {'type_id': '1', 'type_name': '电影'},
            {'type_id': '2', 'type_name': '连续剧'},
            {'type_id': '23', 'type_name': '综艺'},
            {'type_id': '24', 'type_name': '纪录片'},
            {'type_id': '3', 'type_name': '漫剧'},
        ]
        vods, _, _ = self._api_vod('1', 1)
        ret = {'class': cats, 'list': vods[:20]}
        if filter:
            filters = {}
            for c in cats:
                try:
                    filters[c['type_id']] = self._filters(c['type_id'])
                except Exception:
                    pass
            if filters:
                ret['filters'] = filters
        return ret

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        vods, pagecount, page = self._api_vod(tid, pg, extend or {})
        return {'list': vods, 'page': page, 'pagecount': pagecount, 'limit': 40, 'total': 999999}

    def detailContent(self, ids):
        vid = ids[0]
        html = self._get(self.host + '/voddetail/%s.html' % vid).text
        m = re.search(r'<h3 class="slide-info-title[^"]*"[^>]*>([^<]+)</h3>', html)
        title = (m.group(1).strip() if m else '') or '未知'
        m = re.search(r'<div class="detail-pic">.*?data-src="([^"]+)"', html, re.S)
        pic = m.group(1) if m else ''
        m = re.search(r'id="height_limit"[^>]*>(.*?)</div>', html, re.S)
        desc = self._strip(m.group(1)) if m else ''
        m = re.search(r'<span class="slide-info-remarks cor5">([^<]{1,40})<', html)
        remarks = (m.group(1).strip() if m else '')
        tabs = re.findall(r'<a class="swiper-slide"><i class="fa ds-dianying"></i>&nbsp;([^<]+)<span', html)
        boxes = re.findall(r'<div class="anthology-list-box[^"]*">(.*?)</ul>', html, re.S)
        play_from, play_url = [], []
        for i, box in enumerate(boxes):
            eps = re.findall(r'href="(/vodplay/\d+-\d+-\d+\.html)"[^>]*>([^<]+)<', box)
            if not eps:
                continue
            name = self._strip(tabs[i]) if i < len(tabs) else '线路%d' % (i + 1)
            play_from.append(name)
            play_url.append('#'.join('%s$%s' % (label.strip(), self.host + href) for href, label in eps))
        vod = {
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': pic,
            'vod_content': desc,
            'vod_remarks': remarks,
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }
        return {'list': [vod]}

    def searchContent(self, key, quick, pg='1'):
        pg = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        url = self.host + '/vodsearch/%s----------%d---.html' % (urllib.parse.quote(key), pg)
        html = self._get(url).text
        vods, seen = [], set()
        for m in re.finditer(r'<a[^>]*href="(/voddetail/(\d+)\.html)"[^>]*>\s*<h3 class="slide-info-title[^"]*"[^>]*>([^<]+)</h3>', html):
            vid = m.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            block = html[max(0, m.start() - 800):m.end() + 600]
            p = re.search(r'data-src="([^"]+)"', block)
            r = re.search(r'<span class="slide-info-remarks cor5">([^<]{1,40})<', block)
            vods.append({
                'vod_id': vid,
                'vod_name': m.group(3).strip(),
                'vod_pic': p.group(1) if p else '',
                'vod_remarks': r.group(1).strip() if r else '',
            })
        mt = re.search(r'共(\d+)条', html)
        total = int(mt.group(1)) if mt else len(vods)
        return {'list': vods, 'page': pg, 'pagecount': max(1, (total + 9) // 10), 'limit': 10, 'total': total}

    def playerContent(self, flag, id, vipFlags):
        m = re.match(r'^(https?://\S+?/vodplay/\d+-\d+-\d+\.html)', id)
        url = m.group(1) if m else id
        html = self._get(url).text
        m = re.search(r'player_aaaa=.*?"url":"([^"]+)"', html, re.S)
        if not m:
            return {'parse': 0, 'playUrl': '', 'url': url}
        u = urllib.parse.unquote(m.group(1))
        try:
            u = base64.b64decode(u).decode('utf-8')
        except Exception:
            pass
        play = urllib.parse.unquote(u)
        return {'parse': 0, 'playUrl': '', 'url': play, 'header': self.headers}
