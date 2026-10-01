# -*- coding: utf-8 -*-
"""csp 静态 C0 判定的口径闸门（全 mock，不连网、不跑 dexdump）。

2026-10-01 踩过的坑：早期版本拿「某一个 jar 里没有」当「所有 jar 里没有」，还把
站点首页 HTML 当 jar 解，一次造出 824 个假 C0。收紧后的三条规则必须由测试钉住：
  1) 解析不出类的 jar 一律记 err，不给空清单（空清单=全场判死）；
  2) 真机给过 C1-C5 的站不因本地池缺类而降级；
  3) 池子太小 / 报告过期 / 报告没有 pool_files / 该站自带 jar 没读到 → 都不写判死。
"""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import csp_jar_scan as scan          # noqa: E402
import csp_static_merge as merge     # noqa: E402


def _report(**over):
    rep = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "pool": {"files": 40, "parsed": 30, "failed": 10},
           "wanted": 3,
           "classes": {},
           "absent": ["Dead1", "Conf", "UnknownJar"],
           "pool_files": ["deps/x.jar"]}
    rep.update(over)
    return rep


CONFIG = {"spider": "https://cdn.example/x.jar",
          "sites": [{"key": "a", "name": "A 站", "api": "csp_Dead1"},
                    {"key": "b", "name": "B 站", "api": "csp_Conf", "ext": "./jar/x.jar"},
                    {"key": "c", "name": "C 站", "api": "csp_UnknownJar",
                     "ext": "https://other.example/y.jar"}]}
MANIFEST = {"k1|https://cdn.example/x.jar":
            {"url": "https://cdn.example/x.jar", "local": "deps/x.jar"},
            "k2|https://other.example/y.jar":
            {"url": "https://other.example/y.jar", "local": "deps/missing.jar"}}
PROBE = {"generated_at": "2026-09-28T00:00:00", "summary": {},
         "sites": [{"key": "b", "name": "B 站", "kind": "csp", "cls": "Conf",
                    "level": "C1", "err": "", "probed_at": "2026-09-28T00:00:00"}]}


class MergeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.cfg = os.path.join(d, "tvbox.json")
        self.probe = os.path.join(d, "csp_probe.json")
        self.manifest = os.path.join(d, "manifest.json")
        self.scan = os.path.join(d, "csp_jar_scan.json")
        for path, doc in ((self.cfg, CONFIG), (self.probe, PROBE),
                          (self.manifest, MANIFEST), (self.scan, _report())):
            json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        self._patch = mock.patch.object(merge, "SCAN", self.scan)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.addCleanup(self.tmp.cleanup)
        cwd = os.getcwd()
        os.chdir(d)                       # norm()/relpath 以仓库根为基准，测试里以 tmp 为根
        self.addCleanup(lambda: os.chdir(cwd))

    def _write_scan(self, **over):
        json.dump(_report(**over), open(self.scan, "w", encoding="utf-8"), ensure_ascii=False)

    def _run(self):
        rc = merge.merge(config=self.cfg, probe_path=self.probe, manifest=self.manifest)
        doc = json.load(open(self.probe, encoding="utf-8"))
        return rc, {s["key"]: s for s in doc["sites"]}

    def test_absent_with_readable_jar_becomes_c0(self):
        rc, by = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(by["a"]["level"], "C0")
        self.assertEqual(by["a"]["evidence"]["static"], "class-absent-in-local-jar-pool")

    def test_device_verdict_is_not_downgraded(self):
        rc, by = self._run()
        self.assertEqual(by["b"]["level"], "C1", "真机判过能跑的站不能因为本地池缺类而死")

    def test_unreadable_own_jar_is_left_unknown(self):
        _, by = self._run()
        self.assertNotIn("c", by, "自带的 jar 没读到过，证据不足，不能判死")

    def test_tiny_pool_refuses_to_write(self):
        self._write_scan(pool={"files": 40, "parsed": 3, "failed": 37},
                         pool_files=["deps/x.jar"])
        rc, by = self._run()
        self.assertEqual(rc, 3)
        self.assertNotIn("a", by)

    def test_stale_report_refuses_to_write(self):
        self._write_scan(generated_at=(datetime.now() - timedelta(days=30))
                         .strftime("%Y-%m-%dT%H:%M:%S"))
        rc, by = self._run()
        self.assertEqual(rc, 4)
        self.assertNotIn("a", by)

    def test_report_without_pool_files_refuses_to_write(self):
        self._write_scan(pool_files=[])
        rc, by = self._run()
        self.assertEqual(rc, 5)
        self.assertNotIn("a", by)


class DexScanCase(unittest.TestCase):
    def test_non_zip_yields_err_not_empty_class_list(self):
        with tempfile.TemporaryDirectory() as d:
            junk = os.path.join(d, "home.html")
            with open(junk, "wb") as f:
                f.write(b"<html>not a jar</html>" * 100)
            res = scan.dex_classes("dexdump-not-used", junk, os.path.join(d, "t.dex"))
            self.assertTrue(res.get("err"), "解不开必须报错，空 classes 会被下游判成全场缺席")

    def test_zip_without_dex_yields_err(self):
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "nojar.jar")
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("readme.txt", "x" * 10)
            res = scan.dex_classes("dexdump-not-used", p, os.path.join(d, "t.dex"))
            self.assertEqual(res.get("err"), "no-dex-entry")


if __name__ == "__main__":
    unittest.main()
