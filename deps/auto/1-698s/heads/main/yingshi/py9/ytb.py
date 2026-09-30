#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Isis Fashion Awards - TVBox / FongMi Python Plugin
频道: https://www.youtube.com/@IsisFashionAwards
"""

import json

class Spider:
    def __init__(self):
        self.siteUrl = "https://www.youtube.com"
        self.channelId = "@IsisFashionAwards"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.youtube.com/"
        }
        self.channel_name = "Isis Fashion Awards"
        self.channel_pic = "https://yt3.googleusercontent.com/ytc/AIdro_kIN6uBmWVfTujWwGBKZeYfLrdLVYxK1nYwtmwA9TPy_4k=s160-c-k-c0x00ffffff-no-rj"
        self.channel_desc = "Isis Fashion Awards - Fashion Show Accessory Designers Runway Models Catwalk TV International\nhttps://isisfashionawards.com"
        
        self.videos = [
            {"id": "oI9ftxYlDoU", "title": "Isis Fashion Awards 2026 Part 1 Opening Speech (Nude Accessory Runway Catwalk Isis Show)", "duration": "4:04", "cat": "2026", "thumb": "https://i.ytimg.com/vi/oI9ftxYlDoU/hqdefault.jpg"},
            {"id": "-AReqaFzpxg", "title": "Isis Fashion Awards 2026 Part 2 Ballet Opening (Nude Accessory Runway Catwalk Isis Show)", "duration": "2:40", "cat": "2026", "thumb": "https://i.ytimg.com/vi/-AReqaFzpxg/hqdefault.jpg"},
            {"id": "m0iRO7dU2Zc", "title": "Isis Fashion Awards 2026 Part 3 (Nude Accessory Runway Catwalk Show) FreeStyle Up", "duration": "4:39", "cat": "2026", "thumb": "https://i.ytimg.com/vi/m0iRO7dU2Zc/hqdefault.jpg"},
            {"id": "6D19aQnWL_8", "title": "Isis Fashion Awards 2026 Part 14 Naked Art Auction (Nude Painting)", "duration": "3:46", "cat": "auction", "thumb": "https://i.ytimg.com/vi/6D19aQnWL_8/hqdefault.jpg"},
            {"id": "IVJP4lGEqWc", "title": "Isis Fashion Awards 2026 Part 15 Naked Art Auction (Nude Painting)", "duration": "2:41", "cat": "auction", "thumb": "https://i.ytimg.com/vi/IVJP4lGEqWc/hqdefault.jpg"},
            {"id": "qAy8rmF7gu0", "title": "Isis Fashion Awards 2026 Part 16 Naked Art Auction (Nude Painting Brigitte Bardot)", "duration": "4:09", "cat": "auction", "thumb": "https://i.ytimg.com/vi/qAy8rmF7gu0/hqdefault.jpg"},
            {"id": "IZh8SUjZj2U", "title": "Isis Fashion Awards 2025 - Part 1 (Nude Accessory Runway Catwalk Isis Show) Quattuor Gemmis", "duration": "2:55", "cat": "2025", "thumb": "https://i.ytimg.com/vi/IZh8SUjZj2U/hqdefault.jpg"},
            {"id": "s0FGdfSlxlk", "title": "Isis Fashion Awards 2025 - Part 2 (Nude Accessory Runway Catwalk Isis Show) Suzan Studio", "duration": "4:08", "cat": "2025", "thumb": "https://i.ytimg.com/vi/s0FGdfSlxlk/hqdefault.jpg"},
            {"id": "kq8F5BTazc8", "title": "Isis Fashion Awards 2025 - Part 3 (Nude Accessory Runway Isis Show) ALTER by Sanghee Moon (Ingrid)", "duration": "4:14", "cat": "2025", "thumb": "https://i.ytimg.com/vi/kq8F5BTazc8/hqdefault.jpg"},
            {"id": "Gnr4MZYnF-I", "title": "Isis Fashion Awards 2025 - Part 12 (Nude Accessory Runway Catwalk Isis Show) Odinski Jewels", "duration": "5:16", "cat": "2025", "thumb": "https://i.ytimg.com/vi/Gnr4MZYnF-I/hqdefault.jpg"},
            {"id": "DTBpSYU5Aq0", "title": "Isis Fashion Awards 2025 - Part 13 (Nude Accessory Runway Show) Prinses Margarita - De Parme Design", "duration": "5:13", "cat": "2025", "thumb": "https://i.ytimg.com/vi/DTBpSYU5Aq0/hqdefault.jpg"},
            {"id": "sdt7KcHmskA", "title": "Isis Fashion Awards 2025 - Part 14 (Nude Accessory Runway Catwalk Isis Show) Award Ceremony", "duration": "7:21", "cat": "2025", "thumb": "https://i.ytimg.com/vi/sdt7KcHmskA/hqdefault.jpg"},
            {"id": "jXt_lio-3Do", "title": "Isis Fashion Awards 2024 - Part 1 (Nude Accessory Runway Catwalk Isis Show) ANNIGJE", "duration": "3:25", "cat": "2024", "thumb": "https://i.ytimg.com/vi/jXt_lio-3Do/hqdefault.jpg"},
            {"id": "dTyTiVW1Y0g", "title": "Isis Fashion Awards 2024 Part 2 (Nude Accessory Runway Catwalk Isis Show) Vanihila", "duration": "3:17", "cat": "2024", "thumb": "https://i.ytimg.com/vi/dTyTiVW1Y0g/hqdefault.jpg"},
            {"id": "G-o-f4GBkxI", "title": "Isis Fashion Awards 2024 - Part 3 (Nude Accessory Runway Catwalk Isis Show) Obiaocha Designs", "duration": "4:00", "cat": "2024", "thumb": "https://i.ytimg.com/vi/G-o-f4GBkxI/hqdefault.jpg"},
            {"id": "1cmV1UM6_ys", "title": "Isis Fashion Awards 2022 - Part 1 (Nude Accessory Runway Catwalk Show) The New Tribe", "duration": "6:02", "cat": "2022", "thumb": "https://i.ytimg.com/vi/1cmV1UM6_ys/hqdefault.jpg"},
            {"id": "draP5nH_WXk", "title": "Isis Fashion Awards 2022 - Part 2 (Nude Accessory Runway Catwalk Show) Global Hats", "duration": "4:57", "cat": "2022", "thumb": "https://i.ytimg.com/vi/draP5nH_WXk/hqdefault.jpg"},
            {"id": "LkpTshwskgg", "title": "Isis Fashion Awards 2022 - Part 8 (Nude Accessory Runway Catwalk Show) MukaCariza", "duration": "5:50", "cat": "2022", "thumb": "https://i.ytimg.com/vi/LkpTshwskgg/hqdefault.jpg"},
            {"id": "v_Y_VHQ6duk", "title": "Patreon Members (Join!) Exclusive Access Behind The Scenes - Isis Fashion Awards", "duration": "0:57", "cat": "bts", "thumb": "https://i.ytimg.com/vi/v_Y_VHQ6duk/hqdefault.jpg"},
            {"id": "aHf_2Jcnits", "title": "Patreon Membership - Behind the Scenes Videos Available Now!", "duration": "1:17", "cat": "bts", "thumb": "https://i.ytimg.com/vi/aHf_2Jcnits/hqdefault.jpg"},
            {"id": "D80joQeF30k", "title": "Esme Cordus Interview Preview Teaser - Isis Fashion Awards Backstage Behind The Scenes BTS 2025", "duration": "0:42", "cat": "bts", "thumb": "https://i.ytimg.com/vi/D80joQeF30k/hqdefault.jpg"},
            {"id": "KFMC5DMFRaA", "title": "Brooklyn Haydar - How Old Is She? Interview Model Red Carpet Interview Isis Fashion Awards Show", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/KFMC5DMFRaA/hqdefault.jpg"},
            {"id": "mxiuSTyBg7k", "title": "Vanessa Bartsch & AuroraK Foxy Liliac Interview Model Red Carpet Interview Isis Fashion Awards Show", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/mxiuSTyBg7k/hqdefault.jpg"},
            {"id": "AW6eq04rRok", "title": "Laura Giraudi Interview - Is She Single?... Isis Fashion Awards Show 2026 Red Carpet", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/AW6eq04rRok/hqdefault.jpg"},
            {"id": "KegOg4DVW_o", "title": "Isis Fashion Awards 2026 (Isis Show) Jury Interview Miryam Ish", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/KegOg4DVW_o/hqdefault.jpg"},
            {"id": "hDsXto0ncZY", "title": "Models Of Isis Fashion Awards 2026 (Isis Show)", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/hDsXto0ncZY/hqdefault.jpg"},
            {"id": "QBitdNfNK9Y", "title": "Isis Fashion Awards 2026! Tickets Available Now! Announcement! (Isis Show)", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/QBitdNfNK9Y/hqdefault.jpg"},
            {"id": "UNXNkfBeSUw", "title": "Donnalyn Bartolome - Isis Fashion Awards 2025 (Isis Show) Red Carpet Judge Jury", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/UNXNkfBeSUw/hqdefault.jpg"},
            {"id": "hXPlPa0TSgs", "title": "Autumn Noel - Isis Fashion Awards 2025 (Isis Show) Red Carpet Judge Jury", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/hXPlPa0TSgs/hqdefault.jpg"},
            {"id": "R8TaJBRq0A4", "title": "De Parme Design Princess Prinses Margarita de Bourbon - Isis Fashion Awards 2025 (Isis Show) Winner", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/R8TaJBRq0A4/hqdefault.jpg"},
            {"id": "35VTCMPRtsw", "title": "How To Join and Become Member Of The Isis Fashion Awards?", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/35VTCMPRtsw/hqdefault.jpg"},
            {"id": "Eq8pvW3at90", "title": "How To Model For The Isis Fashion Awards Model?", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/Eq8pvW3at90/hqdefault.jpg"},
            {"id": "PK2-YAL_gD4", "title": "Isis Fashion Awards Named Explained", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/PK2-YAL_gD4/hqdefault.jpg"},
            {"id": "N-sYqma4H6I", "title": "How To Buy Tickets To Isis Fashion Awards?", "duration": "Short", "cat": "shorts", "thumb": "https://i.ytimg.com/vi/N-sYqma4H6I/hqdefault.jpg"},
        ]
        
        self.categories = [
            {"type_id": "all", "type_name": "全部视频"},
            {"type_id": "2026", "type_name": "2026系列"},
            {"type_id": "2025", "type_name": "2025系列"},
            {"type_id": "2024", "type_name": "2024系列"},
            {"type_id": "2022", "type_name": "2022系列"},
            {"type_id": "auction", "type_name": "艺术拍卖"},
            {"type_id": "bts", "type_name": "幕后花絮"},
            {"type_id": "shorts", "type_name": "Shorts"},
        ]
    
    def getName(self):
        return self.channel_name
    
    def init(self, extend=""):
        pass
    
    def isVideoFormat(self, url):
        return False
    
    def manualVideoCheck(self):
        return False
    
    def _video_to_vod(self, v):
        return {
            "vod_id": v["id"],
            "vod_name": v["title"],
            "vod_pic": v["thumb"],
            "vod_remarks": v["duration"],
            "vod_content": v["title"],
            "vod_tag": "file"
        }
    
    def homeContent(self, filter):
        result = {}
        result["class"] = self.categories
        videos = []
        for v in self.videos:
            videos.append(self._video_to_vod(v))
        result["list"] = videos
        return result
    
    def categoryContent(self, tid, pg, filter, extend):
        result = {}
        videos = []
        for v in self.videos:
            if tid == "all" or v["cat"] == tid:
                videos.append(self._video_to_vod(v))
        result["list"] = videos
        result["page"] = 1
        result["pagecount"] = 1
        result["limit"] = len(videos)
        result["total"] = len(videos)
        return result
    
    def detailContent(self, ids):
        result = {}
        videos = []
        for vid in ids:
            for v in self.videos:
                if v["id"] == vid:
                    play_url = f"{v['title']}${v['id']}"
                    videos.append({
                        "vod_id": v["id"],
                        "vod_name": v["title"],
                        "vod_pic": v["thumb"],
                        "vod_remarks": v["duration"],
                        "vod_content": f"{self.channel_desc}\n\n{v['title']}",
                        "vod_play_from": "YouTube",
                        "vod_play_url": play_url
                    })
                    break
        result["list"] = videos
        return result
    
    def playerContent(self, flag, id, vipFlags):
        result = {}
        result["parse"] = 1
        result["url"] = f"https://www.youtube.com/watch?v={id}"
        result["header"] = json.dumps(self.headers)
        return result
    
    def searchContent(self, key, quick):
        result = {}
        videos = []
        key_lower = key.lower()
        for v in self.videos:
            if key_lower in v["title"].lower():
                videos.append(self._video_to_vod(v))
        result["list"] = videos
        return result
    
    def searchContentPage(self, key, quick, pg):
        return self.searchContent(key, quick)
    
    def localProxy(self, param):
        return [200, "video/MP2T", "", ""]


if __name__ == "__main__":
    spider = Spider()
    print(json.dumps(spider.homeContent(None), ensure_ascii=False, indent=2))
