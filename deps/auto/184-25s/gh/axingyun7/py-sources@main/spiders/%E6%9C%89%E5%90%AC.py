# -*- coding: utf-8 -*-
# 有听网 (https://m.ting15.com) TVBox 采集源 v1（2026-09-15 实测）
# 站点形态：有声小说站（非影视站），每本书 = 一个"条目"，每集为一段音频（m4a/mp3）。
#   首页      /                         精品推荐（tlist 区块）
#   分类页    /{cat}/                   第 1 页；/{cat}/index{N}.html 第 N 页（页次 x/y 真实分页）
#   详情页    /{cat}/{id}.html          书信息 + 分集列表（plist 区块，最多 3000+ 集单页全量）
#   播放章节  /{cat}/{id}/0-{n}.html    页面内 <audio> 无静态 src，音频地址由 JS 动态获取
#   音频接口  POST /?s=api-getneoplay   data: bookId&page -> {"url": "...m4a", "ourl": "", "status": 1}
#   搜索页    /?s=ting-search-wd-{quote(kw)}   多页: -p-{N}.html
#
# ============================ 协议要点（2026-09-15 全量实测）============================
# 1) 播放：章节页 <audio id="player"> 无 src，由 m_p.js POST /?s=api-getneoplay
#    （bookId/page 两参即可，isPay 可省略）返回 audio 直链；ourl 字段优先，否则 url。
#    status == -1 表示收费章节（如实返回空），-2 表示访问过快。
# 2) 防盗链：音频 CDN oss-links.guoguo.org.cn 必须携带 Referer: *.ting15.com
#    （m/www 均可）才返回 200，否则 301 跳 /sos/ 反盗链页；playerContent 返回 header
#    字段让播放器带 Referer 取流，并在源内做带 Referer 的真直链门禁（Range 采样校验
#    Content-Type 含 audio 或 ftyp 魔数）。
# 3) 封面：img-book-oss.guoguo.org.cn 实测带站点 Referer 返回 200 + JPEG/PNG 魔数正常，
#    但无 Referer 时返回 404（防盗链）；TVBox 客户端拉图不带 Referer 会全破图，因此本源
#    所有封面一律走壳端 localProxy 图片代理：vod_pic 输出 getProxyUrl()+base64(原图)，
#    localProxy 内带站点 Referer 拉取后返回字节（壳端图片代理 -> 本源 localProxy -> CDN）。
# 4) 搜索：GET /?s=ting-search-wd-{关键词}(URL 编码)，结果结构与分类页 clist 一致；
#    多结果时页次 x/y，分页路由 -p-{N}.html，本源支持按 pg 翻页。
# 5) 列表：分类页共 10 个分类（武侠玄幻/恐怖灵异/推理悬疑/都市言情/家庭伦理/官场职场/
#    经典评书/曲艺戏曲/相声小品/助眠音频），每页 8 项，页次数来自"页次 x/y"真实值。
# 6) 详情：binfo 区块给出书名/作者/播音/状态，plist 区块给出全部分集（链接文本为集数），
#    集数即接口 page 参数（第 n 集 <-> page=n，与音频文件名 000{n}.m4a 一致）。
# ======================================================================================
# 依赖：requests + 标准库（re/json/urllib），TVBox Python3 环境可直接运行。
import re
import json
import base64
from urllib.parse import quote
import requests

from base.spider import Spider

CATS = (
    ('/wuxiaxuanhuan/', '武侠玄幻'),
    ('/kongbulingyi/', '恐怖灵异'),
    ('/tuilixuanyi/', '推理悬疑'),
    ('/dushiyanqing/', '都市言情'),
    ('/jiatinglunli/', '家庭伦理'),
    ('/wenxuemingzhu/', '官场职场'),
    ('/jingdianpingshu/', '经典评书'),
    ('/quyixiqu/', '曲艺戏曲'),
    ('/xiangshengxiaopin/', '相声小品'),
    ('/yinyue/', '助眠音频'),
)


