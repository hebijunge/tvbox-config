# -*- coding: utf-8 -*-
"""探针撤回后必须重算健康：证据没了，结论不能继续挂着。

起因（2026-10-02 实测）：真机合并口径收紧后 csp_probe 的 C0 从 817 降到 10，
但 CI 跑完 daily 的 dead 纹丝不动（1054→1055）。根因在库里不在产物里——
record_check 用 MAX(health_rank) 且浅探针不覆盖深探针，这套闸门在「证据还在」时
是对的；某站从快照探针里消失之后，那条 dead 成了没人认领的结论，没有任何路径能摘掉它。
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import store  # noqa: E402


def _probe(tmp, name, rows, stamp):
    """写一份探针产物（generated_at 决定批次，同一批次重复导入应当幂等）。"""
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"generated_at": stamp, "sites": rows}, f, ensure_ascii=False)
    return p


def _today(minute=0):
    return datetime.now().replace(minute=minute, second=0, microsecond=0).isoformat(timespec="seconds")


class RetractCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(os.path.join(self.tmp.name, "t.db"))
        self.addCleanup(self.conn.close)
        self.dir = self.tmp.name

    def add_iface(self, *keys):
        for k in keys:
            self.conn.execute("INSERT OR REPLACE INTO interfaces (key,name,api,type,health,"
                              "health_rank,first_seen,last_seen,updated_at)"
                              " VALUES (?,?,'csp_X',1,'unknown',0,'now','now','now')", (k, k))
        self.conn.commit()

    def health(self, key):
        r = self.conn.execute("SELECT health, level, health_rank FROM interfaces WHERE key=?",
                              (key,)).fetchone()
        return (r["health"], r["level"], r["health_rank"]) if r else None

    def test_dropped_key_stops_being_dead(self):
        self.add_iface("a", "b")
        t1 = _today(1)
        store.ingest_probe(self.conn, _probe(self.dir, "csp_probe.json",
                                             [{"key": "a", "level": "C0"},
                                              {"key": "b", "level": "C0"}], t1))
        self.assertEqual(self.health("a")[0], "dead")
        # 口径收紧：b 还在（静态真有证据），a 被洗掉 → a 必须回到未判定
        t2 = _today(2)
        store.ingest_probe(self.conn, _probe(self.dir, "csp_probe.json",
                                             [{"key": "b", "level": "C0"}], t2))
        self.assertEqual(self.health("a"), ("unknown", None, 0), "撤回后该站应回到未判定")
        self.assertEqual(self.health("b")[0], "dead", "仍有证据的站不受影响")

    def test_falls_back_to_other_probe(self):
        self.add_iface("a")
        store.ingest_probe(self.conn, _probe(self.dir, "sites_probe.json",
                                             [{"key": "a", "level": "L2"}], _today(1)))
        store.ingest_probe(self.conn, _probe(self.dir, "csp_probe.json",
                                             [{"key": "a", "level": "C0"}], _today(2)))
        self.assertEqual(self.health("a")[0], "dead", "深探针覆盖浅探针")
        store.ingest_probe(self.conn, _probe(self.dir, "csp_probe.json", [], _today(3)))
        self.assertEqual(self.health("a"), ("degraded", "L2", 3),
                         "深证据撤回应回落到浅证据，而不是抹成未判定")

    def test_reimport_same_batch_is_idempotent(self):
        self.add_iface("a")
        t = _today(1)
        p = _probe(self.dir, "csp_probe.json", [{"key": "a", "level": "C0"}], t)
        store.ingest_probe(self.conn, p)
        store.ingest_probe(self.conn, p)
        n = self.conn.execute("SELECT COUNT(*) FROM checks WHERE probe='csp_probe.json'").fetchone()[0]
        self.assertEqual(n, 1, "同批次重复导入不能翻倍，也不能被当成撤回")
        self.assertEqual(self.health("a")[0], "dead")

    def test_rotating_probe_does_not_retract(self):
        """sites_probe 走配额轮转：这轮没排到 ≠ 结论作废。"""
        self.add_iface("a")
        store.ingest_probe(self.conn, _probe(self.dir, "sites_probe.json",
                                             [{"key": "a", "level": "L3"}], _today(1)))
        store.ingest_probe(self.conn, _probe(self.dir, "sites_probe.json",
                                             [{"key": "z", "level": "L3"}], _today(2)))
        self.assertEqual(self.health("a")[0], "healthy",
                         "轮转探针的历史结论必须留着")

    def test_snapshot_probes_list_guarded(self):
        self.assertIn("csp_probe.json", store.SNAPSHOT_PROBES)
        self.assertNotIn("sites_probe.json", store.SNAPSHOT_PROBES)
        self.assertNotIn("spider_probe.json", store.SNAPSHOT_PROBES)


if __name__ == "__main__":
    unittest.main()
