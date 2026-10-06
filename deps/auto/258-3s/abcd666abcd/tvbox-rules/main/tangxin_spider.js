/**
 * Tangxin Media Core Spider
 * Version: 1.2.4-Production
 * Standards: CatVod / TVBox QuickJS Specification
 */

let HOST = 'https://raw.myvbox99.top/tx';
let ORIGIN = 'https://tangxinvlog.app';
let CDN = 'https://t.5gcdn.xyz';
let IMG_HOST = 'https://raw.myvbox99.top/tx-img';
const DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

let siteKey = '';
let siteType = 0;

// 规范分类字典（纯数字 type_id，去重精选合辑由 homeVod 接管）
const CATEGORY_MAP = {
    '1': { name: '柚子猫', path: 'a/Yuzukitty柚子猫' },
    '2': { name: '桥本香菜', path: 'a/桥本香菜' },
    '3': { name: '小欣奈', path: 'a/小欣奈' },
    '4': { name: '饼干姐姐', path: 'a/饼干姐姐' },
    '5': { name: '星野兔', path: 'a/星野兔' },
    '6': { name: '小狐狸', path: 'a/Sweetie Fox(小狐狸)' },
    '7': { name: 'Nana', path: 'a/Nana_taipei' },
    '8': { name: '整活工坊', path: 'a/小野整活部' },
    '9': { name: 'AI短剧', path: 'a/糖心AI创意短剧' },
    '10': { name: '反差剧场', path: 'a/极限反差团' },
    '11': { name: '星空专区', path: 'a/星空无限传媒' },
    '12': { name: '爱豆专区', path: 'a/爱豆传媒' },
    '13': { name: '二次元漫剪', path: 'tag/cospaly' }
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

// GET 网络请求
async function request(reqUrl) {
    try {
        let res = await req(reqUrl, {
            method: 'get',
            headers: {
                'User-Agent': DEFAULT_UA,
                'Referer': ORIGIN + '/'
            }
        });
        return getResponseContent(res);
    } catch (e) {
        return '';
    }
}

// 物理切块解析卡片列表
function parseCards(html) {
    let vods = [];
    if (!html) return vods;
    let items = html.split(/<article\s+class=["'][^"']*card[^"']*["']/i);
    for (let i = 1; i < items.length; i++) {
        let chunk = items[i];
        let idM = chunk.match(/href=["']\/v\/(\d+)\/["']/i);
        let titleM = chunk.match(/aria-label=["']([^"']+)["']/i) ||
                     chunk.match(/<h3[^>]*class=["']title["'][^>]*>\s*<a[^>]*>([^<]+)<\/a>/i);
        let durM = chunk.match(/class=["']duration["'][^>]*>([^<]+)<\/span>/i);
        let picM = chunk.match(/src=["'](https?:\/\/[^"']+cover\.jpg)["']/i);
        let nickM = chunk.match(/class=["']nickname["'][^>]*>([\s\S]*?)<\/a>/i);

        if (idM) {
            let id = idM[1];
            let title = titleM ? titleM[1].trim() : ('作品 ' + id);
            let pic = `${IMG_HOST}/${id}.jpg`;
            let dur = durM ? durM[1].trim() : '';
            let nick = nickM ? nickM[1].replace(/<[^>]+>/g, '').replace(/^@\s*/, '').trim() : '';
            let rem = dur + (nick ? ' · ' + nick : '');

            if (!vods.some(v => v.vod_id === id)) {
                vods.push({
                    vod_id: id,
                    vod_name: title,
                    vod_pic: pic,
                    vod_remarks: rem
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

// 动态输出知名创作者与精选分类
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

async function homeVod() {
    return await category('featured', '1', false, {});
}

async function category(tid, pg, filter, extend) {
    let page = parseInt(pg || '1');
    let url = '';

    if (String(tid) === 'featured') {
        url = page === 1 ? `${HOST}/featured/` : `${HOST}/featured/${page}/`;
    } else {
        let conf = CATEGORY_MAP[String(tid)] || CATEGORY_MAP['1'];
        let path = conf.path;
        let parts = path.split('/');
        let prefix = parts[0];
        let slug = encodeURIComponent(parts.slice(1).join('/'));
        url = page === 1 ? `${HOST}/${prefix}/${slug}/` : `${HOST}/${prefix}/${slug}/${page}/`;
    }

    let html = await request(url);
    let vods = parseCards(html);
    let hasNext = /rel=["']next["']/i.test(html) || /下一页/.test(html) || vods.length >= 24;

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
    if (vid.includes('/')) {
        let m = vid.match(/(\d+)/);
        if (m) vid = m[1];
    }

    let detailUrl = `${HOST}/v/${vid}/`;
    let html = await request(detailUrl);

    let titleMatch = html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i) ||
                     html.match(/<title>([^<]+)<\/title>/i);
    let title = titleMatch ? titleMatch[1].replace(/<[^>]+>/g, '').trim() : `视频 ${vid}`;

    let pic = `${IMG_HOST}/${vid}.jpg`;

    let descMatch = html.match(/<meta\s+name=["']description["']\s+content=["']([^"']*)["']/i);
    let desc = descMatch ? descMatch[1].trim() : '';

    let actorMatch = html.match(/href=["']\/a\/[^"']+\/["'][^>]*>([\s\S]*?)<\/a>/i);
    let actor = actorMatch ? actorMatch[1].replace(/<[^>]+>/g, '').replace(/^@\s*/, '').trim() : '';

    // 0ms 前置组装免解密直链（国内直连 CDN 秒开）
    let streamUrl = `${CDN}/videos/${vid}/index.m3u8`;

    return JSON.stringify({
        list: [{
            vod_id: vid,
            vod_name: title,
            vod_pic: pic,
            vod_actor: actor,
            vod_content: desc,
            vod_play_from: '极速专线',
            vod_play_url: `正片$${streamUrl}`
        }]
    });
}

async function search(wd, quick, pg) {
    let page = parseInt(pg || '1');
    if (!wd) {
        return JSON.stringify({
            page: page,
            pagecount: page,
            limit: 0,
            total: 0,
            list: []
        });
    }
    let trimmed = String(wd).trim();
    let encoded = encodeURIComponent(trimmed);

    // 优先尝试创作者专栏（按页码拼接 /a/{name}/ 或 /a/{name}/{page}/）
    let actorUrl = page === 1 ? `${HOST}/a/${encoded}/` : `${HOST}/a/${encoded}/${page}/`;
    let html = await request(actorUrl);
    let vods = parseCards(html);

    // 次选尝试标签分类（按页码拼接 /tag/{name}/ 或 /tag/{name}/{page}/）
    if (vods.length === 0 && page === 1) {
        let tagUrl = `${HOST}/tag/${encoded}/`;
        let tagHtml = await request(tagUrl);
        vods = parseCards(tagHtml);
        if (vods.length > 0) {
            html = tagHtml;
        }
    } else if (vods.length === 0 && page > 1) {
        let tagUrl = `${HOST}/tag/${encoded}/${page}/`;
        let tagHtml = await request(tagUrl);
        vods = parseCards(tagHtml);
        if (vods.length > 0) {
            html = tagHtml;
        }
    }

    // 判断是否存在真实下一页（Astro 生成的 link rel="next"、下一页链接或满页 24 条）
    let hasNext = false;
    if (vods.length > 0 && html) {
        hasNext = /rel=["']next["']/i.test(html) ||
                  /class=["'][^"']*pager-link[^"']*["'][^>]*>下一页/i.test(html) ||
                  (new RegExp(`/(${page + 1})/?["']`, 'i')).test(html) ||
                  vods.length >= 24;
    }

    return JSON.stringify({
        page: page,
        pagecount: hasNext ? page + 1 : page,
        limit: vods.length,
        total: hasNext ? (page + 1) * 24 : page * vods.length,
        list: vods
    });
}

async function play(flag, id, flags) {
    let playUrl = String(id);
    if (!playUrl.startsWith('http://') && !playUrl.startsWith('https://')) {
        playUrl = `${CDN}/videos/${id}/index.m3u8`;
    }

    return JSON.stringify({
        parse: 0,
        url: playUrl,
        header: {
            'User-Agent': DEFAULT_UA,
            'Referer': ORIGIN + '/'
        }
    });
}

// 关键规范导出接口（兼容 ES Module 与 QuickJS 全局调用）
export function __jsEvalReturn() {
    return {
        init: init,
        home: home,
        homeVod: homeVod,
        category: category,
        detail: detail,
        play: play,
        search: search
    };
}

if (typeof globalThis !== 'undefined') {
    globalThis.__jsEvalReturn = __jsEvalReturn;
}
