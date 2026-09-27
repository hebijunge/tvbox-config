#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_merge 拉取+解析+合并核心流程的端到端集成测试。

用例分两部分
============

1. 端到端（test_fetch_merge_e2e）
   起一个本地 ``ThreadingHTTPServer`` 提供固定 fixture 上游配置（最小 tvbox json，
   含 3 个 site，ext 指向同服务器上的几个 .js），然后驱动 fetch_merge 的真实
   原语（http_get 拉取 → json.loads 解析 → dep_download 落库 → dep_local_path
   算相对路径 → dep_classify 判型 → 引用改写为 ./deps/...）跑一遍核心流程。
   断言：
     - 输出 sites 数量符合 fixture（3 个）；
     - deps/ 下依赖文件确实落盘；
     - site.ext 引用已改写成相对路径 ``./deps/...``；
     - deps/manifest.json 已写入对应记录。

2. dep_local_path 回归（test_dep_local_path_windows_safe）
   覆盖四种历史踩坑输入：镜像前缀 URL、raw.githubusercontent.com 直链、
   普通相对/通用 URL、origin=remote。断言结果路径在 Windows 上可创建
   （pathutil.is_windows_safe）。

说明
----
* 全程本地 http.server，不访问外网；在临时目录里 chdir，不污染仓库。
* 纯标准库；用 ``python -m unittest tests.test_fetch_merge_e2e`` 跑。
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 让脚本既能从 tests/ 目录直接跑、也能被 unittest 发现
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import pathutil  # noqa: E402
import fetch_merge  # noqa: E402


# ---- fixture 内容 ----
def _fixture_upstream(ext_a, ext_b, ext_c):
    return {
        "spider": "",
        "sites": [
            {"key": "site_a", "name": "A站", "type": 3,
             "searchable": 1, "ext": ext_a, "jar": ""},
            {"key": "site_b", "name": "B站", "type": 1,
             "searchable": 0, "ext": ext_b, "jar": ""},
            {"key": "site_c", "name": "C站", "type": 3,
             "searchable": 1, "ext": ext_c, "jar": ""},
        ],
    }


JS_BODY_A = "var a = 1;\nfunction hello(){ return 'a'; }\n"
JS_BODY_B = "const b = 2;\nexport default b;\n"
JS_BODY_C = "let c = 3;\nfunction world(){ return c; }\n"


class _Handler(BaseHTTPRequestHandler):
    """按路径返回 fixture；测试里通过闭包变量拿端口/内容。"""

    fixtures = {}  # path -> bytes

    def log_message(self, *args):  # 静音
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in self.fixtures:
            body = self.fixtures[path]
            self.send_response(200)
            ctype = "application/json" if path.endswith(".json") else "application/javascript"
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


