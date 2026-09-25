"""batch18 吸收实施（hacks 四分类 + 春晚专项组 + 动漫城 + 治理）行为测试。

覆盖：
A. .mp4/快手 VOD 规则过滤去除（用户 2026-09-25 指令）——春晚历史录像不再被源头丢弃，
   AV 番号与其他 VOD 规则仍生效；
B. live.hacks.tools 四分类源接入（build_sources / classify_source / 春晚(季节性) 分组）；
C. 动漫城 yingm.cc 上游接入（UPSTREAMS 锚点 + dm.json key 级去重对账）；
D. 治理项（live.json 单条目 / jsdelivr 规范化 / 摸鱼 canary / GH_MIRRORS 完整性）；
E. 真网 E2E（春晚源实拉 + 快手 mp4 流可达抽测）——网络不可达时 skip，不算失败。

不依赖 pipeline 运行顺序；dm.json 离线副本由调研批取证留存。
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import fetch_merge as fm
import live_aggregate as la

REPO = os.path.join(os.path.dirname(__file__), "..")
DM_JSON = os.path.join(REPO, ".b18", "dm.json")

CHUNWAN_URL = ("https://live.hacks.tools/tv/ipv4/categories/"
               "%E6%98%A5%E6%99%9A%E9%A2%91%E9%81%93.m3u")

# 调研批实测留样：春晚条目真链从 .b18 取证文件读取（缺失则 E2E 跳过）
KW_MP4 = ("https://alimov2.a.kwimgs.com/upic/2023/01/13/22/"
          "BMjAyMzAxMTMyMjEwMDNfNDAzMDAxOTlfOTM1MTIzMzYwODJfMF8z_b_B647d.mp4")
KW_M3U8 = "https://txmov2.a.kwimgs.com/bs3/video-hls/5195746663405928031_hlsb.m3u8"


def _sample_urls():
    """从调研批取证的春晚 m3u 读取真链（供 E2E；文件缺失返回空表）。"""
    p = os.path.join(REPO, ".b18", "hacks_春晚频道.m3u")
    if not os.path.exists(p):
        return []
    return [l.strip() for l in open(p, encoding="utf-8") if l.startswith("http")]


class TestVodRuleRemoval(unittest.TestCase):
    """A. 用户指令「.mp4 规则过滤去掉」：kwimgs 两条分支不再命中 _VOD_URL_RE。"""

    def test_kwimgs_mp4_kept(self):
        self.assertFalse(la._drop_vod_row("1993年春晚", KW_MP4))

    def test_kwimgs_m3u8_kept(self):
        self.assertFalse(la._drop_vod_row("1987年春晚", KW_M3U8))

    def test_regex_no_kwimgs_branch(self):
        self.assertNotIn("kwimgs", la._VOD_URL_RE.pattern)

    def test_av_number_still_dropped(self):
        self.assertEqual(la._drop_vod_row("SSNI-240", "http://x/a.m3u8"), "AV_NUMBER")
        self.assertEqual(la._drop_vod_row("MIAA-247", "http://x/a.m3u8"), "AV_NUMBER")
        self.assertEqual(la._drop_vod_row("SONE-071", "http://x/a.m3u8"), "AV_NUMBER")

    def test_other_vod_rules_intact(self):
        cases = [
            ("综艺", "https://cdn2020.com/video/m3u8/2024/01/01/abc.m3u8"),
            ("推广", "https://adultiptv.net/list.m3u8"),
            ("杂项", "https://x.com/video/av1234"),
        ]
        for name, url in cases:
            self.assertTrue(la._drop_vod_row(name, url), url)

    def test_parse_m3u_end_to_end(self):
        text = "\n".join([
            "#EXTM3U",
            '#EXTINF:-1 tvg-name="1993年春晚", 1993年春晚', KW_MP4,
            '#EXTINF:-1, SSNI-240', "http://x/a.m3u8",
            '#EXTINF:-1, CCTV-1', "http://x/cctv1.m3u8",
        ])
        rows = la.parse_m3u(text)
        names = [n for n, _ in rows]
        self.assertIn("1993年春晚", names)
        self.assertNotIn("SSNI-240", names)
        self.assertIn("CCTV-1", names)


class TestHacksSources(unittest.TestCase):
    """B. hacks 四分类源接入与春晚专项分组。"""

    def test_build_sources_contains_hacks(self):
        sources = dict(la.build_sources(REPO))
        for sid in ("hacks_cctv", "hacks_weishi", "hacks_difang", "chunwan"):
            self.assertIn(sid, sources, sid)
        self.assertTrue(sources["chunwan"].startswith("https://live.hacks.tools/tv/ipv4/categories/"))

    def test_classify_source_encoded_urls(self):
        self.assertEqual(la.classify_source(
            "https://live.hacks.tools/tv/ipv4/categories/%E5%A4%AE%E8%A7%86%E9%A2%91%E9%81%93.m3u"),
            "hacks_cctv")
        self.assertEqual(la.classify_source(
            "https://live.hacks.tools/tv/ipv4/categories/%E5%8D%AB%E8%A7%86%E9%A2%91%E9%81%93.m3u"),
            "hacks_weishi")
        self.assertEqual(la.classify_source(
            "https://live.hacks.tools/tv/ipv4/categories/%E5%9C%B0%E6%96%B9%E9%A2%91%E9%81%93.m3u"),
            "hacks_difang")
        self.assertEqual(la.classify_source(CHUNWAN_URL), "chunwan")

    def test_chunwan_class_override(self):
        # 离线注入：monkeypatch load_source，直接走 build_channel_map 的春晚覆写分支
        #（cmap 按频道去重键为键，分组归属看条目的 class 字段）
        orig = la.load_source
        la.load_source = lambda sid, url, repo: (
            [("1987年春晚", KW_MP4), ("2024年春晚", KW_M3U8)] if sid == "chunwan"
            else [("CCTV-1 综合", "http://x/cctv1.m3u8")])
        try:
            cmap = la.build_channel_map([("chunwan", "http://x/chunwan.m3u"),
                                         ("cctv", "http://x/cctv.m3u")], REPO)
        finally:
            la.load_source = orig
        self.assertEqual(cmap["1987年春晚"]["class"], "春晚(季节性)")
        self.assertEqual(cmap["2024年春晚"]["class"], "春晚(季节性)")
        self.assertEqual(cmap["cctv-1综合"]["class"], "央视")

    def test_big_order_and_core_class(self):
        self.assertIn("春晚(季节性)", la.BIG_ORDER)
        self.assertLess(la.BIG_ORDER.index("春晚(季节性)"), la.BIG_ORDER.index("卫视"))
        self.assertTrue(la._is_core_class("春晚(季节性)"))


class TestYingmUpstream(unittest.TestCase):
    """C. 动漫城上游锚点 + dm.json 对账（key 级净新增）。"""

    def test_upstream_anchor(self):
        entries = {u["name"]: u for u in fm.UPSTREAMS}
        self.assertIn("yingm/dm", entries)
        self.assertEqual(entries["yingm/dm"]["url"], "https://www.yingm.cc/dm/dm.json")
        self.assertEqual(entries["yingm/dm"]["kind"], "tvbox")
        # 上游基表自动覆盖（相对路径改写依赖）
        self.assertIn("yingm/dm", fm.UPSTREAM_BASES)
        self.assertEqual(fm.UPSTREAM_BASES["yingm/dm"], "https://www.yingm.cc/dm/")

    def test_canary_moyu_direct(self):
        entries = {u["name"]: u for u in fm.UPSTREAMS if u.get("canary")}
        self.assertIn("canary/moyu-direct", entries)
        self.assertEqual(entries["canary/moyu-direct"]["url"], "http://www.y456y.com")

    @unittest.skipUnless(os.path.exists(DM_JSON), "dm.json 离线副本缺失（调研批取证件）")
    def test_dmjson_key_level_dedup(self):
        dm = json.load(open(DM_JSON, encoding="utf-8"))
        self.assertEqual(len(dm["sites"]), 27)
        self.assertEqual(len(dm["parses"]), 20)
        tv = json.load(open(os.path.join(REPO, "tvbox.json"), encoding="utf-8"))
        existing_keys = {s.get("key") for s in tv["sites"]}
        existing_parses = {p.get("name") for p in tv["parses"]}
        net_new_sites = [s for s in dm["sites"] if s.get("key") not in existing_keys]
        net_new_parses = [p for p in dm["parses"]
                          if p.get("name") not in existing_parses
                          and p.get("url") not in ("Demo", "Web")
                          and str(p.get("url", "")).startswith("http")]
        # 质检遗留小补丁（单向断言）：调研 merge key 口径净新增 1 站（csp_Ying 樱花动漫）+ 15 parses；
        # 每日 05:00 管线把 dm.json 落进 tvbox.json 后净新增归零属预期，
        # 故不再锁死「净新增恰为 csp_Ying+15」，改为状态自适应断言：
        #   - 未合并态：净新增恰为 csp_Ying，且 http 解析净新增 ≥15；
        #   - 已合并态：csp_Ying 已入池，且 dm 的 http 解析全部在池。
        dm_http_parse_names = {p.get("name") for p in dm["parses"]
                               if p.get("url") not in ("Demo", "Web")
                               and str(p.get("url", "")).startswith("http")}
        if "csp_Ying" in existing_keys:
            missing = dm_http_parse_names - existing_parses
            self.assertFalse(missing, f"已合并态下 dm http 解析仍缺失: {sorted(missing)}")
        else:
            self.assertEqual([s["key"] for s in net_new_sites], ["csp_Ying"])
            self.assertGreaterEqual(len(net_new_parses), 15)


class TestGovernance(unittest.TestCase):
    """D. 治理项核验。"""

    def test_livejson_single_entry(self):
        with open(os.path.join(REPO, "live.json"), encoding="utf-8") as f:
            lj = json.load(f)
        self.assertEqual(len(lj.get("lives", [])), 1)

    def test_jsdelivr_normalized(self):
        with open(os.path.join(REPO, "state", "extra_upstreams.json"), encoding="utf-8") as f:
            ex = json.load(f)
        urls = [u.get("url", "") for u in ex.get("upstreams", []) if isinstance(u, dict)]
        self.assertFalse([u for u in urls if u.startswith("https://cdn.jsdelivr.net/")])
        self.assertIn("https://fastly.jsdelivr.net/gh/jyoketsu/tv@main/m.json", urls)

    def test_gh_mirrors_intact(self):
        self.assertEqual(len(fm.GH_MIRRORS), 9)
        self.assertIn("https://gh-proxy.com/", fm.GH_MIRRORS)  # QC 软化口径：保留、按当日实测轮换


class TestE2ELive(unittest.TestCase):
    """E. 真网 E2E：网络不可达 skip（CI 与每日管线另行实证）。
    live_probe.http_get 返回 (status, headers, body)；status=0 表示请求异常。"""

    def test_chunwan_live_fetch(self):
        status, _h, body = la.http_get(CHUNWAN_URL, 20)
        if status == 0:
            self.skipTest("网络不可达")
        self.assertEqual(status, 200)
        rows = la.parse_m3u(body.decode("utf-8", "ignore"))
        self.assertEqual(len(rows), 21)
        mp4 = sum(1 for _, u in rows if ".mp4" in u.lower())
        self.assertGreaterEqual(mp4, 15)

    def test_kwimgs_stream_reachable(self):
        urls = [u for u in _sample_urls() if "kwimgs" in u]
        if not urls:
            self.skipTest("取证样本缺失")
        for u in urls[:3]:
            status, _h, body = la.http_get(u, 15, rng="bytes=0-2047")
            if status == 0:
                self.skipTest("网络不可达")
            self.assertIn(status, (200, 206), u)


if __name__ == "__main__":
    unittest.main(verbosity=2)
