"""同目录大小写冲突消解的单元测试（stdlib unittest）。

覆盖 pathutil 的冲突识别与确定性降级、fetch_merge 批量落库路径消解、
raw_store 账本层的同名沿用与降级、windows_path_check 守护接线。

动机：上游同名文件只差大小写时，Linux CI 两条记录并存、Windows 只能留一个，
本地内容与 git/账本三方错位，且 git status 永久显示该文件已修改，驱动 daily
反复重写同一份大文件（远端 pack 只存一份 blob，重复副本不占远端体积，被反复
重写的**新版本**才占）。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import fetch_merge as fm            # noqa: E402
import fix_case_collisions as fcc   # noqa: E402
import pathutil                     # noqa: E402
import raw_store                    # noqa: E402
import windows_path_check as wpc    # noqa: E402


class TestCollisionDetect(unittest.TestCase):
    def test_same_dir_diff_case_is_group(self):
        g = pathutil.case_collisions(["deps/a/IPTV.m3u", "deps/a/iptv.m3u"])
        self.assertEqual(g, [["deps/a/IPTV.m3u", "deps/a/iptv.m3u"]])

    def test_different_dirs_not_collision(self):
        self.assertEqual(
            pathutil.case_collisions(["deps/a/iptv.m3u", "deps/b/IPTV.m3u"]), [])

    def test_identical_path_not_collision(self):
        # 多条 URL 指向同一 local 是既有的去重设计，不是冲突
        self.assertEqual(pathutil.case_collisions(["deps/a/x.js", "deps/a/x.js"]), [])


class TestResolveCollisions(unittest.TestCase):
    def test_winner_keeps_name_bytewise(self):
        out = pathutil.resolve_case_collisions(
            ["deps/a/iptv.m3u", "deps/a/IPTV.m3u"])
        self.assertEqual(out["deps/a/IPTV.m3u"], "deps/a/IPTV.m3u")
        self.assertNotEqual(out["deps/a/iptv.m3u"], "deps/a/iptv.m3u")

    def test_stable_regardless_of_input_order(self):
        a = pathutil.resolve_case_collisions(
            ["deps/a/IPTV.m3u", "deps/a/iptv.m3u"])
        b = pathutil.resolve_case_collisions(
            ["deps/a/iptv.m3u", "deps/a/IPTV.m3u"])
        self.assertEqual(a, b, "本地与 CI 必须消解出同一个名字，否则账本再也对不上")

    def test_demoted_names_are_distinct_case_insensitively(self):
        paths = ["deps/a/IPTV.m3u", "deps/a/iptv.m3u", "deps/a/IPTV~deadbeef.m3u"]
        out = pathutil.resolve_case_collisions(paths)
        vals = list(out.values())
        self.assertEqual(len(set(v.lower() for v in vals)), len(vals))

    def test_idempotent_on_resolved_set(self):
        first = pathutil.resolve_case_collisions(
            ["deps/a/IPTV.m3u", "deps/a/iptv.m3u"])
        again = pathutil.resolve_case_collisions(list(first.values()))
        self.assertEqual({k: k for k in again}, again,
                         "消解后的集合不应再被改名")

    def test_no_collision_passthrough(self):
        paths = ["deps/a/x.m3u", "deps/b/y.m3u"]
        self.assertEqual(pathutil.resolve_case_collisions(paths),
                         {p: p for p in paths})


class TestResolveDepPaths(unittest.TestCase):
    def test_case_variants_get_distinct_locals(self):
        pairs = [("wex/newwex", "https://x.com/a/IPTV.m3u"),
                 ("wex/newwex", "https://x.com/a/iptv.m3u")]
        m = fm.resolve_dep_paths(pairs)
        self.assertEqual(len(m), 2)
        vals = list(m.values())
        self.assertEqual(len(set(v.lower() for v in vals)), 2,
                         f"两条 URL 落到同一物理文件: {vals}")

    def test_same_path_alias_still_allowed(self):
        # 多个 URL 派生出完全相同的路径是既有去重设计，不该被降级
        pairs = [("wex", "https://x.com/a/iptv.m3u"), ("wex", "https://y.com/a/iptv.m3u")]
        vals = list(fm.resolve_dep_paths(pairs).values())
        self.assertEqual(vals[0].lower(), vals[1].lower())
        self.assertEqual(vals[0], vals[1])

    def test_dep_local_path_unchanged_by_resolution(self):
        # 无冲突时消解必须是恒等，避免给存量路径带来漂移
        origin, url = "qist/jsm", "https://raw.githubusercontent.com/qist/tvbox/master/jar/spider.jar"
        self.assertEqual(fm.resolve_dep_paths([(origin, url)])[f"{origin}|{url}"],
                         fm.dep_local_path(origin, url))


class TestRawStoreSettle(unittest.TestCase):
    STORE = "raw/vod"

    def settle(self, m, key, ent, rel):
        return raw_store._settle_case_rel(self.STORE, m, key, ent, rel)

    def test_reuses_registered_case_variant(self):
        # 同一 key 上一轮登记的是大写名，本轮 URL 推出小写名 → 沿用大写名
        m = {"k1": {"path": "IPTV.m3u"}}
        self.assertEqual(self.settle(m, "k1", m["k1"], "iptv.m3u"), "IPTV.m3u")

    def test_demotes_other_key_holding_variant(self):
        m = {"k1": {"path": "IPTV.m3u"}}
        rel = self.settle(m, "k2", {}, "iptv.m3u")
        self.assertNotEqual(rel.lower(), "iptv.m3u")
        self.assertTrue(rel.endswith(".m3u"))

    def test_demotion_stable_across_rounds(self):
        m = {"k1": {"path": "IPTV.m3u"}}
        self.assertEqual(self.settle(m, "k2", {}, "iptv.m3u"),
                         self.settle(m, "k2", {}, "iptv.m3u"))

    def test_name_matches_migration_rule(self):
        """ingest 现算的名字必须和 fix_case_collisions 改出来的名字一致。

        两处各算各的，daily 下一轮就会把迁移改好的名字再改一遍，账本重新漂移。
        """
        m = {"k1": {"path": "Box.json"}}
        got = f"{self.STORE}/" + self.settle(m, "k2", {}, "box.json")
        expect = pathutil.resolve_case_collisions(
            [f"{self.STORE}/Box.json", f"{self.STORE}/box.json"]
        )[f"{self.STORE}/box.json"]
        self.assertEqual(got, expect)

    def test_backslash_ledger_path_normalized(self):
        # 历史账本里存在 os.path.relpath 留下的反斜杠 path
        m = {"k1": {"path": "history\\2026-09-29\\IPTV.m3u"}}
        rel = raw_store._settle_case_rel(
            "raw/live", m, "k1", m["k1"], "history/2026-09-29/iptv.m3u")
        self.assertEqual(rel, "history/2026-09-29/IPTV.m3u")

    def test_no_collision_untouched(self):
        m = {"k1": {"path": "other.m3u"}}
        self.assertEqual(self.settle(m, "k2", {}, "cn.m3u"), "cn.m3u")


class TestWindowsPathCheckGuard(unittest.TestCase):
    def test_guard_reports_collision(self):
        probs = wpc.check_case_collisions(["deps/a/IPTV.m3u", "deps/a/iptv.m3u"])
        self.assertEqual(len(probs), 1)
        self.assertIn("<->", probs[0][0])

    def test_guard_clean_when_distinct(self):
        self.assertEqual(
            wpc.check_case_collisions(["deps/a/iptv.m3u", "deps/b/IPTV.m3u"]), [])


class TestLedgerRewrite(unittest.TestCase):
    """账本改写字段的形态：deps 记仓库相对路径，raw 账本记 store 内相对路径。

    这里踩过坑：无条件按 store 目录剥前缀，把 deps/manifest.json 的 local 写成
    ``wex/newwex/...``，缓存查找与 dep_repair 全线失配。
    """

    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix="case_ledger_")
        os.chdir(self.tmp)
        os.makedirs("deps/wex/newwex")
        os.makedirs("raw/live")
        with open("deps/manifest.json", "w", encoding="utf-8") as f:
            json.dump({"wex|u2": {"local": "deps/wex/newwex/iptv.m3u"}}, f)
        with open("raw/live/manifest.json", "w", encoding="utf-8") as f:
            json.dump({"k2": {"path": "iptv.m3u"}}, f)

    def tearDown(self):
        # 顺序不能反：先离开临时目录再删，否则 rmtree 的是已不存在的 cwd，
        # 而全局 cwd 仍指向它（曾因此误删生产工作目录）
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_local_keeps_repo_relative_prefix(self):
        renames = {"deps/wex/newwex/iptv.m3u": "deps/wex/newwex/iptv~abc123.m3u",
                   "raw/live/iptv.m3u": "raw/live/iptv~abc123.m3u"}
        fcc.ledgers_with_renames(renames, True)
        dep = json.load(open("deps/manifest.json", encoding="utf-8"))
        raw = json.load(open("raw/live/manifest.json", encoding="utf-8"))
        self.assertEqual(dep["wex|u2"]["local"], "deps/wex/newwex/iptv~abc123.m3u")
        self.assertEqual(raw["k2"]["path"], "iptv~abc123.m3u")

    def test_backslash_ledger_path_also_rewritten(self):
        # 历史账本里同一归档存在 history\日期\name 这种反斜杠 path
        # （os.path.relpath 直接写进 manifest 留下的），JSON 文本里是转义两道。
        raw0 = {"k3": {"path": "cn.m3u",
                       "history": [{"path": "history\\2026-09-29\\iptv.m3u"}]}}
        with open("raw/live/manifest.json", "w", encoding="utf-8") as f:
            json.dump(raw0, f)
        renames = {"raw/live/history/2026-09-29/iptv.m3u":
                   "raw/live/history/2026-09-29/iptv~abc123.m3u"}
        fcc.ledgers_with_renames(renames, True)
        raw = json.load(open("raw/live/manifest.json", encoding="utf-8"))
        self.assertEqual(raw["k3"]["history"][0]["path"],
                         "history/2026-09-29/iptv~abc123.m3u")


class TestSkipRefreshUsesResolvedPath(unittest.TestCase):
    """SKIP_REFRESH 分支必须优先用 resolve_dep_paths 消解后的名字，
    否则 PR#35 迁移前留下的旧名（IPTV.m3u/iptv.m3u）会被 manifest-cache hit
    直接落到 ok_map、Windows 上物理是同一文件、CI 又写回产物 → 冲突复活。
    2026-10-03 PR#39/#40 CI 的 windows-path-check FAIL 就是这么产生的。"""

    def test_prefers_lp_map_over_manifest_local(self):
        lp_map = {"o|https://x/IPTV.m3u": "deps/o/iptv~1f1e8f.m3u"}
        got = fm.pick_refresh_local("o|https://x/IPTV.m3u",
                                     "deps/o/IPTV.m3u", lp_map)
        self.assertEqual(got, "deps/o/iptv~1f1e8f.m3u")

    def test_falls_back_to_manifest_local_when_unresolved(self):
        # 无冲突、resolve 没生成消解名的正常路径要沿用 manifest 里的登记，
        # 不能强行造一个新名。
        got = fm.pick_refresh_local("o|https://x/normal.js",
                                     "deps/o/normal.js", {})
        self.assertEqual(got, "deps/o/normal.js")

    def test_both_sides_of_collision_map_to_distinct_paths(self):
        # 大小写两 URL 都过 resolve_dep_paths：一个保原名、一个降级，
        # SKIP_REFRESH 阶段各自 hit 到自己的路径、产物里不再撞名。
        pairs = [("wex/newwex", "https://a/IPTV.m3u"),
                 ("wex/newwex", "https://b/iptv.m3u")]
        lp_map = fm.resolve_dep_paths(pairs)
        self.assertEqual(len(set(lp_map.values())), 2)
        self.assertEqual(
            fm.pick_refresh_local("wex/newwex|https://a/IPTV.m3u",
                                    "deps/wex/newwex/IPTV.m3u", lp_map),
            lp_map["wex/newwex|https://a/IPTV.m3u"])
        self.assertEqual(
            fm.pick_refresh_local("wex/newwex|https://b/iptv.m3u",
                                    "deps/wex/newwex/iptv.m3u", lp_map),
            lp_map["wex/newwex|https://b/iptv.m3u"])


if __name__ == "__main__":
    unittest.main()
