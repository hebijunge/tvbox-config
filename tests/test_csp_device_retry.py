# -*- coding: utf-8 -*-
"""残缺块必须被查出来——done_ 标记只看"有没有文件"，不看跑没跑完。

实测（2026-10-02 第四轮）：block 000 只写了 3/40 行就 rc=0 退出（设备上 app_process
被低内存杀掉），按旧逻辑它算"已完成"，剩下 37 个站静默消失。一轮这样能丢掉九成槽位，
而且日志里看不出异常。
"""
import importlib.util
import json
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "csp_device_batch", os.path.join(_ROOT, "csp-device", "csp_device_batch.py"))
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


def _line(i, lvl="G1"):
    return json.dumps({"id": i, "level": lvl, "gates": 1}, ensure_ascii=False)


class MissingJobsTest(unittest.TestCase):
    def test_truncated_block_yields_the_unrun_sites(self):
        jobs = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        text = "\n".join([_line("a"), ""])
        self.assertEqual([j["id"] for j in mod.missing_jobs(jobs, text)], ["b", "c"])

    def test_complete_block_needs_no_retry(self):
        jobs = [{"id": "a"}, {"id": "b"}]
        text = _line("a") + "\n" + _line("b")
        self.assertEqual(mod.missing_jobs(jobs, text), [])

    def test_chinese_and_escaped_ids_match(self):
        jobs = [{"id": "厂长资源-蓝光"}, {"id": '带"引号'}]
        text = _line("厂长资源-蓝光")
        self.assertEqual([j["id"] for j in mod.missing_jobs(jobs, text)], ['带"引号'])

    def test_garbage_lines_do_not_count_as_done(self):
        jobs = [{"id": "a"}]
        self.assertEqual([j["id"] for j in mod.missing_jobs(jobs, "Killed\n")], ["a"])

    def test_empty_inputs_are_safe(self):
        self.assertEqual(mod.missing_jobs([], _line("a")), [])
        self.assertEqual(mod.missing_jobs([{"id": "a"}], None), [{"id": "a"}])
        self.assertEqual(mod.done_ids(""), set())


if __name__ == "__main__":
    unittest.main()
