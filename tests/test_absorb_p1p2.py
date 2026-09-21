"""P1-2 多镜像选通 / P1-3 UA 轮换 / P2-1 lives 套壳穿透 的行为测试。

不真实联网：monkeypatch http_get 记录调用并返回可控响应。
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import fetch_merge as fm
import live_aggregate as la


def _resp(status, body=b""):
    # fetch_merge.http_get 返回 (status, bytes, elapsed_ms)
    return status, body, 0


class TestFetchRaw(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.orig = fm.http_get

    def tearDown(self):
        fm.http_get = self.orig

    def _patch(self, fail_urls):
        def fake(url, timeout, max_bytes=0, rng=None, ua=None, xrw=None):
            self.calls.append((url, ua, xrw))
            if url in fail_urls:
                raise IOError("boom %s" % url)
            return _resp(200, b"data")
        fm.http_get = fake

    def test_primary_success_no_ua_retry(self):
        self._patch(set())
        raw, ch, ok_url = fm.fetch_raw("http://a.example/x.json")
        self.assertEqual(raw, b"data")
        self.assertEqual(ch, "direct")
        self.assertEqual(ok_url, "http://a.example/x.json")
        self.assertEqual(len(self.calls), 1)          # 首组 UA 即成功，不轮换
        self.assertEqual(self.calls[0][1], fm.UA_POOL_VOD[0]["User-Agent"])
        self.assertEqual(self.calls[0][2], fm.UA_POOL_VOD[0]["X-Requested-With"])

    def test_ua_rotation_then_mirror(self):
        # 主 URL 全 UA 组都挂 + mirror 也挂 → 尝试次数 = 2 URL × UA_ROTATE_MAX 组
        mirror = "http://m.example/x.json"
        self._patch({"http://a.example/x.json", mirror})
        raw, ch, ok_url = fm.fetch_raw("http://a.example/x.json", mirrors=[mirror])
        self.assertIsNone(raw)
        self.assertEqual(len(self.calls), 2 * fm.UA_ROTATE_MAX)
        # UA 依次轮换
        uas = [c[1] for c in self.calls[:fm.UA_ROTATE_MAX]]
        pool_uas = [p["User-Agent"] for p in fm.UA_POOL_VOD[:fm.UA_ROTATE_MAX]]
        self.assertEqual(uas, pool_uas)

    def test_mirror_success_after_primary_fail(self):
        mirror = "http://m.example/x.json"
        # 主 URL 用满轮换后仍失败，mirror 首组 UA 成功 → 共 3+1 次调用
        def fake(url, timeout, max_bytes=0, rng=None, ua=None, xrw=None):
            self.calls.append((url, ua))
            if url == "http://a.example/x.json":
                raise IOError("down")
            return _resp(200, b"m")
        fm.http_get = fake
        raw, ch, ok_url = fm.fetch_raw("http://a.example/x.json", mirrors=[mirror])
        self.assertEqual(raw, b"m")
        self.assertEqual(ok_url, mirror)
        self.assertEqual(ch, "mirror:m.example")

    def test_github_ghproxy_fallback_kept(self):
        # ghproxy 兜底通道保持默认 UA 单次尝试
        u = "https://raw.githubusercontent.com/foo/bar/main/c.json"
        gh_first = fm.GH_MIRRORS[0] + u
        self._patch({u})
        raw, ch, ok_url = fm.fetch_raw(u)
        self.assertEqual(raw, b"data")
        self.assertEqual(ok_url, gh_first)
        self.assertTrue(ch.startswith("mirror:"))

    def test_single_url_backward_compat(self):
        self._patch(set())
        raw, ch, ok_url = fm.fetch_raw("http://a.example/plain.json")
        self.assertEqual((raw, ch), (b"data", "direct"))


def _presp(status, body=b""):
    # live_probe.http_get 返回 (status, headers, body_bytes)
    return status, {}, body


class TestLiveShell(unittest.TestCase):
    def setUp(self):
        self.orig = la.http_get

    def tearDown(self):
        la.http_get = self.orig

    def test_plain_url_body_classification(self):
        self.assertTrue(la._is_plain_url_list_body("http://x/y.m3u\n"))
        self.assertFalse(la._is_plain_url_list_body("#EXTM3U\nhttp://x/y\n"))
        self.assertFalse(la._is_plain_url_list_body("a\nb"))

    def test_follow_two_layers(self):
        def fake(url, timeout, rng=None, ua=None):
            if url == "http://shell/a":
                return _presp(200, b"http://shell/b\n")
            return _presp(200, b"#EXTM3U\nhttp://real/1.ts\n")
        la.http_get = fake
        real = la.follow_live_shell("http://shell/a", set())
        self.assertEqual(real, "http://shell/b")

    def test_follow_loop_protection(self):
        def fake(url, timeout, rng=None, ua=None):
            return _presp(200, b"http://loop/b\n")
        la.http_get = fake
        # a 指向 b，b 指向 a？这里体恒指向 b；visited 防呆用自指体测循环
        def fake_self(url, timeout, rng=None, ua=None):
            return _presp(200, (url + "\n").encode())
        la.http_get = fake_self
        self.assertEqual(la.follow_live_shell("http://loop/a", set()), "")

    def test_non_shell_passthrough(self):
        def fake(url, timeout, rng=None, ua=None):
            return _presp(200, b"#EXTM3U\nhttp://real/1.ts\n")
        la.http_get = fake
        self.assertEqual(la.follow_live_shell("http://real/list.m3u", set()),
                         "http://real/list.m3u")

    def test_fetch_error_abandoned(self):
        def fake(url, timeout, rng=None, ua=None):
            return _presp(0, None)
        la.http_get = fake
        self.assertEqual(la.follow_live_shell("http://dead/a", set()), "")


class TestCollectCfgLives(unittest.TestCase):
    def setUp(self):
        self.orig = la.follow_live_shell
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        la.follow_live_shell = self.orig

    def test_collect(self):
        cfg = {"lives": [
            {"name": "壳源", "url": "http://shell/a"},
            {"name": "直连", "url": ["http://direct/x.m3u"]},
            {"name": "非URL", "url": "not-a-url"},
        ]}
        with open(os.path.join(self.tmp, "tvbox.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        la.follow_live_shell = lambda url, visited, timeout=15: (
            "http://real/a.m3u" if "shell" in url else url)
        out = la.collect_config_live_sources(self.tmp)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][0], "cfg:壳源")
        self.assertEqual(out[0][1], "http://real/a.m3u")
        self.assertEqual(out[1], ("cfg:直连", "http://direct/x.m3u"))

    def test_no_repo(self):
        self.assertEqual(la.collect_config_live_sources(None), [])
        self.assertEqual(la.collect_config_live_sources(os.path.join(self.tmp, "empty")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
