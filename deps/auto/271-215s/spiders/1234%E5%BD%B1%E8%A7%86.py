# coding=utf-8
import sys, re, json, ssl, gzip
import urllib.request as ur
from urllib.parse import unquote, quote
sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def __init__(self, extend=''):
            pass
        def fetch(self, url, headers=None, timeout=10):
            return ''

CTX=ssl._create_unverified_context()

class Spider(Spider):
    name='1234影视'
    host='https://www.1234sp.cc'
    ua='Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
    proxy='https://ttss.langfeng888.com'
    CATEGORIES={
        'A2xeflx0UY1tu':'连续剧',
        'A2mOC0y4HbZ3l':'电影',
        'A2ttqWI1YGgTu':'动漫',
        'A2b7iFz0ozYru':'综艺'
    }
    def __init__(self,extend=''):
        self.extend=extend
    def init(self,extend=''):
        if extend:self.extend=extend
        return True
    def getName(self):
        return self.name
    def _get(self,url,referer='',retry=2):
        for _ in range(retry):
            try:
                h={'User-Agent':self.ua,'Accept':'text/html,application/xhtml+xml,*/*','Accept-Encoding':'gzip'}
                if referer:h['Referer']=referer
                r=ur.urlopen(ur.Request(url,headers=h),timeout=15,context=CTX)
                b=r.read()
                if str(r.headers.get('Content-Encoding','')).lower()=='gzip':
                    try:b=gzip.decompress(b)
                    except Exception:pass
                return b.decode('utf-8','ignore')
            except Exception:
                continue
        return ''
    def _jget(self,url,referer=''):
        try:
            h={'User-Agent':self.ua,'Accept':'application/json'}
            if referer:h['Referer']=referer
            r=ur.urlopen(ur.Request(url,headers=h),timeout=15,context=CTX)
            return json.loads(r.read().decode('utf-8','ignore'))
        except Exception:
            return {}
    def _fix(self,u):
        return (u or '').replace('&amp;','&').strip()
    def _parse_list(self,html):
        out=[];seen=set()
        if not html:return out
        for m in re.finditer(r'<a\s[^<>]*href=["\'](/v/([^"\']+))\.html["\']([^>]*)>',html,re.I):
            href='/v/%s.html'%m.group(2)
            if href in seen:continue
            start=m.start();end=html.find('</a>',m.end())
            seg=html[start:end+4] if end>0 else html[start:m.end()+600]
            img=re.search(r'<img[^>]*src=["\']([^"\']+)["\']',seg,re.I)
            if not img:continue
            pic=self._fix(img.group(1))
            if not pic:continue
            name=''
            nm=re.search(r'alt=["\']([^"\']*)["\']',seg,re.I)
            if nm:name=nm.group(1)
            if not name:
                nm2=re.search(r'title=["\']([^"\']*)["\']',m.group(3),re.I)
                if nm2:name=nm2.group(1)
            rm=re.search(r'(更新至[^<>"\']*|全集|HD中字|TC中字|第\d+集|完结)',seg)
            seen.add(href)
            out.append({'vod_id':m.group(2),'vod_name':name.strip(),'vod_pic':pic,'vod_remarks':rm.group(1) if rm else ''})
        return out
    def homeContent(self,filter=False):
        return {'class':[{'type_id':k,'type_name':v} for k,v in self.CATEGORIES.items()],'filters':{}}
    def homeVideoContent(self):
        return {'list':self._parse_list(self._get(self.host+'/'))[:72]}
    def categoryContent(self,tid,pg='1',filter=False,extend=None):
        try:page=max(1,int(str(pg)))
        except Exception:page=1
        tid=str(tid or '').strip()
        if tid not in self.CATEGORIES:
            for k,v in self.CATEGORIES.items():
                if v==tid:tid=k;break
        html=self._get('%s/list/%s/%s.html'%(self.host,tid,page))
        items=self._parse_list(html)
        nxt=bool(re.search(r'href=["\'][^"\']*/%s/%d\.html["\']'%(re.escape(tid),page+1),html or ''))
        total=0
        tm=re.search(r'共\s*(\d+)\s*[部条]',html or '')
        if tm:total=int(tm.group(1))
        return {'list':items,'page':page,'pagecount':page+1 if nxt or len(items)>=20 else page,'limit':36,'total':total}
    def detailContent(self,ids):
        vid=str(ids[0] if isinstance(ids,list) else ids)
        vod={'vod_id':vid,'vod_name':'','vod_pic':'','vod_remarks':'','vod_year':'','vod_area':'','vod_director':'','vod_actor':'','vod_content':'','vod_play_from':'','vod_play_url':''}
        if not vid:return {'list':[vod]}
        html=self._get('%s/v/%s.html'%(self.host,vid))
        if not html:return {'list':[vod]}
        hm=re.search(r'<h1[^>]*>([^<>]+)</h1>',html,re.I)
        if hm:vod['vod_name']=hm.group(1).strip()
        if not vod['vod_name']:
            tm=re.search(r'<title>([^<>]+?)\s*(?:在线观看|-|\|)',html,re.I)
            if tm:vod['vod_name']=tm.group(1).strip()
        pm=re.search(r'<img[^>]*src=["\']([^"\']+)["\']',html,re.I)
        if pm:vod['vod_pic']=self._fix(pm.group(1))
        for k,pat in [('vod_director',r'<dt>导演</dt><dd>([^<]*)</dd>'),('vod_actor',r'<dt>主演</dt><dd>([^<]*)</dd>')]:
            m=re.search(pat,html)
            if m:vod[k]=m.group(1).strip()
        m=re.search(r'<dt>地区 / 年份</dt><dd>([^<]*?)\s*/\s*([^<]*)</dd>',html)
        if m:
            vod['vod_area']=m.group(1).strip();vod['vod_year']=m.group(2).strip()
        m=re.search(r'<dt>状态</dt><dd>([^<]*)</dd>',html)
        if m:vod['vod_remarks']=m.group(1).strip()
        line_map={};seen=set()
        for href,name in re.findall(r'href=["\'](/p/[^"\']*)["\'][^<>]*>([^<>]+)</a>',html):
            m=re.match(r'/p/%s/(\d+)/(\d+)\.html'%re.escape(vid),href)
            if not m or href in seen:continue
            seen.add(href)
            ln=m.group(1);ep=m.group(2);epn=name.strip()
            if not epn or epn=='\u7acb\u5373\u64ad\u653e':epn='第%02d集'%int(ep)
            line_map.setdefault(ln,[]).append((int(ep),epn,href))
        froms=[];urls=[]
        for ln in sorted(line_map.keys(),key=lambda x:int(x)):
            eps=sorted(line_map[ln],key=lambda x:x[0])
            froms.append('线路%s'%ln)
            urls.append('#'.join('%s$%s'%(e[1],e[2]) for e in eps))
        if froms:
            vod['vod_play_from']='$$$'.join(froms)
            vod['vod_play_url']='$$$'.join(urls)
        return {'list':[vod]}
    def searchContent(self,key,quick=False,pg='1'):
        try:page=max(1,int(str(pg)))
        except Exception:page=1
        k=str(key or '').strip()
        if not k:return {'list':[],'page':page}
        html=self._get('%s/?s=%s&page=%d'%(self.host,quote(k),page),referer=self.host+'/')
        items=self._parse_list(html)
        if not items:
            items=self._parse_list(self._get('%s/search/%s/%s.html'%(self.host,quote(k),page),referer=self.host+'/'))
        return {'list':items,'page':page}
    def playerContent(self,flag,id,vipFlags=None):
        h={'User-Agent':self.ua}
        pid=str(id or '')
        if not pid.startswith('/p/'):
            return {'parse':0,'url':pid,'header':h}
        page=self.host+pid
        html=self._get(page,referer=self.host+'/')
        m=re.search(r'<iframe[^>]*src=["\']([^"\']+)["\']',html or '',re.I)
        if not m:
            return {'parse':1,'url':page,'header':h}
        src=self._fix(m.group(1))
        if not src.startswith('http'):
            src='https:'+src if src.startswith('//') else self.host+src
        vm=re.search(r'[?&]v=([^&]+)',src)
        if vm and 'proxy/' not in src:
            d=self._jget('%s/proxy/%s'%(self.proxy,vm.group(1)))
            u=self._fix(str(d.get('url','') or ''))
            if u:
                return {'parse':0,'url':u,'header':h}
            return {'parse':1,'url':src,'header':h}
        um=re.search(r'[?&]url=([^&]+)',src)
        if um:
            return {'parse':0,'url':unquote(self._fix(um.group(1))),'header':h}
        return {'parse':1,'url':src,'header':h}
    def isVideoFormat(self,url):
        u=str(url or '').lower()
        return any(u.endswith(x) for x in ['.m3u8','.mp4','.ts','.flv','.mkv']) or u.endswith('/')
    def manualVideoCheck(self):
        return False
    def localProxy(self,param):
        return [404,'text/plain','']
    def destroy(self):
        pass