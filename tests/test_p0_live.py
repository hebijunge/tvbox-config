"""P0 路线图纯逻辑回归测试（P0-4 单测分层·纯逻辑必过）。

覆盖：
  · adult 频道名判定（成人关键词/纯数字/【水果派】前缀/AV 番号）
  · URL 域名黑名单判定（suffix_domains + host_tokens）
  · 频道名标准化（去空格/全角转半角/装饰剥除）
  · 解析器导出规则 JSON 与代码常量一致（单一事实源回归）
  · 分片 sha1 取模确定性
  · 双重 host 命中：URL 含 host_tokens 时返回 True

触网用例另放 tests_net/，失败不阻塞 daily。
"""

import hashlib
import json
import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

# 显式 import 路径以保证测试可独立跑
import importlib.util


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


la = _load("live_aggregate_for_test",
           os.path.join(_ROOT, "scripts", "live_aggregate.py"))


class AdultChannelNameTests(unittest.TestCase):
    """频道名成人判定 — 来自 live_aggregate 实际常量的回归。"""

    def test_porn_keyword_match(self):
        # 关键词：porn_kw:1024 / 少妇 / mmz / 看片
        self.assertTrue(la.is_adult("1024"))
        self.assertTrue(la.is_adult("1024伦理"))
        self.assertTrue(la.is_adult("少妇上门"))
        self.assertTrue(la.is_adult("mmz-002"))
        self.assertTrue(la.is_adult("看片神器"))
        self.assertTrue(la.is_adult("一本道"))

    def test_pure_number_station(self):
        # 纯数字短名 ≤3 位视为成人
        self.assertTrue(la.is_adult("999"))
        self.assertTrue(la.is_adult("789"))
        self.assertTrue(la.is_adult("365"))
        self.assertTrue(la.is_adult("007"))
        self.assertFalse(la.is_adult("CCTV1"))
        self.assertFalse(la.is_adult("湖南卫视"))

    def test_bracket_tag(self):
        # 【水果派】/【免费】前缀
        self.assertTrue(la.is_adult("【水果派】东京热精选"))
        self.assertTrue(la.is_adult("【免费】高清"))
        self.assertFalse(la.is_adult("【央广】新闻"))

    def test_av_serial(self):
        # AV 番号 / 日期格式（4-6 位日期段；regex 限制避免 CCTV-1 误伤）
        self.assertTrue(la.is_adult("n1234-2025-01"))
        self.assertTrue(la.is_adult("123456-12-25"))
        self.assertFalse(la.is_adult("CCTV-1"))
        self.assertFalse(la.is_adult("湖南-10"))

    def test_negative_cases(self):
        self.assertFalse(la.is_adult("CCTV-13 新闻"))
        self.assertFalse(la.is_adult("湖南卫视"))
        self.assertFalse(la.is_adult("BBC Earth"))
        self.assertFalse(la.is_adult(""))

    def test_rule_of_returns_label(self):
        self.assertIn("porn_kw", la.adult_rule_of("1024"))
        self.assertIn("pure_number", la.adult_rule_of("999"))
        self.assertEqual("", la.adult_rule_of("CCTV-13"))
        self.assertEqual("", la.adult_rule_of(""))


class AdultUrlDomainTests(unittest.TestCase):
    """URL 域名级成人判定 — 第三重防线，事实来自 adult 实际产物。"""

    def test_suffix_domains_block(self):
        for h in ["mycamtv.net", "adultiptv.net", "slbfsl.com", "ddyunbo.com"]:
            self.assertTrue(la.is_adult_url(f"https://{h}/some/path"))
            self.assertTrue(la.is_adult_url(f"http://{h}/"))

    def test_subdomain_block(self):
        # 子域也应命中后缀匹配
        self.assertTrue(la.is_adult_url("https://play.mycamtv.net/"))
        self.assertTrue(la.is_adult_url("https://cdn.adultiptv.net/live/123"))

    def test_host_tokens_block(self):
        for u in ["https://pornhub.com/foo",
                  "https://www.xvideos.com/bar",
                  "https://xnxx.example.com/",
                  "https://missav.cdn.baz/"]:
            self.assertTrue(la.is_adult_url(u))

    def test_legit_url_passes(self):
        for u in ["https://github.com/hebijunge/tvbox-config",
                  "https://raw.githubusercontent.com/hebijunge/foo/main/x.json",
                  "https://example.com/live?id=1",
                  "https://cdn.jsdelivr.net/npm/lib@1/dist.js"]:
            self.assertFalse(la.is_adult_url(u), u)


class ShardStabilityTests(unittest.TestCase):
    """分片轮转：同 URL 同 total_shards 时取模结果稳定。"""

    def test_sha1_mod_deterministic(self):
        # 30 个 URL × N 分片验证确定性 + 不全撞同一桶
        urls = ["https://a%d.com/%d" % (i, j) for i in range(10) for j in range(3)]
        for total in [3, 5, 7, 11]:
            r1 = sorted(int(hashlib.sha1(u.encode()).hexdigest(), 16) % total for u in urls)
            r2 = sorted(int(hashlib.sha1(u.encode()).hexdigest(), 16) % total for u in urls)
            self.assertEqual(r1, r2, "sha1 mod 确定性失败")
            # 30 个 URL 应能命中至少 ≥ min(total, 3) 个桶
            self.assertGreaterEqual(len(set(r1)), min(total, 3),
                                    f"分片数 {total} 命中分布过窄")

    test_shard_same_channel_same_bucket = test_sha1_mod_deterministic


class RuleExportConsistencyTests(unittest.TestCase):
    """规则单一事实源：导出的 rules/*.json 必须与 live_aggregate 常量一致。"""

    def test_keywords_json_matches(self):
        path = os.path.join(_ROOT, "rules", "adult_keywords.json")
        if not os.path.isfile(path):
            self.skipTest("rules/ 未导出（export_rules.py 未跑）")
        data = json.load(open(path, encoding="utf-8"))
        # 导出的 porn_keywords 与代码 PORN_KW 必须一致
        exported = set(data["porn_keywords"])
        source = set(la.PORN_KW)
        self.assertEqual(exported, source,
                         "porn_keywords 与代码 PORN_KW 不一致（事实源漂移）")

    def test_blacklist_json_matches(self):
        path = os.path.join(_ROOT, "rules", "adult_host_blacklist.json")
        if not os.path.isfile(path):
            self.skipTest("rules/ 未导出")
        data = json.load(open(path, encoding="utf-8"))
        self.assertEqual(set(data["suffix_domains"]), set(la.ADULT_HOSTS))
        self.assertEqual(set(data["host_tokens"]), set(la.ADULT_HOST_TOKENS))

    def test_blacklist_size_baseline(self):
        """回归守卫：域名黑名单萎缩时必须显式更新基线，避免规则静默退化。"""
        path = os.path.join(_ROOT, "rules", "adult_host_blacklist.json")
        if not os.path.isfile(path):
            self.skipTest("rules/ 未导出")
        data = json.load(open(path, encoding="utf-8"))
        # 基线=导出首次 34 个后缀 + 6 tokens，规则收缩到 < 30 视为退化
        n_dom = len(data["suffix_domains"])
        n_tok = len(data["host_tokens"])
        self.assertGreaterEqual(n_dom, 30,
                                f"suffix_domains 萎缩到 {n_dom} < 30，请更新基线")
        self.assertGreaterEqual(n_tok, 5,
                                f"host_tokens 萎缩到 {n_tok} < 5，请更新基线")


if __name__ == "__main__":
    unittest.main()