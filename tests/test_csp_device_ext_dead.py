# -*- coding: utf-8 -*-
"""远程 ext 的可达性判定：只把「结构性已亡」写成结论，环境性失败留未测。

起因（2026-10-02 实测）：734 个真机 G0 里 261 个连 gateErr 都没有——homeContent 不抛异常、
直接返回空串（采样 60 个，57 个是空串）。原因是 xyq/xbpq 系 spider 在 init 里自己联网拉
远程规则，拉不到就静默空转。416 个远程 ext 在国内只有 3 个还能取回规则形态，250 个域名
根本解析不了。这类站在真机上永远测不出结论，但 ext 可达性能在国内直接证伪。

红线：解析失败必须过 DoH 复核才准判死。只凭本机一台解析器判死，就是 2026-09-29
「本地网络误杀 adult.json 104 站」那次事故的重演。
"""
import importlib.util
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "csp_device_batch", os.path.join(_ROOT, "csp-device", "csp_device_batch.py"))
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

U = "http://mao.laigc.com/MaooXB/蓝光影院.json"


class RemoteExtsTest(unittest.TestCase):
    def test_device_side_services_are_never_judged(self):
        """127.0.0.1:9978 是设备上的 token 服务：本机取到的是 PC 的文件，据此判死是假证据。"""
        for u in ("http://127.0.0.1:9978/file/tm/token.txt", "http://localhost:1/x.json",
                  "http://192.168.1.9/api.php/v1.vod", "http://10.0.0.5/x.json"):
            self.assertEqual(mod.remote_exts(u), [], u)

    def test_public_remote_ext_is_picked_up(self):
        self.assertEqual(mod.remote_exts(U), [U])
        self.assertEqual(mod.remote_exts("./deps/x.json"), [])

    def test_multi_segment_only_counts_url_segments(self):
        got = mod.remote_exts("http://a/x.json$$$./deps/y.json$$$key123")
        self.assertEqual(got, ["http://a/x.json"])


class ApplyExtDeadTest(unittest.TestCase):
    def setUp(self):
        self.pending = [("蓝", "蓝", "XBPQ", U), ("影", "影", "XYQHiker", "http://b/y.json"),
                        ("好", "好", "csp", "http://c/z.json")]

    def test_confirmed_dead_url_writes_c0(self):
        by = {}
        n = mod.apply_ext_dead(by, self.pending, {U: "域名无解析记录(DoH一致)"}, "now")
        self.assertEqual(n, 1)
        row = by["蓝"]
        self.assertEqual(row["level"], "C0")
        self.assertEqual(row["evidence"]["ext_dep"], "remote-rule-unreachable")
        self.assertIn("DoH", row["evidence"]["cause"], "判死理由要能复盘")

    def test_environmental_failure_writes_nothing(self):
        """超时/重置/未复核：不下结论。"""
        by = {}
        n = mod.apply_ext_dead(by, self.pending, {}, "now")
        self.assertEqual(n, 0)
        self.assertEqual(by, {})

    def test_existing_device_verdict_is_not_downgraded(self):
        by = {"蓝": {"key": "蓝", "level": "C2"}}
        n = mod.apply_ext_dead(by, self.pending, {U: "gone-404"}, "now")
        self.assertEqual(n, 0, "真机跑实过的站不因 URL 死就降级")
        self.assertEqual(by["蓝"]["level"], "C2")

    def test_cannot_be_rescued_by_absence(self):
        by = {"好": {"key": "好", "level": "C3"}}
        dead = {"http://b/y.json": "lander-html"}
        n = mod.apply_ext_dead(by, self.pending, dead, "now")
        self.assertEqual((n, by["好"]["level"]), (1, "C3"), "有结论的站不动，其他照常判死")


class IsRuleTest(unittest.TestCase):
    def test_shapes(self):
        for good in ('{"list":[]}', '[1,2,3]', '<?xml version="1.0"?><class t="1"/>'):
            self.assertTrue(mod.is_rule(good), good)
        for bad in ("", "   ", "<html><body>404</body></html>",
                    "<!DOCTYPE html><html>lander</html>", "plain text"):
            self.assertFalse(mod.is_rule(bad), bad)


class ClassifyMissTest(unittest.TestCase):
    """只有「规则文件本身不在了」才算已亡；站点根 URL 返回 HTML 是正常形态。"""

    def test_rule_file_404_is_dead(self):
        self.assertEqual(mod.classify_miss("http://a/x/rule.json", 404, ""), "gone-404")
        self.assertEqual(mod.classify_miss("http://a/rule.txt", 410, ""), "gone-410")

    def test_rule_file_now_html_is_dead(self):
        self.assertEqual(mod.classify_miss("https://agit.ai/x/nmys.json", 200,
                                           "<!DOCTYPE html><html>lander"), "lander-html")

    def test_site_root_url_returning_html_is_NOT_dead(self):
        """xyq/xp 系的 ext 常是站点根地址，spider 抓首页自己解析——上一版误判了 31 站。"""
        self.assertEqual(mod.classify_miss("https://www.mutefun.tv", 200,
                                           "<!DOCTYPE html><html>正常门户"), "")
        self.assertEqual(mod.classify_miss("https://www.czzy.site/", 200, "<html>x</html>"), "")

    def test_root_url_404_is_NOT_a_rule_death(self):
        """根路径 404 可能只是站点改版，不足以判死整站。"""
        self.assertEqual(mod.classify_miss("https://a.example.com/", 404, ""), "")

    def test_timeout_on_rule_file_is_environmental(self):
        self.assertEqual(mod.classify_miss("http://a/x.json", 502, ""), "")


if __name__ == "__main__":
    unittest.main()
