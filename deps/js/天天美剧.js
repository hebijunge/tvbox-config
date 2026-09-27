// ==UserScript==
// @name         451dy 天天美剧
// @namespace    https://451dy.com
// @version      1.0.0
// @description   天天美剧 ESM 爬虫 - 电影/连续剧/综艺/动漫/短剧 含子分类筛选
// @author       DuMate
// ==/UserScript==

// {"siteName":"天天美剧","siteUrl":"https://451dy.com"}

import cheerio from 'assets://js/lib/cheerio.min.js';

// ============================ appConfig ============================
const appConfig = {
    siteName: '天天美剧',
    siteUrl: 'https://451dy.com',
    version: '1.0.0',
    ua: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
};

// ============================ classList ============================
const classList = [
    { type_id: 1, type_name: '电影' },
    { type_id: 2, type_name: '连续剧' },
    { type_id: 3, type_name: '综艺' },
    { type_id: 4, type_name: '动漫' },
    { type_id: 34, type_name: '短剧' },
];

// ============================ myFilters (子分类筛选) ============================
// 格式: { key, name, init: '', value: [{n, v}] }
// value 数组第一项 v 为空串表示"全部"

function nv(n, v) {
    return { n, v };
}

function buildFilter(key, name, options) {
    return { key, name, init: '', value: [{ n: '全部', v: '' }, ...options] };
}

// 电影子分类: 类型(二级分类) + 扩展分类 + 地区 + 年份
const movieTypeFilters = [
    nv('动作片', '6'), nv('喜剧片', '7'), nv('爱情片', '8'), nv('科幻片', '9'),
    nv('恐怖片', '10'), nv('剧情片', '11'), nv('战争片', '12'), nv('悬疑片', '13'),
    nv('冒险片', '14'), nv('奇幻片', '15'), nv('惊悚片', '16'), nv('动画片', '17'),
    nv('纪录片', '18'), nv('其他片', '19'),
];

const movieClassFilters = [
    nv('喜剧', '喜剧'), nv('爱情', '爱情'), nv('恐怖', '恐怖'), nv('动作', '动作'),
    nv('科幻', '科幻'), nv('剧情', '剧情'), nv('战争', '战争'), nv('警匪', '警匪'),
    nv('犯罪', '犯罪'), nv('动画', '动画'), nv('奇幻', '奇幻'), nv('武侠', '武侠'),
    nv('冒险', '冒险'), nv('枪战', '枪战'), nv('悬疑', '悬疑'), nv('惊悚', '惊悚'),
    nv('经典', '经典'), nv('青春', '青春'), nv('文艺', '文艺'), nv('微电影', '微电影'),
    nv('古装', '古装'), nv('历史', '历史'), nv('运动', '运动'), nv('农村', '农村'),
    nv('儿童', '儿童'), nv('网络电影', '网络电影'),
];

const movieAreaFilters = [
    nv('大陆', '大陆'), nv('香港', '香港'), nv('台湾', '台湾'), nv('美国', '美国'),
    nv('法国', '法国'), nv('英国', '英国'), nv('日本', '日本'), nv('韩国', '韩国'),
    nv('德国', '德国'), nv('泰国', '泰国'), nv('印度', '印度'), nv('意大利', '意大利'),
    nv('西班牙', '西班牙'), nv('加拿大', '加拿大'), nv('其他', '其他'),
];

const movieYearFilters = [
    nv('2025', '2025'), nv('2024', '2024'), nv('2023', '2023'), nv('2022', '2022'),
    nv('2021', '2021'), nv('2020', '2020'), nv('2019', '2019'), nv('2018', '2018'),
    nv('2017', '2017'), nv('2016', '2016'), nv('2015', '2015'), nv('2014', '2014'),
    nv('2013', '2013'), nv('2012', '2012'), nv('2011', '2011'), nv('2010', '2010'),
    nv('2009', '2009'), nv('2008', '2008'), nv('2007', '2007'), nv('2006', '2006'),
    nv('2005', '2005'), nv('2004', '2004'), nv('2003', '2003'), nv('2002', '2002'),
    nv('2001', '2001'), nv('2000', '2000'),
];

