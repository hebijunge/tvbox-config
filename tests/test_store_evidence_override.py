# -*- coding: utf-8 -*-
"""带结构性证据的结论必须能改判，否则浅探针的证据永远进不了产物。

起因（2026-10-02 实测）：把 `S0` 收进 `_DEAD` 后重灌 main 的真库，26 条带证据的 js S0
里有 **25 条仍然挂着 unknown**。根因是 `record_check` 的同级闸门：
`_HEALTH_ORDER = {healthy:3, degraded:2, unknown:1, dead:0}`，dead 排在 unknown 之后，
于是"同级但不更优就保留原结论"把证据判死也一起挡住了——这条闸门本来是防浅探针把
好消息刷坏的，不该挡掉真证据。
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import store  # noqa: E402

EV = {"ext_dep": "remote-rule-unreachable", "cause": "gone-404", "url": "https://a/x.js", "tried": 2}


def _probe(tmp, name, rows, stamp):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"generated_at": stamp, "sites": rows}, f, ensure_ascii=False)
    return p


def _now():
    return datetime.now().isoformat(timespec="seconds")


class EvidenceOverride(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(os.path.join(self.tmp.name, "t.db"))
        self.addCleanup(self.conn.close)
        store.upsert_interface(self.conn, {"key": "K1", "name": "甲", "api": "csp_X"})
        store.upsert_interface(self.conn, {"key": "K2", "name": "乙", "api": "csp_Y"})
        store.upsert_interface(self.conn, {"key": "K3", "name": "丙", "api": "csp_Z"})
        self.conn.commit()

    def health(self, key):
        r = self.conn.execute("SELECT health, level FROM interfaces WHERE key=?", (key,)).fetchone()
        return r["health"], r["level"]

    def test_evidenceless_same_priority_still_blocked(self):
        """没有证据的浅结论不许把 unknown 刷成 dead——这条闸门必须留着（824 假死的教训）。"""
        store.record_check(self.conn, "K1", level="S0", reason="规则源取不到",
                           probe="js_probe.json", checked_at=_now())
        self.conn.commit()
        self.assertEqual("unknown", self.health("K1")[0])

    def test_evidence_backed_same_priority_overrides(self):
        store.record_check(self.conn, "K2", level="S0", reason="远程规则已亡：gone-404",
                           probe="js_probe.json", checked_at=_now(), evidence=EV)
        self.conn.commit()
        self.assertEqual(("dead", "S0"), self.health("K2"))

    def test_deeper_probe_verdict_not_overridden_by_shallow_evidence(self):
        """更深的结论（csp pri=4）不能被浅探针（js pri=2）的证据改写，哪怕带证据。"""
        store.record_check(self.conn, "K3", level="C3", probe="csp_probe.json", checked_at=_now())
        self.conn.commit()
        self.assertEqual("healthy", self.health("K3")[0])
        store.record_check(self.conn, "K3", level="S0", probe="js_probe.json",
                           checked_at=_now(), evidence=EV)
        self.conn.commit()
        self.assertEqual("healthy", self.health("K3")[0], "新证据更浅：只记历史")

    def test_ingest_passes_evidence_through(self):
        """产物里的 evidence 字段要真的传到 record_check（否则改动只活在函数签名上）。"""
        p = _probe(self.tmp.name, "js_probe.json", [
            {"key": "K1", "level": "S0", "reason": "远程规则已亡：gone-404", "evidence": EV},
            {"key": "K2", "level": "S0", "reason": "规则源取不到（老口径无证据）"},
        ], _now())
        store.ingest_probe(self.conn, p)
        self.assertEqual("dead", self.health("K1")[0])
        self.assertEqual("unknown", self.health("K2")[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
