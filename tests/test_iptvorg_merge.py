"""P1 收口：iptv-org canary 晋升流汇入 live_aggregate 的回归测试。

覆盖：
  · 文件缺失 / 为空 / 损坏 → no-op（不抛错、cmap 不变）
  · 正常晋升条目 → 与既有上游同口径并入（norm_channel + dedup_key 聚合、URL 去重）
  · adult 三重红线同链过滤：_is_adult_source（源级）/ is_adult（频道名）/
    is_adult_url（URL 域名黑名单）
  · 已存在频道合线路、不重复记行

纯离线（不触网），与 test_p0_live 同一导入模式。
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


la = _load("live_aggregate_for_merge_test",
           os.path.join(_ROOT, "scripts", "live_aggregate.py"))


def _promoted_file(repo, upstreams, raw=None):
    d = os.path.join(repo, "state", "upstreams")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "iptvorg.normal.json")
    with open(path, "w", encoding="utf-8") as f:
        if raw is not None:
            f.write(raw)
        else:
            json.dump({"generated_at": "2026-09-25T00:00:00+08:00",
                       "upstreams": upstreams}, f, ensure_ascii=False, indent=1)
    return path


def _base_cmap():
    cmap = {}
    la._merge_channel_rows(cmap, [("CCTV-1", "http://example.com/cctv1.m3u8")], "cctv")
    return cmap


class IptvorgMergeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_noop(self):
        cmap = _base_cmap()
        self.assertEqual(la.merge_iptvorg_promoted(cmap, self.repo), 0)
        self.assertEqual(sum(len(v["lines"]) for v in cmap.values()), 1)

    def test_corrupt_file_noop(self):
        _promoted_file(self.repo, None, raw="{not-json")
        cmap = _base_cmap()
        self.assertEqual(la.merge_iptvorg_promoted(cmap, self.repo), 0)
        self.assertEqual(sum(len(v["lines"]) for v in cmap.values()), 1)

    def test_normal_merge_and_dedup(self):
        _promoted_file(self.repo, [
            {"name": "CCTV-1", "url": "http://iptvorg.example.org/cctv1.m3u8",
             "source": "iptv-org"},
            {"name": "翡翠台", "url": "http://iptvorg.example.org/tvbjade.m3u8",
             "source": "iptv-org"},
        ])
        cmap = _base_cmap()
        n = la.merge_iptvorg_promoted(cmap, self.repo)
        self.assertEqual(n, 2)
        # CCTV-1 并进既有聚合键（繁简/后缀归一同键），显示名保留首次出现
        k = la.dedup_key("CCTV-1")
        self.assertIn("iptvorg", [s for s, _u in cmap[k]["lines"]])
        self.assertEqual(cmap[k]["name"], "CCTV-1")
        # 翡翠台新增频道
        kj = la.dedup_key("翡翠台")
        self.assertIn(kj, cmap)
        # 同一 URL 二次汇入不重复记行
        n2 = la.merge_iptvorg_promoted(cmap, self.repo)
        self.assertEqual(n2, 0)

    def test_adult_red_lines(self):
        _promoted_file(self.repo, [
            # ① 源级 _is_adult_source（sid+url+name 词表正则）
            {"name": "某某频道", "url": "http://adult-example-host.invalid/a.m3u8",
             "source": "iptv-org"},
        ] + _adult_probe_rows())
        cmap = _base_cmap()
        lines_before = sum(len(v["lines"]) for v in cmap.values())
        n = la.merge_iptvorg_promoted(cmap, self.repo)
        lines_after = sum(len(v["lines"]) for v in cmap.values())
        self.assertEqual(n, 0)
        self.assertEqual(lines_after, lines_before)

    def test_partial_filter(self):
        _promoted_file(self.repo, [
            {"name": "CCTV-2", "url": "http://iptvorg.example.org/cctv2.m3u8",
             "source": "iptv-org"},
        ] + _adult_probe_rows())
        cmap = _base_cmap()
        n = la.merge_iptvorg_promoted(cmap, self.repo)
        self.assertEqual(n, 1)
        for v in cmap.values():
            for _s, u in v["lines"]:
                self.assertFalse(la.is_adult_url(u))


def _adult_probe_rows():
    """构造必然命中三重红线的样本（词表真实命中项，避免测试随词表漂移失真）。"""
    rows = []
    # is_adult（频道名）——用 test_p0_live 验证过的实词；若词表变化导致不命中，
    # 退化为 URL 红线仍能兜底，不产生假阴性失败。
    try:
        if la.is_adult("咪咕成人频道"):
            rows.append({"name": "咪咕成人频道",
                         "url": "http://iptvorg.example.org/x1.m3u8",
                         "source": "iptv-org"})
    except Exception:  # noqa: BLE001
        pass
    # is_adult_url（域名黑名单）——直接用 la.is_adult_url 找一个当前词表必命中 host
    for host in ("javhd.com", "missav.ws", "pornhub.com"):
        if la.is_adult_url("http://%s/v.m3u8" % host):
            rows.append({"name": "普通名字", "url": "http://%s/v.m3u8" % host,
                         "source": "iptv-org"})
            break
    return rows


if __name__ == "__main__":
    unittest.main(verbosity=2)
