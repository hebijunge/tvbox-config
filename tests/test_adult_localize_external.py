"""成人专供线补跑本地化的耦合测试。

2026-10-03 用户报出 `adult.json` 里 23 个站点的 `jar` 字段仍是 https:// 远端 URL
（例如 `gitee.com/lwlxh/tvhome/raw/master/o.jar`）；对应文件**已在
deps/localized/858cb4948d-o.jar 落库、manifest 双登记**，只是主链本地化在
`adult_excluded_sites` 从 kept_sites 摘走之后才跑（line 5569 → 5736），成人线
0 处被改写。修复 = 单独给 adult 补一遍。这里钉住"补跑被调用"与"空列表短路"。
"""

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import fetch_merge as fm  # noqa: E402


class TestLocalizeExcludedAdultSites(unittest.TestCase):
    def test_empty_short_circuits(self):
        r = fm.localize_excluded_adult_sites([])
        self.assertEqual(r, {"skipped": True})

    def test_wraps_and_calls_both_stages(self):
        # 关键：必须把 sites 包成 {"sites": ...} 传给两个 stage 函数（它们都按
        # "cfg 里的 sites 字段"遍历）；否则传 list 会直接 AttributeError 或静默不跑
        sites = [{"key": "youshou", "jar": "https://gitee.com/x/o.jar"}]
        with mock.patch.object(fm, "localize_external_refs",
                                return_value={"downloaded": 1, "rewritten": 1}) as loc, \
             mock.patch.object(fm, "prune_unlocalized_jars",
                                return_value={"checked": 1, "pruned": 0}) as pr:
            r = fm.localize_excluded_adult_sites(sites)
        self.assertEqual(loc.call_count, 1)
        self.assertEqual(pr.call_count, 1)
        # 传给两个 stage 的应该是同一个 wrap，两次调用之间 sites 被就地改写
        arg = loc.call_args[0][0]
        self.assertIsInstance(arg, dict)
        self.assertEqual(arg["sites"], sites)
        self.assertEqual(pr.call_args[0][0], arg,
                        "prune 必须在同一份 wrap 上跑，才能看到 localize 的改写结果")
        self.assertEqual(r.get("rewritten"), 1)
        self.assertEqual(r.get("pruned_unlocalized"), 0)

    def test_mutates_original_sites_in_place(self):
        # 端到端确认：改写在原 sites 列表元素上生效（不是新列表），
        # 因为 main() 之后会用 `adult_excluded_sites` 这份引用去派生 adult.sites。
        sites = [{"key": "y", "jar": "./deps/never-exists/x.jar"}]
        # 用真的 prune_unlocalized_jars，localize 用 mock 让它 no-op（不动 sites）
        with mock.patch.object(fm, "localize_external_refs",
                                side_effect=lambda cfg: {}):
            fm.localize_excluded_adult_sites(sites)
        self.assertNotIn("jar", sites[0],
                        "不存在的相对路径 jar 应被 prune_unlocalized_jars 撤走")


if __name__ == "__main__":
    unittest.main()