// 连续剧子分类
const tvTypeFilters = [
    nv('国产剧', '20'), nv('港台剧', '21'), nv('日韩剧', '22'), nv('欧美剧', '23'), nv('海外剧', '24'),
];
const tvClassFilters = [
    nv('古装', '古装'), nv('战争', '战争'), nv('青春偶像', '青春偶像'), nv('喜剧', '喜剧'),
    nv('家庭', '家庭'), nv('犯罪', '犯罪'), nv('动作', '动作'), nv('奇幻', '奇幻'),
    nv('剧情', '剧情'), nv('历史', '历史'), nv('经典', '经典'), nv('乡村', '乡村'),
    nv('情景', '情景'), nv('商战', '商战'), nv('网剧', '网剧'), nv('其他', '其他'),
];
const tvAreaFilters = [
    nv('内地', '内地'), nv('韩国', '韩国'), nv('香港', '香港'), nv('台湾', '台湾'),
    nv('日本', '日本'), nv('美国', '美国'), nv('泰国', '泰国'), nv('英国', '英国'),
    nv('新加坡', '新加坡'), nv('其他', '其他'),
];

// 综艺子分类
const varietyTypeFilters = [
    nv('大陆综艺', '25'), nv('日韩综艺', '26'), nv('港台综艺', '27'), nv('欧美综艺', '28'), nv('海外综艺', '29'),
];
const varietyClassFilters = [
    nv('选秀', '选秀'), nv('情感', '情感'), nv('访谈', '访谈'), nv('播报', '播报'),
    nv('旅游', '旅游'), nv('音乐', '音乐'), nv('美食', '美食'), nv('纪实', '纪实'),
    nv('曲艺', '曲艺'), nv('生活', '生活'), nv('游戏互动', '游戏互动'), nv('财经', '财经'),
    nv('求职', '求职'),
];
const varietyAreaFilters = [
    nv('内地', '内地'), nv('港台', '港台'), nv('日韩', '日韩'), nv('欧美', '欧美'),
];

// 动漫子分类
const animeTypeFilters = [
    nv('国产动漫', '30'), nv('日本动漫', '31'), nv('欧美动漫', '32'), nv('海外动漫', '33'),
];
const animeClassFilters = [
    nv('情感', '情感'), nv('科幻', '科幻'), nv('热血', '热血'), nv('推理', '推理'),
    nv('搞笑', '搞笑'), nv('冒险', '冒险'), nv('萝莉', '萝莉'), nv('校园', '校园'),
    nv('动作', '动作'), nv('机战', '机战'), nv('运动', '运动'), nv('战争', '战争'),
    nv('少年', '少年'), nv('少女', '少女'), nv('社会', '社会'), nv('原创', '原创'),
    nv('亲子', '亲子'), nv('益智', '益智'), nv('励志', '励志'), nv('其他', '其他'),
];
const animeAreaFilters = [
    nv('国产', '国产'), nv('日本', '日本'), nv('欧美', '欧美'), nv('其他', '其他'),
];

// 短剧子分类 (短剧页有年份和排序, 无扩展分类/地区)
const duanjuYearFilters = [
    nv('2025', '2025'), nv('2024', '2024'), nv('2023', '2023'), nv('2022', '2022'), nv('2021', '2021'),
];

// 通用年份 (电影/连续剧/综艺/动漫 共用)
const commonYearFilters = movieYearFilters;

