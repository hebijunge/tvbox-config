/**
 * 发布页 https://www.jpyy.com/
 */

const baseUrl = 'https://www.x8kb9k8.com';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36';
const HEADERS = { 'User-Agent': UA, 'Referer': baseUrl + '/', 'Accept': 'text/html' };
const PLAY_HEADERS = { 'User-Agent': UA, 'Referer': baseUrl + '/', 'Origin': baseUrl };

async function init(cfg) { return {}; }
function destroy() { return {}; }
function live(u) { return JSON.stringify([]); }
function proxy(p) { return [404, 'text/plain', 'no proxy']; }
function sniffer() { return false; }
function isVideo(url) {
  const u = String(url || '').split(/[?#]/)[0].toLowerCase();
  return ['.m3u8', '.mp4', '.mkv', '.flv'].some(function (s) { return u.endsWith(s); });
}
async function action(v) { return JSON.stringify({ msg: 'ok' }); }
function output(v) { return JSON.stringify(v); }
function str(v) { return v == null ? '' : String(v); }
function stripTags(s) { return str(s).replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').trim(); }

function parseRespText(resp) {
  if (resp == null) return '';
  if (typeof resp === 'string') return resp;
  if (typeof resp === 'object') {
    if (typeof resp.content === 'string') return resp.content;
    if (typeof resp.data === 'string') return resp.data;
  }
  return str(resp);
}
async function httpGet(url) {
  const r = await req(url, { headers: HEADERS });
  return parseRespText(r);
}
function flightText(html) {
  const src = str(html || '');
  const re = /self\.__next_f\.push\(\[1,([\s\S]*?)\]\)<\/script>/g;
  const parts = [];
  let m;
  while ((m = re.exec(src)) !== null) {
    let c = m[1];
    try { c = JSON.parse(c); } catch (e) { try { c = JSON.parse('[' + c + ']')[1]; } catch (e2) { c = c.split('\\n').join('\n').split('\\"').join('"'); } }
    if (typeof c !== 'string') c = str(c);
    parts.push(c);
  }
  return parts.join('\n');
}
function extractBalanced(s, start) {
  const open = s[start];
  const close = open === '{' ? '}' : ']';
  let depth = 0, inStr = false, esc = false;
  for (let i = start; i < s.length; i++) {
    const ch = s[i];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === '\\') esc = true;
      else if (ch === '"') inStr = false;
    } else {
      if (ch === '"') inStr = true;
      else if (ch === open) depth++;
      else if (ch === close) { depth--; if (depth === 0) return s.slice(start, i + 1); }
    }
  }
  return '';
}
function extractJsonByKey(text, key) {
  const pat = '"' + key + '"';
  let idx = text.indexOf(pat);
  while (idx >= 0) {
    let j = idx + pat.length;
    while (j < text.length && /\s/.test(text[j])) j++;
    if (text[j] === ':') {
      j++;
      while (j < text.length && /\s/.test(text[j])) j++;
      if (text[j] === '{' || text[j] === '[') {
        const sub = extractBalanced(text, j);
        if (sub) { try { return JSON.parse(sub); } catch (e) {} }
      }
    }
    idx = text.indexOf(pat, idx + 1);
  }
  return null;
}
function mapVodItem(o) {
  if (!o) return null;
  const vodId = str(o.vodId != null ? o.vodId : o.id);
  if (!vodId) return null;
  let remarks = str(o.vodRemarks || o.vodVersion || o.vodSerial || o.remark || '');
  if (!remarks && o.vodScore) remarks = str(o.vodScore);
  return {
    vod_id: vodId,
    vod_name: str(o.vodName || o.name || ''),
    vod_pic: str(o.vodPic || o.img || ''),
    vod_remarks: remarks,
    vod_year: str(o.vodYear || ''),
    vod_area: str(o.vodArea || ''),
    type_name: str(o.vodClass || o.typeName || '')
  };
}
function parseCardsFallback(html) {
  const src = str(html || '');
  const re = /<a[^>]*class="[^"]*content-card[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g;
  const list = [];
  let m;
  while ((m = re.exec(src)) !== null) {
    const href = m[1];
    const inner = m[2];
    const idm = /(\d{4,})/.exec(href);
    if (!idm) continue;
    const vodId = idm[1];
    if (list.some(function (x) { return x.vod_id === vodId; })) continue;
    let name = '';
    const tm = /<div[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)<\/div>/.exec(inner);
    if (tm) name = stripTags(tm[1]);
    if (!name) { const am = /alt="([^"]+)"/.exec(inner); if (am) name = am[1]; }
    if (!name) continue;
    let pic = '';
    const imSet = /<img[^>]*srcSet="([^"]+)"/.exec(inner);
    const imSrc = /<img[^>]*src="([^"]+)"/.exec(inner);
    const imOrig = /data-original="([^"]+)"/.exec(inner);
    const bg = /background-image:url\((https?:[^)]+)\)/.exec(inner);
    const cand = (imOrig && imOrig[1]) || (imSet && imSet[1].split(',')[0].split(' ')[0]) || (imSrc && imSrc[1]) || (bg && bg[1]) || '';
    if (cand && cand.indexOf('site_logo') < 0 && cand.indexOf('data:') !== 0) pic = cand;
    let score = '';
    const sm = /<div[^>]*class="[^"]*score[^"]*"[^>]*>(.*?)<\/div>/.exec(inner);
    if (sm) score = stripTags(sm[1]);
    list.push({ vod_id: vodId, vod_name: name, vod_pic: pic, vod_remarks: score });
    if (list.length >= 48) break;
  }
  return list;
}
function v(n, val) { return { n: n, v: val == null ? '' : str(val) }; }

