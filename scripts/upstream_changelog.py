#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上游配置变更追踪（P0，全 stdlib）。

每次上游拉取成功后，对配置内容做归一化（去空白、递归排序 key）后计算 sha256，
与该 url 上一次记录的 sha256 比较：内容真正变化才追加一行到
``state/upstream_changelog.jsonl``。仅空白/key 顺序差异不产生记录。

jsonl 每行字段：
    date           北京时间 ISO（YYYY-MM-DDTHH:MM:SS+08:00）
    url            上游配置 URL
    sha256         归一化后内容 sha256
    changed_fields 与上一版相比顶层 key 的对称差（新增/消失的顶层字段）
    size           原始字节数

用法（脚本内被 fetch_merge 调用，也可独立自检）：
    from upstream_changelog import record
    record(url, parsed_config_or_raw_bytes, size=len(raw))
"""
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta

BEIJING = timezone(timedelta(hours=8))
CHANGELOG_PATH = os.environ.get("UPSTREAM_CHANGELOG", "state/upstream_changelog.jsonl")


def _normalize(obj):
    """递归排序 dict key；字符串 strip；list/tuple 统一成 list。"""
    if isinstance(obj, dict):
        return {str(k): _normalize(obj[k]) for k in sorted(obj.keys(), key=str)}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, str):
        return obj.strip()
    return obj


def normalized_sha256(obj) -> str:
    canon = json.dumps(_normalize(obj), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _load_last(path: str) -> dict:
    """读 jsonl，返回 {url: 最后一条记录}。文件缺失/损坏返回空。"""
    last = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                u = rec.get("url")
                if u:
                    last[u] = rec
    except OSError:
        pass
    return last


def record(url: str, config, size: int = 0, path: str = None) -> bool:
    """记录一次上游拉取。

    config: 已解析的 tvbox dict，或 m3u/txt 的原始 bytes。
    返回 True 表示内容有变化、新追加了一行；False 表示与上一版一致未写入。
    """
    path = path or CHANGELOG_PATH
    if isinstance(config, (bytes, bytearray)):
        text = config.decode("utf-8", "replace").strip()
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        top_keys = []
    elif isinstance(config, dict):
        sha = normalized_sha256(config)
        top_keys = sorted(str(k) for k in config.keys())
    else:
        return False

    prev = _load_last(path).get(url)
    if prev and prev.get("sha256") == sha:
        return False  # 仅空白/格式差异，视为无变化

    prev_keys = set(prev.get("top_keys", [])) if prev else set()
    changed_fields = sorted(set(top_keys) ^ prev_keys) if prev else top_keys

    rec = {
        "date": datetime.now(BEIJING).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "url": url,
        "sha256": sha,
        "changed_fields": changed_fields,
        "size": size or (len(config) if isinstance(config, (bytes, bytearray)) else 0),
        "top_keys": top_keys,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


if __name__ == "__main__":
    # 自检：用一个假 dict 跑两次，第二次应不写入
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "_ucl_selftest.jsonl")
    if os.path.exists(tmp):
        os.remove(tmp)
    a = {"sites": [{"key": "x"}], "spider": "a.jar"}
    b = {"sites": [{"key": "y"}], "spider": "a.jar", "lives": []}
    print("first  :", record("https://t/a.json", a, size=10, path=tmp))
    print("same   :", record("https://t/a.json", a, size=10, path=tmp))
    print("changed:", record("https://t/a.json", b, size=12, path=tmp))
    with open(tmp, encoding="utf-8") as f:
        print("lines:", f.read().count(chr(10)))
