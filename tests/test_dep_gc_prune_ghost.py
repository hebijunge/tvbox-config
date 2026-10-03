"""dep_gc --prune-manifest 剪幽灵账本的判据测试。

2026-10-03 PR#41 CI 后发现：daily.yml 里 `--prune-manifest --apply` 早已存在
（P1-2 已合），但**默认 `--min-idle-days 3` 拦住了所有剪除**——fetch_merge 每
天重写 rec 的 `updated_at`、idle_days 恒 <3，账本累积到 9000+ 剪不动。
真正的判据是"ref_count=0 ∧ 磁盘文件不存在"，`idle>=3` 只是防 fetch_merge
中间瞬态；daily 步骤在完整性闸门之后跑、此时"文件不存在"就是真死。
治本 = daily.yml 传 `--min-idle-days 0`。这里钉死剪/不剪的四条边界。
"""

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import dep_gc  # noqa: E402


def _args(manifest_path, min_idle_days=0.0, apply=False):
    return argparse.Namespace(
        manifest=manifest_path,
        min_idle_days=min_idle_days,
        apply=apply,
    )


def _capture(prune_args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        dep_gc.prune_manifest(prune_args)
    return buf.getvalue()


class TestPruneManifestGhosts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dep-gc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mf = os.path.join(self.tmp, "manifest.json")

    def _write_manifest(self, recs):
        # recs: list of (key, url, local, ref_count, updated_at_offset_days)
        doc = {}
        for key, local, ref_count, days_ago in recs:
            upd = time.strftime("%Y-%m-%d",
                                 time.gmtime(time.time() - days_ago * 86400))
            doc[key] = {"url": key, "origin": "o", "local": local,
                        "ref_count": ref_count, "updated_at": upd}
        with open(self.mf, "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def test_prunes_ghost_when_min_idle_zero(self):
        # 磁盘上只留 live 那份；ghost 那份文件缺失
        os.makedirs(os.path.dirname(os.path.join(self.tmp, "deps/live.js")), exist_ok=True)
        with open(os.path.join(self.tmp, "deps/live.js"), "w") as f:
            f.write("x")
        self._write_manifest([
            ("u|live", os.path.join(self.tmp, "deps/live.js"), 0, 0),
            ("u|ghost", os.path.join(self.tmp, "deps/ghost.js"), 0, 0),
        ])
        out = _capture(_args(self.mf, min_idle_days=0.0, apply=True))
        self.assertIn("1 条", out, "ghost 应被剪")
        after = json.load(open(self.mf, encoding="utf-8"))
        self.assertIn("u|live", after)
        self.assertNotIn("u|ghost", after)

    def test_keeps_records_with_file_on_disk(self):
        # 文件在磁盘 → 不剪，即使 ref_count=0 + idle=0
        with open(os.path.join(self.tmp, "deps.js"), "w") as f:
            f.write("x")
        self._write_manifest([
            ("u|keep", os.path.join(self.tmp, "deps.js"), 0, 0),
        ])
        out = _capture(_args(self.mf, min_idle_days=0.0, apply=True))
        self.assertIn("0 条", out)
        after = json.load(open(self.mf, encoding="utf-8"))
        self.assertIn("u|keep", after)

    def test_keeps_records_with_ref_count_positive(self):
        # ref_count>0 意味着还有消费方在引用，即便文件已消失也不动账本
        # （fetch_merge 下轮命中 manifest-cache 时会重下、不该被账本瘦身干扰）
        self._write_manifest([
            ("u|ref", os.path.join(self.tmp, "not-exist.js"), 3, 0),
        ])
        out = _capture(_args(self.mf, min_idle_days=0.0, apply=True))
        self.assertIn("0 条", out)
        after = json.load(open(self.mf, encoding="utf-8"))
        self.assertIn("u|ref", after)

    def test_min_idle_days_still_respected_when_positive(self):
        # min_idle_days>0 时新记录（updated_at=今天）应被门槛拦住，
        # 保护 daily 中间的瞬态。这条测试证明"改成 0 是撤门槛、不是删逻辑"。
        self._write_manifest([
            ("u|new", os.path.join(self.tmp, "gone.js"), 0, 0),  # idle=0
        ])
        out = _capture(_args(self.mf, min_idle_days=3.0, apply=True))
        self.assertIn("0 条", out)
        after = json.load(open(self.mf, encoding="utf-8"))
        self.assertIn("u|new", after,
                        "min_idle_days=3 时 idle=0 的新记录不能被剪")

    def test_backup_written_when_apply(self):
        # --apply 会先备份 .pre_gc；记忆里说 rollback 依赖这个
        self._write_manifest([
            ("u|ghost", os.path.join(self.tmp, "gone.js"), 0, 0),
        ])
        _capture(_args(self.mf, min_idle_days=0.0, apply=True))
        self.assertTrue(os.path.isfile(self.mf + ".pre_gc"),
                        "prune --apply 必须先写 .pre_gc 备份")


if __name__ == "__main__":
    unittest.main()
