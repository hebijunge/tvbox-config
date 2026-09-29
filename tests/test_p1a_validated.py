#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-A 冒烟：validated.json 读写往返 + record_result 历史 + 跨日衰减 + 规范键。

重写说明（2026-09-29）：原文件是「模块级脚本 + try/except 打印 SMOKE FAIL」的形态，
`python -m unittest discover` 只关心模块能否 import，断言失败被吞成一行打印，**套件恒绿**；
而首个断言 `len(st) == 694` 早在账本涨到 805 条时就失败，后面 4 步（record_result、
跨日衰减、飞书桥接、规范键）从未执行过。改成真 unittest 用例，并把「依赖真实账本具体条数」
的断言一律换成形状断言——上游清单每日变化，硬编码数字必然腐坏。

这些用例会改写真实账本 state/validated.json：setUp 备份、cleanup 无条件还原。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import validated_state as vs  # noqa: E402
import fetch_merge as fm  # noqa: E402

REAL = os.path.join(_ROOT, "state", "validated.json")
RETEST_FIXTURE = "../retest_20260925.json"  # workdir 外部的复测样本，缺失则桥接用空输入


class TestP1AValidated(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="p1a_validated_")
        self._bak = os.path.join(self._dir, "validated.json")
        shutil.copy(REAL, self._bak)
        self.addCleanup(self._restore)

    def _restore(self):
        shutil.copy(self._bak, REAL)
        shutil.rmtree(self._dir, ignore_errors=True)

    def _fake(self, doc, name, days):
        """塞一个假条目，给它连续 days 天从 09-18 起的失败历史。"""
        ent = doc["sources"].setdefault(name, {"name": name})
        ent["history"] = {"2026-09-%02d" % (17 + i): "unavailable"
                          for i in range(1, days + 1)}
        return ent

    def test_load_state_shape(self):
        st = fm.load_state()
        self.assertTrue(st, "validated.json 的 sources 不应为空")
        self.assertTrue(all(isinstance(v, dict) for v in st.values()))

    def test_record_result_ckey_and_history(self):
        st = fm.load_state()
        st["p1a_selftest"] = {"name": "p1a_selftest"}
        url = ("https://ghproxy.net/https://raw.githubusercontent.com"
               "/P1A/selftest/main/cfg.json")
        self.assertEqual(fm.record_result(st, "p1a_selftest", False, [], url=url),
                         "failing")
        ent = st["p1a_selftest"]
        self.assertEqual(ent["ckey"],
                         "raw.githubusercontent.com/P1A/selftest/main/cfg.json")
        self.assertEqual(ent["history"].get(vs.today_bj()), "unavailable")
        fm.save_state(st)
        self.assertIn("p1a_selftest", vs.load_validated()["sources"])

    def test_decay_out_watch_and_recover(self):
        doc = vs.load_validated()
        out_ent = self._fake(doc, "p1a_selftest_out", 7)
        vs.apply_decay(doc)
        self.assertEqual(out_ent["decay"]["stage"], "out")
        self.assertTrue(out_ent["decayed"])

        watch_ent = self._fake(doc, "p1a_selftest_watch", 3)
        vs.apply_decay(doc)
        self.assertEqual(watch_ent["decay"]["stage"], "watch")
        self.assertFalse(watch_ent.get("decayed"))

        stages = {}
        for x in doc["sources"].values():
            s = (x.get("decay") or {}).get("stage", "active")
            stages[s] = stages.get(s, 0) + 1
        self.assertEqual(len(vs.active_sources(doc)), stages.get("active", 0))
        self.assertEqual(sum(stages.values()), len(doc["sources"]))

        # 回捞：当日通过一次即回到 active
        watch_ent["history"][vs.today_bj()] = "fully"
        vs.apply_decay(doc)
        self.assertEqual(watch_ent["decay"]["stage"], "active")
        self.assertFalse(watch_ent.get("decayed"))

    def test_bridge_migrate_keeps_schema(self):
        rows = []
        if os.path.exists(RETEST_FIXTURE):
            with open(RETEST_FIXTURE, encoding="utf-8") as f:
                rows = [{"name": r["name"], "url": r["url"], "level": r["level"],
                         "date": "2026-09-25"}
                        for r in json.load(f)[:3] if r.get("url")]
        vs.migrate(".", extra_feishu=rows, note="P1-A selftest 桥接")
        self.assertEqual(vs.load_validated()["schema"], vs.SCHEMA)

    def test_canonical_key_and_normalize_name(self):
        cases = [
            ("https://GHProxy.net/https://raw.githubusercontent.com/A/B/main/c.json",
             "raw.githubusercontent.com/A/B/main/c.json"),
            ("http://www.Example.com:80/x/", "example.com/x"),
            ("https://api.example.com:443/v1?a=1#frag", "api.example.com/v1?a=1"),
        ]
        for url, want in cases:
            self.assertEqual(vs.canonical_key(url), want, url)
        self.assertEqual(vs.normalize_name("【高清】CCTV-1 综合"),
                         vs.normalize_name("cctv1综合"))


if __name__ == "__main__":
    unittest.main()
