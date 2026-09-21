# -*- coding: utf-8 -*-
"""config_decode.py — 混淆/加密 TVBox 配置解码层（stdlib only，独立实现）。

背景（2026-09-22 tvbox-api-backup 吸收评估，P1-1）：饭太硬/嗷呜/潇洒等活跃
上游以混淆壳分发配置，fetch_merge 原来只能靠二手明文镜像绕行。本模块在
「拉取」与「质量门槛」之间补一层解码，仅当内容呈现密文特征时介入，明文
上游零开销。

支持的分发形态（均为社区公开的通用传输格式，此处为独立重写实现，未复制
任何 GPL 仓库代码；AES-128 的 S-box 等表由 GF(2^8) 数学程序化生成）：
  1. ``**`` 壳   —— 前 ≥8 字节任意前缀 + ``**`` 分隔，其后为 base64（可夹杂
     空白字节），解码后可能仍是另一层壳/密文，递归下钻；
  2. 2423 AES-128-CBC —— 文本以 ``2423`` 开头、内含 ``2324`` 分隔与 key/iv
     段，分 hex 布局与 plain 布局两种，各试一次；
  3. gzip      —— 字节流以 1f 8b 开头（部分服务器对无压缩能力的客户端也
     回 gzip 体，如 zhi35 实测）；
  4. 裸 base64 —— 除去空白后仅 base64 字符且足够长。

防御（评估报告明确要求的红线）：
  - 输入/输出字节上限（DECODE_MAX_BYTES，默认 8MB），防解压炸弹；
  - 递归深度上限（DECODE_MAX_DEPTH，默认 5）；
  - 解码失败一律返回 (None, 原因)，由调用方按候选失败计，不落盘；
  - 解码产物仍需过 fetch_merge 既有的最小字节/行数/sha256 门槛，本模块
    不替代治理层。
"""
import base64
import binascii
import os
import re
import zlib

MAX_INPUT_BYTES = int(os.environ.get("DECODE_MAX_BYTES", str(8 << 20)))
MAX_DEPTH = int(os.environ.get("DECODE_MAX_DEPTH", "5"))
MAX_OUTPUT_BYTES = MAX_INPUT_BYTES  # 解压/解码产物同上限，防炸弹


# ---------------------------------------------------------------------------
# AES-128（纯标准库独立实现；表由 GF(2^8) 生成，含 ECB 加解与 CBC 加解）
# ---------------------------------------------------------------------------

def _build_sbox():
    """生成 AES S-box：GF(2^8) 乘法逆元 + 仿射变换；逆表直接反转。"""
    def gf_mul(a, b):
        p = 0
        for _ in range(8):
            if b & 1:
                p ^= a
            hi = a & 0x80
            a = (a << 1) & 0xFF
            if hi:
                a ^= 0x1B
            b >>= 1
        return p

    def gf_inv(a):
        if a == 0:
            return 0
        for x in range(1, 256):
            if gf_mul(a, x) == 1:
                return x
        return 0

    sbox = [0] * 256
    for i in range(256):
        b = gf_inv(i)
        s = b
        for _ in range(4):          # s ^= rotl(b,1..4)
            b = ((b << 1) | (b >> 7)) & 0xFF
            s ^= b
        sbox[i] = s ^ 0x63
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    return sbox, inv


_SBOX, _INV_SBOX = _build_sbox()
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1B) & 0xFF
    return a


def _mul(a, b):
    """GF(2^8) 乘法（用于列混淆）。"""
    p = 0
    for _ in range(4):
        if b & 1:
            p ^= a
        a = _xtime(a)
        b >>= 1
    return p


