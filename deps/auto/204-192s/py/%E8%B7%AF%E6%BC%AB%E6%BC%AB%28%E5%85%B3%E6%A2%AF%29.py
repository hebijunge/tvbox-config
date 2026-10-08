# -*- coding: utf-8 -*-
"""
路漫漫在线动漫 · TVBox / 影视仓 / OK影视 / PickTV Spider
站点: https://www.lmm85.com/  (MacCMS jable 模板 · 前置 Cloudflare 托管挑战)

★ 为什么不抓网页
  主站 www.lmm85.com 与备用域名 m.lm6.net 全站（含 /api.php、静态资源）均返回
  CF 403 "Just a moment" 托管挑战，Python 无法执行 JS 校验。本源改用站点
  安卓 APP 的接口域名，实测无 CF、无 UA 限制，纯标准库可直连。

数据接口(APP API, 无 CF):
  /api.php/Appapi/vod?type_id={tid}&pg={pg}[&year=][&by=][&wd=]   列表/搜索
  /api.php/Appapi/vod?ids={vod_id}                                 详情(含播放串)
  /api.php/Appapi/vod?pg=1  → 字段 class 返回全部一级分类
  /api.php/Appapi/toplist / topic / appconfig/index                榜单/专题/配置

播放解析(云解析服务 yun.92cj.com):
  1) 详情接口给出每条线路的播放串，形态三类:
       明文直链            https://.../index.m3u8            → 直出
       DOU6_<b64>&t=ecvod   ykbox 线路                       → type=ecvod
       DU_<b64>&t=DU        tudou 线路                       → type=DU
       <数字>_<小写串>       xgvxcd / vxdev 线路              → type=vxcd / vxdev
  2) GET  https://yun.92cj.com/yunbox/?type={type}&vid={串}&referer={播放页}
     ——必须带 Referer 头=播放页 URL，否则返回空页
     页面内联: var vid / var t / var token / $.post("xxx.php", ...)
  3) token 为 AES-128-CBC(OpenSSL 无 salt) 密文，密钥/IV 见 _AES_KEY/_AES_IV，
     解密得 32 位 hex 校验值（站点 player 里叫 getc()）
  4) POST https://yun.92cj.com/yunbox/{xxx.php}
     body: vid / t / token(解密值) / act=0 / play=1
     返回 {"code":200,"ext":"mp4|link","referer":"never","url":"真实地址"}
     ext=link 时 url 为可 iframe 的外链；referer=never 表示播放不得携带 Referer

壳契约: class Spider 无继承 · 13 接口齐全 · 位置参数 · playerContent.header 为 dict
        · 直链 parse=0/jx=0 · 播放 id 用短串 play|vid|sid|nid 不塞长 URL
"""
import re
import json
import base64
import urllib.parse
import urllib.request
import urllib.error

# ===================== 纯标准库 AES-128-CBC 解密 =====================
_SBOX = bytes.fromhex(
    '637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0'
    'b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275'
    '09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf'
    'd0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2'
    'cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb'
    'e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08'
    'ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e'
    'e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16')
_ISBOX = bytearray(256)
for _i, _v in enumerate(_SBOX):
    _ISBOX[_v] = _i
_ISBOX = bytes(_ISBOX)
_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36)
_MUL = {}
for _c in (9, 11, 13, 14):
    _t = [0] * 256
    for _b in range(256):
        _r, _x, _m = 0, _b, _c
        while _m:
            if _m & 1:
                _r ^= _x
            _x <<= 1
            if _x & 0x100:
                _x = (_x ^ 0x1b) & 0xff
            _m >>= 1
        _t[_b] = _r
    _MUL[_c] = _t


