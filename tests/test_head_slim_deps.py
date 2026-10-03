"""head_slim_deps 的 dry-run / git rm 边界测试（stdlib unittest + 真 git）。

动机：head_slim_deps 是"从 HEAD 移除无引用 deps"的候选清单生成器，一旦
--execute 就会真 git rm；这里钉死它的三条判据：
  1) 引用口径完全走 dep_refs（7 主产物 ∪ stores ∪ manifest 账本），
     不能自己另算一份；
  2) 只有"未在 git log 最近 N 天出现过"的才进候选（活跃 dep 排除）；
  3) --execute 才 git rm，dry-run 只写清单。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import head_slim_deps  # noqa: E402


def _git(cwd, *args, **env):
    e = os.environ.copy()
    e.update({
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t",
    })
    e.update(env)
    subprocess.run(["git", *args], cwd=cwd, check=True, env=e)


def _commit_with_date(cwd, date_iso):
    """把 HEAD commit 的 author/committer date 强制设为 date_iso，
    用来测 min_age_days 的时间闸门。"""
    env = {"GIT_AUTHOR_DATE": date_iso, "GIT_COMMITTER_DATE": date_iso}
    e = os.environ.copy()
    e.update({"GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
              "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"})
    e.update(env)
    subprocess.run(["git", "commit", "--amend", "--no-edit",
                    "--date", date_iso], cwd=cwd, check=True, env=e)


def _write(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TestHeadSlim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="head-slim-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        _git(self.tmp, "init", "-q", "-b", "main")

    def _init_repo(self):
        # 提交一批历史 deps，日期设为 60 天前（超过默认 30 天闸门）
        _write(os.path.join(self.tmp, "deps", "old_a.js"), "old_a")
        _write(os.path.join(self.tmp, "deps", "old_b.js"), "old_b")
        _write(os.path.join(self.tmp, "deps", "old_orphan.js"), "orphan")
        _write(os.path.join(self.tmp, "tvbox.json"),
               json.dumps({"sites": [{"api": "./deps/old_a.js"}]}))
        _write(os.path.join(self.tmp, "deps", "manifest.json"),
               json.dumps({"u|b": {"url": "u", "origin": "u",
                                    "local": "deps/old_b.js"}}))
        _git(self.tmp, "add", ".")
        _git(self.tmp, "commit", "-q", "-m", "old")
        _commit_with_date(self.tmp, "2020-01-01T00:00:00+00:00")

    def test_default_dry_run_lists_only_orphan(self):
        self._init_repo()
        cand = head_slim_deps.build_candidates(self.tmp, min_age_days=30)
        self.assertEqual(cand["paths"], ["deps/old_orphan.js"],
                         "只有既无引用、又不最近活跃的文件才算候选")
        self.assertFalse(cand["paths"] == [])
        self.assertGreaterEqual(cand["tracked_total"], 4)

    def test_recent_touch_excludes_from_candidates(self):
        # 60 天前一批历史，然后 3 天前新增 old_orphan.js —— 即使 dep_refs 无引用，
        # 也应因"最近有改动"被排除。
        self._init_repo()
        _write(os.path.join(self.tmp, "deps", "recent.js"), "new")
        _git(self.tmp, "add", ".")
        _git(self.tmp, "commit", "-q", "-m", "recent")
        cand = head_slim_deps.build_candidates(self.tmp, min_age_days=30)
        self.assertNotIn("deps/recent.js", cand["paths"])
        self.assertIn("deps/old_orphan.js", cand["paths"])

    def test_nonascii_paths_are_not_false_candidates(self):
        """回归钉子：git 文本输出会把非 ASCII 路径 C-引号化，中文名整批误判成孤儿。

        2026-10-04 实测：HEAD 里 14716 个 deps 路径有 **6927 个**是中文/非 ASCII 名，
        `git ls-files`（不带 -z）按 core.quotepath 把它们输出成
        `"deps/auto/.../\\347\\234\\213.js"`，而 dep_refs 的引用是从产物文本里正则出来的
        真路径——两边永远匹配不上，候选数从真实 11391 虚高到 12821，其中约 1430 个是
        产物真在引用的活文件。照那个清单 --execute 就是删功能。
        `tracked_deps` / `recently_touched_deps` 都必须走 `-z`。
        """
        _write(os.path.join(self.tmp, "deps", "看.js"), "live")
        _write(os.path.join(self.tmp, "deps", "孤儿.js"), "dead")
        _write(os.path.join(self.tmp, "tvbox.json"),
               json.dumps({"sites": [{"api": "./deps/看.js"}]}, ensure_ascii=False))
        _write(os.path.join(self.tmp, "deps", "manifest.json"), "{}")
        _git(self.tmp, "add", ".")
        _git(self.tmp, "commit", "-q", "-m", "nonascii")
        _commit_with_date(self.tmp, "2020-01-01T00:00:00+00:00")

        tracked = head_slim_deps.tracked_deps(self.tmp)
        self.assertIn("deps/看.js", tracked, "中文名要以真路径出现")
        self.assertFalse([p for p in tracked if p.startswith('"')],
                         "不许出现 C-引号形式的路径")

        # 2020 那次提交在 3650 天内 -> 两个中文名都该被认成"最近动过"
        touched = head_slim_deps.recently_touched_deps(3650, self.tmp)
        self.assertIn("deps/看.js", touched)
        self.assertIn("deps/孤儿.js", touched)
        self.assertEqual(head_slim_deps.build_candidates(self.tmp, min_age_days=3650)["paths"], [])

        # 闸门收紧到 30 天：2020 的提交出窗，只剩真孤儿
        cand = head_slim_deps.build_candidates(self.tmp, min_age_days=30)
        self.assertEqual(set(cand["paths"]), {"deps/孤儿.js"})

    def test_execute_does_not_run_without_flag(self):
        # dry-run 绝不能改索引
        self._init_repo()
        before = head_slim_deps.tracked_deps(self.tmp)
        old = sys.argv
        sys.argv = ["head_slim_deps", "--repo", self.tmp]
        try:
            head_slim_deps.main()
        finally:
            sys.argv = old
        after = head_slim_deps.tracked_deps(self.tmp)
        self.assertEqual(before, after)

    def test_refs_union_includes_adult_stores_and_manifest(self):
        # 覆盖 PR#36 三处口径统一后 head_slim 也应看到 adult.json / stores 的引用
        self._init_repo()
        _write(os.path.join(self.tmp, "adult.json"),
               json.dumps({"sites": [{"api": "./deps/old_orphan.js"}]}))
        _git(self.tmp, "add", ".")
        _git(self.tmp, "commit", "-q", "-m", "adult")
        _commit_with_date(self.tmp, "2020-01-01T00:00:00+00:00")
        cand = head_slim_deps.build_candidates(self.tmp, min_age_days=30)
        self.assertEqual(cand["paths"], [],
                         "adult.json 里引用的 dep 不能进候选")

    def test_only_dir_scopes_candidates(self):
        # 分批推进用：--only-dir 应把结果限制到指定前缀，其他目录同类候选被排除。
        self._init_repo()
        _write(os.path.join(self.tmp, "deps", "external", "x.txt"), "x")
        _write(os.path.join(self.tmp, "deps", "jar", "y.jar"), "y")
        _git(self.tmp, "add", ".")
        _git(self.tmp, "commit", "-q", "-m", "add more")
        _commit_with_date(self.tmp, "2020-01-01T00:00:00+00:00")
        cand_ext = head_slim_deps.build_candidates(
            self.tmp, min_age_days=30, only_dir="deps/external/")
        self.assertEqual(cand_ext["paths"], ["deps/external/x.txt"])
        cand_all = head_slim_deps.build_candidates(self.tmp, min_age_days=30)
        self.assertIn("deps/external/x.txt", cand_all["paths"])
        self.assertIn("deps/jar/y.jar", cand_all["paths"])
        self.assertIn("deps/old_orphan.js", cand_all["paths"])


if __name__ == "__main__":
    unittest.main()
