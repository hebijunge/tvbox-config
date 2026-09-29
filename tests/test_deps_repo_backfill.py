"""整仓兜底两路（稀疏浅克隆 / codeload tarball）的回归，不依赖外网。

用本地 git 仓驱动同一条 clone→sparse-checkout→checkout 路径（把 _git_repo_url 指向
临时仓即可），验证：
  · gh_repo_ref_of 的识别边界（raw / raw 写法 / blob / release / 非 github 主机 / 镜像前缀）
  · deps_git_plan 的阈值与排序
  · deps_git_backfill 真取回字节、树里没有的路径不出现、未知 ref 退默认分支
  · tarball_take_files 只取白名单、超限单文件不收、成员名不参与拼路径
"""
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
import io
import subprocess

HAS_GIT = shutil.which("git") is not None

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import fetch_merge as fm  # noqa: E402


def _git(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


class TestRepoRef(unittest.TestCase):
    def test_recognized(self):
        self.assertEqual(fm.gh_repo_ref_of(
            "https://raw.githubusercontent.com/a/b/main/lib/x.json"),
            ("a", "b", "main", "lib/x.json"))
        self.assertEqual(fm.gh_repo_ref_of(
            "https://gh.halonice.com/https://raw.githubusercontent.com/a/b/main/x.js"),
            ("a", "b", "main", "x.js"))
        self.assertEqual(fm.gh_repo_ref_of("https://github.com/a/b/raw/main/x.json"),
                         ("a", "b", "main", "x.json"))
        self.assertEqual(fm.gh_repo_ref_of("https://github.com/a/b/blob/v1/dir/x.js"),
                         ("a", "b", "v1", "dir/x.js"))

    def test_path_traversal_rejected(self):
        # 上游 URL 可控，`..` 必须在解析阶段就拒（两条兜底路都拿它拼过文件系统路径）
        for u in ["https://raw.githubusercontent.com/a/b/main/../../../../etc/passwd",
                  "https://raw.githubusercontent.com/a/b/main/../../outside/x.json",
                  "https://github.com/a/b/blob/main/%2e%2e/secret"]:
            self.assertIsNone(fm.gh_repo_ref_of(u), u)
        self.assertFalse(fm._safe_rel_path(""))
        self.assertFalse(fm._safe_rel_path("/abs/path"))
        self.assertFalse(fm._safe_rel_path("a" + chr(0) + "b"))
        self.assertFalse(fm._safe_rel_path("%2e%2e/secret"), "百分号编码的点也要拦")
        self.assertFalse(fm._safe_rel_path("a" + chr(0) + "b"))
        self.assertFalse(fm._safe_rel_path("%2e%2e/secret"), "百分号编码的点也要拦")
        self.assertTrue(fm._safe_rel_path("lib/cat/x.js"))

    def test_rejected(self):
        for u in ["https://github.com/a/b/releases/download/v1/x.jar",   # 资产不在源码树
                  "https://api.x.com/provide/vod/https://github.com/a/b",
                  "https://gitee.com/a/b/raw/master/x.json",
                  "https://raw.githubusercontent.com/a/b/main",
                  ""]:
            self.assertIsNone(fm.gh_repo_ref_of(u), u)


class TestPlan(unittest.TestCase):
    def _needs(self, n, repo="a/b", ref="main", sub="lib"):
        return [("json", f"https://raw.githubusercontent.com/{repo}/{ref}/{sub}/f{i}.json",
                 f"org{i}") for i in range(n)]

    def test_threshold_and_order(self):
        needs = self._needs(4) + self._needs(2, repo="c/d") + \
            [("json", "https://raw.githubusercontent.com/e/f/main/x.json", "solo")]
        plan = fm.deps_git_plan(needs)
        self.assertEqual(list(plan)[0], ("a", "b", "main"), "缺得多的仓先做")
        self.assertNotIn(("e", "f", "main"), plan, "不足 DEPS_GIT_MIN_FILES 的不做")
        self.assertEqual(len(plan[("a", "b", "main")]), 4)


@unittest.skipUnless(HAS_GIT, "需要 git 可执行")
class TestGitBackfill(unittest.TestCase):
    """本地裸仓驱动真实 clone/sparse-checkout 路径（不联网）。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="dep-git-fixture-")
        cls.repo = os.path.join(cls.dir, "src")
        os.makedirs(os.path.join(cls.repo, "lib"))
        with open(os.path.join(cls.repo, "lib", "a.json"), "w", encoding="utf-8") as f:
            f.write('{"sites":[]}')
        with open(os.path.join(cls.repo, "lib", "b.js"), "w", encoding="utf-8") as f:
            f.write("export const x = 1;")
        _git(["init", "-q", "-b", "main"], cwd=cls.repo)
        _git(["-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], cwd=cls.repo)
        _git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], cwd=cls.repo)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self._url = fm._git_repo_url
        self._cache = dict(fm._git_probe_cache)
        fm._git_repo_url = lambda owner, repo: os.path.join(self.dir, "src")

    def tearDown(self):
        fm._git_repo_url = self._url
        fm._git_probe_cache.clear()
        fm._git_probe_cache.update(self._cache)

    def test_fetches_needed_blobs(self):
        needs = [("json", "https://raw.githubusercontent.com/o/r/main/lib/a.json", "org"),
                 ("js", "https://raw.githubusercontent.com/o/r/main/lib/b.js", "org"),
                 ("json", "https://raw.githubusercontent.com/o/r/main/lib/gone.json", "org")]
        got, st = fm.deps_git_backfill(needs)
        self.assertEqual(got[("org", needs[0][1])], b'{"sites":[]}')
        self.assertEqual(got[("org", needs[1][1])], b"export const x = 1;")
        self.assertNotIn(("org", needs[2][1]), got, "树里没有的路径不该出现")
        self.assertEqual(st["repos_ok"], 1)
        self.assertEqual(st["files"], 2)

    def test_traversal_never_read_from_disk(self):
        # 两个合法路径 + 一个穿越路径：合法照常取回，穿越的既不进 clone 清单也不进结果
        needs = [("json", "https://raw.githubusercontent.com/o/r/main/lib/a.json", "org"),
                 ("js", "https://raw.githubusercontent.com/o/r/main/lib/b.js", "org"),
                 ("json", "https://raw.githubusercontent.com/o/r/main/../../secret.json", "org")]
        got, st = fm.deps_git_backfill(needs)
        self.assertEqual(len(got), 2)
        self.assertNotIn(("org", needs[2][1]), got)
        self.assertEqual(st["groups"], 1, "两个合法路径应成组")

    def test_unknown_ref_falls_back_to_default_branch(self):
        needs = [("json", "https://raw.githubusercontent.com/o/r/main/lib/a.json", "org"),
                 ("js", "https://raw.githubusercontent.com/o/r/main/lib/b.js", "org")]
        # 把 ref 换成不存在的分支：clone -b 失败后应退回默认分支再取
        needs = [("json", u.replace("/main/", "/no-such-branch/"), o) for _k, u, o in needs]
        got, st = fm.deps_git_backfill(needs)
        self.assertEqual(st["repos_failed"], 0)
        self.assertEqual(len(got), 2, "退回默认分支后仍应取到文件")


class TestTarballTake(unittest.TestCase):
    def _tar(self, files):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, data in files.items():
                info = tarfile.TarInfo("repo-abc/" + name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    def test_whitelist_and_caps(self):
        big = b"x" * (fm.DEP_MAX_BYTES + 1)
        tar = self._tar({"lib/a.json": b"{}", "lib/b.js": b"//b", "lib/big.js": big,
                         "../evil": b"rm -rf"})
        got = fm.tarball_take_files(tar, {"lib/a.json", "lib/big.js", "../evil"})
        self.assertEqual(got, {"lib/a.json": b"{}"}, "超限的不收；白名单外的一律不取")

    def test_garbage_tar_returns_empty(self):
        self.assertEqual(fm.tarball_take_files(b"not a tar", {"x"}), {})

    def test_pick_filters_by_size_and_threshold(self):
        # 纯逻辑校验：体积未知/超阈值/数量不足都不该发起 tarball 下载
        calls = []
        orig_size, orig_fetch = fm.gh_repo_size_kb, fm.fetch_repo_tarball
        fm.gh_repo_size_kb = lambda o, r: None
        fm.fetch_repo_tarball = lambda o, r, ref: calls.append((o, r)) or None
        try:
            needs = [("json", f"https://raw.githubusercontent.com/a/b/main/x{i}.json", "o")
                     for i in range(5)]
            got, st = fm.deps_tarball_pick(needs)
            self.assertEqual((st["size_unknown"], st["repos_tried"], calls), (1, 0, []))
            fm.gh_repo_size_kb = lambda o, r: fm.DEPS_TARBALL_MAX_REPO_KB + 1
            got, st = fm.deps_tarball_pick(needs)
            self.assertEqual((st["too_big"], st["repos_tried"]), (5, 0))
            fm.gh_repo_size_kb = lambda o, r: 10
            small = [("json", "https://raw.githubusercontent.com/z/y/main/x.json", "o")]
            got, st = fm.deps_tarball_pick(small)
            self.assertEqual((st["below_threshold"], st["repos_tried"]), (1, 0))
        finally:
            fm.gh_repo_size_kb, fm.fetch_repo_tarball = orig_size, orig_fetch


if __name__ == "__main__":
    unittest.main()