// 汇总 myFilters
const myFilters = {
    // 电影
    1: [
        buildFilter('type', '类型', movieTypeFilters),
        buildFilter('class', '分类', movieClassFilters),
        buildFilter('area', '地区', movieAreaFilters),
        buildFilter('year', '年份', commonYearFilters),
    ],
    // 连续剧
    2: [
        buildFilter('type', '类型', tvTypeFilters),
        buildFilter('class', '分类', tvClassFilters),
        buildFilter('area', '地区', tvAreaFilters),
        buildFilter('year', '年份', commonYearFilters),
    ],
    // 综艺
    3: [
        buildFilter('type', '类型', varietyTypeFilters),
        buildFilter('class', '分类', varietyClassFilters),
        buildFilter('area', '地区', varietyAreaFilters),
        buildFilter('year', '年份', commonYearFilters),
    ],
    // 动漫
    4: [
        buildFilter('type', '类型', animeTypeFilters),
        buildFilter('class', '分类', animeClassFilters),
        buildFilter('area', '地区', animeAreaFilters),
        buildFilter('year', '年份', commonYearFilters),
    ],
    // 短剧
    34: [
        buildFilter('year', '年份', duanjuYearFilters),
    ],
};

// ============================ 辅助函数 ============================

function fixUrl(url) {
    if (!url) return '';
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
    if (url.startsWith('//')) return 'https:' + url;
    if (url.startsWith('/')) return appConfig.siteUrl + url;
    return appConfig.siteUrl + '/' + url;
}

// 构建分类页URL
// tid: 顶级分类ID (1=电影, 2=连续剧, 3=综艺, 4=动漫, 34=短剧)
// extend: 筛选参数 { type, class, area, year }
// pg: 页码
function buildCategoryUrl(tid, extend, pg) {
    extend = extend || {};
    pg = pg || 1;

    // 如果选了子类型(如动作片=6), 以子类型ID作为路径
    let searchId = extend.type || String(tid);

    // 基础路径: /search/{id}.html 或 /search/{id}/page/{pg}.html
    let path = '/search/' + searchId;
    let parts = [];

    if (extend.class) parts.push('class', encodeURIComponent(extend.class));
    if (extend.area) parts.push('area', encodeURIComponent(extend.area));
    if (extend.year) parts.push('year', extend.year);

    let url;
    if (parts.length === 0) {
        // 无筛选: /search/{id}.html 或 /search/{id}/page/{pg}.html
        if (pg > 1) {
            url = '/search/' + searchId + '/page/' + pg + '.html';
        } else {
            url = '/search/' + searchId + '.html';
        }
    } else {
        // 有筛选: /search/{id}/{key}/{val}/{key2}/{val2}.../page/{pg}.html
        let pathParts = [];
        for (let i = 0; i < parts.length; i += 2) {
            pathParts.push(parts[i] + '/' + parts[i + 1]);
        }
        let basePath = '/search/' + searchId + '/' + pathParts.join('/');
        if (pg > 1) {
            url = basePath + '/page/' + pg + '.html';
        } else {
            url = basePath + '.html';
        }
    }

    return appConfig.siteUrl + url;
}

// 构建搜索URL
function buildSearchUrl(keyword, pg) {
    pg = pg || 1;
    if (pg <= 1) {
        // 搜索第一页: /search/-------------.html?wd=关键词
        // 实际站点用 POST, 但 GET 也能工作
        return appConfig.siteUrl + '/search/-------------.html?wd=' + encodeURIComponent(keyword);
    } else {
        // 翻页: /search/{encode(kw)}----------{pg}---.html
        return appConfig.siteUrl + '/search/' + encodeURIComponent(keyword) + '----------' + pg + '---.html';
    }
}

