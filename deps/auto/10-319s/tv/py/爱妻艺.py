# -*- coding: utf-8 -*-
#发布页https://093934.com/
#iqy99.ai
#iqyi03.cc
#iqyi02.cc
import sys, re, json, base64, socket, threading, time
import requests, urllib3
from urllib.parse import quote, unquote, urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from Crypto.Cipher import AES

urllib3.disable_warnings()
sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            import requests as rq
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r

HOST = 'https://525071.com'
UA = 'Mozilla/5.0 (Linux; Android 13) Chrome/120 Mobile'
K2 = 'zH3JDuCRXVGa3na7xbOqpx1bw6DAkbTP'
JSON_API = 'https://jsonbfq1.cszmys.com'
SEARCH_API = 'https://search5.fvnmowb.com'
PIC_API = 'https://mstatic1.cszmys.com'
VIDEO_DOMAINS = ['https://videos.yngte.com:65443', 'https://videos1.cszmys.com', 'https://vdfm.cszmys.com', 'https://jsonxz.cszmys.com']
# type_id = {site}:{cid}   w=water加密 p=water明文 t=topic
CATEGORIES = [
    {'type_id': 'w5:1867171983000444929', 'type_name': '妻友·推荐'},
    {'type_id': 'w5:1834141353648275458', 'type_name': '妻友·娇妻爱偷腥'},
    {'type_id': 'w5:2039683109807267841', 'type_name': '妻友·花式排精'},
    {'type_id': 'w5:1834158557194186754', 'type_name': '妻友·AV百科'},
    {'type_id': 'w5:1834141030896582658', 'type_name': '妻友·国产传媒'},
    {'type_id': 'w5:1856634604183420930', 'type_name': '妻友·网黄精选'},
    {'type_id': 'w5:1887472109954633730', 'type_name': '妻友·欧美'},
    {'type_id': 'w5:1910618543176429569', 'type_name': '妻友·动漫'},
    {'type_id': 'w5:1834142784048427010', 'type_name': '妻友·小众'},
    {'type_id': 't2:1813444410127257601', 'type_name': '香蕉·精选'},
    {'type_id': 'p3:1829527205563883521', 'type_name': '狼友·高分色情'},
    {'type_id': 'p3:1824076234591326210', 'type_name': '狼友·onlyfans'},
    {'type_id': 'p3:1824076346354933761', 'type_name': '狼友·户外'},
    {'type_id': 'p3:1824076421923708930', 'type_name': '狼友·直播'},
    {'type_id': 'p3:1824076506350854145', 'type_name': '狼友·偷窥'},
    {'type_id': 'p3:1824076678222860289', 'type_name': '狼友·爆菊'},
    {'type_id': 'p3:1824076984402857985', 'type_name': '狼友·少女'},
    {'type_id': 'p3:1824077031131598850', 'type_name': '狼友·孕妇'},
    {'type_id': 'p3:1824077121667833858', 'type_name': '狼友·Cosplay'},
    {'type_id': 'p3:1824077191104536577', 'type_name': '狼友·P站'},
    {'type_id': 'p3:1824077250283982849', 'type_name': '狼友·按摩'},
    {'type_id': 'p3:1824077361661714434', 'type_name': '狼友·创意'},
    {'type_id': 'p3:1824077586056978434', 'type_name': '狼友·媚黑'},
    {'type_id': 'p3:1824077663032856577', 'type_name': '狼友·反差'},
    {'type_id': 'p3:1824077712827633665', 'type_name': '狼友·调教'},
    {'type_id': 'p3:1824077895789551618', 'type_name': '狼友·探花'},
    {'type_id': 'p3:1824078772774391809', 'type_name': '狼友·扩张'},
    {'type_id': 'p3:1824079067176783874', 'type_name': '狼友·男娘'},
    {'type_id': 'p3:1824079225094512642', 'type_name': '狼友·三级'},
    {'type_id': 'w4:1823238080397332482', 'type_name': '乱伦·精选'},
    {'type_id': 'w4:1823631587949780994', 'type_name': '乱伦·日本'},
    {'type_id': 'w4:1823637473814401026', 'type_name': '乱伦·欧美'},
    {'type_id': 'w4:1823635358526230529', 'type_name': '乱伦·国产'},
    {'type_id': 'w4:1823637514520121346', 'type_name': '乱伦·动漫'},
    {'type_id': 'w4:1834212602109968385', 'type_name': '乱伦·网黄'},
    {'type_id': 'w6:1834846559507648514', 'type_name': '综合·推荐'},
    {'type_id': 'w6:1834552860668280834', 'type_name': '综合·热门专题'},
    {'type_id': 'w6:1834845947722416129', 'type_name': '综合·精选热播'},
    {'type_id': 'w6:1834849346278866945', 'type_name': '综合·百家传媒'},
    {'type_id': 'w6:1872148173865959425', 'type_name': '综合·外网社媒'},
    {'type_id': 'w6:1834849501149229057', 'type_name': '综合·环球影城'},
    {'type_id': 'w6:1834858289440821249', 'type_name': '综合·探花大全'},
    {'type_id': 'w6:1834852095376703490', 'type_name': '综合·二次元'},
    {'type_id': 'w7:1866844611617230850', 'type_name': '绿帽·推荐'},
    {'type_id': 'w7:1836276933903372289', 'type_name': '绿帽·精选AV'},
    {'type_id': 'w7:1910636159886495746', 'type_name': '绿帽·欧美'},
    {'type_id': 'w7:1840567488183386114', 'type_name': '绿帽·网黄'},
    {'type_id': 'w7:1836330192353472513', 'type_name': '绿帽·二次元'},
    {'type_id': 'w8:1836636258456862722', 'type_name': '黑料·头条爆料'},
    {'type_id': 'w8:1836637230514163713', 'type_name': '黑料·热门专题'},
    {'type_id': 'w8:1836637472047345665', 'type_name': '黑料·特殊癖好'},
    {'type_id': 'w8:1836638166510841858', 'type_name': '黑料·花式排精'},
    {'type_id': 'w8:2033439346590068737', 'type_name': '黑料·AI视频'},
    {'type_id': 'w8:1836638321423286274', 'type_name': '黑料·日本AV'},
    {'type_id': 'w8:1838844944606740482', 'type_name': '黑料·国产传媒'},
    {'type_id': 'w8:1949124017779376130', 'type_name': '黑料·欧美大片'},
    {'type_id': 'w8:1836637986105458690', 'type_name': '黑料·网黄博主'},
    {'type_id': 'w8:1836638857375633410', 'type_name': '黑料·里番肉漫'},
    {'type_id': 'w8:1838847758462455810', 'type_name': '黑料·猎奇小众'},
    {'type_id': 'w8:1838837573832511489', 'type_name': '黑料·探花视频'},
    {'type_id': 'w9:1840571385960505345', 'type_name': '萝莉·推荐'},
    {'type_id': 'w9:1840575476264615937', 'type_name': '萝莉·今日更新'},
    {'type_id': 'w9:1837368338654527489', 'type_name': '萝莉·少女反差'},
    {'type_id': 'w9:1837366364831850498', 'type_name': '萝莉·清纯萝莉'},
    {'type_id': 'w9:1837382638242717697', 'type_name': '萝莉·黑料吃瓜'},
    {'type_id': 'w9:1850808385254830081', 'type_name': '萝莉·约炮分享'},
    {'type_id': 'w9:1837368612865548290', 'type_name': '萝莉·福小姬'},
    {'type_id': 'w9:1838399286550564866', 'type_name': '萝莉·志同道合'},
    {'type_id': 'w9:1837384824024555521', 'type_name': '萝莉·户外露出'},
    {'type_id': 'w9:1837385350546030593', 'type_name': '萝莉·虚拟伴侣'},
    {'type_id': 'w9:1837386071119077377', 'type_name': '萝莉·唯美校花'},
]


