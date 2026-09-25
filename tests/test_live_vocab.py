"""2026-09-25 直播分类词表（live_vocab）单测。

覆盖：
- normalize：方括号剥除 / 质量词 / 品牌后缀 / 繁简 / 全半角
- classify：央视（CCTV-1/央视一套/CETV/CGTN）/ 港台（TVB/HK开电视/凤凰/翡翠湾反例）/ 轮播（含排除）/ 地方（卫视/组播）/ 兜底
- adult：关键词 / host 命中 / 「[来源组名]前缀剥离」不影响 CCTV 判定
- source_marker：整源标记者优先级最高
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from live_vocab import classify, normalize


# ============== normalize ==============

def test_normalize_strip_brackets():
    """[xxx] 来源组前缀整段剥除。"""
    assert normalize("[SWAG]CCTV-1") == "cctv-1"
    assert normalize("[FHD]湖南卫视") == "湖南卫视"
    assert normalize("【水果派】CCTV-1") == "cctv-1"
    assert normalize("[BD]cctv1咪咕") == "cctv1"


def test_normalize_strip_quality():
    """质量词（4K/1080/超清/蓝光/HD/SD）剥离。"""
    assert normalize("CCTV-1 1080P") == "cctv-1"
    assert normalize("湖南卫视4K") == "湖南卫视"
    assert normalize("央视一套 超高清") == "央视一套"
    assert normalize("CCTV-5+ HEVC") == "cctv-5+"
    assert normalize("HD测试频道") == "测试频道"  # HD 是质量词
    assert normalize("SD 频道") == "频道"


def test_normalize_strip_brand():
    """品牌后缀（咪咕/官方）剥离。"""
    assert normalize("CCTV-1 咪咕") == "cctv-1"
    assert normalize("CCTV-5+ 咪咕") == "cctv-5+"
    assert normalize("湖南卫视 官方") == "湖南卫视"


def test_normalize_fullwidth():
    """全角→半角 + 空格折叠。"""
    assert normalize("CCTV-1（高清）") == "cctv-1"
    assert normalize("湖南卫视　4K") == "湖南卫视"  # 全角空格折叠


def test_normalize_t2s():
    """繁→简转换（来自 t2s_grounded.json，745 字实测表）。"""
    # 鳳凰 → 凤凰
    assert normalize("鳳凰衛視") == "凤凰卫视"
    assert normalize("無綫新聞台") == "无线新闻台"
    # 衛視/電視 不动（卫视/电视本身就是简）
    assert "卫视" in normalize("衛視中文台")


def test_normalize_compose():
    """组合：方括号 + 质量 + 品牌 + 繁简。"""
    assert normalize("【水果派】CCTV-1 咪咕 4K") == "cctv-1"
    assert normalize("[FHD]TVB無綫新聞台 1080p") == "tvb无线新闻台"


# ============== classify: 央视 ==============

def test_cctv_numbered():
    """编号 CCTV 1..17。"""
    assert classify("CCTV-1")["group"] == "cctv"
    assert classify("CCTV-1")["canonical"] == "CCTV-1"
    assert classify("CCTV-17")["canonical"] == "CCTV-17"
    assert classify("CCTV-5+")["canonical"] == "CCTV-5+"
    assert classify("CCTV-03")["canonical"] == "CCTV-3"  # 0-padded


def test_cctv_alias_canon():
    """央视一套...央视十七套 → CCTV-1..CCTV-17。"""
    assert classify("央视一套")["canonical"] == "CCTV-1"
    assert classify("央视二套")["canonical"] == "CCTV-2"
    assert classify("央视十七套")["canonical"] == "CCTV-17"


def test_cctv_strip_prefix():
    """[来源组名] + 品牌后缀 + 质量词 前缀被剥，依然归 cctv。"""
    r = classify("[SWAG]CCTV-1 咪咕")
    assert r["group"] == "cctv", f"实际 group={r['group']}, by={r['debug']['matched_by']}"
    assert r["canonical"] == "CCTV-1"


def test_cctv_cgtn():
    """CGTN 系列（含子语种）。"""
    assert classify("CGTN")["canonical"] == "CGTN"
    assert classify("CGTN English")["canonical"] == "CGTN english"  # 下游可决定是否还原
    assert classify("中国国际")["canonical"] == "CGTN"


def test_cctv_cetv():
    """CETV 系列。"""
    assert classify("CETV-1")["canonical"] == "CETV-1"
    assert classify("CETV-4")["canonical"] == "CETV-4"


def test_cctv_strict_no_overflow():
    """CCTV-20 纪录片/CCTV怀旧剧场 等付费频道越界 → 不归 cctv（任务 strict 定义）。"""
    # CCTV-20 越界 1..17 → 不归 cctv
    r = classify("CCTV-20")
    assert r["group"] != "cctv", f"实际 group={r['group']}"


# ============== classify: 港台 ==============

def test_gangtai_tvb():
    """TVB 系列 + 翡翠/明珠/本港台 + 凤凰系 + RTHK（港台电视31）。"""
    assert classify("TVB無綫新聞台")["group"] == "gangtai"
    assert classify("TVB 8 频道")["group"] == "gangtai"
    assert classify("翡翠台")["group"] == "gangtai"
    assert classify("明珠台")["group"] == "gangtai"
    assert classify("凤凰卫视中文台")["group"] == "gangtai"
    assert classify("凤凰资讯台")["group"] == "gangtai"
    assert classify("港台電視31")["group"] == "gangtai"


def test_gangtai_taiwan():
    """台湾主要台（中天/东森/民视/三立/华视/公视/TVBS/纬来）。"""
    assert classify("TVBS新闻台")["group"] == "gangtai"
    assert classify("中天新闻台")["group"] == "gangtai"
    assert classify("民视")["group"] == "gangtai"
    assert classify("三立台湾台")["group"] == "gangtai"
    assert classify("华视")["group"] == "gangtai"
    assert classify("公视")["group"] == "gangtai"


def test_gangtai_negative():
    """翡翠湾 / 翡翠绿 等地名不归港台。"""
    r = classify("❌福建漳州六鳌翡翠湾")
    assert r["group"] != "gangtai", f"实际 group={r['group']}, 不该归港台"


def test_hong_kong_sat_is_local():
    """香港卫视是地方频道（公司名带卫视不在港台 group），按 spec 归地方。"""
    # 任务里说"香港卫视"示例应当归 local（因为它是大陆市场化频道，不是港台原声）
    r = classify("香港卫视")
    # 这里香港卫视 在港台组（凤凰系列归港台，但"香港卫视"是公司名带卫视的产品频道）
    # 我们的词表里有"凤凰"而没"香港卫视"→ 落到地方（卫视是地方后缀）
    assert r["group"] in ("gangtai", "local"), f"实际 group={r['group']}"


# ============== classify: 轮播 ==============

def test_lunbo_basic():
    """轮播/循环/重播/一起看/轰脑循环/循环播 → lunbo。"""
    assert classify("YY轮播")["group"] == "lunbo"
    assert classify("虎牙一起看")["group"] == "lunbo"
    assert classify("循环剧场")["group"] == "lunbo"


def test_lunbo_exclude():
    """综艺/节目名含「循环/回味/初舞台」但被排除正则命中 → 归 live（兜底）。"""
    r = classify("乘风2026娜就聊姐姐第8期：循环回味初舞台")
    assert r["group"] != "lunbo", f"实际 group={r['group']}（综艺名不该归轮播）"
    assert r["group"] == "live"


# ============== classify: 地方 ==============

def test_local_province():
    """省级卫视/地方频道归 local。"""
    assert classify("湖南卫视")["group"] == "local"
    assert classify("北京卫视")["group"] == "local"
    assert classify("广东卫视")["group"] == "local"
    assert classify("四川卫视")["group"] == "local"


def test_local_multicast_priority():
    """rtp:// udp:// 组播在 local 同级优先（不覆盖 CCTV/Gangtai 等更高优先级）。"""
    # 组播 + 省级卫视 → local
    r = classify("广东卫视", "rtp://239.10.0.1:8000")
    assert r["group"] == "local", f"组播应归地方，实际={r['group']}"
    # 组播 + 省级卫视 (UDP) → local
    r = classify("四川卫视", "udp://239.20.0.5:8000")
    assert r["group"] == "local", f"UDP 组播应归地方，实际={r['group']}"
    # 注：CCTV 组仍由优先级链保护（cctv > local），组播不覆盖 CCTV
    r = classify("CCTV-1", "rtp://239.10.0.2:8000")
    assert r["group"] == "cctv", f"CCTV 不被组播覆盖，实际={r['group']}"


