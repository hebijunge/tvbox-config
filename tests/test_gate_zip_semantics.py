"""回归守卫：adult_leak_check.scan_zip 语义统一（2026-09-26 第 3 轮整改）。

三个语义点，各自对应一类实测伪阳性（本地实包 438 处 zip 命中定位）：
  1. rules/ 与 state/vocab/ 前缀条目跳过——词表本体打包进 zip 不改变其性质，
     逐字扫描只会命中词表自己（实测 rules 202 + state 205 处）。
  2. json 条目全字段扫描传白名单——「白名单命中不计一票否决」不因载体是 zip
     而失效（实测 ext 密文 blob mmz/1024 磁盘侧 guarded、zip 侧却计违规）。
  3. main 的 packs 双扫去重（gate_criteria dirs 含 packs 时 438×2 伪计数）。
"""

import io
import json
import os
import sys
import unittest
import zipfile

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_TESTS_DIR, "..", "scripts")
sys.path.insert(0, _SCRIPTS)

import adult_leak_check as g  # noqa: E402


def _mkzip(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for nm, txt in entries.items():
            z.writestr(nm, txt)


class TestScanZipSemantics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)) + "/../../.tmp-test-zip")
        os.makedirs(self.tmp, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vocab_entries_skipped(self):
        p = os.path.join(self.tmp, "a.zip")
        _mkzip(p, {
            "rules/adult_host_blacklist.json": json.dumps({"x": ["jable.tv", "pornhub.com"]}),
            "state/vocab/categories.json": json.dumps({"adult": ["18+"]}),
        })
        hits = []
        g.scan_zip(p, hits)
        self.assertEqual(hits, [])

    def test_real_leak_still_caught(self):
        p = os.path.join(self.tmp, "b.zip")
        _mkzip(p, {
            "deps/evil.json": json.dumps({"type_name": "AV淫水机"}),
        })
        hits = []
        g.scan_zip(p, hits)
        self.assertEqual(len(hits), 1)
        self.assertIn("porn_kw", hits[0]["rule"])

    def test_whitelist_guarded_inside_zip(self):
        p = os.path.join(self.tmp, "c.zip")
        blob = "A" * 60 + "mmz" + "B" * 20   # 形态符合白名单 blob 规则的密文串
        _mkzip(p, {"tvbox.json": json.dumps({"sites": [{"ext": blob}]})})
        wl = g._whitelist_res(None)  # 无文件 → 空
        # 直接构造与 state/adult_leak_whitelist.txt 等价的白名单
        import re
        wl = [re.compile(r"^[A-Za-z0-9+/=]{50,}$", re.IGNORECASE)]
        hits = []
        g.scan_zip(p, hits, wl)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["kind"], "guarded")
        # 无白名单时计为真实命中（word）——口径差异可见
        hits2 = []
        g.scan_zip(p, hits2)
        self.assertEqual(hits2[0]["kind"], "word")


if __name__ == "__main__":
    unittest.main()
