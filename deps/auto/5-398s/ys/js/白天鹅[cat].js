import { Crypto } from 'assets://js/lib/cat.js';

const HOST = 'https://api.bteys.com';
const BIZ_KEY = 'fb2ab11fa8111d7f';
const BIZ_IV = '43xGSCM9PQX8lTgU';
const PLAY_KEY = 'qQqO7UYlJnzuwAdd';
const PLAY_IV = '43xGSCM9PQX8lTgU';

let siteKey = '';
let siteType = 0;
let configCache = null;
let configTime = 0;

const headers = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 12; Pixel 6 Build/SD1A.210817.036; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/121.0.6167.178 Mobile Safari/537.36',
    'clientname': 'baitiane',
    'version': '220'
};

function aesDecode(text, key, ivStr) {
    try {
        if (!text || text.length < 10) return text;
        const k = Crypto.enc.Utf8.parse(key);
        const v = Crypto.enc.Utf8.parse(ivStr);
        const decrypted = Crypto.AES.decrypt(text, k, {
            iv: v,
            mode: Crypto.mode.CBC,
            padding: Crypto.pad.Pkcs7
        });
        return decrypted.toString(Crypto.enc.Utf8);
    } catch (e) {
        return '';
    }
}

async function request(url) {
    try {
        const res = await req(url, { headers });
        const json = JSON.parse(res.content);
        if (json.data && typeof json.data === 'string' && json.data.length > 32) {
            const decoded = aesDecode(json.data, BIZ_KEY, BIZ_IV);
            if (decoded) return JSON.parse(decoded);
        }
        return json.data || json;
    } catch (e) { return null; }
}

async function getConfig() {
    const now = Date.now();
    if (configCache && now - configTime < 3600000) return configCache;
    try {
        const res = await req(`${HOST}/api/common/config?clientname=baitiane&version=220`, { headers });
        const json = JSON.parse(res.content);
        if (json.data) {
            const decoded = aesDecode(json.data, PLAY_KEY, PLAY_IV);
            if (decoded) {
                configCache = JSON.parse(decoded);
                configTime = now;
                return configCache;
            }
        }
    } catch (e) {}
    return null;
}

async function init(cfg) {
    siteKey = cfg.skey;
    siteType = cfg.stype;
}

async function home() {
    const url = `${HOST}/api/film/library?type=1&ext_type=all&area=all&year=all&by=all&page=1&clientname=baitiane&version=220`;
    const data = await request(url);
    if (!data) return JSON.stringify({ class: [], filters: {} });
    const classes = [];
    const filters = {};
    const c = data.Classify || {};
    (c.types || []).forEach(it => {
        if (it.type_id === 'all') return;
        classes.push({ type_id: it.type_id, type_name: it.type_name });
        filters[it.type_id] = [
            { key: 'ext_type', name: '类型', value: (c.ext_types || []).map(i => ({ n: i.type_name, v: i.type_id })) },
            { key: 'area', name: '地区', value: (c.areas || []).map(i => ({ n: i.type_name, v: i.type_id })) },
            { key: 'year', name: '年份', value: (c.years || []).map(i => ({ n: i.type_name, v: i.type_id })) },
            { key: 'by', name: '排序', value: (c.bys || []).map(i => ({ n: i.type_name, v: i.type_id })) }
        ];
    });
    return JSON.stringify({ class: classes, filters });
}

async function homeVod() {
    const url = `${HOST}/api/index/index?clientname=baitiane&version=220`;
    const data = await request(url);
    if (!data) return JSON.stringify({ list: [] });
    const list = [];
    const sourceArray = Array.isArray(data) ? data : Object.values(data);
    sourceArray.forEach(section => {
        const items = section.banners || section.list || [];
        if (Array.isArray(items)) {
            items.forEach(it => {
                if (!it.id) return;
                list.push({
                    vod_id: String(it.id),
                    vod_name: it.title || it.name || '',
                    vod_pic: it.picUrl || it.pic || '',
                    vod_remarks: it.msg || ''
                });
            });
        }
    });
    return JSON.stringify({ list });
}

