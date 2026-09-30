# -*- coding: utf-8 -*-
"""公开账本「不声明」过滤回归（2026-09-30 CI 门禁 exit 2 的根因修复）。

背景：CI 全展开发现池后，list.json/exports/upstream_health.json 开始列出成人特征
上游 URL（真成人仓 jigedos/1024 + 用户名子串 javyou/saulxxx），零泄漏门禁一票否决。
修复方向不是放宽门禁，而是公开账本生成侧用同一三重判定剥除——少声明不损失任何功能。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fetch_merge as fm  # noqa: E402


class TestPublicListFilter(unittest.TestCase):
    def test_real_adult_upstream_hidden(self):
        ents = [{"name": "auto/23-46s",
                 "url": "https://g.3344550.xyz/https://raw.githubusercontent.com/jigedos/1024/master/jsm.json",
                 "success_url": ""}]
        kept, hidden = fm.public_list_filter(ents)
        self.assertEqual(kept, [])
        self.assertEqual(len(hidden), 1)

    def test_username_substring_hidden_from_public_but_rule_consistent(self):
        # javyou/saulxxx 属用户名子串：与门禁同口径一律不公开声明（内部账本不受影响）
        ents = [{"name": "j", "url": "https://raw.githubusercontent.com/javyou19700207/d/main/x.json", "success_url": ""},
                {"name": "s", "url": "https://raw.githubusercontent.com/saulxxx/future/main/ok.json", "success_url": ""}]
        kept, hidden = fm.public_list_filter(ents)
        self.assertEqual(kept, [])
        self.assertEqual(len(hidden), 2)

    def test_success_url_hit_also_hides_entry(self):
        ents = [{"name": "n", "url": "https://ok.example.com/a.json",
                 "success_url": "https://raw.githubusercontent.com/jigedos/1024/master/b.json"}]
        kept, hidden = fm.public_list_filter(ents)
        self.assertEqual(kept, [])

    def test_clean_entries_kept_untouched(self):
        ents = [{"name": "gao", "url": "https://gh-proxy.com/https://raw.githubusercontent.com/gaotianliuyun/gao/master/js.json", "success_url": "x"},
                {"name": "cms", "url": "http://example.com/api.php/provide/vod/", "success_url": ""}]
        kept, hidden = fm.public_list_filter(ents)
        self.assertEqual(len(kept), 2)
        self.assertEqual(hidden, [])

    def test_missing_fields_no_crash(self):
        kept, hidden = fm.public_list_filter([{}, {"name": None, "url": None}])
        self.assertEqual(len(kept), 2)
        self.assertEqual(hidden, [])


if __name__ == "__main__":
    unittest.main()