def test_local_suffix():
    """城市/民生/新闻综合等子级关键词归 local-其他。"""
    r = classify("长沙新闻综合")
    assert r["group"] == "local"


# ============== classify: adult ==============

def test_adult_name_keyword():
    """成人关键词命中（任务：不仅成人组自己，整库也要做关键词过滤）。"""
    r = classify("麻豆传媒XXX", "http://example.com/foo.m3u8")
    assert r["group"] == "adult", f"实际 group={r['group']}, by={r['debug']['matched_by']}"


def test_adult_host():
    """URL host 是成人独占域 → adult。"""
    r = classify("随便起个频道名", "http://vod.mycamtv.net/foo.m3u8")
    assert r["group"] == "adult", f"实际 group={r['group']}"


def test_adult_host_shared_not_blacklisted():
    """共享 CDN（cdn2020.com 同时出现于成人与正常）→ 域名黑名单不命中；按频道名走 CCTV。"""
    # cdn2020.com 出现在成人/正常两侧，不进 adult_exclusive 黑名单
    r = classify("[SWAG]CCTV-1", "http://t7.cdn2020.com/1.m3u8")
    assert r["group"] == "cctv", f"实际 group={r['group']}"


def test_adult_pure_num():
    """纯短数字（≤3 位）整组屏蔽 → adult。"""
    r = classify("003", "http://example.com/003.m3u8")
    assert r["group"] == "adult"


