var rule = {
    title: '优酷[官]',
    host: 'https://www.youku.com',
    homeUrl: '',
    searchUrl: 'https://search.youku.com/api/search?pg=fypage&keyword=**',
    searchable: 2,
    quickSearch: 0,
    filterable: 1,
    multi: 1,
    url: '/category/data?optionRefresh=1&pageNo=fypage&params=fyfilter',
    filter_url: '{{fl}}',
    headers: {
        'User-Agent': 'PC_UA',
        'Referer': 'https://www.youku.com'
    },
    timeout: 5000,
    class_name: '电视剧&电影&综艺&动漫&少儿&纪录片&文化&亲子&教育&搞笑&生活&体育&音乐&游戏',
    class_url: '电视剧&电影&综艺&动漫&少儿&纪录片&文化&亲子&教育&搞笑&生活&体育&音乐&游戏',
    limit: 20,
    play_parse: true,
    lazy: $js.toString(() => {
        let parse_url = [
        "http://192.140.166.17:8864/api/index?parsesId=4&appid=10000&videoUrl=",
         "http://103.236.72.166:188/api/?key=veniDOaEzSzIThZsyb&url=",
         "https://api.jxapi.cc/api/?key=e0df4139f1e7f09375e864cc4937570e&url=",
           'https://jx.hls.one/?url=',
           'https://jx.xmflv.com/?url=',,
          "http://www.ckplayer.vip/jiexi/?url=",
            'http://1.94.244.214:8889/geturl?url='
        ];

        let targetUrl = input;

        function tryParse(url, index) {
            if (index >= parse_url.length) {
                print("所有解析接口都失败");
                input = { parse: 0, url: url, jx: 1, danmaku: '' };
                return;
            }

            let parseUrl = parse_url[index] + encodeURIComponent(url);
            print("尝试解析接口" + (index + 1));

            try {
                let response = fetch(parseUrl, {
                    method: 'get',
                    headers: { 'User-Agent': 'okhttp/3.14.9' }
                });

                if (!response || response.length < 10) {
                    print("接口" + (index + 1) + "无响应，尝试下一个");
                    tryParse(url, index + 1);
                    return;
                }

                let data = JSON.parse(response);
                let playUrl = data.url || data.playUrl || data.data;

                if (playUrl && playUrl.indexOf('http') > -1) {
                    print("接口" + (index + 1) + "成功");
                    input = { parse: 0, url: playUrl, jx: 0, danmaku: '' };
                } else {
                    print("接口" + (index + 1) + "无效URL，尝试下一个");
                    tryParse(url, index + 1);
                }
            } catch (e) {
                print("接口" + (index + 1) + "失败: " + e.message + "，尝试下一个");
                tryParse(url, index + 1);
            }
        }

        tryParse(targetUrl, 0);
    }),
    一级: $js.toString(() => {
        let d = [];
        MY_FL.type = MY_CATE;
        let fl = stringify(MY_FL);
        fl = encodeUrl(fl);
        input = input.split('{')[0] + fl;
        if (MY_PAGE > 1) {
            let old_session = getItem('yk_session_' + MY_CATE, '{}');
            if (MY_PAGE === 2) {
                input = input.replace('optionRefresh=1', 'session=' + encodeUrl(old_session))
            } else {
                input = input.replace('optionRefresh=1', 'session=' + encodeUrl(old_session))
            }
        }
        let html = fetch(input, fetch_params);
        try {
            html = JSON.parse(html);
            let lists = html.data.filterData.listData;
            let session = html.data.filterData.session;
            session = stringify(session);
            if (session !== getItem('yk_session_' + MY_CATE, '{}')) {
                setItem('yk_session_' + MY_CATE, session)
            }
            lists.forEach(function(it) {
                let vid;
                if (it.videoLink.includes('id_')) {
                    vid = it.videoLink.split('id_')[1].split('.html')[0]
                } else {
                    vid = 'msearch:'
                }
                d.push({
                    title: it.title,
                    img: it.img,
                    desc: it.summary,
                    url: 'https://search.youku.com/api/search?appScene=show_episode&showIds=' + vid,
                    content: it.subTitle
                })
            })
        } catch (e) {
            log('一级列表解析发生错误:' + e.message)
        }
        setResult(d);
    }),
    二级: $js.toString(() => {
        var d = [];
        VOD = {};
        let html = request(input);
        let json = JSON.parse(html);

        function getShowId(url) {
            if (!url) return null;
            let match = url.match(/[?&]showIds=([^&]+)/);
            if (match && match[1]) {
                return decodeURIComponent(match[1]);
            }
            return null;
        }

        if (/keyword/.test(input)) {
            let showId = getShowId(input);
            if (showId) {
                input = 'https://search.youku.com/api/search?appScene=show_episode&showIds=' + showId;
                json = JSON.parse(fetch(MY_URL, fetch_params))
            }
        }

        let video_lists = json.serisesList;
        var name = json.sourceName || '优酷';
        if (/优酷/.test(name) && video_lists && video_lists.length > 0) {
            let ourl = 'https://v.youku.com/v_show/id_' + video_lists[0].videoId + '.html';
            let _img = video_lists[0].thumbUrl || '';
            let html = fetch(ourl, { headers: { Referer: 'https://v.youku.com/', 'User-Agent': PC_UA } });
            let json = /__INITIAL_DATA__/.test(html) ? html.split('window.__INITIAL_DATA__ =')[1].split(';')[0] : '{}';
            if (json === '{}') {
                log('触发了优酷人机验证');
                VOD.vod_remarks = ourl;
                VOD.vod_pic = _img;
                VOD.vod_name = (video_lists[0].title || '').replace(/(\d+)/g, '');
                VOD.vod_content = '触发了优酷人机验证,本次未获取详情,但不影响播放(' + ourl + ')'
            } else {
                try {
                    json = JSON.parse(json);
                    let data = json.data.data;
                    let data_extra = data.data.extra;
                    let img = data_extra.showImgV || '';
                    let model = json.data.model;
                    let m = model.detail.data.nodes[0].nodes[0].nodes[0].data;
                    let _type = m.showGenre || '';
                    let _desc = m.updateInfo || m.subtitle || '';
                    let JJ = m.desc || '';
                    let _title = m.introTitle || '';
                    let _title_clean = _title.replace(/第\d+集/g, '').replace(/\s+/g, '').trim();
                    VOD.vod_pic = img;
                    VOD.vod_name = _title_clean || _title;
                    VOD.vod_type = _type;
                    VOD.vod_remarks = _desc;
                    VOD.vod_content = JJ
                } catch (e) {
                    log('海报渲染发生错误:' + e.message);
                    print(json);
                    VOD.vod_name = video_lists[0].title || '';
                    VOD.vod_remarks = name
                }
            }
        }
        if (!VOD.vod_name) {
            VOD.vod_name = video_lists && video_lists[0] ? (video_lists[0].title || '') : ''
        }
        if (!/优酷/.test(name)) {
            VOD.vod_content = '非自家播放源,暂无视频简介及海报';
            VOD.vod_remarks = name
        }
        function adhead(url) {
            return urlencode(url)
        }
        play_url = play_url.replace('&play_url=', '&type=json&play_url=');
        if (video_lists) {
            // 提取纯净的剧名用于去重
            let baseTitle = (VOD.vod_name || '').replace(/第[\d一二三四五六七八九十]+集/g, '').replace(/第[\d]+期/g, '').replace(/\s+/g, '').trim();
            if (!baseTitle && video_lists[0]) {
                baseTitle = (video_lists[0].title || '').replace(/第[\d一二三四五六七八九十]+集/g, '').replace(/第[\d]+期/g, '').replace(/\s+/g, '').trim();
            }
            video_lists.forEach(function(it) {
                let url = 'https://v.youku.com/v_show/id_' + it.videoId + '.html';
                if (it.thumbUrl) {
                    let rawTitle = it.title || it.displayName || '';
                    let cleanTitle = rawTitle;
                    // 去掉剧名重复部分
                    if (baseTitle && rawTitle.length > baseTitle.length) {
                        if (rawTitle.indexOf(baseTitle) === 0) {
                            cleanTitle = rawTitle.substring(baseTitle.length).trim() || rawTitle;
                        }
                    }
                    // 如果去重后为空，使用集数格式
                    if (!cleanTitle || cleanTitle === rawTitle) {
                        if (it.showVideoStage) {
                            cleanTitle = it.showVideoStage.replace(/^第/, '').replace(/期$/, '集') || rawTitle;
                        }
                    }
                    d.push({ desc: it.showVideoStage ? it.showVideoStage.replace('期', '集') : it.displayName, pic_url: it.thumbUrl, title: cleanTitle, url: play_url + adhead(url) })
                } else if (name !== '优酷') {
                    d.push({ title: it.displayName ? it.displayName : it.title, url: play_url + adhead(it.url) })
                }
            });
        }
        VOD.vod_play_from = name;
        VOD.vod_play_url = d.map(function(it) {
            return it.title + '$' + it.url
        }).join('#');
    }),
    搜索: $js.toString(() => {
        var d = [];
        let html = request(input);
        let json = JSON.parse(html);
        json.pageComponentList.forEach(function(it) {
            if (it.hasOwnProperty('commonData')) {
                it = it.commonData;
                d.push({
                    title: it.titleDTO ? (it.titleDTO.displayName || '') : '',
                    img: it.posterDTO ? (it.posterDTO.vThumbUrl || '') : '',
                    desc: it.stripeBottom || '',
                    content: (it.updateNotice || '') + ' ' + (it.feature || ''),
                    url: 'https://search.youku.com/api/search?appScene=show_episode&showIds=' + it.showId
                })
            }
        });
        setResult(d)
    }),
    filter: {
        "电视剧": [
            { "key": "main_area", "name": "全部地区", "value": [{ "n": "全部地区", "v": "" }, { "n": "内地剧", "v": "中国内地" }, { "n": "港剧", "v": "中国香港" }, { "n": "台剧", "v": "中国台湾" }, { "n": "韩剧", "v": "韩国" }, { "n": "美剧", "v": "美国" }, { "n": "英剧", "v": "英国" }, { "n": "日剧", "v": "日本" }, { "n": "泰剧", "v": "泰国" }] },
            { "key": "tags", "name": "全部类型", "value": [{ "n": "全部类型", "v": "" }, { "n": "青春", "v": "青春" }, { "n": "古装", "v": "古装" }, { "n": "爱情", "v": "爱情" }, { "n": "都市", "v": "都市" }, { "n": "喜剧", "v": "喜剧,搞笑" }, { "n": "战争", "v": "战争" }, { "n": "军旅", "v": "军旅" }, { "n": "谍战", "v": "谍战" }, { "n": "偶像", "v": "偶像" }, { "n": "警匪", "v": "警匪" }, { "n": "冒险", "v": "冒险" }, { "n": "穿越", "v": "穿越" }, { "n": "仙侠", "v": "仙侠" }, { "n": "武侠", "v": "武侠" }, { "n": "悬疑", "v": "悬疑" }, { "n": "罪案", "v": "罪案" }, { "n": "家庭", "v": "家庭" }, { "n": "历史", "v": "历史" }, { "n": "年代", "v": "年代" }, { "n": "农村", "v": "农村" }] },
            { "key": "year", "name": "全部年份", "value": [{ "n": "全部年份", "v": "" }, { "n": "2025", "v": "2025" }, { "n": "2024", "v": "2024" }, { "n": "2023", "v": "2023" }, { "n": "2022", "v": "2022" }, { "n": "2021", "v": "2021" }, { "n": "2020", "v": "2020" }, { "n": "2019", "v": "2019" }, { "n": "2018", "v": "2018" }, { "n": "2017", "v": "2017" }, { "n": "2016", "v": "2016" }, { "n": "2015", "v": "2015" }, { "n": "2014-2011", "v": "2011-2014" }, { "n": "更早", "v": "-2010" }] },
            { "key": "status", "name": "全部规格", "value": [{ "n": "全部规格", "v": "" }, { "n": "全网独播", "v": "1" }, { "n": "优酷自制", "v": "2" }, { "n": "已完结", "v": "3" }, { "n": "即将上线", "v": "4" }, { "n": "短剧", "v": "5" }] },
            { "key": "pay_type", "name": "付费类型", "value": [{ "n": "付费类型", "v": "" }, { "n": "免费", "v": "0" }, { "n": "VIP", "v": "2" }, { "n": "付费", "v": "1" }] },
            { "key": "sort", "name": "综合排序", "value": [{ "n": "综合排序", "v": "" }, { "n": "热度最高", "v": "7" }, { "n": "最新上线", "v": "1" }, { "n": "最好评", "v": "3" }, { "n": "最多播放", "v": "2" }] }
        ],
        "电影": [
            { "key": "main_area", "name": "全部地区", "value": [{ "n": "全部地区", "v": "" }, { "n": "内地", "v": "中国内地" }, { "n": "中国香港", "v": "中国香港" }, { "n": "中国台湾", "v": "中国台湾" }, { "n": "美国", "v": "美国" }, { "n": "印度", "v": "印度" }, { "n": "日韩", "v": "韩国,日本" }, { "n": "泰国", "v": "泰国" }, { "n": "欧洲", "v": "欧洲" }] },
            { "key": "tags", "name": "全部类型", "value": [{ "n": "全部类型", "v": "" }, { "n": "喜剧", "v": "喜剧,搞笑" }, { "n": "动作", "v": "动作" }, { "n": "怪兽", "v": "怪兽" }, { "n": "战争", "v": "战争" }, { "n": "爱情", "v": "爱情" }, { "n": "悬疑", "v": "悬疑" }, { "n": "武侠", "v": "武侠" }, { "n": "奇幻", "v": "奇幻" }, { "n": "科幻", "v": "科幻" }, { "n": "冒险", "v": "冒险" }, { "n": "警匪", "v": "警匪" }, { "n": "动画", "v": "动画" }, { "n": "惊悚", "v": "惊悚" }, { "n": "犯罪", "v": "犯罪" }, { "n": "恐怖", "v": "恐怖" }, { "n": "剧情", "v": "剧情" }, { "n": "历史", "v": "历史" }, { "n": "纪录片", "v": "纪录片" }, { "n": "传记", "v": "传记" }, { "n": "歌舞", "v": "歌舞" }, { "n": "短片", "v": "短片" }, { "n": "其他", "v": "其他" }] },
            { "key": "source", "name": "全部规格", "value": [{ "n": "全部规格", "v": "" }, { "n": "院线", "v": "1" }, { "n": "网络电影", "v": "0" }, { "n": "独播", "v": "2" }, { "n": "高清修复", "v": "3" }, { "n": "1080P", "v": "4" }] },
            { "key": "year", "name": "全部年份", "value": [{ "n": "全部年份", "v": "" }, { "n": "2025", "v": "2025" }, { "n": "2024", "v": "2024" }, { "n": "2023", "v": "2023" }, { "n": "2022", "v": "2022" }, { "n": "2021", "v": "2021" }, { "n": "2020", "v": "2020" }, { "n": "2019", "v": "2019" }, { "n": "2018", "v": "2018" }, { "n": "2017", "v": "2017" }, { "n": "2016", "v": "2016" }, { "n": "2015", "v": "2015" }, { "n": "2014-2010", "v": "2010-2014" }, { "n": "2009-2000", "v": "2000-2009" }, { "n": "90年代", "v": "1990-1999" }, { "n": "80年代", "v": "1980-1989" }, { "n": "70年代", "v": "1970-1979" }, { "n": "更早", "v": "-1969" }] },
            { "key": "pay_type", "name": "付费类型", "value": [{ "n": "付费类型", "v": "" }, { "n": "免费", "v": "0" }, { "n": "会员", "v": "2" }, { "n": "点播", "v": "1" }] },
            { "key": "sort", "name": "综合排序", "value": [{ "n": "综合排序", "v": "" }, { "n": "热度最高", "v": "7" }, { "n": "最多播放", "v": "2" }, { "n": "最新上线", "v": "1" }, { "n": "最好评", "v": "3" }] }
        ],
        "综艺": [
            { "key": "main_area", "name": "全部地区", "value": [{ "n": "全部地区", "v": "" }, { "n": "内地", "v": "中国内地" }, { "n": "中国台湾", "v": "中国台湾" }, { "n": "美国", "v": "美国" }, { "n": "英国", "v": "英国" }] },
            { "key": "tags", "name": "全部类型", "value": [{ "n": "全部类型", "v": "" }, { "n": "偶像", "v": "偶像" }, { "n": "舞蹈", "v": "舞蹈" }, { "n": "音乐", "v": "音乐" }, { "n": "情感", "v": "情感" }, { "n": "喜剧", "v": "喜剧,搞笑" }, { "n": "体育", "v": "体育" }, { "n": "游戏", "v": "游戏" }, { "n": "相声", "v": "相声" }, { "n": "婚恋", "v": "婚恋" }, { "n": "时尚", "v": "时尚" }, { "n": "晚会", "v": "晚会" }, { "n": "明星访谈", "v": "明星访谈" }, { "n": "亲子", "v": "亲子" }, { "n": "生活", "v": "生活" }, { "n": "文化", "v": "文化" }, { "n": "美食", "v": "美食" }, { "n": "旅游", "v": "旅游" }, { "n": "益智", "v": "益智" }] },
            { "key": "year", "name": "全部年份", "value": [{ "n": "全部年份", "v": "" }, { "n": "2025", "v": "2025" }, { "n": "2024", "v": "2024" }, { "n": "2023", "v": "2023" }, { "n": "2022", "v": "2022" }, { "n": "2021", "v": "2021" }, { "n": "2020", "v": "2020" }, { "n": "2019", "v": "2019" }, { "n": "2018", "v": "2018" }, { "n": "2017", "v": "2017" }, { "n": "2016", "v": "2016" }, { "n": "2015", "v": "2015" }, { "n": "2014-2011", "v": "2011-2014" }, { "n": "更早", "v": "-2010" }] },
            { "key": "status", "name": "全部规格", "value": [{ "n": "全部规格", "v": "" }, { "n": "优酷自制", "v": "2" }, { "n": "优酷独播", "v": "1" }, { "n": "电视综艺", "v": "6" }, { "n": "已完结", "v": "3" }, { "n": "即将上线", "v": "4" }] },
            { "key": "pay_type", "name": "付费类型", "value": [{ "n": "付费类型", "v": "" }, { "n": "免费", "v": "0" }, { "n": "VIP", "v": "2" }, { "n": "付费", "v": "1" }] },
            { "key": "sort", "name": "热度最高", "value": [{ "n": "热度最高", "v": "" }, { "n": "最新更新", "v": "8" }, { "n": "最近开播", "v": "9" }, { "n": "最多评论", "v": "4" }] }
        ],
        "动漫": [
            { "key": "sort", "name": "综合排序", "value": [{ "n": "综合排序", "v": "" }, { "n": "最多播放", "v": "2" }, { "n": "最好评", "v": "3" }, { "n": "最新上线", "v": "1" }] },
            { "key": "main_area", "name": "全部地区", "value": [{ "n": "全部地区", "v": "" }, { "n": "内地", "v": "中国内地" }, { "n": "日本", "v": "日本" }, { "n": "美国", "v": "美国" }, { "n": "中国台湾", "v": "中国台湾" }, { "n": "其他", "v": "其他" }] },
            { "key": "tags", "name": "全部类型", "value": [{ "n": "全部类型", "v": "" }, { "n": "热血", "v": "热血,战斗" }, { "n": "励志", "v": "励志" }, { "n": "玄幻", "v": "玄幻" }, { "n": "古风", "v": "历史,古风" }, { "n": "恋爱", "v": "恋爱" }, { "n": "青春", "v": "青春" }, { "n": "校园", "v": "校园" }, { "n": "运动", "v": "社团,运动" }, { "n": "科幻", "v": "科幻" }, { "n": "冒险", "v": "冒险" }, { "n": "魔法", "v": "魔法" }, { "n": "日常", "v": "日常" }, { "n": "治愈", "v": "治愈" }, { "n": "机战", "v": "机战" }, { "n": "推理", "v": "推理" }, { "n": "都市", "v": "都市" }, { "n": "小说改", "v": "小说改编" }, { "n": "游戏改", "v": "游戏改编" }, { "n": "漫画改", "v": "漫画改编" }, { "n": "动态漫", "v": "动态漫画" }, { "n": "特摄", "v": "特摄" }, { "n": "布袋戏", "v": "布袋戏" }] },
            { "key": "completed", "name": "连载情况", "value": [{ "n": "连载情况", "v": "" }, { "n": "更新中", "v": "0" }, { "n": "已完结", "v": "1" }] },
            { "key": "pay_type", "name": "付费类型", "value": [{ "n": "付费类型", "v": "" }, { "n": "免费", "v": "0" }, { "n": "会员", "v": "2" }] },
            { "key": "year", "name": "全部年份", "value": [{ "n": "全部年份", "v": "" }, { "n": "2025", "v": "2025" }, { "n": "2024", "v": "2024" }, { "n": "2023", "v": "2023" }, { "n": "2022", "v": "2022" }, { "n": "2021", "v": "2021" }, { "n": "2020", "v": "2020" }, { "n": "2019", "v": "2019" }, { "n": "2018", "v": "2018" }, { "n": "2017", "v": "2017" }, { "n": "2016", "v": "2016" }, { "n": "2015", "v": "2015" }, { "n": "2014", "v": "2014" }, { "n": "2013", "v": "2013" }, { "n": "2012", "v": "2012" }, { "n": "2011", "v": "2011" }, { "n": "00年代", "v": "2000-2010" }, { "n": "更早", "v": "-1999" }] }
        ],
        "少儿": [
            { "key": "main_area", "name": "全部地区", "value": [{ "n": "全部地区", "v": "" }, { "n": "中国", "v": "中国,香港,台湾" }, { "n": "美国", "v": "美国" }, { "n": "英国", "v": "英国" }, { "n": "其他国家", "v": "其他" }] },
            { "key": "show_label_type", "name": "全部类型", "value": [{ "n": "全部类型", "v": "" }, { "n": "动画", "v": "动画" }, { "n": "儿歌", "v": "儿歌" }, { "n": "玩具", "v": "玩具" }, { "n": "动画电影", "v": "电影" }, { "n": "绘本故事", "v": "绘本故事" }, { "n": "真人", "v": "真人" }, { "n": "少儿综艺", "v": "少儿综艺" }, { "n": "亲子", "v": "亲子" }, { "n": "探索纪实", "v": "探索纪实" }, { "n": "音频", "v": "音频" }] },
            { "key": "child_tags", "name": "全部分类", "value": [{ "n": "全部分类", "v": "" }, { "n": "益智", "v": "益智" }, { "n": "冒险", "v": "冒险" }, { "n": "幽默", "v": "幽默" }, { "n": "机甲", "v": "机甲" }, { "n": "公主魔法", "v": "公主,魔法" }, { "n": "交通工具", "v": "交通工具" }, { "n": "恐龙", "v": "恐龙" }, { "n": "动物", "v": "动物" }, { "n": "励志", "v": "励志" }, { "n": "友情", "v": "友情" }, { "n": "战斗", "v": "战斗" }, { "n": "校园", "v": "校园" }, { "n": "正义", "v": "正义" }, { "n": "热血", "v": "热血" }, { "n": "科幻", "v": "科幻" }, { "n": "童话", "v": "童话" }, { "n": "运动", "v": "运动" }, { "n": "专注力", "v": "专注力" }, { "n": "创造力", "v": "创造力" }, { "n": "想象力", "v": "想象力" }, { "n": "科普", "v": "科普" }, { "n": "情商", "v": "情商" }, { "n": "思维逻辑", "v": "思维逻辑" }, { "n": "兴趣培养", "v": "兴趣培养" }, { "n": "语文", "v": "语文" }, { "n": "英语", "v": "英语" }, { "n": "数学", "v": "数学" }, { "n": "课程辅导", "v": "课程辅导" }] },
            { "key": "age", "name": "全部年龄", "value": [{ "n": "全部年龄", "v": "" }, { "n": "0-2岁", "v": "0-2" }, { "n": "3-4岁", "v": "3-4" }, { "n": "5-6岁", "v": "5-6" }, { "n": "7岁以上", "v": "7-" }] },
            { "key": "pay_type", "name": "付费类型", "value": [{ "n": "付费类型", "v": "" }, { "n": "免费", "v": "0" }, { "n": "付费", "v": "1" }, { "n": "VIP", "v": "2" }] },
            { "key": "sort", "name": "综合排序", "value": [{ "n": "综合排序", "v": "" }, { "n": "最新上线", "v": "1" }, { "n": "最多播放", "v": "2" }, { "n": "最多评论", "v": "4" }, { "n": "最多收藏", "v": "5" }] }
        ],
        "纪录片": [
            { "key": "tags", "name": "全部类型", "value": [{ "n": "全部类型", "v": "" }, { "n": "美食", "v": "美食" }, { "n": "自然", "v": "自然" }, { "n": "历史", "v": "历史" }, { "n": "探险", "v": "探险" }, { "n": "军事", "v": "军事" }, { "n": "人物", "v": "人物" }, { "n": "宇宙", "v": "宇宙" }, { "n": "刑侦", "v": "刑侦" }, { "n": "社会", "v": "社会" }, { "n": "科技", "v": "科技" }, { "n": "旅游", "v": "旅游" }] },
            { "key": "company", "name": "全部出品", "value": [{ "n": "全部出品", "v": "" }, { "n": "BBC", "v": "bbc,british" }, { "n": "央视", "v": "央视,中央电视台,cctv,中国广播电影电视节目交易中心" }, { "n": "国家地理", "v": "国家地理" }, { "n": "Love Nature", "v": "love nature" }, { "n": "LGI", "v": "looking" }, { "n": "A&E", "v": "ae" }, { "n": "OTF", "v": "fence" }] },
            { "key": "year", "name": "全部年份", "value": [{ "n": "全部年份", "v": "" }, { "n": "2025", "v": "2025" }, { "n": "2024", "v": "2024" }, { "n": "2023", "v": "2023" }, { "n": "2022", "v": "2022" }, { "n": "2021", "v": "2021" }, { "n": "2020", "v": "2020" }, { "n": "2019", "v": "2019" }, { "n": "2018", "v": "2018" }, { "n": "2017", "v": "2017" }, { "n": "2016", "v": "2016" }, { "n": "2015", "v": "2015" }, { "n": "2014-2011", "v": "2011-2014" }, { "n": "更早", "v": "-2010" }] },
            { "key": "pay_type", "name": "付费类型", "value": [{ "n": "付费类型", "v": "" }, { "n": "免费", "v": "0" }, { "n": "会员", "v": "2" }] },
            { "key": "sort", "name": "热度最高", "value": [{ "n": "热度最高", "v": "" }, { "n": "综合排序", "v": "0" }, { "n": "最新上线", "v": "1" }, { "n": "最好评", "v": "3" }, { "n": "最多收藏", "v": "5" }] }
        ]
    }
};