// ============================================================
// 黄果短剧 TVBox 源（FongMi / catvod quickjs 兼容）
// 特性：多域名容灾自动切换 · 封面 AES 解密代理 · 分类/搜索/详情/播放
// 站点：wbydq.juatinpqz.com / g90jqd.juatinpqz.com / goxq.juatinpqz.com
// ============================================================

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

// 域名池：写在前面的优先用，请求失败自动切下一个
const HOSTS = [
    'https://wbydq.juatinpqz.com',
    'https://g90jqd.juatinpqz.com',
    'https://goxq.juatinpqz.com'
]
let HIDX = 0

const SITE_KEY = 'huangguo'
const PLAYLIST = '黄果短剧'
// 封面图为 AES-128-CBC 密文；key/iv 取自站端 crypto-worker，padding 为 NoPadding
const IMG_KEY = 'f5d965df75336270'
const IMG_IV = '97b60394abc2fbe1'

const CLASSES = [
    { type_id: 'ai-duanju', type_name: '🔞 AI成人短剧' },
    { type_id: 'ai-manju', type_name: '🎨 AI成人漫剧' },
    { type_id: 'ai-huanlian', type_name: '🔄 AI换脸' },
    { type_id: 'ai-mogai', type_name: '✨ AI魔改' },
    { type_id: 'newest', type_name: '🆕 最新更新' },
    { type_id: 'recommend', type_name: '👍 编辑推荐' },
    { type_id: 'ranks/hot', type_name: '🔥 热播榜' },
    { type_id: 'tag/xiaoyuan', type_name: '🏫 校园' },
    { type_id: 'tag/mingxing', type_name: '⭐ 明星' },
    { type_id: 'tag/wanghong', type_name: '📱 网红' },
    { type_id: 'tag/dushi', type_name: '🏙 都市' },
    { type_id: 'tag/xitong', type_name: '🎮 系统' },
    { type_id: 'tag/luanlun', type_name: '🔒 禁忌' }
]

// ---------- 基础工具 ----------
function host() {
    return HOSTS[HIDX]
}

function hdrs(ref) {
    return {
        'User-Agent': UA,
        Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        Referer: (ref || host()) + '/'
    }
}

