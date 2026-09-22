"""release_cleanup 决策逻辑单测（P1-2 卫生修复，2026-09-22）。

只测纯决策函数 decide()：白名单外删除、白名单内保留、
adult.json 受限产物按所有者决策永不清理。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from release_cleanup import decide, RETAIN_FOREVER  # noqa: E402


class TestDecide(unittest.TestCase):
    KEEP = ["tvbox.json", "vod.json", "live.json", "short.json", "list.json",
            "status.json", "checks.json", "tvbox-latest.zip"]

    def test_whitelist_assets_kept(self):
        to_delete, to_keep = decide(self.KEEP, self.KEEP)
        self.assertEqual(to_delete, [])
        self.assertEqual(sorted(to_keep), sorted(self.KEEP))

    def test_stale_proxy_assets_deleted(self):
        # 评估报告实测：4 个 _proxy.json 停在 09-19，白名单外 → 全部清理
        stale = ["app_proxy.json", "cms_proxy.json", "csp_proxy.json", "pan_proxy.json"]
        to_delete, _ = decide(self.KEEP + stale, self.KEEP)
        self.assertEqual(to_delete, sorted(stale))

    def test_dated_zips_deleted_after_fixed_name_migration(self):
        # 旧日期名 zip（TVBox接口包_20260920.zip 等）白名单外 → 清理，防逐日膨胀
        old = ["TVBox接口包_20260920.zip", "TVBox接口包_20260921.zip"]
        to_delete, _ = decide(self.KEEP + old, self.KEEP)
        self.assertEqual(to_delete, sorted(old))

    def test_adult_json_never_deleted(self):
        # 用户 2026-09-22 拍板：adult.json 受限产物必须保留，即使不在白名单
        to_delete, to_keep = decide(self.KEEP + ["adult.json"], self.KEEP)
        self.assertNotIn("adult.json", to_delete)
        self.assertIn("adult.json", to_keep)
        self.assertIn("adult.json", RETAIN_FOREVER)

    def test_adult_not_in_whitelist_still_retained(self):
        # 白名单本身不含 adult.json（它不更新、不推广），仅保留不清理
        self.assertNotIn("adult.json", self.KEEP)
        to_delete, _ = decide(self.KEEP, self.KEEP)
        self.assertNotIn("adult.json", to_delete)


if __name__ == "__main__":
    unittest.main()
