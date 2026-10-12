# -*- coding: utf-8 -*-
# ============ 伊人网 244544.xyz 源 (成人站 · JSON API 签名站) ============
# 站型: Next.js App Router SPA + 自研 awesome-cms 前端安全层 (非 HTML 爬取, 全走 JSON 接口)
#   1) 会话:  GET /api/front/client-session → {sessionId, secret, serverEpochMillis, expiresAt}
#   2) 签名:  请求带 HMAC-SHA256 签名
#        canonical = METHOD \n PATH?QUERY \n TS(秒) \n NONCE
#        NONCE     = b64url(HMAC-SHA256(sessionId\nTS\nnowMs\ncounter\nrandom, secret))[:24]
#        SIGNATURE = b64url(HMAC-SHA256(canonical, secret))
#        头: X-Front-Session / X-Front-Ts / X-Front-Nonce / X-Front-Signature / X-Front-Encrypt=cbc-hmac-v1
#   3) 响应:  data 为加密信封 {mac, iv, payload, alg=AES-CBC-HMAC-SHA256, __encrypted:true}
#        encKey = SHA256("awesome-front-response-encryption-v1\n" + secret)   # 32B → AES-256-CBC/PKCS7
#        macKey = SHA256("awesome-front-response-authentication-v1\n" + secret)
#        mac    = b64url(HMAC-SHA256("AES-CBC-HMAC-SHA256\n"+iv+"\n"+payload, macKey))
#   4) 接口:  分类 /api/front/categories?contentType=video
#             列表 /api/front/contents?contentType=video&categoryId=&page=&pageSize=&sort=latest|hot
#             详情 /api/front/contents/{id}?includeChapterContent=false
#             搜索 /api/front/search?keyword=&contentType=video&page=&pageSize=
#             取流 POST /api/front/videos/{id}/play-url  (免签名) → data.playUrl (m3u8)
#   5) m3u8: 相对 URI(根相对 key + 裸分片) → 走 localProxy 绝对化重写后回吐
# 契约: 独立 class Spider(不继承 base.spider); header 为 dict; 会话三别名; 三级网络降级;
#       方法签名带默认值; 无 print / 无 __main__
# 更新: 2026-10-11 首版 (签名/加密逆向 → 全链路验证)
#       v1.1 修复「不能播放/加载视频失败」: 播放线路默认改**直连**(远程原始 m3u8),
#            与已验证可用的 ririri/1024吃瓜 同策略(壳会按标准 HLS 解析「根相对分片」);
#            另给第二条「代理」线路(proxy://do=m3u8 → localProxy 绝对化重写)作兜底。

import re, json, base64, time, hmac, hashlib, random, calendar
from urllib.parse import urljoin, quote, urlencode

try:
    import requests as _requests
except Exception:
    _requests = None


# ==================== 纯 Python AES-256-CBC 解密 (壳无 pycryptodome 时兜底) ====================
_AES_SBOX = (
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
)


def _aes_build_inv():
    inv = [0] * 256
    for i, v in enumerate(_AES_SBOX):
        inv[v] = i
    return inv


_AES_INV_SBOX = _aes_build_inv()
_AES_RCON = (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36)


def _gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p & 0xFF


