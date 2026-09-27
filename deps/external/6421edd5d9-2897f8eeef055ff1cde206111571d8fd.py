import sys, uuid, json
import urllib.parse
from base.spider import Spider

sys.path.append('..')

class Spider(Spider):
    local_uuid = ''
    config = {}
    parsing_config = {}
    # 硬编码默认地址，确保无须传参也能运行[cite: 1]
    host = 'http://v.2video.cc'
    headers = {
        'User-Agent': "Dart/2.19 (dart:io)",
        'Accept-Encoding': "gzip",
        'appto-local-uuid': ''
    }

    def init(self, extend=""):
        try:
            # 如果传了参数就用参数，没传就用上面默认的 host[cite: 1]
            arg_host = extend.strip()
            if arg_host.startswith('http'):
                self.host = arg_host
            
            self.local_uuid = str(uuid.uuid4())
            self.headers['appto-local-uuid'] = self.local_uuid
            
            # 获取核心配置[cite: 1]
            res = self.fetch(f'{self.host}/addons/apptov4/app.php/v1/config/get?p=android&__platform=android', headers=self.headers).json()
            self.config = res.get('data', {})
            
            # 智能提取播放解析配置
            parsing_conf = self.config.get('get_parsing', [])
            parsing_config = {}
            for i in parsing_conf:
                if i.get('config'):
                    labels = [j['label'] for j in i['config'] if j.get('type') == 'json']
                    if labels:
                        parsing_config[i['key']] = labels
            self.parsing_config = parsing_config
        except Exception as e:
            print(f'初始化异常：{e}')
            return {}

    def homeContent(self, filter):
        classes = []
        filters = {}
        # 1. 获取主分类[cite: 1]
        home_cate = self.config.get('get_home_cate', [])
        for i in home_cate:
            cate_id = i.get('cate')
            if cate_id is not None and str(cate_id) != '0':
                classes.append({'type_id': str(cate_id), 'type_name': i.get('title', '')})

        # 2. 备用分类获取[cite: 1]
        types = self.config.get('get_type', [])
        if not classes:
            for t in types:
                if t.get('type_pid') == 0 and t.get('type_name') != '全部':
                    classes.append({'type_id': str(t.get('type_id')), 'type_name': t.get('type_name', '').strip()})

        # 3. 筛选器组装[cite: 1]
        for t in types:
            t_id = str(t.get('type_id'))
            extend = t.get('type_extend', {})
            f_list = []
            def format_filter(key, name, raw_str):
                if not raw_str: return None
                items = [{"n": "全部", "v": ""}]
                for v in raw_str.split(','):
                    if v.strip(): items.append({"n": v.strip(), "v": v.strip()})
                return {"key": key, "name": name, "value": items}

            if extend.get('class'): f_list.append(format_filter("type_name", "分类", extend['class']))
            if extend.get('area'): f_list.append(format_filter("area", "地区", extend['area']))
            if extend.get('year'): f_list.append(format_filter("year", "年份", extend['year']))
            f_list.append({"key": "order", "name": "排序", "value": [{"n": "最新", "v": "time"}, {"n": "最热", "v": "hits"}]})
            filters[t_id] = f_list

        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        try:
            url = f'{self.host}/addons/apptov4/app.php/v1/home/cateData?id=2&__platform=android'
            res = self.fetch(url, headers=self.headers).json()
            vod_list = []
            for sec in res.get('data', {}).get('sections', []):
                for item in sec.get('items', []):
                    if item.get('vod_id'):
                        vod_list.append({
                            "vod_id": str(item.get('vod_id')),
                            "vod_name": item.get('vod_name'),
                            "vod_pic": self._fix_pic(item.get('vod_pic')),
                            "vod_remarks": item.get('vod_remarks') or item.get('vod_score') or ''
                        })
            return {'list': vod_list[:30]}
        except: return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        params = {
            'type_id': tid, 'page': pg, 'pageSize': 21, '__platform': 'android',
            'type_name': extend.get('type_name', ''), 'area': extend.get('area', ''),
            'year': extend.get('year', ''), 'order': extend.get('order', 'time'), 'sort': 'desc'
        }
        url = f"{self.host}/addons/apptov4/app.php/v1/vod/getLists"
        res = self.fetch(url, params=params, headers=self.headers).json()
        data = res.get('data', {})
        return {'list': self._fix_vod_list(data.get('data', [])), 'page': int(pg), 'total': data.get('total', 0)}

    def detailContent(self, ids):
        url = f"{self.host}/addons/apptov4/app.php/v1/vod/getVod?id={ids[0]}&__platform=android"
        res = self.fetch(url, headers=self.headers).json()
        data = res.get('data', {})
        vod_play_url, vod_play_from = [], []
        for i in data.get('vod_play_list', []):
            play_from = i.get('player_info', {}).get('from', 'default')
            play_show = i.get('player_info', {}).get('show', play_from)
            urls = [f"{j['name']}${play_from}@{j['url']}" for j in i.get('urls', [])]
            vod_play_from.append(play_show)
            vod_play_url.append("#".join(urls))

        video = {
            'vod_id': data.get('vod_id'), 'vod_name': data.get('vod_name'),
            'vod_pic': self._fix_pic(data.get('vod_pic')),
            'vod_content': '保护正版，人人有责'+data.get('vod_content'), 'vod_play_from': "$$$".join(vod_play_from),
            'vod_play_url': "$$$".join(vod_play_url)
        }
        return {'list': [video]}

    def searchContent(self, key, quick, pg='1'):
        url = f"{self.host}/addons/apptov4/app.php/v1/vod/getVodSearch?wd={key}&page={pg}&pageSize=20&__platform=android"
        res = self.fetch(url, headers=self.headers).json()
        data = res.get('data', {})
        return {'list': self._fix_vod_list(data.get('data', [])), 'page': int(pg), 'total': data.get('total', 0)}

    def playerContent(self, flag, id, vipflags):
        default_ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1'
        parts = id.split('@')
        if len(parts) != 2: return {'parse': 0, 'url': id, 'header': {'User-Agent': default_ua}}
        
        playfrom, rawurl = parts
        label_list = self.parsing_config.get(playfrom, ['默认'])
        
        for label in label_list:
            try:
                payload = {'play_url': rawurl, 'label': label, 'key': playfrom}
                proxy_res = self.post(f"{self.host}/addons/apptov4/app.php/v1/parsing/proxy?__platform=android", 
                                     data=payload, headers=self.headers).json()
                if proxy_res.get('code') == 1 and proxy_res.get('data', {}).get('url'):
                    p_data = proxy_res['data']
                    return {'parse': 0, 'url': p_data.get('url'), 'header': {'User-Agent': p_data.get('UA') or default_ua}}
            except: continue
        return {'parse': 1, 'url': rawurl, 'header': {'User-Agent': default_ua}}

    # 需要代理的图片域名（有防盗链限制）及其对应 Referer
    PIC_PROXY_RULES = {
        'img.bwcgee.cn': 'http://img.bwcgee.cn/',
    }

    def _fix_pic(self, url):
        """检测图片 URL 是否需要代理，需要则替换为本地代理地址"""
        if not url:
            return url
        for domain in self.PIC_PROXY_RULES:
            if domain in url:
                return f'proxy?url={urllib.parse.quote(url, safe="")}'
        return url

    def _fix_vod_list(self, vod_list):
        """批量修复列表中的 vod_pic"""
        for v in vod_list:
            if v.get('vod_pic'):
                v['vod_pic'] = self._fix_pic(v['vod_pic'])
        return vod_list

    def getName(self): return "无极V4"
    def isVideoFormat(self, url): pass
    def manualVideoCheck(self): pass
    def destroy(self): pass

    def localProxy(self, param):
        """代理防盗链图片：给请求加上正确的 Referer 后返回图片内容"""
        try:
            url = param.get('url', '')
            if not url:
                return [404, 'text/plain', None, None]
            # 找到对应的 Referer
            referer = ''
            for domain, ref in self.PIC_PROXY_RULES.items():
                if domain in url:
                    referer = ref
                    break
            fetch_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
                'Referer': referer,
            }
            r = self.fetch(url, headers=fetch_headers)
            content_type = r.headers.get('Content-Type', 'image/jpeg')
            return [200, content_type, None, r.content]
        except Exception as e:
            print(f'localProxy error: {e}')
            return [404, 'text/plain', None, None]