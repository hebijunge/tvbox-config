"""回归守卫：adult.json 每日产出并提交（「不声明」模式）的行为约束。

所有者 2026-09-22 指令：
- adult.json 每天随 daily 聚合产出并提交更新到仓库（不得只写本地留档跑完即弃）；
- 「只是不声明」：不进 Release 附件白名单 / GitHub Pages / 导航页，不在 README 与日报声明。
"""

import ast
import os
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FETCH_MERGE = os.path.join(_TESTS_DIR, "..", "scripts", "fetch_merge.py")


def _load_tree():
    with open(FETCH_MERGE, encoding="utf-8") as f:
        return ast.parse(f.read())


def _is_open_call(node, filename):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "open" and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == filename)


class AdultDailyOutputTest(unittest.TestCase):
    def setUp(self):
        self.tree = _load_tree()
        with open(FETCH_MERGE, encoding="utf-8") as f:
            self.source = f.read()

    def _with_nodes_opening(self, filename):
        """返回所有打开 filename 的 With 节点及其祖先链（含根）。"""
        hits, stack = [], []

        def visit(node):
            stack.append(node)
            if isinstance(node, ast.With):
                for item in node.items:
                    if _is_open_call(item.context_expr, filename):
                        hits.append(list(stack))
            for child in ast.iter_child_nodes(node):
                visit(child)
            stack.pop()

        visit(self.tree)
        return hits

    def test_adult_json_write_not_gated_by_publish_switch(self):
        """adult.json 的写入不得嵌在 `if PUBLISH_ADULT` 分支里（必须每天无条件产出）。"""
        hits = self._with_nodes_opening("adult.json")
        self.assertTrue(hits, "fetch_merge.py 里找不到 adult.json 的写入点")
        for ancestors in hits:
            for node in ancestors:
                if isinstance(node, ast.If):
                    self.assertNotIn(
                        "PUBLISH_ADULT", ast.unparse(node.test),
                        "adult.json 写入被 PUBLISH_ADULT 条件门控，违反每日产出要求")

    def test_main_products_still_exclude_adult_by_default(self):
        """默认模式必须继续把成人站点从主产物剔除（不声明 ≠ 混进主产物）。"""
        found = any(
            isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
            and isinstance(node.test.operand, ast.Name)
            and node.test.operand.id == "PUBLISH_ADULT"
            for node in ast.walk(self.tree))
        self.assertTrue(found, "找不到 `if not PUBLISH_ADULT` 主产物剔除分支")

    def test_no_workbuddy_archive_written(self):
        """不再写 .workbuddy 本地留档（避免被 pack_local 收进 Release 附件 zip）。"""
        self.assertNotIn("adult.local.json", self.source)
        self.assertNotIn("_dump_adult_local", self.source)
        self.assertNotIn("ADULT_LOCAL_PATH", self.source)

    def test_publish_switch_defaults_off(self):
        """PUBLISH_ADULT 默认必须为关（默认模式 = 不声明模式，主产物不含成人站点）。"""
        self.assertNotIn('os.environ.get("PUBLISH_ADULT", "1")', self.source)


if __name__ == "__main__":
    unittest.main()
