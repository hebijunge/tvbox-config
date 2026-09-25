"""2026-09-25 iptv-org 适配器（P1-B）单测。

覆盖（docs/iptvorg-adapter-plan.md §8 验证清单中可离线验证项）：
- parse：channels/streams 解析、大中华区筛选、dmca 剔除、is_nsfw 分流、孤儿流丢弃
- to_upstream：标准上游形态（source=iptv-org / tvg_id / headers / labels）
- stream_id：同 URL 稳定、异 URL 不同
- merge_canary：增量合并保留 probe_history/admitted、上游消失条目保留观测、max_new 分批
- vocab：alt_names 清洗（超长/符号拒收）、CCTV 别名建议、非 CCTV 只留 review
- vocab-merge：幂等、冲突保留既有、备份落盘
"""
import sys, os, json, shutil, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import live_iptvorg_adapter as ad


def mk_stream(cid="CCTV1.cn", feed="", title="CCTV-1", url="http://e/x.m3u8",
              ref=None, ua=None, q="1080p", labels=None):
    return ad.IptvOrgStream(cid, feed, title, url, ref, ua, q, labels or [])


def mk_chan(cid="CCTV1.cn", name="CCTV-1 (China)", alt=None, country="CN",
            cats=None, nsfw=False):
    return ad.IptvOrgChannel(cid, name, alt or [], country, cats or ["news"], nsfw)


class TestParse(unittest.TestCase):
    def test_select_gc_regions(self):
        gc, nsfw = ad.select_gc_channels(
            [mk_chan(), mk_chan(cid="CCTV2.cn", country="US"),
             mk_chan(cid="NSFW.cn", nsfw=True)], [])
        self.assertEqual(len(gc), 1)
        self.assertEqual(len(nsfw), 1)

    def test_dmca_excluded(self):
        gc, _ = ad.select_gc_channels([mk_chan()],
                                      [{"channel": "CCTV1.cn", "reason": "dmca", "ref": "x"}])
        self.assertEqual(gc, [])

    def test_link_streams_orphans_dropped(self):
        idx = {"CCTV1.cn": mk_chan()}
        linked, orphans = ad.link_streams([mk_stream(), mk_stream(url="http://e/2.m3u8", cid="Unknown.tv")], idx)
        self.assertEqual(len(linked), 1)
        self.assertEqual(orphans, 1)

    def test_parse_streams_rejects_bad_url(self):
        streams = ad.parse_streams([{"channel": "x", "url": "not-a-url", "title": "t"},
                                    {"channel": "x", "url": "http://ok/a.m3u8", "title": "ok"}])
        self.assertEqual(len(streams), 1)


class TestToUpstream(unittest.TestCase):
    def test_shape(self):
        s = mk_stream(ref="http://r", ua="okhttp/3.15", labels=["Geo-blocked"])
        c = mk_chan(name="CCTV-1 (China)")
        u = ad.to_upstream(s, c)
        self.assertEqual(u["name"], "CCTV-1")
        self.assertEqual(u["tvg_id"], "CCTV1.cn")
        self.assertEqual(u["headers"], {"Referer": "http://r", "User-Agent": "okhttp/3.15"})
        self.assertEqual(u["quality"], "1080p")
        self.assertEqual(u["labels"], ["Geo-blocked"])
        self.assertEqual(u["source"], "iptv-org")


class TestStreamId(unittest.TestCase):
    def test_stable_and_distinct(self):
        a = ad.stream_id(mk_stream())
        b = ad.stream_id(mk_stream())
        self.assertEqual(a, b)
        c = ad.stream_id(mk_stream(url="http://e/other.m3u8"))
        self.assertNotEqual(a, c)
        self.assertIn("CCTV1.cn", a)


class TestMergeCanary(unittest.TestCase):
    def _pool(self, entries):
        return {"meta": {}, "entries": entries}

    def _entry(self, sid, **kw):
        e = {"stream_id": sid, "channel_name": "x", "alt_names": [], "country": "CN",
             "title": "x", "url": "http://u/%s" % sid, "headers": {}, "quality": None,
             "labels": [], "probe_history": [], "admitted": False, "admit_date": None,
             "reject_reason": None}
        e.update(kw)
        return e

    def test_history_preserved(self):
        old = self._pool([self._entry("s1", probe_history=[{"date": "2026-09-20", "success": True}])])
        new = [self._entry("s1"), self._entry("s2")]
        merged, added = ad.merge_canary(old, new, max_new=10)
        s1 = [e for e in merged if e["stream_id"] == "s1"][0]
        self.assertEqual(len(s1["probe_history"]), 1)
        self.assertEqual(added, 1)

    def test_max_new_batch(self):
        old = self._pool([])
        new = [self._entry("s%d" % i) for i in range(10)]
        merged, added = ad.merge_canary(old, new, max_new=3)
        self.assertEqual(added, 3)
        self.assertEqual(len(merged), 3)

    def test_gone_entry_with_history_kept(self):
        old = self._pool([self._entry("gone", probe_history=[{"date": "d", "success": True}])])
        merged, _ = ad.merge_canary(old, [], max_new=5)
        self.assertEqual(len(merged), 1)

    def test_gone_entry_without_history_dropped(self):
        old = self._pool([self._entry("gone")])
        merged, _ = ad.merge_canary(old, [], max_new=5)
        self.assertEqual(len(merged), 0)


class TestVocab(unittest.TestCase):
    def test_clean_alias_rejects(self):
        self.assertIsNone(ad._clean_alias(""))
        self.assertIsNone(ad._clean_alias("a" * 40))
        self.assertIsNone(ad._clean_alias("别名<script>"))

    def test_cctv_suggestions(self):
        sug, others = ad.build_vocab_additions([
            mk_chan(name="CCTV-1 (China)", alt=["中央一台", "CCTV1 综合"]),
            mk_chan(name="Anhui TV", alt=["安徽卫视"]),
        ])
        self.assertEqual(sug.get("中央一台"), "CCTV-1")
        # 非 CCTV 频道别名只留 review
        self.assertTrue(any(o["name"] == "Anhui TV" for o in others))

    def test_vocab_merge_idempotent_and_conflict(self):
        tmp = tempfile.mkdtemp()
        try:
            orig_vocab = ad.VOCAB_DIR
            ad.VOCAB_DIR = tmp
            norm = {"schema": "x", "version": "v1", "cctv_alias_canonical": {"央视一套": "CCTV-1", "老别名": "CCTV-2"}}
            with open(os.path.join(tmp, "normalization.json"), "w", encoding="utf-8") as f:
                json.dump(norm, f)
            with open(ad.VOCAB_ADDITIONS_PATH, "w", encoding="utf-8") as f:
                json.dump({"cctv_alias_canonical_additions":
                           {"央视一套": "CCTV-1",        # 幂等：已存在同映射
                            "新别名": "CCTV-3",           # 新增
                            "老别名": "CCTV-9"}}, f)      # 冲突：保留既有 CCTV-2
            rc = ad.cmd_vocab_merge(None)
            self.assertEqual(rc, 0)
            merged = json.load(open(os.path.join(tmp, "normalization.json"), encoding="utf-8"))
            self.assertEqual(merged["cctv_alias_canonical"]["新别名"], "CCTV-3")
            self.assertEqual(merged["cctv_alias_canonical"]["老别名"], "CCTV-2")
            baks = [x for x in os.listdir(tmp) if x.startswith("normalization.json.bak-")]
            self.assertEqual(len(baks), 1)
        finally:
            ad.VOCAB_DIR = orig_vocab
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
