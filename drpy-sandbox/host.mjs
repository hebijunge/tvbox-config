/**
 * drpy2 引擎的 Node 宿主（沙箱）。
 *
 * 为什么要它：`type 3` 的本地 JS 源（351 个）真实响应只在运行时才拿得到，外部 HTTP 探针
 * 只能查到「规则文件在不在、模板能不能拼」，拿不到「它到底能不能搜到片」。
 *
 * 契约来自对引擎源码的阅读（`lib/drpy2.min.js`）：
 *   - 引擎 `request(url,obj)` 里调的是**宿主的 `req(url,obj)`**，并且要求返回 `{content, headers}`；
 *   - 调用是**同步**的（`let res = req(url, obj)`，没有 await）—— 这是 TVBox 的 QuickJS 原生阻塞调用，
 *     所以 Node 侧用 `curl` 同步子进程实现，而不是 fetch；
 *   - 宿主还需提供 `pdfh` / `pdfa` / `pd` / `pdr` / `HTML` / `local`；
 *     其余（getItem/setItem/getHome/checkHtml/jsp/getProxyUrl/md5/base64/gzip…）引擎自带。
 *   - 引擎导出 `init(ext)` / `home(filter,html,class_parse)` / `homeVod` / `category(tid,pg,filter,extend)`
 *     / `detail(url)` / `play(flag,id,flags)` / `search(wd,quick,pg)`，`init` 接受**规则 JS 源码字符串**。
 *
 * 用法：
 *   node host.mjs --rule <规则文件路径> --op home --out <结果json>
 *   node host.mjs --rule a.js --op search --kw 庆余年
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const LOCAL_FILE = path.join(HERE, 'state-locals.json');
const UA_MOBILE = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36';

// 引擎会疯狂 console.log，把它赶到 stderr，保证 stdout 只有一行结果 JSON
const realLog = console.log.bind(console);
console.log = (...a) => { if (VERBOSE) process.stderr.write('[js] ' + a.join(' ') + '\n'); };
globalThis.print = (...a) => console.log(...a);

let VERBOSE = process.argv.includes('--verbose');

// ---------------- local 存储 ----------------
let locals = {};
try { locals = JSON.parse(fs.readFileSync(LOCAL_FILE, 'utf8')); } catch { locals = {}; }
function saveLocals() { try { fs.writeFileSync(LOCAL_FILE, JSON.stringify(locals)); } catch { /* 忽略 */ } }

// ---------------- 同步 HTTP（curl）----------------
const CURL = process.platform === 'win32' ? 'curl.exe' : 'curl';
let REQ_COUNT = 0;
let LAST_ERR = '';

