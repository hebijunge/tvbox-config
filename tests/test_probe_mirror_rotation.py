# -*- coding: utf-8 -*-
"""github raw 源「加代理」验活：镜像链轮询的行为回归（全 mock，不连网）。

覆盖所有者 2026-09-30 指令的语义：raw 源判活口径 = 国内经任一镜像可达，
原前缀挂掉要换链上其它前缀重试；但 http 明确错误码不换（换镜像也是同样错误）。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import probe_sites as ps  # noqa: E402

RAW = "https://raw.githubusercontent.com/o/r/main/cfg.json"
PREFIXED = "https://gh-proxy.com/" + RAW
ALT = "https://ghproxy.net/" + RAW


class TestGhInner(unittest.TestCase):
    def test_bare_and_prefixed_both_extract_inner(self):
        self.assertEqual(ps._gh_inner(RAW), RAW)
        self.assertEqual(ps._gh_inner(PREFIXED), RAW)

    def test_non_raw_returns_none(self):
        self.assertIsNone(ps._gh_inner("https://lbapi9.com/api.php/provide/vod/"))
        self.assertIsNone(ps._gh_inner(""))


class TestRotateCandidates(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(ps, "_mirror_prefixes", return_value=[
            "https://gh-proxy.com/", "https://ghproxy.net/",
            "https://gh.acmsz.top/", "https://ghfast.top/"])
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_http_error_class_does_not_rotate(self):
        # 明确错误码（仓库 404）：换镜像也是同样结果，不浪费探测预算
        self.assertEqual(ps._rotate_gh_mirrors(PREFIXED, "http"), [])

    def test_env_class_rotates_excluding_current_prefix(self):
        cands = ps._rotate_gh_mirrors(PREFIXED, "env")
        self.assertTrue(cands)
        self.assertTrue(all(RAW in c for c in cands))
        self.assertFalse(any(c.startswith("https://gh-proxy.com/") for c in cands))

    def test_non_raw_no_rotation(self):
        self.assertEqual(ps._rotate_gh_mirrors("https://ztha.top/x.json", "env"), [])

    def test_cap_limits_candidates(self):
        with mock.patch.object(ps, "_mirror_prefixes",
                               return_value=["https://m%d/" % i for i in range(10)]):
            self.assertLessEqual(len(ps._rotate_gh_mirrors(PREFIXED, "env")),
                                 ps._MIRROR_ROTATE_MAX)


class TestProbeL1Rotation(unittest.TestCase):
    def test_original_ok_skips_rotation(self):
        calls = []
        def fake(api, timeout=None):
            calls.append(api)
            return {"ok": True, "resolved_api": api}
        with mock.patch.object(ps, "_probe_l1_api", fake):
            r = ps.probe_l1(PREFIXED)
        self.assertTrue(r["ok"])
        self.assertEqual(calls, [PREFIXED], "原前缀通了不该再试别的镜像")

    def test_mirror_rescues_when_original_env_fails(self):
        def fake(api, timeout=None):
            if api == ALT:
                return {"ok": True, "resolved_api": api}
            return {"ok": False, "cls": "env", "reason": "timeout"}
        with mock.patch.object(ps, "_mirror_prefixes", return_value=["https://ghproxy.net/"]), \
             mock.patch.object(ps, "_probe_l1_api", fake):
            r = ps.probe_l1(PREFIXED)
        self.assertTrue(r["ok"])
        self.assertTrue(r.get("via_mirror"))
        self.assertEqual(r["resolved_api"], ALT)

    def test_http_class_blocks_rotation(self):
        seen = []
        def fake(api, timeout=None):
            seen.append(api)
            return {"ok": False, "cls": "http", "reason": "HTTP 404"}
        with mock.patch.object(ps, "_probe_l1_api", fake):
            r = ps.probe_l1(PREFIXED)
        self.assertEqual(seen, [PREFIXED], "http 错误码不应触发换镜像")
        self.assertFalse(r["ok"])


class TestResolvedApiThreadsThrough(unittest.TestCase):
    def test_probe_http_site_swaps_to_reachable_mirror(self):
        used_apis = []
        # L1 经另一镜像才通 → probe_http_site 应把 api 回填成可达镜像，L2/L3 复用它
        l1 = mock.Mock(return_value={"ok": True, "cls": None, "resolved_api": ALT})
        def l2(api, keywords, timeout=None):
            used_apis.append(api)
            return {"ok": True, "vod_id": 5}
        l3 = mock.Mock(return_value={"ok": True})
        with mock.patch.object(ps, "_mirror_prefixes", return_value=["https://ghproxy.net/"]), \
             mock.patch.object(ps, "probe_l1", l1), \
             mock.patch.object(ps, "probe_l2", l2), \
             mock.patch.object(ps, "probe_l3", l3):
            r = ps.probe_http_site({"key": "k", "name": "n", "api": PREFIXED}, ["庆余年"])
        self.assertEqual(r["level"], "L3")
        self.assertEqual(r["api"], ALT, "产物 api 回填成可达镜像")
        self.assertEqual(used_apis, [ALT], "L2 复用同一条国内可达链路")


class TestRequestable(unittest.TestCase):
    """中文路径 raw 源必须归一后再发，否则 UnicodeEncodeError 把活源误判死。"""

    def test_chinese_path_percent_encoded(self):
        u = ps.requestable("https://raw.githubusercontent.com/o/r/main/一木/看演唱会.json")
        self.assertTrue(u.isascii())
        self.assertIn("%E7%9C%8B", u)  # "看" 的百分号编码

    def test_ascii_url_unchanged(self):
        self.assertEqual(ps.requestable(RAW), RAW)

    def test_mirror_candidate_survives_encoding(self):
        # 中文路径的 raw 源，换镜像后候选仍是可发出的 ascii
        cn = "https://ghproxy.com/" + "https://raw.githubusercontent.com/o/r/main/娱乐包/x.json"
        with mock.patch.object(ps, "_mirror_prefixes", return_value=["https://gh-proxy.net/"]):
            cands = ps.gh_retry_candidates(cn)
        self.assertTrue(cands)
        self.assertTrue(ps.requestable(cands[0]).isascii())


if __name__ == "__main__":
    unittest.main()
