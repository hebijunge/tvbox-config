"""deps 引用口径的三处一致耦合测试。

动机：dep_audit（报告）、dep_gc（GC 候选）、cleanup_deps（真删）历史上各自算
一份 refs，导致"报告改了、GC 还按旧口径、删除更窄"三层不一致；2026-10-03
修 dep_audit 加 manifest 时，如果不同步改另两处，manifest 里的 1377 条账本
登记在候选清单里仍是"孤儿"、cleanup 一旦开 --execute 就会拿报告没报的路径当
可删目标。这里用同一 tmp repo 让三处跑一遍，钉死它们引用的是同一份
`dep_refs.collect_all_refs`。
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import cleanup_deps  # noqa: E402
import dep_audit     # noqa: E402
import dep_gc        # noqa: E402
import dep_refs      # noqa: E402


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _make_repo(tmp):
    """产物只引 a.js；manifest 登记 b.js；磁盘 a/b/c。真孤儿只有 c。
    adult.json 里也引一个 d.js，验证 cleanup_deps 之前漏扫产物的 bug 已修。
    """
    _write(os.path.join(tmp, "tvbox.json"),
           json.dumps({"sites": [{"key": "x", "api": "./deps/a.js"}]},
                      ensure_ascii=False))
    _write(os.path.join(tmp, "adult.json"),
           json.dumps({"sites": [{"key": "y", "api": "./deps/d.js"}]},
                      ensure_ascii=False))
    _write(os.path.join(tmp, "deps", "manifest.json"),
           json.dumps({"u|b": {"url": "u", "origin": "u", "local": "deps/b.js",
                                "md5": "", "size": 0}}))
    for name in ("a.js", "b.js", "c.js", "d.js"):
        _write(os.path.join(tmp, "deps", name), "x" * 256)


class TestDepRefsAuthority(unittest.TestCase):
    def test_product_refs_include_adult_json(self):
        # 回归钉子：cleanup_deps 之前只扫 5 个主产物，adult.json 里的 deps 引用会被
        # 误算成"未引用"；这里断言 adult/adult_live 也在 PRODUCT_FILES 清单里。
        tmp = tempfile.mkdtemp(prefix="dep-refs-adult-")
        self.addCleanup(shutil.rmtree, tmp, True)
        _make_repo(tmp)
        refs = dep_refs.collect_product_refs(tmp)
        self.assertIn("deps/a.js", refs)
        self.assertIn("deps/d.js", refs,
                        "adult.json 里的 deps 引用必须被扫到")

    def test_manifest_local_normalized(self):
        # 账本里存反斜杠路径也要匹配上磁盘 posix 相对路径。
        tmp = tempfile.mkdtemp(prefix="dep-refs-mf-")
        self.addCleanup(shutil.rmtree, tmp, True)
        _write(os.path.join(tmp, "deps", "manifest.json"),
               json.dumps({"k": {"local": "deps\\sub\\w.js"}}))
        refs = dep_refs.collect_manifest_refs(tmp)
        self.assertEqual(refs, {"deps/sub/w.js"})

    def test_all_refs_is_union(self):
        tmp = tempfile.mkdtemp(prefix="dep-refs-union-")
        self.addCleanup(shutil.rmtree, tmp, True)
        _make_repo(tmp)
        prod, mf = dep_refs.split_refs(tmp)
        union = dep_refs.collect_all_refs(tmp)
        self.assertEqual(union, prod | mf)
        self.assertTrue({"deps/a.js", "deps/d.js"} <= prod)
        self.assertEqual(mf, {"deps/b.js"})


class TestThreeConsumersAligned(unittest.TestCase):
    """同一 tmp repo 让 dep_audit / dep_gc / cleanup_deps 各跑一次，
    断言三者认得的"未引用"集合完全一致——就是"deps/c.js"。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dep-tri-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        _make_repo(self.tmp)
        os.makedirs(os.path.join(self.tmp, "state"), exist_ok=True)
        # 把 mtime 推到 30 天前，绕开 dep_gc 的 7 天闸门、cleanup_deps 的 7/14 天保留期
        old = time.time() - 30 * 86400
        for name in ("a.js", "b.js", "c.js", "d.js"):
            os.utime(os.path.join(self.tmp, "deps", name), (old, old))

    def _chdir(self):
        prev = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, prev)

    def test_dep_audit_reports_only_c(self):
        self._chdir()
        out = os.path.join(self.tmp, "state", "dep_audit.json")
        old = sys.argv
        sys.argv = ["dep_audit", "--repo", self.tmp, "--out", out]
        try:
            dep_audit.main()
        finally:
            sys.argv = old
        doc = json.load(open(out, encoding="utf-8"))
        # 从 unreferenced_top 里排除 manifest.json 本身（它也是磁盘文件、显然不是依赖）
        paths = {u["path"] for u in doc["unreferenced_top"]
                 if not u["path"].endswith("manifest.json")}
        self.assertEqual(paths, {"deps/c.js"})

    def test_dep_gc_candidates_only_c(self):
        self._chdir()
        # dep_gc 会先要求 audit 文件存在（虽然它内部重扫 refs、不真用 audit 内容）
        audit_path = os.path.join(self.tmp, "state", "dep_audit.json")
        old = sys.argv
        sys.argv = ["dep_audit", "--repo", self.tmp, "--out", audit_path]
        try:
            dep_audit.main()
        finally:
            sys.argv = old
        old = sys.argv
        sys.argv = ["dep_gc", "--audit", audit_path,
                     "--out", os.path.join(self.tmp, "state", "dep_gc_candidates.json")]
        try:
            dep_gc.main()
        finally:
            sys.argv = old
        doc = json.load(open(os.path.join(self.tmp, "state", "dep_gc_candidates.json"),
                              encoding="utf-8"))
        paths = {c["path"] for c in doc["candidates"]}
        self.assertEqual(paths, {"deps/c.js"})

    def test_cleanup_deps_collect_refs_matches(self):
        self._chdir()
        refs = cleanup_deps.collect_refs(self.tmp)
        # a/b/d 都算引用，只有 c 不在里面
        self.assertIn("deps/a.js", refs)
        self.assertIn("deps/b.js", refs, "manifest 账本必须并入")
        self.assertIn("deps/d.js", refs, "adult.json 必须扫")
        self.assertNotIn("deps/c.js", refs)


if __name__ == "__main__":
    unittest.main()