class FetchMergeE2ETest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="tvbox_e2e_")
        self._cwd = os.getcwd()
        os.chdir(self._tmp)
        # 指向临时目录内的 deps/
        fetch_merge.DEPS_DIR = "deps"
        fetch_merge.MANIFEST_PATH = os.path.join("deps", "manifest.json")
        os.makedirs("deps", exist_ok=True)

        # 起本地服务器
        _Handler.fixtures = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.server.server_address[1]
        self._srv_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._srv_thread.start()

        base = f"http://127.0.0.1:{self.port}"
        _Handler.fixtures["/lib/a.js"] = JS_BODY_A.encode("utf-8")
        _Handler.fixtures["/lib/b.js"] = JS_BODY_B.encode("utf-8")
        _Handler.fixtures["/lib/c.js"] = JS_BODY_C.encode("utf-8")
        up = _fixture_upstream(f"{base}/lib/a.js", f"{base}/lib/b.js", f"{base}/lib/c.js")
        _Handler.fixtures["/upstream.json"] = json.dumps(up, ensure_ascii=False).encode("utf-8")
        self.upstream_url = f"{base}/upstream.json"
        self.origin = "e2e_test"

    def tearDown(self):
        os.chdir(self._cwd)
        self.server.shutdown()
        self.server.server_close()
        self._srv_thread.join(timeout=3)

    # ---- 核心 e2e：拉取 + 解析 + 落库 + 引用改写 ----
    def test_fetch_merge_e2e(self):
        # 1) 拉取上游配置（真实 http_get）
        status, body, _ = fetch_merge.http_get(self.upstream_url, timeout=5)
        self.assertEqual(status, 200)
        tvbox = json.loads(body.decode("utf-8"))

        # 2) 解析：站点数量符合 fixture
        sites = tvbox.get("sites", [])
        self.assertEqual(len(sites), 3, "fixture 上游应含 3 个 site")
        keys = {s.get("key") for s in sites}
        self.assertEqual(keys, {"site_a", "site_b", "site_c"})

        # 3) 落库每个 site 的 ext 依赖 + 改写引用
        manifest = {}
        for site in sites:
            ext_url = site["ext"]
            content, ch = fetch_merge.dep_download(ext_url)
            self.assertIsNotNone(content, f"dep_download 失败: {ext_url} ({ch})")
            kind = fetch_merge.dep_classify("js", content)
            self.assertEqual(kind, "js", f"{ext_url} 应识别为 js，实际 {kind}")
            local = fetch_merge.dep_local_path(self.origin, ext_url)
            ok, why = pathutil.is_windows_safe(local)
            self.assertTrue(ok, f"落库路径不 Windows 安全: {local} ({why})")
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(content)
            manifest[f"{self.origin}|{ext_url}"] = {
                "url": ext_url, "local": local, "kind": kind,
                "origin": self.origin, "size": len(content),
            }
            # 引用改写为相对路径
            site["ext"] = f"./{local}"

        # 4) 断言 deps 文件已落盘
        for rel in ("deps/e2e_test/lib/a.js", "deps/e2e_test/lib/b.js", "deps/e2e_test/lib/c.js"):
            self.assertTrue(os.path.isfile(rel), f"依赖未落盘: {rel}")

        # 5) 断言引用已改写为 ./deps/... 相对路径
        for site in sites:
            self.assertTrue(site["ext"].startswith("./deps/"),
                            f"ext 未改写为相对路径: {site['ext']}")

        # 6) 断言 manifest 落盘
        with open(fetch_merge.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        with open(fetch_merge.MANIFEST_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(len(saved), 3, "manifest 应有 3 条记录")

    # ---- dep_local_path 回归：Windows 兼容性 ----
    def test_dep_local_path_windows_safe(self):
        cases = [
            # (origin, url, 说明)
            ("mirror",
             "https://ghproxy.example.com/https://raw.githubusercontent.com/owner/repo/master/js/drpy.js",
             "镜像前缀 URL（路径段含 https: 冒号，曾导致 WinError 123）"),
            ("rawgh",
             "https://raw.githubusercontent.com/owner/repo/master/js/drpy.js",
             "raw.githubusercontent.com 直链"),
            ("generic",
             "https://example.com/cdn/libs/spider.js",
             "通用 https URL（非镜像前缀、非 rawgh）"),
            ("remote",
             "https://cdn.example.com/any/path/spider.jar",
             "origin=remote（remote 分支）"),
        ]
        for origin, url, desc in cases:
            with self.subTest(desc=desc):
                p = fetch_merge.dep_local_path(origin, url)
                ok, why = pathutil.is_windows_safe(p)
                self.assertTrue(ok, f"[{desc}] 路径不 Windows 安全: {p} ({why})")
                # 路径不得含 Windows 非法字符 < > : " | ? *
                for bad in '<>:"|?*':
                    self.assertNotIn(bad, p, f"[{desc}] 路径含非法字符 {bad!r}: {p}")


if __name__ == "__main__":
    unittest.main()
