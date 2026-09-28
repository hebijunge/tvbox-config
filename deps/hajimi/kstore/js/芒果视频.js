var rule = {
    title: '百忙无果[官]',
    host: 'https://pianku.api.%6d%67%74%76.com',
    homeUrl: '',
    // searchUrl 仅占位（q/pn 会在 搜索 中重新解析并生成带签名的 v2 请求）
    searchUrl: 'https://mobileso.bz.mgtv.com/pc/search/v2?q=**&pn=fypage&pc=10',
    detailUrl: 'https://pcweb.api.mgtv.com/episode/list?page=1&size=50&video_id=fyid',
    searchable: 2,
    quickSearch: 0,
    filterable: 1,
    multi: 1,
    // 分类链接fypage参数支持1个()表达式
    // https://www.mgtv.com/lib/3?lastp=list_index&kind=a1&year=all&chargeInfo=a1&sort=c2
    url: '/rider/list/pcweb/v3?platform=pcweb&channelId=fyclass&pn=fypage&pc=80&hudong=1&_support=10000000&kind=a1&area=a1',
    filter_url: 'year={{fl.year or "all"}}&sort={{fl.sort or "all"}}&chargeInfo={{fl.chargeInfo or "all"}}',
    headers: {
        'User-Agent': 'PC_UA'
    },
    timeout: 5000,
    class_name: '电视剧&电影&综艺&动漫&纪录片&教育&少儿',
    class_url: '2&3&1&50&51&115&10',
    filter: {
        "1": [{
            "key": "chargeInfo",
            "name": "付费类型",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "免费",
                "v": "b1"
            }, {
                "n": "vip",
                "v": "b2"
            }, {
                "n": "VIP用券",
                "v": "b3"
            }, {
                "n": "付费点播",
                "v": "b4"
            }]
        }, {
            "key": "sort",
            "name": "排序",
            "value": [{
                "n": "最新",
                "v": "c1"
            }, {
                "n": "最热",
                "v": "c2"
            }, {
                "n": "知乎高分",
                "v": "c4"
            }]
        }, {
            "key": "year",
            "name": "年代",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "2026",
                "v": "2026"
            }, {
                "n": "2025",
                "v": "2025"
            }, {
                "n": "2024",
                "v": "2024"
            }, {
                "n": "2023",
                "v": "2023"
            }, {
                "n": "2022",
                "v": "2022"
            }, {
                "n": "2021",
                "v": "2021"
            }, {
                "n": "2020",
                "v": "2020"
            }, {
                "n": "2019",
                "v": "2019"
            }, {
                "n": "2018",
                "v": "2018"
            }, {
                "n": "2017",
                "v": "2017"
            }, {
                "n": "2016",
                "v": "2016"
            }, {
                "n": "2015",
                "v": "2015"
            }, {
                "n": "2014",
                "v": "2014"
            }, {
                "n": "2013",
                "v": "2013"
            }, {
                "n": "2012",
                "v": "2012"
            }, {
                "n": "2011",
                "v": "2011"
            }, {
                "n": "2010",
                "v": "2010"
            }, {
                "n": "2009",
                "v": "2009"
            }, {
                "n": "2008",
                "v": "2008"
            }, {
                "n": "2007",
                "v": "2007"
            }, {
                "n": "2006",
                "v": "2006"
            }, {
                "n": "2005",
                "v": "2005"
            }, {
                "n": "2004",
                "v": "2004"
            }]
        }],
        "2": [{
            "key": "chargeInfo",
            "name": "付费类型",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "免费",
                "v": "b1"
            }, {
                "n": "vip",
                "v": "b2"
            }, {
                "n": "VIP用券",
                "v": "b3"
            }, {
                "n": "付费点播",
                "v": "b4"
            }]
        }, {
            "key": "sort",
            "name": "排序",
            "value": [{
                "n": "最新",
                "v": "c1"
            }, {
                "n": "最热",
                "v": "c2"
            }, {
                "n": "知乎高分",
                "v": "c4"
            }]
        }, {
            "key": "year",
            "name": "年代",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "2026",
                "v": "2026"
            }, {
                "n": "2025",
                "v": "2025"
            }, {
                "n": "2024",
                "v": "2024"
            }, {
                "n": "2023",
                "v": "2023"
            }, {
                "n": "2022",
                "v": "2022"
            }, {
                "n": "2021",
                "v": "2021"
            }, {
                "n": "2020",
                "v": "2020"
            }, {
                "n": "2019",
                "v": "2019"
            }, {
                "n": "2018",
                "v": "2018"
            }, {
                "n": "2017",
                "v": "2017"
            }, {
                "n": "2016",
                "v": "2016"
            }, {
                "n": "2015",
                "v": "2015"
            }, {
                "n": "2014",
                "v": "2014"
            }, {
                "n": "2013",
                "v": "2013"
            }, {
                "n": "2012",
                "v": "2012"
            }, {
                "n": "2011",
                "v": "2011"
            }, {
                "n": "2010",
                "v": "2010"
            }, {
                "n": "2009",
                "v": "2009"
            }, {
                "n": "2008",
                "v": "2008"
            }, {
                "n": "2007",
                "v": "2007"
            }, {
                "n": "2006",
                "v": "2006"
            }, {
                "n": "2005",
                "v": "2005"
            }, {
                "n": "2004",
                "v": "2004"
            }]
        }],
        "3": [{
            "key": "chargeInfo",
            "name": "付费类型",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "免费",
                "v": "b1"
            }, {
                "n": "vip",
                "v": "b2"
            }, {
                "n": "VIP用券",
                "v": "b3"
            }, {
                "n": "付费点播",
                "v": "b4"
            }]
        }, {
            "key": "sort",
            "name": "排序",
            "value": [{
                "n": "最新",
                "v": "c1"
            }, {
                "n": "最热",
                "v": "c2"
            }, {
                "n": "知乎高分",
                "v": "c4"
            }]
        }, {
            "key": "year",
            "name": "年代",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "2026",
                "v": "2026"
            }, {
                "n": "2025",
                "v": "2025"
            }, {
                "n": "2024",
                "v": "2024"
            }, {
                "n": "2023",
                "v": "2023"
            }, {
                "n": "2022",
                "v": "2022"
            }, {
                "n": "2021",
                "v": "2021"
            }, {
                "n": "2020",
                "v": "2020"
            }, {
                "n": "2019",
                "v": "2019"
            }, {
                "n": "2018",
                "v": "2018"
            }, {
                "n": "2017",
                "v": "2017"
            }, {
                "n": "2016",
                "v": "2016"
            }, {
                "n": "2015",
                "v": "2015"
            }, {
                "n": "2014",
                "v": "2014"
            }, {
                "n": "2013",
                "v": "2013"
            }, {
                "n": "2012",
                "v": "2012"
            }, {
                "n": "2011",
                "v": "2011"
            }, {
                "n": "2010",
                "v": "2010"
            }, {
                "n": "2009",
                "v": "2009"
            }, {
                "n": "2008",
                "v": "2008"
            }, {
                "n": "2007",
                "v": "2007"
            }, {
                "n": "2006",
                "v": "2006"
            }, {
                "n": "2005",
                "v": "2005"
            }, {
                "n": "2004",
                "v": "2004"
            }]
        }],
        "50": [{
            "key": "chargeInfo",
            "name": "付费类型",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "免费",
                "v": "b1"
            }, {
                "n": "vip",
                "v": "b2"
            }, {
                "n": "VIP用券",
                "v": "b3"
            }, {
                "n": "付费点播",
                "v": "b4"
            }]
        }, {
            "key": "sort",
            "name": "排序",
            "value": [{
                "n": "最新",
                "v": "c1"
            }, {
                "n": "最热",
                "v": "c2"
            }, {
                "n": "知乎高分",
                "v": "c4"
            }]
        }, {
            "key": "year",
            "name": "年代",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "2026",
                "v": "2026"
            }, {
                "n": "2025",
                "v": "2025"
            }, {
                "n": "2024",
                "v": "2024"
            }, {
                "n": "2023",
                "v": "2023"
            }, {
                "n": "2022",
                "v": "2022"
            }, {
                "n": "2021",
                "v": "2021"
            }, {
                "n": "2020",
                "v": "2020"
            }, {
                "n": "2019",
                "v": "2019"
            }, {
                "n": "2018",
                "v": "2018"
            }, {
                "n": "2017",
                "v": "2017"
            }, {
                "n": "2016",
                "v": "2016"
            }, {
                "n": "2015",
                "v": "2015"
            }, {
                "n": "2014",
                "v": "2014"
            }, {
                "n": "2013",
                "v": "2013"
            }, {
                "n": "2012",
                "v": "2012"
            }, {
                "n": "2011",
                "v": "2011"
            }, {
                "n": "2010",
                "v": "2010"
            }, {
                "n": "2009",
                "v": "2009"
            }, {
                "n": "2008",
                "v": "2008"
            }, {
                "n": "2007",
                "v": "2007"
            }, {
                "n": "2006",
                "v": "2006"
            }, {
                "n": "2005",
                "v": "2005"
            }, {
                "n": "2004",
                "v": "2004"
            }]
        }],
        "51": [{
            "key": "chargeInfo",
            "name": "付费类型",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "免费",
                "v": "b1"
            }, {
                "n": "vip",
                "v": "b2"
            }, {
                "n": "VIP用券",
                "v": "b3"
            }, {
                "n": "付费点播",
                "v": "b4"
            }]
        }, {
            "key": "sort",
            "name": "排序",
            "value": [{
                "n": "最新",
                "v": "c1"
            }, {
                "n": "最热",
                "v": "c2"
            }, {
                "n": "知乎高分",
                "v": "c4"
            }]
        }, {
            "key": "year",
            "name": "年代",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "2026",
                "v": "2026"
            }, {
                "n": "2025",
                "v": "2025"
            }, {
                "n": "2024",
                "v": "2024"
            }, {
                "n": "2023",
                "v": "2023"
            }, {
                "n": "2022",
                "v": "2022"
            }, {
                "n": "2021",
                "v": "2021"
            }, {
                "n": "2020",
                "v": "2020"
            }, {
                "n": "2019",
                "v": "2019"
            }, {
                "n": "2018",
                "v": "2018"
            }, {
                "n": "2017",
                "v": "2017"
            }, {
                "n": "2016",
                "v": "2016"
            }, {
                "n": "2015",
                "v": "2015"
            }, {
                "n": "2014",
                "v": "2014"
            }, {
                "n": "2013",
                "v": "2013"
            }, {
                "n": "2012",
                "v": "2012"
            }, {
                "n": "2011",
                "v": "2011"
            }, {
                "n": "2010",
                "v": "2010"
            }, {
                "n": "2009",
                "v": "2009"
            }, {
                "n": "2008",
                "v": "2008"
            }, {
                "n": "2007",
                "v": "2007"
            }, {
                "n": "2006",
                "v": "2006"
            }, {
                "n": "2005",
                "v": "2005"
            }, {
                "n": "2004",
                "v": "2004"
            }]
        }],
        "115": [{
            "key": "chargeInfo",
            "name": "付费类型",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "免费",
                "v": "b1"
            }, {
                "n": "vip",
                "v": "b2"
            }, {
                "n": "VIP用券",
                "v": "b3"
            }, {
                "n": "付费点播",
                "v": "b4"
            }]
        }, {
            "key": "sort",
            "name": "排序",
            "value": [{
                "n": "最新",
                "v": "c1"
            }, {
                "n": "最热",
                "v": "c2"
            }, {
                "n": "知乎高分",
                "v": "c4"
            }]
        }, {
            "key": "year",
            "name": "年代",
            "value": [{
                "n": "全部",
                "v": "all"
            }, {
                "n": "2026",
                "v": "2026"
            }, {
                "n": "2025",
                "v": "2025"
            }, {
                "n": "2024",
                "v": "2024"
            }, {
                "n": "2023",
                "v": "2023"
            }, {
                "n": "2022",
                "v": "2022"
            }, {
                "n": "2021",
                "v": "2021"
            }, {
                "n": "2020",
                "v": "2020"
            }, {
                "n": "2019",
                "v": "2019"
            }, {
                "n": "2018",
                "v": "2018"
            }, {
                "n": "2017",
                "v": "2017"
            }, {
                "n": "2016",
                "v": "2016"
            }, {
                "n": "2015",
                "v": "2015"
            }, {
                "n": "2014",
                "v": "2014"
            }, {
                "n": "2013",
                "v": "2013"
            }, {
                "n": "2012",
                "v": "2012"
            }, {
                "n": "2011",
                "v": "2011"
            }, {
                "n": "2010",
                "v": "2010"
            }, {
                "n": "2009",
                "v": "2009"
            }, {
                "n": "2008",
                "v": "2008"
            }, {
                "n": "2007",
                "v": "2007"
            }, {
                "n": "2006",
                "v": "2006"
            }, {
                "n": "2005",
                "v": "2005"
            }, {
                "n": "2004",
                "v": "2004"
            }]
        }]
    },
    limit: 20,
    play_parse: true,
    lazy: $js.toString(() => {
        try {
            let api = "" + input.split("?")[0];
            console.log(api);
            let response = fetch(api, {
                method: 'get',
                headers: {
                    'User-Agent': 'okhttp/3.14.9',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            });
            let bata = JSON.parse(response);
            if (bata.url.includes("mgtv")) {
                input = {
                    parse: 0,
                    url: bata.url,
                    jx: 0,
                    danmaku: "http://127.0.0.1:9978/proxy?do=danmu&site=js&url=" + input.split("?")[0]
                };
            } else {
                input = {
                    parse: 0,
                    url: input.split("?")[0],
                    jx: 1,
                    danmaku: "http://127.0.0.1:9978/proxy?do=danmu&site=js&url=" + input.split("?")[0]
                };
            }
        } catch {
            input = {
                parse: 0,
                url: input.split("?")[0],
                jx: 1,
                danmaku: "http://127.0.0.1:9978/proxy?do=danmu&site=js&url=" + input.split("?")[0]
            };
        }
    }),
    // 手动调用解析请求json的url,此lazy不方便
    // lazy:'js:print(input);fetch_params.headers["user-agent"]=MOBILE_UA;let html=request(input);let rurl=html.match(/window\\.open\\(\'(.*?)\',/)[1];rurl=urlDeal(rurl);input={parse:1,url:rurl};',
    // 推荐:'.list_item;img&&alt;img&&src;a&&Text;a&&data-float',
    一级: 'json:data.hitDocs;title;img;updateInfo||rightCorner.text;playPartId',
    // 一级:'json:data.hitDocs;title;img;updateInfo;playPartId',
    二级: $js.toString(() => {
        fetch_params.headers.Referer = "https://www.mgtv.com";
        fetch_params.headers["User-Agent"] = MOBILE_UA;
        pdfh = jsp.pdfh;
        pdfa = jsp.pdfa;
        pd = jsp.pd;
        VOD = {};
        let d = [];
        let html = request(input);
        let json = JSON.parse(html);
        let host = "https://www.mgtv.com";
        let ourl = json.data.list.length > 0 ? json.data.list[0].url : json.data.series[0].url;
        if (!/^http/.test(ourl)) {
            ourl = host + ourl
        }
        fetch_params.headers["User-Agent"] = MOBILE_UA;
        html = request(ourl);
        if (html.includes("window.location =")) {
            print("开始获取ourl");
            ourl = pdfh(html, "meta[http-equiv=refresh]&&content").split("url=")[1];
            print("获取到ourl:" + ourl);
            html = request(ourl)
        }
        try {
            let details = pdfh(html, ".m-details&&Html").replace(/h1>/, "h6>").replace(/div/g, "br");
            print(details);
            let actor = "",
                director = "",
                time = "";
            if (/播出时间/.test(details)) {
                actor = pdfh(html, "p:eq(5)&&Text").substr(0, 25);
                director = pdfh(html, "p:eq(4)&&Text");
                time = pdfh(html, "p:eq(3)&&Text")
            } else {
                actor = pdfh(html, "p:eq(4)&&Text").substr(0, 25);
                director = pdfh(html, "p:eq(3)&&Text");
                time = "已完结"
            }
            let _img = pd(html, ".video-img&&img&&src");
            let JJ = pdfh(html, ".desc&&Text").split("简介：")[1];
            let _desc = time;
            VOD.vod_name = pdfh(html, ".vt-txt&&Text");
            VOD.type_name = pdfh(html, "p:eq(0)&&Text").substr(0, 6);
            VOD.vod_area = pdfh(html, "p:eq(1)&&Text");
            VOD.vod_actor = actor;
            VOD.vod_director = director;
            VOD.vod_remarks = _desc;
            VOD.vod_pic = _img;
            VOD.vod_content = JJ;
            if (!VOD.vod_name) {
                VOD.vod_name = VOD.type_name;
            }
        } catch (e) {
            log("获取影片信息发生错误:" + e.message)
        }

        function getRjpg(imgUrl, xs) {
            xs = xs || 3;
            let picSize = /jpg_/.test(imgUrl) ? imgUrl.split("jpg_")[1].split(".")[0] : false;
            let rjpg = false;
            if (picSize) {
                let a = parseInt(picSize.split("x")[0]) * xs;
                let b = parseInt(picSize.split("x")[1]) * xs;
                rjpg = a + "x" + b + ".jpg"
            }
            let img = /jpg_/.test(imgUrl) && rjpg ? imgUrl.replace(imgUrl.split("jpg_")[1], rjpg) : imgUrl;
            return img
        }

        if (json.data.total === 1 && json.data.list.length === 1) {
            let data = json.data.list[0];
            let url = "https://www.mgtv.com" + data.url;
            d.push({
                title: data.t4,
                desc: data.t2,
                pic_url: getRjpg(data.img),
                url: url
            })
        } else if (json.data.list.length > 1) {
            for (let i = 1; i <= json.data.total_page; i++) {
                if (i > 1) {
                    json = JSON.parse(fetch(input.replace("page=1", "page=" + i), {}))
                }
                json.data.list.forEach(function(data) {
                    let url = "https://www.mgtv.com" + data.url;
                    if (data.isIntact == "1") {
                        d.push({
                            title: data.t4,
                            desc: data.t2,
                            pic_url: getRjpg(data.img),
                            url: url
                        })
                    }
                })
            }
        } else {
            print(input + "暂无片源")
        }
        VOD.vod_play_from = "蓝光4k-原画60帧";
        VOD.vod_play_url = d.map(function(it) {
            return it.title + "$" + it.url
        }).join("#");
        setResult(d);
    }),

    搜索: $js.toString(() => {
        fetch_params.headers.Referer = "https://www.mgtv.com";
        fetch_params.headers["User-Agent"] = PC_UA;
        let d = [];
        // ── 签名辅助全部内联（drpy2 打平 eval 时全局函数不可见）──
        // 算法逆向自官网 pcweb-6.8.18 模块1304: 参数按 key 字典序排序 → qs 序列化(encodeURI) → MD5(盐+串+盐)
        let MGTV_SALT = 'xHAa3YZflWLogZUOzl';
        function _md5(s) {
            function L(a, b) { return (a << b) | (a >>> (32 - b)); }
            function K(x, y) { var l = (x & 0xFFFF) + (y & 0xFFFF), m = (x >> 16) + (y >> 16) + (l >> 16); return (m << 16) | (l & 0xFFFF); }
            function q(f, a, b, x, s, t) { return K(L(K(K(a, f), K(x, t)), s), b); }
            function F(a, b, c, d, x, s, t) { return q((b & c) | (~b & d), a, b, x, s, t); }
            function G(a, b, c, d, x, s, t) { return q((b & d) | (c & ~d), a, b, x, s, t); }
            function H(a, b, c, d, x, s, t) { return q(b ^ c ^ d, a, b, x, s, t); }
            function I(a, b, c, d, x, s, t) { return q(c ^ (b | ~d), a, b, x, s, t); }
            function toWords(str) {
                var w = [], i, n = str.length;
                for (i = 0; i < n * 8; i += 8) w[i >> 5] |= (str.charCodeAt(i / 8) & 0xFF) << (i % 32);
                return w;
            }
            function hex(x) { var s = '', i; for (i = 0; i < 4; i++) s += ('0' + ((x >> (i * 8)) & 0xFF).toString(16)).slice(-2); return s; }
            var bytes = unescape(encodeURIComponent(s));
            var x = toWords(bytes), n = bytes.length * 8, a = 1732584193, b = -271733879, c = -1732584194, dd = 271733878, i;
            x[n >> 5] |= 0x80 << (n % 32); x[(((n + 64) >>> 9) << 4) + 14] = n;
            for (i = 0; i < x.length; i += 16) {
                var oa = a, ob = b, oc = c, od = dd;
                a = F(a, b, c, dd, x[i], 7, -680876936); dd = F(dd, a, b, c, x[i + 1], 12, -389564586); c = F(c, dd, a, b, x[i + 2], 17, 606105819); b = F(b, c, dd, a, x[i + 3], 22, -1044525330);
                a = F(a, b, c, dd, x[i + 4], 7, -176418897); dd = F(dd, a, b, c, x[i + 5], 12, 1200080426); c = F(c, dd, a, b, x[i + 6], 17, -1473231341); b = F(b, c, dd, a, x[i + 7], 22, -45705983);
                a = F(a, b, c, dd, x[i + 8], 7, 1770035416); dd = F(dd, a, b, c, x[i + 9], 12, -1958414417); c = F(c, dd, a, b, x[i + 10], 17, -42063); b = F(b, c, dd, a, x[i + 11], 22, -1990404162);
                a = F(a, b, c, dd, x[i + 12], 7, 1804603682); dd = F(dd, a, b, c, x[i + 13], 12, -40341101); c = F(c, dd, a, b, x[i + 14], 17, -1502002290); b = F(b, c, dd, a, x[i + 15], 22, 1236535329);
                a = G(a, b, c, dd, x[i + 1], 5, -165796510); dd = G(dd, a, b, c, x[i + 6], 9, -1069501632); c = G(c, dd, a, b, x[i + 11], 14, 643717713); b = G(b, c, dd, a, x[i], 20, -373897302);
                a = G(a, b, c, dd, x[i + 5], 5, -701558691); dd = G(dd, a, b, c, x[i + 10], 9, 38016083); c = G(c, dd, a, b, x[i + 15], 14, -660478335); b = G(b, c, dd, a, x[i + 4], 20, -405537848);
                a = G(a, b, c, dd, x[i + 9], 5, 568446438); dd = G(dd, a, b, c, x[i + 14], 9, -1019803690); c = G(c, dd, a, b, x[i + 3], 14, -187363961); b = G(b, c, dd, a, x[i + 8], 20, 1163531501);
                a = G(a, b, c, dd, x[i + 13], 5, -1444681467); dd = G(dd, a, b, c, x[i + 2], 9, -51403784); c = G(c, dd, a, b, x[i + 7], 14, 1735328473); b = G(b, c, dd, a, x[i + 12], 20, -1926607734);
                a = H(a, b, c, dd, x[i + 5], 4, -378558); dd = H(dd, a, b, c, x[i + 8], 11, -2022574463); c = H(c, dd, a, b, x[i + 11], 16, 1839030562); b = H(b, c, dd, a, x[i + 14], 23, -35309556);
                a = H(a, b, c, dd, x[i + 1], 4, -1530992060); dd = H(dd, a, b, c, x[i + 4], 11, 1272893353); c = H(c, dd, a, b, x[i + 7], 16, -155497632); b = H(b, c, dd, a, x[i + 10], 23, -1094730640);
                a = H(a, b, c, dd, x[i + 13], 4, 681279174); dd = H(dd, a, b, c, x[i], 11, -358537222); c = H(c, dd, a, b, x[i + 3], 16, -722521979); b = H(b, c, dd, a, x[i + 6], 23, 76029189);
                a = H(a, b, c, dd, x[i + 9], 4, -640364487); dd = H(dd, a, b, c, x[i + 12], 11, -421815835); c = H(c, dd, a, b, x[i + 15], 16, 530742520); b = H(b, c, dd, a, x[i + 2], 23, -995338651);
                a = I(a, b, c, dd, x[i], 6, -198630844); dd = I(dd, a, b, c, x[i + 7], 10, 1126891415); c = I(c, dd, a, b, x[i + 14], 15, -1416354905); b = I(b, c, dd, a, x[i + 5], 21, -57434055);
                a = I(a, b, c, dd, x[i + 12], 6, 1700485571); dd = I(dd, a, b, c, x[i + 3], 10, -1894986606); c = I(c, dd, a, b, x[i + 10], 15, -1051523); b = I(b, c, dd, a, x[i + 1], 21, -2054922799);
                a = I(a, b, c, dd, x[i + 8], 6, 1873313359); dd = I(dd, a, b, c, x[i + 15], 10, -30611744); c = I(c, dd, a, b, x[i + 6], 15, -1560198380); b = I(b, c, dd, a, x[i + 13], 21, 1309151649);
                a = I(a, b, c, dd, x[i + 4], 6, -145523070); dd = I(dd, a, b, c, x[i + 11], 10, -1120210379); c = I(c, dd, a, b, x[i + 2], 15, 718787259); b = I(b, c, dd, a, x[i + 9], 21, -343485551);
                a = K(a, oa); b = K(b, ob); c = K(c, oc); dd = K(dd, od);
            }
            return hex(a) + hex(b) + hex(c) + hex(dd);
        }
        function _uuid() {
            return 'xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
                var r = Math.random() * 16 | 0;
                return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
            });
        }
        function _signedUrl(q, pn) {
            var params = {
                allowedRC: '1', src: 'mgtv', did: 'cf03b95969454cb6bcb388762459354d',
                timestamp: new Date().toISOString().replace(/\.\d{3}Z/, 'Z'),
                signVersion: '1', signNonce: _uuid(),
                q: q, pn: String(pn), pc: '10', corr: '1', _support: '10000000'
            };
            var keys = Object.keys(params).sort(function (a, b) { return a.localeCompare(b); });
            var qs = keys.map(function (k) { return k + '=' + encodeURI(String(params[k])); }).join('&');
            return 'https://mobileso.bz.mgtv.com/pc/search/v2?' + qs + '&signature=' + _md5(MGTV_SALT + qs + MGTV_SALT);
        }
        // ── 从占位 searchUrl 解析关键词和页码，重新生成带签名的 v2 请求 ──
        let wd = '';
        try { wd = decodeURIComponent((input.match(/[?&]q=([^&]*)/) || [])[1] || ''); } catch (e) { wd = (input.match(/[?&]q=([^&]*)/) || [])[1] || ''; }
        let pg = (input.match(/[?&]pn=(\d+)/) || [])[1] || '1';
        let url = _signedUrl(wd, pg);
        let html = request(url);
        let json = JSON.parse(html);
        // 注意: drpy2 打平 eval 函数体，顶层禁止 return，必须用 if 包裹
        if (json.data && json.data.contents) {
            json.data.contents.forEach(function(data) {
            let d0 = data.data;
            if (!d0 || typeof d0 !== 'object' || Array.isArray(d0)) return;
            // 剧集/综艺可能按年份分多组（yearList），逐组作为独立结果
            let cards = (d0.yearList && d0.yearList.length) ? d0.yearList : [d0];
            cards.forEach(function(item) {
                let title = (item.hitTitle || item.title || '').replace(/<[^>]+>/g, '');
                let img = item.pic || '';
                let descArr = [];
                if (Array.isArray(item.desc)) {
                    item.desc.forEach(function(x) {
                        descArr.push((x.label ? x.label + ':' : '') + (x.text || ''));
                    });
                }
                if (item.playTime) descArr.push(item.playTime);
                let vid = '';
                let src = (item.sourceList && item.sourceList.length) ? item.sourceList[0] : null;
                if (src) {
                    // 只保留芒果自家源，qq 等外链源在二级无法解析，跳过
                    if (src.source !== 'imgo') return;
                    vid = src.vid ? String(src.vid) : '';
                } else if (item.vid) {
                    vid = String(item.vid);
                }
                // vid 缺失时从播放页 url(/b/cid/vid.html) 兜底提取；/h/cid.html 专辑页无法用于二级
                if (!vid) {
                    let pageUrl = (src && src.url) || item.url || '';
                    let m = String(pageUrl).match(/\/b\/\d+\/(\d+)\.html/);
                    if (m) vid = m[1];
                }
                if (!vid || !title) return;
                d.push({
                    title: title,
                    img: img,
                    content: '',
                    desc: descArr.join(','),
                    url: vid
                });
            });
            });
        }
        setResult(d);
    }),
}