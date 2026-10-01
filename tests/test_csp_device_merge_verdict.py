"""真机合并的取证口径：设备只能证明「跑到第几关」，证不了「死」。

为什么要钉这条：v1 runner 的 CLASSPATH 里没挂宿主 apk，spider 接口找不到 → 整批
ClassNotFoundException 写成 C0，802 个假死就这么进了产物（一半连 evidence 都是空的）。
用户口径很明确：不能拿工装能力问题冒充站点死。所以
  * 设备行里 C0 / G0 / stub 家族一律不写等级；
  * 产物里已存在的无静态证据 C0 要在合并时退回未测，否则 plan 会把它们当"已有结论"跳过，
    假死永远洗不掉。
"""
import importlib.util
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "csp_device_batch", os.path.join(_ROOT, "csp-device", "csp_device_batch.py"))
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

verdict = mod.device_verdict


class DeviceVerdictTest(unittest.TestCase):
    def test_gates_become_level(self):
        self.assertEqual(verdict({"level": "G3", "gates": 3}, "XYQHiker"), ("C3", ""))

    def test_zero_gate_load_is_not_a_verdict(self):
        self.assertEqual(verdict({"level": "G0", "gates": 0}, "xBPQ"), (None, "g0"))

    def test_class_load_failure_is_not_a_death_sentence(self):
        """设备侧 C0 = 我们的 DexClassLoader 没把类跑起来，判不起死。"""
        self.assertEqual(verdict({"level": "C0", "err": "ClassNotFoundException"}, "NG"),
                         (None, "load"))

    def test_stub_family_never_recorded(self):
        for cls in ("CatchcatAmns", "SomeGuardProxy"):
            self.assertEqual(verdict({"level": "G5", "gates": 5}, cls)[0], None, cls)

    def test_stub_check_beats_level(self):
        """stub 即便真机跑出关卡也不收：复现不了宿主注入链，结论不可迁移。"""
        self.assertEqual(verdict({"level": "G2", "gates": 2}, "FooAmns"), (None, "stub"))

    def test_unknown_level_is_recorded_for_retest(self):
        self.assertEqual(verdict({"level": "C?"}, "Bar"), ("C?", ""))
        self.assertEqual(verdict({}, "Bar"), ("C?", ""))


class UntrustedC0Test(unittest.TestCase):
    def test_bare_c0_is_purged(self):
        self.assertTrue(mod.untrusted_c0({"level": "C0", "evidence": {}}))
        self.assertTrue(mod.untrusted_c0({"level": "C0"}))

    def test_device_c0_is_purged_too(self):
        self.assertTrue(mod.untrusted_c0({"level": "C0",
                                          "evidence": {"device": "app-process-five-gate"}}))

    def test_static_c0_survives(self):
        row = {"level": "C0", "evidence": {"static": "class-absent-in-local-jar-pool"}}
        self.assertFalse(mod.untrusted_c0(row))

    def test_non_c0_rows_untouched(self):
        for lvl in ("C1", "C5", "C?"):
            self.assertFalse(mod.untrusted_c0({"level": lvl}), lvl)


if __name__ == "__main__":
    unittest.main()
