# -*- coding: utf-8 -*-
"""5c JS 探针：「规则源取不到」必须有逐条证据，环境性失败一律留 S?。

起因（2026-10-02 抽审）：js_probe 里 152 条 S0 的理由是同一句话「deps 无本地副本，域名失效/不可达」，
逐条现场重取后：当场能取回 7 条（pan.szfx.top/down.php 28511B、fastlink.cokey.xyz/f/…/get.js 等）、
DoH 确认域名已亡 7 条、超时/重置等环境性 5 条、其余 133 条状态不明。把「我们没取到」写成
「站点已死」就是拿工装能力冒充站点结论——与 9-29 本地网络误杀 adult.json 104 站同一类事故。

红线：
  * S0 只准带结构性证据（域名 DoH 一致无记录 / 规则文件 404·410 / 规则地址变 HTML 壳）；
  * 备用域列表要**全部**候选都结构性失踪才准判死（spider 自己会挨个试）；
  * ext 是站点根 URL 时返回整页 HTML 属正常形态，不算规则亡。
"""
import importlib.util
import os
import socket
import sys
import types
import unittest
import urllib.error

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "probe_js_under_test", os.path.join(_ROOT, "scripts", "probe_js.py"))
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

RULE_JS = b"""/**
 * rule demo
 */
var rule = {
    title:'demo',
    host:'https://demo.example.com',
    url:'/show/fyclass/fypage.html',
    searchUrl:'/search/?wd=**',
    class_url:'1&2&3',
};
"""


def _httperror(code):
    return urllib.error.HTTPError("u", code, "err", {}, None)


