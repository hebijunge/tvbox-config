# coding = utf-8
# !/usr/bin/python


from Crypto.Util.Padding import unpad
from Crypto.Util.Padding import pad
from urllib.parse import unquote
from Crypto.Cipher import ARC4
from urllib.parse import quote
from base.spider import Spider
from Crypto.Cipher import AES
from datetime import datetime
from bs4 import BeautifulSoup
from base64 import b64decode
import urllib.request
import urllib.parse
import datetime
import binascii
import requests
import base64
import json
import time
import sys
import re
import os

sys.path.append('..')

xurl = "https://www.wasu.cn"

xurl1 = "https://mcspapp.5g.wasu.tv"

xurl2 = "https://ups.5g.wasu.tv"

headerx = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36'
          }

class Spider(Spider):
    global xurl
    global xurl1
    global xurl2
    global headerx

    def getName(self):
        return "首页"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def extract_middle_text(self, text, start_str, end_str, pl, start_index1: str = '', end_index2: str = ''):
        if pl == 3:
            plx = []
            while True:
                start_index = text.find(start_str)
                if start_index == -1:
                    break
                end_index = text.find(end_str, start_index + len(start_str))
                if end_index == -1:
                    break
                middle_text = text[start_index + len(start_str):end_index]
                plx.append(middle_text)
                text = text.replace(start_str + middle_text + end_str, '')
            if len(plx) > 0:
                purl = ''
                for i in range(len(plx)):
                    matches = re.findall(start_index1, plx[i])
                    output = ""
                    for match in matches:
                        match3 = re.search(r'(?:^|[^0-9])(\d+)(?:[^0-9]|$)', match[1])
                        if match3:
                            number = match3.group(1)
                        else:
                            number = 0
                        if 'http' not in match[0]:
                            output += f"#{match[1]}${number}{xurl}{match[0]}"
                        else:
                            output += f"#{match[1]}${number}{match[0]}"
                    output = output[1:]
                    purl = purl + output + "$$$"
                purl = purl[:-3]
                return purl
            else:
                return ""
        else:
            start_index = text.find(start_str)
            if start_index == -1:
                return ""
            end_index = text.find(end_str, start_index + len(start_str))
            if end_index == -1:
                return ""

        if pl == 0:
            middle_text = text[start_index + len(start_str):end_index]
            return middle_text.replace("\\", "")

        if pl == 1:
            middle_text = text[start_index + len(start_str):end_index]
            matches = re.findall(start_index1, middle_text)
            if matches:
                jg = ' '.join(matches)
                return jg

        if pl == 2:
            middle_text = text[start_index + len(start_str):end_index]
            matches = re.findall(start_index1, middle_text)
            if matches:
                new_list = [f'{item}' for item in matches]
                jg = '$$$'.join(new_list)
                return jg

    def homeContent(self, filter):
        result = {}
        result = {"class": [{"type_id": "961", "type_name": "电影"},
                            {"type_id": "962", "type_name": "剧集"},
                            {"type_id": "963", "type_name": "少儿"},
                            {"type_id": "965", "type_name": "栏目"},
                            {"type_id": "966", "type_name": "新闻"}],
                  "list": [],
                  "filters": {"961": [{"key": "年代",
                                     "name": "年代",
                                     "value": [{"n": "全部", "v": ""},
                                               {"n": "2024", "v": "2024"},
                                               {"n": "2023", "v": "2023"},
                                               {"n": "2022", "v": "2022"},
                                               {"n": "2021", "v": "2021"},
                                               {"n": "2020", "v": "2020"},
                                               {"n": "2019", "v": "2019"},
                                               {"n": "2018", "v": "2018"}]}],
                              "962": [{"key": "年代",
                                     "name": "年代",
                                     "value": [{"n": "全部", "v": ""},
                                               {"n": "2024", "v": "2024"},
                                               {"n": "2023", "v": "2023"},
                                               {"n": "2022", "v": "2022"},
                                               {"n": "2021", "v": "2021"},
                                               {"n": "2020", "v": "2020"},
                                               {"n": "2019", "v": "2019"},
                                               {"n": "2018", "v": "2018"}]}],
                              "963": [{"key": "年代",
                                     "name": "年代",
                                     "value": [{"n": "全部", "v": ""},
                                               {"n": "2024", "v": "2024"},
                                               {"n": "2023", "v": "2023"},
                                               {"n": "2022", "v": "2022"},
                                               {"n": "2021", "v": "2021"},
                                               {"n": "2020", "v": "2020"},
                                               {"n": "2019", "v": "2019"},
                                               {"n": "2018", "v": "2018"}]}],
                              "965": [{"key": "年代",
                                     "name": "年代",
                                     "value": [{"n": "全部", "v": ""},
                                               {"n": "2024", "v": "2024"},
                                               {"n": "2023", "v": "2023"},
                                               {"n": "2022", "v": "2022"},
                                               {"n": "2021", "v": "2021"},
                                               {"n": "2020", "v": "2020"},
                                               {"n": "2019", "v": "2019"},
                                               {"n": "2018", "v": "2018"}]}]}}

        return result

    def homeVideoContent(self):
        videos = []

        url = f'{xurl1}/bvradio_app/hzhs/recommendServlet?functionName=getRecommond&modeId=1033&page=1&pageSize=10&siteId=1000101&platform=web'
        detail = requests.get(url=url, headers=headerx)
        detail.encoding = "utf-8"
        if detail.status_code == 200:
            data = detail.json()

            duoxuan = ['1', '3', '5', '7']

            for duo in duoxuan:

                js = data['data'][int(duo)]['childModels'][0]['manualList']

                for vod in js:

                    name = vod['title']

                    id = vod['id']

                    pic = vod['pPic']

                    remark = vod.get('episodeDesc', '推荐')

                    video = {
                        "vod_id": id,
                        "vod_name": name,
                        "vod_pic": pic,
                        "vod_remarks": remark
                            }
                    videos.append(video)

        result = {'list': videos}
        return result

    def categoryContent(self, cid, pg, filter, ext):
        result = {}
        videos = []

        if pg:
            page = int(pg)
        else:
            page = 1

        if '年代' in ext.keys():
            NdType = ext['年代']
        else:
            NdType = ''

        url = f'{xurl2}/rmp-user-suggest/1000101/hzhs/searchServlet?functionName=getNewsSearchedByCondition&nodeId={cid}&nodeTag=全部&yearTag={NdType}&countryTag=全部&orderType=0&pageSize=40&page={str(page)}'
        detail = requests.get(url=url, headers=headerx)
        detail.encoding = "utf-8"
        if detail.status_code == 200:
            data = detail.json()

            stup = data['data']

            for vod in stup:

                name = vod['title']

                nodeId = vod['nodeId']

                newsId = vod['newsId']

                id = str(nodeId) + "," + str(newsId)

                pic = vod['hPic']

                remark = "新闻," if vod['episodeDesc'] == "1" else vod['episodeDesc']

                video = {
                    "vod_id": id,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": remark
                        }
                videos.append(video)

        result = {'list': videos}
        result['page'] = pg
        result['pagecount'] = 9999
        result['limit'] = 90
        result['total'] = 999999
        return result

    def detailContent(self, ids):
        did = ids[0]
        result = {}
        videos = []
        xianlu = ''
        bofang = ''
        fenge = did.split(",")

        url = f'{xurl1}/bvradio_app/hzhs/newsServlet?siteId=1000101&functionName=getCurrentNews&nodeId={fenge[0]}&newsId={fenge[1]}&platform=web'
        detail = requests.get(url=url, headers=headerx)
        detail.encoding = "utf-8"
        if detail.status_code == 200:
            detail = detail.json()

        content = detail['data'].get('newsAbstract', '未知')

        actor = detail['data'].get('actor', '未知')

        director = detail['data'].get('director', '未知')

        pubTime = detail['data'].get('pubTime', '未知')

        episodeDesc = detail['data'].get('episodeDesc', '未知')

        remarks = detail['data'].get('tags', '未知') + " 更新时间 " + pubTime + " 状态 " + episodeDesc

        year = detail['data'].get('yearTag', '未知')

        area = detail['data'].get('countryTag', '未知')

        stup = detail['data']['vodList']

        for vod in stup:

            name = vod['title']

            id = f"{xurl}/teleplay-detail/{fenge[0]}/{fenge[1]}/" + str(vod['vodId'])

            bofang = bofang + name + '$' + id + '#'

        bofang = bofang[:-1]

        xianlu = "第二院线"

        videos.append({
            "vod_id": did,
            "vod_actor": actor,
            "vod_director": director,
            "vod_year": year,
            "vod_area": area,
            "vod_remarks": remarks,
            "vod_content": content,
            "vod_play_from": xianlu,
            "vod_play_url": bofang
                    })

        result['list'] = videos
        return result

    def playerContent(self, flag, id, vipFlags):

        id = "http://8.146.205.47/php/jx.php?url=" + id
        detail = requests.get(url=id, headers=headerx)
        detail.encoding = "utf-8"
        if detail.status_code == 200:
            detail = detail.text
            data = json.loads(detail)
            if data.get("url_1920"):
                url = data["url_1920"]
            else:
                url = data["url_720"]
        result = {}
        result["parse"] = 0
        result["playUrl"] = ''
        result["url"] = url
        result["header"] = headerx
        return result

    def searchContentPage(self, key, quick, page):
        result = {}
        videos = []

        url = f'{xurl2}/rmp-user-suggest/1000101/hzhs/searchServlet?functionName=getServiceAndNewsSearch&keyword={key}&pageSize=10&page={str(page)}'
        detail = requests.get(url=url, headers=headerx)
        detail.encoding = "utf-8"
        if detail.status_code == 200:
            data = detail.json()

            stup = data['data']['videoDataList']

            for vod in stup:
                name = vod['title']

                nodeId = vod['nodeId']

                newsId = vod['newsId']

                id = str(nodeId) + "," + str(newsId)

                pic = vod['hPic']

                remark = "新闻," if vod['episodeDesc'] == "1" else vod['episodeDesc']

                video = {
                    "vod_id": id,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": remark
                        }
                videos.append(video)

        result['list'] = videos
        result['page'] = page
        result['pagecount'] = 9999
        result['limit'] = 90
        result['total'] = 999999
        return result

    def searchContent(self, key, quick, pg="1"):
        return self.searchContentPage(key, quick, '1')

    def localProxy(self, params):
        if params['type'] == "m3u8":
            return self.proxyM3u8(params)
        elif params['type'] == "media":
            return self.proxyMedia(params)
        elif params['type'] == "ts":
            return self.proxyTs(params)
        return None





