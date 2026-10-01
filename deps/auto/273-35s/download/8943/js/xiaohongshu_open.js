import { Crypto, load, _ } from 'assets://js/lib/cat.js';

let siteKey = '';
let siteType = 0;
let host = 'https://jhfkdnov21vfd.fhoumpjjih.work';
let token = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI1OTE0MTQ1IiwiaXNzIjoiIiwiaWF0IjoxNzM5MzYxMDU5LCJuYmYiOjE3MzkzNjEwNTksImV4cCI6MTg5NzA0MTA1OX0.Hq3ChO-V_VIs9MDsJPVmTAq92bGOv4cW4ffpzeSLLio';
let imgDomain = 'https://ssim2.gbrgz.com/';

async function request(reqUrl, data, header, method) {
    let res = await req(reqUrl, {
        method: method || 'get',
        data: data || '',
        headers: header || getHeaders(),
        postType: method === 'post' ? 'form-data' : ''
    });
    return res.content;
}

async function init(cfg) {
    siteKey = cfg.skey;
    siteType = cfg.stype;
    await getToken();
}

async function home(filter) {
    let res = JSON.parse(await request(host + '/api/video/queryClassifyList?mark=4', '', getHeaders())).encData;
    let data = JSON.parse(aesDecode(res, 'JhbGciOiJIUzI1Ni', 'JhbGciOiJIUzI1Ni')).data;
    let list = [];
    _.forEach(data, (item) => {
        list.push({
            type_id: item.classifyId,
            type_name: item.classifyTitle
        })
    })
    return JSON.stringify({
        'class': list,
    });
}

async function category(tid, pg, filter, extend) {
    let url = host + `/api/short/video/getShortVideos?classifyId=${tid}&videoMark=4&page=${pg}&pageSize=20`;
    let res = JSON.parse(await request(url, '', getHeaders())).encData;
    let data = JSON.parse(aesDecode(res, 'JhbGciOiJIUzI1Ni', 'JhbGciOiJIUzI1Ni')).data;
    let list = [];
    _.forEach(data, (item) => {
        list.push({
            vod_id: item.videoId,
            vod_name: item.title,
            vod_pic: imgDomain + item.coverImg,
            vod_remarks: item.playTime,
        })
    })
    return JSON.stringify({
        page: parseInt(pg),
        list: list,
    });
}

async function detail(id) {
    let url = host + `/api/video/getVideoById?videoId=${id}`;
    let res = JSON.parse(await request(url, '', getHeaders())).encData;
    let data = JSON.parse(aesDecode(res, 'JhbGciOiJIUzI1Ni', 'JhbGciOiJIUzI1Ni'));

    let vod = {
        vod_id: id,
        vod_name: data.title,
        type_name: data.tagTitles.join(','),
        vod_play_from: data.nickName || 'Leospring',
        vod_play_url: `${data.title}$auth_key=${data.authKey}&path=${data.videoUrl}`

    }
    return JSON.stringify({
        list: [vod],
    });
}

async function play(flag, id, flags) {
    let header = getHeaders()
    header['Authorization'] = header['aut']
    delete header.deviceid
    delete header.aut

    return JSON.stringify({
        parse: 0,
        url: `${host}/api/m3u8/decode/authPath?${id}`,
        header: header
    });
}

function getSign() {
   return md5(new Date().getTime().toString().substring(3,8));
}

function getHeaders() {
    return {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 11; M2012K10C Build/RP1A.200720.011; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/87.0.4280.141 Mobile Safari/537.36;SuiRui/xhs/ver=1.2.6',
        'deviceid': '730423d47474d129e9ac6a76b169d1bf',
        't': new Date().getTime().toString(),
        's': getSign(),
        'aut': token,
    }
}

function md5(text) {
    return Crypto.MD5(text).toString();
}

async function getToken() {
    let res = JSON.parse(await request(host +'/api/user/traveler', {'deviceId': '730423d47474d129e9ac6a76b169d1bf', 'tt': 'U', 'code': '', 'chCode': 'dafe13'},{
        'User-Agent': 'Mozilla/5.0 (Linux; Android 11; M2012K10C Build/RP1A.200720.011; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/87.0.4280.141 Mobile Safari/537.36;SuiRui/xhs/ver=1.2.6',
        'deviceid': '730423d47474d129e9ac6a76b169d1bf',
        't': new Date().getTime().toString(),
        's': getSign(),
    },'POST'));
    token = res.data.token;
    imgDomain = res.data.imgDomain;
}

function aesDecode(str, keyStr, ivStr, type) {
    const key = Crypto.enc.Utf8.parse(keyStr);
    if (type === 'hex') {
        str = Crypto.enc.Hex.parse(str);
        return Crypto.AES.decrypt({
            ciphertext: str
        }, key, {
            iv: Crypto.enc.Utf8.parse(ivStr),
            mode: Crypto.mode.CBC,
            padding: Crypto.pad.Pkcs7
        }).toString(Crypto.enc.Utf8);
    } else {
        return Crypto.AES.decrypt(str, key, {
            iv: Crypto.enc.Utf8.parse(ivStr),
            mode: Crypto.mode.CBC,
            padding: Crypto.pad.Pkcs7
        }).toString(Crypto.enc.Utf8);
    }
 }
 
 export function __jsEvalReturn() {
     return {
         init: init,
         home: home,
         category: category,
         detail: detail,
         play: play,
     };
 }