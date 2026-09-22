let host = 'https://api.bilibili.com';
let headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com",
    "Cookie": "bili_jct=8d857e6102f03611ebc812dd1832c6ed; DedeUserID=701168335; SESSDATA=f0d59c35%2C1770188969%2Cd19d6%2A81CjCR7VuWQpC5Aps2RKhzCed6afXrGsS7ArTXuWKduCIlnjKvs-NFL-AOOhDWA0q3lh4SVmNINmZmVWpjMGVNbFlmS1piODR4WkRyTFBTNUo5Y3E0VExkcFdESm1JSkEyVzJyZzRkQ1RzYzNrcGJ6M0NwNkVmZjJ5UnowZENLY2RFb2RzQ0k0a25BIIEC;"
};

async function init(cfg) {}

/**
 * 通用解析：从 Bilibili API JSON 中提取视频列表
 */
function getVideos(json) {
    let videos = [];
    if (json["code"] !== 0) return videos;
    let vodList = json.result ? json.result.list : (json.data ? json.data.list : []);
    vodList.forEach(vod => {
        let aid = (vod["season_id"] + "").trim();
        let title = vod["title"].trim();
        let img = vod["cover"].trim();
        let remark = vod.new_ep ? vod["new_ep"]["index_show"] : (vod["index_show"] || "");
        videos.push({
            vod_id: aid,
            vod_name: title,
            vod_pic: img,
            vod_remarks: remark
        });
    });
    return videos;
}

