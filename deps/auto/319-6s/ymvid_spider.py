#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
粤漫之家(ymvid.com) 爬虫 - 增强调试版
专注粤语动漫资源的爬取
"""
import json
import re
import sys
from urllib.parse import urljoin, quote
import requests
from pyquery import PyQuery as pq

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    """粤漫之家爬虫类"""

    def __init__(self):
        self.host = 'https://www.ymvid.com'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': f'{self.host}/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0'
        }
        self.debug_mode = True  # 开启调试模式

    def init(self, extend='{}'):
        """初始化配置"""
        try:
            config = json.loads(extend)
            self.proxies = config.get('proxy', {})
        except:
            self.proxies = {}

    def getName(self):
        """返回爬虫名称"""
        return "粤漫之家"

    # ==================== 核心功能方法 ====================

    def homeContent(self, filter):
        """
        获取首页分类和筛选配置
        """
        result = {}

        # 分类配置
        categories = {
            "全部动画": "1",
            "粤语动画": "1-c1",
            "国语动画": "1-c2",
            "连载中": "1-s1",
            "已完结": "1-s2"
        }

        classes = []
        for name, tid in categories.items():
            classes.append({
                'type_id': tid,
                'type_name': name
            })

        result['class'] = classes

        # 筛选器配置
        if filter:
            result['filters'] = {
                '1': [
                    {
                        'key': 'c',
                        'name': '语言',
                        'value': [
                            {'n': '全部', 'v': '0'},
                            {'n': '粤语', 'v': '1'},
                            {'n': '国语', 'v': '2'}
                        ]
                    },
                    {
                        'key': 's',
                        'name': '状态',
                        'value': [
                            {'n': '全部', 'v': '0'},
                            {'n': '连载', 'v': '1'},
                            {'n': '完结', 'v': '2'},
                            {'n': '未播放', 'v': '3'}
                        ]
                    },
                    {
                        'key': 'v',
                        'name': '版本',
                        'value': [
                            {'n': '全部', 'v': '0'},
                            {'n': 'TV', 'v': '1'},
                            {'n': '剧场版', 'v': '2'},
                            {'n': 'OVA', 'v': '3'},
                            {'n': '其他', 'v': '4'}
                        ]
                    },
                    {
                        'key': 't',
                        'name': '类型',
                        'value': [
                            {'n': '全部', 'v': '0'},
                            {'n': '搞笑', 'v': '1'},
                            {'n': '运动', 'v': '2'},
                            {'n': '励志', 'v': '3'},
                            {'n': '热血', 'v': '4'},
                            {'n': '战斗', 'v': '5'},
                            {'n': '校园', 'v': '6'},
                            {'n': '冒险', 'v': '7'},
                            {'n': '魔法', 'v': '8'},
                            {'n': '科幻', 'v': '9'},
                            {'n': '机器人', 'v': '10'},
                            {'n': '亲子', 'v': '11'}
                        ]
                    },
                    {
                        'key': 'y',
                        'name': '年份',
                        'value': [
                            {'n': '全部', 'v': '0'},
                            {'n': '2025', 'v': '2025'},
                            {'n': '2024', 'v': '2024'},
                            {'n': '2023', 'v': '2023'},
                            {'n': '2022', 'v': '2022'},
                            {'n': '2021', 'v': '2021'},
                            {'n': '2020', 'v': '2020'},
                            {'n': '2019', 'v': '2019'}
                        ]
                    }
                ]
            }

        return result

    def homeVideoContent(self):
        """获取首页推荐视频"""
        try:
            response = self.fetch(self.host)
            if not response:
                self.log("❌ 无法获取首页内容")
                return {'list': []}

            html = pq(response.text)

            # 尝试多个可能的选择器
            all_selectors = [
                # 基于链接的选择器（最可靠）
                'a[href*="/play/"]',
                'a[href*="/voddetail/"]',
                'a[href*="/video/"]',

                # 标准模板选择器
                '.module-items .module-item',
                '.module-list .module-item',
                '.video-list .video-item',
                '.vodlist .vodlist_item',

                # 通用选择器
                '.module-item',
                '.video-item',
                'article.item',
                '.stui-vodlist__box',
                '.myui-vodlist__box'
            ]

            videos = []
            processed_ids = set()  # 去重
            found_selector = None

            for selector in all_selectors:
                items = html(selector)
                self.log(f"尝试选择器 '{selector}': 找到 {len(items)} 个元素")

                if len(items) > 5:  # 首页应该有多个视频
                    # 尝试解析
                    for item in items.items():
                        try:
                            video = self._parse_video_item(item, html)
                            if video.get('vod_id') and video['vod_id'] not in processed_ids:
                                processed_ids.add(video['vod_id'])
                                videos.append(video)
                        except Exception as e:
                            continue

                    if len(videos) > 5:
                        found_selector = selector
                        self.log(f"✅ 成功！选择器 '{selector}' 解析出 {len(videos)} 个视频")
                        break
                    else:
                        videos = []
                        processed_ids = set()

            if not found_selector:
                self.log("❌ 所有选择器都无法找到有效的视频")
                self.log("💡 建议：检查日志中的HTML结构分析")

            return {'list': videos}

        except Exception as e:
            self.log(f"❌ homeVideoContent错误: {e}")
            import traceback
            self.log(traceback.format_exc())
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        """
        获取分类内容
        tid格式: "1" 或 "1-c1" (带预设筛选)
        """
        try:
            pg = int(pg)  # 转换页码为整数
            base_tid = tid.split('-')[0]

            # 构建筛选参数
            filter_parts = []
            if '-' in tid:
                preset_filters = tid.split('-', 1)[1]
                for part in preset_filters.split('-'):
                    key = part[0]
                    value = part[1:]
                    if extend.get(key):
                        filter_parts.append(f"{key}{extend[key]}")
                    else:
                        filter_parts.append(part)

            filter_keys = ['c', 's', 'v', 'l', 't', 'y']
            for key in filter_keys:
                if key in extend and extend[key] != '0':
                    if not any(p.startswith(key) for p in filter_parts):
                        filter_parts.append(f"{key}{extend[key]}")
                elif not any(p.startswith(key) for p in filter_parts):
                    filter_parts.append(f"{key}0")

            filter_str = '-'.join(filter_parts) if filter_parts else 'c0-s0-v0-l0-t0-y0'

            # 构建URL
            url = f'{self.host}/hk/list/{base_tid}/{filter_str}/time_desc'
            if pg > 1:
                url = f'{url}/page/{pg}'

            self.log(f"📍 分类URL: {url}")

            response = self.fetch(url)
            if not response:
                return self._empty_result(pg)

            html = pq(response.text)

            # 使用与首页相同的多选择器策略
            all_selectors = [
                'a[href*="/play/"]',
                '.module-items .module-item',
                '.module-list .module-item',
                '.video-list .video-item',
                '.module-item',
                '.video-item',
                '.stui-vodlist__box',
                '.myui-vodlist__box'
            ]

            videos = []
            processed_ids = set()

            for selector in all_selectors:
                items = html(selector)
                self.log(f"尝试选择器 '{selector}': 找到 {len(items)} 个元素")

                if len(items) > 5:
                    for item in items.items():
                        try:
                            video = self._parse_video_item(item, html)
                            if video.get('vod_id') and video['vod_id'] not in processed_ids:
                                processed_ids.add(video['vod_id'])
                                videos.append(video)
                        except:
                            continue

                    if len(videos) > 5:
                        self.log(f"✅ 成功！解析出 {len(videos)} 个视频（去重后）")
                        break
                    else:
                        videos = []
                        processed_ids = set()

            pagecount = self._extract_pagecount(html)

            return {
                'list': videos,
                'page': pg,
                'pagecount': pagecount,
                'limit': 24,
                'total': pagecount * 24
            }

        except Exception as e:
            self.log(f"❌ categoryContent错误: {e}")
            import traceback
            self.log(traceback.format_exc())
            return self._empty_result(int(pg) if isinstance(pg, str) else pg)

    def detailContent(self, ids):
        """获取视频详情"""
        try:
            video_id = ids[0]
            url = f'{self.host}/play/{video_id}'

            response = self.fetch(url)
            if not response:
                return {'list': []}

            html = pq(response.text)

            # 提取基本信息 - 使用多个备选选择器
            vod = {
                'vod_id': video_id,
                'vod_name': (html('h1').text() or
                            html('.video-info-header h1').text() or
                            html('.title').text() or
                            html('.module-info-heading h1').text() or ''),
                'vod_content': (html('.vod_content').text() or
                               html('.video-info-item:contains("简介")').text() or
                               html('.detail-content').text() or
                               html('.description').text() or '')
            }

            # 提取封面图 - 排除logo
            for img in html('img').items():
                img_src = img.attr('data-src') or img.attr('src') or ''
                # 排除logo和小图标
                if img_src and 'logo' not in img_src.lower() and img_src.startswith('http'):
                    # 检查图片尺寸属性或class，优先选大图
                    if any(keyword in img_src for keyword in ['poster', 'cover', 'thumb']):
                        vod['vod_pic'] = img_src
                        break
                    elif not vod.get('vod_pic'):
                        vod['vod_pic'] = img_src

            # 如果还是没有封面，尝试从style背景图提取
            if not vod.get('vod_pic'):
                for elem in html('[style*="background"]').items():
                    style = elem.attr('style') or ''
                    bg_match = re.search(r'url\(["\']?([^"\'()]+)["\']?\)', style)
                    if bg_match:
                        bg_url = bg_match.group(1)
                        if 'logo' not in bg_url.lower():
                            vod['vod_pic'] = urljoin(self.host, bg_url)
                            break

            # 提取播放源和剧集
            play_from, play_url = self._extract_play_info(html, video_id)

            if play_from:
                vod['vod_play_from'] = '$$$'.join(play_from)
                vod['vod_play_url'] = '$$$'.join(play_url)
                self.log(f"✅ 提取到 {len(play_from)} 个播放源，共 {sum(len(url.split('#')) for url in play_url)} 集")
            else:
                vod['vod_play_from'] = '默认'
                vod['vod_play_url'] = f"播放${video_id}"
                self.log("⚠️ 未找到播放列表，使用默认")

            return {'list': [vod]}

        except Exception as e:
            self.log(f"❌ detailContent错误: {e}")
            import traceback
            self.log(traceback.format_exc())
            return {'list': []}

    def searchContent(self, key, quick, pg='1'):
        """搜索功能"""
        try:
            search_url = f'{self.host}/hk/search/{quote(key)}'
            if pg != '1':
                search_url = f'{search_url}/page/{pg}'

            response = self.fetch(search_url)
            if not response:
                return {'list': [], 'page': pg}

            html = pq(response.text)

            # 使用多选择器
            all_selectors = [
                'a[href*="/play/"]',
                '.module-items .module-item',
                '.search-list .search-item',
                '.video-list .video-item',
                '.module-item'
            ]

            videos = []
            processed_ids = set()

            for selector in all_selectors:
                items = html(selector)
                if len(items) > 0:
                    for item in items.items():
                        try:
                            video = self._parse_video_item(item, html)
                            if video.get('vod_id') and video['vod_id'] not in processed_ids:
                                processed_ids.add(video['vod_id'])
                                videos.append(video)
                        except:
                            continue
                    if videos:
                        break

            self.log(f"搜索 '{key}': 找到 {len(videos)} 个结果")
            return {'list': videos, 'page': pg}

        except Exception as e:
            self.log(f"❌ searchContent错误: {e}")
            return {'list': [], 'page': pg}

    def playerContent(self, flag, id, vipFlags):
        """获取播放链接"""
        try:
            if not id.startswith('http'):
                play_url = f'{self.host}/play/{id}'
            else:
                play_url = id

            response = self.fetch(play_url)
            if not response:
                return {'parse': 1, 'url': play_url, 'header': self.headers}

            real_url = self._extract_video_url(response.text)

            if real_url:
                self.log(f"✅ 提取到直链: {real_url[:50]}...")
                return {'parse': 0, 'url': real_url, 'header': self.headers}
            else:
                self.log(f"⚠️ 未找到直链，返回嗅探模式")
                return {'parse': 1, 'url': play_url, 'header': self.headers}

        except Exception as e:
            self.log(f"❌ playerContent错误: {e}")
            return {'parse': 1, 'url': play_url, 'header': self.headers}

    # ==================== 辅助方法 ====================

    def fetch(self, url, headers=None, timeout=15):
        """统一的HTTP请求方法"""
        if headers is None:
            headers = self.headers

        try:
            response = requests.get(
                url,
                headers=headers,
                proxies=self.proxies,
                timeout=timeout,
                verify=False  # 忽略SSL证书验证
            )

            if response.status_code != 200:
                self.log(f"⚠️ HTTP {response.status_code}: {url}")

            response.raise_for_status()
            return response
        except Exception as e:
            self.log(f"❌ 请求失败 {url}: {e}")
            return None

    def _parse_video_item(self, item, html=None):
        """解析视频列表项 - 增强版"""
        video = {}

        try:
            # 情况1: item本身就是a标签
            if item[0].tag == 'a':
                href = item.attr('href')
                if href and '/play/' in href:
                    match = re.search(r'/play/(\d+)', href)
                    if match:
                        video['vod_id'] = match.group(1)

                        # 从链接或父元素提取标题
                        title = (item.text().strip() or
                                item.attr('title') or
                                item.parent().find('.title').text() or
                                item.parent().find('h3').text() or '')

                        if title and len(title) > 1:
                            video['vod_name'] = title

                        # 提取图片
                        img = item.find('img')
                        if not img:
                            img = item.parent().find('img')
                        if img:
                            img_src = img.attr('data-src') or img.attr('src')
                            if img_src:
                                video['vod_pic'] = urljoin(self.host, img_src)

            # 情况2: item是容器元素
            else:
                # 提取链接和ID
                link = item('a').attr('href') or item.attr('href')
                if link and '/play/' in link:
                    match = re.search(r'/play/(\d+)', link)
                    if match:
                        video['vod_id'] = match.group(1)

                # 提取标题 - 多个备选
                title = (item('.module-item-title').text() or
                        item('.title').text() or
                        item('h3').text() or
                        item('.video-serial').attr('title') or
                        item('a').attr('title') or
                        item.attr('title') or '')

                if title:
                    video['vod_name'] = title.strip()

                # 提取图片 - 多个备选
                img_elem = item('img')
                if img_elem:
                    img_src = (img_elem.attr('data-src') or
                              img_elem.attr('src') or
                              img_elem.attr('data-original'))
                    if img_src:
                        video['vod_pic'] = urljoin(self.host, img_src)

                # 提取备注
                remarks = (item('.module-item-text').text() or
                          item('.video-serial').text() or
                          item('.remarks').text() or '')
                if remarks:
                    video['vod_remarks'] = remarks.strip()

            # 设置样式
            if video.get('vod_id'):
                video['style'] = {'type': 'rect', 'ratio': 1.4}

        except Exception as e:
            if self.debug_mode:
                self.log(f"解析视频项异常: {e}")

        return video

    def _extract_play_info(self, html, video_id):
        """提取播放源和剧集信息"""
        play_from = []
        play_url = []

        try:
            # 尝试查找剧集列表容器
            episode_containers = [
                '.module-play-list',
                '.module-blocklist',
                '.play-list',
                '.episode-list',
                '.stui-content__playlist',
                '.playlist'
            ]

            found_episodes = False

            for container_selector in episode_containers:
                container = html(container_selector)
                if len(container) > 0:
                    self.log(f"找到剧集容器: {container_selector}")

                    # 查找该容器内的所有播放链接
                    episode_links = container.find('a[href*="/play/"]')

                    if len(episode_links) > 0:
                        play_from.append('默认')
                        episodes = []
                        processed_ids = set()

                        for link in episode_links.items():
                            href = link.attr('href')
                            if href:
                                match = re.search(r'/play/(\d+)', href)
                                if match:
                                    ep_id = match.group(1)
                                    # 跳过当前正在播放的视频ID和重复的
                                    if ep_id != video_id and ep_id not in processed_ids:
                                        processed_ids.add(ep_id)
                                        ep_name = link.text().strip()

                                        # 过滤掉无效的剧集名
                                        if ep_name and len(ep_name) < 50 and not any(
                                            keyword in ep_name for keyword in ['简中', '繁中', '粤语', '国语']
                                        ):
                                            episodes.append(f"{ep_name}${ep_id}")
                                        elif not ep_name:
                                            episodes.append(f"第{len(episodes)+1}集${ep_id}")

                        if episodes:
                            play_url.append('#'.join(episodes))
                            self.log(f"✅ 找到 {len(episodes)} 集")
                            found_episodes = True
                            break

            # 如果以上容器都没找到，尝试通用方法
            if not found_episodes:
                all_play_links = html('a[href*="/play/"]')

                if len(all_play_links) > 5:  # 至少有几集
                    play_from.append('默认')
                    episodes = []
                    processed_ids = set()

                    for link in all_play_links.items():
                        href = link.attr('href')
                        if href:
                            match = re.search(r'/play/(\d+)', href)
                            if match:
                                ep_id = match.group(1)
                                if ep_id != video_id and ep_id not in processed_ids:
                                    processed_ids.add(ep_id)
                                    ep_name = link.text().strip()

                                    # 过滤无效剧集名
                                    if ep_name and len(ep_name) < 50 and not any(
                                        keyword in ep_name for keyword in ['简中', '繁中', '粤语', '国语', '首页', '搜索', '分类']
                                    ):
                                        episodes.append(f"{ep_name}${ep_id}")

                    if episodes:
                        play_url.append('#'.join(episodes))
                        self.log(f"✅ 通用方法找到 {len(episodes)} 集")

        except Exception as e:
            self.log(f"提取播放信息失败: {e}")
            import traceback
            self.log(traceback.format_exc())

        return play_from, play_url

    def _extract_video_url(self, html_content):
        """从HTML中提取视频播放链接"""
        patterns = [
            r'"url"\s*:\s*"([^"]+\.m3u8[^"]*)"',
            r'"url"\s*:\s*"([^"]+\.mp4[^"]*)"',
            r'player_data\s*=\s*{[^}]*"url"\s*:\s*"([^"]+)"',
            r'var\s+url\s*=\s*["\']([^"\']+)["\']',
            r'src\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
            r'https?://[^"\'<>\s]+\.m3u8[^"\'<>\s]*',
            r'https?://[^"\'<>\s]+\.mp4[^"\'<>\s]*'
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html_content)
            if matches:
                url = matches[0].replace('\\/', '/')
                return url

        return ''

    def _extract_text(self, html, selector, default=''):
        """安全提取文本"""
        try:
            element = html(selector)
            return element.text().strip() if element else default
        except:
            return default

    def _extract_pagecount(self, html):
        """提取总页数"""
        try:
            pagination = html('.pagination a, .page-link, .page a')
            max_page = 1

            for link in pagination.items():
                text = link.text().strip()
                if text.isdigit():
                    page_num = int(text)
                    if page_num > max_page:
                        max_page = page_num

                href = link.attr('href')
                if href:
                    match = re.search(r'page[=/](\d+)', href)
                    if match:
                        page_num = int(match.group(1))
                        if page_num > max_page:
                            max_page = page_num

            return max_page if max_page > 1 else 999
        except:
            return 999

    def _empty_result(self, pg):
        """返回空结果"""
        return {
            'list': [],
            'page': pg,
            'pagecount': 1,
            'limit': 24,
            'total': 0
        }

    def log(self, message):
        """日志输出"""
        print(f"[粤漫之家] {message}")

    # ==================== 框架必需方法 ====================

    def isVideoFormat(self, url):
        """判断URL是否为视频格式"""
        video_formats = ['.m3u8', '.mp4', '.flv', '.ts']
        return any(fmt in url.lower() for fmt in video_formats)

    def manualVideoCheck(self):
        """是否需要手动检查视频"""
        return False

    def localProxy(self, param):
        """本地代理功能"""
        pass

    def destroy(self):
        """清理资源"""
        pass