// 解析列表页 HTML, 提取视频列表
function parseListHtml(html) {
    let $ = cheerio.load(html);
    let items = [];

    // 列表项选择器: .new-up-list .item (首页/分类页/搜索页统一)
    $('.new-up-list .item, .list-show-all .item').each(function () {
        let $item = $(this);
        let $thumb = $item.find('a.thumb');
        if (!$thumb.length) return;

        let title = $thumb.attr('title') || $item.find('.subject a').text().trim();
        let link = $thumb.attr('href');
        let pic = $item.find('img').attr('data-original') || $item.find('img').attr('src') || '';
        let remark = $item.find('.state').text().trim();
        let tags = $item.find('.tags').text().trim();

        if (link) {
            items.push({
                vod_id: link.replace('/doc/', '').replace('.html', ''),
                vod_name: title,
                vod_pic: fixUrl(pic),
                vod_remarks: remark || tags,
            });
        }
    });

    // 提取总页数
    let pageMatch = html.match(/\.\.(\d+)页/);
    let totalPage = pageMatch ? parseInt(pageMatch[1]) : 1;

    return { list: items, pagecount: totalPage };
}

// ============================ 核心接口 ============================

// init
async function init(ext) {
    if (ext) {
        // ext 可能是 base URL, 如用户更换了域名
        if (ext.startsWith('http')) {
            appConfig.siteUrl = ext.replace(/\/$/, '');
        }
    }
}

// home: 返回分类列表 + 筛选器
async function home(filter) {
    return JSON.stringify({
        class: classList,
        filters: filter ? myFilters : {},
    });
}

// category: 获取分类列表
async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};

    let url = buildCategoryUrl(tid, extend, pg);

    let resp = await req(url, {
        method: 'GET',
        headers: {
            'User-Agent': appConfig.ua,
            'Referer': appConfig.siteUrl + '/',
        },
        timeout: 15000,
    });

    let html = resp.content || '';
    let result = parseListHtml(html);

    return JSON.stringify({
        list: result.list,
        page: pg,
        pagecount: result.pagecount,
        limit: 20,
        total: result.pagecount * 20,
    });
}