class Spider(Spider):
    def getName(self):
        return '有听网'

    def init(self, extend=''):
        self.name = '有听网'
        self.site = 'https://m.ting15.com'
        self.timeout = 20
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36',
            'Referer': self.site + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self._rec_cache = None

    # ----------------------------------------------------------
    # 通用请求与 HTML 工具
    # ----------------------------------------------------------
    def _get(self, url):
        try:
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code != 200:
                return ''
            r.encoding = 'utf-8'
            return r.text
        except Exception as e:
            print('[{}] request error: {}'.format(self.name, e))
            return ''

    def _post_play(self, data):
        """POST /?s=api-getneoplay，返回 JSON dict；异常返回 {}"""
        try:
            r = self.session.post(self.site + '/?s=api-getneoplay', data=data,
                                  headers={'X-Requested-With': 'XMLHttpRequest'},
                                  timeout=self.timeout)
            if r.status_code != 200:
                return {}
            # 站点接口响应带 UTF-8 BOM，直接 json.loads 会解析失败
            return json.loads(r.text.lstrip('\ufeff'))
        except Exception as e:
            print('[{}] play api error: {}'.format(self.name, e))
            return {}

    def _clean(self, s):
        return re.sub(r'\s+', ' ', (s or '').strip())

    def _fix_pic(self, url):
        u = (url or '').strip()
        if not u.startswith(('http://', 'https://')):
            return ''
        # 封面图床 img-book-oss.guoguo.org.cn 防盗链：不带站点 Referer 拉取返回 404。
        # TVBox 客户端图片加载器不带 Referer，直接返回原 URL 会全部破图；
        # 一律改走壳端 localProxy 图片代理（壳端图片加载器 -> 本源的 localProxy ->
        # CDN(带 Referer) -> 图片字节），封面才能正常显示。
        try:
            return self.getProxyUrl() + '&url=' + self.e64(u) + '&type=img'
        except Exception:
            return u

    def e64(self, text):
        try:
            return base64.b64encode(str(text).encode('utf-8')).decode('utf-8')
        except Exception:
            return ''

    def d64(self, encoded_text):
        try:
            return base64.b64decode(str(encoded_text).encode('utf-8')).decode('utf-8')
        except Exception:
            return ''

    def localProxy(self, param):
        """图片防盗链代理：解析壳端传来的 base64 图片地址，带站点 Referer
        拉取后原样返回字节；失败返回 404 空体（壳端显示默认占位图）。"""
        try:
            if param and param.get('type') == 'img':
                u = self.d64(param.get('url', ''))
                if not u:
                    return [404, 'text/plain', '', '']
                r = self.session.get(u, timeout=self.timeout)
                if r.status_code == 200 and r.content:
                    return [200, r.headers.get('Content-Type', 'image/jpeg'), r.content, {}]
        except Exception as e:
            print('[{}] localProxy error: {}'.format(self.name, e))
        return [404, 'text/plain', '', '']

    # ----------------------------------------------------------
    # 数据解析
    # ----------------------------------------------------------
    def _parse_items(self, html):
        """解析 clist 列表项（分类页/搜索页共用）：
        <a href="/{cat}/{id}.html"><dl><dt><img src="封面" alt="书名">
        <dd><h3>书名</h3><p>类别：..</p><p>作者：..</p><p>播音：..</p><p>时间：..</p>
        vod_id 取完整详情页路径，playerContent/detailContent 直接可用。"""
        out = []
        seen = set()
        for m in re.finditer(
                r'<a[^>]*href="(/[a-z]+/\d+\.html)"[^>]*>\s*<dl>\s*<dt>\s*<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*>\s*</dt>\s*<dd>\s*<h3>([^<]{1,100})</h3>([\s\S]*?)</dd>\s*</dl>',
                html, re.I):
            href, pic, alt, name, dd = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            if href in seen:
                continue
            seen.add(href)
            remarks = ''
            m2 = re.search(r'>播音\s*[:：]\s*([^<]{1,60})<', dd)
            if not m2:
                m2 = re.search(r'>类别\s*[:：]\s*([^<]{1,60})<', dd)
            if m2:
                remarks = self._clean(m2.group(1))
            out.append({
                'vod_id': href,
                'vod_name': self._clean(name or alt),
                'vod_pic': self._fix_pic(pic),
                'vod_remarks': remarks,
            })
        return out

    def _parse_recommend(self, html):
        """解析首页"精品推荐"（tlist 区块，结构略简）"""
        out = []
        seen = set()
        for m in re.finditer(
                r'<a[^>]*href="(/[a-z]+/\d+\.html)"[^>]*>\s*<dl>\s*<dt>\s*<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*>\s*</dt>\s*<dd>\s*<h3>([^<]{1,100})</h3>',
                html, re.I):
            href, pic, alt, name = m.group(1), m.group(2), m.group(3), m.group(4)
            if href in seen:
                continue
            seen.add(href)
            out.append({
                'vod_id': href,
                'vod_name': self._clean(name or alt),
                'vod_pic': self._fix_pic(pic),
                'vod_remarks': '',
            })
        return out

    def _parse_pagecount(self, html):
        """页次<span>{cur}/{total}</span> -> total"""
        m = re.search(r'页次<span>\d+/(\d+)</span>', html)
        return int(m.group(1)) if m else 1

    def _cat_url(self, tid, pg):
        """分类第 pg 页 URL：第 1 页为 /{cat}/，第 N 页为 /{cat}/index{N}.html"""
        cat = (str(tid) or '/').strip()
        if not cat.startswith('/'):
            cat = '/' + cat
        if not cat.endswith('/'):
            cat = cat + '/'
        return '{}{}index{}.html'.format(self.site, cat, pg) if pg > 1 else self.site + cat

    def _parse_detail(self, html):
        """详情页：书名/封面/播音/作者/状态/简介/全部分集"""
        info = {}
        m = re.search(r'<h1[^>]*>([^<]{1,100})</h1>', html)
        info['name'] = self._clean(m.group(1)) if m else ''
        m = re.search(r'<div class="bimg">\s*<img[^>]*src="([^"]*)"', html)
        info['pic'] = self._fix_pic(m.group(1)) if m else ''
        for key in ('播音', '作者', '状态', '时间'):
            m = re.search(r'<p>' + key + r'\s*[:：]\s*([^<]{1,100})</p>', html)
            if m:
                info[key] = self._clean(m.group(1))
        # 简介（页面有 2 个 intro 区块，取含 p 文本的后者；最末一个为内容简介）
        intros = re.findall(r'<div class="intro">\s*<p>([\s\S]*?)</p>', html)
        if intros:
            info['简介'] = self._clean(intros[-1])
        # 分集：plist 区块内 <a class="f" href=".../0-{n}.html">{n}</a>
        eps = []
        for m in re.finditer(r'<a class="f" href="(/[a-z]+/\d+/0-(\d+)\.html)">\s*(\d+)\s*</a>', html):
            href, n, label = m.group(1), int(m.group(2)), m.group(3)
            if n != int(label):
                continue
            eps.append((n, href))
        eps.sort(key=lambda x: x[0])
        info['eps'] = eps
        return info

    # ----------------------------------------------------------
    # TVBox 六接口
    # ----------------------------------------------------------
    def _recommend_list(self):
        """聚合推荐：首页精品推荐 + 前 4 个分类第 1 页，去重后最多 60 条。
        结果缓存到源生命周期内（homeContent/homeVideoContent 共用，避免重复请求）。"""
        if self._rec_cache is not None:
            return self._rec_cache
        out, seen = [], set()
        html = self._get(self.site + '/')
        for it in self._parse_recommend(html):
            if it['vod_id'] not in seen:
                seen.add(it['vod_id'])
                out.append(it)
        for cat, _name in CATS[:4]:
            if len(out) >= 60:
                break
            h = self._get(self._cat_url(cat, 1))
            for it in self._parse_items(h):
                if len(out) >= 60:
                    break
                if it['vod_id'] not in seen:
                    seen.add(it['vod_id'])
                    out.append(it)
        self._rec_cache = out
        return out

    def homeContent(self, filter):
        classes = [{'type_id': c[0], 'type_name': c[1]} for c in CATS]
        return {'class': classes, 'list': self._recommend_list(), 'filters': {}}

    def homeVideoContent(self):
        return {'list': self._recommend_list()}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        except Exception:
            pg = 1
        html = self._get(self._cat_url(tid, pg))
        lst = self._parse_items(html) if html else []
        pagecount = self._parse_pagecount(html) if html else 1
        # 第 1 页 URL 是 /{cat}/，正则兜底：无页次时按已有翻页链接推导
        if pagecount == 1 and html:
            cat = (str(tid) or '/').strip()
            if not cat.startswith('/'):
                cat = '/' + cat
            for m in re.finditer(r'href="' + re.escape(cat.rstrip('/')) + r'/index(\d+)\.html"', html):
                n = int(m.group(1))
                if n > pagecount:
                    pagecount = n
        total = len(lst) * pagecount
        return {'page': pg, 'pagecount': pagecount, 'limit': len(lst) if lst else 8,
                'total': total, 'list': lst}

    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, list) else ids)
        if not re.match(r'^/[a-z]+/\d+\.html$', vid):
            return {'list': []}
        html = self._get(self.site + vid)
        if not html:
            return {'list': []}
        info = self._parse_detail(html)
        base = re.sub(r'\.html$', '', vid)
        eps = info.get('eps') or []
        play_url = '#'.join('第{}集$ {}/0-{}.html'.format(n, base, n).replace('$ ', '$')
                            for n, _ in eps)
        vod = {
            'vod_id': vid,
            'vod_name': info.get('name') or vid.split('/')[-1].replace('.html', ''),
            'vod_pic': info.get('pic') or '',
            'vod_actor': info.get('作者') or '',
            'vod_director': info.get('播音') or '',
            'vod_content': info.get('简介') or '',
            'vod_remarks': info.get('状态') or (info.get('播音') or ''),
            'vod_play_from': '听书',
            'vod_play_url': play_url,
        }
        return {'list': [vod]}

    def searchContent(self, key, quick, pg='1'):
        key = str(key).strip()
        if not key:
            return {'list': []}
        try:
            pg = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        except Exception:
            pg = 1
        kw = quote(key)
        url = '{}/?s=ting-search-wd-{}{}'.format(
            self.site, kw, '-p-{}.html'.format(pg) if pg > 1 else '')
        html = self._get(url)
        lst = self._parse_items(html) if html else []
        return {'list': lst}

    def playerContent(self, flag, id, vipFlags):
        # id 为详情页构造的章节路径 /{cat}/{id}/0-{n}.html
        id = str(id)
        m = re.search(r'^/([a-z]+)/(\d+)/0-(\d+)\.html', id)
        if not m:
            return {'parse': 0, 'url': ''}
        book_id, page = m.group(2), m.group(3)
        data = self._post_play({'bookId': book_id, 'page': page})
        if not data or data.get('status') == -1:
            # -1 为收费章节（本站试听版页面上会提示"本章节收费"）
            return {'parse': 0, 'url': ''}
        url = (data.get('ourl') or '').strip() or (data.get('url') or '').strip()
        if not url:
            return {'parse': 0, 'url': ''}
        url = self._probe_media(url)
        if not url:
            return {'parse': 0, 'url': ''}
        return {'parse': 0, 'url': url,
                'header': json.dumps({'User-Agent': self.headers['User-Agent'],
                                      'Referer': 'https://m.ting15.com/'})}

    def _probe_media(self, url):
        """真直链门禁：带 Referer 取响应头 4KB，校验 Content-Type 含 video/audio
        或文件头 ftyp 才放行（Can CDN 无 Referer 会 301 到 /sos/，探测即被拦截）。"""
        try:
            r = self.session.get(url, headers={'Range': 'bytes=0-4095'},
                                 timeout=self.timeout, stream=True)
            data = next(r.iter_content(4096), b'')
            if not r.ok:
                return ''
            ctype = r.headers.get('Content-Type', '').lower()
            if 'video/' in ctype or 'audio/' in ctype or data[4:8] == b'ftyp':
                return r.url
            if '.m3u8' in r.url.lower() and b'#EXTM3U' in data:
                return r.url
            return ''
        except Exception:
            return ''