"""snapshot_rotate 纯决策函数回归（主干只留最新日 + Release 14 天滚动）。"""

import importlib.util
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "snapshot_rotate", os.path.join(_ROOT, "scripts", "snapshot_rotate.py"))
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)


class DecideTests(unittest.TestCase):
    def test_rotate_keeps_only_newest(self):
        days = ["2026-09-23", "2026-09-24", "2026-09-25"]
        tracked = ["2026-09-17", "2026-09-23", "2026-09-24"]
        un, tk = sr.decide(days, tracked)
        self.assertEqual(un, ["2026-09-17", "2026-09-23", "2026-09-24"])
        self.assertEqual(tk, ["2026-09-25"])  # 磁盘最新日未被跟踪 → 应补 add -f

    def test_rotate_tracks_new_day(self):
        days = ["2026-09-25", "2026-09-26"]
        tracked = ["2026-09-25"]
        un, tk = sr.decide(days, tracked)
        self.assertEqual(un, ["2026-09-25"])
        self.assertEqual(tk, ["2026-09-26"])

    def test_rotate_empty_disk_noop(self):
        self.assertEqual(sr.decide([], ["2026-09-24"]), ([], []))

    def test_asset_date(self):
        self.assertEqual(sr.asset_date("snapshot-20260917.zip"), "2026-09-17")
        self.assertIsNone(sr.asset_date("tvbox.json"))
        self.assertIsNone(sr.asset_date("snapshot-bad.zip"))

    def test_release_prune(self):
        assets = ["snapshot-20260910.zip", "snapshot-20260912.zip",
                  "snapshot-20260913.zip", "snapshot-20260924.zip", "tvbox.json"]
        to_del, keep = sr.decide_release_prune(assets, "2026-09-13")
        self.assertEqual(to_del, ["snapshot-20260910.zip", "snapshot-20260912.zip"])
        self.assertEqual(keep, ["snapshot-20260913.zip", "snapshot-20260924.zip",
                                "tvbox.json"])

    def test_release_prune_retain(self):
        assets = ["snapshot-20260910.zip"]
        to_del, _k = sr.decide_release_prune(assets, "2026-09-13",
                                             retain=("snapshot-20260910.zip",))
        self.assertEqual(to_del, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
