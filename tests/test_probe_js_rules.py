# -*- coding: utf-8 -*-
"""5c JS 探针的取景与校验回归（2026-10-01 三个误判的钉版）。

钉住三件事：
  1) 远程规则要顺着 deps 账本找到本地副本——以前只测 api 以 ./ 开头的站，421 个 js 站只测了 48；
  2) drpy 规则是 ES 模块，`node --check` 按 CommonJS 解析会把正常引擎判成"语法错误"；
     校验用的临时副本必须唯一（几百站共享同一个 drpy2.min.js，固定名会并发互删）；
  3) 引擎文件（host 在各站远端规则里）不能判 S1——入库即 degraded，是拿工装能力冒充站点质量。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import probe_js as pj  # noqa: E402

ENGINE = 'import cheerio from "assets://js/lib/cheerio.min.js";\nfunction main(_){}\n'
RULE = 'var rule = {\n  host: "https://example.com",\n  url: "/show/{cat}"\n};\n'


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        os.makedirs(os.path.join(self.repo, "deps", "o"))
        self.remote = "https://git.example.com/o/r/raw/master/js/cat_x.js"
        with open(os.path.join(self.repo, "deps", "o", "cat_x.js"), "w", encoding="utf-8") as f:
            f.write(RULE)
        with open(os.path.join(self.repo, "deps", "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"o|" + self.remote: {"url": self.remote, "local": "deps/o/cat_x.js"}}, f)
        self.idx = pj.manifest_index(self.repo)
        self.addCleanup(self.tmp.cleanup)

    def test_remote_api_resolves_via_manifest(self):
        fp = pj.local_rule_file({"key": "k", "api": self.remote}, self.repo, self.idx)
        self.assertTrue(fp and os.path.isfile(fp), "远程规则顺着账本应能找到本地副本")

    def test_mirror_prefixed_api_also_resolves(self):
        self.assertTrue(pj.local_rule_file({"api": "https://gh-proxy.com/" + self.remote},
                                           self.repo, self.idx))

    def test_relative_api_resolves(self):
        self.assertTrue(pj.local_rule_file({"api": "./deps/o/cat_x.js"}, self.repo, self.idx))

    def test_dynamic_api_endpoint_is_not_a_file(self):
        self.assertIsNone(pj.local_rule_file({"api": "http://x/api.php/provide/vod"},
                                             self.repo, self.idx))


class EngineCase(unittest.TestCase):
    def test_engine_vs_rule_detection(self):
        self.assertTrue(pj.is_engine_file("js/drpy2.min.js", ENGINE))
        self.assertTrue(pj.is_engine_file("js/custom.js", ENGINE))
        self.assertFalse(pj.is_engine_file("js/JSGS.js", RULE))

    def test_engine_site_is_indeterminate_not_degraded(self):
        tmp = tempfile.TemporaryDirectory()
        repo = tmp.name
        os.makedirs(os.path.join(repo, "deps"))
        with open(os.path.join(repo, "deps", "drpy2.min.js"), "w", encoding="utf-8") as f:
            f.write(ENGINE)
        r = pj.probe_one({"key": "e", "name": "引擎站", "api": "./deps/drpy2.min.js"},
                         repo, ["庆余年"], pj.manifest_index(repo))
        self.assertEqual(r.get("level"), "S?", "引擎文件不该记 S1（入库即 degraded）")
        self.assertIn("引擎文件", str(r.get("reason")))
        tmp.cleanup()


class NodeCheckCase(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("没有 node，跳过语法校验回归")

    def test_esm_rule_is_not_a_syntax_error(self):
        d = tempfile.mkdtemp()
        fp = os.path.join(d, "engine.js")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(ENGINE)
        self.assertIs(pj.node_check(fp), True, "ES 模块被按 CommonJS 解析会误判语法错误")

    def test_concurrent_check_of_shared_file_is_stable(self):
        """几百个站共享同一个 drpy2.min.js：临时副本名字不唯一就会 A 删 B 用，成片假语法错。"""
        d = tempfile.mkdtemp()
        fp = os.path.join(d, "drpy2.min.js")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(ENGINE + "//撑大文件：" + ("x" * 200000))
        outs = []
        lock = threading.Lock()

        def run():
            v = pj.node_check(fp)
            with lock:
                outs.append(v)

        ts = [threading.Thread(target=run) for _ in range(12)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertNotIn(False, outs, "并发校验同一个文件不能出现 False")
        self.assertEqual(outs.count(True), 12)


if __name__ == "__main__":
    unittest.main()
