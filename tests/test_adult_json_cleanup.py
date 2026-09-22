"""2026-09-23 adult.json 优化新增单测。

覆盖：
- 多信号 classify_site：覆盖表 / 强信号 / 弱信号+多命中 / 弱信号+上游投票 / 误报白名单
- classify_site_strong_only 仅用强信号（用于上游投票预扫）
- clean_parses 结构校验 / 私有地址剔除 / URL 规范化去重 / 占位保留 / 安全阀
- 上游投票预扫：同 repo 内多站被强信号判成人后，弱信号单命中站被升级
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fetch_merge import (
    classify_site,
    classify_site_strong_only,
    clean_parses,
    _is_private_host,
    _normalize_parse_url,
    _coerce_parse_type,
    STRONG_ADULT_TOKENS,
    WEAK_ADULT_TOKENS,
    ADULT_FALSE_POSITIVE_KEYS,
    ADULT_FALSE_POSITIVE_NAME_FRAGMENTS,
)


def test_strong_signal_direct():
    """强信号词命中即判 adult。"""
    cases = [
        ("pornhub", "https://pornhub.com/api.php"),
        ("xvideos 镜像", "https://xvideos.example/jav.js"),
        ("🔞  乐播资源", "https://lbapi9.example/api.php"),
        ("4k-av 测试", "https://4k-av.example/api.php"),
        ("netflav", "https://netflav.example/api.php"),
        ("missav 国内镜像", "https://missav.example/jav.js"),
        ("souav", "https://api.souavzy.vip/api.php"),
        ("麻豆写真", "https://madou.example/api.php"),
        ("果冻传媒", "https://example.com/api.php"),
        ("18av 影视", "https://example.com/18av.json"),
    ]
    for name, api in cases:
        s = {"name": name, "key": "k_" + name, "api": api}
        assert classify_site(s) == "adult", f"强信号未命中: {name}"
        assert classify_site_strong_only(s) == "adult", f"strong-only 未命中: {name}"


def test_weak_signal_multi_hit():
    """弱信号多词命中直接判 adult。"""
    s = {"name": "涩涩影院", "key": "sesesese", "api": "https://example.com/api.php"}
    assert "涩涩" in str(s).lower()
    # 加入另一个弱词
    s["ext"] = '{"categories": ["成人"]}'
    cat = classify_site(s)
    assert cat == "adult", f"弱信号多命中未判 adult: {cat}"


def test_weak_signal_single_no_upstream_vote():
    """弱信号单命中、无上游投票 → 保留 vod（防误杀）。"""
    s = {"name": "迷妹之家", "key": "m1mei", "api": "https://example.com/api.php"}
    # 无 origin_votes → 保留 vod
    cat = classify_site(s)
    assert cat == "vod", f"弱信号单命中误判: {cat}"
    # 强信号同样
    assert classify_site_strong_only(s) == "vod"


def test_weak_signal_single_with_upstream_vote():
    """弱信号单命中、同上游 ≥1 站强信号命中 → 升级 adult。"""
    s = {"name": "迷妹之家", "key": "m1mei", "api": "https://example.com/api.php", "_origin": "test/adult-repo"}
    origin_votes = {"test/adult-repo": 2}  # 该上游已有 2 个强信号命中
    cat = classify_site(s, origin_votes=origin_votes)
    assert cat == "adult", f"上游投票未生效: {cat}"


def test_false_positive_whitelist():
    """已知误报 key/name 强制 vod。"""
    for k in ADULT_FALSE_POSITIVE_KEYS:
        s = {"name": "webdav 网盘", "key": k, "api": "https://example.com/api.php"}
        assert classify_site(s) == "vod", f"白名单未生效: {k}"
        assert classify_site_strong_only(s) == "vod", f"strong 白名单未生效: {k}"
    # 含 webdav 字样的 name
    s = {"name": "WebDav ┃ 自建网盘", "key": "x", "api": "https://example.com/api.php"}
    assert classify_site(s) == "vod"


def test_override_table_priority():
    """人工覆盖表优先级最高。"""
    # 一个正常站点 key 在覆盖表中被标 short
    overrides = {"myvod": "short", "clearlyAdult": "adult"}
    s1 = {"name": "普通影视", "key": "myvod", "api": "https://example.com/api.php"}
    assert classify_site(s1, overrides) == "short"
    # 一个明显非成人站点被覆盖表标 adult
    s2 = {"name": "门户", "key": "clearlyAdult", "api": "https://example.com/api.php"}
    assert classify_site(s2, overrides) == "adult"


def test_short_keyword_priority():
    """短剧关键词优先于成人词（避免被吞）。"""
    s = {"name": "短剧 · 麻豆剧场", "key": "short-dj", "api": "https://example.com/api.php"}
    # 命中「麻豆」（成人强信号），但因短剧关键词先匹配 → short
    # 若 SHORT_KEYWORDS 包含相关短剧词；这里只验证命中顺序不为 adult
    from fetch_merge import SHORT_KEYWORDS
    short_hit = any(kw.lower() in (s.get("name", "") + " " + s.get("api", "")).lower() for kw in SHORT_KEYWORDS)
    if short_hit:
        assert classify_site(s) == "short"
    else:
        # 否则保持原行为（被成人词判 adult）
        assert classify_site(s) in ("adult", "short")


def test_md5_key_does_not_misclassify():
    """32 位 MD5 key 不参与关键词匹配（防 91/jav 等子串误撞）。"""
    s = {"name": "正常影视", "key": "91823abc91def91abc91823def91823a", "api": "https://example.com/api.php"}
    assert classify_site(s) == "vod"


# ====== clean_parses ======

def test_clean_parses_dedup_by_url():
    """同一 URL 多个不同 name 只保留第一条。"""
    parses = [
        {"name": "虾米", "type": 0, "url": "https://jx.xmflv.com/jx.php"},
        {"name": "-虾米-", "type": 0, "url": "https://jx.xmflv.com/jx.php"},
        {"name": "VIP1", "type": 0, "url": "https://jx.xmflv.com/jx.php"},
        {"name": "blsxm", "type": 0, "url": "http://jx.xmflv.com/jx.php"},  # http 视同
        {"name": "xmflv", "type": 0, "url": "https://jx.xmflv.com/jx.php/"},  # 末尾斜杠视同
    ]
    cleaned, stats = clean_parses(parses, do_probe=False)
    assert stats["before"] == 5
    assert stats["after"] == 1
    assert stats["dropped_duplicate"] == 4
    assert cleaned[0]["name"] == "虾米"


def test_clean_parses_private_address():
    """localhost / 127.x / 10.x / 192.168.x / 172.16-31.x 全部剔除。"""
    parses = [
        {"name": "本地5757", "type": 0, "url": "http://localhost:5757/jx.php"},
        {"name": "本地5759", "type": 0, "url": "http://127.0.0.1:5759/jx.php"},
        {"name": "内网", "type": 0, "url": "http://10.0.0.5/jx.php"},
        {"name": "内网", "type": 0, "url": "http://192.168.1.1/jx.php"},
        {"name": "内网", "type": 0, "url": "http://172.20.1.1/jx.php"},
        {"name": "保留", "type": 0, "url": "https://jx.example.com/jx.php"},
    ]
    cleaned, stats = clean_parses(parses, do_probe=False)
    assert stats["dropped_private"] == 5
    assert stats["after"] == 1
    assert cleaned[0]["name"] == "保留"


def test_clean_parses_invalid_type_coercion():
    """type 数字字符串 → int 保留；非数字 → 剔除。"""
    parses = [
        {"name": "数字字符串", "type": "1", "url": "https://example.com/1.php"},
        {"name": "数字字符串", "type": "3", "url": "https://example.com/2.php"},
        {"name": "无效", "type": "abc", "url": "https://example.com/3.php"},
        {"name": "缺type+占位", "url": "Web"},  # type 缺, url=Web 占位 → 补 3
        {"name": "缺type+占位", "url": "Demo"},  # type 缺, url=Demo 占位 → 补 3
        {"name": "缺type+非占位", "url": "https://example.com/4.php"},  # 缺 type, 非占位 → 剔除
    ]
    cleaned, stats = clean_parses(parses, do_probe=False)
    types = sorted(p["type"] for p in cleaned)
    # 期望：[1, 3, 3, 3]
    assert 1 in types
    assert types.count(3) == 3
    assert stats["dropped_invalid"] == 2  # 无效 + 缺type+非占位


def test_clean_parses_demo_web_placeholders_preserved():
    """type 3 占位（Demo/Web）按 URL 去重，各保留一条。"""
    parses = [
        {"name": "Web1", "type": 3, "url": "Web"},
        {"name": "Web2", "type": 3, "url": "Web"},
        {"name": "Web3", "type": 3, "url": "Web"},
        {"name": "Demo1", "type": 3, "url": "Demo"},
        {"name": "Demo2", "type": 3, "url": "Demo"},
        {"name": "Demo3", "type": 3, "url": "Demo"},
    ]
    cleaned, stats = clean_parses(parses, do_probe=False)
    assert stats["after"] == 2
    urls = sorted(p["url"] for p in cleaned)
    assert urls == ["Demo", "Web"]


def test_clean_parses_missing_fields():
    """结构不完整条目剔除。"""
    parses = [
        {"name": "无url", "type": 0},  # 缺 url
        {"type": 0, "url": "https://example.com/x.php"},  # 缺 name
        {"name": "", "type": 0, "url": "https://example.com/y.php"},  # 空 name
        {"name": "有效", "type": 0, "url": "https://example.com/z.php"},
        "not a dict",  # 非 dict
        None,
        ["list entry"],
    ]
    cleaned, stats = clean_parses(parses, do_probe=False)
    assert stats["dropped_invalid"] == 6
    assert stats["after"] == 1


def test_clean_parses_probe_safety_valve():
    """安全阀：剔除率 > 80% 视为网络故障，回退保留全部。"""
    # 用 mock probe 不可达所有目标 → 应触发安全阀
    parses = [
        {"name": f"假死{i}", "type": 0, "url": f"http://fake-dead-{i}.example.invalid/jx.php"}
        for i in range(5)
    ]
    # SKIP_PARSE_PROBE 关闭，走 do_probe=True。目标主机均不可达 → 触发安全阀。
    cleaned, stats = clean_parses(parses, do_probe=True, probe_timeout=1.0)
    # 安全阀触发后回退保留全部（5 条），probe_dead 被清零
    assert stats["safety_valve_triggered"], f"未触发安全阀: {stats}"
    assert stats["after"] == 5
    assert stats["probe_dead"] == 0


def test_normalize_parse_url_basic():
    """URL 规范化：scheme-insensitive、host lowercase、剥末尾斜杠。"""
    assert _normalize_parse_url("https://JX.example.com/Jx.php") == "jx.example.com/Jx.php"
    assert _normalize_parse_url("http://jx.example.com/jx.php/") == "jx.example.com/jx.php"
    assert _normalize_parse_url("JX.example.com/jx.php/?a=1&b=2") == "jx.example.com/jx.php"
    assert _normalize_parse_url("Web") == "Web"
    assert _normalize_parse_url("Demo") == "Demo"


def test_is_private_host():
    assert _is_private_host("localhost")
    assert _is_private_host("127.0.0.1")
    assert _is_private_host("127.0.0.5")
    assert _is_private_host("10.0.0.1")
    assert _is_private_host("192.168.1.1")
    assert _is_private_host("172.16.0.1")
    assert _is_private_host("172.31.255.255")
    assert _is_private_host("169.254.1.1")
    assert not _is_private_host("jx.example.com")
    assert not _is_private_host("8.8.8.8")
    assert not _is_private_host("")


def test_coerce_parse_type():
    assert _coerce_parse_type(0) == 0
    assert _coerce_parse_type("3") == 3
    assert _coerce_parse_type("  2  ") == 2
    assert _coerce_parse_type("abc") is None
    assert _coerce_parse_type(None) is None
    assert _coerce_parse_type([1]) is None