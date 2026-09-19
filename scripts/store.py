#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接口入库与检测历史（SQLite）——「每日增量、可追溯」的地基。

为什么要有它
------------
之前项目只有「JSON 产物 + state/*.json 的轻量失败计数」，缺三件事：
 1. 没有**检测历史**（答不出「这个源连续几天失效 / 从哪天开始坏 / 延迟趋势」）
 2. 没有**依赖关系持久化**（jar / spider / ext 父配置只散落在产物里）
 3. 没有**统一健康状态**（导出时无法按健康度筛选，"仅健康可用"清单无从产出）

设计原则
--------
 * **幂等**：所有写入都按主键 upsert，同一天跑 N 次结果一致（重复导入只更新，不重复计数）
 * **增量**：只更新有变化的字段；检测记录是追加（历史），接口本体是更新（当前态）
 * **可追溯**：每次检测留痕（状态码/延迟/等级/失败原因/探针来源），支持回溯任意时间点

数据模型
--------
  interfaces  接口当前态（主键 key）：地址/类型/来源/最后检测/健康状态/连续失败次数
  checks      检测历史（追加）：每次实测一条，保留 KEEP_DAYS 天
  deps        依赖关系（主键 key+dep_type+dep_ref）：jar / ext 文件 / 本地 js / 全局 spider
  upstreams   上游健康：拉取结果、站点数、新增站点、连续失败
  runs        运行日志：每阶段开始/结束/成败/备注

用法
----
    python scripts/store.py --init
    python scripts/store.py --ingest-sites tvbox.json
    python scripts/store.py --ingest-probes probe/*.json
    python scripts/store.py --ingest-upstreams status.json
    python scripts/store.py --stats
    python scripts/store.py --prune            # 清理过期检测历史
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta

DEFAULT_DB = os.path.join("state", "tvbox.db")
KEEP_DAYS = int(os.environ.get("CHECK_KEEP_DAYS", "30"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS interfaces (
  key           TEXT PRIMARY KEY,
  name          TEXT,
  api           TEXT,
  type          INTEGER,
  ext           TEXT,
  jar           TEXT,
  group_name    TEXT,
  source        TEXT,
  first_seen    TEXT,
  last_seen     TEXT,
  last_check_at TEXT,
  health        TEXT DEFAULT 'unknown',
  latency_ms    INTEGER,
  status_code   INTEGER,
  level         TEXT,
  reason        TEXT,
  health_rank   INTEGER DEFAULT 0,
  fail_streak   INTEGER DEFAULT 0,
  updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_if_health ON interfaces(health);
CREATE INDEX IF NOT EXISTS idx_if_group  ON interfaces(group_name);
CREATE INDEX IF NOT EXISTS idx_if_source ON interfaces(source);

CREATE TABLE IF NOT EXISTS checks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  key         TEXT NOT NULL,
  checked_at  TEXT NOT NULL,
  ok          INTEGER,
  status_code INTEGER,
  latency_ms  INTEGER,
  level       TEXT,
  reason      TEXT,
  probe       TEXT
);
CREATE INDEX IF NOT EXISTS idx_chk_key ON checks(key);
CREATE INDEX IF NOT EXISTS idx_chk_at  ON checks(checked_at);

CREATE TABLE IF NOT EXISTS deps (
  key        TEXT NOT NULL,
  dep_type   TEXT NOT NULL,
  dep_ref    TEXT NOT NULL,
  local_path TEXT,
  md5        TEXT,
  upstream   TEXT,
  updated_at TEXT,
  PRIMARY KEY (key, dep_type, dep_ref)
);

CREATE TABLE IF NOT EXISTS upstreams (
  url           TEXT PRIMARY KEY,
  name          TEXT,
  kind          TEXT,
  last_fetch_at TEXT,
  ok            INTEGER,
  sites_count   INTEGER,
  new_sites     INTEGER,
  fail_streak   INTEGER DEFAULT 0,
  note          TEXT
);

CREATE TABLE IF NOT EXISTS lives (
  key           TEXT PRIMARY KEY,
  name          TEXT,
  url           TEXT,
  type          INTEGER,
  source        TEXT,
  last_check_at TEXT,
  health        TEXT DEFAULT 'unknown',
  latency_ms    INTEGER,
  updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_lv_health ON lives(health);

CREATE TABLE IF NOT EXISTS runs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT,
  ended_at   TEXT,
  stage      TEXT,
  ok         INTEGER,
  note       TEXT
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[store {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def connect(path: str = DEFAULT_DB) -> sqlite3.Connection:
    """连接（自动建库建表）。目录不存在时创建。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn) -> None:
    """轻量迁移：老库缺列时补上（幂等，重复执行无副作用）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(interfaces)")}
    if "health_rank" not in cols:
        conn.execute("ALTER TABLE interfaces ADD COLUMN health_rank INTEGER DEFAULT 0")


# ---------------- 健康分级 ----------------
# healthy  = 实测能搜到/能播（最深能力达标）
# degraded = 能连通但能力弱（仅首页/分类，或搜索无命中）
# dead     = 实测失败（类缺失/解析失败/站点已死）
# unknown  = 没测过，或超时/本机不可达（不妄下结论）
_HEALTHY = {"L3", "C3", "C4", "C5", "D3", "D4", "D5"}
_DEGRADED = {"L1", "L2", "C1", "C2", "D1", "D2", "S1", "S2", "S3"}
_DEAD = {"L0", "C0", "D0"}
_UNKNOWN = {"L?", "C?", "D?", "S?"}


def classify(level, ok=None) -> str:
    """按实测等级判定健康状态。"""
    lv = (level or "").strip()
    if lv in _HEALTHY:
        return "healthy"
    if lv in _DEGRADED:
        return "degraded"
    if lv in _DEAD:
        return "dead"
    if lv in _UNKNOWN:
        return "unknown"
    # 没有等级字段时（如 spider 连通性探针）用 ok 兜底
    if ok is True:
        return "degraded"
    if ok is False:
        return "dead"
    return "unknown"


# 探针权威性：数字越大，能证明的能力越深（浅探针的结论不能覆盖深探针）
PROBE_PRIORITY = {
    "csp_probe.json": 4,     # 真机五关（首页/分类/搜索/详情/播放）
    "drpy_probe.json": 4,    # Node 沙箱五关
    "sites_probe.json": 3,   # HTTP L1-L3 采集接口实测
    "js_probe.json": 2,      # JS 分类页实测
    "spider_probe.json": 1,  # type3 连通性（只能证明通不通）
}
_HEALTH_ORDER = {"healthy": 3, "degraded": 2, "unknown": 1, "dead": 0}


def probe_priority(probe) -> int:
    return PROBE_PRIORITY.get(os.path.basename(probe or ""), 0)


def _norm_ext(ext) -> str:
    if ext is None:
        return ""
    if isinstance(ext, str):
        return ext
    try:
        return json.dumps(ext, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(ext)


# ---------------- 写入（幂等） ----------------
def upsert_interface(conn, site: dict, source: str = None, seen_at: str = None) -> None:
    """接口入库：已存在则更新（不动 first_seen），不存在则插入。"""
    key = site.get("key")
    if not key:
        return
    seen = seen_at or now()
    conn.execute("""
        INSERT INTO interfaces (key, name, api, type, ext, jar, group_name, source,
                                first_seen, last_seen, updated_at)
        VALUES (:key,:name,:api,:type,:ext,:jar,:group,:source,:seen,:seen,:now)
        ON CONFLICT(key) DO UPDATE SET
            name=excluded.name, api=excluded.api, type=excluded.type,
            ext=excluded.ext, jar=excluded.jar,
            group_name=COALESCE(excluded.group_name, interfaces.group_name),
            source=COALESCE(excluded.source, interfaces.source),
            last_seen=excluded.last_seen, updated_at=excluded.updated_at
    """, {
        "key": key, "name": site.get("name"), "api": site.get("api"),
        "type": site.get("type"), "ext": _norm_ext(site.get("ext")),
        "jar": site.get("jar"), "group": site.get("group"),
        "source": source or site.get("source"), "seen": seen, "now": now(),
    })


def record_check(conn, key: str, ok=None, status_code=None, latency_ms=None,
                 level=None, reason=None, probe=None, checked_at=None) -> str:
    """记录一次检测（历史追加），并按「探针权威性」决定是否回写健康结论。

    为什么不能直接覆盖：一个源会被多路探针各测一次，深度差别很大——
      五关实测(csp/drpy) 能证明「能搜能播」；连通性探针(spider)只能证明「通不通」。
    若让浅探针的结论覆盖深探针，会出现「五关全通的源被判 dead」的荒谬结果
    （实测首轮就是这样，dead 高达 548）。所以：
      * 高优先级探针可覆盖低优先级；
      * 同优先级取更优结论；
      * 低优先级只能记历史，不改结论。
    """
    at = checked_at or now()
    health = classify(level, ok)
    pri = probe_priority(probe)
    conn.execute("""
        INSERT INTO checks (key, checked_at, ok, status_code, latency_ms, level, reason, probe)
        VALUES (?,?,?,?,?,?,?,?)
    """, (key, at,
          None if ok is None else int(bool(ok)),
          status_code, latency_ms, level, (reason or "")[:300], probe))

    row = conn.execute("SELECT health, health_rank FROM interfaces WHERE key=?", (key,)).fetchone()
    if row:
        old_h = row["health"] or "unknown"
        old_rank = row["health_rank"] or 0
        if pri < old_rank:
            return old_h                       # 新证据更浅：只记历史，不改结论
        if pri == old_rank and _HEALTH_ORDER.get(health, 0) <= _HEALTH_ORDER.get(old_h, 0):
            return old_h                       # 同级但不更优：保留原结论

    conn.execute("""
        UPDATE interfaces SET
            last_check_at=?,
            health=?,
            health_rank=MAX(health_rank, ?),
            level=COALESCE(?, level),
            latency_ms=COALESCE(?, latency_ms),
            status_code=COALESCE(?, status_code),
            reason=COALESCE(?, reason),
            fail_streak = CASE WHEN ?='healthy' THEN 0 ELSE fail_streak + 1 END,
            updated_at=?
        WHERE key=?
    """, (at, health, pri, level, latency_ms, status_code,
          (reason or "")[:300] or None, health, now(), key))
    return health


def upsert_dep(conn, key: str, dep_type: str, dep_ref: str,
               local_path=None, md5=None, upstream=None) -> None:
    if not (key and dep_type and dep_ref):
        return
    conn.execute("""
        INSERT INTO deps (key, dep_type, dep_ref, local_path, md5, upstream, updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(key, dep_type, dep_ref) DO UPDATE SET
            local_path=COALESCE(excluded.local_path, deps.local_path),
            md5=COALESCE(excluded.md5, deps.md5),
            upstream=COALESCE(excluded.upstream, deps.upstream),
            updated_at=excluded.updated_at
    """, (key, dep_type, dep_ref, local_path, md5, upstream, now()))


def upsert_upstream(conn, url: str, name=None, kind=None, ok=None,
                    sites_count=None, new_sites=None, note=None) -> None:
    if not url:
        return
    conn.execute("""
        INSERT INTO upstreams (url, name, kind, last_fetch_at, ok, sites_count, new_sites,
                               fail_streak, note)
        VALUES (:url,:name,:kind,:at,:ok,:sc,:ns,
                CASE WHEN :ok=1 THEN 0 ELSE 1 END, :note)
        ON CONFLICT(url) DO UPDATE SET
            name=COALESCE(excluded.name, upstreams.name),
            kind=COALESCE(excluded.kind, upstreams.kind),
            last_fetch_at=excluded.last_fetch_at,
            ok=excluded.ok, sites_count=excluded.sites_count,
            new_sites=COALESCE(excluded.new_sites, upstreams.new_sites),
            fail_streak = CASE WHEN excluded.ok=1 THEN 0 ELSE upstreams.fail_streak + 1 END,
            note=COALESCE(excluded.note, upstreams.note)
    """, {"url": url, "name": name, "kind": kind, "at": now(),
          "ok": None if ok is None else int(bool(ok)),
          "sc": sites_count, "ns": new_sites, "note": (note or "")[:200]})


def start_run(conn, stage: str) -> int:
    cur = conn.execute("INSERT INTO runs (started_at, stage) VALUES (?,?)", (now(), stage))
    conn.commit()
    return cur.lastrowid


def end_run(conn, run_id: int, ok: bool, note: str = "") -> None:
    conn.execute("UPDATE runs SET ended_at=?, ok=?, note=? WHERE id=?",
                 (now(), int(bool(ok)), (note or "")[:300], run_id))
    conn.commit()


# ---------------- 导入 ----------------
def ingest_sites(conn, path: str) -> int:
    """从合并产物导入接口（含依赖关系提取）。幂等。"""
    doc = json.load(open(path, encoding="utf-8"))
    sites = doc.get("sites") or doc.get("video") or []
    n = 0
    for s in sites:
        if not isinstance(s, dict):
            continue
        upsert_interface(conn, s, source=s.get("origin") or s.get("from"))
        key = s.get("key")
        # 依赖关系：jar / ext 本地文件 / 本地 js 规则 / 全局 spider
        if s.get("jar"):
            upsert_dep(conn, key, "jar", s["jar"])
        ext = s.get("ext")
        if isinstance(ext, str) and ext.startswith(("./", "/")):
            upsert_dep(conn, key, "ext_file", ext)
        elif isinstance(ext, dict):
            for k, v in ext.items():
                if isinstance(v, str) and v.startswith(("./", "/")):
                    upsert_dep(conn, key, "ext_file", v)
        api = s.get("api") or ""
        if api.startswith("./") and api.endswith(".js"):
            upsert_dep(conn, key, "local_js", api)
    if doc.get("spider"):
        upsert_dep(conn, "__global__", "spider", doc["spider"])
    conn.commit()
    n = len(sites)
    log(f"导入接口 {n} 个 <- {path}")
    return n


def ingest_probe(conn, path: str) -> int:
    """导入一路探针结果：追加检测历史 + 更新健康状态。幂等（按 key+时间追加）。"""
    doc = json.load(open(path, encoding="utf-8"))
    sites = doc.get("sites") or []
    probe_name = os.path.basename(path)
    # 用产物自带时间作检测时间（而不是导入时刻）：同一份产物重复导入时先清旧记录，
    # 否则检测历史会翻倍（实测重复导入一次就从 2618 涨到 4976），破坏幂等。
    checked_at = str(doc.get("generated_at") or "").replace("T", " ").strip()[:19] or None
    if not checked_at:
        # 有些产物不写 generated_at（如 sites_probe.json）：退用「文件修改时间」。
        # 必须保持可用导入时刻 —— 否则每次导入都是新时间，历史照样翻倍。
        try:
            checked_at = datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")
        except OSError:
            checked_at = None
    if checked_at:
        conn.execute("DELETE FROM checks WHERE probe=? AND checked_at=?", (probe_name, checked_at))
    n = 0
    for r in sites:
        if not isinstance(r, dict) or not r.get("key"):
            continue
        # 不同探针的字段命名不同，统一归一
        ms = r.get("ms")
        if ms is None:
            ms = r.get("cat_ms") or (r.get("l1") or {}).get("ms")
        ok = r.get("ok")
        if ok is None:
            l2 = r.get("l2") or {}
            ok = l2.get("ok") if isinstance(l2, dict) else None
        reason = r.get("err") or r.get("reason") or ""
        if not reason and isinstance(r.get("flags"), dict):
            reason = json.dumps(r["flags"], ensure_ascii=False)[:200]
        record_check(conn, r["key"], ok=ok, latency_ms=ms,
                     level=r.get("level"), reason=reason, probe=probe_name,
                     checked_at=checked_at)
        n += 1
    conn.commit()
    log(f"导入检测记录 {n} 条 <- {probe_name}")
    return n


def ingest_upstreams(conn, path: str) -> int:
    """从 status.json / checks.json 导入上游健康。"""
    doc = json.load(open(path, encoding="utf-8"))
    ups = doc.get("upstreams")
    n = 0
    if isinstance(ups, list):
        for u in ups:
            if not isinstance(u, dict):
                continue
            upsert_upstream(conn, u.get("url"), name=u.get("name"), kind=u.get("kind"),
                            ok=u.get("ok"), sites_count=u.get("sites") or u.get("sites_count"),
                            note=u.get("reason") or u.get("note"))
            n += 1
    elif isinstance(ups, dict):
        for url, u in ups.items():
            u = u if isinstance(u, dict) else {}
            upsert_upstream(conn, url, name=u.get("name"), kind=u.get("kind"),
                            ok=u.get("ok"), sites_count=u.get("sites"),
                            note=u.get("reason") or u.get("note"))
            n += 1
    conn.commit()
    log(f"导入上游 {n} 个 <- {os.path.basename(path)}")
    return n


def ingest_lives(conn, path: str) -> int:
    """直播源入库。

    此前健康体系只覆盖点播 sites，lives（直播）是盲区——导出与日报都看不到它们。
    直播源没有 key 字段，用 url 作主键。
    """
    doc = json.load(open(path, encoding="utf-8"))
    lives = doc.get("lives") or []
    n = 0
    for lv in lives:
        if not isinstance(lv, dict):
            continue
        url = lv.get("url")
        if not url:
            continue
        conn.execute("""
            INSERT INTO lives (key, name, url, type, source, updated_at)
            VALUES (:k,:n,:u,:t,:s,:now)
            ON CONFLICT(key) DO UPDATE SET
                name=excluded.name, type=excluded.type,
                source=COALESCE(excluded.source, lives.source),
                updated_at=excluded.updated_at
        """, {"k": url, "n": lv.get("name"), "u": url, "t": lv.get("type"),
              "s": lv.get("source") or lv.get("from"), "now": now()})
        n += 1
    conn.commit()
    log(f"导入直播源 {n} 条 <- {os.path.basename(path)}")
    return n


def _http_get(url: str, timeout: int = 12):
    """轻量拉取（直播源实测用），raw 直连不通时走镜像兜底。"""
    import urllib.request
    hdr = {"User-Agent": "tvbox-config-live-probe", "Accept": "*/*"}
    try:
        req = urllib.request.Request(url, headers=hdr)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.status, r.read(400_000)
    except Exception as e:
        if "raw.githubusercontent.com" in url:
            try:
                req2 = urllib.request.Request("https://ghproxy.net/" + url, headers=hdr)
                with urllib.request.urlopen(req2, timeout=timeout) as r:
                    return True, r.status, r.read(400_000)
            except Exception as e2:
                return False, None, str(e2)[:100]
        return False, None, str(e)[:100]


