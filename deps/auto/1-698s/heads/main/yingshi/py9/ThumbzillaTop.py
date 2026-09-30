# Thumbzilla T3 类型爬虫

# coding=utf-8
# !/usr/bin/python

import sys
sys.path.append('..')

from base.spider import BaseSpider
import requests
import re

TIMEOUT = 10

HOST = 'https://thumbzilla.top'


class Spider(BaseSpider):
    def getName(self):
        return "Thumbzilla"

    filterable = False
    searchable = True
    host = HOST
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": HOST + '/',
    }

    def init(self, extend=""):
        pass

    def _fetch_url(self, url):
        try:
            r = requests.get(url, headers=self.headers, timeout=TIMEOUT, verify=False)
            r.encoding = 'utf-8'
            return r.text
        except Exception:
            return ''

    def _parse_video_list(self, html):
        video_list = []
        pattern = r'<a href="(/video/([^"]+)\.html)"[^>]*title="([^"]+)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, html, re.DOTALL)
        for match in matches:
            href = match[0]
            vid = match[1]
            title = match[2]
            content = match[3]

            tn_match = re.search(r'data-tn="([^"]+)"', content)
            tn = tn_match.group(1) if tn_match else ''
            pic_url = HOST + "/pics/AA/" + tn[:2] + "/" + tn[2:] + ".jpg" if tn else ''

            duration = ''
            duration_match = re.search(r'<span[^>]*class="[^"]*duration[^"]*"[^>]*>([^<]+)</span>', content)
            if duration_match:
                duration = duration_match.group(1).strip()

            vod_pic = pic_url if pic_url else ''

            video_list.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_remarks': duration,
                'vod_pic': vod_pic,
            })
        return video_list

    def _parse_categories_list(self, html):
        folder_list = []
        pattern = r'<a\s+title="([^"]+)"\s+href="(/cat/([^"]+)/)"[^>]*>\s*<img[^>]*src="([^"]+)"'
        matches = re.findall(pattern, html, re.DOTALL)
        seen = set()
        for match in matches:
            title = match[0]
            href = match[1]
            slug = match[2]
            pic_url = match[3]

            if not title or len(title) > 100:
                continue

            if slug in seen:
                continue
            seen.add(slug)

            name_parts = title.split(':')
            name = name_parts[0].strip()
            vod_remarks = name_parts[1].strip() if len(name_parts) > 1 else ''

            if not pic_url.startswith('http'):
                pic_url = HOST + pic_url

            vod_pic = pic_url if pic_url else ''

            folder_list.append({
                'vod_id': href + '@',
                'vod_name': name,
                'vod_pic': vod_pic,
                'vod_tag': 'folder',
                'vod_remarks': vod_remarks,
            })
        return folder_list

    def homeContent(self, filter):
        result = {}
        class_names = '推荐&热门&分类'.split('&')
        class_ids = 'recommend&hottest&home'.split('&')
        classes = []
        for i in range(len(class_names)):
            classes.append({
                'type_name': class_names[i],
                'type_id': class_ids[i]
            })
        result['class'] = classes
        result['type'] = '视频'
        result['filters'] = {}

        return result

    def homeVideoContent(self, tid, pg, filter, extend):
        return self.categoryContent(tid, pg, filter, extend)

    def categoryContent(self, tid, pg, filter, extend):
        host = self.host

        if '@' in tid:
            tid = tid.replace('@', '')
            base_url = host + tid
            url = base_url if pg == 1 else base_url.rstrip('/') + "/page/" + str(pg)
            html = self._fetch_url(url)
            video_list = self._parse_video_list(html) if html else []
            return {'list': video_list, 'page': pg, 'pagecount': 999, 'limit': len(video_list), 'total': 1000}

        if tid == 'home':
            url = host + "/" 
            html = self._fetch_url(url)
            folder_list = self._parse_categories_list(html) if html else []
            return {'list': folder_list, 'page': pg, 'pagecount': 999, 'limit': len(folder_list), 'total': 1000}

        if tid == 'recommend':
            url = host + "/hottest/"
            html = self._fetch_url(url)
            video_list = self._parse_video_list(html) if html else []
            return {'list': video_list, 'page': pg, 'pagecount': 1, 'limit': len(video_list), 'total': len(video_list)}

        if tid == 'hottest':
            url = host + "/hottest/" if pg == 1 else host + "/hottest/page/" + str(pg)
        else:
            url = host + "/cat/" + tid + "/" if pg == 1 else host + "/cat/" + tid + "/page/" + str(pg)

        html = self._fetch_url(url)
        video_list = self._parse_video_list(html) if html else []

        return {'list': video_list, 'page': pg, 'pagecount': 999, 'limit': len(video_list), 'total': 1000}

    def detailContent(self, ids):
        host = self.host
        did = ids[0] if isinstance(ids, list) else ids
        url = host + "/video/" + did + ".html"

        html = self._fetch_url(url)
        if not html:
            return {'list': []}

        title = ''
        title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if title_match:
            title = title_match.group(1).strip()

        pic_url = ''
        poster_match = re.search(r'poster=[\'"]([^\'"]+)[\'"]', html)
        if not poster_match:
            poster_match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if poster_match:
            pic_url = poster_match.group(1)
            if not pic_url.startswith('http'):
                pic_url = host + pic_url
        vod_pic = pic_url if pic_url else ''

        play_url = []
        file_match = re.search(r'"file"\s*:\s*["\']([^"\']+\.hls)["\']', html)
        if file_match:
            hls_url = file_match.group(1)
            if not hls_url.startswith('http'):
                hls_url = host + hls_url

            try:
                hls_resp = requests.get(hls_url, headers=self.headers, timeout=TIMEOUT, verify=False)
                hls_resp.encoding = 'utf-8'
                hls_content = hls_resp.text
                final_hls_url = hls_resp.url
                if hls_content:
                    streams = re.findall(r'#EXT-X-STREAM-INF:([^\n]+)\n([^\n]+)', hls_content)
                    stream_items = []
                    for stream_info, stream_url in streams:
                        resolution_match = re.search(r'RESOLUTION=(\d+x\d+)', stream_info)
                        bandwidth_match = re.search(r'BANDWIDTH=(\d+)', stream_info)

                        height = 0
                        if resolution_match:
                            res = resolution_match.group(1)
                            height = int(res.split('x')[1])
                            quality = str(height) + 'p'
                        elif bandwidth_match:
                            bps = int(bandwidth_match.group(1))
                            if bps >= 15000000:
                                quality = '2160p'; height = 2160
                            elif bps >= 5000000:
                                quality = '1080p'; height = 1080
                            elif bps >= 2000000:
                                quality = '720p'; height = 720
                            elif bps >= 1000000:
                                quality = '480p'; height = 480
                            else:
                                quality = '360p'; height = 360
                        else:
                            quality = '未知'

                        if not stream_url.startswith('http'):
                            stream_url = final_hls_url.rsplit('/', 1)[0] + '/' + stream_url

                        stream_items.append((height, f"{quality}${stream_url}"))
                    stream_items.sort(key=lambda x: x[0], reverse=True)
                    play_url.extend([item[1] for item in stream_items])
                else:
                    play_url.append(f"自动${hls_url}")
            except Exception:
                play_url.append(f"自动${hls_url}")
        else:
            sources_matches = re.findall(r'sources:\s*\[\s*\{([^}]+)\}\s*\]', html, re.DOTALL)
            for sources_content in sources_matches:
                file_match = re.search(r'"file"\s*:\s*["\']([^"\']+)["\']', sources_content)
                label_match = re.search(r'"label"\s*:\s*["\']([^"\']+)["\']', sources_content)
                if file_match:
                    video_url = file_match.group(1)
                    label = label_match.group(1) if label_match else ''
                    if not video_url.startswith('http'):
                        video_url = host + video_url
                    play_url.append(f"{label if label else '自动'}${video_url}")

        play_from_str = 'thumbzilla'
        play_url_str = '#'.join(play_url)

        return {'list': [{
            'vod_id': did,
            'vod_name': title,
            'vod_pic': vod_pic,
            'vod_actor': '',
            'vod_director': '',
            'vod_content': '',
            'vod_year': '',
            'vod_area': '',
            'vod_remarks': '',
            'vod_play_from': play_from_str,
            'vod_play_url': play_url_str,
            'type': 'video',
        }]}

    def searchContent(self, key, quick, pg=1):
        host = self.host
        url = host + "/s/" + key if pg == 1 else host + "/s/" + key + "/page/" + str(pg)
        html = self._fetch_url(url)
        if not html:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0}

        video_list = self._parse_video_list(html)
        return {'list': video_list, 'page': pg, 'pagecount': 10, 'limit': len(video_list), 'total': len(video_list) * 10}

    def playerContent(self, flag, id, vipFlags=None):
        url = id
        try:
            r = requests.head(url, headers=self.headers, timeout=TIMEOUT, verify=False, allow_redirects=True)
            final_url = r.url if r.status_code == 200 else url
        except Exception:
            final_url = url
        return {'parse': 0, 'url': final_url, 'jx': 0, 'headers': self.headers}

    def localProxy(self, params):
        return None
