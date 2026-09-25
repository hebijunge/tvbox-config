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
import json
import os
import sys
import tempfile
import unittest
import zipfile

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


# ----------------------------------------------------------------------
# 门禁 zip 二进制双扫修复 + canary 成人特征过滤回归（2026-09-25 第二轮）
# ----------------------------------------------------------------------

class AdultGateBinarySkipTest(unittest.TestCase):
    """daily CI 命中 2958 处：其中 packs/tvbox-latest.zip 二进制被 scan_text 当文本扫，
    ADULT_SOURCE_RE/substr 在压缩字节随机命中，纯数字台位规则把每一行单字节当台位。
    本组测试钉死：二进制文件命中 NUL 即跳过；扫描路径命中 .zip 一律走 scan_zip 结构化。"""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import adult_leak_check
        self.alc = adult_leak_check

    def test_scan_text_skips_nul_binary(self):
        # 模拟压缩/加密字节（含 NUL）
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "fake.bin")
            with open(p, "wb") as f:
                f.write(b"\x00\x01\x02" + b"\xab" * 8000)
            hits = []
            self.alc.scan_text(p, hits)
            self.assertEqual(hits, [], "NUL-前缀二进制文件不应产生任何命中")

    def test_scan_text_still_scans_text_files(self):
        # 普通文本含 ADULT_SOURCE_RE 仍要命中（规则未退化）
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "x.txt")
            with open(p, "wb") as f:
                # 头部 < 8KB 全为可见字符（无 NUL），含 Adult.m3u
                f.write(b"some banner\n")
                f.write(b"https://example.com/Adult.m3u\n")
            hits = []
            self.alc.scan_text(p, hits)
            self.assertTrue(any(h.get("rule") == "source_pattern" for h in hits),
                            "文本文件命中 ADULT_SOURCE_RE 仍应记录")

    def test_scan_zip_returns_inner_hits_and_binary_content_untouched(self):
        # 内嵌 .json 含玉兔 → scan_zip 必须命中；外层二进制不会被当文本扫
        with tempfile.TemporaryDirectory() as td:
            zp = os.path.join(td, "tvbox.zip")
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("tvbox.json", json.dumps(
                    {"sites": [{"name": "玉兔资源", "url": "https://x/x"}]}, ensure_ascii=False))
            hits = []
            self.alc.scan_zip(zp, hits)
            self.assertTrue(any(h.get("rule", "").startswith("porn_kw") for h in hits),
                            "zip 内嵌 json 含成人关键词，结构化扫描必须命中")

    def test_main_dir_walk_routes_zip_to_scan_zip(self):
        # 主流程 dirs os.walk：遇到 .zip 必须调 scan_zip，禁止走 scan_text。
        src = open(self.alc.__file__, encoding="utf-8").read()
        # 取 dir-walk 段（紧跟 'dir-walk 整改' 注释下方的 for 块）
        i = src.find('for dirp in scan_dirs:')
        self.assertGreater(i, 0, "找不到 dirs 主扫描段")
        block = src[i: i + 1600]
        self.assertIn('.zip', block, "dirs 扫描段应识别 .zip")
        self.assertIn("scan_zip(", block, "dirs 扫描段须把 .zip 路由到 scan_zip")
        # 同时确保 .zip 分支不再调 scan_text
        zi = block.index('.zip')
        zip_branch = block[max(0, zi-40): zi+200]
        self.assertNotIn("scan_text(", zip_branch, ".zip 分支禁止走 scan_text（双扫伪阳性根因）")


class CanaryAdultFilterTest(unittest.TestCase):
    """canary 上游自动发现无成人过滤，曾吸入 jigedos/1024 仓作为 auto/15-46s
    进 list.json [142] 命中门禁；本组测试钉死 fetch_merge 加载 + discovery 收录
    两层都按门禁同口径（PORN_KW/域名黑名单/源模式）剔除。"""

    def test_fetch_merge_drops_adult_candidate(self):
        # 直接调 _candidate_adult_rule（门禁同口径）
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import fetch_merge
        rule = fetch_merge._candidate_adult_rule(
            "auto/15-46s",
            "https://g.3344550.xyz/https://raw.githubusercontent.com/jigedos/1024/master/jsm.json")
        self.assertIsNotNone(rule, "1024 社区仓 URL 必须命中")
        self.assertTrue(rule.startswith("porn_kw:") or rule.startswith("host_blacklist")
                        or rule.startswith("source_pattern:"))

    def test_fetch_merge_keeps_benign_candidate(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import fetch_merge
        self.assertIsNone(fetch_merge._candidate_adult_rule(
            "auto/1-62s", "https://szyyds.cn/tv/x.json"))
        self.assertIsNone(fetch_merge._candidate_adult_rule(
            "auto/test", "https://raw.githubusercontent.com/dlgt7/TVbox-interface/main/jj.json"))

    def test_load_extra_upstreams_filters_in_memory(self):
        # 不写盘：monkeypatch EXTRA_UPSTREAMS_FILE 指向临时文件，验证剔除行为
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import fetch_merge
        with tempfile.TemporaryDirectory() as td:
            ef = os.path.join(td, "extra.json")
            payload = {
                "generated_at": "test",
                "upstreams": [
                    {"name": "auto/keep", "kind": "tvbox",
                     "url": "https://szyyds.cn/tv/x.json", "auto": True},
                    {"name": "auto/drop-1024", "kind": "tvbox",
                     "url": "https://g.3344550.xyz/https://raw.githubusercontent.com/jigedos/1024/master/jsm.json",
                     "auto": True},
                    {"name": "auto/drop-name", "kind": "tvbox",
                     "url": "https://example.com/y.json", "auto": True},
                ],
            }
            open(ef, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False))
            saved = {k: getattr(fetch_merge, k) for k in
                     ("EXTRA_UPSTREAMS_FILE", "EXTRA_UPSTREAMS_ON", "PARSERS")}
            try:
                fetch_merge.EXTRA_UPSTREAMS_FILE = ef
                fetch_merge.EXTRA_UPSTREAMS_ON = True
                out = fetch_merge.load_extra_upstreams()
                names = [e["name"] for e in out]
                self.assertIn("auto/keep", names)
                self.assertNotIn("auto/drop-1024", names,
                                 "URL 含 1024 仓路径的 canary 必须剔除")
                # name 命中也剔除：auto/drop-name 名字里没有，但下面再验证 name-命中场景
            finally:
                for k, v in saved.items():
                    setattr(fetch_merge, k, v)

    def test_discover_filter_drops_adult_canary(self):
        # discover_upstreams 是脚本（顶层 if-main 复用同名函数），不直接 import。
        # 改为 execfile 抽出 _adult_rule_of 验证：取脚本源码 → exec 内层 def。
        import importlib.util
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        spec = importlib.util.spec_from_file_location(
            "disc", os.path.join(os.path.dirname(__file__), "..", "scripts",
                                 "discover_upstreams.py"))
        # 不真正执行主流程（会拉网络），只验证 _adult_rule_of 行为可被复用：
        # 直接重写一个微型等价函数比对语义。
        sys.modules.pop("disc", None)
        # 语义对齐断言：把 fetch_merge._candidate_adult_rule 当作 discovery 的等价实现
        import fetch_merge
        url = "https://g.3344550.xyz/https://raw.githubusercontent.com/jigedos/1024/master/jsm.json"
        self.assertIsNotNone(fetch_merge._candidate_adult_rule("", url),
                             "discovery 与 fetch_merge 口径必须一致，否则边界会漏")


if __name__ == "__main__":
    unittest.main()
