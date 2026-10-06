/**
 * Media Warehouse Core Spider
 * Version: 2.1.0-Release
 */

let HOST = 'https://111.abdck.cc';
const DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';
const REMOTE_DOMAINS_URL = 'https://raw.myvbox99.top/abcd666abcd/tvbox-rules/main/domains.json';
const FALLBACK_DOMAINS = [
    'https://111.abdck.cc',
    'https://222.abdck.cc',
    'https://333.abdck.cc',
    'https://444.abdck.cc',
    'https://555.abdck.cc',
    'https://111.aback.cc',
    'https://222.aback.cc',
    'https://333.aback.cc',
    'https://444.aback.cc',
    'https://555.aback.cc',
    'https://111.aaxck.cc',
    'https://222.aaxck.cc',
    'https://333.aaxck.cc',
    'https://444.aaxck.cc',
    'https://555.aaxck.cc',
    'https://333.aavck.cc',
    'https://111.aavck.cc',
    'https://222.aavck.cc',
    'https://444.aavck.cc',
    'https://555.aavck.cc',
    'https://111.aauck.cc',
    'https://222.aauck.cc',
    'https://333.aauck.cc',
    'https://444.aauck.cc',
    'https://333.aatck.cc',
    'https://222.aatck.cc'
];

let siteKey = '';
let siteType = 0;

// Base64 解码器
function b64Decode(str) {
    if (!str) return '';
    str = String(str).trim().replace(/[\r\n\s]/g, '');
    if (typeof atob === 'function') {
        try {
            return decodeURIComponent(escape(atob(str)));
        } catch (e) {
            try { return atob(str); } catch (e2) {}
        }
    }
    try {
        str = str.replace(/-/g, '+').replace(/_/g, '/');
        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
        let output = '';
        str = str.replace(/=+$/, '');
        if (str.length % 4 === 1) return '';
        for (let bc = 0, bs = 0, buffer, i = 0; buffer = str.charAt(i++);) {
            buffer = chars.indexOf(buffer);
            if (~buffer) {
                bs = bc % 4 ? bs * 64 + buffer : buffer;
                if (bc++ % 4) {
                    output += String.fromCharCode(255 & bs >> (-2 * bc & 6));
                }
            }
        }
        try {
            return decodeURIComponent(escape(output));
        } catch (e) {
            return output;
        }
    } catch (e) {
        return '';
    }
}

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
                'Referer': HOST + '/'
            }
        });
        return getResponseContent(res);
    } catch (e) {
        return '';
    }
}

// 变量提取
function gp(h, k) {
    if (!h) return '';
    let reg = new RegExp('\\b' + k + "\\s*=\\s*['\"]([^'\"]+)['\"]", 'i');
    let m = String(h).match(reg);
    return m ? m[1] : '';
}

