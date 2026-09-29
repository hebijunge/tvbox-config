"""镜像测速落盘 → fetch_merge 消费的纯逻辑回归（不触网）。

覆盖：
  · _load_mirror_rounds：新鲜/过期/损坏三种情况
  · _mirrors_from_rounds：补尾斜杠、跳过空 prefix
  · _stable_ghproxy：主镜像取「近 3 轮至少 2 轮上榜的中位吞吐最高者」，
    单轮侥幸第一不能被选为写进静态 JSON 的前缀
  · GH_MIRRORS 被显式钉选时，GHPROXY 跟随钉选首位（不自作主张）

触网用例另放 tests_net/，本文件纯逻辑必过。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import fetch_merge as fm  # noqa: E402


def _round(prefixes, ts_min_offset=0):
    """构造一轮测速记录；prefixes 为 (名字, KBps) 列表，按给定顺序即排名。"""
    when = datetime.now(timezone.utc) - timedelta(minutes=ts_min_offset)
    return {"generated_at": when.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "ranking": [{"prefix": p.rstrip("/"), "KBps": k, "bytes": 4194304,
                         "capped": False} for p, k in prefixes]}


class TestMirrorRanking(unittest.TestCase):
    def test_load_rounds_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mirror_ranking.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"rounds": [_round([("https://a.x", 3000),
                                              ("https://b.x", 2000)])]}, f)
            rounds = fm._load_mirror_rounds(path)
            self.assertEqual(len(rounds), 1)
            self.assertEqual(len(rounds[0]["ranking"]), 2)

    def test_load_rounds_stale_and_broken(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mirror_ranking.json")
            old = _round([("https://a.x", 3000)], ts_min_offset=60 * 24 * 5)  # 5 天前
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"rounds": [old]}, f)
            self.assertEqual(fm._load_mirror_rounds(path), [], "超过 3 天应视为过期")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{ 这不是 json")
            self.assertEqual(fm._load_mirror_rounds(path), [])
            self.assertEqual(fm._load_mirror_rounds(os.path.join(d, "不存在.json")), [])

    def test_mirrors_from_rounds_adds_trailing_slash(self):
        rounds = [_round([("https://a.x", 3000), ("", 1), ("https://b.x/", 900)])]
        self.assertEqual(fm._mirrors_from_rounds(rounds),
                         ["https://a.x/", "https://b.x/"])
        self.assertEqual(fm._mirrors_from_rounds([]), [])

    def test_stable_ghproxy_prefers_multi_round_consistency(self):
        # round0 的冠军 lucky 只在第一轮出现（侥幸），稳态应选每轮都在的 steady
        rounds = [
            _round([("https://lucky.x", 9000), ("https://steady.x", 3000)]),
            _round([("https://steady.x", 2900), ("https://other.x", 1200)]),
            _round([("https://steady.x", 3100), ("https://other.x", 1300)]),
        ]
        self.assertEqual(fm._stable_ghproxy(rounds, "https://fallback.x/"),
                         "https://steady.x/")

    def test_stable_ghproxy_needs_two_rounds(self):
        rounds = [_round([("https://solo.x", 9000)])]
        self.assertEqual(fm._stable_ghproxy(rounds, "https://fallback.x/"),
                         "https://fallback.x/")
        self.assertEqual(fm._stable_ghproxy([], "https://fallback.x/"),
                         "https://fallback.x/")

    def test_pinned_env_list_wins_for_ghproxy(self):
        code = ("import sys; sys.path.insert(0, r'{scripts}');"
                "import fetch_merge as m;"
                "print(m.GH_MIRRORS[0], m.GHPROXY, m._MIRRORS_PINNED)").format(
                    scripts=os.path.join(_ROOT, "scripts"))
        env = dict(os.environ, GH_MIRRORS="https://pinned.x/,https://second.y/")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=env, encoding="utf-8").stdout.split()
        self.assertEqual(out, ["https://pinned.x/", "https://pinned.x/", "True"])


if __name__ == "__main__":
    unittest.main()
