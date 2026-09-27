"""2026-09-27 长尾裁剪审计日志 + mursor 房间判归 — 纯逻辑回归测试。

覆盖（合并剔除逻辑核查报告两处遗留优化点）：
  · 其他组长尾裁剪：每次裁剪输出计数日志（组名/规则命中数/来源分布/抽样频道名），
    并落盘 state/live_aggregate_prune_report.json（在临时目录验证，不污染仓库）
  · 裁剪行为不变：单线路未验证其他频道仍被裁；多线路/已验证/电台豁免不受影响
  · 日志签名去重：同一裁剪集连续两次构建（txt/m3u 场景）只输出一次
  · mursor.ottiptv.cc 房间评估：/yy/<房间号> 兜底判归轮播；/mcp/、/migu/ 路径
    （风云剧场/CETV 等正常频道）维持既有归类；仅兜底不覆盖显式分类
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import importlib.util


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


la = _load("live_aggregate_longtail_test",
           os.path.join(_ROOT, "scripts", "live_aggregate.py"))


def _ent(name, cls, urls, sid="src"):
    return {"name": name, "class": cls,
            "lines": [(sid, u) for u in urls], "_seen": set(urls)}


class _PruneLogTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="longtail-prune-test-")
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp)  # 报告落盘 state/ 相对 CWD，隔离进临时目录
        la._LONGTAIL_LOG_SIG["sig"] = None

    def tearDown(self):
        os.chdir(self._old_cwd)
        shutil.rmtree(self._tmp, ignore_errors=True)
        la._LONGTAIL_LOG_SIG["sig"] = None


class LongtailPruneLogTests(_PruneLogTestBase):
    """其他组长尾裁剪：日志内容 + 行为不变 + 签名去重。"""

    def _build(self, cmap):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            groups = la._build_groups(cmap, set())
        return groups, buf.getvalue()

    def test_prune_logs_count_sources_and_samples(self):
        cmap = {
            "a": _ent("孤剧轮播间", "其他", ["http://x/1"], sid="huya"),
            "b": _ent("冷门网络台", "其他", ["http://y/2"], sid="netease"),
        }
        groups, out = self._build(cmap)
        # 行为不变：两个单线路未验证频道仍被裁掉，其他组为空
        self.assertNotIn("其他", groups)
        self.assertIn("[longtail-prune]", out)
        self.assertIn("组=其他", out)
        self.assertIn("剔除频道 2 个", out)
        self.assertIn("huya×1,netease×1", out)
        self.assertIn("孤剧轮播间", out)
        self.assertIn("冷门网络台", out)
        # 报告落盘：总数 / 来源分布 / 抽样明细
        report = json.load(open(
            os.path.join(self._tmp, "state", "live_aggregate_prune_report.json"),
            encoding="utf-8"))
        self.assertEqual(report["pruned_total"], 2)
        self.assertEqual(report["by_source"], {"huya": 1, "netease": 1})
        names = [s["name"] for s in report["samples"]]
        self.assertIn("孤剧轮播间", names)
        self.assertEqual(report["samples"][0]["n_distinct_lines"], 1)
        self.assertEqual(report["samples"][0]["sources"], ["huya"])

    def test_no_prune_logs_zero_count(self):
        # 无频道被裁时仍输出 0 计数行（证明规则已执行、可审计）
        cmap = {"a": _ent("多线路台", "其他", ["http://x/1", "http://x/2"])}
        groups, out = self._build(cmap)
        self.assertIn("多线路台", groups.get("其他", {}))
        self.assertIn("[longtail-prune]", out)
        self.assertIn("剔除频道 0 个", out)

    def test_survivors_unaffected(self):
        cmap = {
            "a": _ent("多线路幸存", "其他", ["http://x/1", "http://x/2"]),
            "b": _ent("电台小站", "电台", ["http://r/1"]),       # 电台豁免
            "c": _ent("已测单线路", "其他", ["http://v/1"]),
        }
        # 单线路但已验证的频道走 verified 分支，不进裁剪；多线路/电台豁免不受影响
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            groups = la._build_groups(cmap, {"c": ["http://v/1"]})
        others = groups.get("其他", {})
        self.assertIn("多线路幸存", others)
        self.assertIn("电台小站", others)          # 电台折叠进其他且豁免裁剪
        self.assertIn("已测单线路", others)
        self.assertIn("剔除频道 0 个", buf.getvalue())  # 三条均未被裁

    def test_signature_dedup_same_set_logged_once(self):
        cmap = {"a": _ent("孤台", "其他", ["http://x/1"], sid="huya")}
        _g1, out1 = self._build(cmap)   # txt 构建
        _g2, out2 = self._build(cmap)   # m3u 构建（同一裁剪集）
        self.assertIn("[longtail-prune]", out1)
        self.assertNotIn("[longtail-prune]", out2)
        # 裁剪集变化后重新输出
        cmap2 = dict(cmap)
        cmap2["b"] = _ent("新孤台", "其他", ["http://z/9"], sid="douyu")
        _g3, out3 = self._build(cmap2)
        self.assertIn("[longtail-prune]", out3)
        self.assertIn("剔除频道 2 个", out3)


class MursorRoomTests(_PruneLogTestBase):
    """mursor.ottiptv.cc 房间评估：/yy/ 兜底判轮播，/mcp/ /migu/ 维持既有归类。"""

    def _merge(self, rows):
        cmap = {}
        la._merge_channel_rows(cmap, rows, "xuy132-tv")
        return cmap

    def test_mursor_yy_room_goes_lunbo(self):
        cmap = self._merge([("漫画解说", "https://mursor.ottiptv.cc/yy/1382735568")])
        self.assertEqual(cmap["漫画解说"]["class"], "轮播")

    def test_mursor_mcp_and_migu_keep_design_class(self):
        cmap = self._merge([
            ("风云剧场", "https://mursor.ottiptv.cc/mcp/fyjc.m3u8"),
            ("CETV-2", "https://mursor.ottiptv.cc/migu/923287211.m3u8?migutoken=t"),
        ])
        self.assertEqual(cmap["风云剧场"]["class"], "其他")  # CCTV 付费频道设计口径
        self.assertEqual(cmap["cetv-2"]["class"], "央视")    # 显式分类不被覆盖

    def test_non_mursor_yy_host_unaffected(self):
        cmap = self._merge([("某某台", "https://sub.ottiptv.cc/yy/123")])
        # classify 归一化后聚合键为「某某」（canonical 显示名保留「某某台」）
        self.assertEqual(cmap["某某"]["class"], "其他")

    def test_is_lunbo_room_url_edges(self):
        self.assertTrue(la._is_lunbo_room_url(
            "https://MURSOR.ottiptv.cc/yy/1382735568?x=1"))  # host 大小写/带查询串
        self.assertFalse(la._is_lunbo_room_url(
            "https://mursor.ottiptv.cc/mcp/fyjc.m3u8"))      # /mcp/ 非房间
        self.assertFalse(la._is_lunbo_room_url(
            "https://mursor.ottiptv.cc/migu/923287211.m3u8"))  # /migu/ 非房间
        self.assertFalse(la._is_lunbo_room_url(""))
        self.assertFalse(la._is_lunbo_room_url(None))
        self.assertFalse(la._is_lunbo_room_url("not a url"))

    def test_mursor_yy_singer_room_still_dropped(self):
        # 判归轮播后仍受 LUNBO_DROP_KW 约束：歌手房间不入任何分组
        cmap = self._merge([("歌手排位赛", "https://mursor.ottiptv.cc/yy/999")])
        self.assertEqual(cmap, {})


if __name__ == "__main__":
    unittest.main()