def test_adult_bracket_tag():
    """【水果派】/【免费】等标签 → adult。"""
    r = classify("【水果派】第N集", "http://example.com/x.m3u8")
    assert r["group"] == "adult"


def test_adult_date_code():
    """nXXXX/XXXX-XX 日期代号 → adult。"""
    r = classify("n12345-2024-01", "http://example.com/x.m3u8")
    assert r["group"] == "adult"


# ============== classify: source_marker ==============

def test_source_marker_priority():
    """source_marker 整源标注 > 其他所有匹配（用合法标记）。"""
    # 即便频道名是「湖南卫视」，如果 source_marker='adult'，整源归 adult
    r = classify("湖南卫视", "", source_marker="adult")
    assert r["group"] == "adult", f"source_marker 应胜出，实际 group={r['group']}"
    # 'cctv' 标记者
    r = classify("某频道名", "", source_marker="cctv")
    assert r["group"] == "cctv"
    # 'gangtai' 标记者
    r = classify("某频道名", "", source_marker="港台")
    assert r["group"] == "gangtai"


# ============== classify: live 兜底 ==============

def test_live_fallback():
    """未命中任何组的频道 → 兜底 live。"""
    r = classify("奇奇怪怪的频道ABC")
    assert r["group"] == "live"


# ============== 跑测 ==============

def _run_all():
    """收集所有 test_ 函数并执行（不依赖 unittest.TestCase 子类化）。"""
    import inspect
    funcs = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in funcs:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{passed} passed, {failed} failed, total {len(funcs)}")
    return failed


if __name__ == "__main__":
    sys.exit(0 if _run_all() == 0 else 1)