"""阶段 2 取数通道回归：镜像链复用 fetch_merge 的 GH_MIRRORS，不再写死 ghproxy.net。

覆盖（全离线，用假 fetch_merge + 假 urlopen）：
  · mirror_chain：链来自 GH_MIRRORS、补尾斜杠、截前 2 位
  · _gh_attempts：非 github 链接不套镜像；raw 直连给短超时；已挂前缀的不重复叠
  · http_get：直连失败才降级到镜像链，按顺序试；全失败抛最后一个异常
"""
import os
import re
import sys
import unittest
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import discover_upstreams as du  # noqa: E402


class _FakeFM:
    GH_MIRRORS = ["https://a.mirror/", "https://b.mirror", "https://c.mirror/"]

    @staticmethod
    def _split_gh_prefix(url):
        m = re.match(r"^https?://[^/]+?/(https?://.*)$", url)
        if m and "github" in m.group(1):
            return m.group(1), True
        return url, False


RAW = "https://raw.githubusercontent.com/o/r/main/x.json"


class TestChain(unittest.TestCase):
    def setUp(self):
        self._real_fm = du._FM
        du._FM = _FakeFM
        self._env = dict(os.environ)

    def tearDown(self):
        du._FM = self._real_fm
        os.environ.clear()
        os.environ.update(self._env)

    def test_mirror_chain_from_gh_mirrors(self):
        self.assertEqual(du.mirror_chain(), ["https://a.mirror/", "https://b.mirror/"],
                         "应取 GH_MIRRORS 前 2 位并补尾斜杠")
        self.assertEqual(du.mirror_chain(1), ["https://a.mirror/"])

    def test_non_github_url_not_mirrored(self):
        u = "https://some-seed.example/README.md"
        self.assertEqual(du._gh_attempts(u, 10), [(u, 10)], "种子站/文章页不该套 github 镜像")

    def test_raw_gets_short_direct_then_mirrors(self):
        os.environ["DISCOVER_DIRECT_TIMEOUT"] = "3"
        a = du._gh_attempts(RAW, 12)
        self.assertEqual(a[0], (RAW, 3.0), "raw 直连只给 3s，别白等 12s")
        self.assertEqual(a[1], ("https://a.mirror/" + RAW, 12))
        self.assertEqual(a[2], ("https://b.mirror/" + RAW, 12))
        self.assertEqual(len(a), 3)

    def test_prefixed_url_does_not_stack(self):
        prefixed = "https://old.proxy/https://raw.githubusercontent.com/o/r/main/x.json"
        a = du._gh_attempts(prefixed, 12)
        self.assertEqual([u for u, _t in a],
                         ["https://a.mirror/" + RAW, "https://b.mirror/" + RAW],
                         "老前缀要被替换成最优链，不能叠两层，也不再直连")

    def test_unknown_prefix_not_stacked(self):
        # 陌生前缀不在 fetch_merge 的已知清单里，也必须剥掉再重挂，否则变双前缀
        u = "https://old.proxy/https://raw.githubusercontent.com/o/r/main/x.json"
        a = [x for x, _t in du._gh_attempts(u, 12)]
        self.assertEqual(a, ["https://a.mirror/" + RAW, "https://b.mirror/" + RAW])
        # 只允许一层代理前缀（双前缀实测基本取不到东西）
        self.assertFalse([x for x in a if re.search(r"https?://[^/]+/https?://[^/]+/", x)
                          and x.count("://") > 2], a)

    def test_path_form_prefix_normalized(self):
        # path 写法剥出来没有协议，要补回 https:// 再挂最优前缀
        class _FM2(_FakeFM):
            @staticmethod
            def _split_gh_prefix(url):
                if url.startswith("https://gh-proxy.com/"):
                    return url.split("gh-proxy.com/", 1)[1], True
                return url, False
        du._FM = _FM2
        u = "https://gh-proxy.com/raw.githubusercontent.com/o/r/main/x.json"
        a = [x for x, _t in du._gh_attempts(u, 12)]
        self.assertEqual(a, ["https://a.mirror/" + RAW, "https://b.mirror/" + RAW])

    def test_github_page_keeps_full_direct_timeout(self):
        u = "https://github.com/o/r"
        a = du._gh_attempts(u, 12)
        self.assertEqual(a[0], (u, 12), "github.com 页面不缩短直连超时，免把好取的判成不可达")


