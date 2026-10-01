# coding=utf-8
# !/usr/bin/python
from urllib.parse import quote
import urllib.parse
import requests
from bs4 import BeautifulSoup
import re
from base.spider import Spider
import sys
import json
import os
import base64
import threading
import concurrent.futures
import shutil

sys.path.append('..')
xurl2 = "http://8.146.205.47:5013"
headerx = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36'
}
cpu_count = os.cpu_count()
if cpu_count is None:
    max_workers = 4
else:
    max_workers = cpu_count * 2


class Spider(Spider):
    global xurl2
    global headerx
    global pm

    def getName(self):
        return "首页"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def fl(self, txt):
        videos = []
        js1 = json.loads(txt)
        for item in js1:
            name = item['name']
            if '金瓶梅' in name:
                continue
            href = item['id']
            pic2 = item['pic']
            if 'doubanio' in pic2:
                pic = pic2+'@Referer=https://www.douban.com/'
            else:
                pic = pic2
            remark = item['remark']
            video = {
                "vod_id": href,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remark
            }
            videos.append(video)
        return videos

    def homeContent(self, filter):
        result = {}
        result = {
            'class': [
                {'type_id': '1', 'type_name': '电影'},
                {'type_id': '2', 'type_name': '电视剧'},
                {"type_id": "8", "type_name": "蓝光原盘"},
                {'type_id': '7', 'type_name': 'TVB'},
                {'type_id': '3', 'type_name': '综艺'},
                {'type_id': '4', 'type_name': '动漫'},
                {'type_id': '6', 'type_name': '短剧'},

            ]
        }

        return result

    def homeVideoContent(self):
        pass

    def categoryContent(self, cid, pg, filter, ext):
        result = {}
        videos = []
        if '地区' in ext.keys():
            if ext['地区'] == '全部':
                DqType = ''
            else:
                DqType = '&region=' + ext['地区']
        else:
            DqType = ''
        if '年代' in ext.keys():
            if ext['年代'] == '全部':
                NfType = ''
            else:
                NfType = '&year=' + ext['年代']
        else:
            NfType = ''
        if '演员' in ext.keys():
            if ext['演员'] == '全部':
                YyType = ''
            else:
                YyType = '&actors=' + ext['演员']
        else:
            YyType = ''

        url = f"{xurl2}/fl?fl=cid={cid}pg={pg}{DqType}{NfType}{YyType}"
        detail = requests.get(url=url, headers=headerx)
        detail.encoding = "utf-8"
        videos = self.fl(detail.text)

        result = {'list': videos}
        result['page'] = pg
        result['pagecount'] = 9999
        result['limit'] = 90
        result['total'] = 999999
        return result

    def extract_middle_text(self, text, start_str, end_str):

        start_index = text.find(start_str)
        if start_index == -1:
            return ""
        end_index = text.find(end_str, start_index + len(start_str))
        if end_index == -1:
            return ""

        middle_text = text[start_index + len(start_str):end_index]
        return middle_text.replace("\\", "")

    def detailContent(self, ids):
        global pm
        did = ids[0]
        id = self.编码(did)
        detail = requests.get(url=xurl2 + '/xq?xq=' + id, headers=headerx)
        detail.encoding = "utf-8"
        result = {}
        videos = []
        js1 = json.loads(detail.text)

        if js1:
            pm = js1['name']
            pic = js1['pic']
            year = js1['year']
            area = js1['region']
            actor = js1['actors']
            director = js1['director']
            content = js1['description']
            playform = '第二院线'
            playurlx = self.编码(js1['url'])
            s = requests.get(f'{xurl2}/ids?ids={playurlx}').text + '#'
            s1 = s.split('#')
            playurls = ''
            replacements = {
                '[www.hmxz.org]': '',
                'Shuke.and.Beita.': '',
            }

            for i in range(len(s1) - 1):
                parts = s1[i].split('$')
                name = parts[0]
                for old, new in replacements.items():
                    name = name.replace(old, new)
                url = parts[-1]
                playurls += f'{name}${url}#'

            playurls = playurls[:-1]
            videos.append({
                "vod_id": did,
                "vod_name": pm,
                "vod_pic": pic,
                "type_name": '',
                "vod_year": year,
                "vod_area": area,
                "vod_remarks": "",
                "vod_actor": actor,
                "vod_director": director,
                "vod_content": content,
                "vod_play_from": playform,
                "vod_play_url": playurls
            })

            result['list'] = videos

            return result

    def playerContent(self, flag, id, vipFlags):
        result = {}
        headerxs = {
            'User-Agent': 'Filmly/2.0.1.0506-255'
        }
        subtitle_url = ''
        if 'zzzmmm' in id:
            id, subtitle_url = id.split('zzzmmm')
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_url = executor.submit(self.get_play_url, id)
            future_subtitle = executor.submit(self.get_subtitle_url, subtitle_url)
            url = future_url.result()
            subtitle_url = future_subtitle.result()
        result["parse"] = 0
        result["playUrl"] = ''
        result["url"] = url
        result["header"] = headerxs
        threading.Timer(0.2, self.afterResult, args=(subtitle_url,)).start()
        return result

    def get_play_url(self, id):
        if 'deyx.txt' in id:
            return id
        else:
            id = self.编码(id)
            url = requests.get(f'{xurl2}/play?play={id}').text
            return url

    def get_subtitle_url(self, subtitle_url):
        if subtitle_url != '':
            id = self.编码(subtitle_url)
            try:
                zm = "/storage/emulated/0/TV/zm"
                url = requests.get(f'{xurl2}/play?play={id}').text
                filename_encoded = url.split('/')[-1].split('?')[0]
                file_extension = urllib.parse.unquote(filename_encoded)
                headerxs = {
                    'User-Agent': 'Filmly/2.0.1.0506-255'
                }
                response = requests.get(url, headers=headerxs)
                response.raise_for_status()
                if os.path.exists(zm):
                    try:
                        shutil.rmtree(zm)
                    except OSError as e:
                        return None
                os.makedirs(zm)
                subtitle_filename = f"中文字幕.{file_extension}"
                subtitle_url = os.path.join(zm, subtitle_filename)
                with open(subtitle_url, 'wb') as f:
                    f.write(response.content)
                return subtitle_url
            except requests.exceptions.RequestException as e:
                return None
            except Exception as e:
                return None

            return subtitle_url
        else:
            return ''

    def afterResult(self, subtitle_url):
        subtitle_url = self.url_encode_chinese_path(subtitle_url)

        requests.get(f'http://127.0.0.1:9978/action?do=refresh&type=subtitle&path={subtitle_url}')

    def url_encode_chinese_path(self, url):
        parts = url.split('?')
        base_url = parts[0]
        query_string = '?' + parts[1] if len(parts) > 1 else ''

        path_parts = base_url.split('/')
        encoded_path_parts = [quote(part) if i > 3 else part for i, part in
                              enumerate(path_parts)]

        encoded_url = '/'.join(encoded_path_parts) + query_string
        return encoded_url

    def searchContentPage(self, key, quick, page):
        result = {}
        detail = requests.get(xurl2 + '/wd?wd=' + key + '&page=' + page, headers=headerx)
        detail.encoding = "utf-8"
        videos = self.fl(detail.text)
        result['list'] = videos
        result['page'] = page
        result['pagecount'] = 9999
        result['limit'] = 90
        result['total'] = 999999
        return result

    def searchContent(self, key, quick):
        return self.searchContentPage(key, quick, '1')

    def localProxy(self, params):
        if params['type'] == "m3u8":
            return self.proxyM3u8(params)
        elif params['type'] == "media":
            return self.proxyMedia(params)
        elif params['type'] == "ts":
            return self.proxyTs(params)
        return None

    def 编码(self, input_string, encoding="utf-8"):
        try:
            input_bytes = input_string.encode(encoding)
            encoded_bytes = base64.b64encode(input_bytes)
            encoded_string = encoded_bytes.decode(encoding)
            return encoded_string
        except Exception as e:
            print(f"错误: {e}")
            return None
