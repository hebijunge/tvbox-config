// ============ 樱之空（drpy2 rule 格式）============
// 播放地址为 JS base64+URL 加密，lazy 内自动解密
// 经 ./lib/drpy2.min.js 运行时加载
var rule = {
    title: '樱之空',
    host: 'https://www.skr.cc',
    url: '/vodtype/fyclass.html?page=fypage',
    detailUrl: 'https://www.skr.cc/fyid',
    searchUrl: '/vodsearch/**----------fypage---.html',
    searchable: 2,
    quickSearch: 0,
    filterable: 0,
    class_name: '动漫$1',
    class_url: '1',
    headers: {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13; V2049A Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36',
        'Referer': 'https://www.skr.cc/'
    },
    timeout: 8000,
    play_parse: true,
    一级: `js:
        let videos = [];
        let html = request(rule.host + '/vodtype/' + MY_CATE + '.html?page=' + MY_PAGE);
        let blocks = html.match(/class="vodlist_thumb[\\s\\S]*?<\\/a>/g) || [];
        blocks.forEach(function (b) {
            let idm = b.match(/href="\\/voddetail\\/(\\d+)\\//);
            let tm = b.match(/alt="([^"]*)"/);
            let im = b.match(/data-original="([^"]*)"/);
            let pm = b.match(/<p>([^<]*)<\\/p>/);
            if (!idm || !tm) return;
            let img = im ? im[1] : '';
            let remark = pm ? pm[1] : '';
            videos.push({
                vod_id: '/voddetail/' + idm[1] + '/',
                vod_name: tm[1],
                vod_pic: img,
                vod_remarks: remark
            });
        });
        VODS = videos;
    `,
    二级: `js:
        let html = request(input);
        let vod = { vod_id: input, vod_name: '', vod_pic: '', vod_play_from: '樱之空', vod_play_url: '' };
        let tm = html.match(/<h1[^>]*>([^<]+)<\\/h1>/);
        if (tm) vod.vod_name = tm[1];
        let im = html.match(/data-original="([^"]+)"/);
        if (im) vod.vod_pic = im[1];
        let dm = html.match(/简介:<\\/span>([\\s\\S]*?)<\\/span>/);
        if (dm) vod.vod_content = dm[1].replace(/<[^>]+>/g, '');
        let pb = html.match(/class="detail_list_box[\\s\\S]*?<\\/div><\\/div>/);
        let links = pb ? pb[0].match(/<a[^>]+href="(\\/vodplay\\/[^"]+)"[^>]*title="([^"]*)"/g) : [];
        let eps = [];
        (links || []).forEach(function (a) {
            let hm = a.match(/href="(\\/vodplay\\/[^"]+)"/);
            let tt = a.match(/title="([^"]*)"/);
            if (hm) eps.push((tt ? tt[1] : '播放') + '$' + rule.host + hm[1]);
        });
        vod.vod_play_url = eps.join('#');
        VOD = vod;
    `,
    搜索: `js:
        let videos = [];
        let html = request(rule.host + '/vodsearch/' + encodeURIComponent(KEY) + '----------' + MY_PAGE + '---.html');
        let items = html.match(/class="searchlist_item[\\s\\S]*?<\\/li>/g) || [];
        items.forEach(function (b) {
            let idm = b.match(/href="\\/voddetail\\/(\\d+)\\//);
            let im = b.match(/data-original="([^"]*)"/);
            let tm = b.match(/vodlist_title"><a[^>]*>([\\s\\S]*?)<\\/a>/);
            if (!idm || !tm) return;
            let name = tm[1].replace(/<span[\\s\\S]*?<\\/span>/g, '').replace(/<[^>]+>/g, '').trim();
            if (!name) return;
            videos.push({
                vod_id: '/voddetail/' + idm[1] + '/',
                vod_name: name,
                vod_pic: im ? im[1] : ''
            });
        });
        VODS = videos;
    `,
    lazy: `js:
        function b64d(s) {
            s = String(s).replace(/[^A-Za-z0-9+/=]/g, '');
            var b = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
            var out = '', i;
            for (i = 0; i + 3 < s.length; i += 4) {
                var e1 = b.indexOf(s.charAt(i));
                var e2 = b.indexOf(s.charAt(i + 1));
                var e3 = s.charAt(i + 2) === '=' ? 0 : b.indexOf(s.charAt(i + 2));
                var e4 = s.charAt(i + 3) === '=' ? 0 : b.indexOf(s.charAt(i + 3));
                if (e1 < 0 || e2 < 0) break;
                out += String.fromCharCode((e1 << 2) | (e2 >> 4));
                if (s.charAt(i + 2) !== '=') out += String.fromCharCode(((e2 & 15) << 4) | (e3 >> 2));
                if (s.charAt(i + 3) !== '=') out += String.fromCharCode(((e3 & 3) << 6) | e4);
            }
            return out;
        }
        let html = request(input);
        let m = html.match(/player_aaaa=([\\s\\S]*?)<\\/script>/);
        if (!m) { VOD = {}; }
        else {
            let m2 = m[1].match(/"url":"([^"]+)"/);
            if (m2) {
                let u = '';
                try { u = decodeURIComponent(b64d(m2[1])); } catch (e) {}
                if (u) {
                    input = {
                        parse: 0,
                        url: u,
                        header: {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Referer': rule.host + '/'
                        }
                    };
                } else { VOD = {}; }
            } else { VOD = {}; }
        }
    `
};
