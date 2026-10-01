# -*- coding: utf-8 -*-
"""store.prune_interfaces：产物里已不存在的幽灵接口行必须能被清掉。

main 库实测 8023 行里 3739 行（46%）早已不在 tvbox.json（key 规范化前带空格的旧名居多），
其中 2553 行挂 unknown——日报"unknown 5655"近半是幽灵。--prune 过去只清 checks 历史。
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import store  # noqa: E402


def _ifc(conn, key, seen_days_ago, name="n", api="http://x/api.php/vod"):
    when = (datetime.now() - timedelta(days=seen_days_ago)).isoformat(timespec="seconds")
    conn.execute("INSERT OR REPLACE INTO interfaces (key,name,api,type,health,first_seen,"
                 "last_seen,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                 (key, name, api, 1, "unknown", when, when, when))
    conn.execute("INSERT INTO checks (key, checked_at, ok, level, reason, probe) "
                 "VALUES (?,?,?,?,?,?)", (key, when, 0, None, "x", "sites_probe.json"))
    conn.commit()


class PruneInterfacesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(os.path.join(self.tmp.name, "t.db"))
        self.addCleanup(self.conn.close)      # Windows：连接不先关，临时目录删不掉

    def _keys(self):
        return {r["key"] for r in self.conn.execute("SELECT key FROM interfaces")}

    def test_stale_rows_and_their_checks_are_dropped(self):
        _ifc(self.conn, " bili_哔哩", 40)      # 产物里已不存在的旧 key（带空格）
        _ifc(self.conn, "fresh", 1)            # 本轮仍在的站
        gone = store.prune_interfaces(self.conn, grace_days=7)
        self.assertEqual(gone, 1)
        self.assertEqual(self._keys(), {"fresh"})
        left = [r[0] for r in self.conn.execute("SELECT key FROM checks")]
        self.assertEqual(left, ["fresh"], "幽灵行的检测历史要一起删，否则留下无主记录")

    def test_fresh_rows_survive_and_grace_window_respected(self):
        _ifc(self.conn, "a", 6)
        _ifc(self.conn, "b", 8)
        self.assertEqual(store.prune_interfaces(self.conn, grace_days=7), 1)
        self.assertEqual(self._keys(), {"a"})

    def test_blank_last_seen_is_never_pruned(self):
        """没有 last_seen 的行不动——宁可留着也不误删台账。"""
        when = (datetime.now() - timedelta(days=99)).isoformat(timespec="seconds")
        self.conn.execute("INSERT INTO interfaces (key,name,api,type,health,first_seen,"
                          "last_seen,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                          ("ghost", "n", "http://x", 1, "unknown", when, "", when))
        self.conn.commit()
        self.assertEqual(store.prune_interfaces(self.conn, grace_days=7), 0)
        self.assertEqual(self._keys(), {"ghost"})

    def test_stats_reports_stale_count(self):
        _ifc(self.conn, " bili_哔哩", 40)
        _ifc(self.conn, "fresh", 1)
        st = store.stats(self.conn)
        self.assertEqual(st["interfaces"], 2)
        self.assertEqual(st["interfaces_stale"], 1)


if __name__ == "__main__":
    unittest.main()
