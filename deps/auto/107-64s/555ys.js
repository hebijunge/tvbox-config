// 555影视 v2 - 完善请求头，绕过反爬
var rule = {
  title: '555影视',
  host: 'https://555yy9.com',
  模板: 'mxpro',
  class_parse: '.nav.navbar-nav li:gt(0):lt(4);a&&Text;a&&href;/(\d+).html',
  推荐: '.module-items .module-poster-item;a&&href;a&&title;.module-poster-item img&&data-original',
  一级: '.module-items .module-poster-item;a&&href;a&&title;.module-poster-item img&&data-original',
  二级: {
    title: '.module-info-title&&Text',
    img: '.module-info-img img&&src',
    desc: '.module-info-item:eq(5) .module-info-item-content&&Text;.module-info-item:eq(4) .module-info-item-content&&Text;.module-info-tag-link:eq(1)&&Text;.module-info-item:eq(3) .module-info-item-content&&Text;.module-info-item:eq(1) .module-info-item-content&&Text',
    content: '.module-info-item:eq(0) .module-info-item-content&&Text',
    tabs: '.module-tab-item&&Text',
    lists: '.module-play-list li a'
  },
  搜索: '.module-items .module-poster-item;a&&href;a&&title;.module-poster-item img&&data-original',
  搜索页: '/index.php/vod/search/page/1/wd/***.html',
  播放配置: 'player_aaaa',
  播放解析: 'json',
  下载: 'm3u8',
  headers:{
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer':'https://555yy9.com/',
  },
};