function stripTags(s) {
    return String(s || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
}

// 相对路径 → 绝对地址
function abs(u) {
    if (!u) return ''
    if (u.indexOf('//') === 0) return 'https:' + u
    if (u.indexOf('http') === 0) return u
    if (u.indexOf('/') === 0) return host() + u
    return host() + '/' + u
}

// 绝对地址 → 相对路径（存进播放列表，域名换了照样能播）
function rel(u) {
    if (!u) return ''
    let s = String(u)
    for (let i = 0; i < HOSTS.length; i++) {
        if (s.indexOf(HOSTS[i]) === 0) return s.slice(HOSTS[i].length)
    }
    try {
        const m = s.match(/^https?:\/\/[^\/]+(\/.*)$/)
        if (m) return m[1]
    } catch (e) {}
    return s
}

// 按路径抓取，失败自动切换域名
function fetchPath(path, buffer) {
    if (!path) return ''
    if (path.indexOf('http') === 0) return fetchUrl(path, buffer)
    for (let i = 0; i < HOSTS.length; i++) {
        const idx = (HIDX + i) % HOSTS.length
        try {
            const res = req(HOSTS[idx] + path, { buffer: buffer || 0, headers: hdrs(HOSTS[idx]) })
            if (res && String(res.code) === '200' && res.content) {
                HIDX = idx
                return res.content
            }
        } catch (e) {}
    }
    return ''
}

// 抓绝对地址（默认文本，buffer=2 拿 base64）
function fetchUrl(url, buffer) {
    if (!url) return ''
    try {
        const res = req(url, { buffer: buffer || 0, headers: hdrs() })
        if (!res || String(res.code) !== '200') return ''
        return res.content || ''
    } catch (e) {
        return ''
    }
}

// 封面 → 本地解密代理（走 JS proxy 方法）
function imgProxy(u) {
    u = abs(u)
    if (!u) return ''
    try {
        return js2Proxy(false, 3, SITE_KEY, u, {})
    } catch (e) {
        return u
    }
}

function isImgB64(b64) {
    if (!b64) return false
    return b64.indexOf('/9j/') === 0 || b64.indexOf('iVBOR') === 0 ||
        b64.indexOf('R0lGOD') === 0 || b64.indexOf('UklGR') === 0
}

function imgMime(url, b64) {
    if (b64) {
        if (b64.indexOf('iVBOR') === 0) return 'image/png'
        if (b64.indexOf('R0lGOD') === 0) return 'image/gif'
        if (b64.indexOf('UklGR') === 0) return 'image/webp'
        if (b64.indexOf('/9j/') === 0) return 'image/jpeg'
    }
    const m = String(url || '').match(/\.(jpg|jpeg|png|gif|webp|bmp)(\?|$)/i)
    return m ? 'image/' + (m[1].toLowerCase() === 'jpg' ? 'jpeg' : m[1].toLowerCase()) : 'image/jpeg'
}

// ---------- 列表卡片解析 ----------
function gridSlices(html, all) {
    const re = /<div\s+class="[^"]*\bhg-card-grid\b[^"]*"[^>]*>/g
    const starts = []
    let m
    while ((m = re.exec(html)) !== null) starts.push(m.index + m[0].length)
    if (!starts.length) return []
    const n = all ? starts.length : Math.min(1, starts.length)
    const out = []
    for (let i = 0; i < n; i++) {
        const to = i + 1 < starts.length ? starts[i + 1] : html.length
        out.push(html.slice(starts[i], to))
    }
    return out
}

function cardBlocks(slice) {
    const re = /<div\s+class="[^"]*\bhg-drama-card\b[^"]*"[^>]*>/g
    const starts = []
    let m
    while ((m = re.exec(slice)) !== null) starts.push(m.index + m[0].length)
    const out = []
    for (let i = 0; i < starts.length; i++) {
        const to = i + 1 < starts.length ? starts[i + 1] : slice.length
        out.push(slice.slice(starts[i], to))
    }
    return out
}

function parseCard(b) {
    const a = b.match(/href="[^"]*\/detail\/(\d+)\/[^"]*"/)
    if (!a) return null
    let title = ''
    const t = b.match(/hg-drama-card__title[^>]*>([\s\S]*?)<\/a>/)
    if (t) title = stripTags(t[1])
    if (!title) {
        const alt = b.match(/<img[^>]+alt="([^"]+)"/)
        if (alt) title = stripTags(alt[1])
    }
    if (!title) return null
    const img = b.match(/data-src="([^"]+)"/) || b.match(/<img[^>]+src="([^"]+)"/)
    const ep = b.match(/hg-drama-card__episode[^>]*>([\s\S]*?)<\/span>/)
    const sc = b.match(/hg-drama-card__score[^>]*>([\s\S]*?)<\/span>/)
    const tg = b.match(/hg-drama-card__tags[^>]*>([\s\S]*?)<\/div>/)
    const parts = []
    if (ep) parts.push(stripTags(ep[1]))
    if (sc) parts.push(stripTags(sc[1]))
    if (!parts.length && tg) parts.push(stripTags(tg[1]))
    return {
        vod_id: a[1],
        vod_name: title,
        vod_pic: imgProxy(img ? img[1] : ''),
        vod_remarks: parts.join(' · ').slice(0, 40)
    }
}

function parseCards(html, all) {
    if (!html) return []
    const out = []
    const seen = {}
    const slices = gridSlices(html, all)
    for (let i = 0; i < slices.length; i++) {
        const blocks = cardBlocks(slices[i])
        for (let j = 0; j < blocks.length; j++) {
            try {
                const it = parseCard(blocks[j])
                if (!it || seen[it.vod_id]) continue
                seen[it.vod_id] = 1
                out.push(it)
            } catch (e) {}
        }
    }
    // 兜底：页面没有 card 容器时，直接扫详情链接
    if (!out.length) {
        const re = /href="\/detail\/(\d+)\/"/g
        let m
        while ((m = re.exec(html)) !== null) {
            if (seen[m[1]]) continue
            seen[m[1]] = 1
            out.push({ vod_id: m[1], vod_name: '剧集 ' + m[1], vod_pic: '', vod_remarks: '' })
        }
    }
    return out
}

