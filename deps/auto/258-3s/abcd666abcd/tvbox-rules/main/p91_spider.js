/**
 * Digital Original Media Spider
 * Version: 1.0.4-Production
 * Standards: CatVod / TVBox QuickJS Specification
 */

let HOST = 'https://91porn.com';
let IMG_HOST = 'https://raw.myvbox99.top/91-img';
const DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';
const DEFAULT_COOKIE = 'ga=OlYqv%5E73b0g9fg9tiYjSwkXIfB_oFGoVlt6luJuk7KXoO3qZuOF7RBQqypYA; CLIPSHARE=5dbb326a0cc3fd9c87072268deff02a6; language=cn_CN';

let siteKey = '';
let siteType = 0;

// 规范分类字典（榜单 + 原站原生专区双轨制，去重精选由 homeVod 接管）
const CATEGORY_MAP = {
    '1': { name: '当前最热', type: 'url', path: '/v.php?category=hot&viewtype=basic' },
    '2': { name: '最近加精', type: 'url', path: '/v.php?category=rf&viewtype=basic' },
    '3': { name: '每月最热', type: 'url', path: '/v.php?category=top&m=-1&viewtype=basic' },
    '4': { name: '本月收藏', type: 'url', path: '/v.php?category=tf&viewtype=basic' },
    '5': { name: '91原创', type: 'url', path: '/v.php?category=ori&viewtype=basic' },
    '6': { name: '高清专区', type: 'url', path: '/v.php?category=hd&viewtype=basic' },
    '7': { name: '极品探花', type: 'search', wd: '探花' },
    '8': { name: '清纯学生', type: 'search', wd: '学生' },
    '9': { name: '风韵人妻', type: 'search', wd: '人妻' },
    '10': { name: '户外实景', type: 'search', wd: '户外' },
    '11': { name: '长视频区', type: 'url', path: '/v.php?category=long&viewtype=basic' }
};

// 递归解包
function getResponseContent(res) {
    if (!res) return '';
    if (typeof res === 'object') {
        if (res.content !== undefined) return getResponseContent(res.content);
        if (res.body !== undefined) return getResponseContent(res.body);
        if (res.data !== undefined) return getResponseContent(res.data);
        return JSON.stringify(res);
    }
    if (typeof res === 'string') {
        let trimmed = res.trim();
        if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
            try {
                let parsed = JSON.parse(trimmed);
                if (parsed && typeof parsed === 'object') {
                    if (parsed.content !== undefined) return getResponseContent(parsed.content);
                    if (parsed.body !== undefined) return getResponseContent(parsed.body);
                    if (parsed.data !== undefined && typeof parsed.data === 'string') return getResponseContent(parsed.data);
                }
            } catch (e) {}
        }
        return res;
    }
    return String(res);
}

// GET 网络请求（内置长效访客验证凭据）
async function request(reqUrl) {
    try {
        let res = await req(reqUrl, {
            method: 'get',
            headers: {
                'User-Agent': DEFAULT_UA,
                'Referer': HOST + '/',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Cookie': DEFAULT_COOKIE
            }
        });
        return getResponseContent(res);
    } catch (e) {
        return '';
    }
}

