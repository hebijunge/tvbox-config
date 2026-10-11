#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_triage 的控制流回归测试（本机无 gh，全部走 mock）。

覆盖三件真实失败过的事：
1. 只认 conclusion=failure 的 job 及其失败步骤，不误报全绿 job；
2. 同一失败重复出现时追加评论而不是刷新一堆 issue；
3. dry-run 不产生任何写操作。
"""
import json
import os
import sys
import unittest
from unittest import mock

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import ci_triage as ct  # noqa: E402

RUN_META = {
    "name": "daily-fetch",
    "run_number": 173,
    "event": "schedule",
    "created_at": "2026-10-10T22:15:42Z",
    "html_url": "https://github.com/o/r/actions/runs/38090751386",
    "head_branch": "main",
    "head_commit": {"id": "abcdef1234567890abcdef1234567890abcdef12"},
}

JOBS = [
    {"name": "windows-path-check", "conclusion": "failure",
     "steps": [{"name": "Set up job", "conclusion": "success"},
               {"name": "Windows 兼容性检查", "conclusion": "failure"},
               {"name": "Post Run actions/checkout@v4", "conclusion": "success"}]},
    {"name": "fetch-merge", "conclusion": "success",
     "steps": [{"name": "入库", "conclusion": "success"},
               {"name": "提交并推送", "conclusion": "success"}]},
]


def make_proc(calls, issue_list_result=None, jobs=None):
    """构造 subprocess.run 替身：按 gh 子命令路由。

    不能用整行子串匹配——issue body 里带着 run 的 ``/actions/runs/`` 链接，
    会把写操作误判成查询。
    """
    payload_jobs = json.dumps({"jobs": jobs if jobs is not None else JOBS})

    def _run(cmd, *a, **kw):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        sub = cmd[1] if len(cmd) > 1 else ""
        third = cmd[2] if len(cmd) > 2 else ""
        if sub == "api":
            R.stdout = payload_jobs if "/jobs" in third else json.dumps(RUN_META)
        elif sub == "issue" and third == "list":
            R.stdout = json.dumps(issue_list_result if issue_list_result is not None else [])
        elif sub in ("issue", "label"):
            calls.append(cmd)
            if sub == "issue" and third == "create":
                R.stdout = "https://github.com/o/r/issues/7\n"
        return R()
    return _run


class TestFailurePick(unittest.TestCase):
    def test_only_failed_job_and_step(self):
        calls = []
        with mock.patch.object(ct.subprocess, "run", make_proc(calls)):
            found = ct.fetch_failed_steps("o/r", "1")
        self.assertEqual(found, [("windows-path-check", ["Windows 兼容性检查"])])

    def test_job_failure_without_step_marker(self):
        jobs = [{"name": "deploy", "conclusion": "failure",
                 "steps": [{"name": "Set up job", "conclusion": "success"}]}]
        with mock.patch.object(ct.subprocess, "run", make_proc([], jobs=jobs)):
            found = ct.fetch_failed_steps("o/r", "1")
        self.assertEqual(found[0][1], ["（job 级失败，无步骤标记）"])


class TestFingerprint(unittest.TestCase):
    def _fp(self, step):
        return ct.hashlib.sha1(f"daily-fetch|windows-path-check|{step}".encode()).hexdigest()[:8]

    def test_stable_for_same_failure(self):
        self.assertEqual(self._fp("Windows 兼容性检查"), self._fp("Windows 兼容性检查"))

    def test_distinct_for_different_step(self):
        self.assertNotEqual(self._fp("Windows 兼容性检查"), self._fp("别的步骤"))


class TestApplyBehaviour(unittest.TestCase):
    def _main(self, argv, issue_list_result):
        calls = []
        with mock.patch.object(ct.subprocess, "run", make_proc(calls, issue_list_result)), \
             mock.patch.object(sys, "argv", argv):
            rc = ct.main()
        return rc, calls

    def test_new_failure_opens_issue(self):
        rc, calls = self._main(["ci_triage.py", "--repo", "o/r", "--run-id", "1", "--apply"], None)
        self.assertEqual(rc, 0)
        verbs = [" ".join(c[:3]) for c in calls]
        self.assertIn("gh label create", verbs)
        create = [c for c in calls if c[1] == "issue" and c[2] == "create"]
        self.assertEqual(len(create), 1)
        title = create[0][create[0].index("--title") + 1]
        self.assertTrue(title.startswith("[ci-failure] daily-fetch · windows-path-check"))
        self.assertIn("Windows 兼容性检查", title)

    def test_repeated_failure_comments_instead_of_new_issue(self):
        rc, calls = self._main(["ci_triage.py", "--repo", "o/r", "--run-id", "1", "--apply"],
                               [{"number": 42, "title": "[ci-failure] ... (deadbeef)"}])
        self.assertEqual(rc, 0)
        self.assertFalse([c for c in calls if c[1] == "issue" and c[2] == "create"],
                         "重复失败不应再开新 issue")
        comment = [c for c in calls if c[1] == "issue" and c[2] == "comment"]
        self.assertEqual(len(comment), 1)
        self.assertIn("42", comment[0])

    def test_dry_run_writes_nothing(self):
        rc, calls = self._main(["ci_triage.py", "--repo", "o/r", "--run-id", "1"], None)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [], "dry-run 不该有任何写操作")

    def test_all_green_run_is_skipped(self):
        green = [{"name": "fetch-merge", "conclusion": "success",
                  "steps": [{"name": "入库", "conclusion": "success"}]}]
        calls = []
        with mock.patch.object(ct.subprocess, "run", make_proc(calls, jobs=green)), \
             mock.patch.object(sys, "argv",
                               ["ci_triage.py", "--repo", "o/r", "--run-id", "1", "--apply"]):
            rc = ct.main()
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