class _Resp:
    def __init__(self, body=b'{"sites":[]}'):
        self._b = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=0):
        return self._b if not n else self._b[:n]

    status = 200


class TestHttpGet(unittest.TestCase):
    def setUp(self):
        self._real_fm = du._FM
        du._FM = _FakeFM
        self.seen = []
        self._urlopen = urllib.request.urlopen

    def tearDown(self):
        du._FM = self._real_fm
        urllib.request.urlopen = self._urlopen

    def _fake(self, fail_until=None, body=b'{"sites":[]}'):
        def impl(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            self.seen.append((url, timeout))
            if fail_until is True or (fail_until and url in fail_until):
                raise OSError("blocked")
            return _Resp(body)
        urllib.request.urlopen = impl

    def test_falls_back_to_mirror_in_order(self):
        self._fake(fail_until={RAW})
        st, raw = du.http_get(RAW, 12, 300_000)
        self.assertEqual(st, 200)
        self.assertEqual(raw, b'{"sites":[]}')
        self.assertEqual([u for u, _t in self.seen][:2],
                         [RAW, "https://a.mirror/" + RAW], "直连失败应立刻按镜像链降级")

    def test_raises_last_when_all_fail(self):
        self._fake(fail_until=True)  # 三次尝试全失败
        with self.assertRaises(Exception):
            du.http_get(RAW, 5, 100)
        self.assertEqual(len(self.seen), 3, "直连 + 2 个镜像都试完才放弃")

    def test_non_github_single_attempt(self):
        self._fake()
        du.http_get("https://seed.example/README.md", 10)
        self.assertEqual(len(self.seen), 1)


class TestProbeWindow(unittest.TestCase):
    """候选窗口与排序的确定性（阶段 2 池子换手的真凶）。"""

    def test_deterministic_across_set_orders(self):
        urls = [f"https://raw.githubusercontent.com/o/r{i % 3}/main/x{i}.json"
                for i in range(30)]
        s1, s2 = set(urls), set(reversed(urls))
        self.assertEqual(du.probe_window(s1, 12, day=5), du.probe_window(s2, 12, day=5),
                         "同一批候选、不同 set 插入顺序，窗口必须一致")

    def test_no_truncation_when_fits(self):
        urls = {"https://b/x.json", "https://a/x.json"}
        self.assertEqual(du.probe_window(urls, 10), ["https://a/x.json", "https://b/x.json"])

    def test_rotation_covers_everything_over_days(self):
        urls = {f"https://x.test/{i:02d}.json" for i in range(20)}
        seen = set()
        for day in range(1, 4):
            seen |= set(du.probe_window(urls, 8, day=day))
        self.assertEqual(seen, urls, "按日轮转应让尾巴也有被探到的一天")

    def test_day_is_stable_within_day(self):
        urls = {f"https://x.test/{i:02d}.json" for i in range(20)}
        self.assertEqual(du.probe_window(urls, 8, day=9), du.probe_window(urls, 8, day=9))


class TestRank(unittest.TestCase):
    def test_tie_break_prefers_tvbox_then_bigger_then_url(self):
        rows = [
            {"url": "https://z/x.json", "score": 90, "kind": "tvbox", "evidence": {"sites": 10}},
            {"url": "https://a/x.json", "score": 90, "kind": "tvbox", "evidence": {"sites": 99}},
            {"url": "https://m/m.json", "score": 90, "kind": "m3u", "evidence": {"entries": 50}},
            {"url": "https://b/x.json", "score": 90, "kind": "tvbox", "evidence": {"sites": 10}},
            {"url": "https://h/h.json", "score": 100, "kind": "other", "evidence": {}},
        ]
        out = [r["url"] for r in du.rank_results(rows)]
        self.assertEqual(out, ["https://h/h.json",           # 100 分最高
                               "https://a/x.json",           # 90 分里站点最多
                               "https://b/x.json",           # 同分同站点，URL 字典序
                               "https://z/x.json",
                               "https://m/m.json"])          # 同分非 tvbox 靠后

    def test_m3u_entries_used_as_size(self):
        rows = [{"url": "https://a", "score": 60, "kind": "m3u", "evidence": {"entries": 7}},
                {"url": "https://b", "score": 60, "kind": "other", "evidence": {}}]
        self.assertEqual(du.rank_results(rows)[0]["url"], "https://a")


if __name__ == "__main__":
    unittest.main()
