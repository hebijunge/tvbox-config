var rule = {
    title: '百忙无果[官]',
    host: 'https://pianku.api.mgtv.com',
    homeUrl: '',
    searchUrl: 'https://mobileso.bz.mgtv.com/msite/search/v2?q=**&pn=fypage&pc=10',
    detailUrl: 'https://pcweb.api.mgtv.com/episode/list?page=1&size=50&video_id=fyid',
    searchable: 2,
    quickSearch: 0,
    filterable: 1,
    multi: 1,
    url: '/rider/list/pcweb/v3?platform=pcweb&channelId=fyclass&pn=fypage&pc=80&hudong=1&_support=10000000&kind=a1&area=a1',
    filter_url: 'year={{fl.year or "all"}}&sort={{fl.sort or "all"}}&chargeInfo={{fl.chargeInfo or "all"}}',

    // 屏蔽地址
    blocked_urls: [
        'http://lie.yuyun4kmaopan.qijiyun.vip/d/ty/923241268797768768/video_260803_125610.mp4',
        'http://mlwl.7766.org:91/qf.mp4',
         'https://hwmov.a.yximgs.com/upic/2026/05/20/12/BMjAyNjA1MjAxMjIyNThfMTY1NTYxNDk0NF8xOTY0Mjg2MzEzNzNfMl8z_b_B2d85e883e7ab00ad52949e6bcad9fa59.mp4',
       'https://txmov2.a.kwimgs.com/upic/2026/04/24/22/BMjAyNjA0MjQyMjMxMTdfNTE1Njg1NzUyXzE5NDAxNDg2MjI0N18yXzM=_b_Be9cdf9b3f66017f25b1e9f7c1135de53.mp4',
       'https://gitee.com/nm_nm/interface/raw/master/ips/ips(20250418105556)_001.ts',
        'IP使用次数超限，请加群签到.mp4'
    ],

    headers: {
        'User-Agent': 'PC_UA'
    },
    timeout: 5000,

    class_name: '电视剧&电影&综艺&动漫&纪录片&教育&少儿',
    class_url: '2&3&1&50&51&115&10',

    filter: {
        "1": [
            {"key": "chargeInfo", "name": "付费类型", "value": [{"n": "全部", "v": "all"}, {"n": "免费", "v": "b1"}, {"n": "VIP", "v": "b2"}, {"n": "VIP用券", "v": "b3"}, {"n": "付费点播", "v": "b4"}]},
            {"key": "sort", "name": "排序", "value": [{"n": "最新", "v": "c1"}, {"n": "最热", "v": "c2"}, {"n": "知乎高分", "v": "c4"}]},
            {"key": "year", "name": "年代", "value": [{"n": "全部", "v": "all"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"}, {"n": "2015", "v": "2015"}, {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"}, {"n": "2012", "v": "2012"}, {"n": "2011", "v": "2011"}, {"n": "2010", "v": "2010"}, {"n": "2009", "v": "2009"}, {"n": "2008", "v": "2008"}, {"n": "2007", "v": "2007"}, {"n": "2006", "v": "2006"}, {"n": "2005", "v": "2005"}, {"n": "2004", "v": "2004"}]}
        ],
        "2": [
            {"key": "chargeInfo", "name": "付费类型", "value": [{"n": "全部", "v": "all"}, {"n": "免费", "v": "b1"}, {"n": "VIP", "v": "b2"}, {"n": "VIP用券", "v": "b3"}, {"n": "付费点播", "v": "b4"}]},
            {"key": "sort", "name": "排序", "value": [{"n": "最新", "v": "c1"}, {"n": "最热", "v": "c2"}, {"n": "知乎高分", "v": "c4"}]},
            {"key": "year", "name": "年代", "value": [{"n": "全部", "v": "all"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"}, {"n": "2015", "v": "2015"}]}
        ],
        "3": [
            {"key": "chargeInfo", "name": "付费类型", "value": [{"n": "全部", "v": "all"}, {"n": "免费", "v": "b1"}, {"n": "VIP", "v": "b2"}, {"n": "VIP用券", "v": "b3"}, {"n": "付费点播", "v": "b4"}]},
            {"key": "sort", "name": "排序", "value": [{"n": "最新", "v": "c1"}, {"n": "最热", "v": "c2"}, {"n": "知乎高分", "v": "c4"}]},
            {"key": "year", "name": "年代", "value": [{"n": "全部", "v": "all"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"}]}
        ],
        "50": [
            {"key": "chargeInfo", "name": "付费类型", "value": [{"n": "全部", "v": "all"}, {"n": "免费", "v": "b1"}, {"n": "VIP", "v": "b2"}, {"n": "VIP用券", "v": "b3"}, {"n": "付费点播", "v": "b4"}]},
            {"key": "sort", "name": "排序", "value": [{"n": "最新", "v": "c1"}, {"n": "最热", "v": "c2"}, {"n": "知乎高分", "v": "c4"}]},
            {"key": "year", "name": "年代", "value": [{"n": "全部", "v": "all"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}]}
        ],
        "51": [
            {"key": "chargeInfo", "name": "付费类型", "value": [{"n": "全部", "v": "all"}, {"n": "免费", "v": "b1"}, {"n": "VIP", "v": "b2"}, {"n": "VIP用券", "v": "b3"}, {"n": "付费点播", "v": "b4"}]},
            {"key": "sort", "name": "排序", "value": [{"n": "最新", "v": "c1"}, {"n": "最热", "v": "c2"}, {"n": "知乎高分", "v": "c4"}]},
            {"key": "year", "name": "年代", "value": [{"n": "全部", "v": "all"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}]}
        ],
        "115": [
            {"key": "chargeInfo", "name": "付费类型", "value": [{"n": "全部", "v": "all"}, {"n": "免费", "v": "b1"}, {"n": "VIP", "v": "b2"}, {"n": "VIP用券", "v": "b3"}, {"n": "付费点播", "v": "b4"}]},
            {"key": "sort", "name": "排序", "value": [{"n": "最新", "v": "c1"}, {"n": "最热", "v": "c2"}, {"n": "知乎高分", "v": "c4"}]},
            {"key": "year", "name": "年代", "value": [{"n": "全部", "v": "all"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}]}
        ]
    },

    limit: 20,
    play_parse: true,

    lazy: $js.toString(() => {
        let apiList = [
             "http://niubi.69mini.com/api/?key=09a74556faba7e3b528d64b9c9a86a61&url=",
         "http://106.12.58.21:6207/Vqq20000.php?url=",  
         "https://api.jxapi.cc/api/?key=e0df4139f1e7f09375e864cc4937570e&url=",
        "http://zxy-th1.jsszks.dpdns.org:8090/?url=",
        "http://gsd-jx.810211.dpdns.org/home/api?type=ys&uid=2733323&key=lbalobOE9F6B7I0DfE&url=",
            "http://103.236.72.166:188/api/?key=veniDOaEzSzIThZsyb&url=",
            "http://mg.itufm.top/mg.php?url=",
            'https://jx.hls.one/?url=',
            'https://jx.xmflv.com/?url='
        ];

        let videoUrl = input.split("?")[0];
        let success = false;
        let playUrl = '';

        // 检查屏蔽地址
        function isBlocked(url) {
            if (!url) return false;
            for (let i = 0; i < rule.blocked_urls.length; i++) {
                if (url.indexOf(rule.blocked_urls[i]) !== -1) {
                    return true;
                }
            }
            return false;
        }

        for (let i = 0; i < apiList.length; i++) {
            try {
                let api = apiList[i] + videoUrl;
                print("尝试解析接口 " + (i + 1));
                let response = fetch(api, {
                    method: 'get',
                    headers: { 'User-Agent': 'okhttp/3.14.9' }
                });
                let data = JSON.parse(response);
                playUrl = data.url || data.playUrl || data.data;

                if (playUrl && playUrl.indexOf("http") > -1) {
                    // 检查是否是屏蔽地址
                    if (isBlocked(playUrl)) {
                        print("解析接口 " + (i + 1) + " 返回屏蔽地址，跳过");
                        continue;
                    }
                    success = true;
                    print("解析接口 " + (i + 1) + " 成功");
                    break;
                }
            } catch (e) {
                print("解析接口 " + (i + 1) + " 失败");
                continue;
            }
        }

        if (success && playUrl) {
            input = {
                header: {'User-Agent': ''},
                parse: 0,
                url: playUrl,
                jx: 0,
                danmaku: ''
            };
        } else {
            input = {
                header: {'User-Agent': ''},
                parse: 0,
                url: videoUrl,
                jx: 1,
                danmaku: ''
            };
        }
    }),

    一级: 'json:data.hitDocs;title;img;updateInfo||rightCorner.text;playPartId',

    二级: $js.toString(() => {
        fetch_params.headers.Referer = "https://www.mgtv.com";
        fetch_params.headers["User-Agent"] = MOBILE_UA;
        let videoId = input.split('video_id=')[1].split('&')[0];
        let infoUrl = `https://pcweb.api.mgtv.com/video/info?allowedRC=1&vid=${videoId}&type=b&_support=10000000`;
        let infoData = JSON.parse(request(infoUrl));
        if (infoData && infoData.data && infoData.data.info) {
            let detail = infoData.data.info.detail || {};
            VOD = {
                vod_name: infoData.data.info.title || "",
                type_name: detail.kind || "",
                vod_year: detail.releaseTime || "",
                vod_area: detail.area || "",
                vod_actor: detail.leader || "",
                vod_director: detail.director || "",
                vod_content: detail.story || "",
                vod_remarks: detail.updateInfo || ""
            };
            if (detail.img) VOD.vod_pic = detail.img;
        }
        let d = [];
        let html = request(input);
        let json = JSON.parse(html);
        let host = "https://www.mgtv.com";
        let ourl = json.data.list.length > 0 ? json.data.list[0].url : json.data.series[0].url;
        if (!/^http/.test(ourl)) ourl = host + ourl;
        fetch_params.headers["User-Agent"] = MOBILE_UA;
        html = request(ourl);
        if (html.includes("window.location =")) {
            ourl = pdfh(html, "meta[http-equiv=refresh]&&content").split("url=")[1];
            html = request(ourl);
        }
        try {
            let details = pdfh(html, ".m-details&&Html").replace(/h1>/, "h6>").replace(/div/g, "br");
            let actor = "", director = "", time = "";
            if (/播出时间/.test(details)) {
                actor = pdfh(html, "p:eq(5)&&Text").substr(0, 25);
                director = pdfh(html, "p:eq(4)&&Text");
                time = pdfh(html, "p:eq(3)&&Text");
            } else {
                actor = pdfh(html, "p:eq(4)&&Text").substr(0, 25);
                director = pdfh(html, "p:eq(3)&&Text");
                time = "已完结";
            }
            let _img = pd(html, ".video-img&&img&&src");
            let JJ = pdfh(html, ".desc&&Text").split("简介：")[1];
            VOD.vod_name = VOD.vod_name || pdfh(html, ".vt-txt&&Text");
            VOD.type_name = VOD.type_name || pdfh(html, "p:eq(0)&&Text").substr(0, 6);
            VOD.vod_area = VOD.vod_area || pdfh(html, "p:eq(1)&&Text");
            VOD.vod_actor = VOD.vod_actor || actor;
            VOD.vod_director = VOD.vod_director || director;
            VOD.vod_remarks = VOD.vod_remarks || time;
            VOD.vod_pic = VOD.vod_pic || _img;
            VOD.vod_content = VOD.vod_content || JJ;
            if (!VOD.vod_name) VOD.vod_name = VOD.type_name;
        } catch (e) {
            log("获取影片信息发生错误:" + e.message);
        }

        function getRjpg(imgUrl, xs) {
            xs = xs || 3;
            let picSize = /jpg_/.test(imgUrl) ? imgUrl.split("jpg_")[1].split(".")[0] : false;
            let rjpg = false;
            if (picSize) {
                let a = parseInt(picSize.split("x")[0]) * xs;
                let b = parseInt(picSize.split("x")[1]) * xs;
                rjpg = a + "x" + b + ".jpg";
            }
            return /jpg_/.test(imgUrl) && rjpg ? imgUrl.replace(imgUrl.split("jpg_")[1], rjpg) : imgUrl;
        }

        if (json.data.total === 1 && json.data.list.length === 1) {
            let data = json.data.list[0];
            d.push({
                title: data.t4,
                desc: data.t2,
                pic_url: getRjpg(data.img),
                url: "https://www.mgtv.com" + data.url
            });
        } else if (json.data.list.length > 1) {
            for (let i = 1; i <= json.data.total_page; i++) {
                if (i > 1) json = JSON.parse(fetch(input.replace("page=1", "page=" + i), {}));
                json.data.list.forEach(function(data) {
                    if (data.isIntact == "1") {
                        d.push({
                            title: data.t4,
                            desc: data.t2,
                            pic_url: getRjpg(data.img),
                            url: "https://www.mgtv.com" + data.url
                        });
                    }
                });
            }
        } else {
            print(input + "暂无片源");
        }
        VOD.vod_play_from = "芒果TV(拒绝买卖!请去12315举报)";
        VOD.vod_play_url = d.map(function(it) {
            return it.title + "$" + it.url;
        }).join("#");
        setResult(d);
    }),

    搜索: $js.toString(() => {
        fetch_params.headers.Referer = "https://www.mgtv.com";
        fetch_params.headers["User-Agent"] = MOBILE_UA;
        let searchUrl = input;
        let searchMatch = searchUrl.match(/q=([^&]+)/);
        let searchKeyword = searchMatch ? decodeURIComponent(searchMatch[1]) : "";
        let d = [];
        let html = request(input);
        let json = JSON.parse(html);
        let filterKeywords = ["新闻", "教育", "生活", "娱乐", "音乐"];
        let filterTitleKeywords = ["《", "解说", "预告", "匿杀", "靳东日记", "泰语", "眼福不浅", "越南语", "花絮", "番外", "独家", "阿拉伯"];
        json.data.contents.forEach(function(data) {
            if (data.type && data.type == 'media') {
                let item = data.data[0];
                if (item.source === "imgo") {
                    let title = item.title.replace(/<B>|<\/B>/g, '');
                    if (searchKeyword && !title.toLowerCase().includes(searchKeyword.toLowerCase())) {
                        return;
                    }
                    let shouldFilterTitle = false;
                    if (filterTitleKeywords && filterTitleKeywords.length > 0) {
                        for (let i = 0; i < filterTitleKeywords.length; i++) {
                            if (title.includes(filterTitleKeywords[i])) {
                                shouldFilterTitle = true;
                                log("过滤掉标题包含'" + filterTitleKeywords[i] + "'的资源: " + title);
                                break;
                            }
                        }
                    }
                    if (shouldFilterTitle) {
                        return;
                    }
                    let typeInfo = item.desc && item.desc.length > 0 ? item.desc[0] : "";
                    let shouldFilterType = false;
                    if (filterKeywords && filterKeywords.length > 0) {
                        for (let i = 0; i < filterKeywords.length; i++) {
                            if (typeInfo.includes(filterKeywords[i])) {
                                shouldFilterType = true;
                                log("过滤掉类型为'" + filterKeywords[i] + "'的资源: " + title + " | 类型: " + typeInfo);
                                break;
                            }
                        }
                    }
                    if (shouldFilterType) {
                        return;
                    }
                    let fyclass = '';
                    try {
                        fyclass = item.rpt.match(/idx=(.*?)&/)[1] + '$';
                    } catch (e) {
                        log(e.message);
                    }
                    d.push({
                        title: title,
                        img: item.img || '',
                        content: '',
                        desc: item.desc.join(','),
                        url: fyclass + item.url.match(/.*\/(.*?)\.html/)[1]
                    });
                }
            }
        });
        if (d.length === 0) {
            log("搜索'" + searchKeyword + "'后，根据过滤条件（类型：" + (filterKeywords.length > 0 ? filterKeywords.join("、") : "无") + "，标题：" + (filterTitleKeywords.length > 0 ? filterTitleKeywords.join("、") : "无") + "）过滤，没有找到匹配的资源");
        } else {
            log("搜索'" + searchKeyword + "'找到" + d.length + "个结果（已过滤掉类型：" + (filterKeywords.length > 0 ? filterKeywords.join("、") : "无") + "，标题包含：" + (filterTitleKeywords.length > 0 ? filterTitleKeywords.join("、") : "无") + "的资源）");
        }
        setResult(d);
    })
};