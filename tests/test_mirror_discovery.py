"""公网镜像发现路的纯逻辑回归（不触网）。

覆盖：
  · extract_prefix_hosts：只认「前缀 + github/raw」的确证形态，源站/短链一律不算
  · discover_hosts 的排除集：固定池、近 N 天测过（ranking + discovered 两处）、判死冷却、
    以及过期后重新有资格（轮转）
  · probe_one 对新面孔的忠实性闸门：校验不过直接出局，不浪费测速
  · online_hosts 走缓存时不再打网络
"""

import collections
import json
import os
import sys
import tempfile
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import mirror_probe as mp  # noqa: E402


def _utc(epoch):
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(epoch))


class TestExtract(unittest.TestCase):
    def test_only_prefix_form_counts(self):
        text = ("加速 https://gh.abcd.xyz/https://raw.githubusercontent.com/a/b/main/c.json "
                "或 https://x.net/gh/https://github.com/a/b/releases/download/v1/f.jar "
                "path 写法 https://gh-proxy.com/raw.githubusercontent.com/z/c/main/box "
                "源站 https://raw.githubusercontent.com/a/b/main/c.json 不算 "
                "短链 https://bit.ly/https://github.com/a/b 不算 "
                "裸域名 gh.some.host 也不算")
        self.assertEqual(dict(mp.extract_prefix_hosts(text)),
                         {"gh.abcd.xyz": 1, "x.net": 1, "gh-proxy.com": 1})

    def test_multi_segment_path_is_not_a_prefix(self):
        # 接口域名的参数里嵌了 github 地址，不是镜像前缀
        text = "https://api.xx.com/provide/vod/at/json/https://github.com/a/b"
        self.assertEqual(dict(mp.extract_prefix_hosts(text)), {})

    def test_host_of(self):
        self.assertEqual(mp._host_of("https://A.X.Com/something"), "a.x.com")
        self.assertEqual(mp._host_of(None), "")


class TestUpstreamLedger(unittest.TestCase):
    """路 0：管线自己拉成功过的前缀，取自上流账本。"""

    def test_channel_mirror_weighted(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "upstream_status.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"interfaces": [
                    {"channel": "mirror:gh.good.io",
                     "success_url": "https://gh.good.io/https://raw.githubusercontent.com/a/b/m/c.json"},
                    {"channel": "direct", "success_url": "https://some.site/api.php"},
                ]}, f)
            hosts = mp.upstream_proven_hosts([p])
        self.assertEqual(hosts["gh.good.io"], 6)  # 前缀形态 1 + 成功通道加权 5
        self.assertNotIn("some.site", hosts)

    def test_missing_ledger_is_silent(self):
        self.assertEqual(mp.upstream_proven_hosts(["不存在/的路径.json"]), {})


class TestSelection(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.fixed = {mp._host_of(p) for p in mp.CANDIDATES}
        self.rounds = [
            {"generated_at": _utc(self.now - 3600),          # 今天测过
             "ranking": [{"prefix": "https://recent.x"}],
             "discovered": [{"prefix": "https://newface.x/"}]},
            {"generated_at": _utc(self.now - 10 * 86400),    # 10 天前，重新有资格
             "ranking": [{"prefix": "https://longago.x"}], "discovered": []},
        ]
        self.dead = {"cool.x": {"at": self.now},             # 冷却中
                     "ancient.x": {"at": self.now - 90 * 86400}}  # 冷却已过
        self.proven = collections.Counter({"proven.x": 6, "recent.x": 5,
                                           "raw.githubusercontent.com": 88})
        self.web = collections.Counter({"cool.x": 99, "newface.x": 4, "ancient.x": 3,
                                        "longago.x": 7, "brand.x": 2,
                                        mp._host_of(mp.CANDIDATES[0]): 60})

    def test_exclusions_rotation_and_origin(self):
        picked = [(mp._host_of(p), o) for p, _n, o in
                  mp.discover_hosts(self.fixed, self.rounds, self.dead,
                                    proven=self.proven, web=self.web)]
        # 实证路优先出队；固定池/今天测过/冷却中/源站本身都被跳过
        self.assertEqual(picked, [("proven.x", "upstream"),
                                  ("longago.x", "online"),
                                  ("ancient.x", "online"),
                                  ("brand.x", "online")])

    def test_same_host_in_both_ledgers_probed_once(self):
        both = collections.Counter({"dup.x": 3})
        picked = mp.discover_hosts(self.fixed, [], {}, proven=both, web=both)
        self.assertEqual([mp._host_of(p) for p, _n, _o in picked], ["dup.x"])

    def test_per_round_cap(self):
        web = collections.Counter({"h%02d.x" % i: 100 - i for i in range(20)})
        picked = mp.discover_hosts(self.fixed, [], {}, proven=collections.Counter(),
                                   web=web)
        self.assertEqual(len(picked), mp.NEW_PER_ROUND)

    def test_cache_avoids_network(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "discovered.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"scanned_at": time.time(), "hosts": {"cached.x": 9}}, f)
            old = mp.DISCOVERED_CACHE
            mp.DISCOVERED_CACHE = path
            try:
                self.assertEqual(dict(mp.online_hosts()), {"cached.x": 9})
            finally:
                mp.DISCOVERED_CACHE = old


class TestContentGate(unittest.TestCase):
    def test_new_face_rejected_before_speed(self):
        orig_verify, orig_small = mp.verify_prefix_content, mp.probe_small
        called = []
        mp.verify_prefix_content = lambda p: False
        mp.probe_small = lambda p: called.append(p) or (None, False)
        try:
            r = mp.probe_one("https://stranger.x/", origin="upstream")
        finally:
            mp.verify_prefix_content, mp.probe_small = orig_verify, orig_small
        self.assertTrue(r["content_bad"])
        self.assertFalse(r["alive"])
        self.assertEqual(called, [], "忠实性闸门不过就不该再花时间测速")

    def test_fixed_pool_skips_gate(self):
        orig_verify = mp.verify_prefix_content
        mp.verify_prefix_content = lambda p: self.fail("固定池不该重复做全量校验")
        mp.probe_small = lambda p: (120, False)
        mp.probe_big = lambda p: (2000, False, 4194304, False)
        try:
            r = mp.probe_one("https://gh.halonice.com/", origin="fixed")
        finally:
            mp.verify_prefix_content = orig_verify
        self.assertEqual(r["KBps"], 2000)
        self.assertEqual(r["origin"], "fixed")


if __name__ == "__main__":
    unittest.main()