async function home(filter) {
  const classes = [
    { type_id: '1', type_name: '电影' },
    { type_id: '2', type_name: '电视剧' },
    { type_id: '3', type_name: '综艺' },
    { type_id: '4', type_name: '动漫' },
    { type_id: '88', type_name: '短剧' }
  ];
  const filters = {
    '1': [
      { key: 'class', name: '剧情', value: [v('全部', ''), v('喜剧', '喜剧'), v('动作', '动作'), v('爱情', '爱情'), v('科幻', '科幻'), v('悬疑', '悬疑'), v('奇幻', '奇幻'), v('恐怖', '恐怖'), v('剧情', '剧情'), v('犯罪', '犯罪'), v('动画', '动画'), v('惊悚', '惊悚'), v('战争', '战争'), v('冒险', '冒险'), v('灾难', '灾难'), v('伦理', '伦理'), v('其他', '其他')] },
      { key: 'area', name: '地区', value: [v('全部', ''), v('中国大陆', '中国大陆'), v('中国香港', '中国香港'), v('中国台湾', '中国台湾'), v('美国', '美国'), v('日本', '日本'), v('韩国', '韩国'), v('印度', '印度'), v('泰国', '泰国'), v('英国', '英国'), v('法国', '法国'), v('其他', '其他')] },
      { key: 'year', name: '年份', value: [v('全部', ''), v('2026', '2026'), v('2025', '2025'), v('2024', '2024'), v('2023', '2023'), v('2022', '2022'), v('2021', '2021'), v('2020', '2020'), v('2019', '2019'), v('2018', '2018'), v('2017', '2017'), v('2016', '2016'), v('2015', '2015'), v('2014', '2014'), v('2013', '2013'), v('2012', '2012'), v('2011', '2011'), v('2010', '2010'), v('2009~2000', '2009~2000')] },
      { key: 'lang', name: '语言', value: [v('全部', ''), v('国语', '国语'), v('英语', '英语'), v('粤语', '粤语'), v('韩语', '韩语'), v('日语', '日语'), v('其他', '其他')] }
    ],
    '2': [
      { key: 'type', name: '类型', value: [v('全部', ''), v('国产剧', '14'), v('欧美剧', '15'), v('港台剧', '16'), v('日韩剧', '62'), v('其他剧', '68')] },
      { key: 'class', name: '剧情', value: [v('全部', ''), v('古装', '古装'), v('战争', '战争'), v('喜剧', '喜剧'), v('家庭', '家庭'), v('犯罪', '犯罪'), v('动作', '动作'), v('奇幻', '奇幻'), v('剧情', '剧情'), v('历史', '历史'), v('短片', '短片'), v('其他', '其他')] },
      { key: 'area', name: '地区', value: [v('全部', ''), v('中国大陆', '中国大陆'), v('中国香港', '中国香港'), v('中国台湾', '中国台湾'), v('日本', '日本'), v('韩国', '韩国'), v('美国', '美国'), v('泰国', '泰国'), v('其他', '其他')] },
      { key: 'year', name: '年份', value: [v('全部', ''), v('2026', '2026'), v('2025', '2025'), v('2024', '2024'), v('2023', '2023'), v('2022', '2022'), v('2021', '2021'), v('2020', '2020'), v('2019', '2019'), v('2018', '2018'), v('2017', '2017'), v('2016', '2016'), v('2015', '2015'), v('2014', '2014'), v('2013', '2013'), v('2012', '2012'), v('2011', '2011'), v('2010', '2010')] },
      { key: 'lang', name: '语言', value: [v('全部', ''), v('国语', '国语'), v('英语', '英语'), v('粤语', '粤语'), v('韩语', '韩语'), v('日语', '日语'), v('泰语', '泰语'), v('其他', '其他')] }
    ],
    '3': [
      { key: 'type', name: '类型', value: [v('全部', ''), v('国产综艺', '69'), v('港台综艺', '70'), v('日韩综艺', '72'), v('欧美综艺', '73')] },
      { key: 'class', name: '剧情', value: [v('全部', ''), v('真人秀', '真人秀'), v('音乐', '音乐'), v('脱口秀', '脱口秀')] },
      { key: 'area', name: '地区', value: [v('全部', ''), v('中国大陆', '中国大陆'), v('中国香港', '中国香港'), v('中国台湾', '中国台湾'), v('日本', '日本'), v('韩国', '韩国'), v('美国', '美国'), v('其他', '其他')] },
      { key: 'year', name: '年份', value: [v('全部', ''), v('2026', '2026'), v('2025', '2025'), v('2024', '2024'), v('2023', '2023'), v('2022', '2022'), v('2021', '2021'), v('2020', '2020')] },
      { key: 'lang', name: '语言', value: [v('全部', ''), v('国语', '国语'), v('英语', '英语'), v('粤语', '粤语'), v('韩语', '韩语'), v('日语', '日语'), v('其他', '其他')] }
    ],
    '4': [
      { key: 'type', name: '类型', value: [v('全部', ''), v('国产动漫', '75'), v('日韩动漫', '76'), v('欧美动漫', '77')] },
      { key: 'class', name: '剧情', value: [v('全部', ''), v('喜剧', '喜剧'), v('科幻', '科幻'), v('热血', '热血'), v('冒险', '冒险'), v('动作', '动作'), v('运动', '运动'), v('战争', '战争'), v('动画', '动画')] },
      { key: 'area', name: '地区', value: [v('全部', ''), v('中国大陆', '中国大陆'), v('日本', '日本'), v('美国', '美国'), v('其他', '其他')] },
      { key: 'year', name: '年份', value: [v('全部', ''), v('2026', '2026'), v('2025', '2025'), v('2024', '2024'), v('2023', '2023'), v('2022', '2022'), v('2021', '2021'), v('2020', '2020'), v('2019', '2019'), v('2018', '2018'), v('2017', '2017'), v('2016', '2016'), v('2015', '2015'), v('2014', '2014'), v('2013', '2013'), v('2012', '2012'), v('2011', '2011'), v('2010', '2010')] },
      { key: 'lang', name: '语言', value: [v('全部', ''), v('国语', '国语'), v('英语', '英语'), v('日语', '日语'), v('其他', '其他')] }
    ],
    '88': [
      { key: 'type', name: '类型', value: [v('全部', ''), v('喜剧', '100'), v('奇幻', '99'), v('惊悚', '98'), v('悬疑', '97'), v('古装', '96'), v('爱情', '95'), v('剧情', '94')] },
      { key: 'class', name: '剧情', value: [v('全部', ''), v('逆袭', '逆袭'), v('甜宠', '甜宠'), v('虐恋', '虐恋'), v('穿越', '穿越'), v('重生', '重生'), v('剧情', '剧情'), v('科幻', '科幻'), v('武侠', '武侠'), v('爱情', '爱情'), v('动作', '动作'), v('战争', '战争'), v('冒险', '冒险'), v('其他', '其他')] },
      { key: 'year', name: '年份', value: [v('全部', ''), v('2026', '2026'), v('2025', '2025'), v('2024', '2024'), v('2023', '2023'), v('2022', '2022'), v('2021', '2021'), v('2020', '2020'), v('更早', '更早')] }
    ]
  };
  return output({ class: classes, filters: filters });
}

