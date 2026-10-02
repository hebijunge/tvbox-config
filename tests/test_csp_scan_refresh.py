# -*- coding: utf-8 -*-
"""jar 扫描报告的时效：报告比 deps 树旧 = 白丢真机覆盖。

起因（2026-10-02 实测）：`WORK/csp_jar_scan.json` 还是 2026-10-01T07:48 的，而
`deps/auto/<随机>/jar/*` 这类本地化路径每天换目录——报告里的老路径在盘上已不存在，
build_jobs 把 **90 个站**当"本地缺 jar"跳过（同类 jar 当天就在别的目录里）。
重扫后同一批站变成"本地缺 jar 0"。所以 plan/push 前必须按需刷新报告。

CI 上没有 dexdump（扫描要 Android build-tools）：刷新失败要沿用上轮报告并说清楚，
不能因为刷不动就把上轮的好数据覆写成空报告。
"""
import datetime
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "csp_device_batch_refresh", os.path.join(_ROOT, "csp-device", "csp_device_batch.py"))
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


class ScanAgeTest(unittest.TestCase):
    def setUp(self):
        self.old_work = mod.WORK
        mod.WORK = tempfile.mkdtemp(prefix="csp-scan-")

    def tearDown(self):
        # 必须先删临时目录再恢复模块全局，顺序反了就会删掉真实 WORK。
        shutil.rmtree(mod.WORK, ignore_errors=True)
        mod.WORK = self.old_work

    def write(self, stamp):
        json.dump({"generated_at": stamp, "classes": {}},
                  io.open(os.path.join(mod.WORK, "csp_jar_scan.json"), "w", encoding="utf-8"))

    def test_no_report_counts_as_stale(self):
        self.assertGreater(mod.scan_age_h(), 900)

    def test_broken_report_counts_as_stale(self):
        io.open(os.path.join(mod.WORK, "csp_jar_scan.json"), "w", encoding="utf-8").write("{坏")
        self.assertGreater(mod.scan_age_h(), 900)

    def test_fresh_report_age(self):
        now = datetime.datetime(2026, 10, 2, 12, 0, 0)
        self.write("2026-10-02T11:30:00")
        self.assertAlmostEqual(mod.scan_age_h(now), 0.5, places=3)

    def test_yesterday_report_is_28h(self):
        now = datetime.datetime(2026, 10, 2, 12, 0, 0)
        self.write("2026-10-01T07:48:48")
        self.assertGreater(mod.scan_age_h(now), 28)
        self.assertLess(mod.scan_age_h(now), 29)


class EnsureScanTest(unittest.TestCase):
    def setUp(self):
        self.old_work, self.old_sh = mod.WORK, mod.sh
        mod.WORK = tempfile.mkdtemp(prefix="csp-scan-")

    def tearDown(self):
        # 必须先删临时目录再恢复模块全局：反过来的话 rmtree 拿到的就是真实 WORK，
        # 2026-10-02 就这么把真机工装目录 csp-harness 整个删过一次。
        shutil.rmtree(mod.WORK, ignore_errors=True)
        mod.WORK = self.old_work
        mod.sh = self.old_sh

    def test_fresh_report_does_not_rescan(self):
        called = []
        mod.sh = lambda cmd: called.append(cmd) or (0, "")
        json.dump({"generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                   "classes": {}},
                  io.open(os.path.join(mod.WORK, "csp_jar_scan.json"), "w", encoding="utf-8"))
        msg = mod.ensure_scan()
        self.assertIn("新鲜", msg)
        self.assertEqual([], called, "报告新鲜就不该重扫（一次 25s+）")

    def test_stale_report_triggers_rescan(self):
        called = []

        def fake(cmd):
            called.append(cmd)
            return 0, "[1361/1361] 池：301/1361 解析成功"
        mod.sh = fake
        json.dump({"generated_at": "2026-10-01T07:48:48", "classes": {}},
                  io.open(os.path.join(mod.WORK, "csp_jar_scan.json"), "w", encoding="utf-8"))
        msg = mod.ensure_scan()
        self.assertIn("已刷新", msg)
        self.assertEqual(1, len(called))
        self.assertIn("csp_jar_scan.py", " ".join(called[0]))

    def test_scan_failure_keeps_previous_report(self):
        mod.sh = lambda cmd: (2, "缺 dexdump：设 DEXDUMP 指向 android build-tools/dexdump(.exe)")
        json.dump({"generated_at": "2026-10-01T07:48:48", "classes": {}},
                  io.open(os.path.join(mod.WORK, "csp_jar_scan.json"), "w", encoding="utf-8"))
        msg = mod.ensure_scan()
        self.assertIn("沿用上轮报告", msg)
        self.assertTrue(os.path.exists(os.path.join(mod.WORK, "csp_jar_scan.json")),
                        "刷新失败不能把上轮好数据覆写掉")


if __name__ == "__main__":
    unittest.main(verbosity=2)
