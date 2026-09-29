"""阶段 3 候选评估的形态分流回归（不触网：monkeypatch http_get）。

钉住 2026-09-29 的修法：直播列表/HTML 页/SVG 不能再被算成「JSON 解析失败」，
BOM 与裸数组形态要与 discover 同口径——旧口径下 80 条候选只有 25 条评估成功，
其中 32 条「Expecting value」其实是候选根本不是点播配置。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import evaluate_candidates as ec  # noqa: E402

BASE = {"fp-existing"}


class TestShapeDetection(unittest.TestCase):
    def test_live_shapes(self):
        self.assertTrue(ec._looks_like_live('#EXTM3U\n#EXTINF:-1,t\nhttp://a/1.ts'))
        self.assertTrue(ec._looks_like_live('央视,#genre#\nCCTV-1,http://a'))
        self.assertFalse(ec._looks_like_live('{"sites":[]}'))

    def test_html_shapes(self):
        self.assertTrue(ec._looks_like_html('<!DOCTYPE html><html>'))
        self.assertTrue(ec._looks_like_html('<svg xmlns="http://www.w3.org/2000/svg">'))
        self.assertFalse(ec._looks_like_html('{"sites":[{"api":"u"}]}'))


class TestEvalOne(unittest.TestCase):
    def setUp(self):
        self._real = ec.http_get

    def tearDown(self):
        ec.http_get = self._real

    def _feed(self, text):
        ec.http_get = lambda url, timeout=15: text

    def test_m3u_is_skipped_not_failure(self):
        self._feed('#EXTM3U\n' + '#EXTINF:-1,t\nhttp://a/1.ts\n' * 7)
        out = ec.eval_one({"url": "https://x/iptv.m3u"}, BASE)
        self.assertEqual(out["err"], "", "直播列表不该记成解析失败")
        self.assertIn("直播", out.get("skipped", ""))
        self.assertEqual(out["entries"], 7)

    def test_html_page_is_labelled_noise(self):
        self._feed("<!DOCTYPE html><html><body>repo front page</body></html>")
        out = ec.eval_one({"url": "https://github.com/qist/tvbox"}, BASE)
        self.assertTrue(out["err"].startswith("HTML/SVG"), out["err"])

    def test_bom_and_leading_space_still_parse(self):
        self._feed('\ufeff  \n {"sites":[{"key":"k","api":"http://a/x","name":"n"}]}')
        out = ec.eval_one({"url": "https://x/cfg.json"}, BASE)
        self.assertEqual(out["err"], "")
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["unique"], 1)

    def test_bare_array_needs_api(self):
        # Alist 服务器列表：有 name 无 api → 不能算站点（与 discover.sites_of 同口径）
        self._feed('[{"name":"本地","server":"http://127.0.0.1:5244"}]')
        out = ec.eval_one({"url": "https://x/alist.json"}, BASE)
        self.assertEqual(out["err"], "无站点数组（格式未识别）")

    def test_fetch_failure_keeps_err(self):
        def boom(url, timeout=15):
            raise RuntimeError("blocked")
        ec.http_get = boom
        out = ec.eval_one({"url": "https://x/a.json"}, BASE)
        self.assertIn("blocked", out["err"])
        self.assertEqual(out["unique"], 0)


if __name__ == "__main__":
    unittest.main()
