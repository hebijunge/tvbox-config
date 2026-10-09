// ============ 哔哩 · 直连（drpy2 rule 格式）v2.0 ============
// 免代理、免登录 B 站源。与仓库内全部 drpy2 源（如 LMM.js）同格式，
// 经 ./lib/drpy2.min.js 运行时加载，兼容 TVBox 主流的 drpy 加载方式。
// 接口：分区推荐（rcmd）、搜索、详情（view）、播放（playurl 直链）
// 限制：匿名访问，大会员/登录限清晰度自动降级；全部 JS 用 drpy2 的同步 request()
var rule = {
    title: '哔哩直连',
    host: 'https://api.bilibili.com',
    url: '/x/web-interface/index/top/feed/rcmd?ps=20&pn=fypage&rid=fyclass',
    detailUrl: '/x/web-interface/view?bvid=fyid',
    searchUrl: '/x/web-interface/search/type?search_type=video&keyword=**&page=fypage',
    searchable: 1,
    quickSearch: 1,
    filterable: 0,
    class_name: '综合&动画&番剧&国创&音乐&舞蹈&游戏&科技&数码&生活&鬼畜&时尚&娱乐&影视&纪录片&电影&电视剧&知识&运动&汽车',
    class_url: '0&1&13&167&3&129&4&36&188&160&119&155&5&181&17&23&11&6&138&223',
    headers: {
        'User-Agent': 'PC_UA',
        'Referer': 'https://www.bilibili.com/',
        'Cookie': 'buvid3=0879DFCE-E687-DB47-DCEF-2BE20B6DD7C043368infoc; b_nut=1790278143'
    },
    timeout: 5000,
    play_parse: true,
    pagecount: {"0":1,"1":1,"13":1,"167":1,"3":1,"129":1,"4":1,"36":1,"188":1,"160":1,"119":1,"155":1,"5":1,"181":1,"17":1,"23":1,"11":1,"6":1,"138":1,"223":1},
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
        let rid = MY_CATE || '0';
        let pg = MY_PAGE || 1;
        let url = rule.host + '/x/web-interface/index/top/feed/rcmd?ps=20&pn=' + pg + '&rid=' + rid;
        let html = request(url);
        let jo = JSON.parse(html);
        if (jo.code === 0 && jo.data && jo.data.item) {
            jo.data.item.forEach(build);
        }
        if (videos.length === 0) {
            let url2 = rule.host + '/x/web-interface/index/top/feed/rcmd?ps=20&pn=' + pg;
            let html2 = request(url2);
            let jo2 = JSON.parse(html2);
            if (jo2.code === 0 && jo2.data && jo2.data.item) jo2.data.item.forEach(build);
        }
        if (videos.length === 0) {
            let url3 = rule.host + '/x/web-interface/ranking?rid=' + rid + '&day=3';
            let html3 = request(url3);
            let jo3 = JSON.parse(html3);
            if (jo3.code === 0 && jo3.data && jo3.data.list) jo3.data.list.forEach(build);
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
