"""真机工装的 ext 内联口径。

为什么要钉这条：宿主 app 加载站点前会把 `./deps/x.json` 这类相对路径读成规则文本再喂 spider，
`app_process` 复现不了这一步。直接把路径串交给 `init`，xBPQ/XYQHiker 这一类就把它当 JSON 解析，
报 `JSONException: End of input`——那是工装没喂到位，不是站点死。本机真机对照：同样 8 个 G0 站，
内联规则内容后 7 个变 G1。所以这条既不能漏（漏了就造假死），也不能过（把非路径的 ext 乱改写）。
"""
import importlib.util
import json
import os
import tempfile
import unittest
import urllib.parse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "csp_device_batch", os.path.join(_ROOT, "csp-device", "csp_device_batch.py"))
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


class InlineExtTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.cwd)

    def write(self, rel, text):
        fp = os.path.join(self.tmp.name, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(text)
        return "./" + rel

    def test_relative_rule_file_is_inlined(self):
        ref = self.write("deps/x.json", json.dumps({"rule": {"home": "https://a/b"}}))
        cfg, note = mod.inline_ext(ref)
        self.assertIn('"home"', cfg, "内联后应该拿到规则内容本身")
        self.assertIn("内联", note)

    def test_percent_encoded_path_resolves(self):
        self.write("deps/码上/555影视.json", '{"x":1,"pad":"aaaaaaaaaaaaaaaaaaaaaaaa"}')
        quoted = "./deps/" + urllib.parse.quote("码上/555影视.json")
        cfg, note = mod.inline_ext(quoted)
        self.assertTrue(cfg.startswith("{"), "%s -> %s" % (quoted, cfg[:30]))
        self.assertIn("内联", note)

    def test_missing_file_leaves_cfg_untouched(self):
        ref = "./deps/nope.json"
        cfg, note = mod.inline_ext(ref)
        self.assertEqual(cfg, ref)
        self.assertIn("未内联", note)

    def test_oversize_file_is_not_inlined(self):
        ref = self.write("deps/big.json", "{" + "a" * (mod.MAX_INLINE + 10) + "}")
        cfg, note = mod.inline_ext(ref)
        self.assertEqual(cfg, ref, "超大规则文件会把 jobs 块撑爆，不该内联")
        self.assertIn("大小", note)

    def test_tiny_file_is_not_inlined(self):
        ref = self.write("deps/tiny.json", "{}")
        cfg, note = mod.inline_ext(ref)
        self.assertEqual(cfg, ref, "几十字节的占位文件内联了也说明不了什么")

    def test_multi_value_ext_only_inlines_path_segments(self):
        ref = self.write("deps/multi.json", '{"k":"value","list":[1,2,3,4,5]}')
        cfg, note = mod.inline_ext(ref + "$$$https://a/b.json$$$key123")
        parts = cfg.split("$$$")
        self.assertEqual(len(parts), 3)
        self.assertIn('"value"', parts[0])
        self.assertEqual(parts[1], "https://a/b.json", "URL 形态交给 spider 自己取，不能改写")
        self.assertEqual(parts[2], "key123")
        self.assertEqual(note.count("内联"), 1)

    def test_non_path_forms_untouched(self):
        for cfg0 in ("", "   ", '{"inline":"json"}', "https://a/b.json",
                     "base64:xxxx", "w7TCmsK/w7H"):
            cfg, note = mod.inline_ext(cfg0)
            self.assertEqual(cfg, cfg0)
            self.assertEqual(note, "")

    def test_assets_prefix_is_inlined_too(self):
        self.write("asset.json", '{"a":1234567890,"b":"0987654321"}')
        cfg, note = mod.inline_ext("assets://asset.json")
        self.assertIn("a\":12345", cfg)
        self.assertIn("内联", note)


if __name__ == "__main__":
    unittest.main()