async function category(tid, pg, filter, ext) {
    const url = `${HOST}/api/film/library?type=${tid}&ext_type=${ext.ext_type || 'all'}&area=${ext.area || 'all'}&year=${ext.year || 'all'}&by=${ext.by || 'all'}&page=${pg}&clientname=baitiane&version=220`;
    const data = await request(url);
    if (!data) return JSON.stringify({ list: [] });
    const list = (data.Library || []).map(it => ({
        vod_id: String(it.id),
        vod_name: it.title,
        vod_pic: it.pic,
        vod_remarks: it.msg || ''
    }));
    return JSON.stringify({ page: pg, pagecount: 999, list });
}

async function detail(id) {
    const url = `${HOST}/api/index/detail?id=${id}&clientname=baitiane&version=220`;
    const data = await request(url);
    if (!data || !data.detail) return JSON.stringify({ list: [] });
    const vod = data.detail;
    const playFrom = [];
    const playUrls = [];
    (vod.players || []).forEach(p => {
        if (!p.name) return;
        playFrom.push(p.name);
        const urls = (p.datas || []).map(u => `${u.text}$${u.play_url}`);
        playUrls.push(urls.join('#'));
    });
    return JSON.stringify({
        list: [{
            vod_id: String(vod.id),
            vod_name: vod.title,
            vod_pic: vod.pic,
            vod_play_from: playFrom.join('$$$'),
            vod_play_url: playUrls.join('$$$'),
            vod_content: vod.content || '',
            vod_actor: (vod.actors || []).join('/'),
            vod_director: (vod.director || []).join('/'),
            vod_year: vod.year || '',
            vod_area: (vod.area || []).join('/'),
            vod_remarks: vod.msg || ''
        }]
    });
}

async function play(flag, id, flags) {
    try {
        let realUrl = id;
        if (!id.startsWith('http')) {
            const decoded = aesDecode(id, PLAY_KEY, PLAY_IV);
            if (decoded) {
                try {
                    const obj = JSON.parse(decoded);
                    realUrl = obj.url || decoded;
                } catch (e) {
                    realUrl = decoded;
                }
            }
        }
        const config = await getConfig();
        let finalUrl = realUrl;
        let playUA = headers['User-Agent'];

        if (config && config.parsing) {
            let parser = config.parsing.find(p => {
                if (!p.play_key) return false;
                return p.play_key.split(',').some(k => realUrl.includes(k));
            });
            if (!parser && !realUrl.includes('.m3u8') && !realUrl.includes('.mp4')) {
                parser = config.parsing[0];
            }

            if (parser && parser.url) {
                const parseApi = parser.url + encodeURIComponent(realUrl);
                const res = await req(parseApi, { headers: { 'User-Agent': playUA } });
                const json = JSON.parse(res.content);
                if (json.url) {
                    finalUrl = json.url;
                    if (json.UA) playUA = json.UA;
                }
            }
        }
        if (finalUrl.startsWith('http') && !finalUrl.includes('.m3u8') && !finalUrl.includes('.mp4')) {
            const checkRes = await req(finalUrl, { headers: { 'User-Agent': playUA }, method: 'get' });
            if (checkRes.content.includes('.m3u8') || checkRes.content.includes('.mp4')) {
                try {
                    const checkJson = JSON.parse(checkRes.content);
                    if (checkJson.url) finalUrl = checkJson.url;
                } catch(e) {}
            }
        }
        return JSON.stringify({
            parse: 0,
            url: finalUrl,
            header: {
                'User-Agent': playUA,
                'Origin': HOST,
                'Referer': HOST
            }
        });
    } catch (e) {
        return JSON.stringify({ parse: 0, url: id });
    }
}

async function search(wd, quick, pg) {
    const page = pg || 1;
    const url = `${HOST}/api/search/searchvideo?keyword=${encodeURIComponent(wd)}&page=${page}&pagesize=10&clientname=baitiane&version=220`;
    const data = await request(url);
    if (!data || (!data.list && !Array.isArray(data))) return JSON.stringify({ list: [] });
    const items = Array.isArray(data) ? data : (data.list || []);
    const list = items.map(it => ({
        vod_id: String(it.id),
        vod_name: it.title || it.name,
        vod_pic: it.pic || it.picUrl,
        vod_remarks: it.msg || ''
    }));
    return JSON.stringify({ list });
}

export function __jsEvalReturn() {
    return { init, home, homeVod, category, detail, play, search };
}