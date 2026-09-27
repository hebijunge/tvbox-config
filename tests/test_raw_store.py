"""raw_store 落库单测（2026-09-27 落库改造·纯逻辑必过）。

覆盖：
  · ingest 四态转移：new / changed / unchanged / restored（文件丢失补齐）
  · 上游删除保护：mark_deleted 只改清单绝不删文件；恢复（同内容 recovered /
    新内容 changed_recovered）
  · 账本模式（store_bytes=False）：不落字节、不归档、ent.ledger=True
  · history 归档：旧版入 history/<日>/、环形保留 RAW_HISTORY_KEEP
  · read_stored：字节留档可读、账本条目返回 None
  · 清单损坏容错：manifest.json 坏 → 当空清单处理
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import raw_store  # noqa: E402


def _tmp_store():
    return tempfile.mkdtemp(prefix="rawstore-test-")


def _load_manifest(store):
    with open(os.path.join(store, "manifest.json"), "r", encoding="utf-8") as f:
        return json.load(f)


class TestIngestTransitions(unittest.TestCase):
    def test_new_then_unchanged(self):
        st = _tmp_store()
        r1 = raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-27")
        self.assertEqual(r1["status"], "new")
        self.assertTrue(os.path.isfile(os.path.join(st, "a/1.txt")))
        r2 = raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-28")
        self.assertEqual(r2["status"], "unchanged")

    def test_changed_archives_old_version(self):
        st = _tmp_store()
        raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-27")
        r = raw_store.ingest(st, "k", "http://u/1.txt", b"BBB", rel="a/1.txt", now="2026-09-28")
        self.assertEqual(r["status"], "changed")
        old = os.path.join(st, "history", "2026-09-28", "a", "1.txt")
        self.assertTrue(os.path.isfile(old))
        with open(old, "rb") as f:
            self.assertEqual(f.read(), b"AAA")
        m = _load_manifest(st)
        hist = m["k"]["history"]
        self.assertEqual(hist[0]["date"], "2026-09-28")
        self.assertEqual(hist[0]["sha256"], raw_store.sha256_hex(b"AAA"))
        self.assertTrue(hist[0]["path"])

    def test_restored_when_file_lost(self):
        st = _tmp_store()
        raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-27")
        os.remove(os.path.join(st, "a/1.txt"))
        r = raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-28")
        self.assertEqual(r["status"], "restored")
        self.assertTrue(os.path.isfile(os.path.join(st, "a/1.txt")))

    def test_history_ring_keeps_limit(self):
        st = _tmp_store()
        for i in range(raw_store.HISTORY_KEEP + 3):
            raw_store.ingest(st, "k", "http://u/1.txt", bytes([i]), rel="a/1.txt",
                             now=f"2026-01-{(i % 28) + 1:02d}")
        m = _load_manifest(st)
        self.assertLessEqual(len(m["k"]["history"]), raw_store.HISTORY_KEEP)


class TestDeleteProtection(unittest.TestCase):
    def test_mark_deleted_keeps_file(self):
        st = _tmp_store()
        raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-27")
        fp = os.path.join(st, "a/1.txt")
        ent = raw_store.mark_deleted(st, "k", "HTTP 404", now="2026-09-28")
        self.assertEqual(ent["status"], "deleted_upstream")
        self.assertEqual(ent["deleted_at"], "2026-09-28")
        self.assertTrue(os.path.isfile(fp), "标记删除绝不能删本地文件")
        with open(fp, "rb") as f:
            self.assertEqual(f.read(), b"AAA")

    def test_mark_deleted_never_ingested_returns_none(self):
        st = _tmp_store()
        self.assertIsNone(raw_store.mark_deleted(st, "nope", "404", now="2026-09-28"))

    def test_recovered_same_content(self):
        st = _tmp_store()
        raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-27")
        raw_store.mark_deleted(st, "k", "404", now="2026-09-28")
        r = raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-29")
        self.assertEqual(r["status"], "recovered")
        m = _load_manifest(st)
        self.assertEqual(m["k"]["status"], "ok")

    def test_changed_recover_new_content(self):
        st = _tmp_store()
        raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-27")
        raw_store.mark_deleted(st, "k", "404", now="2026-09-28")
        r = raw_store.ingest(st, "k", "http://u/1.txt", b"BBB", rel="a/1.txt", now="2026-09-29")
        self.assertEqual(r["status"], "changed_recovered")
        m = _load_manifest(st)
        self.assertEqual(m["k"]["status"], "ok")
        self.assertNotIn("deleted_at", m["k"])

    def test_read_stored_roundtrip(self):
        st = _tmp_store()
        raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-27")
        self.assertEqual(raw_store.read_stored(st, "k"), b"AAA")
        self.assertIsNone(raw_store.read_stored(st, "absent"))


class TestLedgerMode(unittest.TestCase):
    def test_ledger_no_bytes_written(self):
        st = _tmp_store()
        r = raw_store.ingest(st, "k", "http://u/x.js", b"CODE", rel="o/x.js",
                             now="2026-09-27", store_bytes=False)
        self.assertEqual(r["status"], "new")
        self.assertFalse(os.path.exists(os.path.join(st, "o/x.js")), "账本模式不得落字节")
        m = _load_manifest(st)
        self.assertTrue(m["k"].get("ledger"))
        self.assertEqual(m["k"]["sha256"], raw_store.sha256_hex(b"CODE"))
        self.assertIsNone(raw_store.read_stored(st, "k"), "账本条目 read_stored 应返回 None")

    def test_ledger_change_records_history_without_bytes(self):
        st = _tmp_store()
        raw_store.ingest(st, "k", "http://u/x.js", b"V1", rel="o/x.js",
                         now="2026-09-27", store_bytes=False)
        r = raw_store.ingest(st, "k", "http://u/x.js", b"V2", rel="o/x.js",
                             now="2026-09-28", store_bytes=False)
        self.assertEqual(r["status"], "changed")
        self.assertFalse(os.path.exists(os.path.join(st, "history")), "账本模式不得归档字节")
        m = _load_manifest(st)
        self.assertEqual(m["k"]["history"][0]["path"], None)
        self.assertEqual(m["k"]["sha256"], raw_store.sha256_hex(b"V2"))

    def test_ledger_unchanged_then_deleted(self):
        st = _tmp_store()
        raw_store.ingest(st, "k", "http://u/x.js", b"V1", rel="o/x.js",
                         now="2026-09-27", store_bytes=False)
        r = raw_store.ingest(st, "k", "http://u/x.js", b"V1", rel="o/x.js",
                             now="2026-09-28", store_bytes=False)
        self.assertEqual(r["status"], "unchanged")
        ent = raw_store.mark_deleted(st, "k", "404", now="2026-09-29")
        self.assertEqual(ent["status"], "deleted_upstream")


class TestManifestCorruption(unittest.TestCase):
    def test_broken_manifest_treated_as_empty(self):
        st = _tmp_store()
        with open(os.path.join(st, "manifest.json"), "w", encoding="utf-8") as f:
            f.write("{broken json")
        r = raw_store.ingest(st, "k", "http://u/1.txt", b"AAA", rel="a/1.txt", now="2026-09-27")
        self.assertEqual(r["status"], "new")

    def test_summarize(self):
        st = _tmp_store()
        raw_store.ingest(st, "a", "http://u/a", b"1", rel="a.txt", now="2026-09-27")
        raw_store.ingest(st, "b", "http://u/b", b"2", rel="b.txt", now="2026-09-27")
        raw_store.mark_deleted(st, "b", "404", now="2026-09-28")
        s = raw_store.summarize(st)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["ok"], 1)
        self.assertEqual(s["deleted_upstream"], 1)


class TestRunTriggerStatuses(unittest.TestCase):
    def test_unchanged_and_deleted_do_not_trigger_rerun(self):
        self.assertNotIn("unchanged", raw_store.RUN_TRIGGER_STATUSES)
        self.assertNotIn("deleted_upstream", raw_store.RUN_TRIGGER_STATUSES)
        for s in ("new", "changed", "changed_recovered", "restored"):
            self.assertIn(s, raw_store.RUN_TRIGGER_STATUSES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