function parseHeaders(txt) {
  const lines = txt.split(/\r?\n/).filter(Boolean);
  const out = { 'content-type': '' };
  // 跟随重定向后会有多段响应头，取最后一段（真实响应）
  let last = [];
  for (const ln of lines) {
    if (/^HTTP\//i.test(ln)) last = [];
    else last.push(ln);
  }
  for (const ln of last) {
    const i = ln.indexOf(':');
    if (i > 0) out[ln.slice(0, i).trim().toLowerCase()] = ln.slice(i + 1).trim();
  }
  return out;
}

function decodeBody(buf, charset) {
  const cs = (charset || 'utf-8').toLowerCase().replace(/["']/g, '');
  try {
    return new TextDecoder(cs).decode(buf);
  } catch {
    try { return new TextDecoder('utf-8').decode(buf); } catch { return buf.toString('latin1'); }
  }
}

globalThis.req = function req(url, obj) {
  obj = obj || {};
  REQ_COUNT++;
  const timeoutMs = Number(obj.timeout) > 0 ? Number(obj.timeout) : 15000;
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'drpy-'));
  const hf = path.join(tmp, 'h.txt');
  const bf = path.join(tmp, 'b.bin');
  const args = ['-sS', '-L', '--max-time', String(Math.max(3, Math.ceil(timeoutMs / 1000))),
                '-D', hf, '-o', bf];
  const method = String(obj.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'POST') args.push('-X', method);
  if (method === 'POST') args.push('-X', 'POST');
  const headers = obj.headers || {};
  for (const [k, v] of Object.entries(headers)) {
    if (v !== null && v !== undefined && v !== '') args.push('-H', `${k}: ${v}`);
  }
  let body = null;
  if (typeof obj.body === 'string') body = obj.body;
  else if (obj.data && typeof obj.data === 'object') body = new URLSearchParams(obj.data).toString();
  if (body !== null) args.push('--data-binary', body);
  args.push(url);

  let failed = null;
  try {
    execFileSync(CURL, args, { stdio: 'ignore', timeout: timeoutMs + 6000 });
  } catch (e) {
    failed = e && e.message ? e.message.split('\n')[0] : String(e);
  }
  LAST_ERR = failed || '';

  let raw = Buffer.alloc(0);
  let htxt = '';
  try { raw = fs.readFileSync(bf); } catch { raw = Buffer.alloc(0); }
  try { htxt = fs.readFileSync(hf, 'utf8'); } catch { htxt = ''; }
  try { fs.rmSync(tmp, { recursive: true, force: true }); } catch { /* 忽略 */ }

  const hdrs = parseHeaders(htxt);
  if (failed && raw.length === 0) {
    return { content: '', headers: hdrs, __err: failed };
  }
  if (obj.buffer || obj.toBase64) {
    return { content: raw.toString('base64'), headers: hdrs };
  }
  // 编码优先级：obj.encoding > 响应头 charset > utf-8
  let charset = obj.encoding;
  if (!charset && hdrs['content-type']) {
    const m = /charset=([\w-]+)/i.exec(hdrs['content-type']);
    if (m) charset = m[1];
  }
  return { content: decodeBody(raw, charset), headers: hdrs };
};

// ---------------- local ----------------
globalThis.local = {
  get: (k, d) => (k in locals ? locals[k] : (d === undefined ? '' : d)),
  set: (k, v) => { locals[k] = v; saveLocals(); },
  delete: (k) => { delete locals[k]; saveLocals(); },
};

// ---------------- HTML 解析：pdfh / pdfa / pd / pdr ----------------
// 引擎与运行时：优先复用仓库内已有的 lib/drpy2.min.js（用户配置里 api 指向的就是它），
// 避免仓库里存两份大文件；找不到再退回沙箱自带副本。这样 CI 与本地都能直接跑。
function pickFile(cands) {
  for (const p of cands) {
    try { if (fs.existsSync(p)) return p; } catch { /* 继续找下一个候选 */ }
  }
  return cands[cands.length - 1];
}
const CORE_FILE = pickFile([
  path.join(HERE, 'drpy-core-lite.min.js'),
  path.join(HERE, '..', 'lib', 'drpy-core-lite.min.js'),
]);
// 注意顺序：引擎 drpy2.min.js 内部会「相对自身所在目录」去 import drpy-core-lite.min.js，
// 所以必须与 core-lite 同目录。若直接用 lib/ 下那份引擎，它会去 lib/ 找 core-lite 而失败
// （实测踩过：ERR_MODULE_NOT_FOUND）。故优先用沙箱自带的这一份。
const ENGINE_FILE = pickFile([
  path.join(HERE, 'drpy2.min.js'),
  path.join(HERE, '..', 'lib', 'drpy2.min.js'),
]);
const core = await import(pathToFileURL(CORE_FILE).href);

// 注意：core 导出的 `cheerio` **不是** cheerio 本身，而是 `{ jinja2, jp }`
// （引擎正是用 `cheerio.jp(...)` / `cheerio.jinja2(...)`，所以版本是配的）。
// pdfh/pdfa 需要真正的 HTML 解析器，所以沙箱里单独装了一份 cheerio。
const cheerio = await import('cheerio');

// core（drpy-core-lite）导出的这几个，就是**宿主需要装成全局**的运行时能力 ——
// 引擎只 import 了 cheerio/模板，但直接当全局用 pako / gbkTool / NODERSA
// （实测：`init_test` 第一句就报 `joinUrl is not defined`，随后 pako/gbkTool 也会缺）。
for (const name of ['pako', 'jinja', 'gbkTool', 'NODERSA', 'TextDecoder', 'TextEncoder']) {
  if (globalThis[name] === undefined && core[name] !== undefined) {
    try { globalThis[name] = core[name]; } catch { /* 只读全局，忽略 */ }
  }
}

/** 宿主提供的 URL 拼接（引擎的 urljoin 直接调它） */
globalThis.joinUrl = function joinUrl(from, to) {
  from = from || '';
  to = to || '';
  if (!to) return from;
  if (/^https?:\/\//i.test(to)) return to;
  if (!from) return to;
  try {
    return new URL(to, from).toString();
  } catch {
    return String(from).replace(/\/+$/, '') + '/' + String(to).replace(/^\/+/, '');
  }
};

function load$(html) {
  try { return cheerio.load(String(html == null ? '' : html), { decodeEntities: false }); }
  catch { return cheerio.load(''); }
}

const ATTR_ONLY = /^(href|src|title|alt|data-\S+|onclick|value|id|class|style|content|datetime|index|for|name|type|target|rel|width|height|poster|data-original|data-src|data-video)$/i;

function pick(node, field) {
  const $ = node.$;
  const f = String(field || 'Text').trim();
  if (!$) return '';
  if (/^(Text|text|TextTrim)$/.test(f)) {
    const t = $(node.el).text();
    return f === 'TextTrim' ? t.trim() : t;
  }
  if (/^(Html|html)$/.test(f)) return $(node.el).html() || '';
  // 其余当属性名
  const v = $(node.el).attr(f);
  return v === undefined || v === null ? '' : v;
}

/** 把 `a&&b&&Text` 拆成 选择器数组 + 字段；末段一律当字段（TVBox 的口径） */
function splitRule(rule) {
  const segs = String(rule).split('&&').map(s => s.trim()).filter(s => s.length > 0);
  if (segs.length === 0) return { sels: [], field: 'Text' };
  if (segs.length === 1) {
    // 只有一段：是字段还是选择器？按属性名判断
    return ATTR_ONLY.test(segs[0]) ? { sels: [], field: segs[0] } : { sels: segs, field: 'Text' };
  }
  return { sels: segs.slice(0, -1), field: segs[segs.length - 1] };
}

function collect(html, rule) {
  const $ = load$(html);
  const { sels, field } = splitRule(rule);
  let nodes = [{ $, el: $.root()[0] }];
  for (const s of sels) {
    const next = [];
    for (const n of nodes) {
      $(n.el).find(s).each((_, el) => next.push({ $, el }));
    }
    nodes = next;
    if (nodes.length === 0) return { out: [], field, $ };
  }
  return { out: nodes, field, $ };
}

globalThis.pdfh = function pdfh(html, rule, base) {
  const { out, field } = collect(html, rule);
  if (out.length === 0) return '';
  return pick(out[0], field);
};

globalThis.pdfa = function pdfa(html, rule) {
  const { out, field, $ } = collect(html, rule);
  // drpy 对 class_parse 等"第一层纯选择器"的用法：先 pdfa 取节点 outerHTML 数组，
  // 再对每个节点链式解析 `a&&Text;a&&href` 等。因此纯选择器（无 && 字段段）必须返回
  // 节点 HTML，而不能提前提取 Text——否则后续链式拿不到 <a> 标签而报 null[1]。
  if (!String(rule == null ? '' : rule).includes('&&')) {
    return out.map(n => $.html(n.el));
  }
  return out.map(n => pick(n, field));
};

/** pd：支持 `选择器;属性;下标` 的写法，缺省下标 0 */
globalThis.pd = function pd(html, rule, base) {
  const parts = String(rule).split(';').map(s => s.trim());
  const sels = parts[0].split('&&').map(s => s.trim()).filter(Boolean);
  const attr = parts.length > 1 && parts[1] ? parts[1] : 'Text';
  const idx = parts.length > 2 && parts[2] !== '' ? parseInt(parts[2], 10) || 0 : 0;
  const { out } = collect(html, sels.join('&&'));
  if (out.length <= idx) return '';
  return pick(out[idx], attr);
};

/** pdr：返回匹配节点的 outerHTML 数组 */
globalThis.pdr = function pdr(html, rule, index) {
  const $ = load$(html);
  const { out } = collect(html, rule);
  const htmls = out.map(n => $.html(n.el));
  if (index === undefined || index === null || index === '') return htmls;
  const i = parseInt(index, 10) || 0;
  return htmls[i] === undefined ? '' : htmls[i];
};

globalThis.HTML = function HTML(html) { return load$(html); };

// ---------------- 驱动 ----------------
function argOf(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i > 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : dflt;
}

function safe(fn) {
  try {
    return { ok: true, data: fn() };
  } catch (e) {
    return { ok: false, err: `${e && e.name ? e.name : 'Error'}: ${e && e.message ? e.message : e}` };
  }
}

// 引擎是 `export default { runMain, getRule, init, home, ... }`，函数都在 default 上
const mod = await import(pathToFileURL(ENGINE_FILE).href);
const engine = mod.default ?? mod;

function toObj(s) {
  if (typeof s !== 'string') return s;
  const t = s.trim();
  if (!t) return null;
  try { return JSON.parse(t); } catch { return null; }
}

const ruleFile = argOf('rule');
const op = argOf('op', 'home');
const t0 = Date.now();
const r = { rule: ruleFile, op };

try {
  const src = fs.readFileSync(ruleFile, 'utf8');
  const initRes = safe(() => engine.init(src));
  if (!initRes.ok) throw new Error('init 失败: ' + initRes.err);
  r.rule_keys = Object.keys(engine.getRule() || {}).length;

  if (op === 'home') {
    const res = safe(() => engine.home('', '', ''));
    r.ok = res.ok && !!toObj(res.data);
    r.raw_len = res.ok ? String(res.data || '').length : 0;
    const o = toObj(res.data);
    r.classes = o && Array.isArray(o.class) ? o.class.length : 0;
    r.has_list = !!(o && (o.list || o.videos));
    r.class_ref = o && Array.isArray(o.class) && o.class.length ? o.class[0].type_id : null;
    if (!res.ok) r.err = res.err;
  } else if (op === 'category') {
    const tid = argOf('tid');
    const pg = argOf('pg', '1');
    const res = safe(() => engine.category(tid, pg, '{}', '{}'));
    const o = toObj(res.ok ? res.data : null);
    r.ok = !!(o && (o.list || o.videos) && (o.list || o.videos).length > 0);
    r.items = o ? ((o.list || o.videos) || []).length : 0;
    if (!res.ok) r.err = res.err;
  } else if (op === 'search') {
    const kw = argOf('kw', '庆余年');
    const res = safe(() => engine.search(kw, false, '1'));
    const o = toObj(res.ok ? res.data : null);
    r.ok = !!(o && (o.list || o.videos) && (o.list || o.videos).length > 0);
    r.hits = o ? ((o.list || o.videos) || []).length : 0;
    r.first_id = o && (o.list || o.videos) && (o.list || o.videos)[0] ? (o.list || o.videos)[0].vod_id : null;
    if (!res.ok) r.err = res.err;
  } else if (op === 'detail') {
    const id = argOf('id');
    const res = safe(() => engine.detail(id));
    const o = toObj(res.ok ? res.data : null);
    const first = o && o.list && o.list[0];
    r.ok = !!(first && first.vod_play_url);
    r.play_url_len = first && first.vod_play_url ? String(first.vod_play_url).length : 0;
    if (!res.ok) r.err = res.err;
  } else if (op === 'play') {
    const flag = argOf('flag', '');
    const id = argOf('id');
    const res = safe(() => engine.play(flag, id, []));
    const o = toObj(res.ok ? res.data : null);
    r.ok = !!(o && (o.url || (o.urls && o.urls.length)));
    r.play = o ? String(o.url || (o.urls && o.urls[0] && o.urls[0].url) || '').slice(0, 140) : '';
    if (!res.ok) r.err = res.err;
  } else if (op === 'all') {
    // 一次进程跑完五关（home → category → search → detail → play），
    // 省掉每个源起多次 Node 的开销。
    const kw = argOf('kw', '庆余年');

    const h = safe(() => engine.home('', '', ''));
    const ho = toObj(h.ok ? h.data : null);
    const classes = ho && Array.isArray(ho.class) ? ho.class : [];
    r.home = !!(ho && (classes.length > 0 || (ho.list && ho.list.length)));
    r.classes = classes.length;
    if (!h.ok) r.home_err = h.err;

    if (classes.length) {
      const tid = classes[0].type_id;
      const c = safe(() => engine.category(tid, '1', '{}', '{}'));
      const co = toObj(c.ok ? c.data : null);
      const clist = co ? (co.list || co.videos || []) : [];
      r.cat = clist.length > 0;
      r.cat_items = clist.length;
      if (!c.ok) r.cat_err = c.err;
    }

    const s = safe(() => engine.search(kw, false, '1'));
    const so = toObj(s.ok ? s.data : null);
    const slist = so ? (so.list || so.videos || []) : [];
    r.search = slist.length > 0;
    r.hits = slist.length;
    if (!s.ok) r.search_err = s.err;

    if (slist.length) {
      const id = slist[0].vod_id;
      const d = safe(() => engine.detail(id));
      const dObj = toObj(d.ok ? d.data : null);
      const first = dObj && dObj.list && dObj.list[0];
      r.detail = !!(first && first.vod_play_url);
      if (!d.ok) r.detail_err = d.err;
      if (r.detail) {
        // 播放串形如 "线路1$id1#线路2$id2"，取第一条
        const froms = String(first.vod_play_from || '').split('$$$');
        const groups = String(first.vod_play_url).split('$$$');
        const firstGroup = groups[0] || '';
        const ep = firstGroup.split('#')[0] || '';
        const parts = ep.split('$');
        const pid = parts.length > 1 ? parts[1] : parts[0];
        const p = safe(() => engine.play(froms[0] || '', pid, []));
        const po = toObj(p.ok ? p.data : null);
        r.play = !!(po && (po.url || (po.urls && po.urls.length)));
        r.play_url = po ? String(po.url || (po.urls && po.urls[0] && po.urls[0].url) || '').slice(0, 140) : '';
        if (po && po.parse !== undefined) r.parse = po.parse;
        if (!p.ok) r.play_err = p.err;
      }
    }
  } else {
    r.err = 'unknown op: ' + op;
  }
} catch (e) {
  r.ok = false;
  r.err = `${e && e.name ? e.name : 'Error'}: ${e && e.message ? e.message : e}`;
}

r.reqs = REQ_COUNT;
r.ms = Date.now() - t0;
if (REQ_COUNT === 0 && LAST_ERR) r.net_err = LAST_ERR;
realLog(JSON.stringify(r));
