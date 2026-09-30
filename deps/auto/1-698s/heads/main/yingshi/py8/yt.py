import re, sys, json, base64
from Crypto.Cipher import AES
from urllib.parse import quote
from Crypto.Util.Padding import unpad
from base.spider import Spider

sys.path.append('..')

class Spider(Spider):
    headers = {'User-Agent': 'okhttp/4.12.0'}
    
    FIXED_CONFIG = {
        'host': 'http://pgcms.lyyytv.cn',
        'cmskey': 'wP5btxoc3yv8FoBQENFZumF0EUYr4LTy'
    }

    def init(self, extend=''):
        self.host = self.FIXED_CONFIG['host']
        self.cmskey = self.FIXED_CONFIG.get('cmskey', '')
        
        # ============ 原来的解析器（虚联、虚移、虚翼使用这个）============
        self.external_parser = "http://yoyo.ovg.sh/yt/ttjx.php?url="
        
        # ============ 新增解析器（虚腾、虚果、虚爱、虚酷、虚哔、虚哩使用这个）============
        self.need_parse_lines = ["藤藤", "茫茫", "小爱", "小优", "小哩"]
        
        # 新增解析源列表（按优先级排序）
        self.new_parsers = [      
            "http://nm.4688888.xyz/jiexi.php?data=093207528aec95afa4616e7afb8e2649&url=",  # 牛马解析
            "http://120.46.190.255//jiexi.php?data=f603bb5f52a0cc1db4064599c3cc9abf&url=",  # 小白解析
            "http://8.155.50.80/xiayexk.php?url=",  # 夏夜解析
            "https://qsy.wya6.cn/parse.php?url=",  # 无意云解析
            "http://zhuimi.摸鱼儿.com/moyu/zhuimi?token=uZBC6q6w&url=",  # 摸鱼解析
            "http://yoyo168.zabc.net/getjx.php?host=http://154.222.26.58:7788&key=guodan2004031600&api=6d735c167eeda72b836cf382e4863f3f&v=",  # 呦呦解析
            "https://cachem3u8.2s0.cn:8899/Th_JsonApi.php?url=",  #擦车解析
            "http://mg.itufm.top/mg.php?url=",#芒果解析    
            "https://jx.xmflv.com/?url=",  # 虾米嗅探
            "https://pp1301239612013983305599.tai2tai.sbs/?url=",  # 太乙嗅探
            "https://jx.m3u8.tv/jiexi/?url="  # m3u8解析
        ]
        
        self.direct_sniff_keys = [
            "tai2tai.sbs",
            "xmflv.com",
            "m3u8.tv"
        ]
        
        # ============ 域名替换规则 ============
        self.domain_replace_rules = {
        }
        
        # ============ 线路配置开始 ============
        self.line_name_mapping = {
            "移动云": "移不动",
            "天翼云": "天意也",
            "联通云": "联不通",
            "蓝奏云": "拦着揍",
            "腾讯": "藤藤",
            "芒果": "茫茫",
            "爱奇艺": "小爱",
            "优酷": "小优",
            "BL线路": "小哩"
        }
        
        self.line_order = [
            "移不动", "天意也", "联不通", "拦着揍", "藤藤", "茫茫", "小爱", "小优", "小哩"
        ]
        
        # ============ 新增：线路特定的headers ============
        self.line_headers = {
            "藤藤": {  # 腾讯视频
                'User-Agent': 'okhttp/4.12.0',
                'Referer': 'https://v.qq.com'
            },
            "茫茫": {  # 芒果TV
                'User-Agent': 'okhttp/4.12.0',
                'Referer': ''
            },
            "小爱": {  # 爱奇艺
                'User-Agent': 'okhttp/4.12.0',
                'Referer': 'https://www.iqiyi.com'
            },
            "小优": {  # 优酷
                'User-Agent': 'okhttp/4.12.0',
                'Referer': 'https://v.youku.com'
            },
            "小哩": {  # Bilibili需要Referer
                'User-Agent': 'okhttp/4.12.0',
                'Referer': 'https://www.bilibili.com'
            }                       
        }

    def homeVideoContent(self):
        data = self.fetch(f"{self.host}/api.php/app/index_video?token=", headers=self.headers).json()
        videos = []
        for item in data['list']:
            videos.extend(item['vlist'])
        return {'list': videos}

    def homeContent(self, filter):
        data = self.fetch(f"{self.host}/api.php/app/nav?token=", headers=self.headers).json()
        keys = ["class", "area", "lang", "year", "letter", "by", "sort"]
        filters = {}
        classes = []
        
        for item in data['list']:
            has_non_empty_field = False
            jsontype_extend = item["type_extend"]
            classes.append({"type_name": item["type_name"], "type_id": item["type_id"]})
            
            for key in keys:
                if key in jsontype_extend and jsontype_extend[key].strip() != "":
                    has_non_empty_field = True
                    break
            
            if has_non_empty_field:
                filters[str(item["type_id"])] = []
            
            for dkey in jsontype_extend:
                if dkey in keys and jsontype_extend[dkey].strip() != "":
                    values = jsontype_extend[dkey].split(",")
                    value_array = []
                    for value in values:
                        if value.strip() != "":
                            value_array.append({"n": value.strip(), "v": value.strip()})
                    filters[str(item["type_id"])].append({"key": dkey, "name": dkey, "value": value_array})
        
        return {"class": classes, "filters": filters}

    def categoryContent(self, tid, pg, filter, extend):
        params = {
            'tid': tid,
            'class': extend.get('class', ''),
            'area': extend.get('area', ''),
            'lang': extend.get('lang', ''),
            'year': extend.get('year', ''),
            'limit': '18',
            'pg': pg
        }
        data = self.fetch(f"{self.host}/api.php/app/video", params=params, headers=self.headers).json()
        return data

    def searchContent(self, key, quick, pg="1"):
        data = self.fetch(f"{self.host}/api.php/app/search?text={key}&pg={pg}", headers=self.headers).json()
        videos = data['list']
        for item in data['list']:
            item.pop('type', None)
        return {'list': videos, 'page': pg}

    def detailContent(self, ids):
        data = self.fetch(f"{self.host}/api.php/app/video_detail?id={ids[0]}", headers=self.headers).json()['data']
        show, paly_urls = [], []
        
        for i in data['vod_url_with_player']:
            original_name = i['name'].strip()
            
            if original_name in self.line_name_mapping and self.line_name_mapping[original_name] == "":
                continue
                
            display_name = self.line_name_mapping.get(original_name, original_name)
            
            urls = i['url'].split('#')
            urls2 = []
            for j in urls:
                if j:
                    if j.startswith('lvdou+'):
                        j = self.lvdou(j)
                    
                    j = self.replace_domains(j)
                    
                    url = j.split('$', 1)
                    if len(url) == 2:
                        urls2.append(f"{url[0]}${url[1]}")
                    else:
                        urls2.append(j)
            paly_urls.append('#'.join(urls2))
            show.append(display_name)
        
        data.pop('vod_url_with_player')
        
        sorted_show, sorted_paly_urls = self.sort_play_lines(show, paly_urls)
        
        data['vod_play_from'] = '$$$'.join(sorted_show)
        data['vod_play_url'] = '$$$'.join(sorted_paly_urls)
        return {'list': [data]}

    def playerContent(self, flag, video_id, vipFlags):
        print(f"=== playerContent 被调用 ===")
        print(f"线路标识: {flag}")
        print(f"原始播放地址: {video_id}")
        
        # 获取该线路特定的headers
        line_header = self.line_headers.get(flag, self.headers)
        print(f"使用headers: {line_header}")
        
        if video_id.startswith('lvdou+'):
            decrypted_url = self.lvdou(video_id)
        else:
            decrypted_url = video_id
        
        decrypted_url = self.replace_domains(decrypted_url)
        
        print(f"解密/替换后地址: {decrypted_url}")
        
        if decrypted_url.endswith('.m3u8') or '.m3u8?' in decrypted_url or '#EXTM3U' in decrypted_url:
            print(f"✅ 已经是m3u8直链，直连播放")
            return {
                'parse': 0,
                'jx': 0,
                'url': decrypted_url,
                'header': line_header
            }
        
        if flag in self.need_parse_lines:
            print(f"线路 {flag} 需要解析")
            return self._try_parsers(decrypted_url, self.new_parsers, flag)
        elif re.search(r'(?:www\.iqiyi|v\.qq|v\.youku|www\.mgtv|www\.bilibili)\.com', decrypted_url):
            print(f"视频网站链接，使用解析器")
            return self._try_parsers(decrypted_url, self.new_parsers, flag)
        else:
            print(f"线路 {flag} 使用external_parser直接解析")
            return self._parse_external_direct(decrypted_url, flag)
    
    def replace_domains(self, url):
        if not url:
            return url
            
        for old_domain, new_domain in self.domain_replace_rules.items():
            if old_domain in url:
                url = url.replace(old_domain, new_domain)
        
        return url
    
    def _parse_external_direct(self, video_url, flag=None):
        print(f"使用external_parser直接解析")
        
        # 获取该线路特定的headers
        line_header = self.line_headers.get(flag, self.headers) if flag else self.headers
        
        try:
            parsed_url = f"{self.external_parser}{quote(video_url)}"
            print(f"解析地址: {parsed_url[:150]}...")
            
            response = self.fetch(parsed_url, allow_redirects=True, timeout=10, headers=line_header)
            
            if response.status_code != 200:
                print(f"解析失败，状态码: {response.status_code}")
                return {
                    'parse': 1,
                    'jx': 1,
                    'url': video_url,
                    'header': line_header
                }
            
            content = response.text
            
            if content.strip().startswith('{'):
                try:
                    json_response = response.json()
                    print(f"解析器返回JSON格式")
                    
                    possible_fields = ['url', 'm3u8', 'play_url', 'video_url', 'src', 'data']
                    
                    for field in possible_fields:
                        if field in json_response:
                            if isinstance(json_response[field], str):
                                video_url_result = json_response[field]
                                print(f"从字段 {field} 提取到地址: {video_url_result[:100]}")
                                video_url_result = self.replace_domains(video_url_result)
                                return {
                                    'parse': 0,
                                    'jx': 0,
                                    'url': video_url_result,
                                    'header': line_header
                                }
                            elif isinstance(json_response[field], dict):
                                for sub_field in possible_fields:
                                    if sub_field in json_response[field] and isinstance(json_response[field][sub_field], str):
                                        video_url_result = json_response[field][sub_field]
                                        print(f"从嵌套字段 {field}.{sub_field} 提取到地址: {video_url_result[:100]}")
                                        video_url_result = self.replace_domains(video_url_result)
                                        return {
                                            'parse': 0,
                                            'jx': 0,
                                            'url': video_url_result,
                                            'header': line_header
                                        }
                except Exception as e:
                    print(f"JSON解析失败: {e}")
            
            if '#EXTM3U' in content:
                print(f"解析器返回m3u8内容")
                return {
                    'parse': 0,
                    'jx': 0,
                    'url': parsed_url,
                    'header': line_header
                }
            
            m3u8_matches = re.findall(r'https?://[^\s<>"\']+\.(?:m3u8|mp4)[^\s<>"\']*', content)
            if m3u8_matches:
                video_url_result = m3u8_matches[0]
                print(f"从页面提取到视频地址: {video_url_result[:100]}")
                video_url_result = self.replace_domains(video_url_result)
                return {
                    'parse': 0,
                    'jx': 0,
                    'url': video_url_result,
                    'header': line_header
                }
            
            print(f"未找到视频地址，返回原链让壳子解析")
            return {
                'parse': 1,
                'jx': 1,
                'url': video_url,
                'header': line_header
            }
                
        except Exception as e:
            print(f"解析器异常: {e}")
            return {
                'parse': 1,
                'jx': 1,
                'url': video_url,
                'header': line_header
            }
    
    def _try_parsers(self, video_url, parsers, flag=None):
        """
        核心修复：尝试所有解析器，直到找到可用的
        只有两种情况下才返回：1.找到视频地址 2.所有解析器都试过了
        """
        print(f"尝试 {len(parsers)} 个解析器")
        
        # 获取该线路特定的headers
        line_header = self.line_headers.get(flag, self.headers) if flag else self.headers
        
        # 按优先级尝试所有解析器
        for i, parser in enumerate(parsers):
            try:
                parsed_url = f"{parser}{quote(video_url)}"
                print(f"\n[{i+1}/{len(parsers)}] 尝试解析器: {parser}")
                print(f"解析地址: {parsed_url[:100]}...")
                
                # 检查是否是嗅探解析器
                is_direct_sniff = any(key in parser for key in self.direct_sniff_keys)
                
                if is_direct_sniff:
                    # 嗅探解析器：返回给壳子处理
                    print(f"✅ 嗅探解析器，返回给壳子处理 (parse=1)")
                    return {
                        'parse': 1,
                        'url': parsed_url,
                        'header': line_header
                    }
                
                # 普通解析器：尝试请求获取视频地址
                print(f"普通解析器，尝试获取视频地址...")
                response = self.fetch(parsed_url, timeout=10, allow_redirects=True, headers=line_header)
                
                if response.status_code != 200:
                    print(f"✗ 解析器返回状态码: {response.status_code}")
                    continue  # 继续下一个解析器
                
                content = response.text
                
                # 检查是否是测试视频
                if self._is_test_video(content):
                    print(f"✗ 解析器返回测试视频")
                    continue  # 继续下一个解析器
                
                # 1. 检查是否是m3u8内容
                if '#EXTM3U' in content:
                    print(f"✓ 解析器返回m3u8内容")
                    # 检查是否可以直接播放
                    if re.search(r'\.m3u8', content) or 'video/' in response.headers.get('Content-Type', ''):
                        return {
                            'parse': 0,
                            'jx': 0,
                            'url': parsed_url,
                            'header': line_header
                        }
                    else:
                        # 需要进一步处理
                        return {
                            'parse': 1,
                            'jx': 0,
                            'url': parsed_url,
                            'header': line_header
                        }
                
                # 2. 检查JSON格式
                if content.strip().startswith('{'):
                    try:
                        json_data = json.loads(content)
                        video_url_from_json = self._extract_video_url_from_json(json_data)
                        if video_url_from_json:
                            video_url_from_json = self.replace_domains(video_url_from_json)
                            print(f"✓ 从JSON提取到视频地址: {video_url_from_json[:100]}")
                            return {
                                'parse': 0,
                                'jx': 0,
                                'url': video_url_from_json,
                                'header': line_header
                            }
                    except Exception as e:
                        print(f"JSON解析失败: {e}")
                        # JSON解析失败，继续下一个解析器
                        continue
                
                # 3. 从HTML中提取视频地址
                video_patterns = [
                    r'src=["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                    r'url["\']?\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                    r'video["\']?\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                    r'file["\']?\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                ]
                
                for pattern in video_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        for match in matches:
                            if match.startswith('http'):
                                video_url_result = match
                                video_url_result = self.replace_domains(video_url_result)
                                print(f"✓ 从HTML提取到视频地址: {video_url_result[:100]}")
                                return {
                                    'parse': 0,
                                    'jx': 0,
                                    'url': video_url_result,
                                    'header': line_header
                                }
                
                # 4. 直接查找.m3u8或.mp4链接
                direct_matches = re.findall(r'https?://[^\s<>"\']+\.(?:m3u8|mp4)[^\s<>"\']*', content)
                if direct_matches:
                    video_url_result = direct_matches[0]
                    video_url_result = self.replace_domains(video_url_result)
                    print(f"✓ 直接提取到视频地址: {video_url_result[:100]}")
                    return {
                        'parse': 0,
                        'jx': 0,
                        'url': video_url_result,
                        'header': line_header
                    }
                
                # 5. 如果没有找到视频地址，继续尝试下一个解析器
                print(f"✗ 未找到视频地址，继续尝试下一个解析器")
                continue  # 关键修复：这里用continue而不是return
                    
            except Exception as e:
                print(f"✗ 解析器失败: {str(e)[:100]}")
                continue  # 继续下一个解析器
        
        # 所有解析器都失败，才返回原链让壳子处理
        print(f"✗ 所有 {len(parsers)} 个解析器都尝试过了，全部失败")
        print(f"返回原链让壳子处理")
        return {
            'parse': 1,
            'jx': 1,
            'url': video_url,
            'header': line_header
        }
    
    def _extract_video_url_from_json(self, json_data):
        if not json_data:
            return None
            
        possible_fields = ['url', 'm3u8', 'play_url', 'video_url', 'src', 'link']
        
        for field in possible_fields:
            if field in json_data and json_data[field] and isinstance(json_data[field], str):
                return json_data[field]
        
        if 'data' in json_data and isinstance(json_data['data'], dict):
            for field in possible_fields:
                if field in json_data['data'] and json_data['data'][field] and isinstance(json_data['data'][field], str):
                    return json_data['data'][field]
        
        return None
    
    def _is_test_video(self, text):
        if not text:
            return False
            
        text_lower = text.lower()
        
        test_patterns = [
            'oplist.wya6.cn',
            'web.wya6.com',
            'k0udeyaayccydz.djvod.ndcimgs.com',
            'pan.baidu.re',
            'www.panurl.cn',
            'test.mp4', 'demo.mp4', 'sample.mp4',
            'short.mp4', 'preview.mp4', 'trailer.mp4',
            'ad.mp4', '广告.mp4',
            '/10秒.mp4', '/15秒.mp4', '/30秒.mp4',
            '/10s.mp4', '/15s.mp4', '/30s.mp4',
            'error.html', '404.mp4', 'error.mp4',
        ]
        
        for pattern in test_patterns:
            if pattern in text_lower:
                print(f"检测到测试视频特征: {pattern}")
                return True
                
        return False

    def lvdou(self, text):
        key = self.cmskey[:16].encode("utf-8")
        iv = self.cmskey[-16:].encode("utf-8")
        original_text = text
        url_prefix = "lvdou+"
        
        if original_text.startswith(url_prefix):
            ciphertext_b64 = original_text[len(url_prefix):]
            try:
                cipher = AES.new(key, AES.MODE_CBC, iv)
                ct_bytes = base64.b64decode(ciphertext_b64)
                pt_bytes = cipher.decrypt(ct_bytes)
                return unpad(pt_bytes, AES.block_size).decode('utf-8')
            except Exception:
                return original_text
        else:
            return original_text

    def sort_play_lines(self, show_list, url_list):
        if len(show_list) != len(url_list):
            return show_list, url_list
        
        original_order = {}
        for idx, name in enumerate(show_list):
            original_order[name] = idx
        
        line_map = {}
        for name, url in zip(show_list, url_list):
            line_map[name] = url
        
        sorted_show = []
        sorted_urls = []
        
        for ordered_name in self.line_order:
            if ordered_name in line_map:
                sorted_show.append(ordered_name)
                sorted_urls.append(line_map[ordered_name])
                line_map.pop(ordered_name)
        
        remaining_lines = [(name, line_map[name], original_order[name]) 
                          for name in line_map.keys()]
        remaining_lines.sort(key=lambda x: x[2])
        
        for name, url, _ in remaining_lines:
            sorted_show.append(name)
            sorted_urls.append(url)
        
        return sorted_show, sorted_urls

    def getName(self): 
        return "小心儿悠悠（修复版）"
    
    def isVideoFormat(self, url): 
        return True

    def fetch(self, url, **kwargs):
        import requests
        if 'headers' not in kwargs:
            kwargs['headers'] = self.headers
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 10
        try:
            return requests.get(url, **kwargs)
        except Exception as e:
            print(f"请求失败: {str(e)}")
            from requests.models import Response
            response = Response()
            response.status_code = 500
            return response