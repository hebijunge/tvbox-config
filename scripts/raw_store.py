#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""raw_store.py — 输入层原始源镜像：落库 + 每日变化检测 + 上游删除保护。

背景（2026-09-27 落库改造）：直播与点播流水线的「输入层」改造——把上游原始文件
（直播 m3u/txt、点播配置上游 json、点播依赖 php/js/jar/txt/json）原样落盘到
raw/（上游）与 raw-vod/（点播依赖），按 sha256 做每日变化检测：

  - 变了（changed）  → 归档上一版到 history/<日期>/ 后覆盖入库，触发下游重跑；
  - 没变（unchanged）→ 沿用缓存，跳过该源聚合，避免每天全量无效重跑；
  - 上游删除（404/拉取失败）→ **绝不跟随删除**：保留本地最后可用版本，
    标记 status=deleted_upstream 并留痕（deleted_at / deleted_reason），
    继续供下游聚合与发布产物引用，直到上游恢复（重新可下载后自动清除标记）。

设计约束：
  - 本模块零第三方依赖、不 import fetch_merge（避免环）；fetch_merge 传入
    「仓库内相对落盘路径」，本模块只负责存取 / 哈希 / 清单 / 历史归档。
  - 清单字段日期一律用「日期」（YYYY-MM-DD）而非完整时间戳：没变的源
    last_checked 不产生 git diff，保持每日提交最小噪声。
  - 点播依赖路径与 deps/ 一一镜像（deps/<origin>/<path> → raw-vod/<origin>/<path>），
    审计脚本可直接对比「原始输入 vs 生效文件」。

环境开关：
  RAW_STORE=0          关闭（默认 1 开启）
  RAW_HISTORY_KEEP=60  每个源在 manifest.history 里保留的上一版归档条数
