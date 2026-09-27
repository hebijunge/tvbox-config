#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一上游配置管理（全仓库唯一事实源）。

把分散在 fetch_merge.py 硬编码 UPSTREAMS/LIVE_UPSTREAMS/SHORTS_ADULT_UPSTREAMS、
state/extra_upstreams.json（canary）、state/blacklist_auto.txt 的上游信息统一到
config/upstreams.json。

字段
----
    name          上游标识（唯一）
    url           配置 URL
    type          vod / live / mixed
    priority      整数，越大越优先（默认 50）
    enabled       是否启用（False = canary 观察 / 黑名单）
    added_at      加入日期 YYYY-MM-DD
    source        github / gitee / gitlab / canary / manual / discover
    discover_date 发现日期
    last_commit_at 最近 commit 日期（可空）
    format        json / m3u / obscured / encrypted
    notes         备注
    mirrors       可选镜像 URL 列表

向后兼容
--------
fetch_merge.py 仍保留硬编码 UPSTREAMS 等作为 fallback：config/upstreams.json
缺失或损坏时回退到硬编码，不破坏现有 CI。
"""
import json
import os
from typing import Optional

CONFIG_PATH = os.environ.get("UPSTREAM_CONFIG", "config/upstreams.json")

_cache: Optional[dict] = None
_cache_mtime: float = 0


def load_config(force_reload: bool = False) -> dict:
    """加载 config/upstreams.json，返回 {"version":..., "upstreams": [...]}。

    文件缺失或损坏时返回空配置（调用方应回退到硬编码）。
    """
    global _cache, _cache_mtime
    if not force_reload and _cache is not None:
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
            if mtime == _cache_mtime:
                return _cache
        except OSError:
            pass
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("upstreams"), list):
            _cache = data
            _cache_mtime = os.path.getmtime(CONFIG_PATH)
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "upstreams": []}


def save_config(data: dict):
    """保存配置到 config/upstreams.json（原子写入）。"""
    os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CONFIG_PATH)
    global _cache, _cache_mtime
    _cache = data
    _cache_mtime = os.path.getmtime(CONFIG_PATH)


def get_upstreams(upstream_type: Optional[str] = None,
                  enabled_only: bool = True) -> list:
    """查询上游列表。

    upstream_type: 过滤类型（vod/live/mixed），None = 全部
    enabled_only: 只返回 enabled=True 的
    """
    data = load_config()
    result = []
    for u in data.get("upstreams", []):
        if upstream_type and u.get("type") != upstream_type:
            continue
        if enabled_only and not u.get("enabled", True):
            continue
        result.append(u)
    return result


def get_upstream(name: str) -> Optional[dict]:
    """按 name 查找单个上游。"""
    for u in load_config().get("upstreams", []):
        if u.get("name") == name:
            return u
    return None


def add_upstream(entry: dict) -> bool:
    """新增上游（name 重复则返回 False）。"""
    data = load_config()
    name = entry.get("name", "")
    if not name:
        return False
    for u in data["upstreams"]:
        if u.get("name") == name:
            return False
    data["upstreams"].append(entry)
    save_config(data)
    return True


def update_upstream(name: str, **kwargs) -> bool:
    """更新上游字段。"""
    data = load_config()
    for u in data["upstreams"]:
        if u.get("name") == name:
            u.update(kwargs)
            save_config(data)
            return True
    return False


def to_fetch_merge_format(upstream_type: Optional[str] = None) -> list:
    """转换为 fetch_merge 兼容的 [{name, kind, url, mirrors?}] 格式。

    kind: tvbox（vod/mixed）或 m3u（live）。
    """
    result = []
    for u in get_upstreams(upstream_type=upstream_type, enabled_only=True):
        kind = "m3u" if u.get("type") == "live" else "tvbox"
        entry = {"name": u["name"], "kind": kind, "url": u["url"]}
        if u.get("mirrors"):
            entry["mirrors"] = u["mirrors"]
        result.append(entry)
    return result


def stats() -> dict:
    """返回配置统计。"""
    data = load_config()
    entries = data.get("upstreams", [])
    return {
        "total": len(entries),
        "enabled": sum(1 for u in entries if u.get("enabled", True)),
        "by_type": {
            t: sum(1 for u in entries if u.get("type") == t)
            for t in ("vod", "live", "mixed")
        },
        "by_source": {},
    }


if __name__ == "__main__":
    s = stats()
    print(json.dumps(s, ensure_ascii=False, indent=2))
