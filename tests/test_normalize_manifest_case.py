#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写盘前收口（fetch_merge.normalize_manifest_case_collisions）的回归测试。

这个函数存在的理由是：resolve_dep_paths 只看得见本轮处理的条目，账本里那些本轮
不重处理的历史陈旧条目会以原名一路被写回。2026-10-12 之前 windows-path-check 反复
红，就是因为 CI 缓存每轮把账本回滚成旧版，而写出的账本没人再校验一遍。

两条最要紧的断言：
1. 陈旧条目（updated_at 很旧、本轮不在映射里）也会被收口；
2. 选边必须与 pathutil.resolve_case_collisions 同一条规则——本函数曾按
   「优先保留全小写名」选胜者，与 #62 相反，于是同一个冲突长出两套降级名。
"""
import os
import sys
import unittest
from unittest import mock

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import fetch_merge as fm        # noqa: E402
import pathutil                 # noqa: E402

UP = "deps/wex/newwex/IPTV.m3u"
LOW = "deps/wex/newwex/iptv.m3u"


def dirty_manifest():
    """两份大写 + 两份小写，模拟 run#177 之后 main 上那个脏账本的形状。"""
    return {
        "wex/newwex|gh.halonice.com/.../IPTV.m3u": {"local": UP, "updated_at": "2026-09-28"},
        "wex/newwex|github.moeyy.xyz/.../IPTV.m3u": {"local": UP, "updated_at": "2026-09-28"},
        "wex/newwex|cdn.gh-proxy.org/.../iptv.m3u": {"local": LOW, "updated_at": "2026-09-28"},
        "wex/newwex|tv.711933.xyz/iptv.m3u": {"local": LOW, "updated_at": "2026-09-28"},
    }


class TestCollapseStaleEntries(unittest.TestCase):
    def test_stale_loser_is_renamed(self):
        m = dirty_manifest()
        changed = fm.normalize_manifest_case_collisions(m)
        self.assertEqual(changed, 2, "两条陈旧小写都该被改走")
        demoted = pathutil.demote_rel(LOW)
        for k in ("wex/newwex|cdn.gh-proxy.org/.../iptv.m3u", "wex/newwex|tv.711933.xyz/iptv.m3u"):
            self.assertEqual(m[k]["local"], demoted)

    def test_winner_keeps_original_name(self):
        m = dirty_manifest()
        fm.normalize_manifest_case_collisions(m)
        for k in ("wex/newwex|gh.halonice.com/.../IPTV.m3u", "wex/newwex|github.moeyy.xyz/.../IPTV.m3u"):
            self.assertEqual(m[k]["local"], UP, "已落库优先：大写那条保留原名")

    def test_ledger_is_collision_free_after_write(self):
        m = dirty_manifest()
        fm.normalize_manifest_case_collisions(m)
        locals_ = [v["local"] for v in m.values()]
        self.assertEqual(pathutil.case_collisions(locals_), [])

    def test_idempotent(self):
        m = dirty_manifest()
        self.assertEqual(fm.normalize_manifest_case_collisions(m), 2)
        self.assertEqual(fm.normalize_manifest_case_collisions(m), 0, "再收口一次不该又改名")

    def test_clean_ledger_untouched(self):
        m = {"a|x": {"local": "deps/a/x.m3u"}, "a|y": {"local": "deps/a/y.m3u"}}
        self.assertEqual(fm.normalize_manifest_case_collisions(m), 0)
        self.assertEqual(m["a|x"]["local"], "deps/a/x.m3u")


class TestSameRuleAsPathutil(unittest.TestCase):
    """本函数不得另立选边标准，否则账本会长出两套降级名（历史上的 #55/#62 分歧）。"""

    def test_matches_resolve_case_collisions(self):
        m = dirty_manifest()
        fm.normalize_manifest_case_collisions(m)
        locals_ = [v["local"] for v in dirty_manifest().values()]
        expect = pathutil.resolve_case_collisions(locals_, occupied=locals_)
        for v in m.values():
            self.assertIn(v["local"], set(expect.values()))

    def test_does_not_prefer_all_lowercase(self):
        # 若沿用「优先保留全小写」，LOW 会保名、UP 会让位成 IPTV~d9cba8 —— 与 main 相反
        m = dirty_manifest()
        fm.normalize_manifest_case_collisions(m)
        self.assertTrue(any(v["local"] == UP for v in m.values()),
                        "大写原名必须仍有一条保留（已落库优先）")
        self.assertEqual(m["wex/newwex|tv.711933.xyz/iptv.m3u"]["local"],
                         pathutil.demote_rel(LOW))


class TestEntryShapeGuard(unittest.TestCase):
    def test_ignores_non_dict_and_blank_local(self):
        m = {"a|1": "junk", "a|2": {"local": ""}, "a|3": {"local": None},
             "a|4": {"local": "deps/a/ok.m3u"}}
        self.assertEqual(fm.normalize_manifest_case_collisions(m), 0)
        self.assertEqual(m["a|4"]["local"], "deps/a/ok.m3u")


class TestDiskMove(unittest.TestCase):
    """磁盘那一支在 Windows 上无法真造出大小写双胞胎（那正是本 bug 的形态），
    所以用桩验分支：优先复用已存在的降级文件，否则挪动败者，挪不动不许抛。"""

    def test_reuses_existing_demoted_file(self):
        m = {
            "a|up": {"local": "sub/Box.json"},
            "a|lo": {"local": "sub/box.json"},
            "a|pre": {"local": "sub/box~ab12cd.json"},
        }
        with mock.patch("os.path.isfile", return_value=True), \
             mock.patch("os.replace") as rep:
            fm.normalize_manifest_case_collisions(m)
        rep.assert_not_called()

    def test_moves_loser_when_demoted_file_absent(self):
        m = {"a|up": {"local": "sub/Box.json"}, "a|lo": {"local": "sub/box.json"}}
        demoted = pathutil.demote_rel("sub/box.json")

        def isfile(p):
            return p == "sub/box.json"          # 只有败者在磁盘上

        with mock.patch("os.path.isfile", side_effect=isfile), \
             mock.patch("os.makedirs"), mock.patch("os.replace") as rep:
            fm.normalize_manifest_case_collisions(m)
        rep.assert_called_once_with("sub/box.json", demoted)
        self.assertEqual(m["a|lo"]["local"], demoted)

    def test_oserror_does_not_break_ledger(self):
        m = {"a|up": {"local": "sub/Box.json"}, "a|lo": {"local": "sub/box.json"}}

        def isfile(p):
            return p == "sub/box.json"

        with mock.patch("os.path.isfile", side_effect=isfile), \
             mock.patch("os.makedirs"), \
             mock.patch("os.replace", side_effect=OSError("拒绝访问")):
            changed = fm.normalize_manifest_case_collisions(m)
        self.assertEqual(changed, 1, "磁盘挪不动只影响文件，账本仍要收口")
        self.assertNotEqual(m["a|lo"]["local"], "sub/box.json")


if __name__ == "__main__":
    unittest.main()