def _aes_expand(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_AES_SBOX[b] for b in t]
            t[0] ^= _AES_RCON[i // nk]
        elif nk > 6 and i % nk == 4:
            t = [_AES_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(nr + 1)], nr


def _aes_decrypt_block(blk, rk, nr):
    # 解密轮密钥必须逆序: 先 rk[nr] → … → rk[0](原实现误用了加密顺序)
    s = [blk[i] ^ rk[nr][i] for i in range(16)]
    for rnd in range(nr - 1, 0, -1):
        t = list(s)
        for r in range(1, 4):
            for c in range(4):
                s[4 * c + r] = t[4 * ((c - r) % 4) + r]
        s = [_AES_INV_SBOX[b] for b in s]
        s = [s[i] ^ rk[rnd][i] for i in range(16)]
        t = list(s)
        for c in range(4):
            a0, a1, a2, a3 = t[4 * c], t[4 * c + 1], t[4 * c + 2], t[4 * c + 3]
            s[4 * c] = _gmul(a0, 14) ^ _gmul(a1, 11) ^ _gmul(a2, 13) ^ _gmul(a3, 9)
            s[4 * c + 1] = _gmul(a0, 9) ^ _gmul(a1, 14) ^ _gmul(a2, 11) ^ _gmul(a3, 13)
            s[4 * c + 2] = _gmul(a0, 13) ^ _gmul(a1, 9) ^ _gmul(a2, 14) ^ _gmul(a3, 11)
            s[4 * c + 3] = _gmul(a0, 11) ^ _gmul(a1, 13) ^ _gmul(a2, 9) ^ _gmul(a3, 14)
    t = list(s)
    for r in range(1, 4):
        for c in range(4):
            s[4 * c + r] = t[4 * ((c - r) % 4) + r]
    s = [_AES_INV_SBOX[b] for b in s]
    s = [s[i] ^ rk[0][i] for i in range(16)]
    return bytes(s)


def _aes_cbc_decrypt(key, iv, data):
    """AES-CBC 解密: pycryptodome 快路径 → 纯 Python 兜底"""
    try:
        from Crypto.Cipher import AES
        return AES.new(key, AES.MODE_CBC, iv).decrypt(data)
    except Exception:
        pass
    try:
        from Cryptodome.Cipher import AES
        return AES.new(key, AES.MODE_CBC, iv).decrypt(data)
    except Exception:
        pass
    rk, nr = _aes_expand(key)
    out = bytearray()
    prev = iv
    n = len(data) - (len(data) % 16)
    for i in range(0, n, 16):
        blk = data[i:i + 16]
        dec = _aes_decrypt_block(blk, rk, nr)
        out += bytes(a ^ b for a, b in zip(dec, prev))
        prev = blk
    return bytes(out)


def _b64url(b):
    return base64.b64encode(b).decode("utf-8").replace("+", "-").replace("/", "_").rstrip("=")


def _iso_ms(s):
    return calendar.timegm(time.strptime(str(s).replace("Z", "").strip()[:19], "%Y-%m-%dT%H:%M:%S")) * 1000


def _fmt_dur(sec):
    try:
        sec = int(sec)
    except Exception:
        return ""
    if sec <= 0:
        return ""
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return ("%d:%02d:%02d" % (h, m, s)) if h else ("%02d:%02d" % (m, s))


class Spider:
    SITE = "https://www.244544.xyz"
    NAME = "伊人网"
    # 站点实际视频分类兜底(id 1/2/3/4/9; 站点日后调整会自动以接口为准)
    FALLBACK_CATS = (("1", "中文字幕"), ("2", "自拍"), ("3", "动漫"), ("4", "亚洲无码"), ("9", "国产AV"))

    def __init__(self):
        self.site = self.SITE
        self.name = self.NAME
        self.header = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": self.site + "/",
            "Origin": self.site,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "application/json, text/plain, */*",
        }
        self.s = self.session = self.sess = _requests.Session() if _requests else None
        self._extend = {}
        self._sess = None            # {id, secret, exp_local_ms, offset}
        self._cnt = 0
        self._cats_cache = None
        self._home_cache = None

    # ---------------- 生命周期 ----------------
    def init(self, extend=""):
        self._extend = {}
        if isinstance(extend, dict):
            self._extend = extend
        elif isinstance(extend, str) and extend.strip():
            try:
                e = json.loads(extend)
                if isinstance(e, dict):
                    self._extend = e
            except Exception:
                pass
        self._sess = None
        self._cnt = 0
        self._cats_cache = None
        self._home_cache = None

    def destroy(self):
        self._sess = None
        self._cats_cache = None
        self._home_cache = None

    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    def action(self, action):
        return {}

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower()
        return u.endswith((".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".avi")) or "m3u8" in u

    # ---------------- 网络 (壳 → requests → urllib 三级) ----------------
    def _http(self, url, method="GET", data=None, headers=None, timeout=12):
        """返回 (status, text)；全失败 (0, "")"""
        h = dict(self.header)
        if headers:
            h.update(headers)
        if self.s is not None:
            try:
                r = self.s.request(method, url, headers=h, data=data, timeout=timeout, allow_redirects=True)
                return r.status_code, (r.text or "")
            except Exception:
                pass
        try:
            import urllib.request
            body = data.encode("utf-8") if isinstance(data, str) else data
            req = urllib.request.Request(url, data=body, headers=h, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.getcode(), resp.read().decode("utf-8", "ignore")
        except Exception:
            return 0, ""

    # ---------------- 会话 ----------------
    def _ensure_session(self, force=False):
        s = self._sess
        now = int(time.time() * 1000)
        if s and not force and s.get("exp_local_ms", 0) - now > 60000:
            return s
        t1 = time.time() * 1000
        st, txt = self._http(self.site + "/api/front/client-session")
        t2 = time.time() * 1000
        if not txt:
            return s
        try:
            d = json.loads(txt).get("data") or {}
        except Exception:
            return s
        if not d.get("sessionId") or not d.get("secret"):
            return s
        offset = 0.0
        try:
            mid = t1 + max(0.0, t2 - t1) / 2.0
            offset = float(d.get("serverEpochMillis")) - mid
        except Exception:
            offset = 0.0
        try:
            ttl = _iso_ms(d.get("expiresAt")) - float(d.get("serverEpochMillis"))
            exp_local = now + max(60000, ttl)
        except Exception:
            exp_local = now + 600000
        self._sess = {"id": d["sessionId"], "secret": d["secret"], "exp_local_ms": exp_local, "offset": offset}
        return self._sess

    def _sign_headers(self, sess, method, full):
        secret = sess["secret"].encode("utf-8")
        ts = str(int((time.time() * 1000 + sess["offset"]) // 1000))
        self._cnt = (self._cnt + 1) % 0x7FFFFFFF
        a = "%s\n%s\n%d\n%d\n%s" % (sess["id"], ts, int(time.time() * 1000 + sess["offset"]),
                                    self._cnt, repr(random.random()))
        nonce = _b64url(hmac.new(secret, a.encode("utf-8"), hashlib.sha256).digest())[:24]
        canon = "%s\n%s\n%s\n%s" % (method.upper(), full, ts, nonce)
        sig = _b64url(hmac.new(secret, canon.encode("utf-8"), hashlib.sha256).digest())
        return {
            "X-Front-Session": sess["id"],
            "X-Front-Ts": ts,
            "X-Front-Nonce": nonce,
            "X-Front-Signature": sig,
            "X-Front-Encrypt": "cbc-hmac-v1",
        }

    # ---------------- 响应解密 ----------------
    def _dec(self, d):
        sess = self._sess
        if not sess:
            return None
        try:
            iv_b64 = str(d.get("iv", ""))
            pl_b64 = str(d.get("payload", ""))
            mac = str(d.get("mac", ""))
            if not iv_b64 or not pl_b64:
                return None
            iv = base64.b64decode(iv_b64)
            ct = base64.b64decode(pl_b64)
            mac_key = hashlib.sha256(("awesome-front-response-authentication-v1\n" + sess["secret"]).encode("utf-8")).digest()
            exp = _b64url(hmac.new(mac_key, ("AES-CBC-HMAC-SHA256\n" + iv_b64 + "\n" + pl_b64).encode("utf-8"), hashlib.sha256).digest())
            if exp != mac:
                return None
            enc_key = hashlib.sha256(("awesome-front-response-encryption-v1\n" + sess["secret"]).encode("utf-8")).digest()
            pt = _aes_cbc_decrypt(enc_key, iv, ct)
            if not pt:
                return None
            pad = pt[-1]
            if 1 <= pad <= 16:
                pt = pt[:-pad]
            return json.loads(pt.decode("utf-8", "ignore"))
        except Exception:
            return None

    # ---------------- 签名 API ----------------
    def _api(self, path, params=None):
        """签名 GET + 自动解密；返回 data(dict/list) 或 None"""
        full = path + (("?" + urlencode(params)) if params else "")
        for attempt in (0, 1):
            sess = self._ensure_session(force=(attempt == 1))
            if not sess:
                return None
            h = self._sign_headers(sess, "GET", full)
            st, txt = self._http(self.site + full, headers=h)
            if not txt:
                continue
            try:
                j = json.loads(txt)
            except Exception:
                continue
            if j.get("code") in (401, 403, 419) and attempt == 0:
                continue  # 会话失效 → 强刷重试一次
            d = j.get("data")
            if isinstance(d, dict) and "payload" in d and "iv" in d:
                return self._dec(d)
            return d
        return None

    def _play_url(self, cid):
        """POST /api/front/videos/{id}/play-url (免签名) → m3u8"""
        path = "/api/front/videos/%s/play-url" % cid
        st, txt = self._http(self.site + path, method="POST", data="{}",
                             headers={"Content-Type": "application/json", "Accept": "application/json"})
        if not txt:
            return ""
        try:
            d = json.loads(txt).get("data") or {}
        except Exception:
            return ""
        for k in ("playUrl", "directUrl", "proxyUrl", "url"):
            v = d.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
        return ""

    # ---------------- m3u8 绝对化重写 (供「代理」线路的 localProxy 使用) ----------------
    def _get_text(self, url):
        st, txt = self._http(url)
        return txt or ""

    def _rewrite_m3u8(self, url):
        txt = self._get_text(url)
        if not txt or "#EXTM3U" not in txt:
            return ""
        out = []
        for ln in txt.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("#"):
                m = re.search(r'URI="([^"]+)"', s)
                if m and not m.group(1).startswith(("http://", "https://", "data:")):
                    s = s.replace('URI="%s"' % m.group(1), 'URI="%s"' % urljoin(url, m.group(1)))
                out.append(s)
            elif s.startswith(("http://", "https://")):
                out.append(s)
            else:
                out.append(urljoin(url, s))
        return "\n".join(out)

    def _wrap_play(self, m3u, mode="direct"):
        """mode: 'direct'=直返远程 m3u8(壳按标准 HLS 解析相对分片, 与已验证可用的 ririri/1024吃瓜 同策略)
                 'proxy' =proxy://do=m3u8 交 localProxy 绝对化重写(壳不认远程相对流时的兜底)"""
        if not m3u:
            return {"parse": 0, "url": "", "header": dict(self.header)}
        # extend 覆盖: init({"m3u8":"direct"|"proxy"})
        ext = str(self._extend.get("m3u8", "")).lower()
        if ext in ("direct", "raw", "off"):
            mode = "direct"
        elif ext in ("proxy", "local", "on"):
            mode = "proxy"
        if mode == "proxy":
            return {"parse": 0, "url": "proxy://do=m3u8&url=" + quote(m3u, safe=""),
                    "format": "application/vnd.apple.mpegurl", "header": dict(self.header)}
        return {"parse": 0, "url": m3u, "header": dict(self.header)}

    # ---------------- 数据映射 ----------------
    def _mk(self, it):
        if not isinstance(it, dict):
            return None
        return {
            "vod_id": str(it.get("id", "")),
            "vod_name": it.get("title") or "",
            "vod_pic": it.get("coverUrl") or "",
            "vod_remarks": _fmt_dur(it.get("duration")),
        }

    def _list(self, d):
        items = (d or {}).get("items") if isinstance(d, dict) else None
        out = []
        for it in (items or []):
            v = self._mk(it)
            if v and v["vod_id"]:
                out.append(v)
        return out

    # ---------------- 分类 ----------------
    def _cats(self):
        if self._cats_cache is not None:
            return self._cats_cache
        out = []
        d = self._api("/api/front/categories", {"contentType": "video"})
        if isinstance(d, list):
            rows = [c for c in d if isinstance(c, dict) and c.get("contentType") == "video"]
            rows.sort(key=lambda c: (c.get("sortOrder") or 0, c.get("id") or 0))
            for c in rows:
                nm = c.get("name") or ""
                if nm:
                    out.append({"type_id": str(c.get("id")), "type_name": nm})
        if not out:
            out = [{"type_id": k, "type_name": v} for k, v in self.FALLBACK_CATS]
        self._cats_cache = out
        return out

    def _filters(self, cats):
        f = {}
        for c in cats:
            f[c["type_id"]] = [{
                "key": "sort", "name": "排序",
                "value": [{"n": "最新", "v": "latest"}, {"n": "最热", "v": "hot"}],
            }]
        return f

    # ---------------- 首页 ----------------
    def homeContent(self, filter=False):
        cats = self._cats()
        d = self._api("/api/front/contents", {"contentType": "video", "page": "1",
                                              "pageSize": "20", "sort": "latest", "coverCdnVersion": "3"})
        r = {"class": cats, "list": self._list(d)}
        if filter:
            r["filters"] = self._filters(cats)
        return r

    def homeVideoContent(self):
        d = self._api("/api/front/contents", {"contentType": "video", "page": "1",
                                              "pageSize": "20", "sort": "latest", "coverCdnVersion": "3"})
        return {"list": self._list(d)}

    # ---------------- 分类列表 ----------------
    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        sort = "latest"
        for src in (filter, extend):
            if isinstance(src, dict) and src.get("sort"):
                sort = src.get("sort")
                break
        d = self._api("/api/front/contents", {"contentType": "video", "categoryId": str(tid),
                                              "page": str(pg), "pageSize": "20",
                                              "sort": sort, "coverCdnVersion": "3"})
        lst = self._list(d)
        total = (d or {}).get("total") or 0
        ps = (d or {}).get("pageSize") or 20
        try:
            pagecount = max(1, (int(total) + int(ps) - 1) // int(ps)) if total else 1
        except Exception:
            pagecount = 1
        return {"list": lst, "page": pg, "pagecount": pagecount, "limit": ps, "total": total}

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        vid = ids
        if isinstance(ids, (list, tuple)):
            vid = ids[0] if ids else ""
        vid = str(vid or "").strip()
        m = re.search(r"(\d+)", vid)
        if not m:
            return {"list": []}
        cid = m.group(1)
        d = self._api("/api/front/contents/%s" % cid, {"includeChapterContent": "false", "coverCdnVersion": "3"})
        if not isinstance(d, dict):
            return {"list": []}
        movie = d.get("movie") if isinstance(d.get("movie"), dict) else {}
        tags = d.get("tags") if isinstance(d.get("tags"), list) else []
        vod = {
            "vod_id": cid,
            "vod_name": d.get("title") or "",
            "vod_pic": d.get("coverUrl") or "",
            "vod_content": d.get("summary") or "",
            "vod_year": (str(movie.get("releaseDate") or "")[:4] or ""),
            "vod_area": d.get("categoryName") or "",
            "vod_actor": movie.get("actorsText") or "",
            "vod_remarks": _fmt_dur(d.get("duration")),
            # 双线路: 直连(默认, 壳自解析相对分片) + 代理(壳不认远程相对流时用)
            "vod_play_from": "%s·直连$$$%s·代理" % (self.name, self.name),
            "vod_play_url": "正片$%s$$$正片$%s" % (cid, cid),
        }
        if tags:
            vod["vod_tag"] = ",".join([str(t) for t in tags])
        if movie.get("seriesName"):
            vod["vod_series"] = movie.get("seriesName")
        return {"list": [vod]}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick=False, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        d = self._api("/api/front/search", {"keyword": str(key), "contentType": "video",
                                            "page": str(pg), "pageSize": "20"})
        return {"list": self._list(d)}

    # ---------------- 播放 ----------------
    def playerContent(self, flag, ids, vipFlags=None):
        # 线路选择: 源名含「代理」→ 走 proxy://do=m3u8; 否则直连
        mode = "proxy" if (flag and "代理" in str(flag)) else "direct"
        url = ids
        if isinstance(ids, (list, tuple)):
            url = ids[0] if ids else ""
        url = str(url or "").strip()
        if "$$$" in url:
            url = url.split("$$$")[-1]
        if "$" in url:
            url = url.split("$")[-1].strip()
        if not url:
            return {"parse": 0, "url": "", "header": dict(self.header)}
        # 已是直链
        if url.startswith("http") and ("m3u8" in url.lower() or self.isVideoFormat(url)):
            return self._wrap_play(url, mode)
        # 纯 id(或 正片$id 剥离后) → 取流
        m = re.search(r"(\d+)", url)
        if m:
            m3u = self._play_url(m.group(1))
            if m3u:
                return self._wrap_play(m3u, mode)
        # 兜底: 当普通 URL 处理
        if url.startswith("http"):
            return self._wrap_play(url, mode)
        return {"parse": 0, "url": "", "header": dict(self.header)}

    # ---------------- 本地代理 (m3u8 绝对化) ----------------
    def localProxy(self, param):
        u = ""
        if isinstance(param, dict):
            u = param.get("url") or param.get("res") or param.get("u") or ""
        elif isinstance(param, str):
            m = re.search(r"(?:url|res)=([^&]+)", param)
            if m:
                u = m.group(1)
        if not u:
            return [403, "text/plain", b"", None]
        try:
            from urllib.parse import unquote
            u = unquote(u)
        except Exception:
            pass
        txt = self._rewrite_m3u8(u)
        if txt:
            return [200, "application/vnd.apple.mpegurl", txt.encode("utf-8"), None]
        return [403, "text/plain", b"", None]
