"""回归守卫：N1 存量词表盲区（香蕉超清/avhh.vip）+ N3 门禁扫描域补 exports（2026-09-26）。

质检1号独立验证（2026-09-26）点名：
  N1 阻断：tvbox sites[1632] 香蕉超清（csp_xBPQ_超清，ext=avhh.vip，分类 ID 为
     「2k-<拼音>」成人分类模板）仍在常规产物——词表只收「香蕉啪」收漏站点名、
     avhh.vip 不在 host 黑名单、pinyin 分类编码脱分子串匹配。
  N3 P2：exports/ 不在 gate_criteria 扫描域；status.json 内部审计口径未明示。

修复语义：
  1. 词表单源 state/vocab/categories.json：+香蕉超清（站名）、+avhh.vip（host exact）、
     +avhh（token，防后缀变体）、+5 个长且高特异性 pinyin 分类词
     （luanlun/zipaitoupai/siwazhifu/zhibolubo/chaoqingsanji）；短/歧义 pinyin
     （如 sanji/sm）不收防误伤。
  2. 合并层门禁同口径终扫按构造重定向该站 → adult.json（复用既有代码路径）。
  3. gate_criteria dirs += exports；扫描 JSON 内 gone/dropped/removed/
     local_ref_audit 审计上下文按 guarded 豁免（audit_context=true 显式入报告）。
"""

import json
import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_SCRIPTS = os.path.join(_TESTS_DIR, "..", "scripts")
sys.path.insert(0, _SCRIPTS)

import live_aggregate as la  # noqa: E402
import adult_leak_check as gate  # noqa: E402
import fetch_merge as fm  # noqa: E402

VOCAB_PATH = os.path.join(_ROOT, "state", "vocab", "categories.json")
GATE_PATH = os.path.join(_ROOT, "rules", "gate_criteria.json")

NEW_KW = ["香蕉超清", "luanlun", "zipaitoupai", "siwazhifu", "zhibolubo",
          "chaoqingsanji"]

# 质检1号 N1 取证的真实站点形态（tvbox sites[1632]，ext 截取）
XJQ_SITE = {
    "key": "csp_xBPQ_超清", "name": "香蕉超清", "type": 3, "api": "csp_xBPQ",
    "ext": {"分类url": "https://avhh.vip/cq/{cateId}-{catePg}.html",
            "分类": "请勿外传$2k-yazhou#按主页切换$2k-zipaitoupai#乱伦人妻$2k-luanlun#"
                   "丝袜制服$2k-siwazhifu#直播撸播$2k-zhibolubo#SM另类$2k-SMlinglei#"
                   "超清三级$2k-chaoqingsanji",
            "简介": "请勿外传，绝对禁止未成年人观看"},
}
CLEAN_SITE = {"key": "db1", "name": "豆瓣影视", "type": 0,
              "api": "https://caiji.example.com/api.php/provide/vod"}


class TestVocabSingleSource(unittest.TestCase):
    """词表事实源 state/vocab/categories.json 单源落词。"""

    def setUp(self):
        self.voc = json.load(open(VOCAB_PATH, encoding="utf-8"))
        self.a = self.voc["adult"]

    def test_n1_keywords(self):
        for w in NEW_KW:
            self.assertIn(w, self.a["name_keywords"], "缺词: %s" % w)

    def test_n1_host_blacklist(self):
        self.assertIn("avhh.vip", self.a["host_blacklist_exact"])
        self.assertIn("avhh", self.a["host_blacklist_tokens"])
        # token pattern 为独立字段，须同步含 avhh
        self.assertIn("avhh", self.a["host_blacklist_pattern"])

    def test_short_ambiguous_pinyin_not_added(self):
        # 短/歧义 pinyin 不收（sanji 是 sanjiao(三角) 子串；sm 过短）
        self.assertNotIn("sanji", self.a["name_keywords"])
        self.assertNotIn("sm", self.a["name_keywords"])

    def test_version_bumped(self):
        self.assertEqual(self.voc["version"], "2026-09-26.1")
        self.assertIn("N1 整改", self.voc["source_note"])


