"""daily.yml 里"大小写冲突每日消解"步骤存在性测试。

2026-10-03 PR#41 一次性 `git rm --cached iptv.m3u` 只清了当时索引；下一轮 daily
fetch-merge 又拉小写 URL、`resolve_dep_paths` 只看**本次 entries** 里的撞名，
当天没同时拉大写那条 → lp 落回原名、`git add` 把 entry 又加回来 → PR#42/#43
windows-path-check 复活 FAIL。治本 = 把 `fix_case_collisions.py --apply` 加进
daily.yml，在 dep_gc 之后、入库之前每日扫一遍消解。这条测试防的是"以后有人
手动删了这个步骤、windows-path-check 又开始每天 FAIL 却找不到原因"。
"""

import os
import re
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(_ROOT, ".github", "workflows", "daily.yml")


class TestDailyHasCaseCollisionStep(unittest.TestCase):
    def setUp(self):
        with open(DAILY, encoding="utf-8") as f:
            self.txt = f.read()

    def test_case_collision_apply_step_present(self):
        # 每日消解大小写冲突这一步必须在
        self.assertIn("fix_case_collisions.py --apply", self.txt,
                      "daily.yml 必须调 fix_case_collisions --apply；"
                      "没有它会每日复活 windows-path-check FAIL")

    def test_step_after_dep_gc_before_ingest(self):
        # 顺序：dep_gc prune-manifest → fix_case_collisions → 入库
        i_gc = self.txt.find("dep_gc.py --prune-manifest")
        i_fix = self.txt.find("fix_case_collisions.py --apply")
        i_ing = self.txt.find("入库（接口")
        self.assertGreater(i_gc, -1, "dep_gc prune-manifest 步骤缺失")
        self.assertGreater(i_fix, i_gc,
                           "fix_case_collisions 必须在 dep_gc 之后："
                           "账本瘦身后剩下的记录才是当前有效引用")
        self.assertGreater(i_ing, i_fix,
                           "fix_case_collisions 必须在入库之前："
                           "索引要在 DB ingest 前定稿")

    def test_step_declared_with_continue_on_error(self):
        # 与 dep_gc 同规格：continue-on-error，脚本异常不阻断 daily 主链
        m = re.search(
            r"(- name:[^\n]*大小写冲突[^\n]*\n(?:\s+#[^\n]*\n)+\s+continue-on-error:\s*true\s+run:\s*python scripts/fix_case_collisions\.py --apply)",
            self.txt)
        self.assertIsNotNone(m,
                              "fix_case_collisions 步骤应有 continue-on-error: true，"
                              "与 dep_gc 步骤同规格")


if __name__ == "__main__":
    unittest.main()
