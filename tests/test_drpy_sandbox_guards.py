# -*- coding: utf-8 -*-
"""drpy 沙箱的三道防线：依赖没装、整轮全 D0、失败行漏 key。

2026-10-02 实测事故：新 worktree 里 `drpy-sandbox/` 源文件齐、node 也在，唯独
`node_modules`（.gitignore 忽略、要 npm ci 现装）没装。当时守卫只查 host.mjs 与 node
在不在，于是 178 源全部以 `ERR_MODULE_NOT_FOUND` 失败 → 产物整份刷成 D0，还随 PR 合进了
main。更糟的是那条早退分支没带 `key`：store 按 key 入库会全部跳过，而 PR#27 的撤回逻辑
反过来把上一版 105 条真实判定当成「本轮不再报」清掉——一次环境缺失连带抹掉历史结论。
"""
import importlib.util
import json
import os
import subprocess
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import drpy_probe as mod  # noqa: E402


def _row(grade="D0", err=""):
    return {"grade": grade, "err": err, "key": "k"}


class SandboxBrokenTest(unittest.TestCase):
    def test_all_d0_with_module_missing_is_tool_failure(self):
        rows = [_row(err="code: 'ERR_MODULE_NOT_FOUND'") for _ in range(5)]
        self.assertTrue(mod.sandbox_broken(rows))

    def test_all_d0_with_no_json_is_tool_failure(self):
        self.assertTrue(mod.sandbox_broken([_row(err="no-json:TypeError...") for _ in range(4)]))

    def test_mixed_levels_is_a_real_run(self):
        rows = [_row("D2"), _row("D0", "timeout>90s"), _row("D4")]
        self.assertFalse(mod.sandbox_broken(rows))

    def test_all_d0_with_real_site_errors_is_still_recorded(self):
        """真的整批站点死掉（错误各不相同）不能被当成工装故障而拒绝落盘。"""
        rows = [_row("D0", "timeout>90s") for _ in range(6)]
        self.assertFalse(mod.sandbox_broken(rows))

    def test_empty_run_is_not_called_broken(self):
        self.assertFalse(mod.sandbox_broken([]))


class RowShapeTest(unittest.TestCase):
    def test_no_json_branch_still_carries_key(self):
        job = {"key": "drpy_js_188看", "name": "188看[DRPY]", "rule": "./x.js",
               "full": "x.js", "type": ""}
        real = subprocess.run

        def fake(cmd, **kw):
            return real([sys.executable, "-c",
                         "import sys;sys.stderr.write(\"ERR_MODULE_NOT_FOUND\\n\");"
                         "sys.stderr.flush()"], capture_output=True, text=True)
        mod.subprocess.run = fake
        try:
            r = mod.run_one(job, "庆余年")
        finally:
            mod.subprocess.run = real
        self.assertEqual(r.get("key"), job["key"], "失败行也必须带 key，否则入库跳过+撤回误伤")
        self.assertFalse(r["ok"])


class DepsGuardSourceTest(unittest.TestCase):
    def test_guard_checks_node_modules_not_only_host(self):
        path = os.path.join(_ROOT, "scripts", "drpy_probe.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("node_modules", src, "守卫必须覆盖依赖缺失，而不只是 host.mjs/node")
        self.assertIn("sandbox_broken", src)


if __name__ == "__main__":
    unittest.main()
