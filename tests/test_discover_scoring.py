"""阶段 2 形态判定的回归（sites_of）。

2026-09-29 用独立通道（api.github.com contents，不经脚本的镜像链）抽查发现：
`pubtargus/CatVodTVSpider/js/alist.json` 是 18 项 Alist 服务器列表（键 name/server/startPage，
**0 项含 api**），却被旧判据「裸数组里有 name 的 dict」当成 tvbox 配置打 80 分。
产物不会脏（fetch_merge 合并要求 key+api），但会白占 canary 名额、把 unique 评估喂脏。
故裸数组分支收紧为「必须带 api」，dict.sites 分支保持宽松（sites 键本身是配置的结构证据）。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import discover_upstreams as du  # noqa: E402


class TestSitesOf(unittest.TestCase):
    def test_bare_array_needs_api(self):
        alist = [{"name": "本地", "server": "http://127.0.0.1:5244", "startPage": "/"},
                 {"name": "XY", "server": "https://xy.example", "search": True}]
        self.assertEqual(du.sites_of(alist), [], "服务器列表不该被算作站点")

    def test_bare_array_with_api_kept(self):
        cfg = [{"key": "k1", "name": "csp_x", "api": "https://ok.example/api", "type": 3},
               {"key": "k2", "name": "no-api", "type": 1}]
        out = du.sites_of(cfg)
        self.assertEqual([s["key"] for s in out], ["k1"], "裸数组里只收有 api 的项")

    def test_dict_sites_branch_stays_lenient(self):
        # sites 键本身即「这是配置」的结构证据：分支保持原样（返回全部 dict 项，
        # 含缺 api 的），本次只收紧裸数组分支，不动它——避免重演"聚合器配置被误判成垃圾"
        doc = {"sites": [{"key": "k", "name": "n"}, {"bad": 1}]}
        self.assertEqual(len(du.sites_of(doc)), 2)
        self.assertEqual([s.get("key") for s in du.sites_of(doc)], ["k", None])

    def test_nested_and_video_keys(self):
        self.assertEqual(len(du.sites_of({"data": {"sites": [{"api": "u"}]}})), 1)
        self.assertEqual(len(du.sites_of({"video": [{"api": "u"}, {"api": "v"}]})), 2)

    def test_non_config(self):
        self.assertEqual(du.sites_of({"name": "只是个说明", "list": "字符串"}), [])
        self.assertEqual(du.sites_of("不是 json"), [])


class TestContentDedup(unittest.TestCase):
    """同内容镜像去重：canary 名额不该被同一份配置的多个副本占掉。"""

    def _row(self, url, sha, size=1000, score=90, partial=False):
        return {"url": url, "sha256": sha, "bytes": size, "score": score,
                "kind": "tvbox", "sha_partial": partial, "evidence": {"sites": 10}}

    def test_same_hash_same_size_collapses(self):
        rows = [self._row("https://a/x.json", "abc"), self._row("https://b/x.json", "abc"),
                self._row("https://c/x.json", "abd")]
        kept, dupes = du.dedup_by_content(rows)
        self.assertEqual([r["url"] for r in kept], ["https://a/x.json", "https://c/x.json"])
        self.assertEqual(dupes[0]["same_as"], "https://a/x.json", "保留的是排在前面的代表")

    def test_truncated_reads_are_never_merged(self):
        """读满 300KB 上限的条目身份未知，整条退出去重。
        反例形状：同仓库一份 x.json（只有 sites）+ 一份 x_full.json（sites 一字不动再多带
        lives），两份都超 300KB → 前缀哈希与截断 bytes 全一样，一比就误杀真候选。
        （本轮实测的 haygcao `tvbox.json`/`tvbox_full.json` 就是这个形状，全文下载核对
        后确认内容确实相同——但那要读全文才知道，L0 阶段不能拿这个结论。）"""
        rows = [self._row("https://a/x.json", "abc", size=300_000, partial=True),
                self._row("https://a/x_full.json", "abc", size=300_000, partial=True)]
        kept, dupes = du.dedup_by_content(rows)
        self.assertEqual(len(kept), 2, "前缀相同不代表内容相同")
        self.assertEqual(dupes, [])

    def test_truncated_row_is_not_swallowed_by_complete_twin(self):
        """一条被截断（身份未知）、一条完整读到且哈希恰好相同：都不动。
        并错的代价是丢掉一个真候选，少并的代价只是一个重复名额。"""
        rows = [self._row("https://a/x.json", "abc", size=300_000, partial=True),
                self._row("https://mirror/a/x.json", "abc", size=1234)]
        kept, dupes = du.dedup_by_content(rows)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dupes, [])

    def test_rows_without_hash_are_kept(self):
        rows = [{"url": "https://a", "score": 30}, {"url": "https://b", "score": 30}]
        kept, dupes = du.dedup_by_content(rows)
        self.assertEqual(len(kept), 2)

    def test_representative_is_deterministic(self):
        rows = [self._row("https://z/x.json", "abc"), self._row("https://a/x.json", "abc")]
        kept, _ = du.dedup_by_content(rows)
        self.assertEqual(kept[0]["url"], "https://z/x.json",
                         "代表由入参顺序（rank_results 已定序）决定，不看 URL 字典序")


if __name__ == "__main__":
    unittest.main()
