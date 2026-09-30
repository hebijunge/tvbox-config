# coding = utf-8
# !/usr/bin/python

"""

作者 蒋勇 🚓 内容均从互联网收集而来 仅供交流学习使用 版权归原创者所有 如侵犯了您的权益 请通知作者 将及时删除侵权内容2026.6.17
                    ====================JiangYong===================

"""

from Crypto.Util.Padding import unpad
from urllib.parse import unquote
from Crypto.Cipher import ARC4
from urllib.parse import quote
from base.spider import Spider
from Crypto.Cipher import AES
from bs4 import BeautifulSoup
from base64 import b64decode
import urllib.request
import urllib.parse
import binascii
import requests
import base64
import json
import time
import sys
import re
import os

sys.path.append('..')

xurl = "https://www.985djw.com"

headerx = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36',
      'Referer':'https://www.985djw.com/vodshow/douyinduanju-----------2025/'   }

pm = ''

class Spider(Spider):
    global xurl
    global headerx
    global headers

    def getName(self):
        return "蒋勇短剧"

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
        result = {"class": [{"type_id": "douyinduanju", "type_name": "抖音短剧"},
                            {"type_id": "hanju", "type_name": "韩剧"},
                            {"type_id": "dianshiju", "type_name": "电视剧"},
                            {"type_id": "dianying", "type_name": "热门电影"},
                            {"type_id": "zongyijiemu", "type_name": "综艺节目"},
                            {"type_id": "dongma", "type_name": "动漫"},
                            {"type_id": "tiyusaishi", "type_name": "体育赛事"}],

                  "list": [],
                  "filters": {"douyinduanju": [{"key": "年代",
                                     "name": "年代",
                                     "value": [{"n": "全部", "v": ""},
                                               {"n": "2025", "v": "2025"},
                                               {"n": "2024", "v": "2024"},
                                               {"n": "2023", "v": "2023"},
                                               {"n": "2022", "v": "2022"},
                                               {"n": "2021", "v": "2021"},
                                               {"n": "2020", "v": "2020"},
                                               {"n": "2019", "v": "2019"},
                                               {"n": "2018", "v": "2018"}]}],
                              "hanju": [{"key": "年代",
                                     "name": "年代",
                                     "value": [{"n": "全部", "v": ""},
                                               {"n": "2025", "v": "2025"},
                                               {"n": "2024", "v": "2024"},
                                               {"n": "2023", "v": "2023"},
                                               {"n": "2022", "v": "2022"},
                                               {"n": "2021", "v": "2021"},
                                               {"n": "2020", "v": "2020"},
                                               {"n": "2019", "v": "2019"},
                                               {"n": "2018", "v": "2018"}]}],
                              "dianshiju": [{"key": "年代",
                                     "name": "年代",
                                     "value": [{"n": "全部", "v": ""},
                                               {"n": "2025", "v": "2025"},
                                               {"n": "2024", "v": "2024"},
                                               {"n": "2023", "v": "2023"},
                                               {"n": "2022", "v": "2022"},
                                               {"n": "2021", "v": "2021"},
                                               {"n": "2020", "v": "2020"},
                                               {"n": "2019", "v": "2019"},
                                               {"n": "2018", "v": "2018"}]}],
                              "dianying": [{"key": "年代",
                                     "name": "年代",
                                     "value": [{"n": "全部", "v": ""},
                                               {"n": "2025", "v": "2025"},
                                               {"n": "2024", "v": "2024"},
                                               {"n": "2023", "v": "2023"},
                                               {"n": "2022", "v": "2022"},
                                               {"n": "2021", "v": "2021"},
                                               {"n": "2020", "v": "2020"},
                                               {"n": "2019", "v": "2019"},
                                               {"n": "2018", "v": "2018"}]}],
                              "zongyijiemu": [{"key": "年代",
                                     "name": "年代",
                                     "value": [{"n": "全部", "v": ""},
                                               {"n": "2025", "v": "2025"},
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

        try:
            detail = requests.get(url=xurl+'/nl/douyinduanju/', headers=headerx)
            detail.encoding = "utf-8"
            res = detail.text

            doc = BeautifulSoup(res, "lxml")

            soups = doc.find_all('ul', class_="stui-vodlist clearfix")

            for soup in soups:
                vods = soup.find_all('li')

                for vod in vods:
                    names = vod.find('a', class_="stui-vodlist__thumb lazyload")
                   # name = names.text.strip()
                    name = names['title']

                    id = names['href'][:-1]

                   # pics = vod.find('a', class_="fed-list-pics")
                    pic = names['data-original']

                    if 'http' not in pic:
                        pic = xurl + pic

                    remarks = vod.find('span', class_="pic-text text-right")
                    remark = remarks.text.strip()

                    video = {
                        "vod_id": id,
                        "vod_name": name,
                        "vod_pic": pic,
                        "vod_remarks": '▶️' + remark
                             }
                    videos.append(video)

            result = {'list': videos}
            return result
        except:
            pass

    def categoryContent(self, cid, pg, filter, ext):
        result = {}
        videos = []

        if pg:
            page = int(pg)
        else:
            page = 1
        if  '年代'  in ext:
          if '年代' in ext.keys():
            NdType = ext['年代']
        else:
            NdType = ''

        if page == 1:
            url = f'{xurl}/vodshow/{cid}--------{str(page)}---'

        else:
            url = f'{xurl}/vodshow/{cid}--------{str(page)}---{NdType}/'

        try:
            detail = requests.get(url=url, headers=headerx)
            #print(detail.text)
            detail.encoding = "utf-8"
            res = detail.text
            doc = BeautifulSoup(res, "lxml")
            soups = doc.find_all('ul', class_="stui-vodlist clearfix")

            for soup in soups:
                vods = soup.find_all('li')

                for vod in vods:
                  names = vod.find('a', class_="stui-vodlist__thumb lazyload")
                # name = names.text.strip()
                  name = names['title']

                  id = names['href'][:-1]

                # pics = vod.find('a', class_="fed-list-pics")
                  pic = names['data-original']

                  if 'http' not in pic:
                     pic = xurl + pic

                  remarks = vod.find('span', class_="pic-text text-right")
                  remark = remarks.text.strip()

                  video = {
                    "vod_id": id,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": '▶️' + remark
                  }
                  videos.append(video)



        except:
          pass

        result = {'list': videos}
        result['page'] = pg
        result['pagecount'] = 9999
        result['limit'] = 90
        result['total'] = 999999
        return result

    def detailContent(self, ids):
        global pm
        did = ids[0]
        result = {}
        videos = []
        play_urls=""

        if 'http' not in did:
            di=str(did)
            did = xurl + str.replace(di,"/m/","/play/")+"-1-1"

        res = requests.get(url=did, headers=headerx)
        res.encoding = "utf-8"
        res = res.text
        #print(did,res)

        # doc = BeautifulSoup(res, "lxml")
        #soups = doc.find_all('div', class_="stui-player__video")
        #soup = soups.__str__()
        #bofang = s.extract_middle_text(soup, 'https', "index.m3u8", 0)
        #print(soup) 可以取<div
        try:
           doc2 = BeautifulSoup(res, "lxml")
           soups2 = doc2.find_all('ul', class_="stui-content__playlist clearfix")
           for sov in soups2:
             ress=sov.find_all('li')
             for res in ress:
                names = res.find_all('a')
                name=names[0]['href']
                #print(name)
                play_urls = play_urls + name[-4:] + '$' + name + '#'
             play_urls = play_urls[:-1]


        except:
          pass

        videos.append({
            "vod_id": did,
            "vod_remarks": "remarks",
            "vod_year": "year",
            "vod_content": play_urls,
            "vod_play_from": "xianlu",
            "vod_play_url": play_urls
        })

        result['list'] = videos


        return result

    def playerContent(self, flag, id, vipFlags):
        if "$" in id:
            id= id.split("$")[1]
        did = xurl + id
        #print(did)


        res = requests.get(url=did, headers=headerx)
        res.encoding = "utf-8"
        res = res.text
        # print(did,res)

        doc = BeautifulSoup(res, "lxml")
        soups = doc.find_all('div', class_="stui-player__video")
        soup = soups.__str__()
        bofang ='https'+ s.extract_middle_text(soup, 'https', "index.m3u8", 0)+"index.m3u8"


        return {"parse": 0, "url": bofang}



    def searchContentPage(self, key, quick, page):
        result = {}
        videos = []

        if not page:
            page = '1'
        if page == '1':
            url = f'{xurl}/vodsearch/-------------/?wd={key}&submit='

        else:
            url = f'{xurl}/vodsearch/{key}----------{str(page)}---/&submit ='

        detail = requests.get(url=url, headers=headerx)
        detail.encoding = "utf-8"
        res = detail.text
        doc = BeautifulSoup(res, "lxml")

        soups = doc.find_all('ul', class_="stui-vodlist clearfix")
        for soup in soups:
            vods = soup.find_all('li')

            for vod in vods:



              ids = vod.find('a', class_="stui-vodlist__thumb lazyload")
              id = ids['href'][:-1]
              name =  ids['title']

              pic = ids['data-original']

              if 'http' not in pic:
                pic = xurl + pic

              remarks = vod.find('span', class_="pic-text text-right")
              remark = remarks.text.strip()

              video = {
                "vod_id": id,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": '▶️' + remark
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




s=Spider()
#print(s.categoryContent('douyinduanju',"","",""))

#print(s.searchContent("江",1))
print(s.detailContent(["/m/huangchengguian",""]))
print(s.playerContent("", "1-1/$/play/huangchengguian-1-1/",0))
