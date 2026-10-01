# -*- coding: utf-8 -*-
"""5f py 探针的结构判定与"别自造误判"回归。

钉住两类真踩过的坑：
  * 只读 600KB → 1.5-2.3MB 的大插件被切断，报出假的 unterminated string literal（3 例）；
    不吃 BOM → 行首 U+FEFF 又算一次假语法错（1 例）。判死前必须先排除自己。
  * 取不到文件 / 认不出 Spider 类一律 unknown，不给 dead：PC 取不到网盘直链不代表
    手机取不到（本机 189 个 py 源里 47 个属这类）。
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import probe_py as pp   # noqa: E402
import store           # noqa: E402

GOOD = '''# -*- coding: utf-8 -*-
from base.spider import Spider


class Spider(Spider):
    def init(self, extend=""):
        pass

    def homeContent(self, filter):
        return {}

    def categoryContent(self, tid, pg, filter, extend):
        return {}

    def detailContent(self, ids):
        return {}

    def searchContent(self, key, quick):
        return {}

    def playerContent(self, flag, url, vip):
        return {}
'''


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        os.makedirs(os.path.join(self.repo, "deps", "o"))
        self.addCleanup(self.tmp.cleanup)
        self.url = "https://host/o/py_good.py"
        with open(os.path.join(self.repo, "deps", "o", "py_good.py"), "w", encoding="utf-8") as f:
            f.write(GOOD)
        with open(os.path.join(self.repo, "deps", "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"o|" + self.url: {"url": self.url, "local": "deps/o/py_good.py"}}, f)
        self.idx = pp.load_manifest_index(self.repo)

    def test_remote_py_resolves_through_ledger(self):
        fp, note = pp.local_py_file({"api": self.url}, self.repo, self.idx)
        self.assertTrue(fp and fp.endswith("py_good.py"), "远程直链要顺着 deps 账本找到本地副本")
        self.assertEqual(note, "")

    def test_missing_from_ledger_is_recorded_not_guessed(self):
        fp, note = pp.local_py_file({"api": "https://pan.other/x.py"}, self.repo, self.idx)
        self.assertEqual(fp, "")
        self.assertIn("账本无记录", note)

    def test_good_spider_is_p4_and_degraded(self):
        r = pp.probe_one({"key": "k", "name": "好源", "api": self.url}, self.repo, self.idx)
        self.assertEqual(r["level"], "P4")
        self.assertEqual(store.classify(r["level"], r.get("ok")), "degraded")

    def test_incomplete_entries_are_p3(self):
        with open(os.path.join(self.repo, "deps", "o", "py_part.py"), "w", encoding="utf-8") as f:
            f.write(GOOD.replace("    def playerContent(self, flag, url, vip):\n        return {}\n", ""))
        idx = pp.load_manifest_index(self.repo)
        r = pp.probe_one({"api": "deps/o/py_part.py"}, self.repo, idx)
        self.assertEqual(r["level"], "P3")
        self.assertIn("playerContent", r["methods_missing"])
        self.assertEqual(store.classify("P3"), "degraded")

    def test_no_class_is_unknown_not_dead(self):
        with open(os.path.join(self.repo, "deps", "o", "noclass.py"), "w", encoding="utf-8") as f:
            f.write("def main():\n    return 1\n")
        r = pp.probe_one({"api": "deps/o/noclass.py"}, self.repo, pp.load_manifest_index(self.repo))
        self.assertEqual(r["level"], "P2")
        self.assertEqual(store.classify("P2"), "unknown", "认不出入口不能算站点死")

    def test_missing_file_is_unknown_not_dead(self):
        r = pp.probe_one({"api": "https://pan.other/x.py"}, self.repo, self.idx)
        self.assertEqual(r["level"], "P0")
        self.assertEqual(store.classify("P0"), "unknown")


class TruncationRegressionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        os.makedirs(os.path.join(self.repo, "deps"))
        self.addCleanup(self.tmp.cleanup)

    def _probe_text(self, text, name="big.py", bom=False):
        p = os.path.join(self.repo, "deps", name)
        raw = text.encode("utf-8")
        if bom:
            raw = bytes([0xEF, 0xBB, 0xBF]) + raw
        with open(p, "wb") as f:
            f.write(raw)
        return pp.probe_one({"api": "deps/" + name}, self.repo, {})

    def test_two_megabyte_plugin_is_not_a_false_syntax_error(self):
        body = GOOD + "\n# " + ("x" * 200) * 11000          # >2MB 的合法源码
        r = self._probe_text(body)
        self.assertEqual(r["level"], "P4", "整读之前先截断会造出假 SyntaxError")

    def test_bom_prefixed_plugin_is_not_a_false_syntax_error(self):
        r = self._probe_text(GOOD, name="bom.py", bom=True)
        self.assertEqual(r["level"], "P4")

    def test_genuine_syntax_error_is_dead(self):
        r = self._probe_text(GOOD + "\n    def broken(:\n", name="bad.py")
        self.assertEqual(r["level"], "P1")
        self.assertEqual(store.classify("P1"), "dead")


class WiringCase(unittest.TestCase):
    def test_probe_priority_sits_between_deep_and_shallow(self):
        self.assertEqual(store.probe_priority("py_probe.json"), 2)
        self.assertLess(store.probe_priority("probe/py_probe.json"),
                        store.probe_priority("csp_probe.json"),
                        "静态结构判定不能覆盖真机五关结论")

    def test_is_py_site_catches_api_and_ext(self):
        self.assertFalse(pp.is_py_site({"api": "py_x"}), "api 只写 py_x 不含文件名后缀，不能算 py 源")
        self.assertTrue(pp.is_py_site({"api": "https://h/a.py"}))
        self.assertTrue(pp.is_py_site({"api": "./deps/x/py_a.py", "ext": ""}))
        self.assertTrue(pp.is_py_site({"api": "py", "ext": "deps/o/x.py"}))
        self.assertFalse(pp.is_py_site({"api": "csp_Home", "ext": "http://x/api.php/vod"}))


if __name__ == "__main__":
    unittest.main()
