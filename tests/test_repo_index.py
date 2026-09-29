"""仓库增量索引（state/repo_index.json）的行为回归。

背景：全展开 977 个仓 ≈ 2329 条候选，L0 实测吞吐 1.45 条/秒 → 单探测 27 分钟，加列树 12.5 分钟
＝一轮 40 分钟，正因付不起才一直只展开 15 个仓（还抽得随机）。而样本 60 个仓里近 24h 有 push
的只有 27%，配置内容本身变得更慢。于是「全量覆盖 + 增量免检」：pushed_at 没变的仓不列树，
blob sha 没变、且已有结论的文件不重探。
这几条测试钉的就是"什么时候允许免检"——放太松会把残缺结论固化，放太紧等于没有缓存。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import discover_upstreams as du  # noqa: E402

DAY = 86400


def row(kind="tvbox", score=90, sites=12, reachable=True):
    out = {"reachable": reachable, "kind": kind, "score": score,
           "evidence": {"sites": sites}, "bytes": 4096, "sha256": "deadbeef",
           "sha_partial": False}
    if not reachable:
        out = {"reachable": False, "error": "URLError"}
    return out


class CacheCase(unittest.TestCase):
    """把 repo_meta / tree_blobs 换成脚本化的假数据，并记录各自被调了几次。"""

    def setUp(self):
        self.calls = []
        self.meta = {}      # repo -> (branch, pushed_at) | None
        self.trees = {}     # repo -> {path: blob_sha}
        self._meta = du.repo_meta
        self._trees = du.tree_blobs
        du.repo_meta = lambda fn: (self.calls.append("meta:" + fn), self.meta.get(fn))[1]
        du.tree_blobs = lambda fn, br: (self.calls.append("tree:" + fn), self.trees.get(fn, {}))[1]

    def tearDown(self):
        du.repo_meta = self._meta
        du.tree_blobs = self._trees

    def n(self, kind, repo):
        return sum(1 for c in self.calls if c == kind + ":" + repo)


class TestExpandRepos(CacheCase):
    def test_cold_run_probes_everything(self):
        self.meta["o/r"] = ("main", "2026-09-29T00:00:00Z")
        self.trees["o/r"] = {"a.json": "sha-a", "b.json": "sha-b"}
        cands, cached, skip, idx, st = du.expand_repos(["o/r"], {}, now=100)
        self.assertEqual(cands, {"https://raw.githubusercontent.com/o/r/main/a.json",
                                 "https://raw.githubusercontent.com/o/r/main/b.json"})
        self.assertEqual((cached, skip), ({}, set()), "冷启动没有任何结论可复用")
        self.assertEqual((st["reused_files"], st["fresh_files"]), (0, 2))
        self.assertEqual(self.n("tree", "o/r"), 1)

    def test_unchanged_repo_skips_tree_and_reuses_rows(self):
        prev = {"o/r": {"branch": "main", "pushed_at": "P", "seen": 1,
                        "files": {"a.json": {"sha": "sha-a", "row": row(), "at": 1}}}}
        self.meta["o/r"] = ("main", "P")
        cands, cached, skip, _idx, st = du.expand_repos(["o/r"], prev, now=100)
        self.assertEqual(self.n("tree", "o/r"), 0, "pushed_at 没变就不该再列树")
        self.assertEqual((st["hit"], st["reused_files"], st["fresh_files"]), (1, 1, 0))
        self.assertEqual(list(cached.values())[0]["score"], 90, "结论直接来自索引")
        self.assertEqual(st["api"], 1, "命中缓存的仓只花 1 次 API")
        self.assertEqual(list(cands), list(cached), "候选仍在，只是不用实探")

    def test_only_changed_blobs_are_reprobed(self):
        prev = {"o/r": {"branch": "main", "pushed_at": "P0", "seen": 1,
                        "files": {"a.json": {"sha": "sha-a", "row": row(), "at": 1},
                                  "b.json": {"sha": "sha-b", "row": row(sites=3, score=80), "at": 1}}}}
        self.meta["o/r"] = ("main", "P1")                            # 仓被 push 过
        self.trees["o/r"] = {"a.json": "sha-a", "b.json": "sha-B"}   # 但只有 b 的内容变了
        _c, cached, _s, _i, st = du.expand_repos(["o/r"], prev, now=2)
        self.assertEqual(list(cached), ["https://raw.githubusercontent.com/o/r/main/a.json"],
                         "blob sha 没变的文件不重探")
        self.assertEqual((st["reused_files"], st["fresh_files"]), (1, 1))

    def test_failure_is_skipped_inside_backoff_then_retried(self):
        """失败结论按 FAIL_RETRY_DAYS 退避：不缓存到永远（抖动会把源判死），
        但也不天天重探——实测 35% 的即时失败若每天重来，缓存就永远攒不起来。"""
        prev = {"o/r": {"branch": "main", "pushed_at": "P", "seen": 1,
                        "files": {"a.json": {"sha": "sha-a", "row": row(reachable=False),
                                             "at": 1000}}}}
        self.meta["o/r"] = ("main", "P")
        _c, cached, skip, _i, st = du.expand_repos(["o/r"], prev, now=1000 + 3 * DAY)
        self.assertEqual(cached, {}, "连不上的条目不能进池")
        self.assertEqual(len(skip), 1, "退避期内不再实探")
        self.assertEqual(st["skipped_fail"], 1)

        _c, cached, skip, _i, st = du.expand_repos(["o/r"], prev, now=1000 + 30 * DAY)
        self.assertEqual((cached, skip, st["fresh_files"]), ({}, set(), 1),
                         "超过退避期要给一次重试机会")

    def test_meta_failure_keeps_previous_entry(self):
        """一次 404/限流不该把整仓缓存抹掉，否则下一轮要重做全量探测。"""
        prev = {"o/r": {"branch": "main", "pushed_at": "P", "seen": 1,
                        "files": {"a.json": {"sha": "sha-a", "row": row(), "at": 1}}}}
        self.meta["o/r"] = None
        _c, _cached, _skip, idx, _st = du.expand_repos(["o/r"], prev, now=2)
        self.assertEqual(idx["o/r"], prev["o/r"])

    def test_repos_not_picked_this_round_survive(self):
        prev = {"o/other": {"branch": "main", "pushed_at": "P", "seen": 9, "files": {}}}
        self.meta["o/r"] = ("main", "P")
        self.trees["o/r"] = {"a.json": "sha-a"}
        _c, _cached, _skip, idx, _st = du.expand_repos(["o/r"], prev, now=2)
        self.assertIn("o/other", idx, "本轮没抽到的仓要留在索引里，缓存才攒得起来")

    def test_new_file_in_repo_gets_probed(self):
        prev = {"o/r": {"branch": "main", "pushed_at": "P0", "seen": 1,
                        "files": {"a.json": {"sha": "sha-a", "row": row(), "at": 1}}}}
        self.meta["o/r"] = ("main", "P1")
        self.trees["o/r"] = {"a.json": "sha-a", "new.json": "sha-new"}
        cands, cached, _s, _i, st = du.expand_repos(["o/r"], prev, now=2)
        self.assertIn("https://raw.githubusercontent.com/o/r/main/new.json", cands)
        self.assertNotIn("https://raw.githubusercontent.com/o/r/main/new.json", cached)
        self.assertEqual(st["fresh_files"], 1)


class TestIndexPersistence(CacheCase):
    def test_save_load_roundtrip(self):
        path = os.path.join(_ROOT, ".qoder-tmp", "repo_index_case.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        now = 1_800_000_000
        idx = {"o/ok": {"branch": "main", "pushed_at": "P", "seen": now,
                        "files": {"a.json": {"sha": "s", "row": row(), "at": now}}},
               "o/noname": {"branch": "", "pushed_at": "P", "seen": now, "files": {}}}
        self.assertEqual(du.save_repo_index(idx, path, now=now), 1)
        back = du.load_repo_index(path)
        self.assertEqual(list(back), ["o/ok"], "没有 branch 的记录拼不出 URL，存了也没用")
        self.assertEqual(back["o/ok"]["files"]["a.json"]["row"]["score"], 90)
        os.remove(path)

    def test_ttl_prunes_stale(self):
        path = os.path.join(_ROOT, ".qoder-tmp", "repo_index_ttl.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        now = 1_800_000_000
        idx = {"o/fresh": {"branch": "main", "pushed_at": "P", "seen": now, "files": {}},
               "o/stale": {"branch": "main", "pushed_at": "P", "seen": now - 60 * DAY, "files": {}}}
        self.assertEqual(du.save_repo_index(idx, path, now=now), 1)
        self.assertEqual(list(du.load_repo_index(path)), ["o/fresh"])
        os.remove(path)

    def test_load_missing_or_broken_file(self):
        self.assertEqual(du.load_repo_index(os.path.join(_ROOT, ".qoder-tmp", "nope.json")), {})
        bad = os.path.join(_ROOT, ".qoder-tmp", "repo_index_broken.json")
        os.makedirs(os.path.dirname(bad), exist_ok=True)  # 新检出树里没有这个目录，写前先建
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(du.load_repo_index(bad), {})
        os.remove(bad)


class TestMergeProbeRows(CacheCase):
    def test_success_stores_row_and_keeps_blob_sha(self):
        idx = {"o/r": {"branch": "main", "pushed_at": "P", "seen": 1,
                       "files": {"a.json": {"sha": "sha-a", "row": None, "at": 1}}}}
        ok = dict(row(), url="https://raw.githubusercontent.com/o/r/main/a.json")
        self.assertEqual(du.merge_probe_rows(idx, [ok], now=77), 1)
        stored = idx["o/r"]["files"]["a.json"]
        self.assertEqual(stored["sha"], "sha-a", "blob sha 不能被回写冲掉")
        self.assertEqual(stored["at"], 77)
        self.assertTrue(stored["row"]["reachable"])

    def test_failure_is_recorded_with_timestamp(self):
        idx = {"o/r": {"branch": "main", "pushed_at": "P", "seen": 1,
                       "files": {"a.json": {"sha": "sha-a", "row": None, "at": 1}}}}
        dead = {"url": "https://raw.githubusercontent.com/o/r/main/a.json",
                "reachable": False, "error": "URLError"}
        du.merge_probe_rows(idx, [dead], now=500)
        stored = idx["o/r"]["files"]["a.json"]
        self.assertFalse(stored["row"]["reachable"])
        self.assertEqual(stored["at"], 500, "退避计时从这次失败开始")
        self.assertEqual(idx["o/r"]["pushed_at"], "P", "失败不该作废整仓的树缓存")

    def test_url_not_from_expansion_is_ignored(self):
        idx = {"o/r": {"branch": "main", "pushed_at": "P", "seen": 1, "files": {}}}
        self.assertEqual(du.merge_probe_rows(idx, [{"url": "https://elsewhere/x.json"}]), 0)


class TestPickConfigPaths(unittest.TestCase):
    def test_prefers_config_looking_names_then_length(self):
        blobs = {"zz.json": "1", "tvbox.json": "2", "sub/jsm.json": "3", "a" * 30 + ".json": "4"}
        got = du.pick_config_paths(blobs)
        self.assertEqual(got[0], "tvbox.json")
        self.assertIn("sub/jsm.json", got)

    def test_json_substring_does_not_count_as_keyword(self):
        """旧判据 `(tvbox|box|jsm|js|config|api)` 里的 `js` 会命中每个 `*.json` 的 "json" 子串，
        所有文件同为 0 优先级 → 排序退化成按长度排，真正叫 js.json 的反而不占先。"""
        got = du.pick_config_paths({"zz.json": "1", "aaa.js.json": "2"})
        self.assertEqual(got[0], "aaa.js.json", "独立成词的 js 才算关键词")
        self.assertTrue(du.CONFIG_PREFER_RE.search("js.json"))
        self.assertFalse(du.CONFIG_PREFER_RE.search("banjser.json"))

    def test_limit_respected(self):
        blobs = {f"f{i}.json": str(i) for i in range(20)}
        self.assertEqual(len(du.pick_config_paths(blobs)), 8)


class TestKeepConfigBlob(unittest.TestCase):
    def test_engineering_files_are_skipped(self):
        for p in ["package.json", "package-lock.json", "tsconfig.json", "src/bower.json",
                  ".github/labels.json", "lib.min.js", "vendor/x/composer.json"]:
            self.assertFalse(du.keep_config_blob(p, 5000), f"{p} 不该占探测名额")

    def test_extension_and_size_window(self):
        self.assertTrue(du.keep_config_blob("box.json", 5000))
        self.assertTrue(du.keep_config_blob("live.m3u", 600))
        self.assertTrue(du.keep_config_blob("x.txt", 12 * 1024 * 1024))
        self.assertFalse(du.keep_config_blob("readme.md", 5000), "非配置后缀")
        self.assertFalse(du.keep_config_blob("tiny.json", 100), "小于 500B 不可能是配置")
        self.assertFalse(du.keep_config_blob("huge.json", 13 * 1024 * 1024))


if __name__ == "__main__":
    unittest.main()
