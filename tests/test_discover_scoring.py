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


if __name__ == "__main__":
    unittest.main()
