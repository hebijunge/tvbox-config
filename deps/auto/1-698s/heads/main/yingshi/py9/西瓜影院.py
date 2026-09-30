#!/usr/bin/python
# -*- coding: utf-8 -*-
import re, json, requests
from urllib.parse import quote
from base.spider import Spider

class Spider(Spider):
    def getName(self): return "百站资源"
    def init(self, extend=""):
        self.host="https://www.bzzdyy.com"
        self.api=self.host+"/api.php/provide/vod/"
        self.headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Referer":self.host+"/"}
        self.session=requests.Session()
        self.session.headers.update(self.headers)
        self.cache={}
        self.classes=[{"type_id":"20","type_name":"电影"},{"type_id":"37","type_name":"连续剧"},{"type_id":"43","type_name":"动漫"},{"type_id":"45","type_name":"综艺"},{"type_id":"47","type_name":"B站"},{"type_id":"52","type_name":"短剧"},{"type_id":"60","type_name":"人人专区"},{"type_id":"35","type_name":"纪录片"}]
        self.alias={"20":["62","21","22","23","24","25","26","27","28","29","30","31","32","33","34","36","50"],"37":["61","38","39","40","41","42","51"],"43":["63","44","48","49"],"45":["64","46"],"47":["48","49","50","51"],"52":["65","53","54","55","56","57","58","59"],"60":["61","62","63","64","65","66"],"35":["66","35"]}
    def _get(self,url):
        if url in self.cache: return self.cache[url]
        try:
            r=self.session.get(url,timeout=7,verify=False)
            r.encoding="utf-8"
            d=r.json()
        except Exception:
            d={}
        if len(self.cache)>80: self.cache.clear()
        self.cache[url]=d
        return d
    def _fix(self,u):
        u=(u or "").strip().replace("\\/","/")
        return "https:"+u if u.startswith("//") else u
    def _bad_pic(self,u):
        u=(u or "").lower()
        return (not u) or "img.bwcgee.cn" in u
    def _item(self,v):
        p=self._fix(v.get("vod_pic_thumb") or v.get("vod_pic_slide") or v.get("vod_pic") or "")
        if self._bad_pic(p): return None
        return {"vod_id":str(v.get("vod_id","")),"vod_name":v.get("vod_name",""),"vod_pic":p,"vod_remarks":v.get("vod_remarks") or v.get("vod_version") or v.get("vod_state") or ""}
    def _list_one(self,tid,pg):
        for ac in ["detail","videolist","list"]:
            d=self._get(self.api+"?ac=%s&t=%s&pg=%s"%(ac,tid,pg))
            if d.get("list"): return d
        return {}
    def _list(self,tid,pg,limit=18):
        ids=self.alias.get(str(tid),[str(tid)])
        arr=[]; seen=set(); pagecount=1; total=0
        for t in ids:
            d=self._list_one(t,pg)
            pagecount=max(pagecount,int(d.get("pagecount") or 1))
            total+=int(d.get("total") or 0)
            for v in d.get("list",[]):
                it=self._item(v)
                if not it or it["vod_id"] in seen: continue
                seen.add(it["vod_id"])
                arr.append(it)
                if len(arr)>=limit: return arr,pagecount,total
        return arr,pagecount,total
    def homeContent(self,filter):
        arr,_,_=self._list("20","1",12)
        return {"class":self.classes,"list":arr,"filters":{}}
    def categoryContent(self,tid,pg,filter,extend):
        arr,pagecount,total=self._list(tid,pg,18)
        return {"page":int(pg),"pagecount":pagecount,"limit":18,"total":total,"count":len(arr),"list":arr}
    def detailContent(self,ids):
        d=self._get(self.api+"?ac=detail&ids="+str(ids[0]))
        rs=[]
        for v in d.get("list",[]):
            pic=self._fix(v.get("vod_pic") or v.get("vod_pic_thumb") or v.get("vod_pic_slide") or "")
            play_from=[]; play_url=[]
            fs=(v.get("vod_play_from") or "").split("$$$")
            us=(v.get("vod_play_url") or "").split("$$$")
            for i,u in enumerate(us):
                eps=[]
                for e in u.split("#"):
                    if "$" not in e: continue
                    n,a=e.split("$",1)
                    a=self._fix(a)
                    if a: eps.append((n or "播放")+"$"+a)
                if eps:
                    play_from.append(fs[i] if i<len(fs) and fs[i] else "播放")
                    play_url.append("#".join(eps))
            vod={"vod_id":str(v.get("vod_id","")),"vod_name":v.get("vod_name",""),"vod_pic":pic,"type_name":v.get("type_name",""),"vod_year":v.get("vod_year",""),"vod_area":v.get("vod_area",""),"vod_remarks":v.get("vod_remarks") or v.get("vod_version") or v.get("vod_state") or "","vod_actor":v.get("vod_actor",""),"vod_director":v.get("vod_director",""),"vod_content":re.sub(r"<[^>]+>","",v.get("vod_content") or v.get("vod_blurb") or ""),"vod_play_from":"$$$".join(play_from),"vod_play_url":"$$$".join(play_url)}
            rs.append(vod)
        return {"list":rs}
    def searchContent(self,key,quick,pg="1"):
        d=self._get(self.api+"?ac=detail&wd="+quote(key)+"&pg="+str(pg))
        arr=[]
        for v in d.get("list",[]):
            it=self._item(v)
            if it: arr.append(it)
        return {"page":int(pg),"pagecount":int(d.get("pagecount") or 1),"limit":int(d.get("limit") or 20),"total":int(d.get("total") or len(arr)),"list":arr}
    def playerContent(self,flag,id,vipFlags):
        url=self._fix(id)
        h={"User-Agent":self.headers["User-Agent"],"Referer":self.host+"/"}
        if ".qq.com" in url: h["Referer"]="https://v.qq.com/"
        if ".youku.com" in url: h["Referer"]="https://v.youku.com/"
        if ".iqiyi.com" in url: h["Referer"]="https://www.iqiyi.com/"
        if ".mgtv.com" in url: h["Referer"]="https://www.mgtv.com/"
        if re.search(r"\.(m3u8|mp4|flv|mp3)(\?|$)",url): return {"parse":0,"url":url,"header":h}
        return {"parse":1,"url":url,"header":h}