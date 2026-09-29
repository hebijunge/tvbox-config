"""主产物内部字段剥离回归（2026-09-29 决策：健康标注不进主产物）。

覆盖：
  · _strip_internal_fields 递归剥净 _ 前缀字段（含嵌套 list/dict）
  · 不再有 _HEALTH_KEEP 白名单 / attach_site_health 打标函数（体积护栏：
    三个健康字段曾让订阅入口的 tvbox.json 从 1.29MB 涨到 1.67MB）

触网用例另放 tests_net/，本文件纯逻辑必过。
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import fetch_merge as fm  # noqa: E402


class TestProductStrip(unittest.TestCase):
    def test_strips_all_underscore_fields(self):
        doc = {
            "spider": "./deps/x.jar",
            "sites": [
                {"key": "k1", "name": "n", "_health": "healthy",
                 "_checked_at": "2026-09-29", "_latency_ms": 120,
                 "_origin": "https://github.com/a/b",
                 "ext": {"headers": {"_internal": 1, "User-Agent": "ua"}}},
            ],
            "parses": [{"_probe_x": 1, "url": "u"}],
        }
        out = fm._strip_internal_fields(doc)
        site = out["sites"][0]
        self.assertEqual(sorted(site), ["ext", "key", "name"])
        self.assertEqual(sorted(site["ext"]["headers"]), ["User-Agent"])
        self.assertEqual(sorted(out["parses"][0]), ["url"])
        self.assertEqual(out["spider"], "./deps/x.jar")

    def test_no_health_whitelist_left(self):
        # 健康结论走 exports/all.json + state/tvbox.db，主产物不携带
        self.assertFalse(hasattr(fm, "_HEALTH_KEEP"))
        self.assertFalse(hasattr(fm, "attach_site_health"))


if __name__ == "__main__":
    unittest.main()