async function homeVod() {
  try {
    const html = await httpGet(baseUrl + '/');
    const ft = flightText(html);
    const keys = ['homeNewMoviePageData', 'homeBroadcastPageData', 'newestTvPageData', 'newestVarietyPageData', 'newestCartoonPageData', 'newestShortTvPageData'];
    let list = [];
    const seen = {};
    for (const k of keys) {
      const o = extractJsonByKey(ft, k);
      const arr = o && o.list ? o.list : null;
      if (arr) {
        for (const it of arr.slice(0, 6)) { const m = mapVodItem(it); if (m && !seen[m.vod_id]) { seen[m.vod_id] = 1; list.push(m); } }
      }
      if (list.length >= 12) break;
    }
    if (!list.length) list = parseCardsFallback(html);
    return output({ list: list.slice(0, 24) });
  } catch (e) { return output({ list: [] }); }
}

function buildCategoryUrl(tid, pg, extend) {
  extend = extend || {};
  let url = baseUrl + '/vod/show/id/' + encodeURIComponent(str(tid || '1'));
  const t = str(extend.type || '').trim();
  const c = str(extend.class || '').trim();
  const a = str(extend.area || '').trim();
  const y = str(extend.year || '').trim();
  const l = str(extend.lang || '').trim();
  if (t) url += '/type/' + encodeURIComponent(t);
  if (c) url += '/class/' + encodeURIComponent(c);
  if (a) url += '/area/' + encodeURIComponent(a);
  if (y) url += '/year/' + encodeURIComponent(y);
  if (l) url += '/lang/' + encodeURIComponent(l);
  const page = parseInt(pg, 10) || 1;
  if (page > 1) url += '/page/' + page;
  return { url: url, page: page };
}

