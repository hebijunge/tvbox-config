#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立验活脚本（validate workflow 用，与每日拉取 workflow 分离——azhansy/ds-tvbox 模式）：
  拉取全部上游 → P0 质量门槛 → 更新连续失败状态/自动停用 → 写 checks.json → README 可用性锚点回写。
不产出 tvbox.json（拉取与验活频率解耦）。
"""
import os
import sys
import concurrent.futures as cf
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_merge import (  # noqa: E402
    ALL_UPSTREAMS, BEIJING, CONCURRENCY,
    fetch_raw, evaluate_upstream, load_state, save_state, read_name_list,
    enabled_of, record_result, sync_blacklist_auto, write_checks,
    update_readme_availability, sha12, STATE_FILE, BLACKLIST_MANUAL, WHITELIST_MANUAL,
)


def main() -> int:
    now = datetime.now(BEIJING)
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S") + " +08:00"
    state = load_state()
    blacklist_manual = read_name_list(BLACKLIST_MANUAL)
    whitelist_manual = read_name_list(WHITELIST_MANUAL)

    fetchable = []
    for u in ALL_UPSTREAMS:
        ok, tag = enabled_of(u, state, blacklist_manual, whitelist_manual)
        fetchable.append((u, ok, tag))

    def do_fetch(item):
        u, ok, _tag = item
        if not ok:
            return u, None, "skipped", "", ""
        raw, info, ok_url = fetch_raw(u["url"], u.get("mirrors"))
        return u, raw, info, ok_url, ""

    print(f"[validate] 检测 {len(ALL_UPSTREAMS)} 个上游 @ {generated_at}", flush=True)
    records = []
    disabled_now = []
    with cf.ThreadPoolExecutor(min(8, CONCURRENCY)) as ex:
        for (u, fetchable_ok, tag), (u2, raw, info, ok_url, d_method) in zip(fetchable, ex.map(do_fetch, fetchable)):
            name = u["name"]
            state_ent = state.get(name) if isinstance(state.get(name), dict) else {}
            rec = {
                "name": name, "url": u["url"], "kind": u["kind"],
                "http_ms": 0, "channel": "", "bytes": 0, "sha256": "",
                "sites": 0, "lives": 0, "parses": 0,
                "merged_sites": 0, "merged_lives": 0, "merged_parses": 0,
                "grade": "不可用", "error": "",
                "status": tag, "fail_count": int(state_ent.get("fail_count", 0)),
                "last_ok_at": state_ent.get("last_ok_at", ""),
            }
            if not fetchable_ok:
                records.append(rec)
                print(f"  SKIP {name}（{tag}）", flush=True)
                continue
            if raw is not None:
                rec["bytes"] = len(raw)
                rec["sha256"] = sha12(raw)
            ok_eval, status_tag, detail, err = evaluate_upstream(u, raw)
            rec["status"] = status_tag
            rec["error"] = err or ""
            if raw is None:
                rec["error"] = info
            outcome = record_result(state, name, ok_eval, whitelist_manual)
            if outcome == "disabled_now":
                disabled_now.append(name)
            rec["fail_count"] = int(state[name].get("fail_count", 0))
            rec["last_ok_at"] = state[name].get("last_ok_at", "")
            records.append(rec)
            mark = "OK" if ok_eval else status_tag.upper()
            print(f"  {mark} {name}: {rec['bytes']}B #{rec['sha256']} fail={rec['fail_count']} {err}",
                  flush=True)

    sync_blacklist_auto(state)
    save_state(state)
    write_checks(records, generated_at)
    update_readme_availability(records)
    ok_n = sum(1 for r in records if r["status"] == "ok")
    print(f"[validate] 完成：ok={ok_n}/{len(records)} 本轮自动停用={disabled_now or '无'}", flush=True)
    if ok_n == 0:
        print("[validate] 所有上游均不可用，需要人工介入", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
