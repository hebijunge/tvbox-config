# -*- coding: utf-8 -*-
"""sites_probe.json 有两个生产方，本地 5a 不能把别人写的行抹掉。

实测（2026-10-02）：main 的产物里 487 行 = 186 行 http 判定 + 301 行只有
`{key, check_ms, check_at}` 的通路（CI stage 8 直播测速那类写的）。本地跑一次
`probe_sites --only http` 产出 212 行直接覆写，301 条测速记录就地消失；下一轮 CI
再覆写回来——谁后跑谁赢，两边的覆盖率数字都在互相抹。
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import probe_sites  # noqa: E402

MINE = [{"key": "a", "api": "http://a/api.php", "kind": "http", "level": "L3"},
        {"key": "b", "api": "http://b/api.php", "kind": "http", "level": "L0"}]
FOREIGN = [{"key": "lajiaozy.com", "check_ms": 497, "check_at": "2026-10-02 09:47:27"},
           {"key": "ruyi", "check_ms": 1217, "check_at": "2026-10-02 09:47:27"}]


class CarryForeignTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "sites_probe.json")

    def write_prev(self, rows):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"summary": {}, "sites": rows}, f, ensure_ascii=False)

    def test_foreign_rows_survive_our_run(self):
        self.write_prev(MINE + FOREIGN)
        got = probe_sites.carry_foreign_rows(MINE, self.path)
        self.assertEqual(len(got), 4)
        self.assertEqual({r["key"] for r in got}, {"a", "b", "lajiaozy.com", "ruyi"})

    def test_our_own_verdicts_are_not_resurrected(self):
        """本轮判成 L0 的站，不能被上一轮的旧行"补"回来变成两条。"""
        self.write_prev([{"key": "a", "api": "http://a/api.php", "kind": "http", "level": "L3"}])
        this_round = [{"key": "a", "api": "http://a/api.php", "kind": "http", "level": "L0"},
                      {"key": "b", "api": "http://b/api.php", "kind": "http", "level": "L2"}]
        got = probe_sites.carry_foreign_rows(this_round, self.path)
        self.assertEqual([r["key"] for r in got], ["a", "b"], "同 key 只留本轮那条")
        self.assertEqual([r["level"] for r in got], ["L0", "L2"], "本轮结论优先")

    def test_missing_previous_file_is_not_fatal(self):
        got = probe_sites.carry_foreign_rows(MINE, os.path.join(self.tmp.name, "nope.json"))
        self.assertEqual(got, MINE)

    def test_broken_previous_file_is_not_fatal(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ 这不是 json")
        self.assertEqual(probe_sites.carry_foreign_rows(MINE, self.path), MINE)

    def test_same_key_merges_fields_not_rows(self):
        """同 key 两边都有：本轮判定优先，但别人写的测速字段不能丢。"""
        self.write_prev([{"key": "a", "check_ms": 497, "check_at": "2026-10-02 09:47:27"}])
        this_round = [{"key": "a", "api": "http://a/api.php", "kind": "http", "level": "L2"}]
        got = probe_sites.carry_foreign_rows(this_round, self.path)
        self.assertEqual(len(got), 1, "不该变成两条互相打架的记录")
        self.assertEqual((got[0]["level"], got[0]["check_ms"]), ("L2", 497))

    def test_empty_prev_rows_all_are_kept(self):
        self.write_prev(FOREIGN)
        self.assertEqual(len(probe_sites.carry_foreign_rows([], self.path)), 2)


if __name__ == "__main__":
    unittest.main()