def _aes_expand_key(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _aes_decrypt_block(block, w):
    s = list(block)
    for c in range(4):
        for r in range(4):
            s[c * 4 + r] ^= w[40 + c][r]
    for rnd in range(9, 0, -1):
        for r in (1, 2, 3):                       # InvShiftRows
            row = [s[r + 4 * c] for c in range(4)]
            row = row[-r:] + row[:-r]
            for c in range(4):
                s[r + 4 * c] = row[c]
        s = [_ISBOX[b] for b in s]                # InvSubBytes
        for c in range(4):                        # AddRoundKey
            for r in range(4):
                s[c * 4 + r] ^= w[rnd * 4 + c][r]
        m9, m11, m13, m14 = _MUL[9], _MUL[11], _MUL[13], _MUL[14]
        for c in range(4):                        # InvMixColumns
            i = c * 4
            a0, a1, a2, a3 = s[i], s[i + 1], s[i + 2], s[i + 3]
            s[i] = m14[a0] ^ m11[a1] ^ m13[a2] ^ m9[a3]
            s[i + 1] = m9[a0] ^ m14[a1] ^ m11[a2] ^ m13[a3]
            s[i + 2] = m13[a0] ^ m9[a1] ^ m14[a2] ^ m11[a3]
            s[i + 3] = m11[a0] ^ m13[a1] ^ m9[a2] ^ m14[a3]
    for r in (1, 2, 3):
        row = [s[r + 4 * c] for c in range(4)]
        row = row[-r:] + row[:-r]
        for c in range(4):
            s[r + 4 * c] = row[c]
    s = [_ISBOX[b] for b in s]
    for c in range(4):
        for r in range(4):
            s[c * 4 + r] ^= w[c][r]
    return bytes(s)


def _aes_cbc_decrypt(data, key, iv):
    w = _aes_expand_key(key)
    out = bytearray()
    prev = bytes(iv)
    for off in range(0, len(data) - 15, 16):
        blk = data[off:off + 16]
        dec = _aes_decrypt_block(blk, w)
        out += bytes(a ^ b for a, b in zip(dec, prev))
        prev = blk
    if out:
        pad = out[-1]
        if 1 <= pad <= 16 and pad <= len(out):
            out = out[:-pad]
    return bytes(out)


# ===================== 站点常量 =====================
_AES_KEY = bytes.fromhex('265f4d5026477a465375384d5f6a6b70')
_AES_IV = bytes.fromhex('347763794967682b23674b4476285243')

# 线路标识 → 站点播放器显示名(取自 /static/js/playerconfig.js)
_LINE_NAME = {
    'ykbox': 'box聚合', 'tudou': '聚合线路', 'xgvxcd': 'vx云播', 'vxdev': 'dev云播',
    'dpmp4': 'dp云播', 'dpwxv': 'wxv云播', 'hls': 'hls云播', 'xigua': 'xgsp云播',
    'iqiyi': 'iq云播', 'migu': 'migu云播', 'pptv': 'pp云播', 'qqcd': 'qq云播',
    'qqqy': 'qqqy云播', 'qxyun': 'qx云播', 'svod': 'svod云播', 'tv189': '189速播',
    'link': '外链', 'iframe': 'iframe外链',
}
# 广告占位视频特征：站点在片源失效的线路上回填快手广告联盟视频，
# 直接播会看到广告，故在详情构造阶段剔除该集
_AD_MARK = ('adkwai.com', 'adukwai.com', 'ad-dpa', 'advideolp', 'ad_alliance')

_YEARS = ['2026', '2025', '2024', '2023', '2022', '2021', '2020', '2019', '2018', '2017']
_SORTS = [('time', '最近更新'), ('hits', '最高人气'), ('score', '最高评分'), ('up', '最多点赞')]
# 父分类在 APP 列表接口里没有数据（t=1/t=2 恒返回 0 条），
# 改为按子分类同页合并后本地排序：动漫=6120 部、电影=1834 部（与网页版口径一致）
_PARENT_MAP = {
    '1': ['6', '7', '8', '22', '23'],   # 动漫 → 日本/国产/欧美动漫 + 动态漫画 + 日本特摄剧
    '2': ['3', '4', '5'],               # 电影 → 日本/国产/欧美动画电影
}


class Spider:
    def __init__(self):
        self.api = 'https://b4e2ef27af2dec0e.lmm35.com'
        self.api_bak = 'https://b4e2ef27af2dec0e.ho9.cc'
        self.resolver = 'https://yun.92cj.com'
        self.web = 'https://www.lmm85.com'
        self.ua = ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/134.0.0.0 Mobile Safari/537.36')
        self.limit = 30
        self._classes = None

    # ================= 内部工具 =================
    def _open(self, url, referer=None, data=None, timeout=15, extra=None):
        h = {'User-Agent': self.ua, 'Accept-Language': 'zh-CN,zh;q=0.9'}
        if referer:
            h['Referer'] = referer
        if data is not None:
            h['Content-Type'] = 'application/x-www-form-urlencoded'
            h['X-Requested-With'] = 'XMLHttpRequest'
        if extra:
            h.update(extra)
        req = urllib.request.Request(url, data=data, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.geturl()

    def _api(self, path):
        """APP 接口请求，主域名失败自动换备用域名"""
        for host in (self.api, self.api_bak):
            try:
                raw, _ = self._open(host + path, timeout=15)
                return json.loads(raw.decode('utf-8', 'ignore'))
            except Exception:
                continue
        return {}

    def _list_from(self, data):
        items = []
        for it in (data.get('list') or []):
            try:
                items.append({
                    'vod_id': str(it.get('vod_id')),
                    'vod_name': str(it.get('vod_name') or '').strip(),
                    'vod_pic': str(it.get('vod_pic') or it.get('vod_pic_thumb') or ''),
                    'vod_remarks': str(it.get('vod_remarks') or ''),
                })
            except Exception:
                continue
        return items

    def _pager(self, data, pg):
        pc = data.get('pagecount') or pg
        try:
            pc = int(pc)
        except Exception:
            pc = int(pg)
        # 服务端在带 limit 参数时 total 字段不可靠(会回填成 limit)，取两者较大值
        try:
            total = int(data.get('total') or 0)
        except Exception:
            total = 0
        total = max(total, pc * self.limit)
        return {
            'page': str(pg),
            'pagecount': str(pc),
            'limit': str(self.limit),
            'total': str(total),
        }

    def _classes_get(self):
        if self._classes:
            return self._classes
        d = self._api('/api.php/Appapi/vod?pg=1&limit=1')
        cls = d.get('class') or []
        out = []
        for c in cls:
            try:
                out.append((str(c.get('type_id')), str(c.get('type_name') or '')))
            except Exception:
                continue
        if not out:
            out = [('1', '动漫'), ('2', '电影'), ('3', '日本动画电影'), ('4', '国产动画电影'),
                   ('5', '欧美动画电影'), ('6', '日本动漫'), ('7', '国产动漫'), ('8', '欧美动漫'),
                   ('22', '动态漫画'), ('23', '日本特摄剧')]
        self._classes = out
        return out

    def _filters(self):
        year = [{'n': '全部', 'v': ''}] + [{'n': y, 'v': y} for y in _YEARS] + \
               [{'n': '更早', 'v': '2016-1980'}]
        sort = [{'n': n, 'v': v} for v, n in _SORTS]
        groups = [
            {'key': 'year', 'name': '年份', 'value': year},
            {'key': 'by', 'name': '排序', 'value': sort},
        ]
        return dict((tid, groups) for tid, _ in self._classes_get())

    def _first_id(self, ids):
        """入参兼容 list / tuple / dict / JSON 字符串 / 纯字符串"""
        if isinstance(ids, (list, tuple)):
            return str(ids[0]) if ids else ''
        if isinstance(ids, dict):
            for k in ('id', 'vod_id', 'value'):
                if ids.get(k):
                    return str(ids[k])
            return ''
        s = str(ids or '').strip()
        if s.startswith('['):
            try:
                arr = json.loads(s)
                if isinstance(arr, list) and arr:
                    return str(arr[0])
            except Exception:
                pass
        m = re.search(r'\d+', s)
        return m.group(0) if m else s

    # ================= 播放解析 =================
    def _getc(self, token):
        """站点 player 的 getc(): AES-128-CBC 解出 32 位 hex 校验值"""
        try:
            return _aes_cbc_decrypt(base64.b64decode(token), _AES_KEY, _AES_IV).decode('utf-8', 'ignore')
        except Exception:
            return ''

    def _resolve_once(self, enc, referer, typ):
        page = '%s/yunbox/?type=%s&vid=%s&referer=%s' % (
            self.resolver, typ, enc, urllib.parse.quote(referer, safe=''))
        try:
            raw, final = self._open(page, referer=referer, timeout=20)
        except Exception:
            return ''
        html = raw.decode('utf-8', 'ignore')
        g = lambda n: (re.search(r'var %s\s*=\s*"([^"]*)"' % n, html) or [None, ''])[1]
        vid, t, token = g('vid'), g('t'), g('token')
        post = (re.search(r'post\(\s*"([^"]+)"', html) or [None, ''])[1]
        if not token or not post:
            return ''
        target = urllib.parse.urljoin(final.split('?')[0], post)
        body = urllib.parse.urlencode({
            'vid': vid, 't': t, 'token': self._getc(token), 'act': '0', 'play': '1',
        }).encode()
        try:
            raw2, _ = self._open(target, referer=final, data=body, timeout=20,
                                 extra={'Origin': self.resolver})
            ret = json.loads(raw2.decode('utf-8', 'ignore'))
        except Exception:
            return ''
        if str(ret.get('code')) != '200':
            return ''
        return str(ret.get('url') or '')

    def _is_ad(self, url):
        u = (url or '').lower()
        return any(m in u for m in _AD_MARK)

    def _resolve(self, enc, referer):
        enc = (enc or '').strip()
        if not enc:
            return ''
        if enc.startswith('http://') or enc.startswith('https://'):
            # 站点部分明文直链把 query 分隔符写成了 &（如 ...m3u8&t=hls&ct=1），
            # 原样请求会 404，这里把紧跟 .m3u8/.mp4 之后的第一个 & 修正为 ?
            m = re.match(r'^(https?://[^&?]*\.(?:m3u8|mp4))&(.+)$', enc)
            if m:
                enc = m.group(1) + '?' + m.group(2)
            return enc                                     # 明文直链
        m = re.search(r'&t=([A-Za-z0-9_]+)\s*$', enc)
        if m:
            types = [m.group(1)]
        elif re.match(r'^\d+_[a-z0-9]+$', enc):
            types = ['vxcd', 'vxdev']                      # xgvxcd / vxdev 线路
        else:
            types = ['ecvod']
        for t in types:
            url = self._resolve_once(enc, referer, t)
            if url:
                return url
        return ''

    # ================= 壳接口 =================
    def getName(self):
        return '路漫漫'

    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        u = (url or '').lower()
        return u.endswith('.m3u8') or u.endswith('.mp4') or '.m3u8?' in u or '.mp4?' in u

    def manualVideoCheck(self):
        return False

    def init(self, extend):
        try:
            if extend:
                cfg = extend if isinstance(extend, dict) else json.loads(extend)
                if isinstance(cfg, dict):
                    if cfg.get('api'):
                        self.api = str(cfg['api']).rstrip('/')
                    if cfg.get('limit'):
                        self.limit = int(cfg['limit'])
        except Exception:
            pass
        return None

    def destroy(self):
        return None

    def homeContent(self, filter):
        classes = [{'type_id': tid, 'type_name': name} for tid, name in self._classes_get()]
        d = self._api('/api.php/Appapi/vod?pg=1&limit=%d' % self.limit)
        return {'class': classes, 'list': self._list_from(d), 'filters': self._filters()}

    def homeVideoContent(self):
        d = self._api('/api.php/Appapi/vod?pg=1&limit=%d' % self.limit)
        return {'list': self._list_from(d)}

    def _vod_query(self, tid, pg, year, by, limit):
        """APP 列表接口的查询串。
        ★ 分类参数是 t（不是 type_id —— type_id/tid/class 实测均被忽略，
          传了等于没传，会导致所有分类返回同一份列表）。
        """
        params = ['t=%s' % tid, 'pg=%d' % pg, 'limit=%d' % limit]
        if year:
            params.append('year=' + urllib.parse.quote(year, safe='-'))
        if by:
            params.append('by=' + urllib.parse.quote(by, safe=''))
        return '/api.php/Appapi/vod?' + '&'.join(params)

    def _sort_key(self, it, by):
        if by in ('hits', 'score', 'up'):
            try:
                return float(it.get('vod_' + by) or 0)
            except Exception:
                return 0.0
        return str(it.get('vod_time') or '')

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        ext = {}
        if isinstance(extend, dict):
            ext = extend
        elif isinstance(extend, str) and extend.strip().startswith('{'):
            try:
                ext = json.loads(extend)
            except Exception:
                ext = {}
        year = str(ext.get('year') or '').strip()
        by = str(ext.get('by') or '').strip()
        subs = _PARENT_MAP.get(str(tid))
        if not subs:
            d = self._api(self._vod_query(tid, pg, year, by, self.limit))
            r = {'list': self._list_from(d)}
            r.update(self._pager(d, pg))
            return r
        # 父分类(动漫/电影)：接口对 t=1/t=2 返回 0 条，改为按子分类同页合并后本地排序
        merged, seen, pc = [], set(), 1
        for sub in subs:
            d = self._api(self._vod_query(sub, pg, year, by, self.limit))
            for it in (d.get('list') or []):
                vid = str(it.get('vod_id'))
                if vid in seen:
                    continue
                seen.add(vid)
                merged.append(it)
            try:
                pc = max(pc, int(d.get('pagecount') or 1))
            except Exception:
                pass
        merged.sort(key=lambda x: self._sort_key(x, by), reverse=True)
        return {
            'list': self._list_from({'list': merged[:self.limit]}),
            'page': str(pg),
            'pagecount': str(pc),
            'limit': str(self.limit),
            'total': str(pc * self.limit),
        }

    def detailContent(self, ids):
        vid = self._first_id(ids)
        if not vid:
            return {'list': []}
        d = self._api('/api.php/Appapi/vod?ids=' + urllib.parse.quote(vid, safe=''))
        lst = d.get('list') or []
        if not lst:
            return {'list': []}
        it = lst[0]
        froms = [x for x in str(it.get('vod_play_from') or '').split('$$$') if x]
        groups = it.get('vod_play_url_list') or []
        if not groups:                                   # 兜底：解析 vod_play_url 字符串
            raw = str(it.get('vod_play_url') or '')
            groups = [{'urls': [{'name': p.split('$')[0], 'url': p.split('$')[1]}
                                for p in blk.split('#') if '$' in p]}
                      for blk in raw.split('$$$')]
        play_from, play_url = [], []
        used = {}
        for i, grp in enumerate(groups):
            eps = []
            for ni, e in enumerate(grp.get('urls') or []):
                name = str(e.get('name') or '').strip()
                url = str(e.get('url') or '').strip()
                if not url:
                    continue
                if url.startswith('http') and self._is_ad(url):
                    continue                             # 广告占位集，剔除
                eps.append('%s$play|%s|%d|%d' % (
                    name or ('第%d集' % (ni + 1)), vid, i + 1, ni + 1))
            if not eps:
                continue
            key = froms[i] if i < len(froms) else ''
            name = _LINE_NAME.get(key, key or ('线路%d' % (i + 1)))
            if name in used:
                used[name] += 1
                name = '%s%d' % (name, used[name])
            else:
                used[name] = 1
            play_from.append(name)
            play_url.append('#'.join(eps))
        vod = {
            'vod_id': vid,
            'vod_name': str(it.get('vod_name') or '').strip(),
            'vod_pic': str(it.get('vod_pic') or it.get('vod_pic_thumb') or ''),
            'type_name': str(it.get('type_name') or ''),
            'vod_year': str(it.get('vod_year') or ''),
            'vod_area': str(it.get('vod_area') or ''),
            'vod_lang': str(it.get('vod_lang') or ''),
            'vod_remarks': str(it.get('vod_remarks') or ''),
            'vod_score': str(it.get('vod_score') or ''),
            'vod_actor': str(it.get('vod_actor') or ''),
            'vod_director': str(it.get('vod_director') or ''),
            'vod_content': str(it.get('vod_blurb') or it.get('vod_content') or '').replace('\n', ' '),
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }
        return {'list': [vod]}

    def searchContent(self, key, quick=False, pg='1', *args, **kwargs):
        pg = int(pg) if str(pg).isdigit() else 1
        d = self._api('/api.php/Appapi/vod?wd=%s&pg=%d&limit=%d' % (
            urllib.parse.quote(str(key or ''), safe=''), pg, self.limit))
        r = {'list': self._list_from(d)}
        r.update(self._pager(d, pg))
        return r

    def playerContent(self, flag, id, vipFlags):
        header = {'User-Agent': self.ua}
        sid = str(id or '').strip()
        # 已是直链或加密串，直接解析
        if sid.startswith('http') or '&t=' in sid or re.match(r'^\d+_[a-z0-9]+$', sid):
            url = self._resolve(sid, self.web + '/')
            if url:
                return {'parse': 0, 'jx': 0, 'url': url, 'header': header}
            return {'parse': 1, 'jx': 0, 'url': sid, 'header': header}
        m = re.match(r'^play\|(\d+)\|(\d+)\|(\d+)$', sid)
        if not m:
            return {'parse': 0, 'jx': 0, 'url': '', 'header': header}
        vid, s_i, n_i = m.group(1), int(m.group(2)), int(m.group(3))
        d = self._api('/api.php/Appapi/vod?ids=' + vid)
        lst = d.get('list') or []
        if not lst:
            return {'parse': 0, 'jx': 0, 'url': '', 'header': header}
        it = lst[0]
        groups = it.get('vod_play_url_list') or []
        enc = ''
        if 1 <= s_i <= len(groups):
            urls = groups[s_i - 1].get('urls') or []
            if 1 <= n_i <= len(urls):
                enc = str(urls[n_i - 1].get('url') or '')
        if not enc:                                      # 兜底：字符串形态
            blocks = str(it.get('vod_play_url') or '').split('$$$')
            if 1 <= s_i <= len(blocks):
                eps = blocks[s_i - 1].split('#')
                if 1 <= n_i <= len(eps) and '$' in eps[n_i - 1]:
                    enc = eps[n_i - 1].split('$')[1]
        if not enc:
            return {'parse': 0, 'jx': 0, 'url': '', 'header': header}
        referer = '%s/play/%s_%d_%d.html' % (self.web, vid, s_i, n_i)
        url = self._resolve(enc, referer)
        if url:
            # 云解析返回 referer=never：播放不得带 Referer，否则 CDN 拒绝
            return {'parse': 0, 'jx': 0, 'url': url, 'header': header}
        return {'parse': 1, 'jx': 0, 'url': referer, 'header': header}

    def localProxy(self, param):
        return [404, 'text/plain', b'not found', {}]

    def action(self, action):
        return None
