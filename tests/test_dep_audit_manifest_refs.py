"""dep_audit 引用口径的单元测试：tvbox.json 显式引用 ∪ deps/manifest.json 账本。

动机：P0-1 死引用剥离会删产物里的 ./deps/ 引用但保留磁盘上的 dep（别的站可能仍
在用、或 7 天保留期未到）；dep_audit 只看 tvbox.json 时把这类 dep 全算成孤儿，
2026-10-03 实测虚高到 545MB / 89%，照着删会拿账本没登记的当"未使用"、
把仍在 manifest 里的 dep 判死。权威口径 = 产物显式引用 ∪ manifest 账本登记。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import dep_audit  # noqa: E402


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TestManifestRefs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dep-audit-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _make_repo(self, product_refs, manifest_locals, disk_files):
        # tvbox.json：sites[].api / sites[].ext 里带 ./deps/...
        sites = []
        for r in product_refs:
            sites.append({"key": os.path.basename(r), "name": r,
                          "api": "./" + r})
        cfg = {"sites": sites}
        _write(os.path.join(self.tmp, "tvbox.json"),
               json.dumps(cfg, ensure_ascii=False))
        # deps/manifest.json：账本条目
        mf = {f"origin|{url}": {"url": url, "origin": "origin",
                                 "local": lp, "md5": "", "size": 0}
              for url, lp in manifest_locals.items()}
        _write(os.path.join(self.tmp, "deps", "manifest.json"),
               json.dumps(mf, ensure_ascii=False))
        # 磁盘文件
        for rel in disk_files:
            _write(os.path.join(self.tmp, rel), "x" * 128)

    def _run(self):
        out = os.path.join(self.tmp, "state", "dep_audit.json")
        old = sys.argv
        sys.argv = ["dep_audit", "--repo", self.tmp, "--out", out]
        try:
            dep_audit.main()
        finally:
            sys.argv = old
        return json.load(open(out, encoding="utf-8"))

    def test_manifest_local_counts_as_reference(self):
        # a.js 由 tvbox.json 引用；b.js 只在 manifest 里登记（dead-ref 剥离的产物）；
        # c.js 两处都没有 → 只有 c.js 是真孤儿。
        self._make_repo(
            product_refs=["deps/a.js"],
            manifest_locals={"u_b": "deps/b.js"},
            disk_files=["deps/a.js", "deps/b.js", "deps/c.js"],
        )
        doc = self._run()
        un_paths = sorted(os.path.basename(u["path"])
                          for u in self._unreferenced(doc))
        self.assertEqual(un_paths, ["c.js"])
        self.assertEqual(doc["refs_product"], 1)
        self.assertEqual(doc["refs_manifest"], 1)
        self.assertEqual(doc["refs_total"], 2)

    def test_no_manifest_falls_back_to_product_only(self):
        # 缺 manifest 时按旧口径（只 tvbox.json），不能让脚本崩。
        self._make_repo(
            product_refs=["deps/a.js"],
            manifest_locals={},
            disk_files=["deps/a.js", "deps/b.js"],
        )
        # 移除 manifest，模拟账本不存在
        os.remove(os.path.join(self.tmp, "deps", "manifest.json"))
        doc = self._run()
        un_paths = sorted(os.path.basename(u["path"])
                          for u in self._unreferenced(doc))
        self.assertEqual(un_paths, ["b.js"])
        self.assertEqual(doc["refs_manifest"], 0)

    def test_manifest_windows_backslash_normalized(self):
        # 账本里存了 Windows 反斜杠路径也要匹配上 posix 磁盘相对路径。
        self._make_repo(
            product_refs=[],
            manifest_locals={},
            disk_files=["deps/sub/w.js"],
        )
        mf = {"origin|u": {"url": "u", "origin": "origin",
                            "local": "deps\\sub\\w.js", "md5": "", "size": 0}}
        _write(os.path.join(self.tmp, "deps", "manifest.json"),
               json.dumps(mf, ensure_ascii=False))
        doc = self._run()
        self.assertEqual(self._unreferenced(doc), [])

    def test_broken_manifest_does_not_crash(self):
        # 账本写坏（半截 JSON）时按无账本口径继续，不阻塞审计。
        self._make_repo(
            product_refs=["deps/a.js"],
            manifest_locals={},
            disk_files=["deps/a.js", "deps/b.js"],
        )
        _write(os.path.join(self.tmp, "deps", "manifest.json"), "{ broken")
        doc = self._run()
        un_paths = sorted(os.path.basename(u["path"])
                          for u in self._unreferenced(doc))
        self.assertEqual(un_paths, ["b.js"])

    def _unreferenced(self, doc):
        # 排除 deps/manifest.json 自身（审计里 manifest 也算磁盘文件、但显然不是依赖）
        return [u for u in doc["unreferenced_top"]
                if not u["path"].endswith("manifest.json")]


if __name__ == "__main__":
    unittest.main()
