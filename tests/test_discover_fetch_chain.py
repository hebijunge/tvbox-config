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


class TestSelectRepos(unittest.TestCase):
    """仓库展开的抽样也必须确定性——与 probe_window 同一类 bug，但影响更大：
    它在 L0 之前，决定「哪些仓库有机会被列文件树」。

    2026-09-29 查「J 轮池 45→29」时定位到旧写法 `fresh_repos[:max_repos]` 切的是 set
    派生列表（顺序随 PYTHONHASHSEED 每进程洗牌），43 个新仓里随机抽 15 个展开，
    18 条高分候选（含 509/348/152 站的配置）所在仓库整仓没被看到。
    """

    def _repos(self, n):
        return [f"o{i % 7}/r{i:03d}" for i in range(n)]

    def test_same_batch_different_set_order_gives_same_selection(self):
        a, b = set(self._repos(40)), set(reversed(self._repos(40)))
        self.assertEqual(du.select_repos(a, 15, day=3), du.select_repos(b, 15, day=3),
                         "同一批仓、不同 set 顺序，抽出来的必须是同一批")

    def test_selection_is_capped_and_unique(self):
        sel = du.select_repos(self._repos(40), 15, day=9)
        self.assertEqual(len(sel), 15)
        self.assertEqual(len(set(sel)), 15)

    def test_rotation_covers_all_repos_across_days(self):
        repos = self._repos(30)
        seen = set()
        for day in range(1, 7):
            seen |= set(du.select_repos(repos, 10, day=day))
        self.assertEqual(seen, set(repos), "跨几天要把全部仓库轮到，不能永远饿死尾巴")

    def test_no_rotation_when_within_cap(self):
        self.assertEqual(du.select_repos(["b/x", "a/x"], 15), ["a/x", "b/x"])


class TestUnreachableStats(unittest.TestCase):
    """探测失败要留构成，否则「这一轮池子为什么缩」只能靠复跑猜。"""

    def test_histogram_and_sample(self):
        failed = [{"url": f"https://a/{i}.json", "error": "timeout"} for i in range(3)]
        failed += [{"url": "https://b/x.json", "error": "HTTP 404"},
                   {"url": "https://c/x.json"}]
        st = du.unreachable_stats(failed, sample=2)
        self.assertEqual(st["count"], 5)
        self.assertEqual(st["by_error"]["timeout"], 3)
        self.assertEqual(list(st["by_error"])[0], "timeout", "按数量降序")
        self.assertEqual(len(st["sample"]), 2, "明细只留样本，全量进直方图")
        self.assertEqual(st["sample"][0]["url"], "https://a/0.json", "样本按 URL 定序")

    def test_empty(self):
        st = du.unreachable_stats([])
        self.assertEqual(st["count"], 0)
        self.assertEqual(st["by_error"], {})
        self.assertEqual(st["sample"], [])


class TestRequestable(unittest.TestCase):
    """非 ASCII 的候选地址必须先变成 urllib 发得出去的形态。

    K 轮 115 条 L0 失败里 31 条是 UnicodeEncodeError：`http://miqk.cc/小蒙/DEMO.json`
    这类中文路径根本没发出去过就被记成死源。
    """

    def test_ascii_url_unchanged(self):
        u = "https://raw.githubusercontent.com/a/b/main/x.json?sign=Ab_1"
        self.assertEqual(du._requestable(u), u, "纯 ASCII 不该被改写出任何字节")

    def test_non_ascii_path_is_percent_encoded(self):
        out = du._requestable("http://miqk.cc/小蒙/DEMO.json")
        self.assertTrue(out.isascii(), out)
        self.assertIn("%E5%B0%8F%E8%92%99", out)
        self.assertIn("/DEMO.json", out)

    def test_existing_percent_encoding_not_double_encoded(self):
        u = "http://a.test/%E5%90%BE%E7%88%B1.m3u"
        self.assertEqual(du._requestable(u), u, "% 在 safe 集里，不能被二次编码成 %25")

    def test_non_ascii_host_becomes_punycode(self):
        out = du._requestable("http://jin.动漫.love/x.json")
        self.assertTrue(out.isascii(), out)
        self.assertIn("xn--", out.split("/")[2])
        self.assertTrue(out.startswith("http://xn--") or ".xn--" in out, out)

    def test_host_with_port_keeps_port(self):
        out = du._requestable("http://影视.例.com:8080/a.json")
        self.assertIn(":8080/", out)

    def test_broken_idna_host_returns_unchanged_not_crash(self):
        # 编码不出来就原样返回，让上层按普通失败处理，不能抛出去打断整轮探测
        self.assertIsInstance(du._requestable("http://xn--/a.json"), str)


class TestCandidateFilters(unittest.TestCase):
    def test_backtick_not_glued_into_url(self):
        text = "接口见 `http://a.test/x.json`，备用 `http://b.test/y.json`"
        found = du.URL_RE.findall(text)
        self.assertEqual(found, ["http://a.test/x.json", "http://b.test/y.json"],
                         "结尾反引号粘进地址会让同一份配置变成两条候选")

    def test_local_and_lan_addresses_dropped(self):
        for u in ["http://127.0.0.1:18765/live.m3u", "http://localhost/x.json",
                  "http://192.168.1.100:18765/live.m3u", "http://[::1]:8080/a.json",
                  "http://10.1.2.3/a.json"]:
            self.assertTrue(du.DROP_RE.search(u), f"本机/局域网地址必须出池：{u}")

    def test_public_addresses_kept(self):
        for u in ["http://120.79.4.185/dc.json", "http://8.210.232.168/xc.json",
                  "https://szyyds.cn/tv/x.json", "http://10.24hours.example/a.json"]:
            self.assertIsNone(du.DROP_RE.search(u), f"公网地址不该被误杀：{u}")


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