async function category(tid, pg, filter, extend) {
  extend = extend || {};
  const built = buildCategoryUrl(tid, pg, extend);
  const page = built.page;
  try {
    const html = await httpGet(built.url);
    const ft = flightText(html);
    const vd = extractJsonByKey(ft, 'videoList');
    const data = vd && vd.data ? vd.data : vd;
    if (data && Array.isArray(data.list) && data.list.length) {
      const list = [];
      for (const it of data.list) { const m = mapVodItem(it); if (m) list.push(m); }
      return output({ list: list, page: Number(data.pageNum) || page, pagecount: Number(data.totalPage) || 1, limit: Number(data.pageSize) || 48, total: Number(data.totalCount) || list.length });
    }
    const fb = parseCardsFallback(html);
    return output({ list: fb, page: page, pagecount: fb.length ? page + 1 : 1, limit: 48, total: fb.length ? 9999 : 0 });
  } catch (e) { return output({ list: [], page: page, pagecount: 1, limit: 48, total: 0 }); }
}

function detailId(v) { const m = /(\d{4,})/.exec(str(v)); return m ? m[1] : str(v).trim(); }

async function detail(id) {
  const vid = detailId(id);
  try {
    const html = await httpGet(baseUrl + '/detail/' + vid);
    const ft = flightText(html);
    const get = function (k) {
      let m = new RegExp('"' + k + '":"(.*?)"').exec(ft);
      if (m) { try { return JSON.parse('"' + m[1] + '"'); } catch (e) { return m[1]; } }
      const m2 = new RegExp('"' + k + '":([^,}\\]]+)').exec(ft);
      return m2 ? m2[1].replace(/^"|"$/g, '') : '';
    };
    const vodName = get('vodName');
    if (!vodName && ft.indexOf('episodeList') < 0) return output({ list: [] });
    const vodId = get('vodId') || vid;
    const pic = get('vodPic');
    const actor = get('vodActor');
    const director = get('vodDirector');
    const contentRaw = get('vodContent') || get('vodBlurb');
    const area = get('vodArea');
    const lang = get('vodLang');
    let year = get('vodYear') || get('vodPubdate');
    const ym = /(\d{4})/.exec(str(year));
    if (ym) year = ym[1];
    const vclass = get('vodClass') || get('typeName');
    let remarks = str(get('vodRemarks') || get('vodVersion') || get('vodSerial'));
    const serial = get('vodSerial');
    const total = get('vodTotal');
    if (!remarks) { if (serial && total) remarks = '(' + serial + '/' + total + ')'; else if (serial) remarks = '(' + serial + ')'; }
    let eps = [];
    const epArr = extractJsonByKey(ft, 'episodeList');
    if (Array.isArray(epArr)) eps = epArr;
    else {
      const em = /"episodeList":\[([\s\S]*?)\]/.exec(ft);
      if (em) {
        try { eps = JSON.parse('[' + em[1] + ']'); }
        catch (e) {
          const re2 = /"nid":(\d+),"name":"(.*?)"/g;
          let mm; while ((mm = re2.exec(em[1])) !== null) eps.push({ nid: mm[1], name: mm[2] });
        }
      }
    }
    let playUrl = '';
    if (eps && eps.length) {
      const parts = [];
      for (const ep of eps) {
        const nid = str(ep.nid || '');
        let nm = str(ep.name || '正片').replace(/\$/g, '＄').replace(/#/g, '＃');
        if (!nid) continue;
        parts.push(nm + '$' + str(vodId) + '_' + nid);
      }
      playUrl = parts.join('#');
    }
    const vod = { vod_id: str(vodId), vod_name: vodName || ('ID_' + str(vodId)), vod_pic: pic, vod_actor: actor, vod_director: director, vod_content: stripTags(contentRaw), vod_area: area, vod_lang: lang, vod_year: str(year), type_name: vclass, vod_remarks: remarks, vod_play_from: playUrl ? '金牌影院' : '', vod_play_url: playUrl };
    return output({ list: [vod] });
  } catch (e) { return output({ list: [] }); }
}

async function search(key, quick, pg) {
  const wd = str(key || '').trim();
  const page = parseInt(pg, 10) || 1;
  if (!wd) return output({ list: [], page: page, pagecount: 1, limit: 48, total: 0 });
  try {
    let url = baseUrl + '/vod/search/' + encodeURIComponent(wd);
    if (page > 1) url += '?page=' + page;
    const html = await httpGet(url);
    const ft = flightText(html);
    let rs = extractJsonByKey(ft, 'result');
    if (rs && rs.list && rs.list.length) {
      const list = [];
      for (const it of rs.list) { const m = mapVodItem(it); if (m) list.push(m); }
      return output({ list: list, page: Number(rs.pageNum) || page, pagecount: Number(rs.totalPage) || 1, limit: Number(rs.pageSize) || 48, total: Number(rs.totalCount) || list.length });
    }
    const vd = extractJsonByKey(ft, 'videoList');
    const data = vd && vd.data ? vd.data : null;
    if (data && data.list && data.list.length) {
      const list = [];
      for (const it of data.list) { const m = mapVodItem(it); if (m) list.push(m); }
      return output({ list: list, page: Number(data.pageNum) || page, pagecount: Number(data.totalPage) || 1, limit: Number(data.pageSize) || 48, total: Number(data.totalCount) || list.length });
    }
    const fb = parseCardsFallback(html);
    return output({ list: fb, page: page, pagecount: fb.length ? page + 1 : 1, limit: 48, total: fb.length ? 9999 : 0 });
  } catch (e) { return output({ list: [], page: page, pagecount: 1, limit: 48, total: 0 }); }
}

async function play(flag, id, vipFlags) {
  const s = str(id || '');
  let vodId = '', nid = '';
  const m = /(\d+)_(\d+)/.exec(s);
  if (m) { vodId = m[1]; nid = m[2]; }
  else { const nums = s.match(/\d+/g) || []; if (nums.length >= 2) { vodId = nums[nums.length - 2]; nid = nums[nums.length - 1]; } }
  let playPage = s;
  if (vodId && nid) playPage = baseUrl + '/vod/play/' + vodId + '/sid/' + nid;
  else if (s.indexOf('http') === 0) playPage = s;
  try {
    const html = await httpGet(playPage);
    const all = flightText(html) + '\n' + str(html);
    const m3 = /(https?:[^"'\\s<>]+\.m3u8[^"'\\s<>]*)/i.exec(all);
    if (m3) return output({ parse: 0, url: m3[1], header: PLAY_HEADERS });
    const mp4 = /(https?:[^"'\\s<>]+\.mp4[^"'\\s<>]*)/i.exec(all);
    if (mp4) return output({ parse: 0, url: mp4[1], header: PLAY_HEADERS });
    return output({ parse: 1, url: playPage, header: HEADERS });
  } catch (e) { return output({ parse: 1, url: playPage, header: HEADERS }); }
}

async function homeContent(filter) { return home(filter); }
async function homeVideoContent() { return homeVod(); }
async function categoryContent(tid, pg, filter, extend) { return category(tid, pg, filter, extend); }
async function detailContent(ids) { const id = Array.isArray(ids) ? ids[0] : ids; return detail(id); }
async function searchContent(key, quick, pg) { return search(key, quick, pg); }
async function playerContent(flag, id, vipFlags) { return play(flag, id, vipFlags); }

export default { init, home, homeVod, category, detail, search, play, live, proxy, action, sniffer, isVideo, destroy, homeContent, homeVideoContent, categoryContent, detailContent, searchContent, playerContent };