def probe_lives(conn, timeout: int = 12, workers: int = 8) -> dict:
    """直播源连通性实测：拉一次源地址，看是否返回可用频道列表。

    直播此前完全没有健康数据（127 条全是 unknown），日报看不到它们的变化。
    判定：有 >=10 个频道 → healthy；1~9 个 → degraded；拉不到 → dead。
    """
    from concurrent.futures import ThreadPoolExecutor
    rows = conn.execute("SELECT key, name, url FROM lives").fetchall()
    if not rows:
        log("lives 表为空，跳过直播实测（先跑 --ingest-lives）")
        return {}
    log(f"直播实测：{len(rows)} 条源，并发 {workers}")

    def one(r):
        url = r["url"] or ""
        t0 = time.time()
        ok, st, raw = _http_get(url, timeout)
        ms = int((time.time() - t0) * 1000)
        if not ok or not raw:
            return r["key"], "dead", ms, 0, (st and f"HTTP {st}") or "拉取失败"
        text = raw.decode("utf-8", "replace")
        n = text.count("#EXTINF")
        if n >= 10:
            health = "healthy"
        elif n >= 1:
            health = "degraded"
        else:
            health = "degraded"       # 通了但没解析出频道，先降级不判死
        return r["key"], health, ms, n, ""

    out = {}
    with ThreadPoolExecutor(workers) as ex:
        for key, health, ms, n, err in ex.map(one, rows):
            out[key] = {"health": health, "ms": ms, "channels": n, "err": err}
            conn.execute("""
                UPDATE lives SET last_check_at=?, health=?, latency_ms=?, updated_at=? WHERE key=?
            """, (now(), health, ms, now(), key))
            # 也记一条历史，便于日报/趋势追踪
            conn.execute("""
                INSERT INTO checks (key, checked_at, ok, latency_ms, reason, probe)
                VALUES (?,?,?,?,?,?)
            """, (key, now(), 1 if health != "dead" else 0, ms,
                  err or f"channels={n}", "live_probe"))
    conn.commit()
    from collections import Counter
    st = Counter(v["health"] for v in out.values())
    log(f"直播实测完成：{dict(st)}")
    return out


