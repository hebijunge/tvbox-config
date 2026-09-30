// 大米星球 v19 - 改用/vodshow/页面（电视剧库），有完整分页按钮，解决翻页问题
var rule = {
    title:'大米星球',
    host:'https://dmxq7.com',
    homeUrl:'https://dmxq7.com/',
    url:'/vodshow/fyclass--------fypage---.html',
    detailUrl:'/voddetail/fyid.html',
    searchUrl:'/vodsearch/**-------------.html',
    class_url:'20&21&36&22&23',
    class_name:'电影&电视剧&短剧&动漫&综艺',
    一级:'.module-items .module-item;a&&title;.lazyload&&data-original;.module-item-note&&Text;a&&href',
    推荐:'.module-items .module-item;a&&title;.lazyload&&data-original;.module-item-note&&Text;a&&href',
    二级: {
        title: 'h1&&Text',
        img: '.module-item-pic img&&data-original',
        desc: '.module-info-item:eq(1)&&Text;.module-info-item:eq(3)&&Text;.module-info-item:eq(4)&&Text;.module-info-item:eq(5)&&Text',
        content: '.module-info-introduction-content&&Text',
        tabs: '.module-tab-item',
        tab_text: '&&Text',
        lists: '.module-play-list-link',
        list_text: '&&Text',
        list_url: 'a&&href'
    },
    搜索: '.module-items .module-item;a&&title;.lazyload&&data-original;.module-item-note&&Text;a&&href',
    headers:{
        'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer':'https://dmxq7.com/',
    },
    play_parse:true,
    lazy:'js:try{let html=fetch(input,fetch_params);let m=html.match(/player_aaaa\\s*=\\s*(\\{.*?\\})/);if(m){let d=JSON.parse(m[1]);let u=d.url;if(d.encrypt=="1"){u=unescape(u)}else if(d.encrypt=="2"){u=unescape(base64Decode(u))}if(/m3u8|mp4|flv/.test(u)){input=u}}}catch(e){}',
}