"""
import datetime
import gzip
import hashlib
import json
import os
import re
import threading

RAW_DIR = os.environ.get("RAW_DIR", "raw")              # 上游原始文件（raw/live/ 直播、raw/vod/ 点播配置）
RAW_VOD_DIR = os.environ.get("RAW_VOD_DIR", "raw-vod")  # 点播依赖原始文件（与 deps/ 镜像）
HISTORY_KEEP = int(os.environ.get("RAW_HISTORY_KEEP", "60"))
ENABLED = os.environ.get("RAW_STORE", "1") == "1"

STATUS_OK = "ok"
STATUS_DELETED = "deleted_upstream"

# 单次运行里的入库转移状态（manifest.status 之外的瞬时语义，供 fetch_merge 决定是否重跑下游）
ST_NEW = "new"                # 首次入库
ST_CHANGED = "changed"        # 内容有变化（旧版已归档）
ST_UNCHANGED = "unchanged"    # 内容无变化
ST_RECOVERED = "recovered"    # 上游恢复（此前 deleted_upstream，内容与存档一致 → 清除删除标记）
ST_CHANGED_RECOVER = "changed_recovered"  # 上游恢复且内容有更新
ST_RESTORED = "restored"      # 清单在而文件丢失 → 用本轮内容补齐
# 视为「下游需要重跑」的转移
RUN_TRIGGER_STATUSES = {ST_NEW, ST_CHANGED, ST_CHANGED_RECOVER, ST_RESTORED}

# 写锁：fetch_merge 的依赖收集跑线程池，ingest/mark_deleted 的
# load→modify→save 必须互斥，否则并发写 manifest.json 丢更新。
_LOCK = threading.Lock()


def today(now=None) -> str:
    dt = now or datetime.datetime.now()
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d")
    return str(dt)


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_seg(seg: str) -> str:
    """路径段清洗：去非法字符（对齐 fetch_merge._win_safe_seg 的 Linux 行为外再加一层保险）。"""
    s = re.sub(r'[<>:"|?*\x00-\x1f]', "_", seg).strip()
    s = s.rstrip(" .")
    return s or "_"


def safe_rel(rel: str) -> str:
    """仓库相对路径整体清洗（保留 / 分隔）。"""
    parts = [_safe_seg(p) for p in rel.split("/") if p not in ("", ".", "..")]
    return "/".join(parts) or "_unnamed_"


def ext_of(url: str, default: str = "bin") -> str:
    path = (url or "").split("?")[0].split("#")[0]
    ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    if not ext or len(ext) > 8 or not re.match(r"^[a-z0-9]+$", ext):
        return default
    return ext


def manifest_path(store: str) -> str:
    return os.path.join(store, "manifest.json")


def load_manifest(store: str) -> dict:
    try:
        with open(manifest_path(store), encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) else {}
    except Exception:  # noqa: BLE001 —— 清单缺失/损坏按空清单起步，文件本体是事实源
        return {}


def save_manifest(store: str, m: dict):
    os.makedirs(store, exist_ok=True)
    tmp = manifest_path(store) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, manifest_path(store))


def ingest(store: str, key: str, url: str, content: bytes, rel: str = None, now=None,
           store_bytes: bool = True) -> dict:
    """入库（带锁壳，见 _LOCK；实现见 _ingest_impl）。"""
    with _LOCK:
        return _ingest_impl(store, key, url, content, rel=rel, now=now,
                            store_bytes=store_bytes)


def _ingest_impl(store: str, key: str, url: str, content: bytes, rel: str = None, now=None,
                 store_bytes: bool = True) -> dict:
    """把一份原始文件入库。返回转移状态 dict。

    rel: 文件在 store 内的相对路径（调用方给出，保证与 deps/ 布局镜像）；
         缺省时由 url 推导。
    store_bytes: True = 字节级留档（变化时旧版归档到 <store>/history/<今日>/<rel>）；
                 False = 账本模式（只记 sha256/大小/状态，不落字节）——用于点播依赖
                 （deps/ 已 700MB+，再镜像字节会让仓库膨胀失控；deps/ 生效文件本身
                 就是「最后可用版本」的落盘，管线从不删除它，账本承担变化与删除留痕）。"""
    if content is None:
        raise ValueError("ingest content is None")
    rel = safe_rel(rel or _rel_from_url(url))
    day = today(now)
    sha = sha256_hex(content)
    m = load_manifest(store)
    ent = m.get(key) if isinstance(m.get(key), dict) else {}
    fs = os.path.join(store, rel)
    status = None
    archived = None
    if ent.get("sha256") == sha:
        if store_bytes and not os.path.isfile(fs):
            # 清单在、文件丢（手工误删等）→ 用本轮内容补齐
            _write(fs, content)
            status = ST_RESTORED
        elif ent.get("status") == STATUS_DELETED:
            # 上游恢复：内容与最后可用版一致 → 清除删除标记
            ent["status"] = STATUS_OK
            ent["recovered_at"] = day
            ent.pop("deleted_at", None)
            ent.pop("deleted_reason", None)
            status = ST_RECOVERED
        else:
            status = ST_UNCHANGED
        ent["last_checked"] = day
    else:
        status = ST_CHANGED if ent else ST_NEW
        if ent and ent.get("status") == STATUS_DELETED:
            status = ST_CHANGED_RECOVER
            ent.pop("deleted_at", None)
            ent.pop("deleted_reason", None)
        if store_bytes and ent and os.path.isfile(fs):
            archived = _archive_old(store, rel, day)
        if store_bytes:
            _write(fs, content)
        ent = {
            "url": url,
            "path": rel,
            "sha256": sha,
            "size": len(content),
            "ledger": None if store_bytes else True,
            "first_seen": ent.get("first_seen", day),
            "last_checked": day,
            "last_changed": day,
            "status": STATUS_OK,
            "history": _push_history(ent.get("history") if isinstance(ent.get("history"), list) else [],
                                     {"date": day, "sha256": (ent or {}).get("sha256", ""),
                                      "path": archived} if archived else
                                     ({"date": day, "sha256": (ent or {}).get("sha256", ""),
                                       "path": None} if ent else None)),
        }
        if not ent["history"]:
            ent.pop("history")
    ent.setdefault("url", url)
    ent.setdefault("path", rel)
    if not store_bytes:
        ent["ledger"] = True
    m[key] = ent
    save_manifest(store, m)
    return {"key": key, "status": status, "sha256": sha, "size": len(content),
            "path": fs, "archived": archived}


def mark_deleted(store: str, key: str, reason: str, now=None):
    """上游删除保护：拉取失败（404 等）时调用。只改清单标记，绝不删本地文件。

    返回动作 dict；store 里从未入库过该 key 时返回 None（无版本可保护）。"""
    with _LOCK:
        m = load_manifest(store)
        ent = m.get(key)
        if not isinstance(ent, dict):
            return None
        day = today(now)
        ent["last_checked"] = day
        if ent.get("status") != STATUS_DELETED:
            ent["status"] = STATUS_DELETED
            ent["deleted_at"] = day
        ent["deleted_reason"] = str(reason)[:200]
        save_manifest(store, m)
        return {"key": key, "status": STATUS_DELETED, "deleted_at": ent.get("deleted_at", day),
                "path": os.path.join(store, ent.get("path", ""))}


def manifest_has(store: str, key: str) -> bool:
    """该 key 是否已在清单（字节留档与账本模式通用；read_stored 对账本条目
    恒为 None——账本不落字节，存在性判断必须走清单本体）。"""
    return isinstance(load_manifest(store).get(key), dict)


def read_stored(store: str, key: str):
    """读取该 key 最后可用版本的原始字节；从未入库或文件丢失返回 None。

    C6：manifest.compressed=True 时自动 gunzip 解压。"""
    ent = load_manifest(store).get(key)
    if not isinstance(ent, dict):
        return None
    fs = os.path.join(store, ent.get("path", ""))
    try:
        if os.path.isfile(fs):
            with open(fs, "rb") as f:
                data = f.read()
            if ent.get("compressed"):
                try:
                    data = gzip.decompress(data)
                except OSError:
                    pass
            return data
    except OSError:  # noqa: BLE001
        pass
    return None


def summarize(store: str) -> dict:
    m = load_manifest(store)
    out = {"total": len(m), "ok": 0, "deleted_upstream": 0}
    for ent in m.values():
        if isinstance(ent, dict) and ent.get("status") == STATUS_DELETED:
            out["deleted_upstream"] += 1
        else:
            out["ok"] += 1
    return out


# ---------------- 内部 ----------------

def _rel_from_url(url: str) -> str:
    path = (url or "").split("?")[0].split("#")[0]
    segs = [s for s in path.split("/") if s not in ("", ".")]
    segs = segs[3:] if len(segs) > 3 and segs[0] in ("http:", "https:") else segs
    name = segs[-1] if segs else ""
    if not name:
        name = hashlib.md5(url.encode()).hexdigest()[:12]
    return _safe_seg(name)


def _write(fs: str, content: bytes):
    os.makedirs(os.path.dirname(fs) or ".", exist_ok=True)
    with open(fs, "wb") as f:
        f.write(content)


def _archive_old(store: str, rel: str, day: str):
    """变化覆盖前把旧版归档到 history/<日期>/<rel>；失败不影响入库。

    C6 分层：归档时对 >7 天的旧文件做 gzip 压缩（.gz 后缀），manifest.path 记 compressed。
    """
    src = os.path.join(store, rel)
    try:
        if not os.path.isfile(src):
            return None
        dst = os.path.join(store, "history", day, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
        return os.path.relpath(dst, store)
    except OSError:  # noqa: BLE001
        return None


def _compress_old_history(store: str, days: int = 7):
    """C6：把 history/ 下超过 days 天未变的归档文件 gzip 压缩（只压不删）。"""
    hist = os.path.join(store, "history")
    if not os.path.isdir(hist):
        return 0
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    n = 0
    for day_dir in os.listdir(hist):
        if day_dir >= cutoff:
            continue
        d = os.path.join(hist, day_dir)
        if not os.path.isdir(d):
            continue
        for root, _, names in os.walk(d):
            for fn in names:
                if fn.endswith(".gz"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    with open(fp, "rb") as f:
                        data = f.read()
                    with gzip.open(fp + ".gz", "wb", compresslevel=6) as gz:
                        gz.write(data)
                    os.remove(fp)
                    n += 1
                except OSError:
                    pass
    return n


def _push_history(hist: list, entry):
    """环形保留最近 HISTORY_KEEP 条归档记录。"""
    if entry is None:
        return hist
    hist = list(hist) + [entry]
    return hist[-HISTORY_KEEP:] if HISTORY_KEEP > 0 else hist
