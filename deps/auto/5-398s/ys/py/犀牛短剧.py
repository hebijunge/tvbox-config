import requests
from bs4 import BeautifulSoup
import re
from base.spider import Spider
import sys
import json
import base64
import urllib.parse

sys.path.append('..')

xurl = "https://by24h.com"
headerx = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36'
}

def getList(html):
    videos = []    
    源码 = BeautifulSoup(html, "lxml")
    二次截取 = 源码.find_all('ul', class_="stui-vodlist")
    for 数组 in 二次截取:
        数组 = 数组.find_all('li')
        for 影片 in 数组:
            vod = {}
            vod["vod_name"] = 影片.find('a')['title']
            vod["vod_id"] = 影片.find('a')['href']
            vod["vod_pic"] = 影片.find('mip-img')['src']
            if 'http' not in vod["vod_pic"]:
                vod["vod_pic"] = xurl + vod["vod_pic"]
            vod["vod_remarks"] = 影片.find('span', class_="pic-text").text.strip()            
            videos.append(vod)
    return videos

class Spider(Spider):
    global xurl
    global headerx

    def getName(self):
        return "首页"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def localProxy(self, params):
        pass

    def homeContent(self, filter):
        result = {}
        result = {"class": [
        {"type_id": "1","type_name": "重生"},
        {"type_id": "2","type_name": "穿越"},
        {"type_id": "3","type_name": "爽剧"},
        {"type_id": "4","type_name": "言情"},
        {"type_id": "5","type_name": "都市"},
        {"type_id": "6","type_name": "古装"},
        {"type_id": "7","type_name": "悬疑"},
        {"type_id": "8","type_name": "剧情"}]}
        return result

    def homeVideoContent(self):
        resp = requests.get(url=xurl, headers=headerx).text
        result = {'list': getList(resp)}
        return result

    def categoryContent(self, cid, pg, filter, ext):
        result = {}
        url = f'{xurl}/dj/{cid}-{pg}.html'
        resp = requests.get(url=url, headers=headerx).text
        result = {'list': getList(resp)}
        result['page'] = pg
        result['pagecount'] = 99
        result['limit'] = 90
        result['total'] = 99
        return result

    def detailContent(self, ids):    
        did = ids[0]
        result = {}
        videos = []
        if 'http' not in did:
            did = xurl + did
        源码 = BeautifulSoup(requests.get(url=did, headers=headerx).text, "lxml")
        vod = {}
        vod["vod_id"] = did
        vod["vod_name"] = 源码.select_one('h3').get_text()
        vod["type_name"] = (getattr(源码.find('span', class_='text-muted', string='类型：'), 'next_sibling', '') or '').strip()
        vod["vod_pic"] = 源码.select_one('mip-img').get('src', '')
        vod["vod_year"] = (getattr(源码.find('span', class_='text-muted', string='年份：'), 'next_sibling', '') or '').strip()
        vod["vod_area"] = (getattr(源码.find('span', class_='text-muted', string='地区：'), 'next_sibling', '') or '').strip()
        vod["vod_director"] = (a := 源码.select_one('span:-soup-contains("导演") + a')) and a.get_text(strip=True) or ''
        vod["vod_actor"] = (a := 源码.select_one('span:-soup-contains("主演") + a')) and a.get_text(strip=True) or ''
        vod["vod_content"] =(getattr(源码.find('span', class_='text-muted', string='简介：'), 'next_sibling', '') or '').strip()
        ktabs = []
        线路数组 = 源码.select('.stui-tabs ul:not(.stui-content__playlist) > li')
        for XL in 线路数组:
            线路标题 = XL.get_text()
            ktabs.append(线路标题)
        vod["vod_play_from"] = '$$$'.join(ktabs)
        klists = []
        播放数组 = 源码.select('.stui-content__playlist')
        for BF in 播放数组:
            播放列表 = BF.select('a')
            klist = []
            for LB in 播放列表:
                播放标题 = LB.get_text()
                播放链接 = LB.get('href', '')
                剧集 = f'{播放标题}${播放链接}'
                klist.append(剧集)
            klists.append('#'.join(klist))
        vod["vod_play_url"] = '$$$'.join(klists)
        result = {'list': [vod]}
        return result

    def playerContent(self, flag, id, vipFlags):
        result = {}       
        try:
            源码 = BeautifulSoup(requests.get(url=xurl+id, headers=headerx).text, "lxml")
            url = re.search('\?url=(.*?)"', str(源码)).group(1)
            if 'm3u8' in url:
                result["parse"] = 0
                result["url"] = url
            else:
                result["parse"] = 1
                result["url"] = xurl + id  
        except (AttributeError, Exception):
            result["parse"] = 1
            result["url"] = xurl + id
        result["header"] = headerx
        return result

    def searchContent(self, key, quick, page=1):
        result = {}
        url = f'{xurl}/search.php?page={page}&searchword={key}&searchtype='  
        resp = requests.get(url=url, headers=headerx).text
        result = {'list': getList(resp)}
        result['page'] = page
        result['pagecount'] = 60
        result['limit'] = 30
        result['total'] = 999999
        return result

    def searchContentPage(self, key, quick, page):
        return self.searchContent(key, quick, page)