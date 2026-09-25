"""回归守卫：合并层「门禁同口径终扫」——adult 零泄漏 P0-2 红线对齐。

根因（daily run 36187372853 step17 门禁 3562 处命中；be53fa8 轮同源 3213 处）：
合并层 classify_site 的 STRONG/WEAK_ADULT_TOKENS 与门禁词表
（state/vocab/categories.json adult 节）是两套独立词表，词表漂移后上游重合并
注入的成人采集站（玉兔/madouse/Jable 等）以 vod 分类进入 tvbox.json。

修复语义：写主产物前用门禁自己的扫描语义（adult_leak_check._scan_string /
_iter_strings + 误报白名单）终扫站点/直播/解析/顶层字段：
  站点/直播命中 → 重定向 adult.json 通道；解析/顶层字符串命中 → 剔除；
  白名单（guarded）命中与门禁同口径留在常规产物。
本测试构造含成人站的上游样本，断言终扫全部拦截、干净样本零误伤。
"""

import ast
import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_TESTS_DIR, "..", "scripts")
FETCH_MERGE = os.path.join(_SCRIPTS, "fetch_merge.py")

sys.path.insert(0, _SCRIPTS)
import fetch_merge as fm  # noqa: E402


# ---- 上游样本（run 36187372853 实际泄漏的采集站形态）----
LEAK_SAMPLES = {
    # 玉兔：名称命中门禁词表 porn_kw:玉兔
    "yutu": {"key": "yutu", "name": "玉兔资源", "type": 0,
             "api": "https://apiyutu.com/api.php/provide/vod"},
    # madouse：名称无特征、域名命中（host token madouse）
    "madouse": {"key": "mds1", "name": "某某资源", "type": 0,
                "api": "https://caiji.madouse.com/api.php/provide/vod"},
    # Jable：名称 + 域名双命中
    "jable": {"key": "jbl1", "name": "Jable精选", "type": 0,
              "api": "https://jable.tv/api.php"},
    # 嵌套 ext 内含成人站名（门禁全字段递归扫描）
    "nested": {"key": "yt2", "name": "云播", "type": 0,
               "api": "https://cdn.example.com/vod", "ext": {"site": "玉兔传媒"}},
    # 整源模式：url 以 /Adult.m3u 结尾（ADULT_SOURCE_RE）
    "adult_m3u": {"key": "am3u", "name": "影视频道", "type": 0,
                  "api": "https://cdn.example.com/Adult.m3u"},
}

CLEAN_SAMPLES = {
    "normal": {"key": "zf1", "name": "卓越资源", "type": 0,
               "api": "https://caiji.zhuoyue.com/api.php/provide/vod"},
    # 已知误报白名单 key（classify 层强制 vod，终扫也应零真实命中）
    "webdav": {"key": "webdav", "name": "WebDav网盘", "type": 3,
               "api": "csp_WebDAV", "ext": "https://dav.example.com/dav"},
}

# 门禁误报白名单中的密文 blob 形态（≥50 位连续 [A-Za-z0-9+/=]）
CIPHER_BLOB = "AbC123xyzQwErTyUiOpAsDfGhJkLzXcVbNm1234567890QWEasdZXC=" + "mmz"