// search
async function search(keyword, pg, filter, extend) {
    pg = pg || 1;
    let url = buildSearchUrl(keyword, pg);

    let resp = await req(url, {
        method: 'GET',
        headers: {
            'User-Agent': appConfig.ua,
            'Referer': appConfig.siteUrl + '/',
        },
        timeout: 15000,
    });

    let html = resp.content || '';
    let result = parseListHtml(html);

    // 搜索页可能没有分页信息, 从 script 中提取
    if (result.pagecount === 1) {
        let totalMatch = html.match(/mac_page_total"\)\.text\((\d+)\)/);
        if (totalMatch) {
            result.pagecount = parseInt(totalMatch[1]);
        }
    }

    return JSON.stringify({
        list: result.list,
        page: pg,
        pagecount: result.pagecount,
    });
}

// detail: 获取视频详情和播放线路
async function detail(id) {
    let url = appConfig.siteUrl + '/doc/' + id + '.html';

    let resp = await req(url, {
        method: 'GET',
        headers: {
            'User-Agent': appConfig.ua,
            'Referer': appConfig.siteUrl + '/',
        },
        timeout: 15000,
    });

    let html = resp.content || '';
    let $ = cheerio.load(html);

    // 基本信息
    let vodName = $('h1.article-subject-m').text().trim() || $('title').text().trim();
    let vodPic = $('img#movie_thumb').attr('data-original') || $('img.lazyload').first().attr('data-original') || '';
    let vodContent = $('.summary-con .box').text().trim();

    // 提取分类信息
    let vodYear = '', vodArea = '', vodClass = '', vodActor = '', vodDirector = '';
    $('.info-wrap p').each(function () {
        let label = $(this).find('label').text().trim();
        let val = $(this).find('span').text().trim();
        if (label.includes('类型')) vodClass = val;
        if (label.includes('导演')) vodDirector = val;
        if (label.includes('主演')) vodActor = val;
        if (label.includes('年份')) vodYear = val;
        if (label.includes('地区')) vodArea = val;
    });

    // 提取播放线路
    let playFromArr = [];
    let playUrlArr = [];

    $('.resource-box .rb-item').each(function (idx) {
        let lineName = $('.resource-box-nav .swiper-slide').eq(idx).find('.tab-nav').text().trim() || ('线路' + (idx + 1));
        let episodes = [];

        $(this).find('.episodes-list li a').each(function () {
            let epName = $(this).text().trim();
            let epLink = $(this).attr('href');
            // 提取播放ID: /playback/119502-1-1.html -> 119502-1-1
            let match = epLink && epLink.match(/\/playback\/(.+?)\.html/);
            let playId = match ? match[1] : epLink;

            episodes.push(epName + '$' + playId);
        });

        if (episodes.length > 0) {
            playFromArr.push(lineName);
            playUrlArr.push(episodes.join('#'));
        }
    });

    let vodPlayFrom = playFromArr.join('$$$');
    let vodPlayUrl = playUrlArr.join('$$$');

    let vod = {
        vod_id: id,
        vod_name: vodName,
        vod_pic: fixUrl(vodPic),
        vod_year: vodYear,
        vod_area: vodArea,
        vod_class: vodClass,
        vod_actor: vodActor,
        vod_director: vodDirector,
        vod_content: vodContent,
        vod_play_from: vodPlayFrom,
        vod_play_url: vodPlayUrl,
    };

    return JSON.stringify({
        list: [vod],
    });
}

// play: 获取播放地址
async function play(flag, id, flags) {
    // id 格式: 119502-1-1 (vodId-lineNo-epNo)
    let url = appConfig.siteUrl + '/playback/' + id + '.html';

    let resp = await req(url, {
        method: 'GET',
        headers: {
            'User-Agent': appConfig.ua,
            'Referer': appConfig.siteUrl + '/',
        },
        timeout: 15000,
    });

    let html = resp.content || '';

    // 从 player_aaaa 中提取播放地址
    let playerMatch = html.match(/var player_aaaa\s*=\s*(\{[^<]+\})/);
    if (playerMatch) {
        try {
            let playerData = JSON.parse(playerMatch[1]);
            let playUrl = playerData.url || '';

            // url 是 URL 编码的 (如 %68%74%74%70...), 需要解码
            if (playUrl && playUrl.indexOf('%') !== -1) {
                playUrl = decodeURIComponent(playUrl);
            }

            if (playUrl) {
                // http 开头直链 -> parse:0, 路径 -> parse:1
                let parseType = 0;
                if (!playUrl.startsWith('http')) {
                    parseType = 1;
                }

                return JSON.stringify({
                    parse: parseType,
                    url: playUrl,
                    header: {
                        'User-Agent': appConfig.ua,
                        'Referer': appConfig.siteUrl + '/',
                    },
                });
            }
        } catch (e) {
            // JSON 解析失败, 尝试其他方式
        }
    }

    // 备用: 从 .dplayer data-config 提取
    let configMatch = html.match(/\.dplayer["']?\s*\)\.attr\(["']data-config["']\s*,\s*["']([^"']+)["']/);
    if (!configMatch) {
        // 直接搜索 data-config 属性
        configMatch = html.match(/data-config=["']([^"']+)["']/);
    }
    if (configMatch) {
        try {
            let config = JSON.parse(configMatch[1].replace(/&quot;/g, '"'));
            let videoUrl = config.video && config.video.url ? config.video.url : '';
            if (videoUrl) {
                return JSON.stringify({
                    parse: 0,
                    url: videoUrl,
                    header: {
                        'User-Agent': appConfig.ua,
                        'Referer': appConfig.siteUrl + '/',
                    },
                });
            }
        } catch (e) {
            // ignore
        }
    }

    // 最终兜底: 返回原始播放页路径, 让引擎尝试解析
    return JSON.stringify({
        parse: 1,
        url: id,
        header: {
            'User-Agent': appConfig.ua,
            'Referer': appConfig.siteUrl + '/',
        },
    });
}

// ============================ localProxy (可选, 图片代理) ============================
// 本站图片为直接 URL, 无需解密代理

// ============================ export default ============================
export default {
    init,
    home,
    category,
    search,
    detail,
    play,
};
