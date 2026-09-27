// 秋霞影院 qiuxia001.com
var rule = {
    title: '秋霞',
    host: 'https://qiuxia001.com',
    url: '/qiu/fyclass/fypage/',
    searchUrl: '/search/-------------/?wd=fykey',
    headers: {
        'User-Agent': 'MOBILE_UA'
    },
    class_name: '电影&连续剧&综艺&动漫&短剧&理论片',
    class_url: '1&2&3&4&27&20',
    class_parse: '.nav li a;Text;href;/qiu/(\\d+)/',
    二级: {
        title: 'h2.text-overflow&&Text',
        img: '.video-pic&&data-original;.lazyload&&data-original',
        desc: '.score&&Text;.note&&Text',
        content: '.detail-content&&Text;.content&&Text',
        tabs: `js:
pdfh=jsp.pdfh;pdfa=jsp.pdfa;pd=jsp.pd;
TABS=[];
let d=pdfa(html,'.wi-play-list-box');
d.forEach(function(it,idx){
    let name=pdfh(it,'h3&&Text').trim();
    if(!name) name='线路'+(idx+1);
    TABS.push(name);
});
if(TABS.length==0){
    let all=pdfa(html,'a[href*="/qxp/"]');
    if(all.length>0) TABS=['默认线路'];
}
log('qiuxia TABS:'+JSON.stringify(TABS));
`,
        lists: `js:
pdfh=jsp.pdfh;pdfa=jsp.pdfa;pd=jsp.pd;
LISTS=[];
let d=pdfa(html,'.wi-play-list-box');
d.forEach(function(it,idx){
    let list=[];
    let urls=pdfa(it,'.wi-play-list-content a');
    urls.forEach(function(a){
        let name=pdfh(a,'Text').trim();
        let href=pd(a,'href',HOST);
        if(name && href && href.indexOf('/qxp/')>=0){
            list.push(name+'$'+href);
        }
    });
    if(list.length>0) LISTS.push(list);
});
if(LISTS.length==0){
    let all=pdfa(html,'a[href*="/qxp/"]');
    let list=[];
    let seen={};
    all.forEach(function(a){
        let name=pdfh(a,'Text').trim();
        let href=pd(a,'href',HOST);
        if(name && href && !seen[href]){
            seen[href]=1;
            list.push(name+'$'+href);
        }
    });
    if(list.length>0) LISTS.push(list);
}
log('qiuxia LISTS:'+LISTS.length+' lines');
`
    },
    一级: 'ul.item li;.title h5&&Text;.video-pic&&data-original;.score&&Text;.video-pic&&href',
    搜索: {
        title: '.video-pic&&title',
        img: '.video-pic&&data-original',
        desc: '.note&&Text',
        url: '.video-pic&&href'
    },
    play_js: `js:
pdfh=jsp.pdfh;pdfa=jsp.pdfa;pd=jsp.pd;
let m=html.match(/player_aaaa\\s*=\\s*(\\{[\\s\\S]*?\\})/);
if(m){
    try{
        let obj=JSON.parse(m[1]);
        if(obj.url){
            log('qiuxia play url:'+obj.url);
            result=obj.url;
        }
    }catch(e){
        log('qiuxia parse error:'+e);
    }
}
if(!result){
    let m2=html.match(/"url"\\s*:\\s*"([^"]+\\.m3u8[^"]*)"/);
    if(m2){
        result=m2[1].replace(/\\\\\\//g,'/');
        log('qiuxia play url2:'+result);
    }
}
`
}
