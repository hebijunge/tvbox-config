// ============ 哔哩·合集2（drpy2 rule 格式）============
// 关键词合集直连版：分类关键词 -> B站搜索，免登录免代理
// 经 ./lib/drpy2.min.js 运行时加载（与原 jar 版 csp_Bili 对应）
var rule = {
    title: '哔哩·合集2',
    host: 'https://api.bilibili.com',
    url: '/x/web-interface/search/type?search_type=video&keyword=fyclass&page=fypage',
    detailUrl: '/x/web-interface/view?bvid=fyid',
    searchUrl: '/x/web-interface/search/type?search_type=video&keyword=**&page=fypage',
    searchable: 2,
    quickSearch: 0,
    filterable: 0,
    class_name: '哔哩合集',
    class_url: '哔哩合集',
    headers: {
        'User-Agent': 'PC_UA',
        'Referer': 'https://www.bilibili.com/',
        'Cookie': 'buvid3=0879DFCE-E687-DB47-DCEF-2BE20B6DD7C043368infoc; b_nut=1790278143'
    },
    timeout: 5000,
    play_parse: true,
    推荐: `js:
        let videos = [];
        function build(vod) {
            let img = vod.pic || '';
            if (img.indexOf('http') !== 0) img = 'https:' + img;
            let remark = '';
            if (vod.duration) {
                let sec = parseInt(vod.duration, 10) || 0;
                let hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60), ss = sec % 60;
                remark = (hh > 0 ? hh + ':' : '') + (mm < 10 ? '0' : '') + mm + ':' + (ss < 10 ? '0' : '') + ss;
            }
            if (vod.owner && vod.owner.name) remark = remark ? remark + ' · ' + vod.owner.name : vod.owner.name;
            videos.push({ vod_id: vod.bvid, vod_name: vod.title || '', vod_pic: img, vod_remarks: remark });
        }
        let html = request(rule.host + '/x/web-interface/index/top/feed/rcmd?ps=20&pn=1');
        let jo = JSON.parse(html);
        if (jo.code === 0 && jo.data && jo.data.item) {
            jo.data.item.forEach(build);
        }
        if (videos.length === 0) {
            let html2 = request(rule.host + '/x/web-interface/popular?ps=20&pn=1');
            let jo2 = JSON.parse(html2);
            if (jo2.code === 0 && jo2.data && jo2.data.list) jo2.data.list.forEach(build);
        }
        VODS = videos;
    `,
        一级: `js:
        let videos = [];
        function build(v) {
            let img = v.pic || '';
            if (img.indexOf('http') !== 0) img = 'https:' + img;
            let remark = v.author || '';
            if (v.play !== undefined) {
                let n = parseInt(v.play, 10) || 0;
                let ps = n >= 10000 ? (n / 10000).toFixed(1) + '万' : '' + n;
                remark = remark ? remark + ' · ' + ps + '播放' : ps + '播放';
            }
            let name = v.title ? v.title.replace(/<em[^>]*>/g, '').replace(/<\\/em>/g, '') : '';
            videos.push({ vod_id: v.bvid, vod_name: name, vod_pic: img, vod_remarks: remark });
        }
        let kw = MY_CATE || '';
        let pg = MY_PAGE || 1;
        let url = rule.host + '/x/web-interface/search/type?search_type=video&keyword=' + encodeURIComponent(kw) + '&page=' + pg;
        let html = request(url);
        let jo = JSON.parse(html);
        if (jo.code === 0 && jo.data && jo.data.result) {
            jo.data.result.forEach(build);
        }
        if (videos.length === 0) {
            let url2 = rule.host + '/x/web-interface/index/top/feed/rcmd?ps=20&pn=' + pg;
            let html2 = request(url2);
            let jo2 = JSON.parse(html2);
            if (jo2.code === 0 && jo2.data && jo2.data.item) jo2.data.item.forEach(build);
        }
        VODS = videos;
    `,
    二级: `js:
        let html = request(input);
        let jo = JSON.parse(html);
        if (!jo || jo.code !== 0 || !jo.data) { VOD = {}; }
        let d = jo.data;
        let img = d.pic || '';
        if (img.indexOf('http') !== 0) img = 'https:' + img;
        let pages = (d.pages && d.pages.length) ? d.pages : [{ cid: d.cid }];
        let playurls = [];
        pages.forEach(function(p, i) {
            let part = (p.part || ('P' + (i + 1))).replace(/#/g, '﹟').replace(/\\$/g, '﹩');
            playurls.push(part + '$' + d.bvid + '_' + p.cid);
        });
        let vod = {
            vod_id: d.bvid,
            vod_name: d.title || '',
            vod_pic: img,
            type_name: d.tname || '哔哩',
            vod_year: d.pubdate ? new Date(d.pubdate * 1000).getFullYear() : '',
            vod_remarks: d.duration ? '时长' + Math.floor((d.duration || 0) / 60) + '分' : '',
            vod_actor: d.owner ? d.owner.name : '',
            vod_director: d.tname || '',
            vod_content: d.desc || '',
            vod_play_from: 'B站',
            vod_play_url: playurls.join('#')
        };
        VOD = vod;
    `,
    搜索: `js:
        let videos = [];
        let html = request(input);
        let jo = JSON.parse(html);
        if (jo.code === 0 && jo.data && jo.data.result) {
            jo.data.result.forEach(function(v) {
                let img = v.pic || '';
                if (img.indexOf('http') !== 0) img = 'https:' + img;
                let remark = v.author || '';
                if (v.play !== undefined) {
                    let n = parseInt(v.play, 10) || 0;
                    let ps = n >= 10000 ? (n / 10000).toFixed(1) + '万' : '' + n;
                    remark = remark ? remark + ' · ' + ps + '播放' : ps + '播放';
                }
                let name = v.title ? v.title.replace(/<em[^>]*>/g, '').replace(/<\\/em>/g, '') : '';
                videos.push({ vod_id: v.bvid, vod_name: name, vod_pic: img, vod_remarks: remark });
            });
        }
        VODS = videos;
    `,
    lazy: `js:
        if (/^http/.test(input)) {
            input = { parse: 0, url: input, header: { 'User-Agent': 'Mozilla/5.0' } };
        } else {
            let ids = input.split('_');
            let bvid = ids[0];
            let cid = ids[1];
            let qns = [116, 64, 32, 16];
            let purl = '';
            for (let i = 0; i < qns.length; i++) {
                let u = rule.host + '/x/player/playurl?bvid=' + bvid + '&cid=' + cid + '&qn=' + qns[i] + '&fnval=0&fourk=1';
                let html = request(u);
                let jo = JSON.parse(html);
                if (jo.code === 0 && jo.data && jo.data.durl && jo.data.durl.length) {
                    purl = jo.data.durl[0].url;
                    break;
                }
            }
            if (!purl) {
                input = '';
            } else {
                let result = {
                    parse: 0,
                    playUrl: '',
                    url: unescape(purl),
                    header: {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Referer': 'https://www.bilibili.com/'
                    }
                };
                if (/\.flv/.test(purl)) result.contentType = 'video/x-flv';
                input = result;
            }
        }
    `
};