// 首页轮播（内嵌 JSON，含广告项需过滤）
function parseHero(html) {
    const out = []
    try {
        const m = html.match(/data-hero-slides[^>]*>([\s\S]*?)<\/script>/)
        if (!m) return out
        const arr = JSON.parse(m[1])
        for (let i = 0; i < arr.length; i++) {
            const it = arr[i] || {}
            if (it.isAd || it.linkUrl) continue
            const dm = String(it.detailHref || '').match(/\/detail\/(\d+)/)
            if (!dm) continue
            const rem = []
            if (it.episode) rem.push(it.episode)
            if (it.score) rem.push(it.score + '分')
            out.push({
                vod_id: dm[1],
                vod_name: it.title || '',
                vod_pic: imgProxy(it.cover || it.thumb || ''),
                vod_remarks: rem.join(' · ').slice(0, 40)
            })
        }
    } catch (e) {}
    return out
}

// 精选条目（分类页/首页的横向推荐）
function parseCatItems(html) {
    const out = []
    try {
        const re = /<a[^>]*class="[^"]*\bhg-category-item\b[^"]*"[^>]*>/g
        const starts = []
        let m
        while ((m = re.exec(html)) !== null) starts.push(m.index)
        for (let i = 0; i < starts.length; i++) {
            const to = i + 1 < starts.length ? starts[i + 1] : Math.min(html.length, starts[i] + 1400)
            const b = html.slice(starts[i], to)
            const h = b.match(/href="\/detail\/(\d+)\/"/)
            if (!h) continue
            const t = b.match(/hg-category-item__title[^>]*>([\s\S]*?)<\/div>/)
            if (!t) continue
            const name = stripTags(t[1])
            if (!name) continue
            const img = b.match(/data-src="([^"]+)"/)
            const desc = b.match(/hg-category-item__desc[^>]*>([\s\S]*?)<\/p>/)
            out.push({
                vod_id: h[1],
                vod_name: name,
                vod_pic: imgProxy(img ? img[1] : ''),
                vod_remarks: desc ? stripTags(desc[1]).slice(0, 30) : ''
            })
        }
    } catch (e) {}
    return out
}

function mergeList() {
    const out = []
    const seen = {}
    for (let i = 0; i < arguments.length; i++) {
        const arr = arguments[i] || []
        for (let j = 0; j < arr.length; j++) {
            const it = arr[j]
            if (!it || !it.vod_id || seen[it.vod_id]) continue
            seen[it.vod_id] = 1
            out.push(it)
        }
    }
    return out
}

// 热播榜
function parseRanks(html) {
    if (!html) return []
    const lm = html.match(/<div\s+class="[^"]*\bhg-rank-list\b[^"]*"[^>]*>/)
    const from = lm ? lm.index + lm[0].length : 0
    const slice = html.slice(from)
    const re = /<div\s+class="[^"]*\bhg-rank-item\b[^"]*"[^>]*>/g
    const starts = []
    let m
    while ((m = re.exec(slice)) !== null) starts.push(m.index + m[0].length)
    const out = []
    const seen = {}
    for (let i = 0; i < starts.length; i++) {
        const to = i + 1 < starts.length ? starts[i + 1] : slice.length
        const b = slice.slice(starts[i], to)
        try {
            const a = b.match(/href="[^"]*\/detail\/(\d+)\/[^"]*"/)
            if (!a || seen[a[1]]) continue
            let title = ''
            const t = b.match(/hg-rank-item__title[^>]*>([\s\S]*?)<\/h2>/)
            if (t) title = stripTags(t[1])
            if (!title) {
                const alt = b.match(/<img[^>]+alt="([^"]+)"/)
                if (alt) title = stripTags(alt[1])
            }
            if (!title) continue
            seen[a[1]] = 1
            const img = b.match(/data-src="([^"]+)"/) || b.match(/<img[^>]+src="([^"]+)"/)
            const tags = b.match(/hg-rank-item__tags[^>]*>([\s\S]*?)<\/div>/)
            out.push({
                vod_id: a[1],
                vod_name: title,
                vod_pic: imgProxy(img ? img[1] : ''),
                vod_remarks: tags ? stripTags(tags[1]) : ''
            })
        } catch (e) {}
    }
    return out
}

// ---------- 接口实现 ----------
function init(ext) {
    for (let i = 0; i < HOSTS.length; i++) {
        try {
            const res = req(HOSTS[i] + '/', { buffer: 0, headers: hdrs(HOSTS[i]) })
            if (res && String(res.code) === '200' && res.content) {
                HIDX = i
                break
            }
        } catch (e) {}
    }
    return ''
}