class TestLoadedVocab(unittest.TestCase):
    """live_aggregate 加载态与 URL 判定生效。"""

    def test_porn_kw_loaded(self):
        for w in NEW_KW:
            self.assertIn(w, la.PORN_KW)

    def test_is_adult_url_avhh(self):
        self.assertTrue(la.is_adult_url("https://avhh.vip/api.php/v1.vod"))
        # token：后缀变体（avhh 换 TLD/子域）也拦
        self.assertTrue(la.is_adult_url("http://avhh.xyz/x"))
        self.assertTrue(la.is_adult_url("https://cdn.avhh.net/cq/1.html"))

    def test_is_adult_name(self):
        self.assertTrue(la.is_adult("香蕉超清"))


class TestMergeGateSweep(unittest.TestCase):
    """合并层门禁同口径终扫：香蕉超清站点按构造重定向 adult.json。"""

    def test_xjq_site_redirected(self):
        clean, hits, _g = fm._split_by_adult_gate([dict(XJQ_SITE), dict(CLEAN_SITE)])
        self.assertEqual([s.get("key") for s in clean], ["db1"],
                         "干净站点不得误伤")
        self.assertEqual(len(hits), 1)
        site, real = hits[0]
        self.assertEqual(site.get("key"), "csp_xBPQ_超清")
        rules = {h["rule"] for h in real}
        self.assertTrue(any("香蕉超清" in r or "luanlun" in r for r in rules),
                        "应命中新词规则，实际: %s" % rules)

    def test_clean_site_untouched(self):
        clean, hits, _g = fm._split_by_adult_gate([dict(CLEAN_SITE)])
        self.assertEqual(len(clean), 1)
        self.assertEqual(hits, [])


class TestRulesExport(unittest.TestCase):
    """export_rules.py 物化产物与词表单源一致。"""

    def test_keywords_export(self):
        d = json.load(open(os.path.join(_ROOT, "rules", "adult_keywords.json"),
                           encoding="utf-8"))
        for w in NEW_KW:
            self.assertIn(w, d["porn_keywords"])

    def test_host_blacklist_export(self):
        d = json.load(open(os.path.join(_ROOT, "rules", "adult_host_blacklist.json"),
                           encoding="utf-8"))
        self.assertIn("avhh.vip", d["suffix_domains"])
        self.assertIn("avhh", d["host_tokens"])


class TestAuditContextGuard(unittest.TestCase):
    """N3：审计上下文豁免——gone/dropped/removed/local_ref_audit 记录按 guarded。"""

    def test_gone_record_guarded(self):
        hits = []
        gate._scan_string("玉兔 | 采集", "$/vod/gone[0]/name", "exports/health_report.json",
                          hits, ())
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["kind"], "guarded")
        self.assertTrue(hits[0].get("audit_context"))

    def test_local_ref_audit_guarded(self):
        hits = []
        gate._scan_string("JavBus", "$/local_ref_audit/dropped/adult.json[1]/name",
                          "status.json", hits, ())
        self.assertEqual(hits[0]["kind"], "guarded")

    def test_consumption_path_still_word(self):
        # 同值出现在消费路径（无审计上下文）必须仍计违规——豁免不得放大
        hits = []
        gate._scan_string("玉兔资源", "$/sites[0]/name", "tvbox.json", hits, ())
        self.assertEqual(hits[0]["kind"], "word")
        self.assertNotIn("audit_context", hits[0])


class TestGateCriteria(unittest.TestCase):
    """N3：gate_criteria 扫描域与豁免口径声明。"""

    def setUp(self):
        self.g = json.load(open(GATE_PATH, encoding="utf-8"))

    def test_exports_in_dirs(self):
        self.assertIn("exports", self.g["adult_zero_leak"]["scan"]["dirs"])

    def test_audit_contexts_declared(self):
        ac = self.g["adult_zero_leak"]["scan"]["audit_contexts"]
        for seg in ("/gone[", "/dropped", "/removed", "local_ref_audit"):
            self.assertIn(seg, ac)

    def test_status_json_excluded_with_reason(self):
        er = self.g["adult_zero_leak"]["scan"]["excluded_reasons"]
        self.assertIn("status.json", er)
        self.assertIn("内部审计", er["status.json"])

    def test_version(self):
        self.assertEqual(self.g["version"], "2026-09-26.1")


if __name__ == "__main__":
    unittest.main()
