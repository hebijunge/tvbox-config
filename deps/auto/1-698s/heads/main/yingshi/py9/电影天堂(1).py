# coding=utf-8
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
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse
import datetime
import binascii
import requests
import random
import base64
import html
import json
import time
import sys
import re
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.append('..')

xurl = "https://web.tt4747.com"
headerx1 = 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36'
headerx = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36'
          }
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

    def homeContent(self, filter):
        result = {}
        leixing = {"key": "类型","name": "类型",
                   "value": [{"n": "全部", "v": ""},{"n": "Netflix", "v": "Netflix"},{"n": "剧情", "v": "剧情"},{"n": "喜剧", "v": "喜剧"},{"n": "动作", "v": "动作"},
                             {"n": "爱情", "v": "爱情"},{"n": "恐怖", "v": "恐怖"},{"n": "惊悚", "v": "惊悚"},{"n": "犯罪", "v": "犯罪"},{"n": "科幻", "v": "科幻"},
                             {"n": "悬疑", "v": "悬疑"},{"n": "奇幻", "v": "奇幻"},{"n": "冒险", "v": "冒险"},{"n": "战争", "v": "战争"},{"n": "历史", "v": "历史"},
                             {"n": "古装", "v": "古装"},{"n": "家庭", "v": "家庭"},{"n": "传记", "v": "传记"},{"n": "武侠", "v": "武侠"},{"n": "同性", "v": "同性"},
                             {"n": "歌舞", "v": "歌舞"},{"n": "短片", "v": "短片"},{"n": "动画", "v": "动画"},{"n": "儿童", "v": "儿童"},{"n": "职场", "v": "职场"}]}
        zy_leixing = {"key": "类型","name": "类型",
                      "value": [{"n": "全部", "v": ""},{"n": "纪录", "v": "纪录"},{"n": "真人秀", "v": "真人秀"},{"n": "记录", "v": "记录"},{"n": "脱口秀", "v": "脱口秀"},
                                {"n": "剧情", "v": "剧情"},{"n": "历史", "v": "历史"},{"n": "喜剧", "v": "喜剧"},{"n": "传记", "v": "传记"},{"n": "相声", "v": "相声"},
                                {"n": "节目", "v": "节目"},{"n": "歌舞", "v": "歌舞"},{"n": "冒险", "v": "冒险"},{"n": "运动", "v": "运动"},{"n": "Season", "v": "Season"},
                                {"n": "犯罪", "v": "犯罪"},{"n": "短片", "v": "短片"},{"n": "搞笑", "v": "搞笑"},{"n": "晚会", "v": "晚会"}]}
        dm_leixing = {"key": "类型","name": "类型",
                      "value": [{"n": "全部", "v": ""},{"n": "Netflix", "v": "Netflix"},{"n": "动态漫画", "v": "动态漫画"},{"n": "剧情", "v": "剧情"},{"n": "动画", "v": "动画"},
                                {"n": "喜剧", "v": "喜剧"},{"n": "冒险", "v": "冒险"},{"n": "动作", "v": "动作"},{"n": "奇幻", "v": "奇幻"},{"n": "科幻", "v": "科幻"},
                                {"n": "儿童", "v": "儿童"},{"n": "搞笑", "v": "搞笑"},{"n": "爱情", "v": "爱情"},{"n": "家庭", "v": "家庭"},{"n": "短片", "v": "短片"},
                                {"n": "热血", "v": "热血"},{"n": "益智", "v": "益智"},{"n": "悬疑", "v": "悬疑"},{"n": "经典", "v": "经典"},{"n": "校园", "v": "校园"},
                                {"n": "Anime", "v": "Anime"},{"n": "运动", "v": "运动"},{"n": "亲子", "v": "亲子"},{"n": "青春", "v": "青春"},{"n": "恋爱", "v": "恋爱"},
                                {"n": "武侠", "v": "武侠"},{"n": "惊悚", "v": "惊悚"}]}
        diqu = {"key": "地区","name": "地区",
                "value": [{"n": "全部", "v": ""},{"n": "大陆", "v": "大陆"},{"n": "香港", "v": "香港"},{"n": "台湾", "v": "台湾"},{"n": "美国", "v": "美国"},
                          {"n": "日本", "v": "日本"},{"n": "韩国", "v": "韩国"},{"n": "英国", "v": "英国"},{"n": "法国", "v": "法国"},{"n": "德国", "v": "德国"},
                          {"n": "印度", "v": "印度"},{"n": "泰国", "v": "泰国"},{"n": "丹麦", "v": "丹麦"},{"n": "瑞典", "v": "瑞典"},{"n": "巴西", "v": "巴西"},
                          {"n": "加拿大", "v": "加拿大"},{"n": "俄罗斯", "v": "俄罗斯"},{"n": "意大利", "v": "意大利"},{"n": "比利时", "v": "比利时"},{"n": "爱尔兰", "v": "爱尔兰"},
                          {"n": "西班牙", "v": "西班牙"},{"n": "澳大利亚", "v": "澳大利亚"},{"n": "其他", "v": "其他"}]}
        yuyuan = {"key": "语言","name": "语言",
                  "value": [{"n": "全部", "v": ""},{"n": "国语", "v": "国语"},{"n": "粤语", "v": "粤语"},{"n": "英语", "v": "英语"},{"n": "日语", "v": "日语"},
                            {"n": "韩语", "v": "韩语"},{"n": "法语", "v": "法语"},{"n": "其他", "v": "其他"}]}
        nianfen = {"key": "年份","name": "年份",
                   "value": [{"n": "全部", "v": ""},{"n": "2025", "v": "2025"},{"n": "2024", "v": "2024"},{"n": "2023", "v": "2023"},{"n": "2022", "v": "2022"},
                             {"n": "2021", "v": "2021"},{"n": "2020", "v": "2020"},{"n": "2019", "v": "2019"},{"n": "2018", "v": "2018"},{"n": "2017", "v": "2017"},
                             {"n": "2016", "v": "2016"},{"n": "2015", "v": "2015"},{"n": "2014", "v": "2014"},{"n": "2013", "v": "2013"},{"n": "2012", "v": "2012"},
                             {"n": "2011", "v": "2011"},{"n": "2010", "v": "2010"}]}
        paixu = {"key": "排序","name": "排序",
                 "value": [{"n": "全部", "v": ""},{"n": "按时间", "v": "time"},{"n": "按人气", "v": "hits"},{"n": "按评分", "v": "score"}]}
        result = {"class": [{"type_id": "1", "type_name": "电影"},
                            {"type_id": "2", "type_name": "电视剧"},
                            {"type_id": "3", "type_name": "综艺"},
                            {"type_id": "4", "type_name": "动漫"},
                            {"type_id": "5", "type_name": "短剧"},
                            {"type_id": "6", "type_name": "伦理"}],

                  "list": [],
                  "filters": {"1": [leixing,diqu,yuyuan,nianfen,paixu],
                              "2": [leixing,diqu,yuyuan,nianfen,paixu],
                              "3": [zy_leixing,diqu,yuyuan,nianfen,paixu],
                              "4": [dm_leixing,diqu,yuyuan,nianfen,paixu],
                              "5": [paixu],
                              "6": [paixu]}}

        return result
    def homeVideoContent(self):
        pass

    def fetch_image_response_info(self, url):
        try:
            response = requests.get(url, timeout=10, allow_redirects=True)
            return response.text
        except Exception as e:
            return ''

    # def fetch_image_response_info(self, url):
    #     try:
    #         response = requests.get(url, timeout=10, allow_redirects=True)
    #         content_type = response.headers.get('Content-Type', '')
    #
    #         if 'text' in content_type or 'json' in content_type:
    #             return {
    #                 'status': 'text',
    #                 'content': response.text
    #             }
    #         elif 'image' in content_type:
    #             # img_base64 = base64.b64encode(response.content).decode('utf-8')
    #             # print(img_base64)
    #             return {
    #                 'status': 'image',
    #                 'content': '',
    #                 'size': len(response.content)
    #             }
    #         else:
    #             return {
    #                 'status': 'unknown',
    #                 'content': str(response.content)
    #             }
    #
    #     except Exception as e:
    #         return {
    #             'status': 'error',
    #             'error': str(e)
    #         }

    def get_video_covers(self, videos, max_workers=8):
        vod_ids = []
        for video in videos:
            vod_id = video['vod_id']
            if '/voddetail/' in vod_id:
                vod_id = vod_id.split('/voddetail/')[1].strip('/')
            vod_ids.append(vod_id)

        cover_map = {}
        lock = threading.Lock()
        success_count = 0
        fail_count = 0

        def fetch_cover(vid):
            nonlocal success_count, fail_count
            url = f"https://web.tt4747.com/voddetail/{vid}/"
            time.sleep(random.uniform(0.3, 1.0))
            try:
                headers = {
                    'User-Agent': random.choice([
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0'
                    ]),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Connection': 'keep-alive',
                    'Referer': 'https://web.tt4747.com/'
                }

                response = requests.get(url, headers=headers)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    pic_div = soup.find('div', class_='detail-pic')
                    if pic_div:
                        img = pic_div.find('img')
                        if img:
                            pic_urls = img.get('data-original')
                            pic_urls = 'https://pics.xhsdns.cn/vod/252/252122.jpg'
                            pic_info = self.fetch_image_response_info(pic_urls)
                            pic_url = f'ddata:image/png;base64,{pic_info}'
                            if pic_url:
                                with lock:
                                    success_count += 1
                                    cover_map[vid] = pic_url
                                return vid, pic_url
                    pattern = r'data-original="([^"]+\.jpg)"'
                    match = re.search(pattern, response.text)
                    if match:
                        pic_url = match.group(1)
                        with lock:
                            success_count += 1
                            cover_map[vid] = pic_url
                        return vid, pic_url

                    with lock:
                        fail_count += 1
                    return vid, None
                else:
                    with lock:
                        fail_count += 1
                    return vid, None
            except Exception as e:
                with lock:
                    fail_count += 1
                return vid, None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_cover, vid): vid for vid in vod_ids}
            for future in as_completed(futures):
                try:
                    future.result(timeout=30)
                except Exception as e:
                    pass

        for video in videos:
            vod_id = video['vod_id']
            if '/voddetail/' in vod_id:
                vid = vod_id.split('/voddetail/')[1].strip('/')
            else:
                vid = vod_id
            video['vod_pic'] = cover_map.get(vid, '')
        return videos

    def categoryContent(self, cid, pg, filter, ext):
        result = {}
        videos = []
        if pg:
            page = int(pg)
        else:
            page = 1
        LX = ext.get('类型', '')
        DQ = ext.get('地区', '')
        YY = ext.get('语言', '')
        NF = ext.get('年份', '')
        PX = ext.get('排序', '')
        if cid == '5' or cid == '6':
            url = f'{xurl}/rss/index.xml?mid=1&tid={cid}&page={str(page)}&limit=24&class=&year=&area=&lang=&by={PX}'
        else:
            url = f'{xurl}/rss/index.xml?mid=1&tid={cid}&page={str(page)}&limit=24&class={LX}&year={NF}&area={DQ}&lang={YY}&by={PX}'
        detail = requests.get(url=url, headers=headerx)
        detail.encoding = "utf-8"
        res = detail.text
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(res)
            items = root.findall('.//item')
            for item in items:
                title_elem = item.find('title')
                if title_elem is not None and title_elem.text:
                    title_text = title_elem.text
                    if ' ' in title_text:
                        first_space = title_text.find(' ')
                        last_space = title_text.rfind(' ')
                        if first_space == last_space:
                            vod_name = title_text[:first_space]
                            vod_remarks = title_text[last_space + 1:]
                        else:
                            vod_name = title_text[:first_space]
                            vod_remarks = title_text[last_space + 1:]
                    else:
                        vod_name = title_text
                        vod_remarks = ""
                else:
                    vod_name = ""
                    vod_remarks = ""
                link_elem = item.find('link')
                vod_ids = link_elem.text if link_elem is not None else ""
                vod_id = vod_ids.replace('http://web.dy1996.com/', 'https://web.tt4747.com/')
                pubdate_elem = item.find('pubDate')
                if pubdate_elem is not None and pubdate_elem.text:
                    pubdate_text = pubdate_elem.text
                    if ' ' in pubdate_text:
                        vod_year = pubdate_text.split(' ')[0]
                    else:
                        vod_year = pubdate_text
                else:
                    vod_year = ""

                video = {
                    "vod_id": vod_id,
                    "vod_name": vod_name,
                    "vod_year": vod_year,
                    "vod_pic": '',
                    "vod_remarks": vod_remarks
                }
                videos.append(video)

        except ET.ParseError as e:
            pass
        except Exception as e:
            pass
        if videos:
            try:
                videos = self.get_video_covers(videos, max_workers=8)
            except Exception as e:
                ''

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
        xianlu = '咖啡直播'
        if did.startswith('@@@'):
            fenge = did.split("@@@")
            url = f"{fenge[1]}"
            detail = requests.get(url=url, headers=headerx)
            detail.encoding = "utf-8"
            res = detail.text
            data = json.loads(res)['data']['replays']
            ids = []
            for item in data:
                bf_name = item['title']
                bf_url = item['video_url']
                ids.append(f"{bf_name}${bf_url}")
            bofang = '#'.join(ids)
        else:
            bofang = did
        videos.append({
            "vod_play_from": xianlu,
            "vod_play_url": bofang
                     })
        result['list'] = videos
        return result

    def playerContent(self, flag, id, vipFlags):
        fenge = id.split("http")
        id = f"http{fenge[1]}"
        url = id

        result = {}
        result["parse"] = 0
        result["playUrl"] = ''
        result["url"] = url
        result["header"] = headerx
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


if __name__ == '__main__':
    spider_instance = Spider()

    # res=spider_instance.homeContent('filter')  #  分类🚨

    # res = spider_instance.homeVideoContent()  # 首页🚨

    res=spider_instance.categoryContent('2', 1, 'filter', {})  #  分页🚨

    # res = spider_instance.detailContent(['@@@https://kafeizhibo.cc/api/v1/match/21895/recordings'])  #  详情页🚨

    # res = spider_instance.playerContent('1', '直播21$01https://live.666666.zip/live/4528263.m3u8', 'vipFlags')  #  播放页🚨

    # res = spider_instance.searchContentPage('我', 'quick', '1')  # 搜索页🚨

    print(res)