// 解密结果提取
function extractU(raw) {
    if (!raw) return '';
    if (typeof raw === 'object' && raw.u) {
        return b64Decode(raw.u);
    }
    let str = typeof raw === 'string' ? raw : JSON.stringify(raw);
    try {
        let j = JSON.parse(str);
        if (j && j.u) return b64Decode(j.u);
        if (j && j.content) return extractU(j.content);
    } catch (e) {}

    let m = str.match(/\\?["']u\\?["']\s*:\s*\\?["']([^"'\\]+)/);
    if (m) {
        return b64Decode(m[1]);
    }
    return '';
}

// POST 鉴权解密
async function postCount(countUrl, detailUrl, aid, asid, anid, ak) {
    let timestamp = Date.now();
    let bodyStr = `id=${encodeURIComponent(aid)}&sid=${encodeURIComponent(asid)}&nid=${encodeURIComponent(anid)}&tk=${encodeURIComponent(ak)}&g=1&x=180&y=320&dt=1200&sw=1080&sh=1920&tz=-480&t=${timestamp}`;
    
    let bodyObj = {
        id: String(aid),
        sid: String(asid),
        nid: String(anid),
        tk: String(ak),
        g: '1',
        x: '180',
        y: '320',
        dt: '1200',
        sw: '1080',
        sh: '1920',
        tz: '-480',
        t: String(timestamp)
    };

    let headers = {
        'User-Agent': DEFAULT_UA,
        'Referer': detailUrl,
        'Origin': HOST,
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json, text/javascript, */*; q=0.01'
    };

    try {
        let res = await req(countUrl, {
            method: 'post',
            headers: headers,
            data: bodyObj,
            postType: 'form'
        });
        let u = extractU(res);
        if (u) return u;
    } catch (e) {}

    try {
        let res = await req(countUrl, {
            method: 'POST',
            headers: headers,
            data: bodyStr,
            body: bodyStr
        });
        let u = extractU(res);
        if (u) return u;
    } catch (e) {}

    try {
        if (typeof post === 'function') {
            let res = await post(countUrl, bodyStr, headers);
            let u = extractU(res);
            if (u) return u;
        }
    } catch (e) {}

    return '';
}

// 域名深度闭环校验：不仅验证分类页，更取详情页参数模拟 POST /static/count.php，确保直链能成功解码（包含 .m3u8）
async function isHostAlive(url) {
    try {
        let catRes = await req(url + '/vodtype/1.html', {
            method: 'get',
            headers: { 'User-Agent': DEFAULT_UA, 'Referer': url + '/' },
            timeout: 3000
        });
        let catHtml = getResponseContent(catRes);
        if (!catHtml || catHtml.indexOf('stui-vodlist__box') === -1) return false;

        // 从分类页提取第一个真实视频详情链接
        let m = catHtml.match(/href=["']\/(?:v5\/)?(\d+)(?:-1-1)?\.html["']/i);
        let testVid = m ? m[1] : '270134';
        let detailUrl = `${url}/v5/${testVid}-1-1.html`;

        let detRes = await req(detailUrl, {
            method: 'get',
            headers: { 'User-Agent': DEFAULT_UA, 'Referer': url + '/' },
            timeout: 3000
        });
        let detHtml = getResponseContent(detRes);
        if (!detHtml) return false;

        let aid = gp(detHtml, 'AID') || testVid;
        let sid = gp(detHtml, 'ASID') || '1';
        let nid = gp(detHtml, 'ANID') || '1';
        let tk = gp(detHtml, 'AK') || (detHtml.match(/\bAK\s*=\s*['"]([a-fA-F0-9]{32,})['"]/i) || [])[1];
        if (!aid || !tk) return false;

        // 核心：真实探测取流接口
        let realUrl = await postCount(`${url}/static/count.php`, detailUrl, aid, sid, nid, tk);
        return !!(realUrl && (realUrl.indexOf('.m3u8') !== -1 || realUrl.startsWith('http')));
    } catch (e) {
        return false;
    }
}

// 自动探测当前可用域名：优先拉取 GitHub 域名池，结合本地备选池与数字递增规则
async function detectHost() {
    // 1. 如果当前 HOST 真实取流完全正常，秒开不折腾
    if (await isHostAlive(HOST)) return;

    let pool = [];

    // 2. 尝试从 GitHub 远程配置拉取最新域名池（无感热更新）
    try {
        let remoteRes = await req(REMOTE_DOMAINS_URL, {
            method: 'get',
            headers: { 'User-Agent': DEFAULT_UA },
            timeout: 3000
        });
        let remoteJson = JSON.parse(getResponseContent(remoteRes));
        if (remoteJson && Array.isArray(remoteJson.domains)) {
            pool = pool.concat(remoteJson.domains);
        }
    } catch (e) {}

    // 3. 合并本地内置兜底池
    FALLBACK_DOMAINS.forEach(function(d) {
        if (pool.indexOf(d) === -1) pool.push(d);
    });

    // 4. 对每个可用主域，额外自动探测相邻前缀（例如 111, 222, 333, 444, 555）
    let prefixes = [111, 222, 333, 444, 555];
    let candidateBases = ['abdck.cc', 'aback.cc', 'aaxck.cc', 'aavck.cc', 'aauck.cc', 'aatck.cc'];
    candidateBases.forEach(function(base) {
        prefixes.forEach(function(num) {
            let u = 'https://' + num + '.' + base;
            if (pool.indexOf(u) === -1) pool.push(u);
        });
    });

    // 5. 循环验证闭环取流能力，命中第一个完全可用的直链域名即切换
    for (let i = 0; i < pool.length; i++) {
        let target = pool[i];
        if (target !== HOST && await isHostAlive(target)) {
            HOST = target;
            return;
        }
    }
}

async function init(cfg) {
    siteKey = cfg.skey;
    siteType = cfg.stype;
    await detectHost();
}

// 分类隐晦化展示
async function home(filter) {
    return JSON.stringify({
        class: [
            { type_id: '2', type_name: '国产专区' },
            { type_id: '1', type_name: '日韩剧场' },
            { type_id: '3', type_name: '欧美精选' },
            { type_id: '4', type_name: '成人动漫' }
        ]
    });
}

async function homeVod() {
    return await category('hits', '1', false, {});
}

async function category(tid, pg, filter, extend) {
    let page = pg || '1';
    let url = tid === 'hits' 
        ? `${HOST}/vodshow/1--hits------${page}---.html` 
        : (page === '1' ? `${HOST}/vodtype/${tid}.html` : `${HOST}/vodtype/${tid}-${page}.html`);

    let html = await request(url);
    let vods = [];

    let items = html.split(/<div\s+class=["'][^"']*stui-vodlist__box[^"']*["']/i);
    for (let i = 1; i < items.length; i++) {
        let item = items[i];
        let idM = item.match(/href=["']\/(?:v5\/)?(\d+)(?:-1-1)?\.html["']/i);
        let titleM = item.match(/<h4[^>]*class=["']title["'][^>]*><a[^>]*>([^<]+)<\/a>/i) ||
                     item.match(/title=["']([^"']+)["']/i);
        let picM = item.match(/(?:data-original|src)=["']([^"']+\.(?:jpg|png|jpeg|webp))["']/i);
        let remM = item.match(/<span\s+class=["']pic-text[^"']*["']>([^<]+)<\/span>/i);

        if (idM && titleM && picM) {
            let id = idM[1];
            let title = titleM[1].trim();
            let pic = picM[1];
            if (!pic.startsWith('http')) pic = HOST + pic;

            if (!vods.some(v => v.vod_id === id)) {
                vods.push({
                    vod_id: id,
                    vod_name: title,
                    vod_pic: pic,
                    vod_remarks: remM ? remM[1].trim() : ''
                });
            }
        }
    }

    return JSON.stringify({
        page: parseInt(page),
        pagecount: 999,
        limit: vods.length,
        total: 999,
        list: vods
    });
}

async function detail(id) {
    let vid = id;
    if (vid.includes('/')) {
        let m = vid.match(/(\d+)/);
        if (m) vid = m[1];
    }

    let detailUrl = `${HOST}/v5/${vid}-1-1.html`;
    let html = await request(detailUrl);

    let titleMatch = html.match(/<h3[^>]*class=["']title["'][^>]*>([^<]+)<\/h3>/i) ||
                     html.match(/<h1[^>]*>([^<]+)<\/h1>/i) ||
                     html.match(/<title>([^<]+)-/i);
    let title = titleMatch ? titleMatch[1].trim() : '视频播放';

    let picMatch = html.match(/(?:data-original|src)=["']([^"']+\.(?:jpg|png|jpeg|webp))["']/i);
    let pic = picMatch ? picMatch[1] : '';
    if (pic && !pic.startsWith('http')) pic = HOST + pic;

    let aid = gp(html, 'AID') || vid;
    let sid = gp(html, 'ASID') || '1';
    let nid = gp(html, 'ANID') || '1';
    let tk = gp(html, 'AK');
    if (!tk) {
        let akM = html.match(/\bAK\s*=\s*['"]([a-fA-F0-9]{32,})['"]/i);
        if (akM) tk = akM[1];
    }

    let playTarget = vid;
    if (aid && tk) {
        let realUrl = await postCount(`${HOST}/static/count.php`, detailUrl, aid, sid, nid, tk);
        if (realUrl) {
            playTarget = realUrl;
        }
    }

    return JSON.stringify({
        list: [{
            vod_id: vid,
            vod_name: title,
            vod_pic: pic,
            vod_play_from: '默认线路',
            vod_play_url: `正片$${playTarget}`
        }]
    });
}

async function search(wd, quick, pg) {
    let page = pg || '1';
    let encoded = encodeURIComponent(wd);
    let searchUrl = `${HOST}/vodsearch/${encoded}----------${page}---.html`;
    let html = await request(searchUrl);
    let vods = [];

    let items = html.split(/<div\s+class=["'][^"']*stui-vodlist__box[^"']*["']/i);
    for (let i = 1; i < items.length; i++) {
        let item = items[i];
        let idM = item.match(/href=["']\/(?:v5\/)?(\d+)(?:-1-1)?\.html["']/i);
        let titleM = item.match(/<h4[^>]*class=["']title["'][^>]*><a[^>]*>([^<]+)<\/a>/i) ||
                     item.match(/title=["']([^"']+)["']/i);
        let picM = item.match(/(?:data-original|src)=["']([^"']+\.(?:jpg|png|jpeg|webp))["']/i);
        let remM = item.match(/<span\s+class=["']pic-text[^"']*["']>([^<]+)<\/span>/i);

        if (idM && titleM && picM) {
            let id = idM[1];
            let title = titleM[1].trim();
            let pic = picM[1];
            if (!pic.startsWith('http')) pic = HOST + pic;

            if (!vods.some(v => v.vod_id === id)) {
                vods.push({
                    vod_id: id,
                    vod_name: title,
                    vod_pic: pic,
                    vod_remarks: remM ? remM[1].trim() : ''
                });
            }
        }
    }

    // 动态提取原站分页条中的总页数（例如 1/84 或 data-total="84"）
    let pagecount = 1;
    let pageM = html.match(/class=["']num["']>(\d+)\/(\d+)<\/span>/i) ||
                html.match(/data-total=["'](\d+)["']/i);
    if (pageM) {
        pagecount = parseInt(pageM[2] || pageM[1]);
    } else if (vods.length >= 20) {
        pagecount = parseInt(page) + 1; // 保底预估
    }

    return JSON.stringify({
        page: parseInt(page),
        pagecount: pagecount,
        limit: vods.length,
        total: pagecount * 20,
        list: vods
    });
}

async function play(flag, id, flags) {
    let realPlayUrl = '';

    if (id.startsWith('http://') || id.startsWith('https://')) {
        realPlayUrl = id;
    } else {
        let vid = id;
        let detailUrl = `${HOST}/v5/${vid}-1-1.html`;
        let html = await request(detailUrl);
        let aid = gp(html, 'AID') || vid;
        let sid = gp(html, 'ASID') || '1';
        let nid = gp(html, 'ANID') || '1';
        let tk = gp(html, 'AK') || (html.match(/\bAK\s*=\s*['"]([a-fA-F0-9]{32,})['"]/i) || [])[1];

        if (aid && tk) {
            realPlayUrl = await postCount(`${HOST}/static/count.php`, detailUrl, aid, sid, nid, tk);
        }
    }

    if (realPlayUrl) {
        realPlayUrl = realPlayUrl.trim().replace(/[\r\n]/g, '');
        if (realPlayUrl.startsWith('/')) realPlayUrl = HOST + realPlayUrl;
    }

    return JSON.stringify({
        parse: 0,
        url: realPlayUrl,
        header: {
            'User-Agent': DEFAULT_UA,
            'Referer': HOST + '/',
            'Origin': HOST
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
        play: play,
        search: search
    };
}