def prune_checks(conn, keep_days: int = KEEP_DAYS) -> int:
    """清理过期检测历史，避免库无限膨胀。"""
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat(timespec="seconds")
    cur = conn.execute("DELETE FROM checks WHERE checked_at < ?", (cutoff,))
    conn.commit()
    log(f"清理 {cur.rowcount} 条超过 {keep_days} 天的检测历史")
    return cur.rowcount


def stats(conn) -> dict:
    out = {}
    out["interfaces"] = conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0]
    for row in conn.execute("SELECT health, COUNT(*) c FROM interfaces GROUP BY health"):
        out[f"health:{row['health']}"] = row["c"]
    out["checks"] = conn.execute("SELECT COUNT(*) FROM checks").fetchone()[0]
    out["deps"] = conn.execute("SELECT COUNT(*) FROM deps").fetchone()[0]
    out["upstreams"] = conn.execute("SELECT COUNT(*) FROM upstreams").fetchone()[0]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--ingest-sites", default="")
    ap.add_argument("--ingest-probes", nargs="*", default=[])
    ap.add_argument("--ingest-upstreams", default="")
    ap.add_argument("--ingest-lives", default="")
    ap.add_argument("--probe-lives", action="store_true", help="对 lives 表里的直播源做连通性实测")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    conn = connect(args.db)
    if args.init:
        log(f"初始化完成 -> {args.db}")
    if args.ingest_sites:
        ingest_sites(conn, args.ingest_sites)
    for p in args.ingest_probes:
        if os.path.isfile(p):
            ingest_probe(conn, p)
        else:
            log(f"跳过（不存在）: {p}")
    if args.ingest_upstreams and os.path.isfile(args.ingest_upstreams):
        ingest_upstream(conn, args.ingest_upstreams)
    if args.ingest_lives and os.path.isfile(args.ingest_lives):
        ingest_lives(conn, args.ingest_lives)
    if args.probe_lives:
        probe_lives(conn)
    if args.prune:
        prune_checks(conn)
    if args.stats or not any([args.ingest_sites, args.ingest_probes,
                              args.ingest_upstreams, args.prune, args.init]):
        for k, v in stats(conn).items():
            print(f"  {k:16} {v}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
