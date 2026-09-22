var rule = {
    title: 'NT动漫',
    host: 'https://www.ntdm.tv',
    homeUrl: '/',
    url: '/show/fyclassfyfilter.html',
    // 自动解析导航栏分类
    class_parse: '.nav_list li:gt(0);a&&Text;a&&href;.*/(.*?)\.html',
    searchUrl: '/search/**----------fypage---.html',
    searchable: 2,
    quickSearch: 0,
    headers: {
        'User-Agent': 'MOBILE_UA',
        'Referer': 'https://www.ntdm.tv/',
    },
    
    // 筛选参数（根据网站URL结构：/show/分类--排序-剧情--字母---页码---年份.html）
    filter_url: '--{{fl.by}}-{{fl.class}}--{{fl.letter}}---fypage---{{fl.year}}',
    filter: {
        "riben": [
            {"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}, {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"}]},
            {"key": "by", "name": "排序", "value": [{"n": "时间", "v": "time"}, {"n": "人气", "v": "hits"}, {"n": "评分", "v": "score"}]}
        ]
    },

    // 一级列表：修正选择器以匹配 111.txt 源码
    一级: '.anime_list li.anime_icon1; .anime_icon1_name&&Text; img&&src; .anime_icon1_name1&&Text; a&&href',

    // 二级详情：修正选择器以匹配 222.txt 源码
    二级: {
        title: 'h1&&Text',
        img: '.video-cover img&&src',
        desc: '.video_info_item:eq(2)&&Text;;;.video_info_item:eq(1)&&Text;.video_info_item:eq(0)&&Text',
        content: '.video_info_content&&Text',
        // 播放源选项卡
        tabs: '.pannel_head h3', 
        // 播放列表：匹配 33.txt 里的 .mov_list li
        lists: '.mov_list:eq(#mindex) li'
    },

    // 搜索解析：匹配 444.txt 源码
    搜索: '.anime_list li.anime_icon1; .anime_icon1_name&&Text; img&&src; .anime_icon1_name1&&Text; a&&href',
}