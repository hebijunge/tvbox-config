#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-A 冒烟测试：validated.json 读写往返 + record_result 历史 + 跨日衰减。"""
import json
import os
import shutil
import sys

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, "scripts")
import validated_state as vs  # noqa: E402
import fetch_merge as fm  # noqa: E402

# 备份真实状态，测试后恢复
shutil.copy("state/validated.json", "/tmp/validated.bak.json")
ok = True
try:
    # 1) GitHub 线读路径
    st = fm.load_state()
    assert len(st) == 694, len(st)
    print("1 load_state sources:", len(st))

    # 2) record_result（假条目，不污染真实源）→ 历史 + ckey + 衰减
    st["p1a_selftest"] = {"name": "p1a_selftest"}
    r = fm.record_result(st, "p1a_selftest", False, [], url="https://ghproxy.net/https://raw.githubusercontent.com/P1A/selftest/main/cfg.json")
    assert r == "failing", r
    ent = st["p1a_selftest"]
    assert ent["ckey"] == "raw.githubusercontent.com/P1A/selftest/main/cfg.json", ent.get("ckey")
    assert ent["history"].get(vs.today_bj()) == "unavailable"
    fm.save_state(st)
    doc = vs.load_validated()
    assert "p1a_selftest" in doc["sources"]
    print("2 record+save: ckey/history 落盘 OK, decay=", doc["sources"]["p1a_selftest"]["decay"])

    # 3) 连续 3 日失败 → watch；7 日 → out；通过复位
    e = doc["sources"]["p1a_selftest"]
    for i in range(1, 8):
        e["history"]["2026-09-%02d" % (17 + i)] = "unavailable"
    vs.apply_decay(doc)
    assert e["decay"]["stage"] == "out" and e["decayed"] is True, e["decay"]
    # watch 边界：另一假条目连续 3 日失败
    w = doc["sources"].setdefault("p1a_selftest_watch", {"name": "p1a_selftest_watch"})
    for d in ("2026-09-23", "2026-09-24", "2026-09-25"):
        w["history"] = w.get("history") or {}
        w["history"][d] = "unavailable"
    vs.apply_decay(doc)
    assert w["decay"]["stage"] == "watch" and not w.get("decayed"), w["decay"]
    dec = {}
    for x in doc["sources"].values():
        s = (x.get("decay") or {}).get("stage", "active")
        dec[s] = dec.get(s, 0) + 1
    assert len(vs.active_sources(doc)) == dec.get("active", 0)
    assert dec.get("out", 0) == 14 + 1 and dec.get("active", 0) + dec.get("watch", 0) + dec.get("out", 0) == len(doc["sources"])
    e["history"][vs.today_bj()] = "fully"
    vs.apply_decay(doc)
    assert e["decay"]["stage"] == "active" and not e.get("decayed"), e["decay"]
    print("3 decay watch/out/回捞 OK; active_sources=", len(vs.active_sources(doc)))

    # 4) 飞书线桥接合并（拿真实复测样本 3 条）
    _retest_fixture = "../retest_20260925.json"  # workdir 外部复测样本，CI/异构工作树下可能缺失
    rows = [{"name": r["name"], "url": r["url"], "level": r["level"], "date": "2026-09-25"}
            for r in (json.load(open(_retest_fixture))[:3] if os.path.exists(_retest_fixture) else [])
            if r.get("url")]
    vs.migrate(".", extra_feishu=rows, note="P1-A selftest 桥接")
    doc2 = vs.load_validated()
    assert doc2["schema"] == vs.SCHEMA
    print("4 bridge merge OK; rows=", len(rows))

    # 5) 规范键单元用例
    cases = [
        ("https://GHProxy.net/https://raw.githubusercontent.com/A/B/main/c.json",
         "raw.githubusercontent.com/A/B/main/c.json"),
        ("http://www.Example.com:80/x/", "example.com/x"),
        ("https://api.example.com:443/v1?a=1#frag", "api.example.com/v1?a=1"),
    ]
    for u, want in cases:
        got = vs.canonical_key(u)
        assert got == want, (u, got, want)
    assert vs.normalize_name("【高清】CCTV-1 综合") == vs.normalize_name("cctv1综合")
    print("5 canonical_key/normalize_name OK")
    print("SMOKE PASS")
except AssertionError as e:
    ok = False
    print("SMOKE FAIL:", e)
finally:
    shutil.copy("/tmp/validated.bak.json", "state/validated.json")
    print("状态已恢复到迁移版")
# unittest discover 兼容：导入期不触发 SystemExit（直跑仍按退出码收尾）
if __name__ == "__main__":
    sys.exit(0 if ok else 1)