// 精准过滤广告与物理卡片解析
function parseCards(html) {
    let vods = [];
    if (!html) return vods;

    // 匹配每一个视频卡片外层 div 容器（保留 class 属性以供深度安全过滤）
    let matches = [...html.matchAll(/<div\s+class=["']([^"']*col-xs-12[^"']*)["']([^>]*)>([\s\S]*?)<\/div>\s*<\/div>/gi)];

    for (let m of matches) {
        let cls = m[1];
        let body = m[3];

        // 核心过滤防线：
        // 1. col-lg-8 为站方置顶竞价广告容器（真实卡片均为 col-lg-3）
        // 2. 广告轮播链接带有 c=aaxbms, c=auct, c=aipneu 等特定推广参数（注意：普通高清带有 c=axbms，不可粗暴过滤 c=a）
        if (cls.includes('col-lg-8') || body.includes('c=aaxbms') || body.includes('c=auct') || body.includes('c=aipneu')) {
            continue;
        }

        // 兼容普通视频 view_video.php 与高清专区 view_video_hd.php
        let idM = body.match(/view_video(?:_hd)?\.php\?viewkey=([a-zA-Z0-9]+)/i);
        let titleM = body.match(/video-title[^>]*>([\s\S]*?)<\/a>/i);
        let picM = body.match(/src=["'](https?:\/\/[^"']*\/thumb\/(\d+)\.jpg)["']/i);
        let durM = body.match(/<span\s+class=["']duration["']>([^<]+)<\/span>/i);
        let hdM = /class=["'][^"']*hd-text-icon[^"']*["']/i.test(body);
        let authorM = body.match(/<span\s+class=["']info["']>([^<]*作者[^<]*)<\/span>\s*([\s\S]*?)<br/i);

        if (idM && titleM) {
            let vid = idM[1];
            let rawTitle = titleM[1].replace(/<[^>]+>/g, '')
                                    .replace(/<\/?span[^>]*>/gi, '')
                                    .replace(/\?\/?span>/gi, '')
                                    .replace(/[\u200B-\u200D\uFEFF]/g, '')
                                    .trim();
            let pic = picM ? `${IMG_HOST}/${picM[2]}.jpg` : '';
            let dur = durM ? durM[1].trim() : '';
            let author = authorM ? authorM[2].replace(/<[^>]+>/g, '').trim() : '';
            let rem = (hdM ? 'HD ' : '') + dur + (author ? ' · ' + author : '');

            // 严格去重保障
            if (!vods.some(v => v.vod_id === vid)) {
                vods.push({
                    vod_id: vid,
                    vod_name: rawTitle || ('视频 ' + vid),
                    vod_pic: pic,
                    vod_remarks: rem.trim()
                });
            }
        }
    }
    return vods;
}

async function init(cfg) {
    if (cfg) {
        siteKey = cfg.skey || '';
        siteType = cfg.stype || 0;
    }
}

// 动态输出分类字典
async function home(filter) {
    let classes = [];
    for (let k in CATEGORY_MAP) {
        classes.push({
            type_id: k,
            type_name: CATEGORY_MAP[k].name
        });
    }
    return JSON.stringify({
        class: classes
    });
}

// 客户端原生「推荐」Tab 接管：默认展示最新精选更新（不放入独立分类，杜绝内容重复）
async function homeVod() {
    let html = await request(`${HOST}/v.php?category=top&viewtype=basic&page=1`);
    let vods = parseCards(html);
    return JSON.stringify({
        page: 1,
        pagecount: 1,
        limit: vods.length,
        total: 9999,
        list: vods
    });
}

async function category(tid, pg, filter, extend) {
    let page = parseInt(pg || '1');
    let conf = CATEGORY_MAP[String(tid)] || CATEGORY_MAP['1'];
    let url = '';

    if (conf.type === 'search') {
        url = `${HOST}/search_result.php?search_id=${encodeURIComponent(conf.wd)}&search_type=search_videos&page=${page}`;
    } else {
        url = `${HOST}${conf.path}&page=${page}`;
    }

    let html = await request(url);
    let vods = parseCards(html);
    let hasNext = /rel=["']next["']/i.test(html) || /下一页/.test(html) || vods.length >= 20;

    return JSON.stringify({
        page: page,
        pagecount: hasNext ? page + 1 : page,
        limit: vods.length,
        total: 9999,
        list: vods
    });
}

async function detail(id) {
    let vid = String(id);
    let detailUrl = `${HOST}/view_video.php?viewkey=${vid}`;
    let html = await request(detailUrl);

    let streamUrl = '';
    let encM = html.match(/strencode2\("([^"]+)"\)/);
    if (encM) {
        let decoded = '';
        try {
            decoded = decodeURIComponent(encM[1]);
        } catch (e) {
            decoded = unescape(encM[1]);
        }
        let srcM = decoded.match(/src=['"]([^'"]+\.mp4\?[^'"]+)['"]/i) ||
                   decoded.match(/src=['"]([^'"]+)['"]/i);
        if (srcM) {
            streamUrl = srcM[1];
        }
    }

    let titleMatch = html.match(/<h4[^>]*class=["'][^"']*login_register_header[^"']*["'][^>]*>([\s\S]*?)<\/h4>/i) ||
                     html.match(/<title>([^<]+)<\/title>/i);
    let title = titleMatch ? titleMatch[1].replace(/<[^>]+>/g, '').replace(/[\u200B-\u200D\uFEFF]/g, '').trim() : `视频 ${vid}`;

    let pic = '';
    let posterM = html.match(/poster=["'](https?:\/\/[^"']*\/thumb\/(\d+)\.jpg)["']/i);
    if (posterM) {
        pic = `${IMG_HOST}/${posterM[2]}.jpg`;
    }

    let actorMatch = html.match(/href=["']uprofile\.php\?UID=[^"']+["'][^>]*>([\s\S]*?)<\/a>/i);
    let actor = actorMatch ? actorMatch[1].replace(/<[^>]+>/g, '').trim() : '';

    return JSON.stringify({
        list: [{
            vod_id: vid,
            vod_name: title,
            vod_pic: pic,
            vod_actor: actor,
            vod_content: title,
            vod_play_from: '默认专线',
            vod_play_url: `正片$${streamUrl}`
        }]
    });
}

async function search(wd, quick, pg) {
    let page = parseInt(pg || '1');
    let url = `${HOST}/search_result.php?search_id=${encodeURIComponent(wd)}&search_type=search_videos&page=${page}`;
    let html = await request(url);
    let vods = parseCards(html);
    let hasNext = /rel=["']next["']/i.test(html) || /下一页/.test(html) || vods.length >= 20;

    return JSON.stringify({
        page: page,
        pagecount: hasNext ? page + 1 : page,
        limit: vods.length,
        total: 9999,
        list: vods
    });
}

async function play(flag, id, flags) {
    return JSON.stringify({
        parse: 0,
        url: id,
        header: {
            'User-Agent': DEFAULT_UA,
            'Referer': HOST + '/'
        }
    });
}

export function __jsEvalReturn() {
    return {
        init: init,
        home: home,
        homeVod: homeVod,
        category: category,
        detail: detail,
        search: search,
        play: play
    };
}
