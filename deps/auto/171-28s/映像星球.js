// 映像星球 v13 - 完善JavaScript二级配置，添加主演导演年份地区简介
var rule = {
  title: '映像星球',
  host: 'https://www.yxxq35.cc',
  homeUrl: 'https://www.yxxq35.cc/',
  url: '/top/fyclass--------fypage---.html',
  class_name: '电影&电视剧&综艺&动漫&短剧',
  class_url: '1&2&3&4&5',
  推荐: '.module-poster-item;a&&title;img&&data-original;.module-item-note&&Text;a&&href',
  一级: '.module-poster-item;a&&title;img&&data-original;.module-item-note&&Text;a&&href',
  二级: 'js:try{var h=request(input);var hs=String(h);var title="";var m=hs.match(/<h1[^>]*>([\\s\\S]*?)<\\/h1>/);if(m)title=m[1].replace(/<[^>]+>/g,"").trim();var pic="";m=hs.match(/<img[^>]*data-original="([^"]+)"[^>]*>/);if(m)pic=m[1];if(pic&&pic.indexOf("//")===0)pic="https:"+pic;var items=hs.match(/<div[^>]*class="module-info-item[^"]*"[^>]*>([\\s\\S]*?)<\\/div>/g)||[];var director="";var actor="";var year="";var area="";var remarks="";var content="";for(var i=0;i<items.length;i++){var txt=items[i].replace(/<[^>]+>/g,"").trim();if(txt.indexOf("导演：")===0)director=txt.substring(3).replace(/\\/$/,"").trim();else if(txt.indexOf("主演：")===0)actor=txt.substring(3).replace(/\\/$/,"").trim();else if(txt.indexOf("上映：")===0){var dt=txt.substring(3);var ym=dt.match(/(\\d{4})/);if(ym)year=ym[1];var am=dt.match(/\\(([^)]+)\\)/);if(am)area=am[1];}else if(txt.indexOf("集数：")===0)remarks=txt.substring(3).trim();else if(txt.indexOf("更新：")===0){if(!remarks)remarks=txt.substring(3).trim();}else if(txt.length>50&&txt.indexOf("详情页")>=0){content=txt;}}if(!content){var cm=hs.match(/<div[^>]*class="module-info-content"[^>]*>([\\s\\S]*?)<\\/div>/);if(cm)content=cm[1].replace(/<[^>]+>/g,"").trim();}var pf=[];var tabMatches=hs.match(/<div[^>]*class="module-tab-item[^"]*"[^>]*>[\\s\\S]*?<span[^>]*>([\\s\\S]*?)<\\/span>/g);if(tabMatches){for(var ti=0;ti<tabMatches.length;ti++){var tm=tabMatches[ti].match(/<span[^>]*>([\\s\\S]*?)<\\/span>/);if(tm){var sn=tm[1].replace(/<[^>]+>/g,"").trim();if(sn)pf.push(sn);}}}if(pf.length===0)pf.push("默认线路");var listHtml="";m=hs.match(/id="panel1"[^>]*>([\\s\\S]*?)<\\/div>\\s*<\\/div>\\s*<\\/div>/);if(!m)m=hs.match(/id="panel1"[^>]*>([\\s\\S]*?)<\\/div>/);if(m)listHtml=m[1];var linkMatches=listHtml.match(/<a[^>]*class="module-play-list-link"[^>]*href="([^"]+)"[^>]*>[\\s\\S]*?<span[^>]*>([\\s\\S]*?)<\\/span>/g);var ll=[];if(linkMatches){for(var j=0;j<linkMatches.length;j++){var lm=linkMatches[j].match(/href="([^"]+)"[\\s\\S]*?<span[^>]*>([\\s\\S]*?)<\\/span>/);if(lm){var epName=lm[2].replace(/<[^>]+>/g,"").trim();var epUrl=lm[1];if(epUrl&&epUrl.indexOf("http")!==0)epUrl="https://www.yxxq35.cc"+epUrl;ll.push(epName+"$"+epUrl);}}}if(ll.length===0)ll.push("暂无$");var pu=[];for(var k=0;k<pf.length;k++){pu.push(ll.join("#"));}VOD={vod_name:title||"无标题",vod_pic:pic,vod_year:year,vod_area:area,vod_actor:actor,vod_director:director,vod_remarks:remarks,vod_content:content||"暂无简介",vod_play_from:pf.join("$$$"),vod_play_url:pu.join("$$$")};}catch(e){VOD={vod_name:"详情错误:"+e.message,vod_play_from:"错误$$$",vod_play_url:"错$"+e.message};}',
  搜索: '.module-item;img&&alt;img&&data-original;.module-item-note&&Text;a&&href',
  searchUrl: '/search/**-------------.html',
  播放配置: 'player_aaaa',
  播放解析: 'json',
  下载: 'm3u8',
  headers:{
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer':'https://www.yxxq35.cc/',
  },
};