async function home(filter) {
    return JSON.stringify({
        "class": [
            {"type_id": "10033", "type_name": "历史"},
            {"type_id": "10065", "type_name": "人文"},
            {"type_id": "10068", "type_name": "宇宙"},
            {"type_id": "10072", "type_name": "自然"},
            {"type_id": "10067", "type_name": "探险"},
            {"type_id": "10071", "type_name": "动物"},
            {"type_id": "10066", "type_name": "科技"},
            {"type_id": "10045", "type_name": "美食"}
        ],
        "filters": {
            "10033": [{"key": "order", "name": "排序", "value": [{"n": "播放数量", "v": "2"}, {"n": "更新时间", "v": "0"}, {"n": "最高评分", "v": "4"}, {"n": "弹幕数量", "v": "1"}, {"n": "追看人数", "v": "3"}, {"n": "开播时间", "v": "5"}, {"n": "上映时间", "v": "6"}]}, {"key": "season_status", "name": "付费", "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "付费", "v": "2%2C6"}, {"n": "大会员", "v": "4%2C6"}]}],
            "10065": [{"key": "order", "name": "排序", "value": [{"n": "播放数量", "v": "2"}, {"n": "更新时间", "v": "0"}, {"n": "最高评分", "v": "4"}, {"n": "弹幕数量", "v": "1"}, {"n": "追看人数", "v": "3"}, {"n": "开播时间", "v": "5"}, {"n": "上映时间", "v": "6"}]}, {"key": "season_status", "name": "付费", "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "付费", "v": "2%2C6"}, {"n": "大会员", "v": "4%2C6"}]}],
            "10068": [{"key": "order", "name": "排序", "value": [{"n": "播放数量", "v": "2"}, {"n": "更新时间", "v": "0"}, {"n": "最高评分", "v": "4"}, {"n": "弹幕数量", "v": "1"}, {"n": "追看人数", "v": "3"}, {"n": "开播时间", "v": "5"}, {"n": "上映时间", "v": "6"}]}, {"key": "season_status", "name": "付费", "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "付费", "v": "2%2C6"}, {"n": "大会员", "v": "4%2C6"}]}],
            "10072": [{"key": "order", "name": "排序", "value": [{"n": "播放数量", "v": "2"}, {"n": "更新时间", "v": "0"}, {"n": "最高评分", "v": "4"}, {"n": "弹幕数量", "v": "1"}, {"n": "追看人数", "v": "3"}, {"n": "开播时间", "v": "5"}, {"n": "上映时间", "v": "6"}]}, {"key": "season_status", "name": "付费", "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "付费", "v": "2%2C6"}, {"n": "大会员", "v": "4%2C6"}]}],
            "10067": [{"key": "order", "name": "排序", "value": [{"n": "播放数量", "v": "2"}, {"n": "更新时间", "v": "0"}, {"n": "最高评分", "v": "4"}, {"n": "弹幕数量", "v": "1"}, {"n": "追看人数", "v": "3"}, {"n": "开播时间", "v": "5"}, {"n": "上映时间", "v": "6"}]}, {"key": "season_status", "name": "付费", "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "付费", "v": "2%2C6"}, {"n": "大会员", "v": "4%2C6"}]}],
            "10071": [{"key": "order", "name": "排序", "value": [{"n": "播放数量", "v": "2"}, {"n": "更新时间", "v": "0"}, {"n": "最高评分", "v": "4"}, {"n": "弹幕数量", "v": "1"}, {"n": "追看人数", "v": "3"}, {"n": "开播时间", "v": "5"}, {"n": "上映时间", "v": "6"}]}, {"key": "season_status", "name": "付费", "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "付费", "v": "2%2C6"}, {"n": "大会员", "v": "4%2C6"}]}],
            "10066": [{"key": "order", "name": "排序", "value": [{"n": "播放数量", "v": "2"}, {"n": "更新时间", "v": "0"}, {"n": "最高评分", "v": "4"}, {"n": "弹幕数量", "v": "1"}, {"n": "追看人数", "v": "3"}, {"n": "开播时间", "v": "5"}, {"n": "上映时间", "v": "6"}]}, {"key": "season_status", "name": "付费", "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "付费", "v": "2%2C6"}, {"n": "大会员", "v": "4%2C6"}]}],
            "10045": [{"key": "order", "name": "排序", "value": [{"n": "播放数量", "v": "2"}, {"n": "更新时间", "v": "0"}, {"n": "最高评分", "v": "4"}, {"n": "弹幕数量", "v": "1"}, {"n": "追看人数", "v": "3"}, {"n": "开播时间", "v": "5"}, {"n": "上映时间", "v": "6"}]}, {"key": "season_status", "name": "付费", "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "付费", "v": "2%2C6"}, {"n": "大会员", "v": "4%2C6"}]}]
        }
    });
}

async function homeVod() {
    let url = host + "/pgc/web/rank/list?season_type=3&pagesize=30&page=1&day=3";
    let resp = await req(url, { headers: headers });
    let jo = JSON.parse(resp.content);
    return JSON.stringify({ list: getVideos(jo) });
}

async function category(tid, pg, filter, extend) {
    let p = pg || 1;
    let order = (extend && extend.order) ? extend.order : "2";
    let season_status = (extend && extend.season_status) ? extend.season_status : "1";
    let url = host + "/pgc/season/index/result?order=" + order + "&pagesize=20&style_id=" + tid + "&type=1&season_type=3&st=3&page=" + p + "&season_status=" + season_status;
    let resp = await req(url, { headers: headers });
    let jo = JSON.parse(resp.content);
    return JSON.stringify({
        "list": getVideos(jo),
        "page": parseInt(p)
    });
}

function formatNumber(num) {
    if (Number(num) > 1e8) return (num / 1e8).toFixed(2) + "亿";
    if (Number(num) > 1e4) return (num / 1e4).toFixed(2) + "万";
    return num + "";
}

async function detail(id) {
    let url = host + "/pgc/view/web/season?season_id=" + id;
    let resp = await req(url, { headers: headers });
    let jo = JSON.parse(resp.content).result;

    let stat = jo["stat"];
    let status = "弹幕: " + formatNumber(stat["danmakus"]) + "　点赞: " + formatNumber(stat["likes"]) + "　投币: " + formatNumber(stat["coins"]) + "　追番追剧: " + formatNumber(stat["favorites"]);
    let score = jo.hasOwnProperty("rating") ? "评分: " + jo["rating"]["score"] + "　" + jo["subtitle"] : "暂无评分　" + jo["subtitle"];

    let episodes = jo["episodes"] || [];
    let playurls1 = [];
    let playurls2 = [];
    episodes.forEach(ep => {
        let eid = ep["id"];
        let cid = ep["cid"];
        let link = ep["link"];
        let part = ep["title"].replace("#", "-") + " " + ep["long_title"];
        playurls1.push(part + "$" + eid + "_" + cid);
        playurls2.push(part + "$" + link);
    });

    return JSON.stringify({
        list: [{
            vod_id: id,
            vod_name: jo["title"],
            vod_pic: jo["cover"],
            type_name: jo["share_sub_title"],
            vod_year: (jo["publish"]["pub_time"] || "").substr(0, 4),
            vod_area: (jo["areas"] && jo["areas"][0]) ? jo["areas"][0]["name"] : "",
            vod_remarks: jo["new_ep"] ? jo["new_ep"]["desc"] : "",
            vod_actor: status,
            vod_director: score,
            vod_content: jo["evaluate"] || "",
            vod_play_from: "B站$$$bilibili",
            vod_play_url: playurls1.join("#") + "$$$" + playurls2.join("#")
        }]
    });
}

async function search(wd, quick, pg) {
    let p = pg || 1;
    let url1 = host + "/x/web-interface/search/type?keyword=" + encodeURIComponent(wd) + "&search_type=media_bangumi&page=" + p;
    let url2 = host + "/x/web-interface/search/type?keyword=" + encodeURIComponent(wd) + "&search_type=media_ft&page=" + p;

    let resp1 = await req(url1, { headers: headers });
    let jo1 = JSON.parse(resp1.content);
    if (jo1["message"] && jo1["message"] !== "0") {
        return JSON.stringify({ list: [] });
    }

    let resp2 = await req(url2, { headers: headers });
    let jo2 = JSON.parse(resp2.content);

    let vodList = [];
    if (jo1.data && jo1.data["numResults"] === 0) {
        vodList = (jo2.data && jo2.data.result) ? jo2.data.result : [];
    } else if (jo2.data && jo2.data["numResults"] === 0) {
        vodList = (jo1.data && jo1.data.result) ? jo1.data.result : [];
    } else {
        let l1 = (jo1.data && jo1.data.result) ? jo1.data.result : [];
        let l2 = (jo2.data && jo2.data.result) ? jo2.data.result : [];
        vodList = l1.concat(l2);
    }

    let videos = [];
    vodList.forEach(vod => {
        let aid = (vod["season_id"] + "").trim();
        let title = vod["title"].trim().replace(/<em class="keyword">/g, "").replace(/<\/em>/g, "");
        let img = vod["cover"].trim();
        let remark = vod["index_show"] || "";
        videos.push({
            vod_id: aid,
            vod_name: title,
            vod_pic: img,
            vod_remarks: remark
        });
    });

    return JSON.stringify({ list: videos });
}

async function play(flag, id, flags) {
    // id 格式: "eid_cid" 或 bilibili 链接
    if (/^http/.test(id)) {
        return JSON.stringify({
            parse: 1,
            url: id,
            header: { "User-Agent": "Mozilla/5.0" }
        });
    }

    let ids = id.split("_");
    let url = host + "/pgc/player/web/playurl?qn=80&ep_id=" + ids[0] + "&cid=" + ids[1];
    let resp = await req(url, { headers: headers });
    let jRoot = JSON.parse(resp.content);

    if (jRoot["message"] !== "success") {
        return JSON.stringify({ parse: 0, url: "" });
    }

    let ja = jRoot["result"]["durl"];
    let maxSize = -1;
    let position = 0;
    ja.forEach((tmpJo, i) => {
        if (maxSize < Number(tmpJo["size"])) {
            maxSize = Number(tmpJo["size"]);
            position = i;
        }
    });

    let playUrl = ja.length > 0 ? ja[position]["url"] : "";
    let dan = "https://api.bilibili.com/x/v1/dm/list.so?oid=" + ids[1];

    return JSON.stringify({
        parse: 0,
        url: playUrl,
        contentType: "video/x-flv",
        header: {
            "Referer": "https://www.bilibili.com",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"
        },
        danmaku: dan
    });
}

export default { init, home, homeVod, category, detail, search, play };
