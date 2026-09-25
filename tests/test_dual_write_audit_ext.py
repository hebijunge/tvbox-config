"""dual_write_audit P1-C 扩展回归：全交付清单 / 状态区分 / 3 连败升级 / 包 manifest。"""

import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
import zipfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "dual_write_audit", os.path.join(_ROOT, "scripts", "dual_write_audit.py"))
dwa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dwa)


class DeliveryListTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _mk(self, rel):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")

    def test_full_delivery_list(self):
        for rel in ("state/vocab/categories.json", "state/vocab/normalization.json",
                    "rules/channel_norm.json", "lives/groups/cctv.m3u",
                    "tvbox.json", "packs/tvbox-latest.zip"):
            self._mk(rel)
        got = dwa.build_delivery_list(self.root)
        self.assertIn("state/vocab/categories.json", got)
        self.assertIn("state/vocab/normalization.json", got)
        self.assertIn("rules/channel_norm.json", got)
        self.assertIn("lives/groups/cctv.m3u", got)
        self.assertIn("tvbox.json", got)
        self.assertIn("packs/tvbox-latest.zip", got)
        # 缺失文件不进清单
        self.assertNotIn("vod.json", got)

    def test_missing_items_skipped(self):
        got = dwa.build_delivery_list(self.root)
        self.assertEqual(got, [])


class StatusTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_mismatch_vs_fetch_failed_inputs(self):
        repo_f = os.path.join(self.root, "tvbox.json")
        open(repo_f, "w").write("a")
        fs_dir = os.path.join(self.root, "fs")
        os.makedirs(fs_dir)
        # 哈希一致 → ok 的素材
        shutil.copy(repo_f, os.path.join(fs_dir, "tvbox.json"))
        self.assertEqual(dwa.sha256_file(repo_f),
                         dwa.sha256_file(os.path.join(fs_dir, "tvbox.json")))
        # 内容不同 → sha256_mismatch 的素材
        open(os.path.join(fs_dir, "other.json"), "w").write("b")
        self.assertNotEqual(dwa.sha256_file(repo_f),
                            dwa.sha256_file(os.path.join(fs_dir, "other.json")))

    def test_zip_manifest_check(self):
        zp = os.path.join(self.root, "pack.zip")
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("a.json", "aaa")
            z.writestr("manifest.json", json.dumps({"entries": [
                {"name": "a.json",
                 "sha256": hashlib.sha256(b"aaa").hexdigest()}]}))
        ok, bad, _n = dwa.check_zip_manifest(zp)
        self.assertEqual((ok, bad), (1, 0))
        # 篡改 entry 哈希 → bad
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("a.json", "aaa")
            z.writestr("manifest.json", json.dumps({"entries": [
                {"name": "a.json", "sha256": "0" * 64}]}))
        ok, bad, _n = dwa.check_zip_manifest(zp)
        self.assertEqual((ok, bad), (0, 1))
        # 无 manifest → bad=-1（显式标注不校验）
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("a.json", "aaa")
        ok, bad, _n = dwa.check_zip_manifest(zp)
        self.assertEqual(bad, -1)


class StreakTests(unittest.TestCase):
    def test_three_consecutive(self):
        rows = [{"date": "2026-09-22", "verdict": "FAIL"},
                {"date": "2026-09-23", "verdict": "FAIL"},
                {"date": "2026-09-24", "verdict": "FAIL"}]
        self.assertEqual(dwa.consecutive_fail_days(rows, "2026-09-25"), 3)

    def test_pass_resets(self):
        rows = [{"date": "2026-09-23", "verdict": "FAIL"},
                {"date": "2026-09-24", "verdict": "PASS"}]
        self.assertEqual(dwa.consecutive_fail_days(rows, "2026-09-25"), 0)

    def test_skipped_day_does_not_break_streak(self):
        rows = [{"date": "2026-09-23", "verdict": "FAIL"}]
        self.assertEqual(dwa.consecutive_fail_days(rows, "2026-09-25"), 1)

    def test_empty_history(self):
        self.assertEqual(dwa.consecutive_fail_days([], "2026-09-25"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