class AdultGateSweepTest(unittest.TestCase):
    """终扫函数行为：泄漏样本全拦截 / 干净样本零误伤 / 白名单同口径。"""

    def test_leak_samples_all_caught_by_gate_scan(self):
        for label, s in LEAK_SAMPLES.items():
            real, _ = fm.adult_gate_scan(s)
            self.assertTrue(real, "泄漏样本 %s 未被门禁同口径终扫命中" % label)
            rule = real[0].get("rule") or ""
            self.assertTrue(rule.startswith(("porn_kw:", "host_blacklist", "source_pattern")),
                            "样本 %s 命中规则异常：%s" % (label, rule))

    def test_clean_samples_zero_real_hit(self):
        for label, s in CLEAN_SAMPLES.items():
            real, _ = fm.adult_gate_scan(s)
            self.assertEqual(real, [], "干净样本 %s 被误伤：%s" % (label, real))

    def test_drift_documented_classify_misses_leak_names(self):
        """固化根因证据：classify_site 对泄漏样本（按名称）判 vod——词表漂移。

        若后续 classify 词表补词导致本断言变化，属预期演进：终扫仍兜底。
        """
        self.assertEqual(fm.classify_site(LEAK_SAMPLES["yutu"], {}, None), "vod")
        self.assertEqual(fm.classify_site(LEAK_SAMPLES["jable"], {}, None), "vod")

    def test_whitelisted_cipher_blob_is_guarded_not_real(self):
        s = {"key": "enc1", "name": "加密站", "type": 0,
             "api": "https://api.normal-site.com/vod", "ext": CIPHER_BLOB}
        real, guarded = fm.adult_gate_scan(s)
        self.assertEqual(real, [], "密文 blob 误报未走白名单：%s" % real)
        self.assertEqual(len(guarded), 1)
        self.assertEqual(guarded[0].get("kind"), "guarded")

    def test_split_redirects_hits_and_keeps_clean(self):
        items = [LEAK_SAMPLES["yutu"], CLEAN_SAMPLES["normal"],
                 LEAK_SAMPLES["madouse"], CLEAN_SAMPLES["webdav"]]
        clean, hits, _guarded = fm._split_by_adult_gate(items)
        self.assertEqual([h[0].get("name") for h in hits], ["玉兔资源", "某某资源"])
        self.assertEqual([c.get("key") for c in clean], ["zf1", "webdav"])

    def test_lives_and_parse_entries_scanned(self):
        live = {"name": "【水果派】精选", "type": 1, "url": "https://x.example.com/a.m3u"}
        real, _ = fm.adult_gate_scan(live)
        self.assertTrue(real)
        # 干净直播/解析零误伤（fanmingming EPG 为常规依赖）
        ok_live = {"name": "CCTV1", "type": 0, "url": "https://live.fanmingming.cn/tv/m3u/global.m3u"}
        self.assertEqual(fm.adult_gate_scan(ok_live)[0], [])
        ok_parse = {"name": "json并发", "type": 0, "url": "https://jx.jsonplayer.com/player/?url="}
        self.assertEqual(fm.adult_gate_scan(ok_parse)[0], [])

    def test_scan_semantics_share_gate_vocab(self):
        """终扫与门禁共用同一词表事实源：PORN_KW/黑名单同源，无第三套词表。"""
        import adult_leak_check as alc
        import live_aggregate as la
        self.assertIs(fm._adult_gate, alc)
        # 样本命中规则必须来自门禁词表（而非合并层 STRONG/WEAK_ADULT_TOKENS）
        for kw in ("玉兔", "madouse", "jable"):
            self.assertIn(kw, la.PORN_KW, "门禁词表缺 %s" % kw)


class SweepWiringTest(unittest.TestCase):
    """接线回归：终扫必须发生在写主产物之前、且覆盖全部注入面。"""

    def setUp(self):
        with open(FETCH_MERGE, encoding="utf-8") as f:
            self.source = f.read()
        self.tree = ast.parse(self.source)

    def _first_line_of(self, needle):
        for i, ln in enumerate(self.source.splitlines(), 1):
            if needle in ln:
                return i
        return -1

    def test_sweep_covers_sites_lives_parses(self):
        # 站点终扫（kept_sites 重绑定）+ 直播终扫 + 解析终扫 共三处条目级调用
        self.assertGreaterEqual(self.source.count("_split_by_adult_gate("), 3,
                                "终扫调用不足 3 处（站点/直播/解析）")

    def test_sweep_runs_before_products_written(self):
        # 终扫重绑定 lives 必须先于 tvbox["lives"] = lives / json.dump(tvbox...)
        sweep_line = self._first_line_of("lives, _life_gate_hits, _life_guarded = _split_by_adult_gate(")
        tvbox_lives_line = self._first_line_of('tvbox["lives"] = lives')
        write_line = self._first_line_of('with open("tvbox.json", "w", encoding="utf-8") as f:')
        self.assertGreater(sweep_line, 0)
        self.assertGreater(tvbox_lives_line, sweep_line, "直播终扫晚于 tvbox 装配，接线失效")
        self.assertGreater(write_line, sweep_line, "终扫必须先于写 tvbox.json")

    def test_gate_hits_redirected_to_adult_channel(self):
        # 直播终扫命中下放 adult_lives（成人通道），站点命中并入 adult_excluded_sites
        self.assertIn("for l in _life_gate_items:", self.source)
        self.assertIn("adult_excluded_sites.extend(s for s, _ in _gate_hits)", self.source)

    def test_status_records_sweep_stats(self):
        self.assertIn("adult_gate_sweep", self.source)


if __name__ == "__main__":
    unittest.main()
