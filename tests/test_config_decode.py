"""config_decode 单元测试（stdlib unittest，不引入第三方依赖）。

覆盖：AES-128 FIPS-197 C.1 已知答案向量、CBC 加解密往返、`**` 壳解码、
2423 hex / plain 两种布局、gzip 与裸 base64、多层混合链与深度上限、
明文透传、输入字节上限与 JSON 尾部填充残字截断等防御。
"""

import base64
import gzip
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import config_decode as cd


def b64(raw: bytes) -> bytes:
    return base64.b64encode(raw)


def pad_to_16(data: bytes) -> bytes:
    p = 16 - len(data) % 16
    return data + bytes([p]) * p


class TestAesKAT(unittest.TestCase):
    def test_fips197_c1(self):
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        pt = bytes.fromhex("00112233445566778899aabbccddeeff")
        expect = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        out = cd._encrypt_block(pt, cd._expand_key(key))
        self.assertEqual(out, expect)

    def test_cbc_roundtrip(self):
        key, iv = b"0123456789abcdef", b"fedcba9876543210"
        for n in (16, 32, 48):
            pt = pad_to_16(bytes((i * 7) % 256 for i in range(n)))
            ct = cd.aes128_cbc_encrypt(pt, key, iv)
            self.assertEqual(len(ct), len(pt))
            self.assertEqual(cd.aes128_cbc_decrypt(ct, key, iv), pt)


class TestShell(unittest.TestCase):
    def test_shell_decode(self):
        obj = {"sites": [{"key": "x", "api": "csp_XPath"}]}
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        shell = b"12345678" + b"**" + b64(payload)
        self.assertTrue(cd.is_obscured(shell))
        out, method = cd.decode_obscured(shell)
        self.assertEqual(json.loads(out), obj)
        self.assertIn("shell_base64", method)

    def test_short_prefix_not_obscured(self):
        shell = b"abc" + b"**" + b64(b'{"a":1}')
        self.assertFalse(cd.is_obscured(shell))


class Test2423(unittest.TestCase):
    def test_2423_hex(self):
        obj = {"spider": "./jar/pg.jar", "sites": [{"key": "k", "api": "a"}]}
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        key, iv = "mykey123", "iv45678901234"   # iv 13 字符 → hex 恰 26 字符
        ct = cd.aes128_cbc_encrypt(pad_to_16(raw), cd._pad16(key), cd._pad16(iv))
        wire = ("2423" + key.encode().hex() + "2324" + ct.hex() + iv.encode().hex())
        self.assertTrue(cd.is_obscured(wire.encode()))
        out, method = cd.decode_obscured(wire.encode())
        self.assertEqual(json.loads(out), obj)
        self.assertIn("aes2423_hex", method)

    def test_2423_plain(self):
        obj = {"sites": [{"key": "k2", "api": "b"}]}
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        key, iv = "secret9", "ivwxyz1234567"    # iv 13 字符，text[-13:] 即 iv
        ct = cd.aes128_cbc_encrypt(pad_to_16(raw), cd._pad16(key), cd._pad16(iv))
        wire = ("2423" + key.encode().hex() + "2324" + ct.hex()
                + "$#" + key + "#$" + iv)
        out, method = cd.decode_obscured(wire.encode())
        self.assertEqual(json.loads(out), obj)
        self.assertIn("aes2423_plain", method)

    def test_hex_branch_not_steal_plain(self):
        # plain 布局不应被 hex 分支抢跑：hex 分支 iv 尾非 hex 必须失败，
        # 最终仍要由 plain 分支正确解出（本用例若回归会解出垃圾而失败）。
        obj = {"sites": [{"key": "p", "api": "c"}]}
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        key, iv = "kk9", "ivwxyz1234567"
        ct = cd.aes128_cbc_encrypt(pad_to_16(raw), cd._pad16(key), cd._pad16(iv))
        wire = ("2423" + key.encode().hex() + "2324" + ct.hex()
                + "$#" + key + "#$" + iv)
        out, method = cd.decode_obscured(wire.encode())
        self.assertIsNotNone(out)
        self.assertEqual(json.loads(out), obj)
        self.assertNotIn("aes2423_hex", method)


class TestGzipBase64(unittest.TestCase):
    def test_gzip(self):
        obj = {"lives": [{"name": "n", "url": "u"}]}
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as f:
            f.write(json.dumps(obj).encode("utf-8"))
        self.assertTrue(cd.is_obscured(buf.getvalue()))
        out, method = cd.decode_obscured(buf.getvalue())
        self.assertEqual(json.loads(out), obj)
        self.assertIn("gzip", method)

    def test_bare_base64(self):
        obj = {"spider": "./jar/pg-live.jar;md5;09032026",
               "sites": [{"key": "k", "api": "c", "name": "长名称测试站点"}]}
        out, method = cd.decode_obscured(b64(json.dumps(obj).encode()))
        self.assertEqual(json.loads(out), obj)
        self.assertIn("base64", method)

    def test_b64_non_json_rejected(self):
        out, method = cd.decode_obscured(b64(b"this is not json at all!!"))
        self.assertIsNone(out)
        self.assertTrue(method)


class TestChain(unittest.TestCase):
    def _mk(self, obj, depth=1):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        for _ in range(depth):
            raw = b"98765432" + b"**" + b64(raw)
        return raw

    def test_multi_layer(self):
        obj = {"sites": [{"key": "deep", "api": "d"}]}
        out, method = cd.decode_obscured(self._mk(obj, depth=3))
        self.assertEqual(json.loads(out), obj)
        self.assertGreaterEqual(method.count(">"), 2)

    def test_depth_cap(self):
        out, method = cd.decode_obscured(self._mk({"sites": []}, depth=6))
        self.assertIsNone(out)


class TestDefenses(unittest.TestCase):
    def test_garbage_input(self):
        out, method = cd.decode_obscured(b"\x00\x01\x02garbage-not-encodable")
        self.assertIsNone(out)
        self.assertTrue(method)

    def test_oversize_input(self):
        old = cd.MAX_INPUT_BYTES
        cd.MAX_INPUT_BYTES = 2048
        try:
            big = b"0123456789abcdef**" + b64(b"x" * 3000)
            out, method = cd.decode_obscured(big)
            self.assertIsNone(out)
            self.assertIn("too large", method)
        finally:
            cd.MAX_INPUT_BYTES = old

    def test_trailing_pad_truncated(self):
        # 密文分组填充残字（非 PKCS7 语义）应被截到最后一个 } / ]
        obj = {"sites": [{"key": "t", "api": "e"}]}
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\x07" * 7
        shell = b"13579024" + b"**" + b64(payload)
        out, method = cd.decode_obscured(shell)
        self.assertEqual(json.loads(out), obj)

    def test_decode_config_passthrough(self):
        raw = json.dumps({"sites": [], "lives": []}).encode("utf-8")
        out, reason = cd.decode_config(raw)
        self.assertEqual(json.loads(out), json.loads(raw))
        self.assertEqual(reason, "")

    def test_decode_config_garbage_passthrough(self):
        # 非密文特征且非 JSON：原样放行（后续由既有质量门裁决）
        raw = b"plain text body"
        out, reason = cd.decode_config(raw)
        self.assertEqual(out, raw)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