function home(filter) {
    const html = fetchPath('/')
    const list = mergeList(parseHero(html), parseCards(html, true), parseCatItems(html))
    return JSON.stringify({ class: CLASSES, list: list })
}

function homeVod() {
    return JSON.stringify({ list: [] })
}

// 支持分页的分类（站点 /tid/页码/ 格式）
const PAGED = { 'ai-duanju': 1, 'ai-manju': 1, 'ai-huanlian': 1, 'ai-mogai': 1 }

function category(tid, pg, filter, extend) {
    tid = String(tid || 'ai-duanju').replace(/^\//, '').replace(/\/$/, '')
    pg = Math.max(1, parseInt(pg) || 1)
    try {
        if (tid === 'ranks/hot') {
            const html = fetchPath('/ranks/hot/')
            let list = parseRanks(html)
            if (!list.length) list = parseCards(html, true)
            return JSON.stringify({ page: 1, pagecount: 1, limit: list.length, list: list })
        }
        const paged = !!PAGED[tid]
        let url
        if (tid === 'newest' || tid === 'recommend') {
            url = '/' + tid
        } else {
            url = '/' + tid + '/' + (paged && pg > 1 ? pg + '/' : '')
        }
        const html = fetchPath(url)
        let list = parseCards(html, true)
        if (pg === 1) list = mergeList(parseHero(html), list)
        return JSON.stringify({
            page: pg,
            pagecount: paged ? 30 : 1,
            limit: list.length,
            list: list
        })
    } catch (e) {
        return JSON.stringify({ page: pg, pagecount: 1, limit: 0, list: [] })
    }
}

function detail(ids) {
    const id = String(ids || '').replace(/[^0-9]/g, '')
    if (!id) return JSON.stringify({ list: [] })
    try {
        const html = fetchPath('/detail/' + id + '/')
        if (!html) return JSON.stringify({ list: [] })

        let name = ''
        const h1 = html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)
        if (h1) name = stripTags(h1[1])
        if (!name) {
            const og = html.match(/property="og:title"\s+content="([^"]*)"/)
            if (og) name = og[1].replace(/\s*[-|]\s*黄果.*$/i, '').trim()
        }
        if (!name) name = '黄果短剧 ' + id

        let pic = ''
        const poster = html.match(/hg-web-detail__poster[^>]*>[\s\S]{0,400}?data-src="([^"]+)"/)
        if (poster) pic = imgProxy(poster[1])
        if (!pic) {
            const ogi = html.match(/property="og:image"\s+content="([^"]*)"/)
            if (ogi) pic = imgProxy(ogi[1])
        }

        let content = ''
        const ogd = html.match(/property="og:description"\s+content="([^"]*)"/)
        if (ogd) content = ogd[1].trim()
        if (!content) {
            const dd = html.match(/hg-web-detail__desc[^>]*>([\s\S]*?)<\/(?:div|p)>/)
            if (dd) content = stripTags(dd[1])
        }

        // 集数：data-ep-grid 区块
        const plays = []
        const seen = {}
        const gm = html.match(/data-ep-grid[^>]*>([\s\S]*?)<\/div>/)
        if (gm) {
            const re = /<a\b[^>]*>[\s\S]*?<\/a>/g
            let m
            while ((m = re.exec(gm[1])) !== null) {
                const tag = m[0]
                const h = tag.match(/href="([^"]+)"/)
                if (!h) continue
                const href = h[1]
                if (href.indexOf('/video/') !== 0) continue
                const eid = tag.match(/data-ep-id="([^"]*)"/)
                const no = eid && eid[1] ? parseInt(eid[1]) : 0
                const label = no ? '第' + no + '集' : stripTags(tag)
                const key = rel(href)
                if (seen[key]) continue
                seen[key] = 1
                plays.push(label + '$' + key)
            }
        }
        // 兜底：全页扫 /video/{id} 链接
        if (!plays.length) {
            const re = new RegExp('/video/' + id + '(?:/ep-(\\d+))?/', 'g')
            let m
            while ((m = re.exec(html)) !== null) {
                const href = m[0]
                if (seen[href]) continue
                seen[href] = 1
                plays.push('第' + (m[1] ? m[1] : '1') + '集$' + href)
            }
        }
        if (!plays.length) return JSON.stringify({ list: [] })

        return JSON.stringify({
            list: [{
                vod_id: id,
                vod_name: name,
                vod_pic: pic,
                vod_content: content,
                vod_play_from: PLAYLIST,
                vod_play_url: plays.join('#')
            }]
        })
    } catch (e) {
        return JSON.stringify({ list: [] })
    }
}

