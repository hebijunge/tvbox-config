#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
raw 落库差异审计（2026-09-27 落库改造交付物）：
对比「原始输入（raw/ 入库镜像 + raw-vod/ 账本）」与「发布产物（lives/*.txt、
deps/ 生效文件）」，定位每个剔除/替换/缺失的来源，输出 state/raw_audit.json。

直播侧（raw/live/，字节级留档）：
  - 逐源解析入库镜像（与每日拉取同一 parse_m3u 口径）→ URL 集合；
  - 与发布产物 lives/*.txt（含 groups/）URL 集合对比 → 每源 kept/dropped 数
    与 dropped 样例（定位「这个 URL 是哪个源贡献的、现在产物里没有」——
    典型去向：探活死链剔除 / 分组筛选）；
  - deleted_upstream 源以保留的最后可用版参与对比（沿用版本仍在产物里
    = 上游删除保护生效）。

点播侧（raw-vod/，账本模式只记 sha256）：
  - 账本 sha256 vs deps/ 生效文件实际 sha256 → match / mismatch / missing；
  - deleted_upstream 依赖的 deps/ 本地文件仍存在 = 删除保护生效；
  - mismatch/missing 逐条列出（mismatch 通常= 人工改过 deps 文件或账本过期）。

用法：
  python3 scripts/raw_audit.py                     # 默认输出 state/raw_audit.json
  python3 scripts/raw_audit.py --max-sample 5      # 每源 dropped 样例条数
零第三方依赖；parse_m3u 优先复用 fetch_merge（与生产口径一致），import 失败
时退回内置精简解析（m3u/txt 两种格式）。
"""
import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import raw_store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVES_DIR = os.path.join(ROOT, "lives")
DEPS_DIR = os.path.join(ROOT, "deps")

# ---- 直播解析（口径与 fetch_merge.parse_m3u 对齐；import 失败时兜底） ----
_EXTINF_RE = re.compile(r"^#EXTINF:\s*-?\d*\s*,?(.*)$")
_TXT_GENRE_RE = re.compile(r"^(.*),\s*#genre#\s*$")


def _mini_parse_m3u(raw: bytes):
    """内置兜底解析：返回 [(频道名, 分组, url)]。"""
    txt = raw.decode("utf-8", "replace")
    entries, attr_name, group = [], None, ""
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            m = _EXTINF_RE.match(line)
            rest = m.group(1) if m else ""
            gm = re.search(r'group-title="([^"]*)"', rest)
            group = gm.group(1).strip() if gm else ""
            attr_name = rest.rsplit(",", 1)[-1].strip() if "," in rest else rest.strip()
            continue
        if line.startswith("#"):
            continue
        gm = _TXT_GENRE_RE.match(line)
        if gm:
            group, attr_name = gm.group(1).strip(), None
            continue
        if "," in line and not attr_name:
            name, _, urls = line.partition(",")
            for u in urls.split("#"):
                u = u.strip()
                if u.lower().startswith(("http://", "https://")):
                    entries.append((name.strip(), group, u))
            continue
        if attr_name and line.lower().startswith(("http://", "https://")):
            entries.append((attr_name, group, line))
    return entries


def _parse_m3u(raw: bytes):
    try:
        from fetch_merge import parse_m3u as fm_parse  # noqa: PLC0415
        return fm_parse(raw)
    except Exception:  # noqa: BLE001 —— 审计不能因为 import 失败就整个挂掉
        return _mini_parse_m3u(raw)


# ---- 发布产物 URL 集合 ----
def published_live_urls():
    """lives/*.txt（含 groups/*.txt）里出现的全部 URL。"""
    urls = set()
    for base, _dirs, files in os.walk(LIVES_DIR):
        for fn in files:
            if not fn.endswith(".txt"):
                continue
            fp = os.path.join(base, fn)
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "," not in line:
                            continue
                        _name, _, rhs = line.partition(",")
                        for u in rhs.split("#"):
                            u = u.strip()
                            if u.lower().startswith(("http://", "https://")):
                                urls.add(u)
            except OSError:
                continue
    return urls


def audit_live(max_sample: int) -> dict:
    manifest = raw_store.load_manifest(os.path.join(raw_store.RAW_DIR, "live"))
    pub = published_live_urls()
    sources, deleted_kept = [], 0
    total_raw = kept_total = 0
    for key, ent in sorted(manifest.items()):
        if not isinstance(ent, dict):
            continue
        fp = os.path.join(raw_store.RAW_DIR, "live", ent.get("path", ""))
        try:
            with open(fp, "rb") as f:
                raw = f.read()
        except OSError:
            sources.append({"source": key, "status": ent.get("status", "?"),
                            "error": "raw 文件丢失"})
            continue
        entries = _parse_m3u(raw)
        src_urls = {u for _n, _g, u in entries}
        kept = src_urls & pub
        dropped = src_urls - pub
        total_raw += len(src_urls)
        kept_total += len(kept)
        if ent.get("status") == raw_store.STATUS_DELETED:
            deleted_kept += 1
        sample = []
        for _n, g, u in entries:
            if u in dropped:
                sample.append({"group": g, "url": u[:160]})
                if len(sample) >= max_sample:
                    break
        sources.append({
            "source": key, "status": ent.get("status", raw_store.STATUS_OK),
            "urls": len(src_urls), "kept": len(kept), "dropped": len(dropped),
            "kept_ratio": round(len(kept) / len(src_urls), 4) if src_urls else None,
            "dropped_sample": sample,
        })
    return {
        "side": "live", "raw_dir": "raw/live", "published_urls": len(pub),
        "sources": sources,
        "deleted_upstream_kept": deleted_kept,
        "summary": {
            "raw_urls_total": total_raw, "raw_urls_in_published": kept_total,
            "raw_urls_dropped": total_raw - kept_total,
            "note": "dropped 去向 = 探活死链剔除/分组筛选（live-prune 独立职能），审计只定位来源",
        },
    }


def audit_vod() -> dict:
    manifest = raw_store.load_manifest(raw_store.RAW_VOD_DIR)
    deps_files = []
    for base, _dirs, files in os.walk(DEPS_DIR):
        for fn in files:
            fp = os.path.join(base, fn)
            deps_files.append(os.path.relpath(fp, ROOT))
    deps_set = set(deps_files)
    items, mismatch, missing = [], [], []
    deleted = []
    for key, ent in sorted(manifest.items()):
        if not isinstance(ent, dict):
            continue
        rel = ent.get("path", "")
        fp = os.path.join(ROOT, "deps", rel)
        it = {"key": key, "path": rel, "status": ent.get("status", raw_store.STATUS_OK),
              "ledger": bool(ent.get("ledger"))}
        if ent.get("status") == raw_store.STATUS_DELETED:
            deleted.append(rel)
            it["protection"] = "deps 文件仍存在" if os.path.isfile(fp) else "deps 文件缺失!"
            if not os.path.isfile(fp):
                missing.append(rel)
        if os.path.isfile(fp):
            h = hashlib.sha256()
            with open(fp, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() == ent.get("sha256"):
                it["check"] = "match"
            else:
                it["check"] = "mismatch"
                mismatch.append(rel)
        else:
            it["check"] = "missing"
            if ent.get("status") != raw_store.STATUS_DELETED:
                missing.append(rel)
        items.append(it)
    return {
        "side": "vod", "ledger_dir": "raw-vod", "deps_entries": len(deps_set),
        "manifest_entries": len(items), "match": len(items) - len(mismatch) - len(missing),
        "mismatch": mismatch, "missing": missing,
        "deleted_upstream": deleted,
        "deleted_upstream_protected": sum(
            1 for r in deleted if os.path.isfile(os.path.join(ROOT, "deps", r))),
        "note": "ledger=账本模式（只记 sha256，deps/ 生效文件即最后可用版落盘）；"
                "mismatch=deps 文件与账本 sha 不一致（人工改动或账本过期）",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "state", "raw_audit.json"))
    ap.add_argument("--max-sample", type=int, default=3)
    args = ap.parse_args()

    report = {"live": audit_live(args.max_sample), "vod": audit_vod()}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, sort_keys=True)
    lv = report["live"]
    vd = report["vod"]
    print(f"[raw-audit] 直播：{len(lv['sources'])} 源 / raw URL {lv['summary']['raw_urls_total']} "
          f"→ 产物 {lv['summary']['raw_urls_in_published']}（剔除 {lv['summary']['raw_urls_dropped']}）；"
          f"deleted_upstream 沿用 {lv['deleted_upstream_kept']} 源", flush=True)
    print(f"[raw-audit] 点播：账本 {vd['manifest_entries']} 条 / match {vd['match']} "
          f"/ mismatch {len(vd['mismatch'])} / missing {len(vd['missing'])}；"
          f"deleted_upstream {len(vd['deleted_upstream'])} 条（保护生效 "
          f"{vd['deleted_upstream_protected']}）", flush=True)
    print(f"[raw-audit] 报告已写入 {os.path.relpath(args.out, ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
