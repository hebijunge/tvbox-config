# -*- coding: utf-8 -*-
"""
江苏名师空中课堂 OK影视Python脚本
"""
import sys
import re
import json
import requests
from urllib.parse import quote, unquote

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        pass


class Spider(Spider):
    def init(self, extend=""):
        self.host = "https://mskzkt.jse.edu.cn"
        self.base_api = "https://mskzkt.jse.edu.cn/baseApi"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 11; SM-G975F) AppleWebKit/537.36 (Chrome/91.0.4472.120 Mobile Safari/537.36",
            "Referer": self.host + "/",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": self.host,
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self._grade_cache = {}
        self._subject_cache = {}
        self._version_cache = {}
        self._play_url_cache = {}
        self._stage_subject_cache = {}

    def getName(self):
        return "江苏名师空中课堂"

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|avi|mkv|mov|ts)(\?|$)', url or "", re.I))

    def manualVideoCheck(self):
        return False

    def _post(self, path, data=None):
        try:
            url = self.base_api + path
            if data is None:
                data = {}
            r = self.session.post(url, data=data, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"[空中课堂] POST失败 {path}: {e}")
        return {"state": -1}

    def homeContent(self, filter):
        return {
            "class": [
                {"type_id": "seyk_1", "type_name": "同步课程-小学"},
                {"type_id": "seyk_2", "type_name": "同步课程-初中"},
                {"type_id": "seyk_3", "type_name": "同步课程-高中"},
                {"type_id": "jzkt", "type_name": "家长课堂"},
                {"type_id": "xljk", "type_name": "心理健康"},
            ],
            "filters": {}
        }

    def homeVideoContent(self):
        try:
            items = self._get_seyk_subject_list(stage_id="1")
            return {"list": items[:20]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        tid = str(tid)
        
        try:
            if tid.startswith("seyk_"):
                stage_id = tid.split("_")[1]
                items = self._get_seyk_subject_list(stage_id)
                start = (page - 1) * 20
                end = start + 20
                page_items = items[start:end]
                total = len(items)
                pagecount = (total + 19) // 20 if total > 0 else 1
                
                return {
                    "page": page,
                    "pagecount": pagecount,
                    "limit": 20,
                    "total": total,
                    "list": page_items,
                }
                
            elif tid == "jzkt":
                items, total = self._get_jzkt_list_with_total(page=page, limit=20)
                pagecount = (total + 19) // 20 if total > 0 else 1
                return {
                    "page": page,
                    "pagecount": pagecount,
                    "limit": 20,
                    "total": total,
                    "list": items,
                }
                
            elif tid == "xljk":
                items, total = self._get_xljk_list_with_total(page=page, limit=20)
                pagecount = (total + 19) // 20 if total > 0 else 1
                return {
                    "page": page,
                    "pagecount": pagecount,
                    "limit": 20,
                    "total": total,
                    "list": items,
                }
                
            else:
                return {"page": page, "pagecount": 1, "limit": 20, "total": 0, "list": []}
                
        except Exception as e:
            print(f"[空中课堂] 分类内容异常: {e}")
            return {"page": page, "pagecount": 1, "limit": 20, "total": 0, "list": []}

    def _get_seyk_subject_list(self, stage_id):
        cache_key = f"stage_{stage_id}"
        if cache_key in self._stage_subject_cache:
            return self._stage_subject_cache[cache_key]
        
        items = []
        grade_list = self._get_grade_list(stage_id)
        
        for grade in grade_list:
            grade_id = grade.get("grade_id", "")
            grade_title = grade.get("grade_title", "")
            
            # 过滤掉"小学""初中""高中"
            grade_title = grade_title.replace("小学", "").replace("初中", "").replace("高中", "")
            
            subject_list = self._get_subject_list(stage_id, grade_id)
            for subject in subject_list:
                subject_id = subject.get("subject_id", "")
                subject_title = subject.get("subject_title", "")
                
                vod_id = f"sub_{stage_id}_{grade_id}_{subject_id}"
                vod_name = grade_title + subject_title
                
                video_count = len(self._get_video_list(stage_id, grade_id, subject_id))
                
                items.append({
                    "vod_id": vod_id,
                    "vod_name": vod_name,
                    "vod_pic": "",
                    "vod_remarks": f"{video_count}个视频" if video_count > 0 else "",
                    "vod_year": "",
                })
        
        self._stage_subject_cache[cache_key] = items
        return items

    def _get_video_list(self, stage_id, grade_id, subject_id):
        version_id = ""
        version_list = self._get_version_list(subject_id, grade_id)
        if version_list:
            version_id = version_list[0].get("version_id", "")

        params = {
            "subject_id": subject_id,
            "version_id": version_id,
            "volumn_id": "",
            "dir_id": "",
            "page": 1,
            "limit": 999,
            "grade_id": grade_id,
            "dir_level": "",
        }
        
        data = self._post("/seyk/resource/list/", params)
        videos = []
        if data.get("state") == 0:
            resource_list = data.get("data", {}).get("resource_list", [])
            for r in resource_list:
                videos.append({
                    "vod_id": f"seyk_{r.get('resource_id', '')}",
                    "vod_name": r.get("resource_title", ""),
                    "vod_pic": self._fix_url(r.get("seal_img", "")),
                    "vod_remarks": str(r.get("view", "")),
                    "vod_year": "",
                })
        return videos

    def detailContent(self, ids):
        vid = str(ids[0]) if isinstance(ids, list) else str(ids)
        
        if vid.startswith("sub_"):
            parts = vid.split("_")
            if len(parts) == 4:
                stage_id = parts[1]
                grade_id = parts[2]
                subject_id = parts[3]
                
                videos = self._get_video_list(stage_id, grade_id, subject_id)
                
                if not videos:
                    return {"list": []}
                
                grade_title = ""
                grade_list = self._get_grade_list(stage_id)
                for g in grade_list:
                    if g.get("grade_id") == grade_id:
                        grade_title = g.get("grade_title", "")
                        break
                
                subject_title = ""
                subject_list = self._get_subject_list(stage_id, grade_id)
                for s in subject_list:
                    if s.get("subject_id") == subject_id:
                        subject_title = s.get("subject_title", "")
                        break
                
                # 过滤掉"小学""初中""高中"
                grade_title = grade_title.replace("小学", "").replace("初中", "").replace("高中", "")
                
                title = grade_title + subject_title
                
                play_list = []
                for v in videos:
                    play_list.append(f"{v['vod_name']}${v['vod_id']}")
                
                if not play_list:
                    return {"list": []}
                
                return {
                    "list": [{
                        "vod_id": vid,
                        "vod_name": title,
                        "vod_pic": "",
                        "vod_content": f"{title} - 共{len(videos)}个视频",
                        "vod_remarks": f"{len(videos)}个视频",
                        "vod_play_from": "默认线路",
                        "vod_play_url": "#".join(play_list),
                    }]
                }
        
        try:
            module, resource_id = vid.split("_", 1)
        except ValueError:
            return {"list": []}

        if module == "seyk":
            data = self._post("/seyk/resource/detail/", {"resource_id": resource_id})
        elif module == "jzkt":
            data = self._post("/jzkt/resource/detail/", {"resource_id": resource_id})
        elif module == "xljk":
            data = self._post("/xljk/resource/detail/", {"resource_id": resource_id})
        else:
            return {"list": []}

        if data.get("state") != 0:
            return {"list": []}

        info = data.get("data", {}).get("resource_info", {})
        title = info.get("title", info.get("resource_title", ""))
        pic = self._fix_url(info.get("seal_img", info.get("thumb", "")))
        desc = info.get("description", info.get("article_content", ""))
        view = info.get("view", "")

        play_list = []
        sub_resources = info.get("sub_resources", []) or info.get("child_resources", [])
        if sub_resources:
            for idx, sub in enumerate(sub_resources):
                sub_id = sub.get("resource_id", sub.get("id", ""))
                sub_title = sub.get("resource_title", sub.get("title", f"第{idx+1}集"))
                if sub_id:
                    play_list.append(f"{sub_title}${module}_{sub_id}")

        if not play_list:
            play_list.append(f"播放${vid}")

        return {
            "list": [{
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_content": self._clean(desc),
                "vod_remarks": str(view),
                "vod_play_from": "默认线路",
                "vod_play_url": "#".join(play_list),
            }]
        }

    def _get_grade_list(self, stage_id):
        if stage_id not in self._grade_cache:
            data = self._post("/seyk/grade/list/", {"stage_id": stage_id})
            if data.get("state") == 0:
                self._grade_cache[stage_id] = data.get("data", {}).get("grade_list", [])
            else:
                self._grade_cache[stage_id] = []
        return self._grade_cache[stage_id]

    def _get_subject_list(self, stage_id, grade_id):
        if not grade_id:
            return []
        key = f"{stage_id}_{grade_id}"
        if key not in self._subject_cache:
            data = self._post("/seyk/subject/list/", {"stage_id": stage_id, "grade_id": grade_id})
            if data.get("state") == 0:
                self._subject_cache[key] = data.get("data", {}).get("subject_list", [])
            else:
                self._subject_cache[key] = []
        return self._subject_cache[key]

    def _get_version_list(self, subject_id, grade_id):
        if not subject_id or not grade_id:
            return []
        key = f"{subject_id}_{grade_id}"
        if key not in self._version_cache:
            data = self._post("/seyk/version/list/", {"subject_id": subject_id, "grade_id": grade_id})
            if data.get("state") == 0:
                self._version_cache[key] = data.get("data", {}).get("version_list", [])
            else:
                self._version_cache[key] = []
        return self._version_cache[key]

    def _get_jzkt_list_with_total(self, page=1, limit=20):
        params = {"page": page, "limit": limit}
        data = self._post("/jzkt/resource/list/", params)

        items = []
        total = 0
        if data.get("state") == 0:
            data_info = data.get("data", {})
            resource_list = data_info.get("resource_list", [])
            total = data_info.get("total", 0)
            for r in resource_list:
                items.append({
                    "vod_id": f"jzkt_{r.get('resource_id', '')}",
                    "vod_name": r.get("resource_title", ""),
                    "vod_pic": self._fix_url(r.get("seal_img", "")),
                    "vod_remarks": str(r.get("view", "")),
                    "vod_year": "",
                })
        return items, total

    def _get_xljk_list_with_total(self, page=1, limit=20):
        params = {"page": page, "limit": limit}
        data = self._post("/xljk/resource/list/", params)

        items = []
        total = 0
        if data.get("state") == 0:
            data_info = data.get("data", {})
            resource_list = data_info.get("resource_list", [])
            total = data_info.get("total", 0)
            for r in resource_list:
                items.append({
                    "vod_id": f"xljk_{r.get('resource_id', '')}",
                    "vod_name": r.get("resource_title", r.get("teacher_title", "")),
                    "vod_pic": self._fix_url(r.get("seal_img", "")),
                    "vod_remarks": str(r.get("view", "")),
                    "vod_year": "",
                })
        return items, total

    def playerContent(self, flag, id, vipFlags):
        vid = str(id or "")
        try:
            module, resource_id = vid.split("_", 1)
        except ValueError:
            return {"parse": 0, "url": "", "msg": "无效的资源ID"}

        if vid in self._play_url_cache:
            return {"parse": 0, "url": self._play_url_cache[vid], "header": self._play_headers()}

        if module == "seyk":
            detail_data = self._post("/seyk/resource/detail/", {"resource_id": resource_id})
        elif module == "jzkt":
            detail_data = self._post("/jzkt/resource/detail/", {"resource_id": resource_id})
        elif module == "xljk":
            detail_data = self._post("/xljk/resource/detail/", {"resource_id": resource_id})
        else:
            return {"parse": 0, "url": "", "msg": "未知的资源类型"}

        if detail_data.get("state") != 0:
            return {"parse": 0, "url": "", "msg": "获取资源详情失败"}

        info = detail_data.get("data", {}).get("resource_info", {})
        file_id = info.get("file_id", "")

        if not file_id:
            sub_resources = info.get("sub_resources", []) or info.get("video_list", [])
            for sub in sub_resources:
                if sub.get("file_id"):
                    file_id = sub.get("file_id")
                    break

        if not file_id:
            return {"parse": 0, "url": "", "msg": "无file_id"}

        vod_data = self._post("/base/vod/", {"file_id": file_id})
        if vod_data.get("state") != 0:
            return {"parse": 0, "url": "", "msg": "获取播放签名失败"}

        vod_info = vod_data.get("data", {})
        app_id = vod_info.get("app_id", "")
        psign = vod_info.get("psign", "")

        if not app_id or not psign:
            return {"parse": 0, "url": "", "msg": "无app_id或psign"}

        play_url = self._get_tencent_play_url(app_id, file_id, psign)
        if not play_url:
            return {"parse": 0, "url": "", "msg": "获取播放地址失败"}

        self._play_url_cache[vid] = play_url
        return {"parse": 0, "url": play_url, "header": self._play_headers()}

    def _get_tencent_play_url(self, app_id, file_id, psign):
        try:
            url = f"https://playvideo.qcloud.com/getplayinfo/v4/{app_id}/{file_id}?psign={psign}"
            headers = {
                "User-Agent": self.headers["User-Agent"],
                "Referer": self.host + "/",
                "Origin": self.host,
            }
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if data.get("code") == 0:
                    media = data.get("media", {}) or {}
                    streaming = media.get("streamingInfo", {}) or {}
                    adaptive = streaming.get("adaptiveDynamicStreamingInfo", {})
                    if adaptive and adaptive.get("url"):
                        return adaptive["url"]
                    plain = streaming.get("plainOutput", {})
                    if plain and plain.get("url"):
                        return plain["url"]
                    video_info = media.get("videoInfo", {}) or {}
                    source = video_info.get("sourceVideo", {})
                    if source and source.get("url"):
                        return source["url"]
                    transcode_list = video_info.get("transcodeList", [])
                    if transcode_list and transcode_list[0].get("url"):
                        return transcode_list[0]["url"]
        except Exception as e:
            print(f"[空中课堂] 获取腾讯云播放地址失败: {e}")
        return ""

    def _play_headers(self):
        return {
            "User-Agent": self.headers["User-Agent"],
            "Referer": self.host + "/",
            "Origin": self.host,
        }

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        try:
            decoded = unquote(str(key))
        except Exception:
            decoded = str(key)

        data = self._post("/search/", {
            "keyword": decoded,
            "page": page,
            "limit": 20,
        })

        items = []
        if data.get("state") == 0:
            resource_list = data.get("data", {}).get("resource_list", [])
            module_map = {"7": "seyk", "106": "jzkt", "3": "xljk"}
            for r in resource_list:
                res_id = r.get("res_id", "")
                module = str(r.get("module", ""))
                prefix = module_map.get(module, "seyk")
                items.append({
                    "vod_id": f"{prefix}_{res_id}",
                    "vod_name": r.get("res_title", ""),
                    "vod_pic": self._fix_url(r.get("seal_img", "")),
                    "vod_remarks": str(r.get("view", "")),
                    "vod_year": "",
                })

        return {
            "list": items,
            "page": page,
            "pagecount": 999,
            "limit": 20,
            "total": len(items),
        }

    def _fix_url(self, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.host + url
        return url

    def _clean(self, text):
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def localProxy(self, param):
        return [404, "text/plain", "", ""]

    def destroy(self):
        return "正在Destroy"