def _b64e(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip('=')


def _b64d(s):
    try:
        return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except Exception:
        try:
            return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
        except Exception:
            return ''


def _aes_en(s):
    try:
        key = K2.encode()
        raw = s.encode()
        n = 16 - len(raw) % 16
        raw += bytes([n]) * n
        c = AES.new(key, AES.MODE_CBC, iv=key[:16])
        return base64.b64encode(c.encrypt(raw)).decode()
    except Exception:
        return ''


def _aes_de(ct):
    if not ct:
        return ''
    try:
        key = K2.encode()
        c = AES.new(key, AES.MODE_CBC, iv=key[:16])
        raw = c.decrypt(base64.b64decode(ct))
        n = raw[-1]
        if 0 < n < len(raw) and raw[-n:] == bytes([n]) * n:
            raw = raw[:-n]
        return raw.decode('utf-8', errors='ignore')
    except Exception:
        return ''


def _pic_shards(path):
    base = re.sub(r'\.\w+$', '', path)
    hd = {'User-Agent': UA, 'Referer': HOST + '/'}
    parts = []
    for i in (1, 2, 3):
        try:
            r = requests.get(PIC_API + base + '_{}3.txt'.format(i), headers=hd, timeout=10, verify=False)
            if r.status_code == 200 and len(r.content) > 10:
                parts.append(r.content[2:].decode('utf-8', errors='ignore'))
        except Exception:
            pass
    if len(parts) != 3:
        return b''
    try:
        return base64.b64decode(''.join(parts))
    except Exception:
        return b''


class _PicH(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            q = parse_qs(urlparse(self.path).query)
            u = unquote(q.get('url', [''])[0])
            body = _pic_shards(u)
            if not body:
                self.send_response(404)
                self.end_headers()
                return
            ctype = 'image/jpeg'
            if body[:8] == b'\x89PNG\r\n\x1a\n':
                ctype = 'image/png'
            elif body[:4] == b'RIFF':
                ctype = 'image/webp'
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            try:
                self.send_response(404)
                self.end_headers()
            except Exception:
                pass

    def log_message(self, *a):
        pass


_pic_port = 0


def _start_pic_proxy():
    global _pic_port
    if _pic_port:
        return _pic_port
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    _pic_port = s.getsockname()[1]
    s.close()
    try:
        t = ThreadingHTTPServer(('127.0.0.1', _pic_port), _PicH)
        threading.Thread(target=t.serve_forever, daemon=True).start()
    except Exception:
        _pic_port = 9978
    return _pic_port


def _pic_url(path):
    if not path:
        return ''
    return 'http://127.0.0.1:{}/pic?url={}'.format(_start_pic_proxy(), quote(path, safe=''))


class Spider(Spider):
    session = requests.Session()
    headers = {'User-Agent': UA, 'Referer': HOST + '/'}
    _cache = {}

    def getName(self):
        return '525071'

    def isVideoFormat(self, url):
        return bool(url and ('.m3u8' in url or '.mp4' in url or '.flv' in url))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return [404, 'text/plain', '']

    def init(self, extend=''):
        self.session.verify = False
        self.session.headers.update(self.headers)

    def _get_raw(self, url):
        try:
            r = self.session.get(url, timeout=15)
            if r.status_code != 200:
                return None
            return r.text
        except Exception:
            return None

    def _list(self, url, plain=False):
        k = url
        now = time.time()
        hit = self._cache.get(k)
        if hit and now - hit[0] < 180:
            return hit[1]
        txt = self._get_raw(url)
        arr = None
        if txt:
            try:
                d = json.loads(txt)
                if isinstance(d, list):
                    arr = d
                elif isinstance(d, dict) and d.get('json_data'):
                    p = _aes_de(d['json_data'])
                    obj = json.loads(p)
                    arr = obj if isinstance(obj, list) else []
            except Exception:
                arr = None
        if arr is None:
            arr = []
        self._cache[k] = (now, arr)
        return arr

    def _norm(self, it):
        if not isinstance(it, dict):
            return None
        title = it.get('title') or ''
        pic = it.get('mainImgUrl') or ''
        vu = it.get('videoUrl') or ''
        if not vu:
            pu = it.get('previewUrl') or ''
            if '/preview/preview.mp4' in pu:
                vu = pu.replace('/preview/preview.mp4', '/index.m3u8')
            elif '/preview.mp4' in pu:
                vu = pu.replace('/preview.mp4', '/index.m3u8')
        if not vu:
            return None
        if not vu.startswith('http'):
            vu = '/' + vu.lstrip('/')
        vid = _b64e('{}|{}|{}|{}'.format(vu, title, pic, it.get('duration') or ''))
        return {
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': _pic_url(pic) if pic else '',
            'vod_remarks': it.get('duration') or '',
            'vod_year': (it.get('createTime') or '')[:4],
        }

    def _items(self, arr):
        out = []
        for it in arr:
            d = self._norm(it)
            if d:
                out.append(d)
        return out

    def _fetch_cat(self, tid, page):
        typ = tid[:1]
        site = tid[1]
        cid = tid[3:]
        if typ == 'w':
            url = JSON_API + '/oss/pages/1/{}/water/{}/{}.json'.format(site, cid, page)
            return self._list(url)
        if typ == 'p':
            url = JSON_API + '/oss/pages/1/{}/water/{}/{}.json'.format(site, cid, page)
            return self._list(url, plain=True)
        if typ == 't':
            url = JSON_API + '/oss/pages/1/{}/new/{}/topic.json'.format(site, cid)
            arr = self._list(url)
            out = []
            for grp in arr:
                if isinstance(grp, dict):
                    out.extend(grp.get('videoList') or [])
            return out
        return []

    def _home_videos(self):
        arr = self._fetch_cat('w5:1867171983000444929', 0)
        return self._items(arr)[:20]

    def homeContent(self, filter=False):
        return {'class': CATEGORIES, 'list': self._home_videos()}

    def homeVideoContent(self):
        return {'list': self._home_videos()}

    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        p = int(pg) if pg else 1
        ipage = (p - 1) // 10
        off = (p - 1) % 10
        arr = self._fetch_cat(str(tid), ipage)
        if len(arr) == 200:
            pagecount = ipage * 10 + 10
        else:
            pagecount = ipage * 10 + max(1, (len(arr) + 19) // 20)
        if off * 20 >= len(arr):
            return {'page': p, 'pagecount': p - 1, 'limit': 20, 'total': ipage * 200 + len(arr), 'list': []}
        items = self._items(arr[off * 20:(off + 1) * 20])
        return {'page': p, 'pagecount': pagecount, 'limit': 20, 'total': ipage * 200 + len(arr), 'list': items}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else str(ids)
        raw = _b64d(vid)
        parts = raw.split('|') if raw else []
        if len(parts) < 3:
            return {'list': []}
        vu, title, pic, dur = parts[0], parts[1], parts[2], (parts[3] if len(parts) > 3 else '')
        urls = [d + vu for d in VIDEO_DOMAINS]
        d = {
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': _pic_url(pic) if pic else '',
            'vod_remarks': dur,
            'vod_content': title,
            'vod_play_from': '$$$'.join(['线路{}'.format(i + 1) for i in range(len(urls))]),
            'vod_play_url': '#'.join(['正片${}'.format(u) for u in urls]),
        }
        return {'list': [d]}

    def searchContent(self, key, quick=False, pg='1'):
        try:
            body = {'text': _aes_en(key), 'current': int(pg) if pg else 1, 'size': 20,
                    'sortType': 0, 'date': '', 'quality': '', 'duration': ''}
            r = self.session.post(SEARCH_API + '/search', json=body, timeout=15)
            t = r.json()
            arr = json.loads(_aes_de(t.get('json_data'))) if t.get('json_data') else []
            total = int(t.get('total') or 0)
            return {'list': self._items(arr), 'page': int(pg) if pg else 1,
                    'pagecount': max(1, (total + 19) // 20)}
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 1}

    def playerContent(self, flag, id, vipFlags=None):
        return {'parse': 0, 'url': id, 'header': {'User-Agent': UA, 'Referer': HOST + '/'}}
