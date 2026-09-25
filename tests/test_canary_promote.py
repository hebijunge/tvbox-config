"""2026-09-25 canary 晋升（P1-B）单测。

覆盖（docs/iptvorg-adapter-plan.md §8 验证清单）：
- 模拟 7 天 probe_history 全成功 -> admitted=true
- 模拟 7 天 probe_history 含 1 次失败 -> admitted=false（容错 0/7）
- 命中率 <60% -> admitted=false
- labels 反证 Geo-blocked / Not 24/7 -> admitted=false（与历史无关）
- 稳定天数不足 -> admitted=false
- 连续 21 天未通过 -> 进 rejected
- 晋升产物为标准上游形态（source=iptv-org）
- looks_like_stream：m3u8/TS/AAC 放行，HTML/JSON 拒
"""
import sys, os, unittest, tempfile, json, shutil
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import canary_promote as cp


def hist(days, fails_at=(), dates_from="2026-09-01"):
    """生成 days 天历史，fails_at 里的天数下标记为失败。"""
    d0 = datetime.strptime(dates_from, "%Y-%m-%d")
    out = []
    for i in range(days):
        out.append({"date": (d0 + timedelta(days=i)).strftime("%Y-%m-%d"),
                    "success": i not in fails_at, "latency_ms": 400, "via": "t"})
    return out


def entry(labels=None, history=None, admitted=False):
    return {"stream_id": "s:::x", "iptv_channel_id": "x", "channel_name": "X",
            "title": "X", "url": "http://u", "headers": {}, "quality": None,
            "labels": labels or [], "probe_history": history or [],
            "admitted": admitted, "admit_date": None, "reject_reason": None}


class TestGates(unittest.TestCase):
    def test_7_days_all_success_admits(self):
        ok, reason = cp.gate_verdict(entry(history=hist(7)))
        self.assertTrue(ok, reason)

    def test_more_than_7_uses_recent_window(self):
        ok, _ = cp.gate_verdict(entry(history=hist(12)))
        self.assertTrue(ok)

    def test_one_failure_rejects_default_tolerance(self):
        ok, reason = cp.gate_verdict(entry(history=hist(7, fails_at={3})))
        self.assertFalse(ok)
        self.assertIn("失败", reason)

    def test_tolerance_1_of_7_relaxed(self):
        ok, _ = cp.gate_verdict(entry(history=hist(7, fails_at={3})), max_failures=1)
        self.assertTrue(ok)

    def test_hit_rate_below_60(self):
        h = hist(7, fails_at={0, 1, 2, 3, 4})  # 成功率 2/7
        ok, reason = cp.gate_verdict(entry(history=h), max_failures=5)
        self.assertFalse(ok)
        self.assertIn("命中率", reason)

    def test_insufficient_days(self):
        ok, reason = cp.gate_verdict(entry(history=hist(6)))
        self.assertFalse(ok)
        self.assertIn("稳定天数不足", reason)

    def test_geo_blocked_label_rejects(self):
        ok, reason = cp.gate_verdict(entry(labels=["Geo-blocked"], history=hist(7)))
        self.assertFalse(ok)
        self.assertIn("Geo-blocked", reason)

    def test_not_247_label_rejects(self):
        ok, reason = cp.gate_verdict(entry(labels=["Not 24/7"], history=hist(7)))
        self.assertFalse(ok)

    def test_label_check_precedes_history(self):
        ok, _ = cp.gate_verdict(entry(labels=["Geo-blocked"], history=hist(2)))
        self.assertFalse(ok)


class TestPromoteRun(unittest.TestCase):
    def test_promote_writes_upstream_and_rejected(self):
        tmp = tempfile.mkdtemp()
        try:
            cp.PROMOTED_PATH = os.path.join(tmp, "up", "iptvorg.normal.json")
            cp.REJECTED_PATH = os.path.join(tmp, "rej", "iptvorg_rejected.json")
            pool_path = os.path.join(tmp, "canary", "iptvorg.json")
            os.makedirs(os.path.dirname(pool_path), exist_ok=True)
            good = entry(history=hist(7))
            bad = entry(history=hist(21, fails_at={0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19}))
            geo = entry(labels=["Geo-blocked"])
            pool = {"meta": {}, "entries": [good, bad, geo]}
            rc = cp.cmd_promote(pool, dry_run=False, pool_path=pool_path)
            self.assertEqual(rc, 0)
            up = json.load(open(cp.PROMOTED_PATH, encoding="utf-8"))
            self.assertEqual(len(up["upstreams"]), 1)
            u = up["upstreams"][0]
            self.assertEqual(u["source"], "iptv-org")
            self.assertEqual(u["tvg_id"], "x")
            rej = json.load(open(cp.REJECTED_PATH, encoding="utf-8"))
            self.assertEqual(len(rej["entries"]), 1)  # geo 21 天？geo 无历史，days_in=0 不会进 rejected
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_rejected_after_21_days(self):
        tmp = tempfile.mkdtemp()
        try:
            cp.PROMOTED_PATH = os.path.join(tmp, "up", "iptvorg.normal.json")
            cp.REJECTED_PATH = os.path.join(tmp, "rej", "iptvorg_rejected.json")
            # 21 天前开始记录且一直低命中
            h = hist(21, fails_at=set(range(21)), dates_from="2026-08-20")
            bad = entry(history=h)
            pool = {"meta": {}, "entries": [bad]}
            pool_path = os.path.join(tmp, "canary", "iptvorg.json")
            os.makedirs(os.path.dirname(pool_path), exist_ok=True)
            cp.cmd_promote(pool, dry_run=False, pool_path=pool_path)
            rej = json.load(open(cp.REJECTED_PATH, encoding="utf-8"))
            self.assertEqual(len(rej["entries"]), 1)
            self.assertTrue(rej["entries"][0].get("reject_reason"))  # 闸1b/闸2 任一触发即拒
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLooksLikeStream(unittest.TestCase):
    def test_m3u8_ok(self):
        self.assertTrue(cp.looks_like_stream(b"#EXTM3U\n#EXT-X-VERSION:3"))

    def test_ts_ok(self):
        self.assertTrue(cp.looks_like_stream(b"\x47\x40\x00\x10" + b"\x00" * 100))

    def test_html_rejected(self):
        self.assertFalse(cp.looks_like_stream(b"<html><body>403</body></html>"))

    def test_json_rejected(self):
        self.assertFalse(cp.looks_like_stream(b'{"error": "not found"}'))

    def test_empty_rejected(self):
        self.assertFalse(cp.looks_like_stream(b""))


if __name__ == "__main__":
    unittest.main()
