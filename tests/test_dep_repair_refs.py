# -*- coding: utf-8 -*-
"""dep_repair 的 deps 引用提取回归（2026-10-01 那轮"16 缺 0 补"的根因钉版）。

旧正则字符类不含非 ASCII：中文文件名在第一个汉字处被截断，导致
  * 98 条含中文名的引用压根没被扫到（磁盘少了几十个文件也看不见）；
  * 截断出来的半截路径查不到账本 → 记成 unfixable，报"缺失 16 / 补下 0"。
另外多值字段用 `$$$` 拼接、jar 值带 `;md5;` 后缀，也必须先分段/去尾再取路径。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import dep_repair as dr  # noqa: E402


class DepRefsCase(unittest.TestCase):
    def test_chinese_filename_is_not_truncated(self):
        got = dr.dep_refs("./deps/auto/2-348s/svip/XBPQ/80S电影.json")
        self.assertEqual(got, ["deps/auto/2-348s/svip/XBPQ/80S电影.json"])

    def test_multi_value_field_splits_on_triple_dollar(self):
        got = dr.dep_refs("./deps/cluntop/jsm/lib/tokenm.json$$$http://x.yy/$$$no")
        self.assertEqual(got, ["deps/cluntop/jsm/lib/tokenm.json"])

    def test_md5_suffix_is_stripped(self):
        got = dr.dep_refs("./deps/jar/spider.jar;md5;abcdef0123")
        self.assertEqual(got, ["deps/jar/spider.jar"])

    def test_non_deps_and_api_endpoints_ignored(self):
        self.assertEqual(dr.dep_refs("http://x/api.php/provide/vod"), [])
        self.assertEqual(dr.dep_refs("./lib/yt2.json"), [])

    def test_multiple_refs_in_one_blob(self):
        s = '{"jar":"./deps/a/b.js","ext":"./deps/汉/名.json"}'
        self.assertEqual(sorted(dr.dep_refs(s)),
                         sorted(["deps/a/b.js", "deps/汉/名.json"]))


if __name__ == "__main__":
    unittest.main()