class FakeModules(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        for name in ("probe_sites", "probe_endpoints"):
            self.saved[name] = sys.modules.get(name)
        ps = types.ModuleType("probe_sites")
        ps.gh_retry_candidates = lambda u: []
        pe = types.ModuleType("probe_endpoints")
        self.doh_verdict = None
        pe.doh_cached = lambda host, t: (self.doh_verdict, "stub")
        sys.modules["probe_sites"] = ps
        sys.modules["probe_endpoints"] = pe
        self.saved_get = mod.http_get

    def tearDown(self):
        for name, m in self.saved.items():
            if m is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = m
        mod.http_get = self.saved_get

    def stub(self, fn):
        mod.http_get = fn


class UrlsTest(FakeModules):
    def test_backup_domains_all_kept(self):
        site = {"ext": "https://a.example/x.js,https://b.example/x.js", "api": "./drpy2.js"}
        self.assertEqual(mod.remote_rule_urls(site),
                         ["https://a.example/x.js", "https://b.example/x.js"])

    def test_local_and_device_endpoints_excluded(self):
        site = {"ext": "http://127.0.0.1:8080/a.js$$$http://192.168.1.5/b.js"}
        self.assertEqual(mod.remote_rule_urls(site), [])

    def test_dollar_separator_keeps_both_segments(self):
        site = {"ext": "https://a.example/x.js$$$https://b.example/y.js"}
        self.assertEqual(mod.remote_rule_urls(site),
                         ["https://a.example/x.js", "https://b.example/y.js"],
                         "$$$ 是多段分隔符，不能黏进第一个 URL 里")

    def test_dollar_split_and_quotes(self):
        site = {"ext": '["https://c.example/r.js",""]',
                "api": "http://d.example/drpy2.min.js;md5;abc"}
        self.assertEqual(mod.remote_rule_urls(site),
                         ["https://c.example/r.js", "http://d.example/drpy2.min.js"],
                         "JSON 数组形态的 ext 也要抓到；;md5; 尾巴要丢掉")


class MissKindTest(FakeModules):
    def test_root_url_html_is_not_death(self):
        self.assertEqual(mod.miss_kind("https://demo.example.com/", 200, "<html>ok</html>"), "")

    def test_rule_file_gone(self):
        self.assertEqual(mod.miss_kind("https://demo.example.com/r.js", 404, ""), "gone-404")
        self.assertEqual(mod.miss_kind("https://demo.example.com/r.json", 410, ""), "gone-410")

    def test_rule_file_became_lander(self):
        self.assertEqual(mod.miss_kind("https://demo.example.com/r.js", 200, "<!DOCTYPE html>"),
                         "lander-html")


class FetchVerdictTest(FakeModules):
    def test_fetchable_rule_returns_local_copy(self):
        def ok(url, timeout=12):
            return 200, RULE_JS, 50, "application/javascript"
        self.stub(ok)
        fp, v = mod.fetch_remote_rule({"ext": "https://a.example/drpy_demo.js"})
        self.assertTrue(fp and fp.endswith(".js"), "取回的规则要落成 .js 供下游复用")
        with open(fp, encoding="utf-8") as f:
            self.assertIn("var rule", f.read())
        self.assertTrue(v["rule_src_url"].startswith("https://a.example/"))

    def test_all_backup_domains_gone_is_s0_with_evidence(self):
        def err(url, timeout=12):
            raise _httperror(404)
        self.stub(err)
        fp, v = mod.fetch_remote_rule({"ext": "https://a.example/x.js,https://b.example/x.js"})
        self.assertIsNone(fp)
        self.assertEqual(v["level"], "S0")
        self.assertEqual(v["evidence"]["ext_dep"], "remote-rule-unreachable")
        self.assertEqual(v["evidence"]["tried"], 2, "备用域要全部失踪才准判死")

    def test_timeout_is_environmental_not_death(self):
        def to(url, timeout=12):
            raise socket.timeout("timed out")
        self.stub(to)
        fp, v = mod.fetch_remote_rule({"ext": "https://a.example/x.js"})
        self.assertIsNone(fp)
        self.assertEqual(v["level"], "S?", "超时是网络问题，不是站点结论")

    def test_dns_fail_unconfirmed_by_doh_stays_unknown(self):
        def bad(url, timeout=12):
            raise OSError("[Errno 11001] getaddrinfo failed")
        self.stub(bad)
        self.doh_verdict = True          # DoH 说域名还在
        fp, v = mod.fetch_remote_rule({"ext": "https://a.example/x.js"})
        self.assertEqual(v["level"], "S?")

    def test_dns_fail_confirmed_dead_by_doh_is_s0(self):
        def bad(url, timeout=12):
            raise OSError("[Errno 11001] getaddrinfo failed")
        self.stub(bad)
        self.doh_verdict = False         # 阿里+Google 都 NOERROR 且无答案
        fp, v = mod.fetch_remote_rule({"ext": "https://a.example/x.js"})
        self.assertEqual(v["level"], "S0")
        self.assertIn("DoH", v["evidence"]["cause"])

    def test_partial_structural_partial_env_does_not_judge(self):
        def mixed(url, timeout=12):
            if url.startswith("https://a."):
                raise _httperror(404)
            raise socket.timeout("timed out")
        self.stub(mixed)
        fp, v = mod.fetch_remote_rule({"ext": "https://a.example/x.js,https://b.example/x.js"})
        self.assertEqual(v["level"], "S?", "有一路只是没测准，就不能说整站已亡")


class ProbeOneIntegration(FakeModules):
    def test_no_local_copy_but_fetchable_gets_real_level(self):
        def ok(url, timeout=12):
            return 200, RULE_JS, 50, ""
        self.stub(ok)
        calls = []

        def site_fetch(url, timeout=12, headers=None):
            calls.append(url)
            raise socket.timeout("timed out")
        real = mod.http_get
        mod.http_get = lambda u, timeout=12, headers=None: (
            ok(u, timeout) if "a.example" in u else site_fetch(u, timeout))
        r = mod.probe_one({"key": "K", "name": "N", "api": "./drpy2.js",
                           "ext": "https://a.example/drpy_demo.js"}, ".", ["庆余年"], {})
        self.assertTrue(str(r.get("rule")).startswith("remote:"), r.get("rule"))
        self.assertEqual(r.get("host"), "https://demo.example.com")
        self.assertIn(r.get("level"), ("S1", "S?"), "站点页取不到只影响等级，不该回到 S0")

    def test_no_local_copy_and_dead_domain_is_s0_not_blanket(self):
        def err(url, timeout=12):
            raise _httperror(404)
        self.stub(err)
        r = mod.probe_one({"key": "K", "name": "N", "api": "./drpy2.js",
                           "ext": "https://a.example/x.js"}, ".", ["庆余年"], {})
        self.assertEqual(r["level"], "S0")
        self.assertIn("ext_dep", r["evidence"])

    def test_no_url_at_all_is_unknown(self):
        r = mod.probe_one({"key": "K", "name": "N", "api": "./missing.js"}, ".", ["庆余年"], {})
        self.assertEqual(r["level"], "S?")



class StoreMapping(unittest.TestCase):
    """S0 现在只带结构性证据，所以入库算 dead；没验成的一律 S?（unknown）。"""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "store_under_test", os.path.join(_ROOT, "scripts", "store.py"))
        cls.store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.store)

    def test_s0_is_dead_squestion_is_unknown(self):
        self.assertEqual(self.store.classify("S0"), "dead")
        self.assertEqual(self.store.classify("S?"), "unknown")
        self.assertEqual(self.store.classify("S1"), "degraded")

    def test_shallow_probe_without_level_stays_unknown(self):
        self.assertEqual(self.store.health_of(None, False, 2), "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