function search(key, quick) {
    key = String(key || '').trim()
    if (!key) return JSON.stringify({ list: [] })
    try {
        const html = fetchPath('/search/video/' + encodeURIComponent(key) + '/')
        return JSON.stringify({ list: parseCards(html, true) })
    } catch (e) {
        return JSON.stringify({ list: [] })
    }
}

function play(flag, id) {
    let p = String(id || '')
    if (!p) return JSON.stringify({})
    try {
        const html = fetchPath(p, 0)
        if (!html) return JSON.stringify({})

        let data = null
        const m = html.match(/id="videoInitialData"[^>]*>([\s\S]*?)<\/script>/)
        if (m) {
            try { data = JSON.parse(m[1]) } catch (e) { data = null }
        }

        let url = ''
        if (data) {
            const srcs = data.epPlaySrcs || {}
            let ep = parseInt(data.ep) || 0
            if (!ep) {
                const em = p.match(/\/ep-(\d+)/)
                ep = em ? parseInt(em[1]) : 1
            }
            url = srcs[String(ep)] || ''
            if (!url) {
                // 目标集不在预取范围时，取任意可用的一集
                const ks = Object.keys(srcs)
                if (ks.length) url = srcs[ks[0]]
            }
            if (!url) url = data.videoSrc || data.previewSrc || ''
        }
        // 兜底：页面里直接找 m3u8
        if (!url) {
            const mm = html.match(/https?:\/\/[^\s"'<>\\]+\.m3u8[^\s"'<>\\]*/)
            if (mm) url = mm[0]
        }
        if (!url) return JSON.stringify({})

        url = url.replace(/\\u0026/g, '&').replace(/&amp;/g, '&')
        if (url.indexOf('http') !== 0) {
            const m2 = url.match(/(https?:\/\/[^\s"']+)/)
            url = m2 ? m2[1] : ''
        }
        if (!url) return JSON.stringify({})

        return JSON.stringify({
            parse: 0,
            url: url,
            header: { 'User-Agent': UA, Referer: host() + '/' }
        })
    } catch (e) {
        return JSON.stringify({})
    }
}

function live(url) {
    return JSON.stringify({})
}

function sniffer() {
    return false
}

function isVideo(url) {
    return false
}

// 封面解密：AES-128-CBC，NoPadding（兼容旧 PKCS5 写法）
function proxy(parts, obj) {
    let url = ''
    try { url = Array.isArray(parts) ? parts.join('/') : String(parts || '') } catch (e) {}
    if (!url || url.indexOf('http') !== 0) return JSON.stringify({ code: 404, content: '', buffer: 0, headers: {} })
    try {
        const res = req(url, { buffer: 2, headers: hdrs() })
        if (!res || String(res.code) !== '200' || !res.content) {
            return JSON.stringify({ code: 404, content: '', buffer: 0, headers: {} })
        }
        let b64 = ''
        try { b64 = aesX('AES/CBC/NoPadding', false, res.content, true, IMG_KEY, IMG_IV, true) } catch (e) { b64 = '' }
        if (!isImgB64(b64)) {
            try {
                const b2 = aesX('AES/CBC/PKCS5Padding', false, res.content, true, IMG_KEY, IMG_IV, true)
                if (isImgB64(b2)) b64 = b2
            } catch (e) {}
        }
        if (isImgB64(b64)) {
            return JSON.stringify({ code: 200, content: b64, buffer: 2, headers: { 'Content-Type': imgMime(url, b64) } })
        }
        // 未加密的原图直接透传
        return JSON.stringify({ code: 200, content: res.content, buffer: 2, headers: { 'Content-Type': imgMime(url, '') } })
    } catch (e) {
        return JSON.stringify({ code: 404, content: '', buffer: 0, headers: {} })
    }
}

function action(name) {
    return ''
}

function destroy() {
    return ''
}

export default {
    init, home, homeVod, category, detail, search, play,
    live, sniffer, isVideo, proxy, action, destroy
}
