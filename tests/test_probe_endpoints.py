"""5g type4 端点探针的取景与判级口径。

钉住的几条硬规则：
  * 只吃 type==4 且 http api（type 0/1 归 5a，type 3 归 5b，别互相踩）
  * 本地/内网端点不下死判（那是用户自己起的助手）
  * 判死要么 404/410，要么 DNS 无解析**且 DoH 复核确认**；超时/被拒/被断一律 unknown
  * "能用"的证据是解析得出非空 JSON 结构，Content-Type 说了不算（实测有 text/json 顶着一句
    中文"参数错误"的口子）
"""
import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import probe_endpoints as pe  # noqa: E402
import store  # noqa: E402


class ScopeTest(unittest.TestCase):
    def test_only_type4_http(self):
        self.assertTrue(pe.is_endpoint_site({"type": 4, "api": "https://x.com/a.php"}))
        self.assertFalse(pe.is_endpoint_site({"type": 1, "api": "https://x.com/api.php"}),
                         "type 0/1 是 5a 的活，不能两边都测")
        self.assertFalse(pe.is_endpoint_site({"type": 3, "api": "csp_Xyz"}))
        self.assertFalse(pe.is_endpoint_site({"type": 4, "api": "./py/x.py"}))

    def test_local_endpoints_are_not_judged(self):
        for u in ("http://127.0.0.1:1988/x", "http://localhost:1900/x",
                  "http://192.168.1.7:8080/x", "http://10.0.0.5/x", "http://[::1]:1/x"):
            self.assertTrue(pe.local_endpoint(u), u)
        self.assertFalse(pe.local_endpoint("https://so.yinpai.xyz/api.php?type=baidu"))

    def test_local_endpoint_gets_unknown_and_no_request(self):
        calls = []
        real = pe.get_status
        pe.get_status = lambda *a, **k: calls.append(a) or (200, b"{}", 1, "application/json")
        try:
            r = pe.probe_one({"key": "k", "type": 4, "api": "http://127.0.0.1:1988/x"}, 3)
        finally:
            pe.get_status = real
        self.assertEqual(r["level"], "E?")
        self.assertIn("本地/内网", r["reason"])
        self.assertEqual(calls, [], "本地端点不该发请求")


class ClassifyTest(unittest.TestCase):
    def test_path_gone_is_dead(self):
        for code in (404, 410):
            lv, why = pe.classify_response(code, "text/html", b"<html>nope</html>")
            self.assertEqual(lv, "E0", code)
            self.assertIn("路径失效", why)

    def test_auth_and_wrong_method_are_not_death(self):
        for code in (401, 403, 405, 501):
            lv, _ = pe.classify_response(code, "text/plain", b"x" * 40)
            self.assertEqual(lv, "E1", code)

    def test_structured_json_is_the_only_usable_evidence(self):
        lv, why = pe.classify_response(200, "application/json", json.dumps({"code": 0, "list": [1]}).encode())
        self.assertEqual(lv, "E2")
        self.assertIn("非空 JSON", why)

    def test_content_type_json_is_not_evidence_by_itself(self):
        # 真实回归：so.yinpai.xyz 一类回 Content-Type: text/json + 4 字节中文"参数错误"
        lv, why = pe.classify_response(200, "text/json", "参数错误".encode("utf-8"))
        self.assertEqual(lv, "E1", "一句报错不能算端点在工作")
        self.assertIn("无结构", why)

    def test_empty_structures_and_html_are_unknown(self):
        for body, ct in ((b"[]", "application/json"), (b"{}", "application/json"),
                         (b"null", "application/json"),
                         (b"<!DOCTYPE html><html><body>hi</body></html>", "text/html"),
                         (b"", "text/plain")):
            self.assertEqual(pe.classify_response(200, ct, body)[0], "E1", body[:12])

    def test_server_error_is_unknown(self):
        self.assertEqual(pe.classify_response(500, "text/plain", b"boom" * 9)[0], "E?")


class DnsCaliberTest(unittest.TestCase):
    """解析失败必须过 DoH 才允许判死——单台解析器不当判决（本地网络误杀 adult.json 的教训）。"""

    def _run_with_dns_error(self, doh_result):
        import urllib.error

        def boom(*a, **k):
            raise urllib.error.URLError("[Errno 11001] getaddrinfo failed")

        real_get, real_doh = pe.get_status, pe.doh_cached
        pe.get_status = boom
        pe.doh_cached = lambda host, t: doh_result
        try:
            return pe.probe_one({"key": "k", "type": 4,
                                 "api": "https://catbox.n13.club/t9/bili.php"}, 3)
        finally:
            pe.get_status, pe.doh_cached = real_get, real_doh

    def test_doh_confirms_absent_record_means_dead(self):
        r = self._run_with_dns_error((False, "ali:NOERROR/空 google:无应答(URLError)"))
        self.assertEqual(r["level"], "E0")
        self.assertIn("DoH", r["reason"], "判死理由要写明是谁确认的")

    def test_doh_has_record_means_environment_problem_not_death(self):
        r = self._run_with_dns_error((True, "ali:NOERROR/有答案"))
        self.assertEqual(r["level"], "E?", "本机解析不到但域还在，不能判死")

    def test_doh_unverifiable_means_unknown(self):
        r = self._run_with_dns_error((None, "ali:无应答(URLError) google:无应答(URLError)"))
        self.assertEqual(r["level"], "E?")


class GuardTest(unittest.TestCase):
    def test_verdict_rate_excludes_local_endpoints(self):
        rs = [{"level": "E2", "reason": "ok"},
              {"level": "E?", "reason": "本地/内网端点，不适用远端实测"},
              {"level": "E?", "reason": "URLError: timed out"}]
        self.assertAlmostEqual(pe.verdict_rate(rs), 0.5, places=3)

    def test_write_guard_only_blocks_when_old_artifact_exists(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "endpoint_probe.json")
            self.assertFalse(pe.should_refuse_write(0.1, p, False), "没有旧产物就没什么可保护")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{}")
            self.assertTrue(pe.should_refuse_write(0.1, p, False), "有结论率过低要保住上一轮判定")
            self.assertFalse(pe.should_refuse_write(0.9, p, False))
            self.assertFalse(pe.should_refuse_write(0.1, p, True), "--force 才允许强刷")


class StoreMappingTest(unittest.TestCase):
    def test_level_mapping(self):
        self.assertEqual(store.classify("E2"), "degraded")
        self.assertEqual(store.classify("E0"), "dead")
        self.assertEqual(store.classify("E1"), "unknown")
        self.assertEqual(store.classify("E?"), "unknown")

    def test_priority_below_deep_probes(self):
        """端点应答比真机五关/沙箱五关浅，不能覆写它们。"""
        self.assertLess(store.probe_priority("probe/endpoint_probe.json"),
                        store.probe_priority("probe/csp_probe.json"))
        self.assertLess(store.probe_priority("probe/endpoint_probe.json"),
                        store.probe_priority("probe/sites_probe.json"))


if __name__ == "__main__":
    unittest.main()
