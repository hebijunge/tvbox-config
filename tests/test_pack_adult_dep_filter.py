"""回归守卫：pack_local 依赖成人预过滤——P0-2 根治 tvbox-latest.zip deps/** 泄漏。

根因（daily run 36202886685 step17 门禁 916 处命中）：fetch_merge 的合并层终扫
只覆盖配置正文字符串，上游配置引用的依赖文件（deps/**/*.json，如
cluntop/aa/lib/cj.json 的 AV 分类、pikpakclass.a.json 的 JAVHD 分类）原样进 zip，
门禁 scan_zip 逐条目扫描即命中。

修复语义：pack_local 在站点过滤前对全部候选引用按门禁 zip 内条目扫描语义
（scan_zip 单条目口径：json 全字段 + 原文 source_pattern + 文件名；zip 内无白名单）
预扫，命中文件进 BLOCKED_DEPS，resolve_ref 视为缺失——引用站点走既有
「依赖缺失→剔除」机制自然落榜，成人依赖不进 zip。
已知可接受代价：门禁词表子串误伤（如「java教程」命中 porn_kw:jav）在 zip 内
无白名单通道，按门禁同口径一并拦截——宁严勿松，引用站点随之剔除。
本测试断言：成人依赖精确拦截、干净依赖零误伤、blocked 后引用解析返回 None。
"""

import json
import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_TESTS_DIR, "..", "scripts")
sys.path.insert(0, _SCRIPTS)

import pack_local as pk  # noqa: E402
import adult_leak_check as gate  # noqa: E402
import live_aggregate as la  # noqa: E402


class TestGateDepHit(unittest.TestCase):
    """_gate_dep_hit：与门禁 scan_zip 单条目语义对齐。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pkdep-")

    def _write(self, name, text):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_json_porn_kw_hit(self):
        p = self._write("cj.json", json.dumps(
            {"classes": [{"type_name": "AV淫水机"}]}, ensure_ascii=False))
        rule = pk._gate_dep_hit(gate, la, p, "deps/x/cj.json")
        self.assertIsNotNone(rule)
        self.assertIn("porn_kw", rule)

    def test_json_clean_no_hit(self):
        p = self._write("ok.json", json.dumps(
            {"name": "影视综合", "api": "./deps/ok.jar"}, ensure_ascii=False))
        self.assertIsNone(pk._gate_dep_hit(gate, la, p, "deps/ok.json"))

    def test_source_pattern_text_hit(self):
        p = self._write("cfg.txt", "spider=http://x/fish2018/lib/a.js")
        rule = pk._gate_dep_hit(gate, la, p, "deps/cfg.txt")
        self.assertIsNotNone(rule)

    def test_adult_filename_hit_without_content_scan(self):
        # jar/js 不做内容扫描，但文件名命中 ADULT_SOURCE_RE 即拦截
        p = self._write("a.js", "var x=1;")
        rule = pk._gate_dep_hit(gate, la, p, "deps/supjav.user.js")
        self.assertIsNotNone(rule)

    def test_js_clean_name_only(self):
        # .js 门禁只扫文件名；内容含敏感词但文件名干净 → 门禁语义下不命中
        p = self._write("x.js", "var s='AV淫水机';")
        self.assertIsNone(pk._gate_dep_hit(gate, la, p, "deps/x.js"))

    def test_json_substring_fp_blocked_gate_same(self):
        # 「java教程」含 porn_kw 子串 jav——zip 内无白名单，门禁同口径拦截
        p = self._write("bili.json", json.dumps({"t": "java教程"}, ensure_ascii=False))
        rule = pk._gate_dep_hit(gate, la, p, "deps/bilibili.json")
        self.assertIsNotNone(rule)
        self.assertIn("porn_kw", rule)


class TestFilterAndResolve(unittest.TestCase):
    """filter_adult_deps + resolve_ref 联动：blocked 后引用视为缺失。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pkflt-")
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)
        os.makedirs(os.path.join("deps", "x"))
        pk.PATH_IDX.clear()
        pk.BLOCKED_DEPS.clear()

    def tearDown(self):
        os.chdir(self.old_cwd)
        pk.PATH_IDX.clear()
        pk.BLOCKED_DEPS.clear()

    def _setup_idx(self):
        files = {
            "deps/x/cj.json": json.dumps(
                {"classes": [{"type_name": "AV淫水机"}]}, ensure_ascii=False),
            "deps/x/bili.json": json.dumps({"t": "java教程"}, ensure_ascii=False),
            "deps/x/clean.json": json.dumps({"t": "普通影视"}, ensure_ascii=False),
        }
        for rel, txt in files.items():
            with open(rel, "w", encoding="utf-8") as f:
                f.write(txt)
            pk.PATH_IDX[rel] = rel

    def test_filter_blocks_adult_keeps_clean(self):
        self._setup_idx()
        refs = {"./deps/x/cj.json", "./deps/x/bili.json", "./deps/x/clean.json"}
        n = pk.filter_adult_deps(refs)
        # cj.json 真成人 + bili.json jav 子串（门禁同口径）均拦截；clean 零误伤
        self.assertEqual(n, 2)
        self.assertIn("deps/x/cj.json", pk.BLOCKED_DEPS)
        self.assertIn("deps/x/bili.json", pk.BLOCKED_DEPS)
        self.assertNotIn("deps/x/clean.json", pk.BLOCKED_DEPS)

    def test_blocked_ref_resolves_none(self):
        self._setup_idx()
        pk.filter_adult_deps({"./deps/x/cj.json"})
        self.assertIsNone(pk.resolve_ref("./deps/x/cj.json"))
        # 干净引用不受影响
        self.assertEqual(pk.resolve_ref("./deps/x/clean.json"), "deps/x/clean.json")

    def test_filter_idempotent(self):
        self._setup_idx()
        refs = {"./deps/x/cj.json"}
        n1 = pk.filter_adult_deps(refs)
        n2 = pk.filter_adult_deps(refs)
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)


if __name__ == "__main__":
    unittest.main()