def _expand_key(key: bytes):
    """AES-128 密钥扩展（Nk=4, Nr=10），返回 44 个 32-bit 字。"""
    if len(key) != 16:
        raise ValueError("AES-128 key must be 16 bytes")
    w = [int.from_bytes(key[i * 4:i * 4 + 4], "big") for i in range(4)]
    for i in range(4, 44):
        t = w[i - 1]
        if i % 4 == 0:
            t = ((t << 8) & 0xFFFFFFFF) | (t >> 24)              # RotWord
            t = (_SBOX[(t >> 24) & 0xFF] << 24 | _SBOX[(t >> 16) & 0xFF] << 16 |
                 _SBOX[(t >> 8) & 0xFF] << 8 | _SBOX[t & 0xFF])  # SubWord
            t ^= _RCON[i // 4 - 1] << 24
        w.append(w[i - 4] ^ t)
    return w


def _encrypt_block(block: bytes, w) -> bytes:
    s = [list(block[i::4]) for i in range(4)]   # state[r][c] = block[4c+r]
    _add_round_key(s, w, 0)
    for rnd in range(1, 10):
        s = [[_SBOX[b] for b in row] for row in s]
        _shift_rows(s)
        _mix_columns(s)
        _add_round_key(s, w, rnd)
    s = [[_SBOX[b] for b in row] for row in s]
    _shift_rows(s)
    _add_round_key(s, w, 10)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _decrypt_block(block: bytes, w) -> bytes:
    s = [list(block[i::4]) for i in range(4)]
    _add_round_key(s, w, 10)
    for rnd in range(9, 0, -1):
        _inv_shift_rows(s)
        s = [[_INV_SBOX[b] for b in row] for row in s]
        _add_round_key(s, w, rnd)
        _inv_mix_columns(s)
    _inv_shift_rows(s)
    s = [[_INV_SBOX[b] for b in row] for row in s]
    _add_round_key(s, w, 0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _add_round_key(s, w, rnd):
    for c in range(4):
        k = w[rnd * 4 + c]
        s[0][c] ^= (k >> 24) & 0xFF
        s[1][c] ^= (k >> 16) & 0xFF
        s[2][c] ^= (k >> 8) & 0xFF
        s[3][c] ^= k & 0xFF


def _shift_rows(s):
    s[1] = s[1][1:] + s[1][:1]
    s[2] = s[2][2:] + s[2][:2]
    s[3] = s[3][3:] + s[3][:3]


def _inv_shift_rows(s):
    s[1] = s[1][-1:] + s[1][:-1]
    s[2] = s[2][-2:] + s[2][:-2]
    s[3] = s[3][-3:] + s[3][:-3]


def _mix_columns(s):
    for c in range(4):
        a0, a1, a2, a3 = s[0][c], s[1][c], s[2][c], s[3][c]
        s[0][c] = _mul(a0, 2) ^ _mul(a1, 3) ^ a2 ^ a3
        s[1][c] = a0 ^ _mul(a1, 2) ^ _mul(a2, 3) ^ a3
        s[2][c] = a0 ^ a1 ^ _mul(a2, 2) ^ _mul(a3, 3)
        s[3][c] = _mul(a0, 3) ^ a1 ^ a2 ^ _mul(a3, 2)


def _inv_mix_columns(s):
    for c in range(4):
        a0, a1, a2, a3 = s[0][c], s[1][c], s[2][c], s[3][c]
        s[0][c] = _mul(a0, 14) ^ _mul(a1, 11) ^ _mul(a2, 13) ^ _mul(a3, 9)
        s[1][c] = _mul(a0, 9) ^ _mul(a1, 14) ^ _mul(a2, 11) ^ _mul(a3, 13)
        s[2][c] = _mul(a0, 13) ^ _mul(a1, 9) ^ _mul(a2, 14) ^ _mul(a3, 11)
        s[3][c] = _mul(a0, 11) ^ _mul(a1, 13) ^ _mul(a2, 9) ^ _mul(a3, 14)


def aes128_cbc_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-128-CBC 解密。data 长度须为 16 的倍数。不做去填充（由调用方裁剪）。"""
    if len(key) != 16 or len(iv) != 16:
        raise ValueError("key/iv must be 16 bytes")
    if len(data) == 0 or len(data) % 16:
        raise ValueError("ciphertext length must be positive multiple of 16")
    w = _expand_key(key)
    out = []
    prev = iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        out.append(bytes(a ^ b for a, b in zip(_decrypt_block(blk, w), prev)))
        prev = blk
    return b"".join(out)


def aes128_cbc_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-128-CBC 加密（供自测回路；长度须为 16 的倍数）。"""
    if len(key) != 16 or len(iv) != 16:
        raise ValueError("key/iv must be 16 bytes")
    if len(data) == 0 or len(data) % 16:
        raise ValueError("plaintext length must be positive multiple of 16")
    w = _expand_key(key)
    out = []
    prev = iv
    for i in range(0, len(data), 16):
        blk = _encrypt_block(bytes(a ^ b for a, b in zip(data[i:i + 16], prev)), w)
        out.append(blk)
        prev = blk
    return b"".join(out)


# ---------------------------------------------------------------------------
# 分发形态解码
# ---------------------------------------------------------------------------

def _pad16(s: str) -> bytes:
    """右补 '0' 到 16 字节（超出截断）——2423 布局里 key/iv 都是变长字段。"""
    return (s + "0" * 16)[:16].encode("utf-8", "replace")[:16]


def _try_2423_hex(text: str) -> bytes:
    """hex 布局：2423 + <key_hex> + 2324 + <data_hex> + <iv_hex(26 字符)>。"""
    if not text.startswith("2423") or "2324" not in text:
        raise ValueError("no 2423 hex layout")
    i2324 = text.index("2324")
    if i2324 <= 4:
        raise ValueError("empty key field")
    key_field = text[4:i2324]
    try:
        key_str = bytes.fromhex(key_field).decode("latin-1")
    except ValueError:
        key_str = key_field
    key = _pad16(key_str)
    tail = text[-26:]
    try:
        iv_raw = bytes.fromhex(tail).decode("latin-1")
    except ValueError:
        raise ValueError("tail is not hex iv")  # hex 布局 iv 尾必须为 hex，否则是其它布局
    iv = _pad16(iv_raw)
    data_hex = re.sub(r"\s", "", text[i2324 + 4:-26])
    if len(data_hex) < 32 or len(data_hex) % 2:
        raise ValueError("bad data length")
    return aes128_cbc_decrypt(binascii.unhexlify(data_hex), key, iv)


def _try_2423_plain(text: str) -> bytes:
    """plain 布局：2423 … 2324 + <data_hex> + $# + <key> + #$ + <iv(13 字符)>。"""
    if not text.startswith("2423") or "2324" not in text:
        raise ValueError("no 2423 plain layout")
    if "$#" not in text or "#$" not in text:
        raise ValueError("no plain markers")
    i2324 = text.index("2324")
    p_doll, p_sharp = text.index("$#"), text.index("#$")
    if not (i2324 + 4 <= p_doll < p_sharp):
        raise ValueError("bad marker order")
    data_hex = re.sub(r"[^0-9a-fA-F]", "", text[i2324 + 4:p_doll])
    if len(data_hex) < 32 or len(data_hex) % 2:
        raise ValueError("bad data length")
    key = _pad16(text[p_doll + 2:p_sharp])
    iv = _pad16(text[-13:])
    return aes128_cbc_decrypt(binascii.unhexlify(data_hex), key, iv)


def _gunzip_capped(raw: bytes) -> bytes:
    """带上限的 gzip 解压（防解压炸弹）。超限抛 ValueError。"""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(raw, MAX_OUTPUT_BYTES + 1)
    if d.unconsumed_tail or len(out) > MAX_OUTPUT_BYTES:
        raise ValueError("decompressed exceeds cap")
    out += d.flush()
    if len(out) > MAX_OUTPUT_BYTES:
        raise ValueError("decompressed exceeds cap")
    return out


_B64_CLEAN_RE = re.compile(rb"[^A-Za-z0-9+/=]")


def _try_b64(raw: bytes) -> bytes:
    """空白字节剔除后 base64 解码；失败抛异常。"""
    b64 = bytes(b for b in raw if b not in (0x09, 0x0A, 0x0D, 0x20))
    if not b64:
        raise ValueError("empty")
    return base64.b64decode(b64, validate=False)


def _as_json_bytes(b: bytes):
    """若字节流（去 BOM/空白后）像 JSON，返回裁掉尾部填充后的字节；否则 None。
    尾部裁剪：密文分组填充（PKCS7 或 \\x00）会在 JSON 结束符后残留，json.loads
    不容忍尾垃圾，故统一裁到最后一个 } 或 ]。"""
    t = b.lstrip(b"\xef\xbb\xbf\r\n\t ")
    if not t or t[0:1] not in (b"{", b"["):
        return None
    end = max(t.rfind(b"}"), t.rfind(b"]"))
    if end < 0:
        return None
    return t[:end + 1]


def is_obscured(raw: bytes) -> bool:
    """廉价特征判定：gzip 魔数 / 2423 前缀 / ``**`` 壳标记（位置 ≥8）。"""
    if not raw or len(raw) > MAX_INPUT_BYTES:
        return False
    if raw[:2] == b"\x1f\x8b":
        return True
    head = raw[:64].lstrip(b"\xef\xbb\xbf\r\n\t ")
    if head.startswith(b"2423"):
        return True
    star = raw.find(b"**")
    return star is not None and star >= 8


def _decode_step(raw: bytes):
    """单层解码，返回 (解码产物 bytes, 方法名) 或 (None, "") 表示不识别。
    尝试顺序与 tvbox 社区分发格式一致：壳 → 2423 → 裸 b64 → gzip。"""
    # 1) ** 壳：定位 ** 分隔符（字节位置 ≥8；find 未命中再走前缀正则兜底）
    star = raw.find(b"**")
    if star < 0:
        m = re.search(rb"[A-Za-z0-9]{8}\*\*", raw[:512])
        star = m.end() - 2 if m else -1
    if star >= 8:
        try:
            return _try_b64(raw[star + 2:]), "shell_base64"
        except Exception:  # noqa: BLE001
            pass
    # 2) 2423 AES-128-CBC（hex 布局 → plain 布局）
    head = raw.lstrip(b"\xef\xbb\xbf\r\n\t ")
    if head.startswith(b"2423"):
        text = raw.decode("utf-8", "replace").strip()
        for fn, tag in ((_try_2423_hex, "aes2423_hex"), (_try_2423_plain, "aes2423_plain")):
            try:
                return fn(text), tag
            except Exception:  # noqa: BLE001
                pass
    # 3) 裸 base64（去杂后仅 b64 字符且 ≥64 字符）
    clean = _B64_CLEAN_RE.sub(b"", raw)
    if len(clean) >= 64 and len(clean) >= len(raw) * 0.95:
        try:
            return base64.b64decode(clean + b"==", validate=False), "base64"
        except Exception:  # noqa: BLE001
            pass
    # 4) gzip
    if raw[:2] == b"\x1f\x8b":
        try:
            return _gunzip_capped(raw), "gzip"
        except Exception:  # noqa: BLE001
            pass
    return None, ""


def decode_obscured(raw: bytes, max_depth: int = None):
    """递归解码链入口。返回 (json_bytes, 方法链) 或 (None, 失败原因)。
    方法链形如 "shell_base64>aes2423_hex"。"""
    if raw is None:
        return None, "empty input"
    if len(raw) > MAX_INPUT_BYTES:
        return None, "input too large (%d bytes > %d)" % (len(raw), MAX_INPUT_BYTES)
    depth = 0
    limit = max_depth if max_depth is not None else MAX_DEPTH
    method_chain = []
    payload = raw
    while depth <= limit:
        jb = _as_json_bytes(payload)
        if jb is not None:
            if len(jb) > MAX_OUTPUT_BYTES:
                return None, "json exceeds cap"
            return jb, ">".join(method_chain)
        if depth == limit:
            break
        nxt, method = _decode_step(payload)
        if nxt is None:
            break
        if len(nxt) > MAX_OUTPUT_BYTES:
            return None, "decoded exceeds cap"
        method_chain.append(method)
        payload = nxt
        depth += 1
    if method_chain:
        return None, "decode exhausted without JSON: " + ">".join(method_chain)
    return None, "no recognizable encoding"


def decode_config(raw: bytes):
    """供 fetch_merge 调用的便捷入口：只对密文特征命中的输入解码，其余原样
    放行（返回 (raw, "")）。解码失败返回 (None, 原因)。"""
    if not is_obscured(raw):
        jb = _as_json_bytes(raw)
        return (jb, "") if jb is not None else (raw, "")
    return decode_obscured(raw)


if __name__ == "__main__":   # 自检：python3 scripts/config_decode.py
    import json as _json
    # FIPS-197 附录 C.1 已知答案测试
    ct = _encrypt_block(bytes.fromhex("00112233445566778899aabbccddeeff"),
                        _expand_key(bytes.fromhex("000102030405060708090a0b0c0d0e0f")))
    assert ct == bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a"), ct.hex()
    # CBC 回路
    key, iv = b"K" * 16, b"I" * 16
    pt = _json.dumps({"sites": [1, 2, 3]}).encode()
    pad = 16 - len(pt) % 16
    pt += bytes([pad]) * pad
    assert aes128_cbc_decrypt(aes128_cbc_encrypt(pt, key, iv), key, iv) == pt
    print("config_decode self-test OK")
