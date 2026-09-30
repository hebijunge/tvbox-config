#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox 配置每日拉取合并脚本 v2（stdlib only，无第三方依赖）

流程：拉取上游清单（一上游一适配器）→ 内容质量门槛（最小字节/行数 + sha256 指纹）
      → 连续不过自动停用（黑白名单三层）+ 停用上游低频探活回捞
      → 合并去重（按 key 冲突时健康度仲裁 + api/ext 指纹二级去重 + 同内容镜像短路）
      → 测速验活（type 0/1 直连站点）→ 连续 N 轮失败才剔除（站点验活历史记忆，通过自动回捞）
      → 直播源分类测速优选（央视/卫视/港台分组 txt，测速全挂频道保底收录）
      → 快照存档（snapshot/<日期>/）→ 输出 tvbox.json / list.json / status.json / checks.json
      → README 可用性锚点回写

对应第二期调研路线图：
  P0 上游验活门槛（joevess 教训 + Guovin 机制）
  P0 直播源上游收编（Guovin/iptv-api gd 分支 + Releases 双通道）
  P1 每日快照存档（kimwang1978/collect-txt 模式）
  P1 黑白名单分文件（kimwang + Guovin 模式）
  P1 分类测速优选（Supprise0901/TVBox_live 模式）
  P1 checks.json 校验产物 + 内容指纹 + 通过时间（azhansy/ds-tvbox 模式）
  P2 一上游一适配器（HerbertHe/iptv-sources 模式）
  P2 域名替换层（hl128k/tvbox 思路）
"""
import sys

if sys.version_info < (3, 10):
    sys.exit("[fetch_merge] 需要 Python 3.10+（当前 %s）：模块使用了 `str | None` 等"
             " 3.10+ 语法，旧解释器会在 import 期直接崩溃" % sys.version.split()[0])
try:  # Windows cp936 控制台下站点名含 emoji 会 UnicodeEncodeError 崩掉打印
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import concurrent.futures as cf
import http.client
import threading
from datetime import datetime, timezone, timedelta
import socket
socket.setdefaulttimeout(30)  # 全局socket超时兜底：Windows下urllib connect超时对SYN无响应可能不生效，强制30s兜底

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts 内互相导入
from config_decode import decode_config   # 吸收点 P1-1：混淆配置解码链（独立实现）
import adult_leak_check as _adult_gate    # 门禁扫描语义单一事实源（P0-2 红线对齐）
import live_aggregate as _la              # 词表驱动 adult 判定（is_adult / is_adult_url）
import raw_store                          # 输入层原始源镜像（落库/每日变化检测/上游删除保护）
import pathutil                           # 跨平台路径安全工具（全仓库唯一事实源）
import upstream_config as _ucfg           # 统一上游配置（config/upstreams.json，硬编码作 fallback）
import upstream_changelog as _uclog       # 上游配置变更追踪（归一化 sha256，state/upstream_changelog.jsonl）

BEIJING = timezone(timedelta(hours=8))
UA = {"User-Agent": "okhttp/3.15", "Accept": "*/*"}
FETCH_TIMEOUT = 15          # 单次拉取超时（秒，旧合并超时，保留兼容）
# 任务2：connect/read 拆分硬超时（env 可覆盖）。连接 10s 快速判死，读 30s 容忍慢大文件。
FETCH_CONNECT_TIMEOUT = int(os.environ.get("FETCH_CONNECT_TIMEOUT", "10"))
FETCH_READ_TIMEOUT = int(os.environ.get("FETCH_READ_TIMEOUT", "30"))

# 吸收点 P1-3：上游拉取 UA 池（设计借鉴自参考仓库调研，代码独立实现）。
# 拉取失败时轮换 UA + 指纹头重试，覆盖部分上游对单一 okhttp UA 的选择性拦截。
UA_POOL_VOD = [
    {"User-Agent": "okhttp/3.15", "X-Requested-With": "com.iptvbox.tvbox"},
    {"User-Agent": "okhttp/4.9.3", "X-Requested-With": "com.iptvbox.tvbox"},
    {"User-Agent": "TVBox/1.0.0", "X-Requested-With": "com.github.tvbox.osc"},
    {"User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; Pixel 3 XL Build/SQ1A.220205.002)", "X-Requested-With": "com.iptvbox.tvbox"},
    {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36", "X-Requested-With": ""},
    {"User-Agent": "okhttp/3.12.0", "X-Requested-With": "com.box.tvbox"},
]
UA_ROTATE_MAX = int(os.environ.get("UA_ROTATE_MAX", "3"))   # 单 URL 的 UA 轮换上限（含首次）

TEST_TIMEOUT = 6            # 站点验活单次超时（秒）
# V4：验活并发 20→48（配合 _domain_semaphore 同域信号量，避免被目标站 WAF 封）
CONCURRENCY = int(os.environ.get("CONCURRENCY", "48"))
MAX_BODY = 4096             # 验活最多读取字节数
# O7 ghproxy 单点依赖缓解：拉取侧按镜像列表依次轮换；产出配置改写固定用主镜像（静态 JSON 无法做客户端容灾）
# 镜像排序依据（2026-09-19 实测本项目文件）：gh-proxy.com TTFB 657ms/1551KB/s 双优；
# gh.zwy.one 624KB/s（用户侧 Release 实测 7119KB/s）；ghproxy.cxkpro.top 434KB/s（用户侧 5292KB/s）；
# v6.gh-proxy.org 260KB/s；ghproxy.net 47KB/s（慢管但稳定）；ghfast.top/gh.llkk.cc/rwa.ihtw.moe/ghp.ci
# 沙箱侧限流/502 不可作首选，留作轮换兜底（GitHub runner 与用户侧网络画像不同，可能表现更好）。
# batch18 调研补充（2026-09-24 深夜 / 09-25 00:15–00:30 复核）：gh-proxy.com 对 Guovin 路径在深夜时段 404、
# 复核时段 200 且与 raw 直连字节级一致——该镜像「间歇不稳定」，拉取侧轮换已兜住。
# 输出侧主镜像（GHPROXY）自 2026-09-29 起不再跟「当日第一名」，改用近 3 轮中位吞吐择优，
# 见 _stable_ghproxy。jsdelivr 主域在沙箱网关 400，
# 引用 jsdelivr 应显式用 fastly.jsdelivr.net 子域（extra_upstreams jyoketsu 条目已按此规范化）。
# 2026-09-29 大文件口径复测（8MB jar，每站读满 4MB 或 12s 时限，速度只算首包之后的传输段）：
# gh.halonice.com 3019KB/s、30006000.xyz 2820、githubproxy.cc 2364、proxy.vvvv.ee 2001、
# gh.padao.fun 1904；gh-proxy.com 144KB/s（12s 只拉到 1.8MB）；gh.acmsz.top 74KB/s 判慢淘汰
# （同日两轮另测 205KB/s、347KB/s，均在末位区间）—— 09-29 早间「acmsz 最快」的结论是
# 1.86MB 小文件口径的失真，已从静态首位撤下，仍留在 mirror_probe 候选池里按每日实测排位。
# 同时删除 ghp.ci / gh.llkk.cc / raw.ihtw.moe：两份实测报告均列其为失效/限流，且不在
# mirror_probe 候选池，留在轮换列表只会让死站各吃一次超时。
MIRROR_RANKING_FILE = os.environ.get("MIRROR_RANKING_FILE", "state/mirror_ranking.json")
MIRROR_RANKING_MAX_AGE_DAYS = int(os.environ.get("MIRROR_RANKING_MAX_AGE_DAYS", "3"))

GH_MIRRORS_DEFAULT = (
    "https://gh.halonice.com/,https://30006000.xyz/,https://githubproxy.cc/,"
    "https://proxy.vvvv.ee/,https://gh.padao.fun/,https://github.cnxiaobai.com/,"
    "https://fastgit.cc/,https://gh.zwy.one/,https://ghproxy.cxkpro.top/,"
    "https://v6.gh-proxy.org/,https://gh-proxy.com/,https://ghproxy.net/,"
    "https://gh.acmsz.top/"
)


def _load_mirror_rounds(path=None):
    """读 mirror_probe 落盘的实测历史（最新一轮在前）。缺失/损坏/过期返回 []。"""
    from datetime import datetime, timedelta, timezone
    try:
        with open(path or MIRROR_RANKING_FILE, encoding="utf-8") as f:
            rounds = (json.load(f) or {}).get("rounds") or []
    except (OSError, ValueError):
        return []
    if not rounds:
        return []
    gen = str(rounds[0].get("generated_at") or "")
    try:
        when = datetime.strptime(gen, "%Y-%m-%d %H:%M:%S UTC").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return []
    if datetime.now(timezone.utc) - when > timedelta(days=MIRROR_RANKING_MAX_AGE_DAYS):
        return []
    return rounds


def _mirrors_from_rounds(rounds):
    if not rounds:
        return []
    out = []
    for row in rounds[0].get("ranking") or []:
        p = str(row.get("prefix") or "").strip()
        if p:
            out.append(p if p.endswith("/") else p + "/")
    return out


def _stable_ghproxy(rounds, fallback):
    """外链改写用的主镜像：取近 3 轮里至少 2 轮上榜、中位吞吐最高的那个。

    不用「当日第一名」：并发共享带宽 + 镜像冷热缓存会让单样本周间排名乱跳
    （2026-09-29 实测同一镜像两轮 2822KB/s ↔ 375KB/s，名次第 2 ↔ 第 23），
    而这个前缀要写进静态 JSON 发给所有用户，稳比快优先。"""
    if not rounds:
        return fallback
    hits = {}
    for idx, rd in enumerate(rounds[:3]):
        for pos, row in enumerate(rd.get("ranking") or []):
            p = str(row.get("prefix") or "").strip()
            if p:
                hits.setdefault(p, []).append((idx, pos, int(row.get("KBps") or 0)))
    best, best_key = None, None
    for p, recs in hits.items():
        if len({i for i, _pos, _k in recs}) < 2:
            continue  # 只在一轮出现过，可能是瞬时侥幸
        vals = sorted(k for _i, _pos, k in recs)
        median = vals[len(vals) // 2] if len(vals) % 2 else (
            vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) // 2
        key = (median, -min(pos for _i, pos, _k in recs), -min(i for i, _p, _k in recs))
        if best_key is None or key > best_key:
            best, best_key = p, key
    chosen = best or fallback
    return chosen if chosen.endswith("/") else chosen + "/"


_MIRROR_ROUNDS = _load_mirror_rounds()
GH_MIRRORS = [m.strip() for m in os.environ.get("GH_MIRRORS", "").split(",") if m.strip()]
_MIRRORS_PINNED = bool(GH_MIRRORS)  # 人工/CI 显式指定列表时，不再自作主张换主镜像
if not GH_MIRRORS:
    # 没有 CI 注入（本地/手动跑）时，用当日实测顺序，而不是拍脑袋的静态默认
    GH_MIRRORS = _mirrors_from_rounds(_MIRROR_ROUNDS) or [
        m.strip() for m in GH_MIRRORS_DEFAULT.split(",") if m.strip()]
GHPROXY = (GH_MIRRORS[0] if GH_MIRRORS else "") if _MIRRORS_PINNED else \
    _stable_ghproxy(_MIRROR_ROUNDS, GH_MIRRORS[0] if GH_MIRRORS else "")

REPO_RAW = "https://raw.githubusercontent.com/hebijunge/tvbox-config/main"

# ---- P0：内容质量门槛参数 ----
MIN_BYTES_TVBOX = int(os.environ.get("MIN_BYTES_TVBOX", "512"))    # 配置类上游最小字节数
MIN_ITEMS_TVBOX = int(os.environ.get("MIN_ITEMS_TVBOX", "1"))      # 至少含多少条 sites/lives/parses
CANARY_MIN_BYTES = int(os.environ.get("CANARY_MIN_BYTES", "5120"))  # canary 上游内容校验最小字节（batch11 P1-1：HEAD 200 + 5KB 内容校验）
MIN_BYTES_M3U = int(os.environ.get("MIN_BYTES_M3U", "1024"))       # m3u 类上游最小字节数
MIN_ENTRIES_M3U = int(os.environ.get("MIN_ENTRIES_M3U", "50"))     # m3u 至少多少条频道

# ---- P0/P1：连续失败自动停用（黑白名单）----
# P1-A 双线职责收敛：验证状态唯一事实源 = state/validated.json（含 sources/sites 两段），
# state/upstreams_state.json / state/sites_state.json 不再读写（见 scripts/validated_state.py）。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validated_state as _vs  # noqa: E402

STATE_FILE = os.environ.get("STATE_FILE", "state/validated.json")  # 兼容引用；实际读写走 _vs
BLACKLIST_AUTO = os.environ.get("BLACKLIST_AUTO", "state/blacklist_auto.txt")
BLACKLIST_MANUAL = os.environ.get("BLACKLIST_MANUAL", "state/blacklist_manual.txt")
WHITELIST_MANUAL = os.environ.get("WHITELIST_MANUAL", "state/whitelist_manual.txt")
FAIL_LIMIT = int(os.environ.get("UPSTREAM_FAIL_LIMIT", "3"))       # 连续 N 次不达标自动停用
# 2026-09-21 点播+容错线：黑名单单轮安全阀（来自 riowang88 设计文档）。
# 单轮「本次停用」数超过上游总数 30% 时，判定为网络抖动等系统性误判而非
# 上游集体长期失效：只警告、不落盘（本轮停用全部回滚，fail_count 保留，
# 真失效的源下一轮仍会正常触发停用），防止一次抖动误杀大量源。
# 与连续 3 次失败自动停用互补：黑名单管长期失效，安全阀管单轮抖动。
BLACKLIST_ROUND_CAP_RATIO = float(os.environ.get("BLACKLIST_ROUND_CAP_RATIO", "0.30"))
# 2026-09-21 点播+容错线：空产物守卫（借鉴 tengxiaobao「聚合失败保留上次缓存」）。
# 本轮 sites/lives/parses 任一为空、或较上一版已提交产物萎缩超 80% 时，
# 判定本轮聚合结果异常：跳过全部产物写入与提交/发布（exit 2），保留上次
# 缓存，写 state/guard_last.json 日报下轮重试。与安全阀互补：安全阀管
# 「单轮停用抖动」，守卫管「合并产物塌方」。
EMPTY_GUARD_DROP_RATIO = float(os.environ.get("EMPTY_GUARD_DROP_RATIO", "0.80"))
PROBE_INTERVAL_DAYS = int(os.environ.get("DISABLED_PROBE_DAYS", "7"))  # O2 停用上游每隔 N 天探活回捞

# O3 站点验活历史记忆（连续 N 轮失败才剔除，通过自动回捞）
SITE_STATE_FILE = os.environ.get("SITE_STATE_FILE", "state/sites_state.json")
SITE_FAIL_LIMIT = int(os.environ.get("SITE_FAIL_LIMIT", "3"))
# 短剧/成人分类人工覆盖表：{"<site key>": "short|adult|vod"}，优先级高于关键词分类
CATEGORY_OVERRIDE_FILE = os.environ.get("CATEGORY_OVERRIDE_FILE", "state/category_overrides.json")

# ---- P1：快照存档 ----
SNAPSHOT_DIR = os.environ.get("SNAPSHOT_DIR", "snapshot")
SNAPSHOT_RETENTION_DAYS = int(os.environ.get("SNAPSHOT_RETENTION_DAYS", "14"))

# ---- P1：直播分类测速优选 ----
LIVE_SPEEDTEST = os.environ.get("LIVE_SPEEDTEST", "1") == "1"
LIVE_TIMEOUT = int(os.environ.get("LIVE_TIMEOUT", "4"))
LIVE_CONCURRENCY = int(os.environ.get("LIVE_CONCURRENCY", "24"))
LIVE_MAX_URLS = int(os.environ.get("LIVE_MAX_URLS", "1200"))       # 单轮测速 URL 总量上限
LIVE_PER_CHANNEL = int(os.environ.get("LIVE_PER_CHANNEL", "3"))    # 每频道保留条数
LIVE_FALLBACK_CHANNELS = int(os.environ.get("LIVE_FALLBACK_CHANNELS", "100"))  # O6 测速全挂频道的保底收录上限
LIVE_MIN_SPEED = float(os.environ.get("LIVE_MIN_SPEED", "0.2"))    # MB/s；低于此速率降权排序（只降权不删除）
LIVE_SPEED_RANGE = int(os.environ.get("LIVE_SPEED_RANGE", str(1 << 20)))  # 测速抽样字节数（HTTP Range 抽 1MB 实测吞吐）
LIVES_DIR = os.environ.get("LIVES_DIR", "lives")
CHECKS_FILE = os.environ.get("CHECKS_FILE", "checks.json")
DOMAIN_MAP_FILE = os.environ.get("DOMAIN_MAP_FILE", "state/domain_map.json")
README_FILE = os.environ.get("README_FILE", "README.md")

# 上游清单（点播配置类）：顺序仍影响收录次序，但同名 key 冲突时按来源健康分仲裁（O1）——
# 最近成功时间新、连续失败少的上游接管；健康分相同保持先到先得（不误伤已有源、避免抖动）
# 一上游一适配器：kind 决定拉取后如何解析（tvbox=json 配置 / m3u=直播列表）
UPSTREAMS = [
    # 2026-09-25 双线融合：飞书巡检线（Aily 定时任务）每日复测+排重后的统一配置，
    # 固定名每日覆盖推送至本仓库 sync/feishu_config_latest.json，作为常规上游参与合并。
    {"name": "feishu-sync", "kind": "tvbox",
     "url": "https://raw.githubusercontent.com/hebijunge/tvbox-config/main/sync/feishu_config_latest.json"},
    {"name": "juhe-tvapi", "kind": "tvbox",
     "url": "https://raw.githubusercontent.com/ccAzy/juhe-tvapi/main/config.json"},
    {"name": "qist/jsm", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/jsm.json"},
    {"name": "qist/js", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/js.json"},
    {"name": "qist/dianshi", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/dianshi.json"},
    {"name": "qist/fty", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/fty.json"},
    {"name": "qist/XYQ", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/XYQ.json"},
    {"name": "qist/0821", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0821.json"},
    {"name": "qist/0825", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0825.json"},
    {"name": "qist/0826", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0826.json"},
    {"name": "qist/0827", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0827.json"},
    {"name": "qist/367", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/367.json"},
    {"name": "qist/9918", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/9918.json"},
    {"name": "qist/99188", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/99188.json"},
    {"name": "gao/js", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/js.json"},
    {"name": "gao/XYQ", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/XYQ.json"},
    {"name": "gao/0821", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0821.json"},
    {"name": "gao/0825", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0825.json"},
    {"name": "gao/0826", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0826.json"},
    {"name": "gao/0827", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0827.json"},
    {"name": "cluntop/jsm", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/jsm.json"},
    {"name": "cluntop/box", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/box.json"},
    {"name": "cluntop/fun", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/fun.json"},
    {"name": "cluntop/aa", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/aa.json"},
    {"name": "cluntop/bb", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/bb.json"},
    {"name": "cluntop/wv", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/wv.json"},
    {"name": "cluntop/yt", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/yt.json"},
    {"name": "cluntop/test", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/test.json"},
    {"name": "nxppru/jsm", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/jsm.json"},
    {"name": "nxppru/js", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/js.json"},
    {"name": "nxppru/dianshi", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/dianshi.json"},
    {"name": "nxppru/fty", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/fty.json"},
    {"name": "nxppru/XYQ", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/XYQ.json"},
    {"name": "nxppru/0821", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0821.json"},
    {"name": "nxppru/0825", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0825.json"},
    {"name": "nxppru/0826", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0826.json"},
    {"name": "nxppru/0827", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0827.json"},
    {"name": "top98", "kind": "tvbox", "url": "http://home.jundie.top:81/top98.json"},
    # ---- 2026-09-19 接K20260729 清单验活后新增（实测报告：飞书云文档 WinbdkIMEoGWfNxVTrVcqtpGnxs）----
    # 王二小 kstore：96 sites（spider 2026-09-17 版），直连 152ms；容灾备选 http://tv.999888987.xyz/（63 sites 旧版）暂不收
    {"name": "wex/newwex", "kind": "tvbox", "url": "https://9280.kstore.vip/newwex.json",
     "mirrors": ["http://new.xn--4kq62z5rby2qupq9ub.top"]},
    # PG：74 sites / 29 lives；spider 为相对路径 ./pg.jar，依赖同源 jar（依赖收集失败时走自动黑名单）
    {"name": "pg/jsm", "kind": "tvbox", "url": "https://www.252035.xyz/p/jsm.json"},
    # 肥猫：39 sites；必须用 /tv 路径（根路径 / 为损坏配置）；IDN 域名已转 punycode 供 urllib 直连
    {"name": "fatcat/tv", "kind": "tvbox", "url": "http://xn--z7x900a.net/tv"},
    # 老刘备：234 sites（容错解析通过）；ghproxy.net 为单点依赖，失效时会被自动停用
    {"name": "liu673cn/m", "kind": "tvbox", "url": "https://ghproxy.net/https://raw.githubusercontent.com/liu673cn/box/main/m.json",
     "mirrors": ["https://raw.githubusercontent.com/liu673cn/box/main/m.json"]},  # 吸收点 P1-2：消除 ghproxy.net 单点
    # ---- 2026-09-20 DeepSeek 报告实测收录（仅纯 JSON 可合并源；图片伪装/加密/多仓类进订阅清单不进此处，避免被判 dead 进黑名单）----
    {"name": "deepseek/8815wmz", "kind": "tvbox", "url": "https://8815.kstore.vip/tvbox/wmz"},          # 105 sites
    {"name": "deepseek/gaoops404", "kind": "tvbox", "url": "https://raw.giteeusercontent.com/gaoops404/tvbox-config/raw/main/tvbox.json"},  # 52 sites
    {"name": "deepseek/gao777520", "kind": "tvbox", "url": "https://gitlab.com/gao777520/tvbox-config/raw/main/tvbox.json"},  # 52 sites
    # ---- 2026-09-21 点播+容错线：六批调研新增上游（jsDelivr 实拉 + parse_tvbox 等效验证后纳入）----
    # tushen6/Tomorrow（2278★，2026-09-21 当日有推送）：根目录 tvbox.json 33 sites / 1 lives / 9 parses
    {"name": "tushen6/tvbox", "kind": "tvbox", "url": "https://raw.githubusercontent.com/tushen6/Tomorrow/master/tvbox.json"},
    # victor1616888/TVBOX-Q（2026-09-21 当日有推送）：根目录 tvbox.json 116 sites / 12 lives / 9 parses（含 // 行内注释，经状态机清洗可解析）
    {"name": "victor/tvbox", "kind": "tvbox", "url": "https://raw.githubusercontent.com/victor1616888/TVBOX-Q/master/tvbox.json"},
    # franksun1211/TVBOX（228★，2026-09-12 推送）：CKS2026.json 60 sites / 2 lives / 4 parses（内含 /* */ 块注释，经状态机清洗可解析）；
    # XCTV.json（APP/TVBoxOSC/XC/，教育向直播源）转直播线任务处理；qiaoji8.json 等其余 19 个配置已登记 candidate_upstreams.json 候选池走 canary 收编
    {"name": "franksun/cks2026", "kind": "tvbox", "url": "https://raw.githubusercontent.com/franksun1211/TVBOX/main/CKS2026.json"},
    # ---- 2026-09-25 吸收（batch18 调研 P1）：动漫城 yingm.cc 专项动漫配置 ----
    # 27 站（全 type=3，drpy2/js 双栈）+ 20 parses（27 接口中解析最多的一份）；spider jar 挂 jihulab。
    # 调研按站点名对账 19/27 已覆盖；按 merge key 实测净新增 csp_Ying（樱花动漫）1 站 + 15 条 parses
    #（Demo 占位 parse 由管线自动过滤）。相对路径 ./js/... 由 UPSTREAM_BASES/deps 改写机制落仓。
    {"name": "yingm/dm", "kind": "tvbox", "url": "https://www.yingm.cc/dm/dm.json"},  # 2026-09-25 实测 200/8737B/0.42s
    # ---- 2026-09-22 吸收 lubin776/tvbox-api-backup list.txt：45 条接口与既有清单全量对比去重后新增 20 条 ----
    # 对比基线：UPSTREAMS + LIVE_UPSTREAMS + SHORTS_ADULT + canary(state/extra_upstreams.json) + candidate_upstreams.json。
    # 重复不加：肥猫(fatcat/tv)、挺好、小马、心魔、俊宇(top98)、clun、动漫（既有 UPSTREAMS 或 canary 已收）；
    #   王二小/王二小2线（aiwex.json 与既有 wex/newwex 字节级一致）。
    # 同内容变体不重复收：饭太硬 2~6 线（与主线 19683B 字节一致）、嗷呜 /tv 与 config.webp（与 aowu.json 同内容 78 sites）。
    # 不可用不硬塞（验活证据同期归档）：潇洒(APP清单非配置)、南风两线(AES 布局 decode 链解不开)、
    #   嗨哥魔改(## 注释行主管线不识别)、时光(字符串含裸控制符 json.loads 拒收)、传说/分享者(返回 HTML)、
    #   驸马(404)、小米(占位文本「后会有期」)。
    # 中文路径/IDN 一律 percent-encode/punycode 供 urllib 直连；伪装扩展名（.png 等）内容已实测可被 decode 链解析。
    {"name": "bocai/x4pro", "kind": "tvbox", "url": "https://0.12yue.de5.net/5/x4pro.json"},  # 菠菜pro：206 sites
    {"name": "bocai/x4", "kind": "tvbox", "url": "https://0.12yue.de5.net/5/x4.json"},        # 菠菜园：55 sites
    {"name": "bocai/update", "kind": "tvbox",
     "url": "https://0.12yue.de5.net/tvbox/%E6%9B%B4%E6%96%B0%E4%B8%93%E7%94%A8%E6%8E%A5%E5%8F%A3.json"},  # 更新专用接口：11 sites
    {"name": "xingfu/bbm", "kind": "tvbox", "url": "http://150.158.52.248/tgyg/bbm.json"},    # 幸福年年：127 sites / 9 lives
    # 饭太硬主线：JPEG 伪装壳，decode 链 shell_base64 解出；47 sites / 6 lives（2~6 线同内容字节一致未收）
    # 第七批（2026-09-22）：4 个同源镜像（sha256 与主 URL 逐字节一致）并入 mirrors
    {"name": "fantaiying/tv", "kind": "tvbox", "url": "http://www.xn--sss604efuw.net/tv",
     "mirrors": ["http://www.xn--sss604efuw.cc/tv", "http://fty.xxooo.cf/tv",
                 "http://fty.888484.xyz/tv", "http://fty.333232.xyz/tv"]},
    # 嗷呜：三线同内容（aowu.json / 嗷呜.tv 伪装 / config.webp 壳），收无解码依赖的纯 JSON 线；78 sites / 7 lives
    {"name": "aowu/kstore", "kind": "tvbox", "url": "https://9763.kstore.vip/aowu.json"},
    # 少儿频道：25 sites（纯 JSON 无直播）
    {"name": "shaoer/tv", "kind": "tvbox",
     "url": "https://0.12yue.de5.net/5/tv%E5%B0%91%E5%84%BF.json"},
    {"name": "feimao2/catvod", "kind": "tvbox", "url": "https://jk.catvod.site"},              # 肥猫2线：22 sites（与 fatcat/tv 不同内容）
    {"name": "laozhang/serv00", "kind": "tvbox", "url": "https://zhangqun1818.serv00.net/zq/api.json"},  # 老张：19 sites
    # 周J：27 sites / 4 lives；沙箱直连 raw 超时，主 URL 走 gh-proxy.com（同 liu673cn/m 口径，直连留作镜像）
    {"name": "zhouj/box", "kind": "tvbox",
     "url": "https://gh-proxy.com/raw.githubusercontent.com/zhoujck/config/main/box",
     "mirrors": ["https://raw.githubusercontent.com/zhoujck/config/main/box"]},
    {"name": "cainisi/tv", "kind": "tvbox", "url": "https://tv.xn--yhqu5zs87a.top"},           # 菜妮丝：55 sites
    {"name": "xiaxia/qk4k", "kind": "tvbox", "url": "https://11405.kstore.space/xiaye/qk4k.json"},  # 夏夏影视：43 sites
    {"name": "xiaokai/kai", "kind": "tvbox", "url": "https://jihulab.com/jyqhkd/kd/-/raw/main/kai.json"},  # 小凯：28 sites
    {"name": "dongli/chigua", "kind": "tvbox", "url": "https://chigua.eu.org"},                # 东篱：93 sites / 12 lives（壳 base64 解码）
    {"name": "juwan/xhz", "kind": "tvbox", "url": "http://xhztv.top/xhz"},                     # 聚玩：54 sites
    # 哈吉米：伪装 .png 扩展名实为纯 JSON；175 sites / 11 lives（URL 已 percent-encode）
    {"name": "hajimi/kstore", "kind": "tvbox",
     "url": "https://17264.kstore.space/%E5%93%88%E5%9F%BA%E7%B1%B3.png"},
    {"name": "zhenliu/cccimg", "kind": "tvbox",
     "url": "https://cccimg.com/down.php/7d1f30263b3f2bf3deda2d7faeef4844.zhen6"},            # 真六：47 sites / 9 lives
    # 小虎斑：2423 AES-128-CBC 加密配置，decode 链 aes2423 解出；64 sites / 1 lives（IDN+中文路径已转码）
    {"name": "xiaohuban/hb", "kind": "tvbox",
     "url": "http://hb.xn--yet24tmq1a.site:25252/%E4%BB%85%E4%BE%9B%E6%B5%8B%E8%AF%95"},
    # 天神：PNG 伪装 + 壳 + AES 双层解码链；102 sites；主 URL 走 raw 直连（实测可达），gh-proxy 留作镜像
    {"name": "tianshen/iy", "kind": "tvbox",
     "url": "https://raw.githubusercontent.com/IY-CPU/IY/main/%E5%A4%A9%E7%A5%9EIY.png",
     "mirrors": ["https://gh-proxy.com/raw.githubusercontent.com/IY-CPU/IY/main/%E5%A4%A9%E7%A5%9EIY.png"]},
    # 星微Vip：伪装路径「测试勿传」实为纯 JSON；60 sites / 3 lives（URL 已 percent-encode）
    {"name": "xingwei/kstore", "kind": "tvbox",
     "url": "https://7337.kstore.vip/xw/%E6%B5%8B%E8%AF%95%E5%8B%BF%E4%BC%A0"},
    # ---- 第七批 P1 点播大源入口收编（2026-09-22，task 7688297741897698251）----
    # 来源：Lightconer/tvbox-ysc-config config/sources.json（34 条）+ Supprise0901/tvbox_live warehouse.txt（66 条）。
    # 全量 100 条经三层归一去重 + 逐条验证：21 条新收（下）、5 条并入既有 mirrors、12 条与既有
    # UPSTREAMS/canary URL 重复、10 条内容同源不重收、51 条不可用（502/404/SSL/格式坏）不硬塞。
    # 验证口径：fetch 成功 + decode_config + parse_tvbox 过 MIN_BYTES/MIN_ITEMS 门槛；中文域名转 punycode、
    # 中文路径 percent-encode（生产 fetch_merge 同口径）；裸 IP 条目为单点源，失效由自动黑名单兜底。
    # 王二小放牛娃 tvbox 面：63 sites / 2 lives（另一面 new.王二小放牛娃.top 与 wex/newwex 同内容，已并入其 mirrors）
    {"name": "ysc/wangxiaoer-tvbox", "kind": "tvbox", "url": "http://tvbox.xn--4kq62z5rby2qupq9ub.top"},
    # ---- Supprise0901/api 仓单（gh-proxy 前缀 blob 链接实测可直出 JSON，保持已验证形态）----
    # 天天&巧计：31 sites / 1 live / 5 parses
    {"name": "sv/tiantian-qiaoji", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/tiantian.json"},
    # api 总仓：90 sites / 8 lives / 15 parses
    {"name": "sv/api", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/api.json"},
    # 肥猫 blob 面：50 sites；fatcat/tv 主源本轮三次 502 无法做内容比对，归属待复验（自动黑名单兜底）
    {"name": "sv/feimao", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/feimao.json"},
    # 王二小 blob 面：78 sites / 2 lives
    {"name": "sv/wangxiaoer", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/wangxiaoer.json"},
    # 小布点：74 sites
    {"name": "sv/xiaobudian", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/xiaobudian.json"},
    # 摸鱼直连 canary（batch18 调研 P2，2026-09-25）：y456y.com 与小不点配置字节级同源（sha 97b4afc95aec…），
    # 内容已随 sv/xiaobudian 进聚合；本条只监控不合并——Supprise0901 GitHub 镜像失联时可按当日实测把直连源转正。
    {"name": "canary/moyu-direct", "kind": "tvbox", "canary": True,
     "url": "http://www.y456y.com"},  # 2026-09-24 调研实测 200/37183B
    # 小米：32 sites / 1 live
    {"name": "sv/xiaomi", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/xiaomi.json"},
    # 小傻：134 sites / 1 live / 9 parses（本批最大面之一）
    {"name": "sv/xiaosa", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/xiaosa.json"},
    # 龙在此(关注TG@stymei1)：234 sites / 3 lives / 27 parses，单接口站点数之最
    {"name": "sv/liucn-m", "kind": "tvbox", "url": "https://raw.liucn.cc/box/m.json"},
    # 科技长青：72 sites（kstore 直连）
    {"name": "sv/changqing", "kind": "tvbox", "url": "https://13413.kstore.space/tv/changqing.json"},
    # 东曦视界：82 sites / 1 live / 10 parses
    {"name": "sv/iqinu", "kind": "tvbox", "url": "https://box.iqinu.com/"},
    # 分享者：168 sites / 9 lives / 25 parses（maoystv/6）
    {"name": "sv/fenxiangzhe", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://raw.githubusercontent.com/maoystv/6/main/001.json"},
    # 乐哥短剧：41 sites / 1 live / 15 parses（短剧专面，lege0001/TVbox）
    {"name": "sv/lege-dj", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://raw.githubusercontent.com/lege0001/TVbox/refs/heads/main/TV/dj.json"},
    # 真心(FongMi-z)：43 sites（www.252035.xyz 与 pg/jsm 同主机不同路径）
    {"name": "sv/fongmi-z", "kind": "tvbox", "url": "https://www.252035.xyz/z/FongMi.json"},
    # 小哥哥：86 sites / 1 live；裸 IP:3 单点源，失效走自动黑名单
    {"name": "sv/xiaogege", "kind": "tvbox", "url": "http://47.96.82.41:3/"},
    # 全影多仓(影视仓.com)：43 sites / 3 lives（IDN 已转 punycode）
    {"name": "sv/quanying", "kind": "tvbox", "url": "http://xn--5mqx81b535a.com/"},
    # ---- play.iptv365.org 系列（路径含中文，已 percent-encode；round3 复测全过）----
    # 天微：97 sites
    {"name": "sv/tianwei", "kind": "tvbox",
     "url": "https://play.iptv365.org/%E5%A4%A9%E5%BE%AE/api.json"},
    # 天天开心：126 sites（本批站点数次高）
    {"name": "sv/tiantiankaixin", "kind": "tvbox",
     "url": "https://play.iptv365.org/%E5%A4%A9%E5%A4%A9%E5%BC%80%E5%BF%83/api.json"},
    # 香雅情：55 sites
    {"name": "sv/xiangyaqing", "kind": "tvbox",
     "url": "https://play.iptv365.org/%E9%A6%99%E9%9B%85%E6%83%85/api.json"},
    # 白嫖：9 sites
    {"name": "sv/baipiao", "kind": "tvbox",
     "url": "https://play.iptv365.org/%E7%99%BD%E5%AB%96/api.json"},
    # 戏曲音乐：10 sites
    {"name": "sv/xiquyinyue", "kind": "tvbox",
     "url": "https://play.iptv365.org/%E6%88%8F%E6%9B%B2%E9%9F%B3%E4%B9%90/api.json"},
    # ---- 2026-09-26 吸收 zoo.ink TVBox 接口研究报告 P0 四源（task 7689782040580885721）----
    # 报告 P0 ②ok线路1=11号托管源 与 ④神秘大佬 qist/jsm 经对账已在清单（sv/liucn-m、qist/jsm），不重复收。
    # 本批实收 2 条，去重对账基线 2026-09-26 main（tvbox.json 3580 sites / 394 lives / 124 parses）：
    # 拾光（xmbjm/svip）：246 sites / 20 直播组（外链 m3u/txt）/ 26 parses；merge-key 对账净新增 128 站 / 12 直播组 / 16 解析。
    # 源文件带 UTF-8 BOM + 字符串内裸 CR LF，parse_tvbox 已加 strict=False 兜底（见适配器注释）。
    # 主 URL gh-proxy.com 全前缀形态实测 200/108349B；两种代理形态与 raw 直连同 sha256，直连留作镜像。
    {"name": "shiguang/svip", "kind": "tvbox",
     "url": "https://gh-proxy.com/https://raw.githubusercontent.com/xmbjm/svip/refs/heads/main/svip.json",
     "mirrors": ["https://gh-proxy.com/raw.githubusercontent.com/xmbjm/svip/refs/heads/main/svip.json",
                 "https://raw.githubusercontent.com/xmbjm/svip/refs/heads/main/svip.json"]},
    # 金鹰（550.3vcn.work）：106 sites / 1 直播组；对账重叠 91 站，净新增 15 站（含星芽短剧等 short 面）。
    # 单主机源，失效走自动黑名单兜底。实测 200/69634B。
    {"name": "jinying/wdjyys", "kind": "tvbox", "url": "http://550.3vcn.work/wdjyys.json"},
]

# P0：直播源上游。2026-09-21 直播线融合扩容（六批调研落地，task 7687996812807916527）：
# 原 2 条（guovin 双通道）扩至 22 条；2026-09-22 第七批扩容（多仓调研+多App调研落地）再增 5 仓 6 条，共 28 条。全部经 live_probe 验活后纳入：
#   ok = L1+L2+L3 全过；format_only = L2 过、L3 沙箱抽样全挂（保留，交 CI 侧验活）；
#   blocked = 沙箱网关 502 无法判定（保留，交 CI 侧验活）；curl 复核项已单独注明。
# 沙箱内不可达不代表死链（CI 侧 raw 直连可达）；运行期任一上游连续 FAIL_LIMIT=3 次
# 失败会被自动停用进 blacklist_auto.txt，无需人工值守。
LIVE_UPSTREAMS = [
    # ---- 原有：guovin 双通道 ----
    {"name": "guovin-gd-ipv4", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/ipv4/result.m3u"},
    {"name": "guovin-release", "kind": "m3u",
     "url": "https://github.com/Guovin/iptv-api/releases/download/playlist-latest/result.m3u"},
    # ---- 第二批（3377/Kshao123/best-fan）----
    {"name": "3377-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/3377/IPTV/master/output/result.m3u"},  # 验活 ok 2261 频道
    {"name": "kshao123-tv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/Kshao123/TV/master/output/result.m3u"},  # 验活 format_only 2688 频道
    {"name": "bestfan-status", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_all_status.m3u8"},  # 验活 ok 164 频道带分辨率标注
    # ---- 第三批（Bruce0422/JunTV/zhi35/iTCoffe）----
    {"name": "bruce0422-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/Bruce0422/iptv-api/master/output/result.m3u"},  # 验活 ok 3217 频道（Guovin fork，每日 6:00/18:00）
    {"name": "juntv-main", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/alantang1977/JunTV/main/output/result.m3u"},  # 验活 ok 1317 频道（master 分支 404，已改 main）
    {"name": "zhi35-iptv", "kind": "m3u",
     "url": "https://live.zhi35.com/iptv.m3u"},  # probe 误判 binary_body（gzip），curl 复核 200/51272B 有效 m3u
    {"name": "itcoffe-itv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/iTCoffe/Collect-iTV/main/Internet_iTV.m3u"},  # 验活 format_only 3241 频道
    # ---- 第五批（xuy132/svefnz/yoursmile66）----
    {"name": "xuy132-tv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/xuy132/TV/master/output/result.txt"},  # 验活 ok 2648 条 txt 格式（每日 6:00/18:00）
    {"name": "svefnz-iptvn", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/svefnz/IPTVN/Files/IPTV.m3u"},  # 验活 ok 338 频道含港澳台（默认分支 Files）
    {"name": "yoursmile66-tvbox", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/yoursmile66/TVBox/main/live.txt"},  # 验活 ok 1156 条多线路 txt
    # ---- 第六批（Collect-IPTV 系独有上游）----
    {"name": "kilvn-iptv", "kind": "m3u",
     "url": "https://live.kilvn.com/iptv.m3u"},  # blocked=沙箱网关 502 无法判定，交 CI 验活
    {"name": "ibert-fmml", "kind": "m3u",
     "url": "https://m3u.ibert.me/txt/fmml_itv.txt"},  # 验活 format_only 189 频道
    {"name": "ibert-ycl", "kind": "m3u",
     "url": "https://m3u.ibert.me/ycl_iptv.m3u"},  # probe 瞬时 fetch_error，curl 复核 200/35330B 有效
    {"name": "vbskycn-iptv4", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/vbskycn/iptv/master/tv/iptv4.m3u"},  # 验活 ok 527 频道
    {"name": "iill-gather", "kind": "m3u",
     "url": "https://tv.iill.top/m3u/Gather"},  # blocked=沙箱网关 502 无法判定，交 CI 验活
    {"name": "zbds-iptv4", "kind": "m3u",
     "url": "https://live.zbds.org/tv/iptv4.m3u"},  # blocked=沙箱网关 502 无法判定，交 CI 验活
    {"name": "yuechan-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/YueChan/Live/main/IPTV.m3u"},  # 验活 format_only 96 频道
    {"name": "burningc4-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/BurningC4/Chinese-IPTV/master/TV-IPV4.m3u"},  # 验活 format_only 58 频道
    {"name": "zwc456baby-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/zwc456baby/iptv_alive/master/live.m3u"},  # 验活 ok 30 频道
    {"name": "hujingguang-cntv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/hujingguang/ChinaIPTV/main/cnTV_AutoUpdate.m3u8"},  # 验活 ok 60 频道
    # ---- 第七批（多仓调研+多App调研落地，2026-09-22）：5 仓 6 条 ----
    {"name": "ccsh-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/ccsh/iptv/main/live.m3u"},  # 验活 ok 2324 频道 47 组（MIT，全自动聚合产物，L3 抽样 3/5）
    {"name": "kimwang-bbxx365lite", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/kimwang1978/collect-txt/main/bbxx365_lite.m3u"},  # 验活 ok 7434 频道 24 组（每日归一化精简产物，沙箱 raw 直拉 200；全量版 bbxx365.m3u 25233 频道体积 4.3MB 未采用）
    {"name": "iptv0610-xp", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/0610840119/iptv-api/master/output/xp_result.m3u"},  # 验活 ok 683 频道 8 组（Guovin 变体秒播级，master 分支）
    {"name": "fanmingming-index", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/index.m3u"},  # 验活 format_only 94 频道（运营商鉴权流沙箱 403/404；CI 侧同仓 Pages 域名产物已验 ok/82 频道，交 live-validate 复核）
    {"name": "yang-gather", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/YanG-1989/m3u/main/Gather.m3u"},  # 验活 ok 123 频道（斗鱼/虎牙等大街源聚合；CI 侧 live_checks 同 URL 组验活 ok/123 频道）
    {"name": "yang-migu", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/YanG-1989/m3u/main/Migu.m3u"},  # 验活 format_only 43 频道（咪咕回看流 gslbserv.itv.cmvideo.cn 沙箱 403，交 CI 验活）
    # ---- 第十三批吸收实施（batch11 P1-1 / batch12 建议落地）：Romaxa55 canary ----
    # canary 语义：只监控不合并。cn.m3u 43 条 < MIN_ENTRIES_M3U=50 属设计内（不套通用门槛），
    # evaluate_upstream 走 canary 专用分支：fetch 200（由 fetch_raw 保证）+ 内容 >= CANARY_MIN_BYTES，
    # 日拉取在合并前跳过（canary continue）。GitHub Pages 静态产物 6h 自动验活；
    # 风险备注（batch11 调研）：README 带 MegaV VPN 商业推广，内容劣化由自动黑名单停用、可随时下线本条目。
    {"name": "romaxa55-cn", "kind": "m3u", "canary": True,
     "url": "https://romaxa55.github.io/world_ip_tv/output/cn.m3u"},  # 2026-09-22 沙箱实测 200/6946B，PARSERS['m3u'] 解析 43 条
    # ---- 第十四批吸收实施（batch8 建议优先融合①·单播面）：xisohi/CHINA-IPTV 分省分运营商源 ----
    # 主列表 TV/live.txt 1231 频道 / 90 域名 / 89 个为新增（batch8 重叠量化）；仓库 1820★ 当日活跃。
    # 组播面（Multicast/ 97 文件，rtp://239.x）不入此表——公网不可达，由 live_aggregate
    # 独立附录输出 lives/live_multicast.txt（内网限定标注）。
    {"name": "xisohi-china-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/xisohi/CHINA-IPTV/main/TV/live.txt"},  # 2026-09-22 沙箱实测 200/133750B，解析 1231 频道
]
# 报告点名的上游未纳入本次 LIVE_UPSTREAMS（有据记录，非遗漏）：
# - tzdr.com/iptv.txt（第六批）：沙箱两次 fetch_error + curl 000 不可达，不硬塞；
# - alantang1977/JunTV master 分支：404，已改用 main 分支（见上 juntv-main）；
# - suxuang/iptv、Kimentanm/iptv（第六批）：与 guovin 系产物重复，避免同质翻倍；
# - 裸 IP 175.178.251.183：报告未点名核实，不臆造；
# - Zhou-Li-Bin/Tvbox-QingNing README 直播源 12 条（第四批 P2 可选）：落点为 README 抓取，
#   不在本任务允许改动的文件清单内，暂不纳入。

# 试探性短剧/成人专项上游：失败/降级均不影响主流程（自动黑名单保护）
# 2026-09-18 实测 GitHub 搜索后，仅找到 duanju_juhe.js（猫/河马/星芽/牛牛 聚合）的 js 源片段
# 与若干订阅链接列表（非 json 配置），故此处仅尝试 jsm.json 系仓库下可能存在的
# duanju/duoduo 类 tvbox 配置分支。命中则纳入 short.json；否则被自动停用。
SHORTS_ADULT_UPSTREAMS = [
    {"name": "qist/duanju", "kind": "tvbox", "category": "short",
     "url": "https://raw.githubusercontent.com/qist/tvbox/master/duanju.json"},
    {"name": "qist/duoduo", "kind": "tvbox", "category": "short",
     "url": "https://raw.githubusercontent.com/qist/tvbox/master/duoduo.json"},
    {"name": "qist/wogg", "kind": "tvbox", "category": "adult",
     "url": "https://raw.githubusercontent.com/qist/tvbox/master/wogg.json"},
    {"name": "gao/duanju", "kind": "tvbox", "category": "short",
     "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/duanju.json"},
    {"name": "nxppru/duanju", "kind": "tvbox", "category": "short",
     "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/duanju.json"},
    {"name": "cluntop/duanju", "kind": "tvbox", "category": "short",
     "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/duanju.json"},
]

ALL_UPSTREAMS = UPSTREAMS + LIVE_UPSTREAMS + SHORTS_ADULT_UPSTREAMS


def _merge_upstream_config():
    """从 config/upstreams.json 合并上游配置，硬编码列表作 fallback。

    config 中 enabled=True 的条目覆盖/补充硬编码；config 缺失或为空时
    完全使用硬编码，保证向后兼容。
    """
    global UPSTREAMS, LIVE_UPSTREAMS, SHORTS_ADULT_UPSTREAMS, ALL_UPSTREAMS, UPSTREAM_BASES
    cfg = _ucfg.load_config()
    entries = cfg.get("upstreams", [])
    if not entries:
        return  # config 为空，保持硬编码
    # 按类型分组
    cfg_vod = [u for u in entries if u.get("type") == "vod" and u.get("enabled", True)]
    cfg_live = [u for u in entries if u.get("type") == "live" and u.get("enabled", True)]
    cfg_mixed = [u for u in entries if u.get("type") == "mixed" and u.get("enabled", True)]
    # 转换为 fetch_merge 格式并去重（以 url 为 key，config 优先）
    def _to_fm(u):
        kind = "m3u" if u.get("type") == "live" else "tvbox"
        e = {"name": u["name"], "kind": kind, "url": u["url"]}
        if u.get("mirrors"):
            e["mirrors"] = u["mirrors"]
        return e
    def _merge(hardcoded, cfg_entries):
        seen = {u["url"] for u in cfg_entries}
        result = [_to_fm(u) for u in cfg_entries]
        for u in hardcoded:
            if u["url"] not in seen:
                result.append(u)
                seen.add(u["url"])
        return result
    if cfg_vod:
        UPSTREAMS = _merge(UPSTREAMS, cfg_vod)
    if cfg_live:
        LIVE_UPSTREAMS = _merge(LIVE_UPSTREAMS, cfg_live)
    if cfg_mixed:
        SHORTS_ADULT_UPSTREAMS = _merge(SHORTS_ADULT_UPSTREAMS, cfg_mixed)
    ALL_UPSTREAMS = UPSTREAMS + LIVE_UPSTREAMS + SHORTS_ADULT_UPSTREAMS
    # 重建 UPSTREAM_BASES
    UPSTREAM_BASES = {u["name"]: u["url"].rsplit("/", 1)[0] + "/"
                      for u in (UPSTREAMS + SHORTS_ADULT_UPSTREAMS) if u.get("kind") == "tvbox"}


_merge_upstream_config()

UPSTREAM_BASES = {u["name"]: u["url"].rsplit("/", 1)[0] + "/" for u in (UPSTREAMS + SHORTS_ADULT_UPSTREAMS) if u.get("kind") == "tvbox"}

# 自动发现产出的 canary 上游（scripts/discover_upstreams.py -> state/extra_upstreams.json）。
# 默认关闭：自动收编陌生配置会让订阅引入未经审核的内容（含未知 jar/js），
# 需要显式 EXTRA_UPSTREAMS=1 才并入；开启后失效由现有自动黑名单兜住。
EXTRA_UPSTREAMS_FILE = os.environ.get("EXTRA_UPSTREAMS_FILE", "state/extra_upstreams.json")
EXTRA_UPSTREAMS_ON = os.environ.get("EXTRA_UPSTREAMS", "0") == "1"
# canary 里带成人特征的上游：2026-09-29 起不再整条剔除，改为「成人专供上游」——
# 站点照样收（全部强制判 adult，落 adult.json），但它的 lives/parses/spider/wallpaper
# 一律不进主产物。必须强制而不是靠 origin_votes：投票只作用于「弱信号单命中」
# （见 classify_site 第 5 步），成人仓里大量站点名字干净，走投票仍会被判 vod 混进主配置。
# 由 load_extra_upstreams() 填充（name 小写），classify_site 读它。
ADULT_ONLY_ORIGINS: set = set()

# ---------------- 成人内容发布开关（默认「不声明」模式，2026-09-22 所有者指令） ----------------
# 所有者指令：adult.json 每天随 daily 聚合产出并提交更新到仓库，但「只是不声明」——
# 不公开传播 / 宣传：不进 Release 附件白名单、不进 GitHub Pages、不进导航页、不在日报/README 中声明。
# 默认（PUBLISH_ADULT=0，「不声明」模式）：
#   1) 成人分类的站点不进 tvbox.json / vod.json（主产物口径不变）；
#   2) 仓库根 adult.json 每日照常产出（成人站点 + 成人直播），由 daily.yml 随提交白名单更新；
#      公开通路的隔离由三处保证：Release 上传白名单不含它、pages.yml 组目录双保险剔除、
#      导航页与 README 均无其入口与说明；
#   3) 不再写 .workbuddy 本地留档（留档职能由仓库根 adult.json 取代，
#      同时避免 pack_local 把它收进 Release 附件 zip）。
# PUBLISH_ADULT=1（完整公开模式）：成人站点同时进 tvbox.json / vod.json；
#   需要打进本地 zip 时给 pack_local.py 传 --adult adult.json。
PUBLISH_ADULT = os.environ.get("PUBLISH_ADULT", "0") == "1"
# 环④ 死引用剥离闸门：主配置（tvbox/vod/stores/short/adult）写产物前，
# 本地 ./deps 引用缺失的站点直接剔除；MAIN_DROP_DEAD_REFS=0 回到旧"仅记录不剔除"行为。
MAIN_DROP_DEAD_REFS = os.environ.get("MAIN_DROP_DEAD_REFS", "1") == "1"



def _norm_jsdelivr(url):
    """cdn.jsdelivr.net 主域在部分网络环境 400（见文件头 jsdelivr 注），统一规范为
    fastly.jsdelivr.net 子域。2026-09-26 治理：09-21 的一次性 state 手工修正被
    自动发现（discover_upstreams/evaluate_candidates 整文件重写 canary 池）用
    cdn 形态盖回，治理测试 test_jsdelivr_normalized 在 CI 失败——归一化提为
    管线不变量，canary 装载与两处收编写入口统一改写。"""
    if isinstance(url, str) and "://cdn.jsdelivr.net/" in url:
        return url.replace("://cdn.jsdelivr.net/", "://fastly.jsdelivr.net/")
    return url


def load_extra_upstreams() -> list:
    """读取 canary 上游名单；开关关闭或文件缺失时返回空列表。

    2026-09-25 合并层成人泄漏治理：canary 来自自动发现（脚本无成人过滤，
    曾吸入 jigedos/1024 等成人配置仓），按门禁同口径（PORN_KW/is_adult_url/
    ADULT_SOURCE_RE）剔除，否则接口元数据进 list.json 命中门禁，配置内容
    进 tvbox.json 又触发合并扫除——于源头拦截，避免下游多处补偿。
    """
    if not EXTRA_UPSTREAMS_ON or not os.path.isfile(EXTRA_UPSTREAMS_FILE):
        return []
    try:
        with open(EXTRA_UPSTREAMS_FILE, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    dropped = []
    for u in doc.get("upstreams", []):
        url, kind = u.get("url"), u.get("kind")
        if not (url and kind in PARSERS):
            continue
        url = _norm_jsdelivr(url)
        name = u.get("name") or url[-28:]
        rule = _candidate_adult_rule(name, url)
        ent = {"name": name, "kind": kind, "url": url, "auto": True}
        if rule:
            # 2026-09-29 所有者指令：带成人特征的 canary 不再整条丢弃，改为进成人池。
            # 站点强制 adult（落 adult.json）、直播强制下放成人直播池（adult_live.json），
            # parses/spider/wallpaper 不收（它们是主配置的全局字段，名字会漏进非成人产物）。
            ent["adult"] = True
            ADULT_ONLY_ORIGINS.add(name.lower())
            dropped.append((name, rule))
        # 吸收点 P1-2：canary 名单同样支持 mirrors 多镜像选通
        if isinstance(u.get("mirrors"), list) and u["mirrors"]:
            ent["mirrors"] = [_norm_jsdelivr(m) for m in u["mirrors"] if isinstance(m, str) and m]
        out.append(ent)
    if out:
        print(f"    canary 上游 {len(out)} 个已并入本轮拉取（EXTRA_UPSTREAMS=1）", flush=True)
    if dropped:
        print(f"    canary 成人特征上游 {len(dropped)} 个转成人池（站点→adult.json，"
              f"直播→adult_live.json，不收 parses/spider）：", flush=True)
        for nm, r in dropped:
            print(f"      - {nm} rule={r}", flush=True)
    return out


def _candidate_adult_rule(name: str, url: str):
    """canary/自动发现上游的成人特征判定（与 adult 零泄漏门禁同口径）。
    返回命中规则标签字符串；未命中返回 None。"""
    for s in (name, url):
        if not s:
            continue
        low = s.lower()
        for kw in _la.PORN_KW:
            if kw.lower() in low:
                return "porn_kw:%s" % kw[:16]
        if "://" in s and _la.is_adult_url(s):
            return "host_blacklist"
        m = _la.ADULT_SOURCE_RE.search(s)
        if m:
            return "source_pattern:%s" % m.group(0)[:24]
    return None


def public_list_filter(interfaces: list):
    """公开清单「不声明」口径（同 adult.json 的"产出但不声明"决策）：成人特征上游的
    URL 绝不进 list.json/list_min.json——真成人仓（jigedos/1024）与用户名子串误报区
    （javyou/saulxxx）用同一条三重判定（_candidate_adult_rule）一并剥除，内部账本与
    成人池不受影响。门禁因此不需要每次发现新仓都补白名单——白名单只兜"已评审要保留"
    的例外，不该当橡皮图章。返回 (保留列表, 被剥 URL 列表)。"""
    def _hide(_e):
        _n = str(_e.get("name") or _e.get("origin") or "")
        return bool(_candidate_adult_rule(_n, str(_e.get("url") or ""))
                    or _candidate_adult_rule(_n, str(_e.get("success_url") or "")))
    kept = [e for e in interfaces if not _hide(e)]
    hidden = [str(e.get("url") or e.get("name") or "?") for e in interfaces if _hide(e)]
    return kept, hidden


# ==================== 短剧/成人分类（独立收录 short.json / adult.json） ====================
# 关键词来源：现有 tvbox.json 22 条短剧站点 + 39 条成人站点的 name/key/api 关键字汇总（2026-09-18 扫描）
# 命中规则：name 或 key 含任一关键词则归入；name/key 均不命中时扫描 api 主机/路径作为兜底
SHORT_KEYWORDS = [
    "短剧", "微短剧", "短剧场",   # 中文
    "duanju", "duanjucat", "duanjumao", "shortplay", "short_play",  # 拼音/英文
    "七猫", "河马", "围观", "好看", "星芽", "果果", "红果", "黄果", "黄豆",
    "锦鲤", "偷乐", "上头", "聚合短剧",
]
ADULT_LIVE_SOURCES = [
    # fish2018/lib 成人直播/成人影片（每个都在 sandbox 实测过 http 200 + 至少一条流抽样通过）
    ("18+合集",   "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/18+.txt",        10679),
    ("live18",     "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/live18.txt",    8917),
    ("pron",       "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/pron.m3u",         64),
    ("国产传媒",   "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/几个传媒.txt",   3331),
    ("成人传媒",   "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/成人传媒.txt",   2980),
    ("成人电影",   "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/成人电影.txt",  14873),
    ("18资源丰富", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/18资源丰富.txt", 5564),
    ("花活",       "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/花活.txt",        2540),
    ("天美传媒816", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/天美传媒816.txt", 23),
    ("果冻传媒816", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/果冻传媒816.txt", 63),
    ("精东影业816", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/精东影业816.txt", 24),
    ("麻豆传媒816", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/麻豆传媒816.txt", 12),
    ("星空传媒816", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/星空传媒816.txt", 46),
]


def _scrub_txt_file(path: str, is_adult_fn) -> None:
    """tvbox 分组 txt 成人行剔除（含其全部线路；#genre# 组头保留）。"""
    try:
        _kept, _dropped = [], 0
        with open(path, encoding="utf-8") as _f:
            for _ln in _f:
                _ln = _ln.rstrip("\n")
                if not _ln or _ln.endswith(",#genre#"):
                    _kept.append(_ln)
                    continue
                _name = _ln.split(",", 1)[0].strip()
                if is_adult_fn(_name) or any(is_adult_fn(_seg) for _seg in _name.split("/")):
                    _dropped += 1
                    continue
                _kept.append(_ln)
        if _dropped:
            with open(path, "w", encoding="utf-8") as _f:
                _f.write("\n".join(_kept) + ("\n" if _kept else ""))
            print("[curated] 快照成人清洗：%s 剔除 %d 行" % (os.path.basename(path), _dropped),
                  flush=True)
    except FileNotFoundError:
        pass
    except Exception as _e:  # 清洗失败不阻断发布，门禁终扫仍是最后防线
        print("[curated] 快照成人清洗异常（%s）：" % os.path.basename(path), _e, flush=True)


def _scrub_m3u_file(path: str, is_adult_fn) -> None:
    """m3u 成人频道剔除：#EXTINF 判名，命中连其后 URL 行一起删。"""
    try:
        _kept, _dropped = [], 0
        _adult_cur = False
        with open(path, encoding="utf-8") as _f:
            for _ln in _f:
                _ln = _ln.rstrip("\n")
                if _ln.startswith("#EXTINF"):
                    _name = _ln.rsplit(",", 1)[-1].strip()
                    _adult_cur = bool(is_adult_fn(_name)) or any(
                        is_adult_fn(_seg) for _seg in _name.split("/"))
                    if _adult_cur:
                        _dropped += 1
                        continue
                    _kept.append(_ln)
                elif _ln.startswith("#"):
                    _adult_cur = False  # 其他元信息行不影响后续条目
                    _kept.append(_ln)
                else:
                    if _adult_cur:
                        _dropped += 1
                        continue
                    _kept.append(_ln)
        if _dropped:
            with open(path, "w", encoding="utf-8") as _f:
                _f.write("\n".join(_kept) + ("\n" if _kept else ""))
            print("[curated] 快照成人清洗：%s 剔除 %d 条目" % (os.path.basename(path), _dropped),
                  flush=True)
    except FileNotFoundError:
        pass
    except Exception as _e:
        print("[curated] 快照成人清洗异常（%s）：" % os.path.basename(path), _e, flush=True)


def _scrub_snapshot(repo_dir: str, is_adult_fn) -> None:
    """消费测速快照前的成人频道兜底清洗（2026-09-26，task 7689782040580885721）。

    背景：live-speedtest / adult-live-probe 等工作流直接提交 state/live_checks.json
    与 lives/ 产物，但它们不跑成人零泄漏门禁；本发布流程消费快照等于原样继承
    脏频道（实证：run 36238948295 门禁抓到 B 站房间标题
    「母亲节特别企划/义母乱伦童贞毕业/tz-056」，porn_kw:乱伦）。
    这里以聚合同口径 is_adult(频道名) 在消费侧双写清洗（2026-09-26 起产物为
    lives/groups/<组>.txt + <组>.m3u 分组文件，不再有大文件 live_verified.txt）：
      ① lives/groups/*.txt 剔除成人频道行（含其全部线路）；
      ② lives/groups/*.m3u 剔除成人频道的 #EXTINF 及其 URL 行；
      ③ state/live_checks.json 剔除成人频道键（含「前缀/台名」复合键逐段判定）。
    清洗只删不增；被删频道若属误杀，应走词表白名单复核流程，本函数不做放行。
    """
    _gdir = os.path.join(repo_dir, "lives", "groups")
    if os.path.isdir(_gdir):
        for _fn in sorted(os.listdir(_gdir)):
            _path = os.path.join(_gdir, _fn)
            if _fn.endswith(".txt"):
                _scrub_txt_file(_path, is_adult_fn)
            elif _fn.endswith(".m3u"):
                _scrub_m3u_file(_path, is_adult_fn)
    _ck_p = os.path.join(repo_dir, "state", "live_checks.json")
    try:
        with open(_ck_p, encoding="utf-8") as _f:
            _data = json.load(_f)
        _chs = _data.get("channels") if isinstance(_data, dict) else None
        if isinstance(_chs, dict):
            _drop = []
            for _k in list(_chs):
                _segs = [_k] + _k.split("/")
                if any(is_adult_fn(_seg) for _seg in _segs):
                    _drop.append(_k)
            if _drop:
                for _k in _drop:
                    _chs.pop(_k, None)
                with open(_ck_p, "w", encoding="utf-8") as _f:
                    json.dump(_data, _f, ensure_ascii=False)
                print("[curated] 快照成人清洗：live_checks.json 剔除 %d 频道（%s…）"
                      % (len(_drop), _drop[0][:24]), flush=True)
    except FileNotFoundError:
        pass
    except Exception as _e:
        print("[curated] 快照成人清洗异常（live_checks.json）：", _e, flush=True)


def build_curated_lives(repo_dir: str):
    """产出 lives/groups/<组>.txt|.m3u 分组直播产物 + live.json 分组接口 + 成人 lives。
    调用本函数后，写入 live.json / adult.json 时各取所需。"""
    import os as _os
    sys.path.insert(0, _os.path.join(repo_dir, "scripts"))
    # 2026-09-25 P0-3 测速与发布解耦：优先消费「最近一次成功直播测速结果」。
    # 测速由独立 job（live-speedtest.yml）执行并提交 state/live_check_meta.json +
    # lives/ 产物；本 job 只消费：元数据 26h 内（LIVE_MAX_AGE_S 可调）→ 不在本
    # 流程内重跑逐线路实测（9 连 cancelled 的历史根因就是测速塞进发布流程）。
    # 元数据缺失/过期 → 回退本轮内聚合（保底：直播产物永远有产出）。
    _max_age = int(_os.environ.get("LIVE_MAX_AGE_S", str(26 * 3600)))
    _meta_p = _os.path.join(repo_dir, "state", "live_check_meta.json")
    _fresh = False
    try:
        with open(_meta_p, encoding="utf-8") as _f:
            _meta = json.load(_f)
        _age = time.time() - datetime.strptime(_meta["updated"], "%Y-%m-%dT%H:%M:%S").timestamp()
        _have_out = _os.path.isfile(_os.path.join(repo_dir, "lives", "groups", "央视.txt"))
        if _have_out and 0 <= _age < _max_age:
            _fresh = True
            print("[curated] 消费最近一次成功直播测速结果：%.1fh 前（shard=%s，%s 频道，verified=%s）"
                  % (_age / 3600, _meta.get("shard"), _meta.get("channels"),
                     _meta.get("verified_channels")), flush=True)
            # 2026-09-26 消费侧成人清洗：测速快照未经频道名成人过滤，直接消费会
            # 把脏频道带进发布产物与 live_checks.json（run 36238948295 门禁实证）。
            # 按聚合同口径 is_adult 兜底剔除后再进入产物链。
            try:
                import live_aggregate as _la  # noqa: WPS433
                _scrub_snapshot(repo_dir, _la.is_adult)
            except Exception as _e:
                print("[curated] 快照成人清洗跳过：", _e, flush=True)
    except Exception as _e:
        print("[curated] 测速快照元数据不可读（%s），回退本轮聚合" % _e, flush=True)
    if not _fresh:
        try:
            import live_aggregate as _la  # noqa: WPS433
            _shard = _os.environ.get("LIVE_SHARD") or None
            _la.main(repo=repo_dir,
                     out_json="live_channels.json", shard=_shard)
        except Exception as e:  # 单次聚合失败不影响主流程
            print("[curated] live_aggregation 跳过：", e.getMessage() if hasattr(e, "getMessage") else e, flush=True)

    # 2026-09-26 用户指令「不要生成大文件，生成多个分组的 txt 和 m3u」：
    # 直播产物改为 lives/groups/<组>.txt（+同名 .m3u）；池子（live_cctv/weishi/
    # gangtai/other.txt 等供 tvbox.json Guovin 条目消费）与精准/组播/原始源保留。
    # 2026-09-27 用户指令「live.json 只显示一个汇总的」：live.json 单条目改指
    # lives/live_all.txt（由 live_aggregate.write_group_txts 随分组一并写出）。
    _RAW = "https://gh.halonice.com/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/"
    _GROUPS = ("央视", "卫视", "地方", "港台", "轮播", "直播", "其他")
    curated = []
    # 2026-09-27 用户指令「live.json 只显示一个汇总的」：回到单仓——7 条分组入口
    # 在播放器里显示成 7 个仓，改为单条目「聚合·分类直播」指向 lives/live_all.txt
    # （全大组依序拼接的合并文件，组内 #genre# 分节即播放器内分类导航）。
    curated.append({
        "name": "聚合·分类直播",
        "type": 1,
        "url": _RAW + "lives/live_all.txt",
        "ua": "TVBox",
        "epg": "https://epg.pw/api/v1/getEpgInfo?token=tvbox",
    })

    # 优质第三方直播源：live.json 固定为分组接口（聚合·分类直播·*），
    # Guovin/平台直播等第三方条目一律不再进入。
    THIRD_PARTY_OK = {}
    for nm, (u, _g) in THIRD_PARTY_OK.items():
        curated.append({"name": nm, "type": 1, "url": u, "group": _g})

    adult_lives = []
    for name, url, ch_count in ADULT_LIVE_SOURCES:
        adult_lives.append({
            "name": "成人·" + name,
            "type": 1,
            "url": url,
            "group": "成人直播",
            "channels": ch_count,
        })
    return curated, adult_lives


ADULT_KEYWORDS = [
    # 明确成人/色情关键词（收紧：去除通用资源站误匹配）
    "成人", "18+", "porn", "麻豆", "果冻", "天美", "精东", "色播", "传媒",
    "花活", "丝袜", "美腿", "hsck", "jav", "1024", "91porn", "91md", "91panta", "91splt", "91bobo", "91精品",
    "色花糖", "朱古力", "Missav", "missav",
    # 注：2026-09-26 用户裁定「玩偶」移出成人词表——玩偶(wogg)系 4K 网盘影视站，
    # 非成人站；此前因 feishu-sync 上游含真成人站被上游投票连带误收进 adult.json。
    "Xojav", "JavBus", "JavDb", "涩涩", "Websites",
    # 扩张：常见成人站点标志词
    "xvideos", "pornhub", "xhamster", "hdsemj", "tokyo-hot",
    # 限定形容词（"敏感词"语义强）— 仅作为最后防线
    "裸聊", "裸播", "黄播", "黄网", "瑟瑟情",
    # 2026-09-21 点播+容错线：高置信词 ×10 增量（来源：实读 ccAzy separate_sources.py
    # 词表后人工挑选，走本表关键词匹配而非其删除式过滤；均为社区普遍使用的成人
    # 站名/黑话，误匹配风险低）
    "探花", "蜜桃", "糖心", "海角", "含羞草", "草榴", "秋霞", "番号", "无码", "里番",
]


def classify_site(s, overrides: dict = None) -> str:
    """返回 'short' / 'adult' / 'vod'。短剧与成人为独立收录分类，其余保持 vod。
    人工覆盖表（state/category_overrides.json，key -> 分类）优先于关键词匹配。"""
    if not isinstance(s, dict):
        return "vod"
    name = s.get("name") or ""
    key = s.get("key") or ""
    if overrides and key and key in overrides:
        return overrides[key]
    api = s.get("api") or ""
    ext = s.get("ext")
    ext_str = ""
    if isinstance(ext, str):
        ext_str = ext
    elif isinstance(ext, dict):
        ext_str = json.dumps(ext, ensure_ascii=False)
    # 跳过纯 MD5 key（上游用 32 位 hex 当 key，会与关键字如 "91"/"jav" 误撞）
    key_use = "" if (len(key) == 32 and all(c in "0123456789abcdef" for c in key.lower())) else key
    target = f"{name} {key_use} {api} {ext_str}".lower()
    # 优先短剧匹配（避免成人站点关键词误吞）
    if any(kw.lower() in target for kw in SHORT_KEYWORDS):
        return "short"
    if any(kw.lower() in target for kw in ADULT_KEYWORDS):
        return "adult"
    return "vod"


# 2026-09-23 改为多信号分级。强信号单命中即判 adult；弱信号需 ≥2 命中或上游投票佐证，
# 避免「吃瓜」「迷妹」等通用词单独命中误杀 vod 站；已知误报 key 进白名单强制 vod。
# 上游投票：同 repo 内强信号命中 ≥2 个站点 → 该 repo 其余未分类站也按投票结果走 adult。
STRONG_ADULT_TOKENS = [
    # 上游/官方标记
    "🔞",
    # 国际化成人平台（品牌词，零误匹配风险）
    "pornhub", "xvideos", "xhamster", "tokyo-hot",
    "javbus", "javdb", "xojav", "missav",
    "91porn", "91md", "hdsemj",
    # 明确成人 api 域名（社区共识的成人 CMS 后端）
    "souavzy", "pgxdy", "dadiapi", "lbapi9", "xrbsp", "jcspcj8",
    "caiji25", "sdszyapi", "hsck",
    # 明确站点标志词（带数字/连字符变体）
    "18av", "4kav", "4k-av", "cableav", "netflav", "owoav", "souav", "黄av",
    # 明确中文成人站点品牌
    "麻豆", "果冻传媒", "天美传媒", "精东传媒",
]

WEAK_ADULT_TOKENS = [
    "成人", "18+", "porn", "传媒", "色播", "丝袜", "美腿",
    "花活", "1024",
    "91panta", "91splt", "91bobo", "91精品",
    "色花糖", "朱古力", "涩涩",
    # 2026-09-26：「玩偶」移出——wogg 系 4K 网盘影视站，非成人站（用户裁定）
    "裸聊", "裸播", "黄播", "黄网", "瑟瑟情",
    "探花", "蜜桃", "糖心", "海角", "含羞草", "草榴", "秋霞", "番号", "无码", "里番",
    "淫水", "色屌丝", "咪咪资源", "嗨片", "吃瓜", "迷妹", "黄果", "熊猫资源",
    "果冻", "天美", "精东",
]

# 已知误报白名单：key 命中强制 vod（这些是网盘/通用资源站，与成人无关）
ADULT_FALSE_POSITIVE_KEYS = {
    "webdav", "webdav1", "webdav2", "webdav3",
    "clouddrive", "aliyundrive", "aliyundrive2",
}
ADULT_FALSE_POSITIVE_NAME_FRAGMENTS = (
    "webdav", "web dav", "clouddrive", "阿里云盘", "alist",
)


def _classify_target_text(s: dict) -> str:
    """构造大小写归一化的搜索串（name + api + ext + 净化 key），跳过 32 位 MD5 key 防误撞。"""
    name = s.get("name") or ""
    api = s.get("api") or ""
    ext = s.get("ext")
    ext_str = ""
    if isinstance(ext, str):
        ext_str = ext
    elif isinstance(ext, dict):
        ext_str = json.dumps(ext, ensure_ascii=False)
    key = s.get("key") or ""
    key_use = "" if (len(key) == 32 and all(c in "0123456789abcdef" for c in key.lower())) else key
    return f"{name} {key_use} {api} {ext_str}".lower()


def classify_site(s, overrides: dict = None, origin_votes: dict = None) -> str:
    """返回 'short' / 'adult' / 'vod'。多信号分级：
    1) 人工覆盖表（state/category_overrides.json）优先；
    2) 已知误报 key/name → vod 兜底；
    3) 短剧关键词优先（避免成人词误吞短剧）；
    4) 强信号关键词 → adult；
    5) 弱信号关键词：单命中 → 仅当上游已 ≥1 站被判 adult 才升 adult；多命中 → 直接 adult；
    6) 其余 vod。

    origin_votes: {上游名: 强信号 adult 命中数}；None 表示不启用上游投票。
    """
    if not isinstance(s, dict):
        return "vod"
    key_raw = s.get("key") or ""
    key = key_raw.lower()
    name = s.get("name") or ""

    # 1. 人工覆盖表（保持原大小写匹配语义，避免与既有 state/category_overrides.json 冲突）
    # 3.4-2：仅内容分类(short/adult/vod)短路；接口类型(cms/pan/csp)留给 store_kind_of，不在此短路
    if overrides and key_raw and key_raw in overrides and overrides[key_raw] in CONTENT_CATEGORIES:
        return overrides[key_raw]

    # 2. 已知误报白名单
    if key in ADULT_FALSE_POSITIVE_KEYS:
        return "vod"

    # 2b. 成人专供上游（canary 带成人特征）：整仓站点一律 adult，不看关键词。
    # 不放投票里是因为投票只影响「弱信号单命中」，成人仓里名字干净的站点会漏判。
    origin = (s.get("_origin") or s.get("origin") or "").lower()
    if origin and ADULT_ONLY_ORIGINS and origin in ADULT_ONLY_ORIGINS:
        return "adult"
    name_lower = name.lower()
    if any(frag in name_lower for frag in ADULT_FALSE_POSITIVE_NAME_FRAGMENTS):
        return "vod"

    target = _classify_target_text(s)

    # 3. 短剧关键词优先（保留原逻辑）
    if any(kw.lower() in target for kw in SHORT_KEYWORDS):
        return "short"

    # 4. 强信号关键词直接判 adult
    if any(t.lower() in target for t in STRONG_ADULT_TOKENS):
        return "adult"

    # 5. 弱信号关键词：单命中需上游投票；多命中直接判
    weak_hits = [t for t in WEAK_ADULT_TOKENS if t.lower() in target]
    if weak_hits:
        if len(weak_hits) >= 2:
            return "adult"
        # 单命中：查上游投票
        if origin_votes:
            site_origin = (s.get("_origin") or s.get("origin") or "").lower()
            if site_origin and origin_votes.get(site_origin, 0) >= 1:
                return "adult"

    return "vod"


def classify_site_strong_only(s, overrides: dict = None) -> str:
    """只用强信号 + 覆盖表 + 短剧词 + 误报白名单判定成人，用于上游投票预扫。
    弱信号在此场景不参与计数，避免把低置信度站计入上游投票而误伤同级站。"""
    if not isinstance(s, dict):
        return "vod"
    key = (s.get("key") or "").lower()
    if overrides and key and key in overrides:
        return overrides[key]
    if key in ADULT_FALSE_POSITIVE_KEYS:
        return "vod"
    name_lower = (s.get("name") or "").lower()
    if any(frag in name_lower for frag in ADULT_FALSE_POSITIVE_NAME_FRAGMENTS):
        return "vod"
    target = _classify_target_text(s)
    if any(kw.lower() in target for kw in SHORT_KEYWORDS):
        return "short"
    if any(t.lower() in target for t in STRONG_ADULT_TOKENS):
        return "adult"
    return "vod"


# ==================== 门禁同口径终扫（P0-2 红线对齐，2026-09-26） ====================
# 根因（daily run 36187372853 step17 门禁 3562 处命中 / be53fa8 轮同源 3213 处）：
# 合并层 classify_site 的 STRONG/WEAK_ADULT_TOKENS 与门禁词表
# （state/vocab/categories.json adult 节，live_aggregate/adult_leak_check 加载）
# 是两套独立维护的词表。词表漂移后，上游重合并注入的成人采集站（玉兔/madouse/
# Jable 等：命中门禁词表但不在合并层词表）以 vod 分类进入 tvbox.json，被 step17
# 一票否决拦截。修法：不维护第三套词表——终扫直接复用门禁自己的扫描语义
# （_scan_string：PORN_KW 子串 / is_adult_url 域名黑名单 / ADULT_SOURCE_RE 整源
# 模式）与误报白名单（state/adult_leak_whitelist.txt，guarded 命中与门禁同口径
# 放行），对将进入常规产物的站点/直播/解析/全局字段逐一扫描：
#   站点/直播条目命中 → 重定向 adult.json 独立通道（与既有隔离通路同源）；
#   解析/顶层字符串命中 → 直接剔除。
# 由此「合并层产出 == 门禁可放行」按构造成立，词表后续只需维护 vocab 一份。

ADULT_GATE_WHITELIST = _adult_gate._whitelist_res(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "state", "adult_leak_whitelist.txt"))


def adult_gate_scan(node):
    """门禁同口径扫描任意 JSON 节点，返回 (real_hits, guarded_hits)。

    扫描语义与 adult_leak_check 的 _scan_string / _iter_strings 完全一致：
    任意字符串跑 PORN_KW 子串 / is_adult_url（含 :// 才跑）/ ADULT_SOURCE_RE；
    命中误报白名单的记为 guarded（不剔除，与门禁放行口径一致）。
    返回元组：(非白名单命中列表, 白名单拦截列表)，两者均为明细 dict。
    """
    hits = []
    _adult_gate._iter_strings(node, "$", "merge-stage-sweep", hits, ADULT_GATE_WHITELIST)
    real = [h for h in hits if h.get("kind") != "guarded"]
    guarded = [h for h in hits if h.get("kind") == "guarded"]
    return real, guarded


def _split_by_adult_gate(items):
    """按门禁同口径终扫切分条目列表，返回 (clean_items, gate_hits, guarded_count)。

    gate_hits 为 [(条目, real_hits)]；clean_items 为零真实命中的干净条目。
    """
    clean, hits, guarded_n = [], [], 0
    for it in items:
        real, guarded = adult_gate_scan(it)
        if real:
            hits.append((it, real))
        else:
            clean.append(it)
            guarded_n += len(guarded)
    return clean, hits, guarded_n


# ==================== adult 直播源测速与成人站点搜索验收 ====================
PROBE_STREAM_RANGE = (0, 2047)  # 直播抽验流 2KB（与 aa5a88d 通用做法对齐）


def _parse_live_list_first_stream(body: bytes, url: str) -> str | None:
    """从 txt（行 "name,url"，#genre# 块标记）或 m3u（#EXTINF 后的 URL）取第一条 http(s) 流。"""
    txt = body.decode("utf-8", "replace")
    for raw in txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#EXTM3U"):
            continue
        if line.startswith("#"):
            continue
        if "," in line and line.split(",", 1)[1].strip().lower().startswith(("http://", "https://")):
            return line.split(",", 1)[1].strip()
        if line.lower().startswith(("http://", "https://")):
            return line
    return None


def probe_adult_lives(adult_lives: list, *, timeout: int = 8, max_bytes: int = 32768) -> tuple:
    """成人直播源测速 + 抽首流验活，返回 (sorted_lives, stats)。

    ms = 列表文件下载耗时（"加载有内容" 的口径）。stream_ok = 从列表里抽第一条流做
    Range 抽段是否 2xx（非 2xx 视为不可访问）。安全阀：stream_ok 率 < 20% 视为网络/抽
    样异常，保留全部并按列表下载耗时排序、不剔除（保护沙箱受限环境）。
    """
    stats = {"before": len(adult_lives), "after": 0, "stream_ok": 0, "stream_dead": 0,
             "safety_valve_triggered": False}
    if not adult_lives:
        return adult_lives, stats
    probed = []
    for l in adult_lives:
        url = l.get("url")
        ms = 0
        list_ok = False
        try:
            status, body, elapsed = http_get(url, timeout, max_bytes)
            ms = elapsed
            list_ok = bool(status == 200 and body)
        except Exception:
            list_ok = False
        stream_ok = False
        stream_ms = 0
        if list_ok:
            stream_uri = _parse_live_list_first_stream(body, url)
            if stream_uri:
                try:
                    st, _, el = http_get(stream_uri, timeout, 0, rng=PROBE_STREAM_RANGE)
                    stream_ms = el
                    if st in (200, 206):
                        stream_ok = True
                except Exception:
                    pass
        probed.append({
            "item": l, "ms": ms, "list_ok": list_ok,
            "stream_ok": stream_ok, "stream_ms": stream_ms,
        })
        stats["stream_ok" if stream_ok else "stream_dead"] += 1
    if stats["before"] > 0 and stats["stream_ok"] / stats["before"] < 0.20:
        stats["safety_valve_triggered"] = True
        # 安全阀：保留全部，仅按列表下载耗时排（升序=快的在前）
        key_fn = lambda p: (not p["list_ok"], p["ms"], p["item"].get("name") or "")
    else:
        # 可访问在前，同档内加载耗时升序（快的在前）；不可访问沉底
        key_fn = lambda p: (not p["stream_ok"], not p["list_ok"], p["ms"], p["item"].get("name") or "")
    probed.sort(key=key_fn)
    # 标记实测可访问标志（装配阶段据所有者指令剔除不可访问的）
    for p in probed:
        p["item"]["_probe_stream_ok"] = bool(p["stream_ok"])
    out = [p["item"] for p in probed]
    stats["after"] = len(out)
    return out, stats


# 搜索词降级序列——对苹果CMS V10 类站点（api 返回 JSON、ac=videolist 协议）
SEARCH_KEYWORDS = ("麻豆", "爱", "传媒")


def _adult_search_and_play(api_url: str, timeout: int = 8) -> dict:
    """对单个站点 api 做「搜索有结果 + 可播放」验收，返回 {search_ok, play_ok, ms_total, vod_name}。

    流程：依次试关键词 ?ac=videolist&wd=<kw> → JSON.list 非空 → 取首个 vod_id →
    ?ac=videolist&ids=<id> → 解析 vod_play_url 中第一个 m3u8 → Range 抽段验证 2xx。
    任一步失败按实际失败位置返回。csp_/jar 类（api 非 http）调用方应在调用前过滤。
    """
    import json as _json
    res = {"search_ok": False, "play_ok": False, "ms_total": 0, "vod_name": ""}
    if not api_url.startswith(("http://", "https://")):
        return res
    sep = "&" if "?" in api_url else "?"
    t0 = time.time()
    list_payload = None
    for kw in SEARCH_KEYWORDS:
        try:
            status, body, _ = http_get(f"{api_url}{sep}ac=videolist&wd={urllib.parse.quote(kw)}", timeout, 65536)
            if status != 200 or not body:
                continue
            j = _json.loads(body.decode("utf-8", errors="replace") or "{}")
            lst = (j.get("list") or [])
            if isinstance(lst, list) and lst:
                res["search_ok"] = True
                list_payload = (kw, lst[0])
                res["vod_name"] = lst[0].get("vod_name") or ""
                break
        except Exception:
            continue
    if not res["search_ok"] or not list_payload:
        res["ms_total"] = int((time.time() - t0) * 1000)
        return res
    vod_id = (list_payload[1].get("vod_id") or "")
    if not vod_id:
        res["ms_total"] = int((time.time() - t0) * 1000)
        return res
    play_url = ""
    try:
        status, body, _ = http_get(f"{api_url}{sep}ac=videolist&ids={vod_id}", timeout, 65536)
        if status == 200 and body:
            j = _json.loads(body.decode("utf-8", errors="replace") or "{}")
            lst = j.get("list") or []
            if lst:
                # TVBox vod_play_url 格式：name$url#name2$url2；先按 # 取首集再按 $ 取 URL
                field = (lst[0].get("vod_play_url") or "")
                first = field.split("#", 1)[0]
                parts = first.split("$")
                play_url = parts[-1].strip() if parts else ""
    except Exception:
        pass
    if play_url.lower().startswith(("http://", "https://")):
        try:
            st, _, _ = http_get(play_url, timeout, 0, rng=PROBE_STREAM_RANGE)
            if st in (200, 206):
                res["play_ok"] = True
        except Exception:
            pass
    res["ms_total"] = int((time.time() - t0) * 1000)
    return res


def verify_adult_sites(adult_sites: list, check_latency: dict, *, timeout: int = 8) -> tuple:
    """成人站点「搜索有结果 + 可播放」验收 + 排序，返回 (sorted_sites, stats)。

    csp_/jar 类（api 非 http）走不可外部验证 → 标 unverified，按 check_latency 兜底排序；
    其余走 _adult_search_and_play。排序键：(play_ok, search_ok, ms_total, name)；
    unverified 排最后，按 check_latency 升序兜底。
    """
    stats = {"before": len(adult_sites), "after": 0, "play_ok": 0, "search_ok": 0,
             "unverified": 0, "search_dead": 0, "total_ms": 0}
    if not adult_sites:
        return adult_sites, stats
    probed = []
    for s in adult_sites:
        api = s.get("api") or ""
        if not api.startswith(("http://", "https://")):
            probed.append({"item": s, "search_ok": False, "play_ok": False,
                           "ms_total": 0, "unverified": True})
            stats["unverified"] += 1
            continue
        try:
            r = _adult_search_and_play(api, timeout=timeout)
        except Exception:
            r = {"search_ok": False, "play_ok": False, "ms_total": 0, "vod_name": ""}
        probed.append({"item": s, **r, "unverified": False})
        stats["total_ms"] += r.get("ms_total") or 0
        if r["play_ok"]:
            stats["play_ok"] += 1
            stats["search_ok"] += 1
        elif r["search_ok"]:
            stats["search_ok"] += 1
        else:
            stats["search_dead"] += 1
    # 排序：可播放 > 可搜索 > 不可外部验证（csp 类） > 搜索失败
    # 同组内速度升序
    key_fn = lambda p: (
        not p["play_ok"],                                   # False < True → play_ok 排前
        not p["search_ok"],                                 # 同理 search_ok
        p["unverified"],                                    # unverified 沉底
        p.get("ms_total") or 0,                             # 同档内速度升序
        p["item"].get("name") or "",
    )
    probed.sort(key=key_fn)
    # 标记实测可播放/可搜索/不可外部验证标志（装配阶段按所有者口径过滤：
    # 「播放不了的就不要留」仅适用于可外部验证的站点；csp/jar 类不剔除）
    for p in probed:
        p["item"]["_probe_play_ok"] = bool(p["play_ok"])
        p["item"]["_probe_search_ok"] = bool(p["search_ok"])
        p["item"]["_probe_unverified"] = bool(p.get("unverified"))
    out = [p["item"] for p in probed]
    stats["after"] = len(out)
    return out, stats



# ==================== 解析池（parses）清洗 ====================
# short.json 等分类产物复用 vod 的 parses 全集（adult.json 自 2026-09-23 起按所有者
# 指令不再携带 parses；TVBox 站点不依赖 parses，parses 是。adult_live.json 同日拆分。
# 全局播放器池）。但历史版本未做去重，导致「一堆没用的解析」：
#   · 同一 URL 多个不同 name（如 jx.xmflv.com 至少 5 个别名）
#   · localhost/127.0.0.1/192.168.x 等本地代理引用（用户环境不可用）
#   · 类型错误（type 为字符串 "1" 而非 int）
#   · 占位 url（type 3 的 "Demo"/"Web" 内置功能，重复 6/7 次应各留一条）
# 修复目标：结构校验 + 私有地址剔除 + URL 规范化去重 + 可选 TCP 探活 + 安全阀
_VALID_PARSE_TYPES = {0, 1, 2, 3, 4}
_LOOPBACK_HOSTS = {"localhost", "0.0.0.0", "::1", "[::1]"}


def _is_private_host(host: str) -> bool:
    """判断主机名是否属于本地/回环/内网。IPv4 用 octet 解析，IPv6 走文本判定。"""
    if not host:
        return False
    h = host.lower().strip("[]")
    if h in _LOOPBACK_HOSTS:
        return True
    if h == "127.0.0.1" or h.startswith("127."):
        return True
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        try:
            o = [int(p) for p in parts]
            if o[0] == 10:
                return True
            if o[0] == 192 and o[1] == 168:
                return True
            if o[0] == 172 and 16 <= o[1] <= 31:
                return True
            if o[0] == 169 and o[1] == 254:
                return True
        except Exception:
            return False
    return False


def _normalize_parse_url(u: str) -> str:
    """规范化解析 URL 用于去重：去 scheme、host 小写、剥末尾斜杠、剥 query/fragment。
    内置 type 3 占位（"Demo"/"Web"）按字面保留大小写一致。"""
    if not isinstance(u, str):
        return ""
    u = u.strip()
    if u in ("Demo", "Web"):
        return u  # TVBox type 3 内置功能占位
    if "://" in u:
        u = u.split("://", 1)[1]
    u = u.split("?", 1)[0].split("#", 1)[0]
    u = u.rstrip("/")
    # host 小写，路径保持原样
    if "/" in u:
        host, _, path = u.partition("/")
        return f"{host.lower()}/{path}"
    return u.lower()


def _coerce_parse_type(t) -> int | None:
    """接受 int / 数字字符串；其余返回 None（视为无效）。"""
    if isinstance(t, int):
        return t
    if isinstance(t, str):
        s = t.strip()
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            try:
                return int(s)
            except Exception:
                return None
    return None


def clean_parses(parses: list, *, do_probe: bool = True, probe_timeout: float = 4.0) -> tuple:
    """解析池清洗：返回 (cleaned_parses, stats)。

    清洗步骤：
    1) 结构校验：非 dict / 缺 name / 缺 url → 剔除；type 数字字符串 → int 保留；
       type 不在 {0,1,2,3,4} 或为 None 且 URL 是占位 → 剔除。
    2) 私有/回环主机剔除（localhost / 127.* / 10.* / 192.168.* / 172.16-31.* / 169.254.*）。
    3) URL 规范化去重（scheme-insensitive、host-lowercase、no trailing slash）：
       同一规范化 URL 保留第一条。
    4) 可选 TCP 主机探活（do_probe=True 时）：仅对 type 0/1/2 且 URL 非占位者做 DNS 解析 + TCP 握手，
       不可达主机 → 剔除。安全阀：若剔除率 > 80% 视为网络故障，回退为「仅做 1-3 步」
       （保护沙箱/受限环境下不会把整个解析池清空）。

    stats dict 字段：before / after / dropped_invalid / dropped_private / dropped_duplicate /
    dropped_unreachable / probe_alive / probe_dead / safety_valve_triggered
    """
    stats = {
        "before": len(parses),
        "after": 0,
        "dropped_invalid": 0,
        "dropped_private": 0,
        "dropped_duplicate": 0,
        "dropped_unreachable": 0,
        "probe_alive": 0,
        "probe_dead": 0,
        "safety_valve_triggered": False,
        "do_probe": bool(do_probe),
    }

    step1: list = []
    for p in parses:
        if not isinstance(p, dict):
            stats["dropped_invalid"] += 1
            continue
        name = p.get("name")
        url = p.get("url")
        if not isinstance(name, str) or not name:
            stats["dropped_invalid"] += 1
            continue
        if not isinstance(url, str) or not url:
            stats["dropped_invalid"] += 1
            continue
        # type 校正
        coerced = _coerce_parse_type(p.get("type"))
        if coerced is not None:
            new_p = dict(p)
            new_p["type"] = coerced
            if url in ("Demo", "Web"):
                new_p["type"] = 3
            step1.append(new_p)
        elif url in ("Demo", "Web"):
            # 占位 url 缺 type → 补 type=3
            new_p = dict(p)
            new_p["type"] = 3
            step1.append(new_p)
        else:
            stats["dropped_invalid"] += 1
            continue

    step2: list = []
    for p in step1:
        url = p["url"]
        if url in ("Demo", "Web"):
            step2.append(p)
            continue
        # 解析主机
        host = ""
        try:
            if "://" in url:
                tail = url.split("://", 1)[1]
            else:
                tail = url
            host = tail.split("/", 1)[0]
            host = host.split(":", 1)[0]
        except Exception:
            stats["dropped_invalid"] += 1
            continue
        if _is_private_host(host):
            stats["dropped_private"] += 1
            continue
        step2.append(p)

    step3: list = []
    seen_urls: set = set()
    for p in step2:
        key = _normalize_parse_url(p["url"])
        if key in seen_urls:
            stats["dropped_duplicate"] += 1
            continue
        seen_urls.add(key)
        step3.append(p)

    # 探活（可选）
    if do_probe and step3:
        probe_targets: list = []
        probe_idx: dict = {}
        for i, p in enumerate(step3):
            url = p["url"]
            if url in ("Demo", "Web"):
                continue
            if p.get("type") not in (0, 1, 2):
                continue
            host = ""
            port = 0
            try:
                tail = url.split("://", 1)[1] if "://" in url else url
                hp = tail.split("/", 1)[0]
                if ":" in hp:
                    host, port_s = hp.rsplit(":", 1)
                    port = int(port_s) if port_s.isdigit() else 0
                else:
                    host = hp
            except Exception:
                continue
            if not host or _is_private_host(host):
                continue
            if not port:
                port = 443 if url.startswith("https") else 80
            probe_targets.append((i, host, port))

        alive_idx: set = set()
        if probe_targets:
            import concurrent.futures as _cf
            import socket as _socket
            from urllib.parse import urlparse as _urlparse
            def _probe(arg):
                i, host, port = arg
                try:
                    ip = _socket.gethostbyname(host)
                    s = _socket.create_connection((ip, port), timeout=probe_timeout)
                    s.close()
                    return i, True
                except Exception:
                    return i, False
            with _cf.ThreadPoolExecutor(min(16, len(probe_targets))) as ex:
                for i, ok in ex.map(_probe, probe_targets):
                    if ok:
                        alive_idx.add(i)
                    else:
                        stats["probe_dead"] += 1

        # 安全阀：剔除率 > 80% 视为网络故障，回退保留全部
        if probe_targets and stats["probe_dead"] / len(probe_targets) > 0.80:
            stats["safety_valve_triggered"] = True
            stats["probe_dead"] = 0
            stats["after"] = len(step3)
            return step3, stats

        step4 = []
        for i, p in enumerate(step3):
            if i in alive_idx or p["url"] in ("Demo", "Web") or p.get("type") not in (0, 1, 2):
                step4.append(p)
                if i in alive_idx:
                    stats["probe_alive"] += 1
            else:
                if p.get("type") in (0, 1, 2):
                    stats["dropped_unreachable"] += 1
        stats["after"] = len(step4)
        return step4, stats

    stats["after"] = len(step3)
    return step3, stats


# ==================== 依赖收集（jar / js / json 库文件） ====================
DEPS_DIR = "deps"
MANIFEST_PATH = os.path.join(DEPS_DIR, "manifest.json")
# deps 失败退避账本（2026-09-28）：死域/挂起链接不再每轮重建清单反复 25s 死撞。
# 上轮 2564 条挂起全是 gitcode.net/yydsys.top 等死域，每轮白花 ~28min。
# 失败按 2^fail_count 天指数退避（上限 14 天），累计 30 天标死不再试；
# 下载成功即清账本；DEP_FORCE_RETRY=1 强制全量重试。
DEP_BACKOFF_FILE = os.environ.get("DEP_BACKOFF_FILE", os.path.join("state", "dep_fail_backoff.json"))
DEP_BACKOFF_MAX_DAYS = 14
DEP_BACKOFF_DEAD_DAYS = 30
DEP_TIMEOUT = 8
DEP_TOTAL_BUDGET = 15  # 单依赖全链路(直连+镜像)总预算秒，防死URL拖慢整轮
DEP_MAX_BYTES = 8 * 1024 * 1024
# 任务3：总并发提到 16，同时按域名限速（默认同域最多 4 并发，避免 raw.githubusercontent.com 限流）
DEP_CONCURRENCY = int(os.environ.get("DEP_CONCURRENCY", "32"))
DEP_DOMAIN_CONCURRENCY = int(os.environ.get("DEP_DOMAIN_CONCURRENCY", "4"))
_DEP_DOMAIN_LOCK = threading.Lock()
_DEP_DOMAIN_SEMAPHORES = {}


def _domain_semaphore(url: str) -> "threading.Semaphore":
    """按 URL host 的信号量：GitHub 系域名并发48，其他域名并发24。
    依赖文件小（平均<1MB），CDN 可扛高并发；过低限速会导致 2561 依赖下载耗时>1h。"""
    import urllib.parse
    host = (urllib.parse.urlparse(url).netloc or "default").lower()
    with _DEP_DOMAIN_LOCK:
        sem = _DEP_DOMAIN_SEMAPHORES.get(host)
        if sem is None:
            _is_gh = any(h in host for h in ("github.com", "githubusercontent.com", "github.io"))
            sem = threading.Semaphore(8 if _is_gh else 4)
            _DEP_DOMAIN_SEMAPHORES[host] = sem
        return sem
# 沙箱/CI 网络受限时可跳过站点验活或强制用缓存
SKIP_SITE_TEST = os.environ.get("SKIP_SITE_TEST", "0") == "1"
SKIP_REFRESH = os.environ.get("SKIP_REFRESH", "0") == "1"

# ---- 输入层原始源镜像（raw 落库 + 每日变化检测 + 上游删除保护，2026-09-27 落库改造）----
# RAW_VOD_VERIFY：点播依赖的每日上游验证模式——
#   on-change（默认）：仅当本轮有上游原始文件变化时才逐个验证当前配置引用的依赖；
#   always：每轮全量验证；off：不主动验证（拉取失败时仍走 raw-vod 删除保护回退）。
# 依据：上游配置不变 ⇒ 依赖集合与内容不变，可整组跳过（变化驱动重跑）。
RAW_VOD_VERIFY = os.environ.get("RAW_VOD_VERIFY", "on-change")
FORCE_FULL_RUN = os.environ.get("FORCE_FULL_RUN", "0") == "1"  # 置 1 忽略「无变化跳过聚合」门控
RAW_VOD_VERIFY_ACTIVE = False   # main() 运行时置位，collect_and_rewrite_deps 据此决定是否逐依赖验证

_IDNA_CACHE = {}


def _idna_host(host: str) -> str:
    """中文域名手动 punycode（urllib 对部分中文域名内置 idna 会抛错）。"""
    if host.isascii():
        return host
    if host in _IDNA_CACHE:
        return _IDNA_CACHE[host]
    labels = []
    for lab in host.split("."):
        if lab.isascii():
            labels.append(lab)
        else:
            try:
                labels.append("xn--" + lab.encode("punycode").decode())
            except Exception:
                labels.append(lab)
    out = ".".join(labels)
    _IDNA_CACHE[host] = out
    return out


def _split_gh_prefix(url: str):
    """剥离 GitHub 代理前缀（ghproxy.net/、ghp.ci/、ghfast.top/…）归一成内层裸 URL。

    返回 (inner_url, had_prefix)。层层剥离（应对「前缀套前缀」的脏配置），
    以 GH_MIRRORS 已知前缀 + 常见老镜像名判定停止。"""
    known = [m.rstrip("/") for m in GH_MIRRORS]
    known.append("https://ghproxy.com")  # 老镜像名（不在当前链里也见过）
    inner = url
    changed = True
    while changed:
        changed = False
        for pre in known:
            p = pre.rstrip("/")
            if inner.startswith(p + "/"):
                inner = inner[len(p) + 1:]
                changed = True
                break
    return inner, url != inner


def dep_lenient_json(text: str) -> bool:
    if text.startswith("\ufeff"):
        text = text[1:]
    # 2026-09-21 点播+容错线：改用主管线同款状态机清洗（去 // 行注释（含行内）、
    # /* */ 块注释、尾随逗号，且不误伤字符串内双斜杠）。原正则只剥「整行 //」，
    # 实测 franksun1211/TVBOX 的 CKS2026.json（/* */ 块注释）与
    # victor1616888/TVBOX-Q 的 tvbox.json（值后行内 // 注释）都会解析失败。
    text = strip_comments_and_clean(text)
    try:
        json.loads(text)
        return True
    except Exception:
        return False


def dep_classify(kind_hint: str, content: bytes) -> str:
    """按内容判定依赖类型: jar / js / json / unknown（伪装扩展名靠内容识别）。"""
    if content[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "jar"
    if content[:3] == b"dex\n":
        return "jar"
    if content[:2] == b"\x1f\x8b":
        return "data"  # gzip 数据文件（如 pikpakclass.db.gz 分享码库）
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return "unknown"
    low = text[:2000].lower()
    if "<html" in low or "<!doctype" in low:
        return "unknown"
    if kind_hint == "json":
        try:
            json.loads(text)
            return "json"
        except Exception:
            return "json" if dep_lenient_json(text) else "data"
    if re.search(r"\b(function|var|let|const|import|export|require)\b", text[:4000]) or "=>" in text[:1000]:
        return "js"
    return "data"  # 其余可解码纯文本（TSV 分享码库等）视为数据文件


def dep_download(url: str):
    """原 URL → gh 镜像链轮换兜底。返回 (bytes, channel) 或 (None, err)。

    2026-09-28 代理前缀归一化：上游配置里很多 github 链接已经挂了镜像前缀
    （ghp.ci / ghfast.top / ghproxy.net 等）。旧实现只查 "ghproxy" 字面量，
    其余前缀的链接会被再叠一层镜像（双前缀低成功率，失败还要多耗 2 次 25s）。
    现在统一剥前缀归一成裸 github URL，再按 mirror_probe 实测择优序套当前最优镜像链：
    已挂前缀 → 直接用最优前缀替换（避免"老前缀+双前缀"）；裸链接 → 直连优先、失败走镜像链。"""
    import urllib.parse
    # 非 ASCII 域名（如中文域名）punycode 化：urllib 发请求头走 latin-1，unicode host 必挂 UnicodeEncodeError
    p = urllib.parse.urlsplit(url)
    if p.hostname and not p.hostname.isascii():
        host = _idna_host(p.hostname)
        netloc = f"{host}:{p.port}" if p.port else host
        url = urllib.parse.urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
    _inner, _had_prefix = _split_gh_prefix(url)
    attempts = [_inner]
    if "github" in _inner.lower():
        if _had_prefix:
            # 已挂前缀：用当前镜像链择优序替换前缀（首位=mirror_probe 实测最快），不双叠
            attempts.extend(m + _inner for m in GH_MIRRORS[:2])
        elif "ghproxy" not in _inner:
            # 裸 github 链接：直连优先（能直连就不走代理），失败走镜像链（最多2个镜像，避免死URL耗时5min+）
            attempts.extend(m + _inner for m in GH_MIRRORS[:2])
    attempts = [
        urllib.parse.quote(u, safe="%/:=&?~#+!$,;'@()*[]|") if not u.isascii() else u
        for u in attempts
    ]
    last = ""
    for i, u in enumerate(attempts):
        # P1-3：失败类型分级重试
        _retries = 0
        _max_retry = 0  # 不重试，快速失败
        while _retries <= _max_retry:
            try:
                status, data, _ = http_get(u, DEP_TIMEOUT, DEP_MAX_BYTES)
                if status == 200 and data:
                    return data, ("direct" if i == 0 else "mirror")
                if status == 404:
                    # 404 直接失败，不浪费镜像请求
                    last = "HTTP 404"
                    return None, last
                if status == 403:
                    # 403 换 UA 重试 1 次
                    if _retries == 0:
                        _retries += 1
                        time.sleep(0.5)
                        continue
                    last = "HTTP 403"
                    break
                if 500 <= status < 600:
                    # 5xx 仅直连URL重试1次
                    if i == 0 and _retries < 1:
                        _retries += 1
                        time.sleep(0.5)
                        continue
                    last = f"HTTP {status}"
                    break
                last = f"HTTP {status}"
                break
            except urllib.error.HTTPError as he:
                if he.code == 404:
                    last = "HTTP 404"
                    return None, last
                if he.code == 403 and _retries == 0:
                    _retries += 1
                    time.sleep(0.5)
                    continue
                if 500 <= he.code < 600 and i == 0 and _retries < 1:
                    _retries += 1
                    time.sleep(0.5)
                    continue
                last = f"HTTP {he.code}"
                break
            except Exception as e:  # noqa: BLE001
                # 超时/连接错误：不重试（超时通常不是瞬时故障，重试只会浪费30s），直接返回
                # 死URL耗时从 30s+30s重试=60s 降到 30s，吞吐翻倍，确保CI在1h内完成
                if "timed out" in str(e).lower() or "timeout" in str(e).lower() or "connection" in str(e).lower():
                    last = f"{type(e).__name__}: {e}"[:120]
                    return None, last
                last = f"{type(e).__name__}: {e}"[:120]
                break
    return None, last


def is_file_ref(v: str):
    """识别配置字符串里的依赖文件引用。返回 ('rel'|'abs', path) 或 None。"""
    v = v.strip()
    if not v or "{name}" in v or "{cateId}" in v or "{catePg}" in v:
        return None
    base = v.split(";")[0]
    if "$$$" in base:
        return None
    if base.startswith("./") or base.startswith("../") or base.startswith("/"):
        return ("rel", base)
    if re.match(r"^https?://", base):
        host = urllib.parse.urlparse(base).netloc
        if "127.0.0.1" in host or "localhost" in host:
            return None
        path = base.split("?")[0].lower()
        # 静态文件后缀：可下载入库。动态 API 端点（/api.php/provide/vod、/v1.vod 等）
        # 不以这些后缀结尾，天然不会被误收。
        if path.endswith((".js", ".jar", ".zip", ".php", ".json", ".py",
                           ".css", ".txt", ".m3u", ".m3u8", ".xml", ".html",
                           # P0-3：补图片后缀（wallpaper 等图片依赖落库）
                           ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):
            return ("abs", base)
    return None


def _is_repo_live_url(url: str) -> bool:
    """P0-1：判断 live url 是否指向本仓库产物（lives/ 目录）——这些是每日生成的产物自身，
    不应作为外部依赖下载。相对路径(./)、绝对路径(/)、本仓库 REPO_RAW 链接均视为本仓库。"""
    if not isinstance(url, str):
        return True
    if url.startswith("./") or url.startswith("/"):
        return True
    if REPO_RAW in url:
        return True
    return False


def _sanitize_seg(seg: str) -> str:
    """兼容包装：委托 pathutil.safe_segment（全仓库唯一事实源）。"""
    return pathutil.safe_segment(seg)


def dep_local_path(origin: str, url: str) -> str:
    if origin == "remote":
        name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or ""
        if not name or len(name) > 80:
            name = hashlib.md5(url.encode()).hexdigest()[:12]
        return pathutil.check_path_length(f"{DEPS_DIR}/remote/{_sanitize_seg(name)}")
    u = urllib.parse.urlparse(url)
    # 剥离镜像前缀：https://<镜像域名>/https://<真实URL>
    # urlparse 后 path 以 /https:/ 或 /http:/ 开头说明是镜像前缀形式，
    # 此时 netloc 是镜像域名，path 第一段变成 https:（带冒号，Windows 非法）。
    # 提取内嵌真实 URL 重新解析，使 netloc 还原为真实域名（如 raw.githubusercontent.com），
    # 后续才能正确剥离 owner/repo/branch。
    p = u.path
    if p.startswith("/https:/") or p.startswith("/http:/"):
        inner = p.lstrip("/")
        if inner.startswith("https:/") and not inner.startswith("https://"):
            inner = "https://" + inner[len("https:/"):]
        elif inner.startswith("http:/") and not inner.startswith("http://"):
            inner = "http://" + inner[len("http:/"):]
        u = urllib.parse.urlparse(inner)
    segs = u.path.lstrip("/").split("/")
    if u.netloc == "raw.githubusercontent.com" and len(segs) > 3:
        segs = segs[3:]  # 剥离 owner/repo/branch，路径与仓库已入库布局一致
    segs = [_sanitize_seg(s) for s in segs if s not in ("", ".")]
    path = "/".join(segs)
    if not path:
        path = hashlib.md5(url.encode()).hexdigest()[:12]
    result = f"{DEPS_DIR}/{_sanitize_seg(origin)}/{path}"
    return pathutil.check_path_length(result)


# ---- codeload 整仓 tarball 兜底（2026-09-29）----
# 依赖收集是「每文件 × 镜像轮换」，同一个仓的几十个文件就是几十次握手；raw 被掐时成片
# 失败（本地 deps 收集 878/2811 的根因之一）。实测 codeload.github.com 的整仓 tar.gz
# 可直连（200 / 0.58s），于是一仓一次取回源码树，只抽需要的那几个文件。
# 三条护栏：整仓体积上限（防 tar 拉爆内存/磁盘）、需要文件数阈值（少于阈值不划算）、
# 整轮时间预算（防兜底路反过来把合并拖长）。
DEPS_TARBALL_BACKFILL = os.environ.get("DEPS_TARBALL_BACKFILL", "1") == "1"
DEPS_TARBALL_MIN_FILES = int(os.environ.get("DEPS_TARBALL_MIN_FILES", "3"))
DEPS_TARBALL_MAX_REPO_KB = int(os.environ.get("DEPS_TARBALL_MAX_REPO_KB", "30000"))
DEPS_TARBALL_MAX_BYTES = int(os.environ.get("DEPS_TARBALL_MAX_BYTES", "60000000"))
DEPS_TARBALL_TIMEOUT = int(os.environ.get("DEPS_TARBALL_TIMEOUT", "60"))
DEPS_TARBALL_REPOS_PER_ROUND = int(os.environ.get("DEPS_TARBALL_REPOS_PER_ROUND", "40"))
DEPS_TARBALL_BUDGET_SEC = float(os.environ.get("DEPS_TARBALL_BUDGET_SEC", "300"))


def _safe_rel_path(path: str) -> bool:
    """仓库内相对路径白名单：空、绝对、含 `..` 或 NUL 的一律拒。

    上游配置里的 URL 是攻击者可控输入，而两条兜底路都要拿「仓库内路径」去拼文件系统
    路径读字节（稀疏克隆是 os.path.join(workdir, *path.split('/'))）。写盘侧
    dep_local_path 有 safe_segment 把 `..` 变 `_` 兜底，但**读取侧没有**——不在这
    里挡住，一条 `.../main/../../../../etc/passwd` 就能把本地任意文件读进内容再发布出去。
    """
    if not path or path.startswith(("/", "\\")) or "\x00" in path:
        return False
    segs = path.replace("\\", "/").split("/")
    if any(seg in ("", "..") for seg in segs):
        return False
    # 再按解码后的形态查一遍（%2e%2e 之类）：正常的依赖路径不需要百分号编码的点，
    # 出现就是有人在试探路径解析的边界，一律不收。
    dec = urllib.parse.unquote(path).replace("\\", "/").split("/")
    return not any(seg in ("", "..") for seg in dec)


def gh_repo_ref_of(url: str):
    """github/raw 链接 → (owner, repo, ref, 仓库内路径)；不可 tar 的形式返回 None。

    认三种写法：raw.githubusercontent.com/o/r/<ref>/<path>、github.com/o/r/raw/<ref>/<path>、
    github.com/o/r/blob/<ref>/<path>。release/download 的资产不在源码树里，一律不认；
    镜像前缀先剥掉再判。路径不过 _safe_rel_path 的也直接拒。"""
    inner, _had = _split_gh_prefix(url)
    u = urllib.parse.urlparse(inner)
    host = (u.netloc or "").lower()
    segs = [s for s in u.path.split("/") if s]
    if host == "raw.githubusercontent.com":
        if len(segs) < 4:
            return None
        owner, repo, ref, path = segs[0], segs[1], segs[2], "/".join(segs[3:])
    elif host in ("github.com", "www.github.com"):
        if len(segs) >= 5 and segs[2] in ("raw", "blob"):
            owner, repo, ref, path = segs[0], segs[1], segs[3], "/".join(segs[4:])
        else:
            return None
    else:
        return None
    if not all((owner, repo, ref, path)) or not _safe_rel_path(path):
        return None
    return owner, repo, ref, path


def gh_repo_size_kb(owner: str, repo: str):
    """api.github.com 取仓库体积（KB）。api 本机实测可直连；取不到返回 None（未知不放行）。"""
    try:
        status, data, _ms = http_get(
            f"https://api.github.com/repos/{owner}/{repo}", 8, 200_000,
            extra_headers={"Accept": "application/vnd.github+json"})
        if status != 200 or not data:
            return None
        return int((json.loads(data.decode("utf-8", "ignore")) or {}).get("size") or 0)
    except Exception:  # noqa: BLE001 —— 兜底路的任何失败都不许影响主流程
        return None


def fetch_repo_tarball(owner: str, repo: str, ref: str):
    """整仓 tar.gz：先按分支试 refs/heads，404 再按标签试 refs/tags。"""
    for kind in ("heads", "tags"):
        try:
            status, data, _ms = http_get(
                f"https://codeload.github.com/{owner}/{repo}/tar.gz/refs/{kind}/{ref}",
                DEPS_TARBALL_TIMEOUT, DEPS_TARBALL_MAX_BYTES)
        except Exception:  # noqa: BLE001
            continue
        if status == 200 and data:
            return data
    return None


def tarball_take_files(tar_bytes: bytes, wanted: set):
    """从 tar 里按「仓库内路径」白名单精确取文件 → {path: bytes}。

    codeload 的 tar 顶层是 `<repo>-<sha>/`，剥首段才是仓库内路径。只读白名单内的成员、
    落盘目标由调用方给定（不用成员名拼路径），所以没有 zip-slip 面。单文件超
    DEP_MAX_BYTES 的与主路一样不收。"""
    import io
    import tarfile
    out = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                parts = m.name.split("/", 1)
                rel = parts[1] if len(parts) == 2 else m.name
                if rel not in wanted or not _safe_rel_path(rel):
                    continue
                fobj = tf.extractfile(m)
                if fobj is None:
                    continue
                data = fobj.read(DEP_MAX_BYTES + 1)
                if len(data) <= DEP_MAX_BYTES:
                    out[rel] = data
    except Exception:  # noqa: BLE001
        return {}
    return out


def deps_tarball_pick(needs):
    """needs=[(kind_hint, url, origin)]（主路与 manifest 缓存都没补上的）→
    ({(origin, url): bytes}, stats)。按仓聚合、体积与阈值过滤、时间预算内尽力而为。"""
    groups = {}
    for kind_hint, url, origin in needs:
        g = gh_repo_ref_of(url)
        if not g:
            continue
        owner, repo, ref, path = g
        groups.setdefault((owner, repo, ref), []).append((origin, url, path))
    stats = {"groups": len(groups), "repos_tried": 0, "repos_ok": 0, "files": 0,
             "below_threshold": 0, "too_big": 0, "size_unknown": 0, "failed": 0,
             "budget_cut": 0}
    got = {}
    t0 = time.time()
    # 缺得越多的仓越划算，按文件数降序
    ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    for (owner, repo, ref), items in ordered[:DEPS_TARBALL_REPOS_PER_ROUND]:
        if len(items) < DEPS_TARBALL_MIN_FILES:
            stats["below_threshold"] += len(items)
            continue
        if time.time() - t0 > DEPS_TARBALL_BUDGET_SEC:
            stats["budget_cut"] += 1
            break
        kb = gh_repo_size_kb(owner, repo)
        if kb is None:
            stats["size_unknown"] += 1
            continue
        if kb > DEPS_TARBALL_MAX_REPO_KB:
            stats["too_big"] += len(items)
            continue
        stats["repos_tried"] += 1
        tar = fetch_repo_tarball(owner, repo, ref)
        if not tar:
            stats["failed"] += 1
            continue
        data = tarball_take_files(tar, {p for _o, _u, p in items})
        if not data:
            stats["failed"] += 1
            continue
        stats["repos_ok"] += 1
        for origin, url, path in items:
            if path in data:
                got[(origin, url)] = data[path]
                stats["files"] += 1
        del tar, data
    return got, stats


# ---- 稀疏浅克隆兜底（2026-09-29，SSH 传输）----
# raw 被掐时最狠的一类：同一个仓缺几十上百个依赖（实测 13998394872/TVBox 缺 269 个）。
# 逐文件走镜像要么超时要么 404，整仓 tarball 又被体积护栏挡住（该仓 248MB）。
# 本机实测 SSH 全通，于是按 `--filter=blob:none --depth 1 --no-checkout` + sparse-checkout
# 只取需要的那些 blob：**269 个路径 10.8 秒、只落 256 个文件 9.5MB**，且不经任何第三方。
DEPS_GIT_BACKFILL = os.environ.get("DEPS_GIT_BACKFILL", "1") == "1"
DEPS_GIT_TRANSPORT = os.environ.get("DEPS_GIT_TRANSPORT", "ssh").strip().lower()
DEPS_GIT_MIN_FILES = int(os.environ.get("DEPS_GIT_MIN_FILES", "2"))
DEPS_GIT_BUDGET_SEC = float(os.environ.get("DEPS_GIT_BUDGET_SEC", "420"))
DEPS_GIT_TIMEOUT = int(os.environ.get("DEPS_GIT_TIMEOUT", "120"))
DEPS_GIT_REPOS_PER_ROUND = int(os.environ.get("DEPS_GIT_REPOS_PER_ROUND", "25"))
_git_probe_cache: dict = {}


def _git_run(args, timeout):
    """跑 git，返回 CompletedProcess 或 None（超时/异常/git 缺失都算 None）。
    GIT_TERMINAL_PROMPT=0 必须有：私有或拼错的仓库名会弹凭据交互，把 shell 卡死。"""
    import subprocess
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_FLUSH="1")
    try:
        return subprocess.run(["git", *args], capture_output=True, timeout=timeout, env=env)
    except Exception:  # noqa: BLE001
        return None


def _git_repo_url(owner: str, repo: str) -> str:
    if DEPS_GIT_TRANSPORT == "https":
        return f"https://github.com/{owner}/{repo}.git"
    return f"git@github.com:{owner}/{repo}.git"


def gh_repo_git_reachable(owner: str, repo: str) -> bool:
    """一次性探测该仓能否用 git 直连（SSH/HTTPS 按 DEPS_GIT_TRANSPORT）。结果按仓缓存。"""
    key = (owner, repo)
    if key in _git_probe_cache:
        return _git_probe_cache[key]
    r = _git_run(["ls-remote", "--exit-code", "-q", _git_repo_url(owner, repo), "HEAD"], 15)
    ok = bool(r and r.returncode == 0)
    _git_probe_cache[key] = ok
    return ok


def deps_git_plan(needs):
    """needs=[(kind_hint, url, origin)] → {(owner, repo, ref): [(origin, url, path)]}，
    只保留可 git 直取且同仓文件数达阈值的组（按文件数降序，最划算的先做）。"""
    groups: dict = {}
    for _kind_hint, url, origin in needs:
        g = gh_repo_ref_of(url)
        if not g:
            continue
        owner, repo, ref, path = g
        groups.setdefault((owner, repo, ref), []).append((origin, url, path))
    out = {k: v for k, v in groups.items() if len(v) >= DEPS_GIT_MIN_FILES}
    return dict(sorted(out.items(), key=lambda kv: -len(kv[1])))


def deps_git_backfill(needs):
    """按仓稀疏浅克隆，取回 needs 里那些文件。返回 ({(origin, url): bytes}, stats)。

    全程在系统临时目录里做，finally 必删；不落地到 deps/（由调用方决定写哪），
    只读我们白名单里的路径，所以没有路径穿越面。"""
    import shutil
    import tempfile
    stats = {"groups": 0, "repos_ok": 0, "repos_failed": 0, "files": 0,
             "probed_unreachable": 0, "budget_cut": 0}
    got: dict = {}
    plan = deps_git_plan(needs)
    stats["groups"] = len(plan)
    if not plan:
        return got, stats
    t0 = time.time()
    for (owner, repo, ref), items in list(plan.items())[:DEPS_GIT_REPOS_PER_ROUND]:
        if time.time() - t0 > DEPS_GIT_BUDGET_SEC:
            stats["budget_cut"] += 1
            break
        if not gh_repo_git_reachable(owner, repo):
            stats["probed_unreachable"] += 1
            continue
        workdir = tempfile.mkdtemp(prefix="tvbox-dep-git-")
        try:
            url_git = _git_repo_url(owner, repo)
            r = _git_run(["clone", "--filter=blob:none", "--depth", "1", "--no-checkout",
                          "--quiet", "-b", ref, url_git, workdir], DEPS_GIT_TIMEOUT)
            if r is None or r.returncode != 0:
                # -b <ref> 失败：ref 可能是标签或已删分支 → 退回默认分支再试一次
                shutil.rmtree(workdir, ignore_errors=True)
                os.makedirs(workdir, exist_ok=True)
                r = _git_run(["clone", "--filter=blob:none", "--depth", "1",
                              "--no-checkout", "--quiet", url_git, workdir],
                             DEPS_GIT_TIMEOUT)
                if r is None or r.returncode != 0:
                    stats["repos_failed"] += 1
                    continue
            paths = [p for _o, _u, p in items if _safe_rel_path(p)]
            if not paths:
                stats["repos_failed"] += 1
                continue
            if _git_run(["-C", workdir, "sparse-checkout", "init", "--no-cone"], 30) is None:
                stats["repos_failed"] += 1
                continue
            r = _git_run(["-C", workdir, "sparse-checkout", "set"] + paths, DEPS_GIT_TIMEOUT)
            if r is None or r.returncode != 0:
                stats["repos_failed"] += 1
                continue
            r = _git_run(["-C", workdir, "checkout"], DEPS_GIT_TIMEOUT)
            if r is None or r.returncode != 0:
                stats["repos_failed"] += 1
                continue
            n = 0
            for origin, url, path in items:
                if not _safe_rel_path(path):
                    continue      # 读取侧自己也要再过一遍，不依赖上游解析
                fp = os.path.join(workdir, *path.split("/"))
                if not os.path.isfile(fp):
                    continue          # 上游树里没有这个路径（多为作者已删）
                try:
                    if os.path.getsize(fp) > DEP_MAX_BYTES:
                        continue
                    with open(fp, "rb") as fh:
                        data = fh.read()
                except OSError:
                    continue
                got[(origin, url)] = data
                n += 1
            if n:
                stats["repos_ok"] += 1
                stats["files"] += n
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    return got, stats


def load_manifest() -> dict:
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def dep_backoff_load() -> dict:
    """deps 失败退避账本：{rkey: {fail_count, next_retry_at, dead, last_error}}。"""
    try:
        with open(DEP_BACKOFF_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def dep_backoff_save(d: dict) -> None:
    """账本批量落盘（原子 replace，防并发读写冲突）。"""
    tmp = DEP_BACKOFF_FILE + ".tmp"
    os.makedirs(os.path.dirname(DEP_BACKOFF_FILE) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DEP_BACKOFF_FILE)


def dep_backoff_skip_in(d: dict, rkey: str, now_naive: datetime) -> bool:
    """纯 dict 判定：退避窗口内/已标死 → 跳过。DEP_FORCE_RETRY=1 不跳过。
    累计失败天数（now - first_fail_at）达 30 天 → 视同永久死域跳过（读端动态复查，
    不依赖写入时刻的 dead 字段——老账本条目也能自动转死）。"""
    if os.environ.get("DEP_FORCE_RETRY") == "1":
        return False
    ent = d.get(rkey)
    if not ent:
        return False
    if ent.get("dead"):
        return True
    try:
        span = (now_naive - datetime.strptime(ent.get("first_fail_at") or "", "%Y-%m-%d %H:%M:%S")).days
    except ValueError:
        span = 0
    if span >= DEP_BACKOFF_DEAD_DAYS:
        return True
    nra = ent.get("next_retry_at")
    if not nra:
        return False
    try:
        return datetime.strptime(nra, "%Y-%m-%d %H:%M:%S") > now_naive
    except (ValueError, TypeError):
        return False


def dep_backoff_record_fail(d: dict, rkey: str, err: str, now_naive: datetime):
    """失败记账本（in-place 改 dict）：next_retry_at = now + 2^fc 天（上限 14）；累计 30 天标死。"""
    ent = d.get(rkey) or {"fail_count": 0,
                          "first_fail_at": now_naive.strftime("%Y-%m-%d %H:%M:%S")}
    fc = int(ent.get("fail_count", 0)) + 1
    try:
        span = (now_naive - datetime.strptime(ent.get("first_fail_at") or "", "%Y-%m-%d %H:%M:%S")).days
    except ValueError:
        span = 0
    ent.update({"fail_count": fc,
                "last_fail_at": now_naive.strftime("%Y-%m-%d %H:%M:%S"),
                "last_error": str(err)[:160],
                "next_retry_at": (now_naive + timedelta(days=min(2 ** fc, DEP_BACKOFF_MAX_DAYS))).strftime("%Y-%m-%d %H:%M:%S"),
                "dead": span >= DEP_BACKOFF_DEAD_DAYS})
    d[rkey] = ent


def dep_backoff_clear(d: dict, rkey: str) -> bool:
    """下载成功 → 清账本条目。返回是否真的删了。"""
    if d.pop(rkey, None) is not None:
        return True
    return False


def _spider_canon(ref, origin: str):
    """把 spider 值归一成绝对 URL，用于判断「是不是同一份包」。

    不能直接比字符串：全局 spider 在上一轮产出里已经被改写成 `./deps/xxx/jar/spider.jar`，
    而上游原始值写的是 `./jar/spider.jar` —— 字面不同、指向同一份包。
    """
    if not isinstance(ref, str) or not ref.strip():
        return None
    r = is_file_ref(ref.split(";md5;")[0])
    if not r:
        return None
    where, pathv = r
    if where == "abs":
        return pathv
    base = UPSTREAM_BASES.get(origin, "")
    return urllib.parse.urljoin(base, pathv) if base else None


def _global_spider_url(tvbox: dict, spider_origin: dict):
    """全局 spider 归一成绝对 URL，用于与各个上游的 spider 比「是不是同一份包」。

    两种来源都要能处理：
      1) 本次合并刚选定的值 —— 形如 `./jar/spider.jar`，用 spider_origin 的 base 拼；
      2) 上一轮产出里已被落库改写的值 —— 形如 `./deps/jar/spider_8955438d.jar`，
         这时不能再拿上游 base 去拼（会拼出不存在的路径），而应从 `deps/<上游>/` 反推上游。
    """
    sp = tvbox.get("spider")
    if not isinstance(sp, str) or not sp.strip():
        return None
    r = is_file_ref(sp.split(";md5;")[0])
    if not r:
        return None
    where, pathv = r
    if where == "abs":
        return pathv
    p = pathv.lstrip("./")
    if p.startswith("deps/"):
        rest = p[len("deps/"):]
        # 上游名里含 '/'（如 qist/jsm），取最长匹配的那个前缀
        for k in sorted(UPSTREAM_BASES, key=len, reverse=True):
            if rest.startswith(k + "/"):
                # 关键：剥掉 deps/<上游>/ 前缀还原成上游内的相对路径，再按上游 base 拼接。
                # 直接 urljoin(base, './deps/...') 会拼出一个上游根本不存在的路径。
                return _spider_canon("./" + rest[len(k) + 1:], k)
    if spider_origin:
        return _spider_canon(sp, spider_origin[0])
    return None


def assign_origin_spiders(tvbox: dict, site_origin_name: dict, upstream_spider: dict,
                          spider_origin: dict = None) -> dict:
    """让每个源用它「来源上游」声明的那份 spider jar。

    ---- 为什么必须这么做 ----
    每个上游配置都声明自己的顶层 spider，而且**各不相同**：
        qist/js、qist/0825  → ./jar/pg_upgraded.jar
        gao/js、nxppru/js   → ./jar/pg.jar
        cluntop/aa          → ./jar/pro.jar
        cluntop/wv          → ./jar/WvSpider.jar
        qist/0826、qist/fty → ./jar/fan.txt
        wex/newwex          → http://oss4liview.moji.com/...
    而合并只能保留一份全局 spider（先到先得）。凡是 `jar` 字段为空、走全局 spider 的源，
    就会被指向一个**不含它所需爬虫类**的包 —— 客户端加载爬虫时抛 ClassNotFoundException，
    这些源直接变成「坏的」。实测受影响 256 个爬虫类 / 359 个源，而它们在真实 TVBox 里本来是能用的。

    这跟「合并丢掉上游语义」是同一类问题：合并只留下了站点数据，丢掉了「这个源该配哪份运行时」。

    ---- 做法 ----
    给这些源的 `jar` 字段补上「它来源上游的那份 spider」原文，后续 collect_and_rewrite_deps 会
    按 origin 把它落库到 deps/<上游>/... 并改写成仓库内相对路径 + md5，与站点自带 jar 走同一条路。
    与全局 spider 指向同一份包的不写（省体积）。
    """
    if os.environ.get("ORIGIN_SPIDER", "1") != "1":
        return {"skipped": 1}

    g_url = _global_spider_url(tvbox, spider_origin)
    stats = {"assigned": 0, "same_as_global": 0, "origin_no_spider": 0, "no_origin": 0,
             "not_file_ref": 0, "conflicts": []}
    for s in tvbox.get("sites") or []:
        if not isinstance(s, dict) or s.get("jar"):
            continue                                  # 自带 jar 的源不动
        api = str(s.get("api") or "")
        if not (api.startswith("csp_") or api.startswith("./")):
            continue                                  # 只有 csp/js 爬虫源才吃 spider
        origin = site_origin_name.get(s.get("key"))
        if not origin:
            stats["no_origin"] += 1
            continue
        sp = upstream_spider.get(origin)
        if not isinstance(sp, str) or not sp:
            stats["origin_no_spider"] += 1
            continue
        sp_url = _spider_canon(sp, origin)
        if not sp_url:
            stats["not_file_ref"] += 1
            continue
        if g_url and sp_url == g_url:
            stats["same_as_global"] += 1
            continue
        # P1-5：解析 ;md5; 后缀与全局 spider md5 比对，不一致记 conflicts（best-effort）
        sp_md5 = sp.split(";md5;")[1] if ";md5;" in sp else ""
        g_md5 = (tvbox.get("spider") or "").split(";md5;")[1] if ";md5;" in (tvbox.get("spider") or "") else ""
        if sp_md5 and g_md5 and sp_md5 != g_md5:
            stats["conflicts"].append({"key": s.get("key"), "origin": origin,
                                       "sp_md5": sp_md5[:12], "global_md5": g_md5[:12]})
        s["jar"] = sp
        stats["assigned"] += 1
    return stats


def prune_unlocalized_jars(tvbox: dict) -> dict:
    """安全网：把没能落库的 per-site `jar` 撤掉，回退成走全局 spider。

    场景：assign_origin_spiders 给某源补了上游的 spider（如 `./jar/pro.jar`），但该包下载失败 /
    被自动黑名单拦下 → collect_and_rewrite_deps 会「保留原值」，于是产物里留下一个**相对路径**。
    客户端拿到 `./jar/pro.jar` 会按配置所在 URL 去解析，多半 404 —— 比不写更糟。
    所以：确认本地没有对应文件的一律撤掉，宁可回退到全局 spider。
    """
    stats = {"checked": 0, "pruned": 0}
    for s in tvbox.get("sites") or []:
        if not isinstance(s, dict) or not s.get("jar"):
            continue
        stats["checked"] += 1
        r = is_file_ref(str(s["jar"]).split(";md5;")[0])
        if not r or r[0] == "abs":
            continue                                   # 绝对 URL 与本地已改写路径都不动
        local = r[1].lstrip("./").replace("/", os.sep)
        if not os.path.exists(local):
            s.pop("jar", None)
            stats["pruned"] += 1
    if stats["pruned"]:
        print(f"    撤回未能落库的 jar 引用：{stats['pruned']} 个（回退为全局 spider）", flush=True)
    return stats


def collect_and_rewrite_deps(tvbox: dict, site_origin: dict, spider_origin: dict):
    """收集 tvbox 配置中的 jar/js/json 依赖到 deps/ 并把引用改写为仓库相对路径。
    site_origin: key -> origin 名；spider_origin: (origin 名, base url)
    返回统计 dict；同时更新 deps/json/manifest.json。"""
    import urllib.parse

    manifest = load_manifest()
    # deps 失败退避账本（2026-09-28）：一次加载、全轮共享；死域链接 2^N 天退避，
    # 退避窗口内不再 25s 死撞（上轮 2564 条挂起白花 ~28min 的根因修复）。
    backoff = dep_backoff_load()
    _backoff_dirty: set = set()
    _now_naive = datetime.now()
    now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S +08:00")

    def _dep_download_throttled(u):
        sem = _domain_semaphore(u)
        sem.acquire()
        try:
            # 线程级硬超时：覆盖DNS解析挂起（socket超时对DNS不生效）
            _res = [None]
            def _do():
                try:
                    _res[0] = dep_download(u)
                except Exception as _e:
                    _res[0] = (None, f"{type(_e).__name__}: {str(_e)[:100]}")
            _t = threading.Thread(target=_do, daemon=True)
            _t.start()
            _t.join(timeout=DEP_TOTAL_BUDGET)  # 总超时25s，覆盖DNS+连接+读取+重试
            if _t.is_alive():
                return None, f"download hang (DNS?) after {DEP_TOTAL_BUDGET}s"
            return _res[0]
        finally:
            sem.release()

    # ---- 1. 生成 (origin, url) 待收集清单 ----
    entries = []  # (kind_hint, url, origin)

    def add_ref(kind_hint: str, ref: str, origin: str, base: str):
        r = is_file_ref(ref)
        if not r:
            return
        where, pathv = r
        url = urllib.parse.urljoin(base, pathv) if where == "rel" else pathv
        e = (kind_hint, url, origin)
        if e not in entries:
            entries.append(e)

    if isinstance(tvbox.get("spider"), str) and spider_origin:
        add_ref("jar", tvbox["spider"].split(";md5;")[0], spider_origin[0], spider_origin[1])
    for s in tvbox.get("sites", []):
        origin = site_origin.get(s.get("key"))
        if not origin:
            continue
        base = UPSTREAM_BASES.get(origin, "")
        if not base:
            continue
        # api 也纳管：规则 js 常写在 api 字段（如 cat 系列 ./cat/MyCatBookan.js），
        # 与 jar/ext 同等落库，否则产物里留悬空相对路径、客户端 404。
        # is_file_ref 只认 .jar/.js/.json/.zip/.css/.txt 等文件后缀，
        # type 1 的 HTTP 端点（/api.php/provide/vod）不以文件后缀结尾，天然不会被误收。
        for field in ("jar", "ext", "api"):
            v = s.get(field)
            if isinstance(v, str):
                hint = "jar" if field == "jar" else ("js" if v.lower().split("?")[0].endswith(".js") else "json")
                for seg in (v.split("$$$") if "$$$" in v else [v]):
                    add_ref(hint, seg, origin, base)
            elif isinstance(v, dict):
                for v2 in v.values():
                    if isinstance(v2, str):
                        for seg in (v2.split("$$$") if "$$$" in v2 else [v2]):
                            add_ref("json", seg, origin, base)

    # ---- P0-1：全局字段 wallpaper/parses/lives 的静态依赖收集 ----
    # 这些全局字段来自第一个成功的 tvbox 上游（merged/spider_origin_info），
    # origin/base 用全局 spider 的来源上游（与全局 spider 同源）。
    _g_origin = spider_origin[0] if spider_origin else "remote"
    _g_base = spider_origin[1] if spider_origin else ""
    if _g_base:
        # wallpaper 单字段（图片 URL）
        _wp = tvbox.get("wallpaper")
        if isinstance(_wp, str):
            add_ref("image", _wp, _g_origin, _g_base)
        # parses 每个 dict 的 url（多为解析 API 端点，is_file_ref 后缀白名单天然过滤）
        for _p in tvbox.get("parses", []):
            if isinstance(_p, dict):
                _pu = _p.get("url") or _p.get("parse")
                if isinstance(_pu, str):
                    add_ref("parse", _pu, _g_origin, _g_base)
        # lives：只收集外部 m3u/txt 依赖，跳过指向本仓库 lives/ 的条目
        #（P0-3：lives 的 url 是直播流动态地址，收集下载但不改写配置）
        for _l in tvbox.get("lives", []):
            if isinstance(_l, dict):
                _lu = _l.get("url")
                if isinstance(_lu, str) and not _is_repo_live_url(_lu):
                    add_ref("live", _lu, _g_origin, _g_base)

    # ---- 2. 并发下载/校验/入库 ----
    def work(e):
        kind_hint, url, origin = e
        lp = dep_local_path(origin, url)
        fp = os.path.join(lp)
        rkey = f"{origin}|{url}"
        # P1-9：manifest 扩展字段 fail_count/last_error/ref_count（供后续缓存校验/去重/清理消费）
        rec = {"key": rkey, "url": url, "origin": origin, "local": lp,
               "ok": False, "kind": "", "md5": "", "size": 0, "err": "", "channel": "",
               "fail_count": 0, "last_error": ""}
        content = None
        ch = ""
        raw_st = None

        # === 缓存优先：本地文件存在且md5与manifest一致 → 跳过下载 ===
        # 这是CI超时的根因修复：RAW_VOD_VERIFY_ACTIVE时不再强制全量重下，
        # 已缓存且内容未变的依赖直接复用，仅新依赖/内容变化的依赖才下载。
        _cache_hit = False
        _backoff_skip = False
        if os.path.isfile(fp) and os.path.getsize(fp) > 0:
            try:
                _local_md5 = hashlib.md5(open(fp, "rb").read()).hexdigest()
            except OSError:
                _local_md5 = ""
            _prev = manifest.get(rkey) or {}
            if _prev.get("md5") and _local_md5 and _prev["md5"] == _local_md5:
                content = open(fp, "rb").read()
                ch = "md5-cache-hit"
                rec["channel"] = ch
                _cache_hit = True
        else:
            _prev = {}
        # === 失败退避短路（2026-09-28）：死域链接 2^N 天退避窗口内不再 25s 死撞 ===
        # 本地有生效文件 → 沿用最后可用版（与 raw-store「上游已删沿用」同语义）；
        # 本地也没有 → 直接跳过，下游保留原 URL 引用，不阻断整轮合并。
        if not _cache_hit and dep_backoff_skip_in(backoff, rkey, _now_naive):
            _backoff_skip = True
            if os.path.isfile(fp) and os.path.getsize(fp) > 0:
                content = open(fp, "rb").read()
                rec["channel"] = "backoff: 上游暂不可用，沿用 deps 最后可用版"
                print(f"  [deps] 退避沿用 {rkey}（{backoff.get(rkey, {}).get('last_error', '')[:40]}）",
                      flush=True)
            else:
                rec["channel"] = "backoff-skip（无本地文件，保留原 URL 引用）"
                return rec

        def _vod_rel():
            # deps/<origin>/<path> → raw-vod/<origin>/<path>（与 deps 布局一一镜像，审计可直接对比）
            return lp[len("deps/"):] if lp.startswith("deps/") else lp

        def _vod_ingest(data: bytes) -> str:
            # 账本模式（store_bytes=False）：只记 sha256/状态，不落字节——deps/ 已
            # 700MB+，再镜像字节会撑爆仓库；deps/ 生效文件本身就是最后可用版落盘。
            return raw_store.ingest(raw_store.RAW_VOD_DIR, rkey, url, data, rel=_vod_rel(),
                                    store_bytes=False)["status"]

        if not _cache_hit and not _backoff_skip and RAW_VOD_VERIFY_ACTIVE:
            # ---- 每日验证模式（2026-09-27 落库改造）----
            # 无条件拉上游 → raw-vod 账本 sha256 变化检测（变了才覆盖 deps/）；
            # 上游删除/404 → deps/ 本地生效文件即最后可用版（管线从不删除它），
            # 标记 deleted_upstream 继续使用，绝不跟随删除。
            dl, dch = _dep_download_throttled(url)
            if dl is not None:
                try:
                    raw_st = _vod_ingest(dl)
                except OSError as e:  # noqa: BLE001 —— 存档失败不阻断依赖收集
                    print(f"  [raw-store] {rkey} 入库失败：{e}", flush=True)
                content, ch = dl, dch
                rec["channel"] = ch
            else:
                has = raw_store.manifest_has(raw_store.RAW_VOD_DIR, rkey)
                if not has and os.path.isfile(fp) and os.path.getsize(fp) > 0:
                    try:
                        _vod_ingest(open(fp, "rb").read())   # 首次部署：用本地生效文件回填账本
                        has = True
                    except (OSError, ValueError):
                        has = False
                if has and os.path.isfile(fp) and os.path.getsize(fp) > 0:
                    # 上游已删：deps/ 生效文件就是最后可用版，保留并标记删除
                    raw_store.mark_deleted(raw_store.RAW_VOD_DIR, rkey, str(dch))
                    content = open(fp, "rb").read()
                    ch = "raw-store:上游已删，沿用 deps 最后可用版"
                    rec["channel"] = ch
                    raw_st = "deleted_upstream_kept"
                # 账本与本地文件都没有 → 落到下方既有路径（重试下载），行为同旧版
        if not _cache_hit and content is None:
            # isfile 而非 exists：上游 jar 路径可能与 deps 内目录同名（CI run
            # 35771827233 实证 'deps/.../sites/码上👓多' 是目录），目录走重新下载，
            # 落盘失败由下方 try/except 兜住，不炸整轮合并
            if os.path.isfile(fp) and os.path.getsize(fp) > 0:
                # P1-4：本地 md5 与 manifest 对比——一致直接复用，不一致删了重下（防损坏文件缓存命中）
                try:
                    _local_md5 = hashlib.md5(open(fp, "rb").read()).hexdigest()
                except OSError:
                    _local_md5 = ""
                _prev = manifest.get(rkey) or {}
                if _prev.get("md5") and _local_md5 and _prev["md5"] != _local_md5:
                    print(f"  [deps] md5 不一致，删了重下：{rkey}", flush=True)
                    try:
                        os.remove(fp)
                    except OSError:
                        pass
                    content, ch = _dep_download_throttled(url)
                    rec["channel"] = ch if content else str(ch)
                    if content is None:
                        rec["err"] = str(ch)
                        rec["fail_count"] = 1
                        rec["last_error"] = str(ch)[:200]
                        return rec
                    if raw_store.ENABLED:
                        try:
                            raw_st = _vod_ingest(content)
                        except OSError as e:
                            print(f"  [raw-store] {rkey} 入库失败：{e}", flush=True)
                else:
                    content = open(fp, "rb").read()
                    if raw_store.ENABLED and not raw_store.manifest_has(raw_store.RAW_VOD_DIR, rkey):
                        # 本地生效文件在、raw-vod 存档缺（首次部署回填）
                        try:
                            raw_st = _vod_ingest(content)
                        except OSError as e:  # noqa: BLE001
                            print(f"  [raw-store] {rkey} 入库失败：{e}", flush=True)
            if content is None:
                content, ch = _dep_download_throttled(url)
                rec["channel"] = ch if content else str(ch)
                if content is None:
                    rec["err"] = str(ch)
                    rec["fail_count"] = 1
                    rec["last_error"] = str(ch)[:200]
                    return rec
                if raw_store.ENABLED:
                    try:
                        raw_st = _vod_ingest(content)
                    except OSError as e:  # noqa: BLE001
                        print(f"  [raw-store] {rkey} 入库失败：{e}", flush=True)
        rec["raw_status"] = raw_st
        hint = {"jar": "jar", "zip": "jar", "js": "js", "json": "json", "php": "jar"}.get(
            url.lower().split("?")[0].rsplit(".", 1)[-1], "")
        kind = dep_classify(hint, content)
        rec["kind"] = kind
        rec["size"] = len(content)
        rec["md5"] = hashlib.md5(content).hexdigest()
        if kind == "unknown":
            rec["err"] = f"content not js/jar/json ({content[:24]!r})"
            return rec
        try:
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, "wb").write(content)
            del content  # 立即释放大对象内存，防OOM
        except OSError as e:
            # 单条依赖落盘失败（典型：Windows 上 URL 拼出的目录名含非法字符）
            # 绝不能让它把整轮合并带崩 —— 记成这条失败，其它依赖照常收集。
            rec["err"] = f"落盘失败 {type(e).__name__}: {str(e)[:80]}"
            return rec
        rec["ok"] = True
        return rec

    ok_map: dict = {}
    _fail_recs: list = []
    print(f"[deps] 收集 {len(entries)} 个依赖（并发 {DEP_CONCURRENCY}）...", flush=True)
    ex = cf.ThreadPoolExecutor(DEP_CONCURRENCY)
    futs = {ex.submit(work, e): e for e in entries}
    pending = set(futs.keys())
    done_count = 0
    while pending:
        done_set, pending = cf.wait(pending, timeout=35, return_when=cf.FIRST_COMPLETED)
        if not done_set:
            # 看门狗：35s无任何完成 = 全部线程挂起（Windows下urllib connect对防火墙静默丢包可能不超时）
            print(f"  [deps] 看门狗超时：35s无进展，{len(pending)}个下载挂起，已跳过", flush=True)
            for fut in pending:
                fut.cancel()
            # 挂起未完成的条目全部计入退避账本（下轮 2^N 天退避，不再死撞）
            for fut in pending:
                e = futs[fut]
                _rkey = f"{e[2]}|{e[1]}"
                dep_backoff_record_fail(backoff, _rkey, "download hang (看门狗超时)", _now_naive)
                _backoff_dirty.add(_rkey)
            print(f"  [deps] 已完成 {done_count}/{len(entries)}，剩余{len(pending)}个因网络挂起跳过并计入退避账本（不影响后续产出）", flush=True)
            break
        for fut in done_set:
            done_count += 1
            try:
                rec = fut.result(timeout=2)
            except Exception as _e:
                print(f"  [deps] worker异常（已跳过）: {type(_e).__name__}: {str(_e)[:100]}", flush=True)
                continue
            if rec.get("ok"):
                ok_map[rec["key"]] = rec
                dep_backoff_clear(backoff, rec["key"])   # 成功 → 清退避（链接复活不再退避）
                _backoff_dirty.add(rec["key"])
            elif rec.get("err") or not rec.get("ok"):
                # 失败（下载挂/404/内容不符/落盘失败）→ 记退避账本，下轮 2^N 天窗口内跳过
                if not str(rec.get("channel", "")).startswith("backoff"):
                    dep_backoff_record_fail(backoff, rec["key"], rec.get("err") or rec.get("last_error") or "dep collect failed", _now_naive)
                    _backoff_dirty.add(rec["key"])
                    _fail_recs.append(rec)
            if done_count % 10 == 0:
                print(f"  ... {done_count}/{len(entries)}", flush=True)
    ex.shutdown(wait=False)  # 不等待挂起线程，避免with块exit时死等
    # 退避账本批量落盘（成功已清 / 失败已记），供下轮 work() 短路死域链接
    if _backoff_dirty:
        dep_backoff_save(backoff)
        print(f"  [deps] 退避账本更新：{len(backoff)} 条（成功 {len(ok_map)} 已清 / 失败 {len(_fail_recs)} 已记）"
              f" → {DEP_BACKOFF_FILE}", flush=True)

    # ---- 2b. 规则 js 内部相对 import 递归落库（限深 1 层）----
    # cat 规则集形态：每个规则 js 顶部 `import { _ } from './lib/cat.js'`，公共库必须随规则
    # 一起落库，否则客户端加载规则时 import 404（Bookan[cat] 等 6 个 cat 源因此曾全灭）。
    # base 用「该 js 文件自身的 url」做 urljoin（标准 ESM 相对语义），比 relpath 反推可靠。
    IMPORT_JS_RE = re.compile(r"""(?:from\s*|import\s*\(\s*|require\(\s*)['"](\.{1,2}/[^'"]+\.js)['"]""")

    def scan_js_imports():
        added = 0
        for rec in list(ok_map.values()):
            if rec.get("kind") != "js" or not rec.get("ok"):
                continue
            try:
                text = open(rec["local"], encoding="utf-8", errors="replace").read()[:65536]
            except OSError:
                continue
            for m in IMPORT_JS_RE.finditer(text):
                imp = m.group(1)  # './lib/cat.js' 或 '../lib/cat.js'
                target_url = urllib.parse.urljoin(rec["url"], imp)
                rkey = f"{rec['origin']}|{target_url}"
                if rkey in ok_map:
                    continue
                entries.append(("js", target_url, rec["origin"]))
                added += 1
        return added

    # P1-2：JS import 递归识别（while 循环 + visited set 防循环 + 深度硬限 3 层）
    _visited_js_urls = set()
    for depth in range(3):  # 深度硬限 3 层
        n_imp = scan_js_imports()
        if not n_imp:
            break
        print(f"  [deps] 规则 js import 第 {depth+1} 层：追加 {n_imp} 个公共库依赖...", flush=True)
        ex2 = cf.ThreadPoolExecutor(DEP_CONCURRENCY)
        futs2 = {ex2.submit(work, e): e for e in entries[-n_imp:]}
        pending2 = set(futs2.keys())
        while pending2:
            done2, pending2 = cf.wait(pending2, timeout=35, return_when=cf.FIRST_COMPLETED)
            if not done2:
                print(f"  [deps] import递归看门狗：{len(pending2)}个挂起已跳过", flush=True)
                for fut in pending2:
                    fut.cancel()
                break
            for fut in done2:
                try:
                    rec2 = fut.result(timeout=2)
                except Exception as _e2:
                    print(f"  [deps] import递归worker异常: {type(_e2).__name__}", flush=True)
                    continue
                if rec2.get("ok"):
                    ok_map[rec2["key"]] = rec2
        ex2.shutdown(wait=False)

    # ---- 3. 失败项回退：manifest 缓存 ----
    for e in entries:
        key = f"{e[2]}|{e[1]}"
        if key not in ok_map and SKIP_REFRESH and key in manifest:
            m = manifest[key]
            if os.path.exists(m["local"]):
                ok_map[key] = {"key": key, "url": e[1], "origin": e[2], "local": m["local"],
                               "ok": True, "kind": m["kind"], "md5": m["md5"],
                               "size": m.get("size", 0), "err": "", "channel": "manifest-cache"}

    # ---- 3b. 整仓兜底：主路与 manifest 缓存都没补上的 github 文件 ----
    # 顺序：先稀疏浅克隆（SSH，一仓一次只取需要的 blob，最准最快），
    # 再用 codeload tarball 补剩余（≤30MB 小仓；CI 上没有 SSH key 时它顶上）。
    _tb_got: dict = {}
    _needs = [e for e in entries if f"{e[2]}|{e[1]}" not in ok_map]
    if _needs and DEPS_GIT_BACKFILL:
        _git_got, _gst = deps_git_backfill(_needs)
        for _k, _v in _git_got.items():
            _tb_got[_k] = (_v, "git-sparse")
        print(f"  [deps] 稀疏克隆兜底：候选 {_gst['groups']} 组 → 成功 {_gst['repos_ok']} 仓，"
              f"补回 {_gst['files']} 个文件（git 不可达 {_gst['probed_unreachable']} / "
              f"失败 {_gst['repos_failed']} / 超预算停 {_gst['budget_cut']}）", flush=True)
    if _needs and DEPS_TARBALL_BACKFILL:
        _rest = [e for e in _needs if (e[2], e[1]) not in _tb_got]
        _tb_raw, _tb_st = deps_tarball_pick(_rest)
        for _k, _v in _tb_raw.items():
            _tb_got[_k] = (_v, "codeload-tarball")
        print(f"  [deps] codeload 整仓兜底：候选 {_tb_st['groups']} 组 → 实拉 "
              f"{_tb_st['repos_tried']} 仓，补回 {_tb_st['files']} 个文件"
              f"（跳过：不足阈值 {_tb_st['below_threshold']} / 仓库过大 {_tb_st['too_big']} / "
              f"体积未知 {_tb_st['size_unknown']} / 取回失败 {_tb_st['failed']} / "
              f"超预算停 {_tb_st['budget_cut']}）", flush=True)
    for (origin, url), (data, channel) in _tb_got.items():
        rkey = f"{origin}|{url}"
        lp = dep_local_path(origin, url)
        hint = {"jar": "jar", "zip": "jar", "js": "js", "json": "json",
                "php": "jar"}.get(url.lower().split("?")[0].rsplit(".", 1)[-1], "")
        kind = dep_classify(hint, data)
        if kind == "unknown":
            continue
        try:
            os.makedirs(os.path.dirname(lp), exist_ok=True)
            with open(lp, "wb") as fh:
                fh.write(data)
        except OSError as ex:
            print(f"  [deps] {channel} 落盘失败 {rkey}: {type(ex).__name__}", flush=True)
            continue
        raw_st = ""
        if raw_store.ENABLED:
            try:
                raw_st = raw_store.ingest(
                    raw_store.RAW_VOD_DIR, rkey, url, data,
                    rel=lp[len("deps/"):] if lp.startswith("deps/") else lp,
                    store_bytes=False)["status"]
            except OSError as ex:  # noqa: BLE001
                print(f"  [deps] {channel} {rkey} 账本写入失败：{ex}", flush=True)
        ok_map[rkey] = {"key": rkey, "url": url, "origin": origin, "local": lp,
                        "ok": True, "kind": kind,
                        "md5": hashlib.md5(data).hexdigest(), "size": len(data),
                        "err": "", "channel": channel, "raw_status": raw_st}
        dep_backoff_clear(backoff, rkey)   # 补回来了，别再退避
        _backoff_dirty.add(rkey)
    if _backoff_dirty:
        dep_backoff_save(backoff)


    # ---- 4. 改写引用 ----
    stats = {"total": len(entries), "collected": len(ok_map), "rewritten": 0, "kept": 0, "spider": 0}
    # raw-store 依赖侧入库结果（本轮实际收集到的依赖中各转移状态计数）
    raw_counts = {"new": 0, "changed": 0, "changed_recovered": 0, "restored": 0,
                  "unchanged": 0, "deleted_upstream_kept": 0}
    for _rec in ok_map.values():
        _rs = _rec.get("raw_status")
        if _rs in raw_counts:
            raw_counts[_rs] += 1
    stats["raw_counts"] = raw_counts
    if RAW_VOD_VERIFY_ACTIVE:
        print(f"[deps] raw-store 验证：new {raw_counts['new']} / changed "
              f"{raw_counts['changed'] + raw_counts['changed_recovered']} / unchanged "
              f"{raw_counts['unchanged']} / 上游已删沿用 {raw_counts['deleted_upstream_kept']}", flush=True)
    missing = []
    # P1-9：ref_count 统计——每个 local 被几个站点字段引用（改写成功即计数）
    ref_counts: dict = {}

    def _bump_ref_count(local: str):
        ref_counts[local] = ref_counts.get(local, 0) + 1

    def md5_of(local: str):
        if not os.path.isfile(local):  # 目录/不存在都算 missing，open 只接受真实文件
            missing.append(local)
            return None
        with open(local, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    if isinstance(tvbox.get("spider"), str) and spider_origin:
        key = f"{spider_origin[0]}|{tvbox['spider'].split(';md5;')[0] if is_file_ref(tvbox['spider'].split(';md5;')[0]) else tvbox['spider']}"
        # spider 的 url 已在 entries 里以 (origin, base) 生成，直接按 url 查
        sk = None
        for e in entries:
            if e[2] == spider_origin[0] and e[0] == "jar":
                sk = ok_map.get(f"{e[2]}|{e[1]}")
                if sk:
                    break
        if sk:
            md5v = md5_of(sk["local"])
            if md5v:
                tvbox["spider"] = f"./{sk['local']};md5;{md5v}"
                stats["spider"] = 1

    # ---- P0-3：全局字段 wallpaper 改写（图片依赖落库后改本地路径）----
    # lives 的 url 不改写（直播流动态地址，P0-3 明确保留原 URL）；
    # parses 的 url 多为解析 API 端点（非静态文件），is_file_ref 天然不过，无需改写。
    _wp = tvbox.get("wallpaper")
    if isinstance(_wp, str):
        _wp_rec = ok_map.get(f"{_g_origin}|{urllib.parse.urljoin(_g_base, _wp) if not _wp.startswith('http') else _wp}")
        if _wp_rec:
            _wp_md5 = md5_of(_wp_rec["local"])
            if _wp_md5:
                tvbox["wallpaper"] = f"./{_wp_rec['local']}"
                stats["rewritten"] += 1

    for s in tvbox.get("sites", []):
        origin = site_origin.get(s.get("key"))
        if not origin:
            continue
        for field in ("jar", "ext", "api"):
            v = s.get(field)
            vals = []
            if isinstance(v, str):
                vals = [(field, None, v)]
            elif isinstance(v, dict):
                vals = [(field, k2, v2) for k2, v2 in v.items() if isinstance(v2, str)]
            for f0, k2, raw in vals:
                if "$$$" in raw:
                    segs = raw.split("$$$")
                    changed = False
                    for si, seg in enumerate(segs):
                        r = is_file_ref(seg)
                        if not r:
                            continue
                        if f0 == "api" and not (r[0] == "rel" and seg.lower().split("?")[0].endswith(".js")):
                            continue  # api 字段只改写「相对 js 规则」，绝不动 HTTP 端点
                        base2 = UPSTREAM_BASES.get(origin, "")
                        url2 = urllib.parse.urljoin(base2, r[1]) if r[0] == "rel" else r[1]
                        rec2 = ok_map.get(f"{origin}|{url2}")
                        if not rec2:
                            continue
                        md52 = md5_of(rec2["local"])
                        if md52 is None:
                            continue
                        segs[si] = f"./{rec2['local']}"
                        changed = True
                        stats["rewritten"] += 1
                        _bump_ref_count(rec2["local"])
                    if changed:
                        if k2 is None:
                            s[f0] = "$$$".join(segs)
                        else:
                            s[f0][k2] = "$$$".join(segs)
                    continue
                r = is_file_ref(raw)
                if not r:
                    continue
                if f0 == "api" and not (r[0] == "rel" and raw.lower().split("?")[0].endswith(".js")):
                    continue  # api 字段只改写「相对 js 规则」，绝不动 HTTP 端点
                base = UPSTREAM_BASES.get(origin, "")
                url = urllib.parse.urljoin(base, r[1]) if r[0] == "rel" else r[1]
                rec = ok_map.get(f"{origin}|{url}")
                if not rec:
                    stats["kept"] += 1
                    continue
                md5v = md5_of(rec["local"])
                if md5v is None:
                    stats["kept"] += 1
                    continue
                if f0 == "jar":
                    had = ";md5;" in raw
                    new = f"./{rec['local']};md5;{md5v}" if had else f"./{rec['local']}"
                    if k2 is None:
                        s[f0] = new
                    else:
                        s[f0][k2] = new
                else:
                    new = f"./{rec['local']}"
                    if k2 is None:
                        s[f0] = new
                    else:
                        s[f0][k2] = new
                stats["rewritten"] += 1
                _bump_ref_count(rec["local"])
    if missing:
        print(f"  [deps] WARN 缺失本地文件 {len(missing)} 个，如 {missing[:3]}", flush=True)
    # P1-5：死引用统计（行为不变——缺失文件本就不改写保留原 URL；只补可观测性）
    stats["dead_dep_refs"] = missing
    stats["dead_dep_refs_count"] = len(missing)

    # ---- 5. 更新 manifest ----
    for rec in ok_map.values():
        manifest[rec["key"]] = {"url": rec["url"], "origin": rec["origin"], "local": rec["local"],
                                "md5": rec["md5"], "kind": rec["kind"], "size": rec["size"],
                                "channel": rec.get("channel", ""), "updated_at": now,
                                # P1-9：扩展字段
                                "fail_count": int(rec.get("fail_count", 0)),
                                "last_error": rec.get("last_error", ""),
                                "ref_count": ref_counts.get(rec["local"], 0)}
    os.makedirs(DEPS_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"[deps] 完成：收集 {stats['collected']}/{stats['total']}，改写 {stats['rewritten']} 处引用，"
          f"spider {'已修复' if stats['spider'] else '未变'}", flush=True)
    # P1-7：内容去重 dry-run 骨架——按 md5 分组建 old→new 映射，只输出 plan 不执行替换
    try:
        by_md5: dict = {}
        for rec in ok_map.values():
            if rec.get("md5") and rec.get("local"):
                by_md5.setdefault(rec["md5"], []).append(rec["local"])
        dup_groups = {m: paths for m, paths in by_md5.items() if len(paths) > 1}
        if dup_groups:
            plan = {"generated_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
                    "note": "DRY-RUN：只输出去重计划，不自动替换引用（人工确认后再开启）",
                    "duplicate_groups": [{"md5": m, "paths": ps, "keep": min(ps, key=len)}
                                         for m, ps in dup_groups.items()]}
            os.makedirs("state", exist_ok=True)
            with open("state/dep_dedup_plan.json", "w", encoding="utf-8") as _f:
                json.dump(plan, _f, ensure_ascii=False, indent=1)
            print(f"  [P1-7] 内容去重 dry-run：发现 {len(dup_groups)} 组重复（state/dep_dedup_plan.json，不自动替换）", flush=True)
    except Exception as _e:  # noqa: BLE001
        print(f"  [P1-7] dry-run 异常（不阻断）：{_e}", flush=True)
    return stats



# ---------------- 依赖外链落库兜底层：collect_and_rewrite_deps 漏网的外部静态引用 ----------------
# 背景（2026-09-19 用户指令「依赖文件落库，相关的路径引用改成仓库路径」）：
#   collect_and_rewrite_deps 只处理 origin 明确、UPSTREAM_BASES 可回溯的站点引用；
#   去重/合并后 origin 丢失的站点，其 ext 里残留第三方绝对 URL（.js/.json/.txt）。
#   本层按 URL 兜底：下载 → deps/localized/ 落库 → 引用改写为 ./deps/... 仓库相对路径
#   （主配置相对路径，子仓经 _absolutize 转为 REPO_RAW 绝对路径）。
#   API 端点（非静态文件后缀）、127.0.0.1/localhost 本机代理、本仓库自身链接一律不动。
#   与 collect_and_rewrite_deps 同口径：已存在非空文件直接复用（保留现值不回源覆盖）、
#   下载失败/内容不可识别 → 保留原 URL 不改写。

MIRROR_PREFIX_RE = re.compile(r"^(https?://[^/]*(?:ghproxy|gh-proxy|ghfast|moeyy|gh\.llkk\.cc|gh\.zwy\.one|raw\.ihtw\.moe|ghp\.ci)[^/]*)/(https?://)")


import urllib.parse


def _static_ext_ref(seg: str):
    """ext 段落识别：第三方静态文件 URL（.js/.json/.txt/.zip）→ 归一化 URL；其余 None。

    .php 端点（dr_py 服务器等）是动态 API 不落库；;md5;/;params; 链只取首段判型。"""
    s = seg.strip()
    if not s or s.startswith("./") or s.startswith("../"):
        return None
    base = s.split(";")[0]
    if "$$$" in base or not re.match(r"^https?://", base):
        return None
    host = urllib.parse.urlparse(base).netloc
    if not host or "127.0.0.1" in host or "localhost" in host:
        return None
    if "hebijunge/tvbox-config" in base:  # 本仓库自身引用已是仓库路径
        return None
    # 镜像前缀归一化：ghproxy/gh-proxy/ghfast/moeyy 前缀剥成裸源 URL 再统一走 dep_download 镜像轮换
    m = MIRROR_PREFIX_RE.match(base)
    url = f"{m.group(2)}{base[m.end(2):]}" if m else base
    path = url.split("?")[0].lower()
    if not path.endswith((".js", ".json", ".txt", ".zip")):
        return None
    return url


def localize_external_refs(tvbox: dict) -> dict:
    """扫描 sites 的 jar/ext，把第三方静态依赖文件下载落库 deps/localized/ 并改写为仓库路径。"""
    manifest = load_manifest()
    now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S +08:00")

    # ---- 1. 收集唯一 URL（jar 用 is_file_ref 识别含 .jar/.zip/.php；ext 走 _static_ext_ref） ----
    candidates: dict = {}   # url -> kind_hint
    api_untouched = 0

    _unresolved_rel_refs: list = []  # P1-1：无法反推 origin 的相对路径引用

    def _infer_origin_from_rawstore(seg: str) -> str:
        """P1-1：相对路径依赖兜底——查 raw_store 快照反推上游 origin（骨架，best-effort）。"""
        return ""  # 待后续：查 raw_store manifest 反查

    def add(field: str, seg: str):
        nonlocal api_untouched
        seg = seg.strip()
        if not seg:
            return
        if field == "jar":
            r = is_file_ref(seg)
            if not r or r[0] != "abs":
                # P1-1：相对路径分支尝试反推 origin（骨架，当前无法反推则记录）
                if r and r[0] == "rel":
                    _inf = _infer_origin_from_rawstore(seg)
                    if not _inf:
                        _unresolved_rel_refs.append(seg[:120])
                return
            url = r[1]
            if "127.0.0.1" in url or "localhost" in url or "hebijunge/tvbox-config" in url:
                return
            candidates.setdefault(url, "jar")
        else:
            url = _static_ext_ref(seg)
            if url:
                hint = "js" if url.lower().split("?")[0].endswith(".js") else (
                    "jar" if url.lower().split("?")[0].endswith(".zip") else "json")
                candidates.setdefault(url, hint)
            elif re.match(r"^https?://", seg.split(";")[0]) and "$$$" not in seg:
                api_untouched += 1  # API 端点等非静态引用：保持原样

    for s in tvbox.get("sites", []):
        for field in ("jar", "ext"):
            v = s.get(field)
            if isinstance(v, str):
                for seg in v.split("$$$"):
                    add(field, seg)
            elif isinstance(v, dict):
                for v2 in v.values():
                    if isinstance(v2, str):
                        for seg in v2.split("$$$"):
                            add(field, seg)

    # ---- 2. 下载/复用/校验（并发，与 collect_and_rewrite_deps 同口径） ----
    def local_path_of(url: str) -> str:
        name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or ""
        name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name)[:60]
        return f"{DEPS_DIR}/localized/{hashlib.md5(url.encode()).hexdigest()[:10]}-{name}"

    def work(url_kind):
        url, hint = url_kind
        lp = local_path_of(url)
        rec = {"url": url, "local": lp, "ok": False, "kind": "", "md5": "", "size": 0, "err": "", "channel": ""}
        if os.path.isfile(lp) and os.path.getsize(lp) > 0:
            content = open(lp, "rb").read()
            rec["channel"] = "keep-existing"
        else:
            content, ch = dep_download(url)
            rec["channel"] = ch if content else str(ch)
            if content is None:
                rec["err"] = str(ch)
                return rec
        kind = dep_classify(hint, content)
        if kind == "unknown":  # HTML/伪装内容：不改写，保留原 URL
            rec["err"] = f"content not js/jar/json ({content[:24]!r})"
            return rec
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        open(lp, "wb").write(content)
        rec.update({"ok": True, "kind": kind, "size": len(content),
                    "md5": hashlib.md5(content).hexdigest()})
        return rec

    ok_map: dict = {}
    if candidates:
        print(f"[deps-2] 外链落库兜底：{len(candidates)} 个第三方静态依赖（API 端点 {api_untouched} 处保持不动）...", flush=True)
        with cf.ThreadPoolExecutor(DEP_CONCURRENCY) as ex:
            for rec in ex.map(work, candidates.items()):
                if rec["ok"]:
                    ok_map[rec["url"]] = rec
                else:
                    print(f"  [deps-2] 保留原链 {rec['url'][:80]} ← {rec['err'][:80]}", flush=True)

    # ---- 3. 改写引用 ----
    stats = {"candidates": len(candidates), "localized": len(ok_map), "rewritten": 0,
             "kept": 0, "api_endpoints_untouched": api_untouched, "files": len(ok_map)}

    def rewrite_seg(field: str, seg: str) -> str:
        def ref_of(local: str) -> str:
            # 引用一律相对仓库根的 ./deps/...（DEPS_DIR 被环境变量指向绝对路径时也能正确改写）
            return local if not os.path.isabs(local) else os.path.relpath(local)
        if field == "jar":
            r = is_file_ref(seg)
            if not r or r[0] != "abs":
                return seg
            rec = ok_map.get(r[1])
            if not rec:
                stats["kept"] += 1
                return seg
            return f"./{ref_of(rec['local'])};md5;{rec['md5']}" if ";md5;" in seg else f"./{ref_of(rec['local'])}"
        url = _static_ext_ref(seg)
        if not url:
            return seg
        rec = ok_map.get(url)
        if not rec:
            stats["kept"] += 1
            return seg
        return f"./{ref_of(rec['local'])}"

    def apply_field(field: str, v):
        if isinstance(v, str):
            if "$$$" in v:
                return "$$$".join(rewrite_seg(field, x) for x in v.split("$$$"))
            return rewrite_seg(field, v)
        if isinstance(v, dict):
            return {k: apply_field(field, v2) for k, v2 in v.items()}
        return v

    if ok_map:
        for s in tvbox.get("sites", []):
            for field in ("jar", "ext"):
                if field in s:
                    new = apply_field(field, s[field])
                    if new != s.get(field):
                        s[field] = new
                        stats["rewritten"] += 1

    # ---- 4. manifest 记录（origin=localized，与 collect 共用一份 manifest） ----
    for rec in ok_map.values():
        manifest[f"localized|{rec['url']}"] = {"url": rec["url"], "origin": "localized",
                                               "local": rec["local"], "md5": rec["md5"],
                                               "kind": rec["kind"], "size": rec["size"],
                                               "channel": rec.get("channel", ""), "updated_at": now}
    os.makedirs(DEPS_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"[deps-2] 完成：落库 {stats['localized']}/{stats['candidates']}，改写 {stats['rewritten']} 个站点字段，"
          f"保留原链 {stats['kept']} 处，API 端点 {stats['api_endpoints_untouched']} 处未动", flush=True)
    return stats



def strip_comments_and_clean(text: str) -> str:
    """去 BOM、去行注释与块注释（状态机，不误伤字符串内双斜杠）、去尾随逗号。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    cleaned = "".join(out)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


def gh_url(u: str) -> str:
    """GitHub 链接换主镜像通道 GH_MIRRORS[0]（产出配置改写用；拉取侧走 GH_MIRRORS 列表轮换）。"""
    if not GH_MIRRORS or "ghproxy" in u or any(u.startswith(m.rstrip("/")) for m in GH_MIRRORS):
        return u
    if re.match(r"^https?://(raw\.)?githubusercontent\.com/", u) or re.match(
        r"^https?://github\.com/[^/]+/[^/]+/(raw|releases|archive)/", u
    ):
        return GHPROXY + u
    return u


class _SplitTimeoutHTTPConnection(http.client.HTTPConnection):
    """connect 用传入 timeout，连接建立后把 socket 读超时切到 FETCH_READ_TIMEOUT。"""

    def connect(self):
        super().connect()
        if self.sock is not None:
            self.sock.settimeout(FETCH_READ_TIMEOUT)


class _SplitTimeoutHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        super().connect()
        if self.sock is not None:
            self.sock.settimeout(FETCH_READ_TIMEOUT)


class _SplitHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_SplitTimeoutHTTPConnection, req)


class _SplitHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        ctx = getattr(self, "_context", None)
        return self.do_open(_SplitTimeoutHTTPSConnection, req, context=ctx)


# 连接阶段用调用方传入的 timeout（connect_timeout），连接建立后所有 recv 走 read_timeout。
_SPLIT_OPENER = urllib.request.build_opener(_SplitHTTPHandler(), _SplitHTTPSHandler())


def http_get(url: str, timeout: int, max_bytes: int = 0, rng=None, ua: str = None,
             xrw: str = None, extra_headers: dict = None, return_headers: bool = False):
    """返回 (status, bytes, elapsed_ms)；return_headers=True 时返回 4 元组 (..., headers dict)。
    非 2xx 抛 HTTPError。timeout 为连接（connect）超时；连接建立后读超时固定 FETCH_READ_TIMEOUT。
    rng=(start, end) 时带 Range 头抽段请求（直播测速用，不整段下载）。
    ua/xrw 传入时覆盖默认 UA / 加 X-Requested-With 指纹头（P1-3 UA 池轮换）。
    extra_headers：C1 增量拉取用（If-None-Match/If-Modified-Since）。"""
    headers = dict(UA)
    if ua:
        headers["User-Agent"] = ua
    if xrw:
        headers["X-Requested-With"] = xrw
    if rng:
        headers["Range"] = f"bytes={rng[0]}-{rng[1]}"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    with _SPLIT_OPENER.open(req, timeout=timeout) as r:
        data = r.read(max_bytes) if max_bytes else r.read()
    _ms = int((time.time() - t0) * 1000)
    if return_headers:
        return r.status, data, _ms, dict(r.headers)
    return r.status, data, _ms


# ---------------- P2：域名替换层 ----------------

def load_domain_map() -> dict:
    try:
        with open(DOMAIN_MAP_FILE, "r", encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m, dict):
            return {str(k): str(v) for k, v in m.items() if k and v and not str(k).startswith("_")}
    except Exception:  # noqa: BLE001
        pass
    return {}


DOMAIN_MAP = {}


def map_domain(value):
    """对 URL 字符串应用 state/domain_map.json 的域名/前缀替换（上游换域名时改写而非丢源）。

    O 小点加固：完整 URL 按 host 边界匹配替换（避免子串误伤路径/其他域名）；
    非 URL 字符串回退到原子串替换行为。
    """
    if not DOMAIN_MAP or not isinstance(value, str):
        return value
    for old, new in DOMAIN_MAP.items():
        if old and old in value:
            value = _replace_host(value, old, new)
    return value


def _replace_host(value: str, old: str, new: str) -> str:
    m = re.match(r"^(https?://)([^/?#]+)(.*)$", value, re.I)
    if not m:
        return value.replace(old, new)
    scheme, netloc, rest = m.groups()
    host = netloc.rsplit("@", 1)[-1].split(":")[0]
    if host == old:
        new_host = new
    elif host.endswith("." + old):
        new_host = host[: -len(old)] + new
    else:
        return value
    return f"{scheme}{netloc.replace(host, new_host, 1)}{rest}"


# ---------------- P0：拉取与解析（一上游一适配器） ----------------

FETCH_HEADERS_FILE = os.environ.get("FETCH_HEADERS_FILE", "state/fetch_headers.json")


def _load_fetch_headers() -> dict:
    """C1：加载各上游最近一次成功响应的 ETag/Last-Modified（state/fetch_headers.json）。"""
    return _load_json_dict(FETCH_HEADERS_FILE)


def _save_fetch_headers(d: dict):
    _save_json_dict(FETCH_HEADERS_FILE, d)


def fetch_raw(url: str, mirrors=None, ua_pool=None, conditional: bool = False):
    """多通道重试（吸收点 P1-2 多镜像选通 / P1-3 UA 轮换，独立实现）。
    尝试顺序：主 URL → mirrors 逐个 → ghproxy 镜像列表（仅 GitHub 链接）。
    主 URL 与用户镜像每个失败后按 UA 池轮换重试（上限 UA_ROTATE_MAX 组）；
    ghproxy 兜底通道保持默认 UA 单次尝试（控制最坏尝试次数）。
    C1：conditional=True 时仅对 GitHub raw 直连发 If-None-Match/If-Modified-Since；
        ghproxy 代理通道不发条件头（代理吞 ETag）。304 返回 (None, "304_not_modified", "")。
    返回 (raw_bytes, channel, success_url) 或 (None, err, "")。"""
    import urllib.parse
    pool = ua_pool if ua_pool is not None else UA_POOL_VOD
    base_urls = [url]
    for m in (mirrors or []):
        if isinstance(m, str) and m and m not in base_urls:
            base_urls.append(m)
    gh_urls = ([m + url for m in GH_MIRRORS if m + url not in base_urls]
               if ("github" in url and "ghproxy" not in url) else [])
    # C1：仅 GitHub raw 直连发条件请求（ghproxy 代理吞 ETag，不发）
    do_conditional = bool(conditional and "githubusercontent.com" in url and "ghproxy" not in url)
    cond_headers = {}
    if do_conditional:
        _h = _load_fetch_headers().get(url) or {}
        if _h.get("etag"):
            cond_headers["If-None-Match"] = _h["etag"]
        if _h.get("last_modified"):
            cond_headers["If-Modified-Since"] = _h["last_modified"]
    last_err = ""
    for ch, u in enumerate(base_urls):
        for pair in pool[:UA_ROTATE_MAX]:
            try:
                _eh = cond_headers if (ch == 0 and do_conditional) else None
                status, raw, _ms, hdrs = http_get(
                    u, FETCH_CONNECT_TIMEOUT,
                    ua=pair.get("User-Agent"),
                    xrw=pair.get("X-Requested-With") or None,
                    extra_headers=_eh, return_headers=True)
                # C1：主 URL 直连 200 成功后更新 ETag/Last-Modified 缓存
                if ch == 0 and do_conditional:
                    try:
                        _hd = _load_fetch_headers()
                        _hd[url] = {"etag": hdrs.get("ETag", ""),
                                    "last_modified": hdrs.get("Last-Modified", "")}
                        _save_fetch_headers(_hd)
                    except Exception:  # noqa: BLE001
                        pass
                if ch == 0:
                    return raw, "direct", u
                return raw, f"mirror:{urllib.parse.urlparse(u).netloc}", u
            except urllib.error.HTTPError as he:
                # C1：304 Not Modified → 通知调用方读 raw-store 最后版本
                if ch == 0 and do_conditional and he.code == 304:
                    return None, "304_not_modified", ""
                last_err = f"HTTP {he.code}"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"[:120]
    for u in gh_urls:
        try:
            status, raw, _ms = http_get(u, FETCH_CONNECT_TIMEOUT)
            return raw, f"mirror:{urllib.parse.urlparse(u).netloc}", u
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"[:120]
    return None, last_err, ""


def parse_tvbox(raw: bytes):
    """适配器：TVBox json 配置。返回 dict。

    容错兜底（2026-09-26，拾光 xmbjm/svip 实测）：部分源字符串值内含裸控制符
    （CR LF），严格 json.loads 必挂会被误判 dead 进自动黑名单；先严格解析，
    失败再以 strict=False 重试（仅放宽字符串内控制符，其余语义不变）。"""
    txt = raw.decode("utf-8", "replace")
    cleaned = strip_comments_and_clean(txt)
    try:
        cfg = json.loads(cleaned)
    except json.JSONDecodeError:
        cfg = json.loads(cleaned, strict=False)
    if not isinstance(cfg, dict):
        raise ValueError("top-level is not an object")
    return cfg


EXTINF_RE = re.compile(r"^#EXTINF:?\s*-?\d+\s*(.*)$")


TXT_GENRE_RE = re.compile(r"^(.*?)[，,]\s*#genre#\s*$", re.IGNORECASE)


def parse_m3u(raw: bytes):
    """适配器：m3u/txt 直播列表。返回 [(频道名, 分组, url)]。
    支持两种格式（2026-09-21 直播线融合，第三批 P3）：
    1) m3u：#EXTINF...group-title="分组",频道名 + 换行 URL；
    2) txt 频道格式（Bruce0422/JunTV 等部分产物）：「分组,#genre#」行声明分组，
       其后「频道名,url1#url2」行，多线路以 # 分隔（仅收 http/https 线路）。"""
    txt = raw.decode("utf-8", "replace")
    entries = []
    attr_name = None
    group = ""
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            m = EXTINF_RE.match(line)
            rest = m.group(1) if m else ""
            gm = re.search(r'group-title="([^"]*)"', rest)
            group = gm.group(1).strip() if gm else ""
            attr_name = rest.rsplit(",", 1)[-1].strip() if "," in rest else rest.strip()
            continue
        if line.startswith("#"):
            continue
        gm = TXT_GENRE_RE.match(line)
        if gm:
            group = gm.group(1).strip()
            attr_name = None
            continue
        if "," in line and not attr_name:
            name, _, urls = line.partition(",")
            got = False
            for u in urls.split("#"):
                u = u.strip()
                if u.lower().startswith(("http://", "https://")):
                    entries.append((name.strip(), group, u))
                    got = True
            if got:
                continue
        if attr_name:
            entries.append((attr_name, group, line))
            attr_name = None
    return entries


PARSERS = {"tvbox": parse_tvbox, "m3u": parse_m3u}


def evaluate_upstream(u: dict, raw):
    """P0 质量门槛。返回 (ok, status, detail, error)。
    status: ok / degraded（解析成功但不达门槛，不参与合并）/ dead（拉取或解析失败）。"""
    try:
        parser = PARSERS[u["kind"]]
    except KeyError:
        return False, "dead", {}, f"unknown kind {u.get('kind')}"
    if raw is None:
        return False, "dead", {}, "fetch failed"
    if u.get("canary"):
        # 第十三批：canary 上游专用门槛——HTTP 200 已由 fetch_raw 保证 + 内容 >= CANARY_MIN_BYTES。
        # 不套通用门槛：romaxa55 cn.m3u 43 条 < MIN_ENTRIES_M3U=50，设计内只监控不合并，
        # 健康分照常进出 record_result（连续失败自动停用对 canary 同样生效）。
        ok_c = len(raw) >= CANARY_MIN_BYTES
        return ok_c, ("ok" if ok_c else "degraded"), {"bytes": len(raw)}, \
            ("" if ok_c else f"canary content check failed: {len(raw)}B < {CANARY_MIN_BYTES}B")
    if len(raw) < (MIN_BYTES_M3U if u["kind"] == "m3u" else MIN_BYTES_TVBOX):
        return False, "degraded", {}, f"too small ({len(raw)} bytes)"
    try:
        parsed = parser(raw)
    except Exception as e:  # noqa: BLE001
        return False, "dead", {}, f"{type(e).__name__}: {e}"[:120]
    if u["kind"] == "tvbox":
        n = sum(len(parsed.get(k) or []) for k in ("sites", "lives", "parses"))
        if n < MIN_ITEMS_TVBOX:
            return False, "degraded", {"items": n}, "no usable items"
        return True, "ok", {"items": n, "cfg": parsed}, ""
    else:
        if len(parsed) < MIN_ENTRIES_M3U:
            return False, "degraded", {"entries": len(parsed)}, f"only {len(parsed)} entries"
        return True, "ok", {"entries": len(parsed)}, ""


# ---------------- P0/P1：状态、黑白名单 ----------------

def load_state() -> dict:
    """P1-A：sources 段读自 state/validated.json（单一事实源）。"""
    return _vs.load_validated()["sources"]


def save_state(state: dict):
    """P1-A：sources 段写回 validated.json，落盘时应用第 4 层跨日衰减。"""
    doc = _vs.load_validated()
    doc["sources"] = state
    _vs.apply_decay(doc)
    _vs.save_validated(doc, note="GitHub 发现验证线写回（fetch_merge）")


def read_name_list(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    except Exception:  # noqa: BLE001
        return []


# V12 失败严重度分级：按失败类型差异化停用阈值（timeout 宽容、404/连接拒绝严苛）
KIND_FAIL_LIMIT = {
    "timeout": 5,            # 网络抖动多，宽容 5 次才降权
    "404": 2,                # 源已删，2 次即剔除
    "connection_refused": 2, # 连接拒绝=源下线，2 次即剔除
    "5xx": 3,                # 服务端错误，3 次降权
    "empty_product": 3,      # 空内容，3 次降权
}


def record_result(state: dict, name: str, ok: bool, whitelist_manual: list,
                  url: str = None, fail_kind: str = None) -> str:
    """更新连续失败计数；达阈值自动停用（手动白名单保护）。返回 'ok'/'disabled_now'/'failing'。
    P1-A：同步写按日历史（第 4 层跨日衰减依据）与规范键 ckey（双线接口键）。
    V12：fail_kind 给出时按 KIND_FAIL_LIMIT 差异化阈值（timeout 5/404 2/5xx 3/空内容 3）。"""
    now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    ent = state.get(name) if isinstance(state.get(name), dict) else {}
    if url:
        ent.setdefault("url", url)
        ent["ckey"] = _vs.canonical_key(url)
    _vs.record_day(ent, ok)
    if ok:
        ent.update({"fail_count": 0, "last_ok_at": now, "disabled": False, "disabled_reason": ""})
        state[name] = ent
        return "ok"
    fc = int(ent.get("fail_count", 0)) + 1
    ent["fail_count"] = fc
    ent["last_fail_at"] = now
    # V12：按失败类型取阈值；未识别类型用默认 FAIL_LIMIT
    _limit = KIND_FAIL_LIMIT.get(fail_kind, FAIL_LIMIT) if fail_kind else FAIL_LIMIT
    ent["fail_kind"] = fail_kind or ent.get("fail_kind", "")
    disabled_now = ""
    if fc >= _limit and name not in whitelist_manual and not ent.get("disabled"):
        ent["disabled"] = True
        ent["disabled_reason"] = f"连续 {fc} 次不达标（{fail_kind or '默认阈值'}>={_limit}），自动停用"
        disabled_now = "disabled_now"
    state[name] = ent
    return disabled_now or "failing"


def sync_blacklist_auto(state: dict):
    """把自动停用的上游回写 blacklist_auto.txt（自动层）。"""
    names = sorted(n for n, v in state.items() if isinstance(v, dict) and v.get("disabled"))
    os.makedirs(os.path.dirname(BLACKLIST_AUTO) or ".", exist_ok=True)
    with open(BLACKLIST_AUTO, "w", encoding="utf-8") as f:
        f.write("# 自动黑名单：连续不达标自动停用的上游（由脚本维护，勿手工编辑）\n")
        for n in names:
            f.write(n + "\n")



# ---------------- 任务5：上游指数退避重试 ----------------
RETRY_FILE = os.environ.get("UPSTREAM_RETRY_FILE", "state/upstream_retry.json")


def _load_json_dict(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json_dict(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def retry_should_skip(url: str, now_naive: datetime) -> bool:
    """next_retry_at 在未来则本轮跳过（指数退避窗口内）。"""
    ent = _load_json_dict(RETRY_FILE).get(url)
    if not ent or ent.get("dead"):
        return False
    nra = ent.get("next_retry_at")
    if not nra:
        return False
    try:
        return datetime.strptime(nra, "%Y-%m-%d %H:%M:%S") > now_naive
    except ValueError:
        return False


def retry_record_success(url: str):
    d = _load_json_dict(RETRY_FILE)
    if url in d:
        d.pop(url, None)
        _save_json_dict(RETRY_FILE, d)


def retry_record_failure(url: str, category: str, now_naive: datetime):
    """失败后 next_retry_at = now + 2^fail_count 天（上限14天）；累计超 30 天标 dead。
    404 走 raw-store 删除保护，不进退避。"""
    if category == "404":
        return
    d = _load_json_dict(RETRY_FILE)
    ent = d.get(url, {"fail_count": 0})
    fc = int(ent.get("fail_count", 0)) + 1
    backoff_days = min(2 ** fc, 14)
    first_fail = ent.get("first_fail_at") or now_naive.strftime("%Y-%m-%d %H:%M:%S")
    try:
        span = (now_naive - datetime.strptime(first_fail, "%Y-%m-%d %H:%M:%S")).days
    except ValueError:
        span = 0
    ent.update({
        "first_fail_at": first_fail,
        "last_fail_at": now_naive.strftime("%Y-%m-%d %H:%M:%S"),
        "fail_count": fc,
        "next_retry_at": (now_naive + timedelta(days=backoff_days)).strftime("%Y-%m-%d %H:%M:%S"),
        "dead": span >= 30,
    })
    d[url] = ent
    _save_json_dict(RETRY_FILE, d)


# ---------------- 任务6：失败原因分类 ----------------
FAILURES_FILE = os.environ.get("UPSTREAM_FAILURES_FILE", "state/upstream_failures.json")


def classify_failure(info, err, raw) -> str:
    """把上游拉取/解析失败归为 404 / timeout / ssl_error / parse_error / empty_product / other。"""
    txt = f"{err or ''} {info or ''}"
    low = txt.lower()
    if "404" in txt:
        return "404"
    if "timed out" in low or "timeout" in low:
        return "timeout"
    if "ssl" in low or "certificate" in low or "cert" in low:
        return "ssl_error"
    if "decode" in low or "json" in low or "parse" in low or "unicode" in low:
        return "parse_error"
    if raw is not None and ("too small" in low or "no usable" in low or ("only" in low and "entries" in low)):
        return "empty_product"
    return "other"


def record_failure(url: str, category: str, detail: str):
    d = _load_json_dict(FAILURES_FILE)
    ent = d.get(url, {"count": 0})
    ent["count"] = int(ent.get("count", 0)) + 1
    ent["last_category"] = category
    ent["last_detail"] = str(detail)[:160]
    ent["last_at"] = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    d[url] = ent
    _save_json_dict(FAILURES_FILE, d)


# ---------------- 任务7：上游拉取延迟记录 ----------------
LATENCY_FILE = os.environ.get("UPSTREAM_LATENCY_FILE", "state/upstream_latency.json")
SLOW_MS = int(os.environ.get("UPSTREAM_SLOW_MS", "30000"))
SLOW_STREAK = int(os.environ.get("UPSTREAM_SLOW_STREAK", "3"))


def _classify_latency_tier(ms: float) -> str:
    """C2：按历史响应时间分三档（<2s 快 / 2-5s 中 / >5s 慢），供调度参考。"""
    if ms < 2000:
        return "fast"
    if ms < 5000:
        return "medium"
    return "slow"


def record_latency(url: str, ms: int):
    """记录单次上游拉取耗时；avg 用 EMA（新=旧*0.7+新*0.3）平滑；连续 >SLOW_MS 次标 slow。"""
    d = _load_json_dict(LATENCY_FILE)
    ent = d.get(url, {"samples": 0, "slow_count": 0})
    n = int(ent.get("samples", 0)) + 1
    prev_avg = float(ent.get("avg_latency", ms))
    # C2：EMA 平滑（新观测权重 0.3，避免单次抖动剧烈改变档位）
    avg = int(prev_avg * 0.7 + ms * 0.3) if n > 1 else ms
    slow_count = int(ent.get("slow_count", 0))
    slow_count = slow_count + 1 if ms > SLOW_MS else 0
    ent.update({"last_latency": ms, "avg_latency": avg, "samples": n,
                "slow_count": slow_count, "slow": slow_count >= SLOW_STREAK,
                "tier": _classify_latency_tier(avg)})
    d[url] = ent
    _save_json_dict(LATENCY_FILE, d)


UPSTREAM_BASELINE_FILE = os.environ.get("UPSTREAM_BASELINE_FILE", "state/upstream_baseline.json")
ANOMALY_ALERTS_FILE = os.environ.get("ANOMALY_ALERTS_FILE", "state/anomaly_alerts.json")


def detect_upstream_anomaly(checks: list, threshold: float = 0.5) -> list:
    """C5：上游内容突变检测——对比 state/upstream_baseline.json，size/条目数超 ±50% 告警。
    新源前 3 轮无基线不告警；只告警不自动停用。结果写 state/anomaly_alerts.json。"""
    baseline = _load_json_dict(UPSTREAM_BASELINE_FILE)
    alerts = []
    for r in checks:
        name = r.get("name")
        if not name or r.get("status") in ("skipped",):
            continue
        prev = baseline.get(name)
        if not prev:
            continue
        cur_size = int(r.get("bytes", 0))
        prev_size = int(prev.get("bytes", 0))
        if prev_size > 0:
            size_ratio = abs(cur_size - prev_size) / prev_size
            if size_ratio > threshold:
                alerts.append({"name": name, "field": "bytes",
                               "prev": prev_size, "cur": cur_size,
                               "ratio": round(size_ratio, 2)})
        prev_sites = int(prev.get("sites", 0))
        cur_sites = int(r.get("sites", 0))
        if prev_sites > 0:
            sites_ratio = abs(cur_sites - prev_sites) / prev_sites
            if sites_ratio > threshold:
                alerts.append({"name": name, "field": "sites",
                               "prev": prev_sites, "cur": cur_sites,
                               "ratio": round(sites_ratio, 2)})
    # 更新基线（本轮成功的上游）
    new_baseline = dict(baseline)
    for r in checks:
        if r.get("bytes"):
            new_baseline[r["name"]] = {"bytes": r.get("bytes", 0),
                                       "sites": r.get("sites", 0),
                                       "updated_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")}
    _save_json_dict(UPSTREAM_BASELINE_FILE, new_baseline)
    if alerts:
        _save_json_dict(ANOMALY_ALERTS_FILE, {"alerts": alerts,
                        "checked_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")})
        print(f"[C5] 上游突变告警 {len(alerts)} 条（state/anomaly_alerts.json）", flush=True)
    return alerts


def load_site_state() -> dict:
    """P1-A：sites 段读自 state/validated.json（单一事实源）。"""
    return _vs.load_validated()["sites"]


def save_site_state(site_state: dict):
    """P1-A：sites 段写回 validated.json（同一事实源文件）。"""
    doc = _vs.load_validated()
    doc["sites"] = site_state
    _vs.save_validated(doc, note="GitHub 线站点验活历史写回（fetch_merge）")


def apply_site_verdict(site_state: dict, key: str, name: str, ok: bool, now: str,
                       fail_kind: str = None) -> dict:
    """O3 站点验活历史记忆：连续 N 轮失败才从配置剔除；任一轮通过即复位（自动回捞）。
    V12：fail_kind=timeout 时阈值放宽到 5 轮（网络抖动宽容）；其余用 SITE_FAIL_LIMIT。"""
    ent = site_state.get(key) if isinstance(site_state.get(key), dict) else {}
    ent["name"] = name
    ent.setdefault("removed", False)
    if ok:
        ent["fails"] = 0
        ent["last_ok_at"] = now
        ent["removed"] = False
        ent.pop("removed_at", None)
    else:
        ent["fails"] = int(ent.get("fails", 0)) + 1
        ent["last_fail_at"] = now
        _limit = 5 if fail_kind == "timeout" else SITE_FAIL_LIMIT
        if ent["fails"] >= _limit and not ent.get("removed"):
            ent["removed"] = True
            ent["removed_at"] = now
    site_state[key] = ent
    return ent


# 3.4-2 / P0-2：人工覆盖表 schema 扩展——同时支持内容分类与接口类型覆盖。
#   内容分类：short / adult / vod   → classify_site 直接短路
#   接口类型：cms / pan / csp       → store_kind_of 直接覆盖（与 rank_sites.type_of 兼容）
CATEGORY_OVERRIDE_VALUES = ("short", "adult", "vod", "cms", "pan", "csp")
CONTENT_CATEGORIES = ("short", "adult", "vod")   # 仅这些会短路 classify_site


def load_category_overrides() -> dict:
    """人工分类覆盖表：{"<site key>": "short|adult|vod|cms|pan|csp"}。
    内容分类(short/adult/vod)优先级高于关键词自动分类；接口类型(cms/pan/csp)供
    store_kind_of 覆盖自动判定（与 Agent B 改的 rank_sites.type_of 兼容）。"""
    try:
        with open(CATEGORY_OVERRIDE_FILE, "r", encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m, dict):
            return {str(k): str(v) for k, v in m.items()
                    if str(v) in CATEGORY_OVERRIDE_VALUES}
    except Exception:  # noqa: BLE001
        pass
    return {}


def enabled_of(u: dict, state: dict, blacklist_manual: list, whitelist_manual: list):
    """返回 (是否拉取, 状态标签)。手动黑名单 > 自动停用（白名单可豁免自动停用）> 启用。
    O2：自动停用超过 PROBE_INTERVAL_DAYS 的上游低频探活一次，成功即自动回捞。"""
    name = u["name"]
    if name in blacklist_manual:
        return False, "blacklisted"
    ent = state.get(name) if isinstance(state.get(name), dict) else {}
    if ent.get("disabled") and name not in whitelist_manual:
        last_fail = ent.get("last_fail_at", "") or ""
        if PROBE_INTERVAL_DAYS > 0 and last_fail:
            try:
                now_naive = datetime.now(BEIJING).replace(tzinfo=None)
                dt = now_naive - datetime.strptime(last_fail, "%Y-%m-%d %H:%M:%S")
                if dt.days >= PROBE_INTERVAL_DAYS:
                    return True, "probe"
            except ValueError:
                pass
        return False, "disabled"
    return True, "enabled"


def upstream_score(name: str, state: dict) -> float:
    """O1 健康度仲裁分：最近成功时间为主（当天 100，每过一天 -10），连续失败每次 -5。
    无成功记录 = 0 分（新上游首轮成功后即达 ~100，可参与同 key 仲裁）。"""
    ent = state.get(name)
    if not isinstance(ent, dict):
        return 0.0
    fc = int(ent.get("fail_count", 0) or 0)
    ok_at = ent.get("last_ok_at", "") or ""
    try:
        # last_ok_at 为北京本地时间字符串（naive），统一按 naive 比较
        now_naive = datetime.now(BEIJING).replace(tzinfo=None)
        days = (now_naive - datetime.strptime(ok_at, "%Y-%m-%d %H:%M:%S")).days
    except (ValueError, TypeError):
        return 0.0
    return max(0.0, 100.0 - days * 10.0) - fc * 5.0


# ---------------- P1：快照存档 ----------------

def snapshot_save(name: str, kind: str, raw: bytes, now: datetime) -> str:
    date_dir = os.path.join(SNAPSHOT_DIR, now.strftime("%Y-%m-%d"))
    os.makedirs(date_dir, exist_ok=True)
    ext = "m3u" if kind == "m3u" else "json"
    path = os.path.join(date_dir, f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}__{now.strftime('%H%M%S')}.{ext}")
    with open(path, "wb") as f:
        f.write(raw)
    return path


def snapshot_prune(keep_days: int) -> list:
    """只保留最近 keep_days 个日期目录，控制仓库体积。"""
    if not os.path.isdir(SNAPSHOT_DIR) or keep_days <= 0:
        return []
    dates = sorted(d for d in os.listdir(SNAPSHOT_DIR)
                   if os.path.isdir(os.path.join(SNAPSHOT_DIR, d)) and re.match(r"^\d{4}-\d{2}-\d{2}$", d))
    removed = []
    for d in dates[:-keep_days]:
        shutil.rmtree(os.path.join(SNAPSHOT_DIR, d), ignore_errors=True)
        removed.append(d)
    return removed


# ---------------- P1：直播分类测速优选 ----------------

def category_of(channel: str, group: str) -> str:
    text = f"{group} {channel}"
    up = text.upper()
    if re.search(r"CCTV|CGTN|CETV|央视", up):
        return "cctv"
    if "卫视" in text:
        return "weishi"
    if re.search(r"香港|台湾|凤凰|TVB|翡翠|明珠|澳门|港台|星空|华视|中天|东森|民视|三立|TVBS|HKTW|HK\b|TW\b", up):
        return "gangtai"
    return "other"


CATEGORY_LABELS = [("cctv", "央视"), ("weishi", "卫视"), ("gangtai", "港台"), ("other", "其他")]


def speed_test(entries, limit: int):
    """并发测速，返回 (lat, spd)。
    lat = {url: latency_ms}，仅 HTTP 200/206 且有数据的 URL 计入；
    spd = {url: MB/s}，对同一请求按实际收到字节数折算吞吐（第一批 P2：
    借鉴 guovin 三维测速中最值得的一维——HTTP Range 抽 LIVE_SPEED_RANGE 字节实测，
    低于 LIVE_MIN_SPEED 的源降权排序、不删除）。
    完全失败的 URL 不在结果里（仍走 O6 保底通道）。"""
    urls = []
    seen = set()
    for _name, _group, url in entries:
        if url not in seen:
            seen.add(url)
            urls.append(url)
    if limit > 0 and len(urls) > limit:
        urls = urls[:limit]  # 顺序即上游优先级，截前 limit 个
    lat = {}
    spd = {}
    print(f"    测速 {len(urls)} 条直播 URL（并发 {LIVE_CONCURRENCY}，单条 {LIVE_TIMEOUT}s，"
          f"Range 抽 {LIVE_SPEED_RANGE >> 10}KB）...", flush=True)

    def probe(u):
        try:
            st, body, ms = http_get(u, LIVE_TIMEOUT, LIVE_SPEED_RANGE,
                                    rng=(0, LIVE_SPEED_RANGE - 1))
            if st in (200, 206) and body:
                dt = ms / 1000.0
                if dt > 0:
                    spd[u] = len(body) / dt / (1 << 20)  # MB/s
                return u, ms
        except Exception:  # noqa: BLE001
            pass
        return u, None

    with cf.ThreadPoolExecutor(LIVE_CONCURRENCY) as ex:
        for u, ms in ex.map(probe, urls):
            if ms is not None:
                lat[u] = ms
    return lat, spd


# ---------------- P0：本地相对路径依赖核验（防死引用写入配置） ----------------

LOCAL_REF_RE = re.compile(r"\./[A-Za-z0-9_\-.\/\u4e00-\u9fff%]+")


def _collect_local_refs(entry) -> list:
    """从站点条目收集 ./ 开头的本地相对路径引用（api/jar/ext 及 ext dict 值）。

    ext 可能是 $$$ 组合串（csp_XBPQ 系：本地路径$$$目标URL$$$参数...），需分段后逐段识别，
    不能把整串当一个本地路径。
    """
    refs: list = []

    def scan(v: str):
        for seg in v.split("$$$"):
            seg = seg.strip()
            if seg.startswith("./"):
                refs.append(seg)
            else:
                refs.extend(m.group(0) for m in LOCAL_REF_RE.finditer(seg))

    if not isinstance(entry, dict):
        return refs
    for field in ("api", "jar", "ext"):
        v = entry.get(field)
        if isinstance(v, str):
            scan(v)
        elif isinstance(v, dict):
            for v2 in v.values():
                if isinstance(v2, str):
                    scan(v2)
    return sorted(set(r[2:] for r in refs if r.startswith("./")))


def _missing_local_refs(entry, repo_dir: str) -> list:
    return [p for p in _collect_local_refs(entry)
            if not os.path.isfile(os.path.join(repo_dir, p))]


def filter_local_ref_sites(sites: list, repo_dir: str, target: str, registry: dict) -> list:
    """写入配置前核验站点 ./ 本地依赖在仓库中真实存在；缺失则剔除该站点并登记到 registry。

    registry 由调用方写入 status.json 的 local_ref_audit，防止每日拉取把死引用写回配置。
    """
    kept, drops = [], []
    for s in sites:
        missing = _missing_local_refs(s, repo_dir)
        if missing:
            drops.append({"key": s.get("key"), "name": s.get("name"), "missing": missing})
        else:
            kept.append(s)
    if drops:
        registry[target] = drops
        print(f"    [local-ref] {target}: 剔除 {len(drops)} 个死引用站点: "
              + ", ".join((d["key"] or "?") for d in drops), flush=True)
    return kept


def build_live_outputs(entries) -> dict:
    """分类 →（可选测速排序）→ 每频道取前 N 条 → 输出 lives/*.txt。返回分类统计 dict。
    测速排序规则（2026-09-21 直播线融合）：吞吐 >= LIVE_MIN_SPEED 的源优先；
    慢速源降权排后但保留（只降权不删除）；完全连不上的 URL 仍剔除走 O6 保底。"""
    os.makedirs(LIVES_DIR, exist_ok=True)
    lat, spd = speed_test(entries, LIVE_MAX_URLS) if LIVE_SPEEDTEST else ({}, {})

    per_cat = {k: [] for k, _ in CATEGORY_LABELS}
    for name, group, url in entries:
        per_cat[category_of(name, group)].append((name, url))

    stats = {}
    for key, label in CATEGORY_LABELS:
        items = per_cat[key]
        if lat:
            by_ch = {}
            for name, url in items:
                ms = lat.get(url)
                if ms is None:
                    continue  # 完全连不上的 URL 剔除（O6 保底兜住）；慢速源不删、仅降权
                by_ch.setdefault(name, []).append((spd.get(url, 0.0), ms, url))
            ranked = []
            for name in sorted(by_ch):
                # 排序键：达速源（吞吐>=LIVE_MIN_SPEED）在前，组内吞吐降序 → 延迟升序 → URL 稳定序
                for _bps, ms, url in sorted(
                        by_ch[name],
                        key=lambda t: (0 if t[0] >= LIVE_MIN_SPEED else 1, -t[0], t[1], t[2])
                )[:LIVE_PER_CHANNEL]:
                    ranked.append((name, url, ms))
            # O6 保底：所有线路测速全挂的频道（多为跑批网络环境误杀）按字母序收录在组尾
            tested_channels = set(by_ch)
            fallback_ch = {}
            for name, url in items:
                if name not in tested_channels:
                    fallback_ch.setdefault(name, []).append(url)
            fallback_used = 0
            for name in sorted(fallback_ch):
                if fallback_used >= LIVE_FALLBACK_CHANNELS:
                    break
                for url in fallback_ch[name][:LIVE_PER_CHANNEL]:
                    ranked.append((name, url, None))
                    fallback_used += 1
        else:
            seen_ch = {}
            ranked = []
            for name, url in items:
                seen_ch.setdefault(name, [])
                if len(seen_ch[name]) < LIVE_PER_CHANNEL:
                    seen_ch[name].append(url)
                    ranked.append((name, url, None))
        stats[key] = {"channels": len({n for n, _u, _ms in ranked}), "urls": len(ranked),
                      "input_urls": len(items), "speed_tested": bool(lat),
                      "slow_speed_urls": (sum(1 for _n, u, ms in ranked
                                              if ms is not None and spd.get(u, 0.0) < LIVE_MIN_SPEED)
                                          if lat else 0),
                      "fallback_urls": (sum(1 for _n, _u, ms in ranked if ms is None) if lat else 0)}
        if not ranked:
            continue
        path = os.path.join(LIVES_DIR, f"live_{key}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{label},#genre#\n")
            for name, url, _ms in ranked:
                f.write(f"{name},{url}\n")
        print(f"    {label}: {stats[key]['channels']} 频道 / {stats[key]['urls']} 条 -> {path}", flush=True)

    with open(os.path.join(LIVES_DIR, "live.txt"), "w", encoding="utf-8") as f:
        for key, _label in CATEGORY_LABELS:
            p = os.path.join(LIVES_DIR, f"live_{key}.txt")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as pf:
                    f.write(pf.read())
    return stats


# ---------------- P1：checks.json + README 回写 ----------------

def sha12(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def _is_local_ref(url) -> bool:
    """url 是否为仓内本地镜像路径（./deps/... 相对路径），而非真实外部 URL。"""
    return isinstance(url, str) and (url.startswith("./") or url.startswith("../"))


# 状态优先级（越小越好），供同名去重时挑「最优状态」。
_STATUS_RANK = {"ok": 0, "probe": 1, "mirror": 1, "degraded": 2,
                "dead": 3, "disabled": 4, "blacklisted": 5}


def dedupe_check_records(records: list) -> list:
    """按上游名去重：把同名「本地镜像 + 真实 URL」双条目合并成一条。

    背景：外部配置本地化后，部分上游在清单里有两条（一条 ./deps/external/ 本地镜像
    + 一条真实外部 URL）。本地镜像读本地文件恒 ok，会掩盖真实 URL 的失效，使
    checks.json / README 表里同一上游出现两行互相矛盾的状态。

    规则（每个 name 留一条）：
      1) 真实外部 URL 优先于本地镜像（即便本地状态更好，也要诚实展示真实 URL）；
      2) 同类（都真实 / 都本地）取最优状态（ok > degraded > dead ...）；
      3) 状态相同取 last_ok_at 更新者。
    保持 name 首次出现顺序，幂等。"""
    by_name = {}
    for r in records:
        n = r.get("name", "")
        cur = by_name.get(n)
        if cur is None:
            by_name[n] = r
            continue
        cur_local = _is_local_ref(cur.get("url", ""))
        new_local = _is_local_ref(r.get("url", ""))
        if cur_local and not new_local:
            by_name[n] = r          # new 是真实 URL，替换本地
            continue
        if new_local and not cur_local:
            continue               # cur 是真实 URL，保留 cur
        cr = _STATUS_RANK.get(cur.get("status", ""), 99)
        nr = _STATUS_RANK.get(r.get("status", ""), 99)
        if nr < cr:
            by_name[n] = r
        elif nr == cr:
            if (r.get("last_ok_at", "") or "") >= (cur.get("last_ok_at", "") or ""):
                by_name[n] = r
    return list(by_name.values())


def write_checks(records: list, generated_at: str) -> dict:
    records = dedupe_check_records(records)
    order = {"ok": 0, "degraded": 1, "dead": 2, "disabled": 3, "blacklisted": 4}
    recs = sorted(records, key=lambda r: order.get(r.get("status"), 5))
    doc = {
        "generated_at": generated_at,
        "note": "每条含最近检测时间、内容 sha256 指纹（前 12 位）、字节数与连续失败计数（azhansy/ds-tvbox checks.json 模式）",
        "summary": {
            "total": len(recs),
            "ok": sum(1 for r in recs if r["status"] == "ok"),
            "degraded": sum(1 for r in recs if r["status"] == "degraded"),
            "dead": sum(1 for r in recs if r["status"] == "dead"),
            "disabled": sum(1 for r in recs if r["status"] == "disabled"),
            "blacklisted": sum(1 for r in recs if r["status"] == "blacklisted"),
        },
        "upstreams": recs,
    }
    with open(CHECKS_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


ICONS = {"ok": "🟢", "degraded": "🟡", "dead": "🔴", "disabled": "⚫", "blacklisted": "🚫"}
STATUS_CN = {"ok": "可用", "degraded": "降级", "dead": "失效", "disabled": "已停用",
             "blacklisted": "黑名单", "probe": "🔵探活", "mirror": "镜像"}


def update_readme_availability(records: list) -> bool:
    """README 内 availability:start/end 锚点间回写可用性表（laoma2053 模式）。"""
    records = dedupe_check_records(records)
    try:
        with open(README_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:  # noqa: BLE001
        return False
    lines = ["| 上游 | 状态 | 字节数 | 指纹 | 连续失败 | 最近通过 |",
             "|------|------|--------|------|----------|----------|"]
    for r in records:
        lines.append(
            "| {name} | {icon} {st} | {bt} | `{fp}` | {fc} | {ok_at} |".format(
                name=r.get("name", ""), icon=ICONS.get(r.get("status"), "⚪"),
                st=STATUS_CN.get(r.get("status"), r.get("status", "")),
                bt=r.get("bytes", 0) or "-", fp=r.get("sha256", "") or "-",
                fc=r.get("fail_count", 0), ok_at=r.get("last_ok_at", "-") or "-"))
    table = "\n".join(lines)
    start = "<!-- availability:start -->"
    end = "<!-- availability:end -->"
    if start in content and end in content:
        pre = content.split(start, 1)[0]
        post = content.split(end, 1)[1]
        content = f"{pre}{start}\n{table}\n{end}{post}"
    else:
        content = content.rstrip() + f"\n\n## 上游可用性（自动回写）\n\n{start}\n{table}\n{end}\n"
    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    return True


# ---------------- 合并辅助（保持既有口径） ----------------

def grade_of(nsites: int, valid: bool) -> str:
    if not valid or nsites <= 0:
        return "不可用"
    if nsites >= 10:
        return "完全可用"
    return "部分可用"


def merge_key_site(s: dict):
    return s.get("key")


def merge_key_live(l: dict):
    return l.get("name")


def merge_key_parse(p: dict):
    return p.get("name")


def site_fingerprint(s: dict) -> str:
    """O4 二级去重指纹：api + ext 内容（不同 key、功能相同的镜像/复刻站点）。"""
    api = (s.get("api") or "").strip().rstrip("/")
    ext = s.get("ext")
    if isinstance(ext, dict):
        ext_s = json.dumps(ext, ensure_ascii=False, sort_keys=True)
    elif isinstance(ext, str):
        ext_s = ext.strip()
    else:
        ext_s = ""
    return hashlib.sha1(f"{api}\n{ext_s}".encode("utf-8")).hexdigest()[:16]


# ---- 站点链接验活缓存（2026-09-28）：链接没变就不重复重测 ----
# 上游仓库照常每轮拉取（拉取阶段不受本缓存影响）；只有「已合并产物的直连站点链接」
# 验活结论按 api+ext 指纹缓存——指纹未变 且 上次通过 且 未超 TTL 时复用结论跳过重测。
# 失败结论不入缓存（下轮照常重测，O3 连续失败剔除与自动回捞语义不变）；
# 指纹变更/新站点/TTL 过期 → 重新实测。TTL 默认 14 天：直连接口长期存活率很高，
# 但站点会悄悄挂，隔两周强制复测一次兜底。
FV_CACHE_FILE = os.environ.get("FV_CACHE_FILE", "state/fv_cache.json")
FV_CACHE_TTL_DAYS = int(os.environ.get("FV_CACHE_TTL_DAYS", "14"))


def load_fv_cache() -> dict:
    """读站点链接验活缓存：{fingerprint: {"ok": True, "ms": int, "ts": epoch, "key": ...}}。"""
    try:
        with open(FV_CACHE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("fvs", {}) if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_fv_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(FV_CACHE_FILE) or ".", exist_ok=True)
    tmp = FV_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
                   "ttl_days": FV_CACHE_TTL_DAYS, "fvs": cache},
                  f, ensure_ascii=False, indent=1)
    os.replace(tmp, FV_CACHE_FILE)


def fv_cache_hit(cache: dict, fp: str) -> bool:
    """指纹命中：上次通过 且 未超 TTL。"""
    c = cache.get(fp)
    if not (isinstance(c, dict) and c.get("ok")):
        return False
    return time.time() - float(c.get("ts", 0)) < FV_CACHE_TTL_DAYS * 86400


def secondary_dedup_sites(sites_by_key: dict, site_origin_name: dict, site_origin_score: dict) -> list:
    """O4 二级去重：api+ext 指纹相同的站点只留一份，保留来源健康分高者（同分保留先收录者）。
    返回剔除明细列表。"""
    groups: dict = {}
    for k, s in sites_by_key.items():
        groups.setdefault(site_fingerprint(s), []).append(k)
    dropped = []
    for keys in groups.values():
        if len(keys) < 2:
            continue
        keys.sort(key=lambda k: (-(site_origin_score.get(k) or 0.0), k))
        keeper = keys[0]
        for k in keys[1:]:
            dropped.append({"dropped_key": k, "kept_key": keeper,
                            "dropped_origin": site_origin_name.get(k, ""),
                            "kept_origin": site_origin_name.get(keeper, "")})
            sites_by_key.pop(k, None)
            site_origin_name.pop(k, None)
            site_origin_score.pop(k, None)
    return dropped


# ---------------- 三级去重：同库镜像站（片名指纹，证据来自 scripts/probe_sites.py） ----------------
# 一级按 key、二级按 api+ext 指纹都抓不到「同库换域名/换路径」的重复：
#   zuidapi.com 与 zuidazy.co、sdzyapi.com 与 xsd.sdzyapi.com、
#   bfzyapi.com/api.php/provide/vod 与 .../vod/?ac=list
# probe_sites.py 在 L1 抓到的片名集合做 Jaccard 判定（实测 96 个源里 61 个属镜像冗余），
# 结果落在 state/mirror_groups.json，合并阶段据此只保留可用性最好的一份。
MIRROR_GROUPS_FILE = os.environ.get("MIRROR_GROUPS_FILE", "state/mirror_groups.json")
MIRROR_DEDUP = os.environ.get("MIRROR_DEDUP", "1") == "1"


def load_mirror_groups() -> dict:
    """读取镜像分组，返回 {被剔除的 key: 保留的 key}。文件缺失或关闭开关时返回空。"""
    if not MIRROR_DEDUP or not os.path.isfile(MIRROR_GROUPS_FILE):
        return {}
    try:
        with open(MIRROR_GROUPS_FILE, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    mapping = {}
    for g in doc.get("groups", []):
        keep = (g.get("keep") or {}).get("key")
        if not keep:
            continue
        for d in g.get("drops", []):
            if d.get("key"):
                mapping[d["key"]] = keep
    return mapping


def apply_mirror_dedup(sites_by_key: dict, site_origin_name: dict, site_origin_score: dict) -> list:
    """三级去重：剔除同库镜像站点，保留可用性最好的一份。

    仅当保留者本身还在集合中时才剔除，避免出现「剔了重复、留下的也已被删」的空洞。
    """
    mapping = load_mirror_groups()
    if not mapping:
        return []
    dropped = []
    for key, keep in mapping.items():
        if key not in sites_by_key or keep not in sites_by_key:
            continue
        s = sites_by_key.pop(key)
        site_origin_name.pop(key, None)
        site_origin_score.pop(key, None)
        dropped.append({"dropped_key": key, "kept_key": keep,
                        "dropped_name": s.get("name"), "reason": "同库镜像（片名指纹）"})
    return dropped


SORT_ENABLED = os.environ.get("SITE_RANK", "1") == "1"
PROBE_FILE = os.environ.get("PROBE_FILE", "probe/sites_probe.json")
SPIDER_PROBE_FILE = os.environ.get("SPIDER_PROBE_FILE", "probe/spider_probe.json")
JS_PROBE_FILE = os.environ.get("JS_PROBE_FILE", "probe/js_probe.json")
# 真机 csp 实测产物（.workbuddy/csp-test 跑出来后提交进仓库，CI 侧只读复用）
CSP_PROBE_FILE = os.environ.get("CSP_PROBE_FILE", "probe/csp_probe.json")


def merge_check_latency(probe_path: str, latency: dict, now_str: str) -> dict:
    """把 [3/6] 验活实测的「取到内容耗时」合并进 sites_probe.json。

    每条站点记录新增 check_ms / check_at 附加字段——不动 l1/l2 等探针原字段，
    不影响搜索可用性判定；rank_sites.speed_of 会优先使用新鲜的 check_ms 排序。
    """
    doc: dict = {}
    if os.path.isfile(probe_path):
        try:
            with open(probe_path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            doc = {}
    if not isinstance(doc, dict):
        doc = {}
    entries = {r.get("key"): r for r in (doc.get("sites") or [])
               if isinstance(r, dict) and r.get("key")}
    for key, ms in (latency or {}).items():
        ent = entries.get(key)
        if ent is None:
            ent = {"key": key}
            entries[key] = ent
            doc.setdefault("sites", []).append(ent)
        ent["check_ms"] = int(ms)
        ent["check_at"] = now_str
    doc["check_summary"] = {
        "generated_at": now_str,
        "measured": len(latency or {}),
        "unit": "ms；取到有效配置内容的完整耗时（DNS+建连+正文读取）",
    }
    try:
        with open(probe_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
    except OSError:
        return {"written": 0}
    return {"written": len(latency or {})}


def apply_rank(tvbox: dict) -> dict:
    """按「分类 → 搜索可用性 → 实测速度」重排 sites，并写 group / 校正 searchable。

    排序键：分类分组 → 实测可搜优先 → 实测速度升序（无速度的按结构完整度兜底）。
    探针产物缺失时静默跳过，绝不因为缺测速数据而影响出配置。
    """
    if not SORT_ENABLED:
        return {}
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        from rank_sites import rank_sites  # noqa: PLC0415
    except ImportError:
        print("    排序模块不可用（scripts/rank_sites.py 缺失），跳过排序", flush=True)
        return {}

    def _load(path):
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    probe, spider = _load(PROBE_FILE), _load(SPIDER_PROBE_FILE)
    js_probe = _load(JS_PROBE_FILE)
    csp_probe = _load(CSP_PROBE_FILE)
    if not probe and not spider and not js_probe and not csp_probe:
        print("    无探针产物，跳过排序（先跑 scripts/probe_*.py）", flush=True)
        return {}
    ranked, stats = rank_sites(tvbox.get("sites") or [], probe, spider, None, js_probe, csp_probe)
    tvbox["sites"] = ranked
    groups = {k.split(":", 1)[1]: v for k, v in stats.items() if k.startswith("group:")}
    speed = {k.split(":", 1)[1]: v for k, v in stats.items() if k.startswith("speed:")}
    fixes = {k.split(":", 1)[1]: v for k, v in stats.items() if k.startswith("searchable:")}
    print(f"    分类分组：{groups}", flush=True)
    print(f"    速度数据：{speed}；searchable 校正：{fixes}", flush=True)
    return dict(stats)


def rewrite_gh(value):
    """对 site/live/parse 字段里的 GitHub 原链统一加主镜像前缀（先过域名替换层）。"""
    if isinstance(value, str):
        return gh_url(map_domain(value))
    if isinstance(value, list):
        return [rewrite_gh(v) for v in value]
    if isinstance(value, dict):
        return {k: rewrite_gh(v) for k, v in value.items()}
    return value




# ---------------- 多仓拆分（stores/）：按接口类型归类 + cms/app 实测排序 + 网盘 CK 清单 ----------------

STORES_DIR = os.environ.get("STORES_DIR", "stores")
STORE_TIMEOUT = int(os.environ.get("STORE_TIMEOUT", "6"))
STORE_CONCURRENCY = int(os.environ.get("STORE_CONCURRENCY", "16"))
# CMS 标准接口形态：api.php 系（type0 xml / type1 json）、provide/vod、inc/api 及苹果CMS 变体
CMS_API_RE = re.compile(r"api\.php|provide/vod|inc/api|atas\.php", re.I)
# 网盘类 csp 识别：key / name / ext 三路命中（key、name 任一命中即归网盘仓）
PAN_KEY_RE = re.compile(
    r"pan|quark|ucshare|aliyun|thunder|xunlei|pikpak|(^|[^0-9])115|pan123|baidu|tianyi|guangya|"
    r"panso|pika|hunhe|miaosou|dapan|qianfan|yiso|zhaozy|upyun|funletu|gitcafe|webdav|alist|"
    r"clouddrive|share|yunpan|yunso|yundisk", re.I)
PAN_NAME_RE = re.compile(
    r"网盘|夸克|阿里云|迅雷|天翼|移动云|云盘|115|PikPak|123盘|百度盘|UC盘|盘搜|聚合盘|阿里盘", re.I)
PAN_EXT_RE = re.compile(
    r"token\.json|quark|aliyundrive|pikpak|yun\.139|189pc|thunder|mypikpak", re.I)

# 网盘 CK 获取端点表：ck_field 与 token.json 字段一一对应（实测后随 stores/pan_ck.json 发布）。
# 注：api.extscreen.com/aliyundrive/token 直接来自 token.json 的 open_api_url 字段，其余为各盘官方登录入口。
PAN_CK_ENDPOINTS = [
    {"disk": "阿里云盘", "ck_field": "token / open_token", "method": "POST 中转",
     "api": "http://api.extscreen.com/aliyundrive/token",
     "note": "open_api_url 默认中转，POST 传 refresh_token 换 open_token"},
    {"disk": "夸克网盘", "ck_field": "quark_cookie", "method": "网页登录",
     "api": "https://pan.quark.cn", "note": "浏览器登录后 F12 复制 Cookie 全量"},
    {"disk": "UC网盘", "ck_field": "uc_cookie", "method": "网页登录",
     "api": "https://drive.uc.cn", "note": "浏览器登录后 F12 复制 Cookie 全量"},
    {"disk": "天翼云盘", "ck_field": "thunder_username/password + captchatoken", "method": "账密+验证码",
     "api": "https://m.cloud.189.cn/login.html", "note": "账密写入 token.json，登录需验证码"},
    {"disk": "115网盘", "ck_field": "cookie(UID/CID/SEID)", "method": "扫码",
     "api": "https://qrcodeapi.115.com/api/1.0/user/1.0/qrcode/token/", "note": "扫码拿二维码 → 轮询确认换 cookie"},
    {"disk": "PikPak", "ck_field": "pikpak_username/password", "method": "账密",
     "api": "https://user.mypikpak.com/v1/auth/token", "note": "OAuth password grant，账密直接换 token"},
    {"disk": "移动云盘", "ck_field": "yd_auth", "method": "App 抓包",
     "api": "https://passport.yun.139.com", "note": "App 登录后抓包取 auth 值"},
    {"disk": "百度网盘", "ck_field": "cookie(BDUSS)", "method": "网页登录",
     "api": "https://pan.baidu.com", "note": "浏览器登录后复制 BDUSS"},
]


def store_kind_of(s: dict, overrides: dict) -> str:
    """站点 → 子仓归类：cms / app / pan / csp。short/adult 已有独立产物（short/adult.json），此处跳过。
    3.4-2：人工覆盖表若给出 cms/pan/csp 接口类型，直接采用（与 rank_sites.type_of 兼容）。"""
    if classify_site(s, overrides) in ("short", "adult"):
        return "skip"
    # 3.4-2：人工接口类型覆盖优先
    _ov = (overrides or {}).get(s.get("key") or "")
    if _ov in ("cms", "pan", "csp"):
        return _ov
    t = s.get("type")
    if t in (0, 1, "0", "1"):
        api = str(s.get("api") or "")
        return "cms" if CMS_API_RE.search(api) else "app"
    key = str(s.get("key") or "")
    name = str(s.get("name") or "")
    ext = s.get("ext")
    if isinstance(ext, str):
        ext_s = ext
    elif ext is None:
        ext_s = ""
    else:
        try:
            ext_s = json.dumps(ext, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            ext_s = ""
    if PAN_KEY_RE.search(key) or PAN_NAME_RE.search(name) or PAN_EXT_RE.search(ext_s):
        return "pan"
    return "csp"


def cms_speed_test(sites: list) -> dict:
    """对 cms/app 站点 api 并发探测（追加 ac=list），返回 {api: ms}（失败不在结果里）。"""
    apis, seen = [], set()
    for s in sites:
        api = str(s.get("api") or "")
        if api.startswith(("http://", "https://")) and api not in seen:
            seen.add(api)
            apis.append(api)

    def probe(api):
        u = api + ("&" if "?" in api else "?") + "ac=list"
        try:
            st, body, ms = http_get(u, STORE_TIMEOUT, 4096)
            if st == 200 and body:
                return api, ms
        except Exception:  # noqa: BLE001
            pass
        return api, None

    lat: dict = {}
    print(f"    多仓：cms/app 接口测速 {len(apis)} 条（并发 {STORE_CONCURRENCY}，超时 {STORE_TIMEOUT}s）...", flush=True)
    with cf.ThreadPoolExecutor(STORE_CONCURRENCY) as ex:
        for api, ms in ex.map(probe, apis):
            if ms is not None:
                lat[api] = ms
    return lat


def _absolutize(v, base: str = None):
    """子仓内 ./ 相对引用 → 仓库绝对路径（默认 REPO_RAW，代理版传镜像前缀 base）。

    子仓位于 stores/ 下，TVBox 按配置 URL 解析相对路径，不改写会指向 stores/deps/ 而失效；
    ext 支持 $$$ 组合串，需逐段改写；产物为 raw 链接，经 gh_url 套镜像前缀（用户设备直连不了 raw）。"""
    base = base or REPO_RAW
    if isinstance(v, str):
        if "$$$" in v:
            return "$$$".join(_absolutize(seg, base) for seg in v.split("$$$"))
        if v.startswith("./"):
            return gh_url(f"{base}/{v[2:]}")
        return v
    if isinstance(v, list):
        return [_absolutize(x, base) for x in v]
    if isinstance(v, dict):
        return {k: _absolutize(x, base) for k, x in v.items()}
    return v


def csp_searchable_filter(sites: list, repo_dir: str) -> tuple:
    """蜘蛛仓只保留可搜索的接口（2026-09-19 用户指令「核心逻辑只保留可搜索的接口」）。

    信号链（有证据才剔，证据不足保留，不误杀）：
      1. site 显式 searchable == 0 → 剔（上游明说不支持搜索）
      2. ext dict 显式 searchable == 0 → 剔
      3. ext 为本地 ./deps/... 但文件不存在 → 剔（ext 404 站点加载即失败，必然搜不了）
      4. ext 为本地 .js 且文件在盘上：内容含 searchable: 0 → 剔（drpy js 惯例 0/1/2，取头部 64KB 判定）
    返回 (kept, dropped, stats)。"""
    import collections
    dropped: list = []
    by_reason: collections.Counter = collections.Counter()

    def drop(s, why):
        by_reason[why] += 1
        if len(dropped) < 200:
            dropped.append({"key": s.get("key"), "name": s.get("name"), "reason": why})

    kept = []
    for s in sites:
        if str(s.get("searchable")) == "0":
            drop(s, "site.searchable=0")
            continue
        v = s.get("ext")
        if isinstance(v, dict):
            if str(v.get("searchable")) == "0":
                drop(s, "ext.searchable=0")
            else:
                kept.append(s)
            continue
        if isinstance(v, str) and v.strip().startswith("./"):
            p = v.strip().split(";")[0][2:]
            fp = os.path.join(repo_dir, p)
            if not os.path.isfile(fp):
                drop(s, "ext文件缺失(死源)")
                continue
            try:
                with open(fp, "rb") as f:
                    head = f.read(65536).decode("utf-8", "ignore")
            except OSError:
                kept.append(s)
                continue
            if re.search(r"searchable\s*[:=]\s*0\b", head):
                drop(s, "js.searchable=0")
            else:
                kept.append(s)
            continue
        kept.append(s)  # 无 ext / http ext / 无标注：证据不足，保留
    stats = {"total": len(sites), "kept": len(kept), "dropped": len(sites) - len(kept),
             "by_reason": dict(by_reason), "dropped_sample": dropped}
    return kept, dropped, stats


# 2026-09-29 决策：主产物不带健康标注。实测 _health/_checked_at/_latency_ms 三字段
# 让 index.html 订阅入口发的 tvbox.json 从 1.29MB 涨到 1.67MB（+29%），而 TVBox 只忽略
# 未知字段、不消费它。健康结论留在 exports/all.json（export_healthy 从 DB 现取，
# 与产物剥离无关）和 state/tvbox.db 里，需要的人看那里。


def _strip_internal_fields(doc):
    """P0-3 辅助字段剥离：递归删除以 _ 开头的内部字段（_origin/_health/_probe_* 等）。
    TVBox 客户端虽自动忽略未知字段，剥离可减小体积并避免泄漏内部状态。
    注意：必须在排序完成后、序列化前调用（adult 排序依赖 _origin）。"""
    if isinstance(doc, dict):
        return {k: _strip_internal_fields(v) for k, v in doc.items()
                if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(doc, list):
        return [_strip_internal_fields(v) for v in doc]
    return doc


# 注（2026-09-29 流程重排）：曾在此处放"新源当天补测"过渡函数；探针已整体后置到
# 拉取合并之后（daily.yml），当天拉当天测由流程顺序保证。
# 同批删除的还有 attach_site_health（主产物 _health 标注）：它让 tvbox.json 体积 +29%
# 而客户端不消费该字段，健康结论走 exports/all.json + DB。


def build_stores(vod: dict, overrides: dict, repo_dir: str) -> dict:
    """按接口类型拆分多仓并写 stores/*.json，返回写入 status.json 的摘要。

    产物：
      stores/cms.json    CMS 标准接口（type 0/1，api.php 系），按实测延迟升序
      stores/app.json    App 型接口（type 0/1 非标准 api），按实测延迟升序
      stores/pan.json    网盘类 csp（需 token.json 填 CK 的均在其中，needs_ck 标记）
      stores/csp.json    其余 csp 蜘蛛站
      stores/pan_ck.json 网盘 CK 获取指引（端点实测可达性）
      stores/duocang.json 多仓入口（纯 urls 格式，条目直挂配置本体，只含 CMS/蜘蛛两条代理线路）
    每个子仓自带 spider/parses/wallpaper/flags 可独立挂载；./ 相对依赖改写为仓库绝对路径并套镜像前缀。
    """
    sites = vod.get("sites") or []
    kinds: dict = {}
    for i, s in enumerate(sites):
        kinds.setdefault(store_kind_of(s, overrides), []).append((i, s))
    cms_app = kinds.get("cms", []) + kinds.get("app", [])
    lat = cms_speed_test([s for _, s in cms_app])

    def ordered(pairs):
        # 实测延迟升序，未测出（失败/超时）置尾；同延迟保持原相对顺序
        return [s for _, s in sorted(pairs, key=lambda t: (lat.get(str(t[1].get("api") or ""), 10 ** 9), t[0]))]

    gh1 = GH_MIRRORS[0].rstrip("/")  # 常量自带尾部斜杠，去重避免出现 //https:// 双斜杠

    def mkdoc(ss):
        doc = {f: _absolutize(vod[f], REPO_RAW)
               for f in ("spider", "wallpaper", "parses", "flags") if vod.get(f) is not None}
        ss2 = []
        for s in ss:
            s2 = dict(s)
            for f in ("jar", "ext"):
                if f in s2:
                    s2[f] = _absolutize(s2[f], REPO_RAW)
            ss2.append(s2)
        doc["sites"] = ss2
        # P0-3：子仓产物同样剥离内部字段（_origin 等）
        return _strip_internal_fields(doc)

    os.makedirs(STORES_DIR, exist_ok=True)
    counts: dict = {}
    stores_meta = (("cms", "cms.json", "CMS接口仓(按速度排序)"),
                   ("app", "app.json", "App接口仓(按速度排序)"),
                   ("pan", "pan.json", "网盘仓"),
                   ("csp", "csp.json", "蜘蛛仓(csp)"))
    csp_filter_stats = None
    for k, fname, _label in stores_meta:
        if k in ("cms", "app"):
            ss = ordered(kinds.get(k, []))
        elif k == "csp":
            # 蜘蛛仓只保留可搜索的接口（用户指令），剔除明细见 status.json
            ss, _csp_dropped, csp_filter_stats = csp_searchable_filter(
                [s for _, s in kinds.get(k, [])], repo_dir)
        else:
            ss = [s for _, s in kinds.get(k, [])]
        with open(os.path.join(STORES_DIR, fname), "w", encoding="utf-8") as f:
            json.dump(mkdoc(ss), f, ensure_ascii=False, indent=1)
        counts[k] = len(ss)

    # 网盘 CK 清单：needs_ck = ext 引用 token.json（需填 CK/账密才出内容）
    pan_rows = []
    for _, s in kinds.get("pan", []):
        ext = s.get("ext")
        ext_s = ext if isinstance(ext, str) else (json.dumps(ext, ensure_ascii=False) if ext else "")
        pan_rows.append({"key": s.get("key"), "name": s.get("name"),
                         "needs_ck": bool(ext_s and "token.json" in ext_s)})
    pan_rows.sort(key=lambda r: (not r["needs_ck"], str(r["name"])))

    # CK 获取端点实测：服务端有响应（含非 2xx）即算可达
    ck_endpoints = []
    for e in PAN_CK_ENDPOINTS:
        rec = dict(e)
        try:
            st, _body, ms = http_get(e["api"], 8, 512)
            rec.update({"reachable": True, "http_status": st, "ms": ms})
        except urllib.error.HTTPError as he:
            # 非 2xx 也是服务端真实响应（POST-only 端点对 GET 回 404/405 属正常）＝域名可达
            rec.update({"reachable": True, "http_status": he.code})
        except Exception as ex_:  # noqa: BLE001
            rec.update({"reachable": False, "err": f"{type(ex_).__name__}: {ex_}"[:120]})
        ck_endpoints.append(rec)
    with open(os.path.join(STORES_DIR, "pan_ck.json"), "w", encoding="utf-8") as f:
        json.dump({
            "note": "网盘 CK 填写指引：CK/账密统一填本仓库 deps/json/token.json（字段见各站点 ck_field）；"
                    "该文件非空时 daily 保留现值不回源覆盖",
            "token_file": "./deps/json/token.json",
            "endpoints": ck_endpoints,
        }, f, ensure_ascii=False, indent=1)

    # 多仓入口：对齐社区标准格式（参考 z.qiqiv.cn/123.txt）——顶层只有 urls、条目直挂配置本体。
    # 实测教训（2026-09-19 用户影视仓截图「Json解析失败No value for urls」）：storeHouse+urls 双格式会让
    # 影视仓走 storeHouse 分支、把条目再按「仓」解析（要求 urls），直挂的 sites 配置就会报错；
    # 纯 urls 格式下 App 把条目当配置加载，与参考仓行为一致。
    # 用户指定（2026-09-19）：入口只保留 CMS 接口仓与蜘蛛仓两条线路（App 接口仓、网盘仓不进入口，
    # 对应文件仍照常生成，可单独挂载）；「代理」指入口 JSON 本身经 ghproxy 镜像加速拉取。
    # 依赖引用一律仓库路径（用户指令「依赖文件落库，相关的路径引用改成仓库路径」）：
    # 子仓内部 spider/ext 引用为 raw.githubusercontent.com 本仓库绝对路径（_absolutize 产出），
    # 第三方静态依赖已由 collect_and_rewrite_deps + localize_external_refs 落库 deps/，
    # 不再生成 *_proxy.json 镜像前缀变体（用户网络实测可达 raw，镜像前缀反而引入单点故障）。
    entry = []
    for k, fname, label in stores_meta:
        if k in ("app", "pan"):
            continue
        entry.append({"url": f"{gh1}/{REPO_RAW}/stores/{fname}", "name": f"{label}·代理"})
    duocang = {"urls": entry}
    with open(os.path.join(STORES_DIR, "duocang.json"), "w", encoding="utf-8") as f:
        json.dump(duocang, f, ensure_ascii=False, indent=1)

    def top10(k):
        return [{"name": s.get("name"), "ms": lat[str(s.get("api") or "")]}
                for s in ordered(kinds.get(k, []))[:10] if str(s.get("api") or "") in lat]

    # P1-6：多仓路径校验——扫描子仓 JSON 文本里残留的第三方静态依赖 URL（.js/.jar/.json/.txt）
    _LEFTOVER_RE = re.compile(r"""https?://[^"\s]+\.(?:js|jar|json|txt)(?:\?[^"\s]*)?""")
    _leftover = []
    for _k, _fname, _ in stores_meta:
        _fp = os.path.join(STORES_DIR, _fname)
        if not os.path.isfile(_fp):
            continue
        try:
            _txt = open(_fp, encoding="utf-8").read()
        except OSError:
            continue
        for _m in _LEFTOVER_RE.finditer(_txt):
            _u = _m.group(0)
            if REPO_RAW not in _u and "127.0.0.1" not in _u and "localhost" not in _u:
                _leftover.append({"file": _fname, "url": _u[:100]})
    if _leftover:
        print(f"    [P1-6] WARN 子仓残留第三方静态依赖 URL {len(_leftover)} 处（应已落库 deps/）", flush=True)
        for _l in _leftover[:5]:
            print(f"      - {_l['file']}: {_l['url']}", flush=True)

    print(f"[5.5/6] 多仓：cms {counts['cms']} / app {counts['app']} / pan {counts['pan']} / csp {counts['csp']}"
          f" → stores/（接口测速通过 {len(lat)}/{len(cms_app)}）", flush=True)
    return {
        "note": "按接口类型拆分多仓：cms/app 按实测延迟升序；stores/duocang.json 为多仓入口（纯 urls 格式对齐社区标准，只含 CMS/蜘蛛两条代理线路）；子仓内部依赖引用一律本仓库路径（第三方静态依赖已落库 deps/localized/）",
        "counts": counts,
        "entry_mirror": gh1,
        "speed_tested": len(cms_app),
        "speed_ok": len(lat),
        "csp_searchable_filter": ({"total": csp_filter_stats["total"],
                                   "kept": csp_filter_stats["kept"],
                                   "dropped": csp_filter_stats["dropped"],
                                   "by_reason": csp_filter_stats["by_reason"]}
                                  if csp_filter_stats else None),
        "cms_speed_top10": top10("cms"),
        "app_speed_top10": top10("app"),
        "pan_sites": pan_rows,
        "pan_ck_endpoints": [{"disk": e["disk"], "api": e["api"], "reachable": e.get("reachable", False),
                              "http_status": e.get("http_status")} for e in ck_endpoints],
    }


# ---- 2026-09-21 点播+容错线：容错函数化（便于构造空场景做单元测试）----

def read_prev_counts(path="tvbox.json") -> dict:
    """读上一版产物（工作树 tvbox.json）的三类条目数；读不到返回 {}。"""
    try:
        with open(path, "r", encoding="utf-8") as _f:
            _p = json.load(_f)
        return {"sites": len(_p.get("sites") or []),
                "lives": len(_p.get("lives") or []),
                "parses": len(_p.get("parses") or [])}
    except Exception:  # noqa: BLE001 —— 首轮无历史产物属正常
        return {}


def _quick_probe_sites(new_sites: list, concurrency: int = 8, timeout: int = 5) -> dict:
    """C4 新源零延迟验活：新上游入库后立即测其贡献站点的前 3 个 api，2/3 过即 healthy。
    只标记不剔除；结果写 probe/new_sites.json（供下轮调度/人工巡检参考）。"""
    results = {}

    def _probe_one(s):
        api = s.get("api")
        if not isinstance(api, str) or not api.startswith("http"):
            return s.get("key"), {"name": s.get("name"), "api": api, "ok": None, "reason": "non-http-api"}
        try:
            st, body, ms = http_get(api, timeout, 4096)
            head = (body or b"")[:1024].lstrip()
            ok = bool(st == 200 and body and head[:1] in (b"{", b"<") and b"<html" not in head.lower())
            return s.get("key"), {"name": s.get("name"), "api": api, "ok": ok, "ms": ms, "status": st}
        except Exception as e:  # noqa: BLE001
            return s.get("key"), {"name": s.get("name"), "api": api, "ok": False, "reason": type(e).__name__}

    sample = [s for s in new_sites if isinstance(s, dict)][:3]
    if sample:
        with cf.ThreadPoolExecutor(concurrency) as ex:
            for k, v in ex.map(_probe_one, sample):
                results[k] = v
    healthy = sum(1 for v in results.values() if v.get("ok"))
    verdict = "healthy" if healthy >= 2 else ("weak" if healthy == 1 else "dead")
    out = {"checked_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
           "sampled": len(results), "healthy": healthy, "verdict": verdict, "sites": results}
    os.makedirs("probe", exist_ok=True)
    try:
        with open("probe/new_sites.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return out


def empty_guard_check(cur: dict, prev: dict, drop_ratio: float = None) -> list:
    """空产物守卫判定：返回触发原因列表（空列表 = 通过）。
    任一维度为 0，或相对上一版萎缩超 drop_ratio，即判定本轮产物异常。"""
    if drop_ratio is None:
        drop_ratio = EMPTY_GUARD_DROP_RATIO
    blocked = []
    for _dim, _cnt in cur.items():
        if _cnt == 0:
            blocked.append(f"{_dim}=0（空产物）")
        elif prev.get(_dim, 0) > 0 and _cnt < prev[_dim] * (1 - drop_ratio):
            blocked.append(f"{_dim} {prev[_dim]}→{_cnt}（萎缩超 {drop_ratio:.0%}）")
    return blocked


def apply_blacklist_round_cap(state: dict, disabled_now_list: list,
                              round_total: int, ratio: float = None) -> list:
    """黑名单单轮安全阀：本轮拟停用数超过上游总数 ratio（默认 30%）时判定为
    网络抖动等单轮系统性误判，回滚全部 disabled 标志（fail_count 保留，
    sync_blacklist_auto 按 disabled 标志回写，故黑名单文件本轮不会有任何新增），
    返回回滚后的空列表；未超阈值时原样返回。"""
    if ratio is None:
        ratio = BLACKLIST_ROUND_CAP_RATIO
    round_cap = max(1, int(round_total * ratio))
    if not disabled_now_list or len(disabled_now_list) <= round_cap:
        return disabled_now_list
    print(f"  [安全阀] 本轮拟自动停用 {len(disabled_now_list)} 个，超过上游总数 {round_total} 的 "
          f"{ratio:.0%}（阈值 {round_cap} 个）——判定为网络抖动等单轮系统性误判："
          f"全部回滚、不落盘黑名单（fail_count 保留，真失效下轮仍会正常停用）", flush=True)
    print(f"  [安全阀] 回滚名单：{', '.join(disabled_now_list)}", flush=True)
    for _n in disabled_now_list:
        _ent = state.get(_n)
        if isinstance(_ent, dict) and _ent.get("disabled"):
            _ent["disabled"] = False
            _ent["disabled_reason"] = ""
    return []


def main() -> int:
    global DOMAIN_MAP
    DOMAIN_MAP = load_domain_map()
    now = datetime.now(BEIJING)
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S") + " +08:00"

    state = load_state()
    site_state = load_site_state()          # O3 站点验活历史
    category_overrides = load_category_overrides()  # 人工分类覆盖表
    blacklist_manual = read_name_list(BLACKLIST_MANUAL)
    whitelist_manual = read_name_list(WHITELIST_MANUAL)

    interfaces = []          # 每条上游的测试记录（list.json，保持原字段）
    checks = []              # P1 校验状态记录（checks.json）
    merged: dict = {}        # 全局字段
    spider_origin_info = None
    site_origin_name: dict = {}   # site key -> 来源上游名
    upstream_spider: dict = {}     # 上游名 -> 它自己声明的顶层 spider（合并只能留一份全局的，其余靠它补回）
    site_origin_score: dict = {}  # site key -> 来源上游健康分（O1 同 key 仲裁）
    live_origin_score: dict = {}  # live name -> 来源上游健康分
    parse_origin_score: dict = {} # parse name -> 来源上游健康分
    seen_sha: dict = {}           # 内容 sha12 -> 首个上游名（O5 镜像短路）
    mirror_count = 0
    sites_by_key: dict = {}
    lives_by_name: dict = {}
    parses_by_name: dict = {}

    # 任务2a：拉取前跨列表 URL 去重（UPSTREAMS/LIVE_UPSTREAMS/SHORTS_ADULT_UPSTREAMS + extra）
    # 保留先出现的条目；同 URL 后出现的剔除。
    _seen_urls: dict = {}
    _deduped_upstreams: list = []
    _dup_urls: list = []
    for _u in (ALL_UPSTREAMS + load_extra_upstreams()):
        _ukey = _u.get("url", "")
        if _ukey in _seen_urls:
            _dup_urls.append(_ukey)
            continue
        _seen_urls[_ukey] = True
        _deduped_upstreams.append(_u)
    _raw_count = len(ALL_UPSTREAMS) + len(load_extra_upstreams())
    active_upstreams = _deduped_upstreams
    if _dup_urls:
        print(f"[1/6] 上游 URL 去重：{_raw_count} → {len(active_upstreams)}（剔除 {len(_dup_urls)} 个重复）", flush=True)
        for _d in _dup_urls[:10]:
            print(f"      - 重复跳过：{_d[:90]}", flush=True)

    for u in active_upstreams:          # canary 上游的相对路径依赖也要能解析
        if u.get("kind") == "tvbox" and u.get("name") not in UPSTREAM_BASES:
            UPSTREAM_BASES[u["name"]] = u["url"].rsplit("/", 1)[0] + "/"
    print(f"[1/6] 拉取 {len(active_upstreams)} 个上游（含 {len(LIVE_UPSTREAMS)} 个直播源上游）...", flush=True)
    fetchable = []
    now_naive = now.replace(tzinfo=None)
    for u in active_upstreams:
        ok, tag = enabled_of(u, state, blacklist_manual, whitelist_manual)
        if ok and retry_should_skip(u["url"], now_naive):
            ok, tag = False, "backoff"   # 任务5：指数退避窗口内本轮跳过
        fetchable.append((u, ok, tag))

    def do_fetch(item):
        u, ok, _tag = item
        if not ok:
            return u, None, "skipped", "", "", None, 0
        _t0 = time.time()
        # C1：conditional=True 启用 ETag/If-Modified-Since 增量拉取（仅 GitHub raw 直连）
        raw, info, ok_url = fetch_raw(u["url"], u.get("mirrors"), conditional=True)
        fetch_ms = int((time.time() - _t0) * 1000)
        d_method = ""
        raw_st = None
        store_dir = os.path.join(raw_store.RAW_DIR, "live" if u["kind"] == "m3u" else "vod")
        # C1：304 Not Modified → 直接读 raw-store 最后版本，不重新入库（内容未变）
        if info == "304_not_modified" and raw_store.ENABLED:
            stored = raw_store.read_stored(store_dir, u["name"])
            if stored is not None:
                raw = stored
                info = "304 Not Modified（raw-store 沿用最后版本，未重新入库）"
                raw_st = "not_modified"
        if raw_store.ENABLED:
            # ---- 输入层原始源镜像入库（2026-09-27 落库改造）----
            # 入库的是「下载到的原始字节」（解码前），保证 raw/ 是真正的上游原样留档。
            if raw is None:
                # 上游删除保护：拉取失败（404/删除/网络不可达）时，只要 raw-store 里有
                # 该源最后成功下载的版本，就沿用之——绝不跟随上游删除本地版本，
                # 也不把该源打成 dead（避免被自动黑名单停用而丢源）。
                stored = raw_store.read_stored(store_dir, u["name"])
                if stored is not None:
                    raw_store.mark_deleted(store_dir, u["name"], info)
                    raw = stored
                    raw_st = "deleted_upstream_kept"
                    info = (f"上游已删/不可达（{str(info)[:80]}），raw-store 沿用最后可用版"
                            f"（{raw_store.today()} 标记 deleted_upstream）")
            else:
                try:
                    raw_st = raw_store.ingest(store_dir, u["name"], u["url"], raw)["status"]
                except OSError as e:  # noqa: BLE001 —— 落库失败不阻断主流程
                    print(f"  [raw-store] {u['name']} 入库失败：{e}", flush=True)
        # 吸收点 P1-1：混淆配置解码（仅 tvbox 配置类；明文零开销直通，
        # 解码失败按候选失败处理，绝不把密文残留进下游解析/快照）。
        if raw is not None and u.get("kind") == "tvbox":
            raw, d_method = decode_config(raw)
            if raw is None:
                info = f"decode failed: {d_method}"
        return u, raw, info, ok_url, d_method, raw_st, fetch_ms

    with cf.ThreadPoolExecutor(min(8, CONCURRENCY)) as ex:
        fetched = list(ex.map(do_fetch, fetchable))

    # 任务2b：同仓库不同分支内容去重——同 github user/repo 下 sha256 完全相同的多条上游，
    # 只保留 main > master > 其他分支优先级最高的一条；其余把 raw 置 None 让消费循环自然跳过。
    # 不直接删 fetched 元素（保持与 fetchable 的 zip 对齐）。
    try:
        import urllib.parse as _up2

        def _repo_key(url: str):
            """从 GitHub URL 提取 user/repo；非 GitHub 返回 None。"""
            if not isinstance(url, str):
                return None
            m = re.search(r"github(?:usercontent)?\.com/([^/]+/[^/]+)", url)
            if not m:
                return None
            return m.group(1)

        def _branch_of(url: str):
            """raw.githubusercontent.com/user/repo/BRANCH/path 或 github.com/user/repo/raw/BRANCH/path。"""
            try:
                p = _up2.urlparse(url)
                parts = p.path.strip("/").split("/")
                # parts: [user, repo, ...]
                if "raw.githubusercontent.com" in p.netloc:
                    return parts[2] if len(parts) > 2 else ""
                if p.netloc == "github.com" and len(parts) > 3 and parts[2] == "raw":
                    return parts[3]
            except Exception:  # noqa: BLE001
                pass
            return ""

        # 按仓库分组：{repo: [(idx, branch, sha256)]}
        _repo_groups: dict = {}
        for _idx, (_u2, _raw, _info, _ou, _dm, _rs, _ms) in enumerate(fetched):
            if _raw is None:
                continue  # 拉取失败不参与去重
            _rk = _repo_key(_u2["url"])
            if not _rk:
                continue
            _sha = hashlib.sha256(_raw).hexdigest()
            _repo_groups.setdefault(_rk, []).append((_idx, _branch_of(_u2["url"]), _sha))

        _skip_idx: set = set()
        for _rk, _items in _repo_groups.items():
            if len(_items) < 2:
                continue
            # 按 sha256 分组：同 hash 的条目只留一条
            by_hash: dict = {}
            for _idx, _br, _sh in _items:
                by_hash.setdefault(_sh, []).append((_idx, _br))
            for _sh, _grp in by_hash.items():
                if len(_grp) < 2:
                    continue
                # 分支优先级：main > master > 其他
                def _br_rank(b):
                    return 0 if b == "main" else (1 if b == "master" else 2)
                _grp_sorted = sorted(_grp, key=lambda x: (_br_rank(x[1]), x[1]))
                _keep_idx, _keep_br = _grp_sorted[0]
                for _idx, _br in _grp_sorted[1:]:
                    _skip_idx.add(_idx)
                    print(f"      [repo-dedup] {_rk}：{_br} 分支内容与 {_keep_br} 完全相同，跳过", flush=True)

        if _skip_idx:
            for _idx in _skip_idx:
                _u2, _raw, _info, _ou, _dm, _rs, _ms = fetched[_idx]
                fetched[_idx] = (_u2, None, "同仓库内容重复已跳过（保留优先级更高的分支）", _ou, _dm, _rs, _ms)
            print(f"[1/6] 同仓库内容去重：跳过 {len(_skip_idx)} 个重复分支（保留 main/master 优先）", flush=True)
    except Exception as _e:  # noqa: BLE001
        print(f"  [repo-dedup] 异常（不阻断）：{_e}", flush=True)

    snapshot_paths = []
    disabled_now_list = []
    rawstore_changed = []   # 本轮 raw-store 判定「有变化」的上游（驱动下游重跑；canary 除外）
    for (u, fetchable_ok, tag), (u2, raw, info, ok_url, d_method, raw_st, fetch_ms) in zip(fetchable, fetched):
        name, kind = u["name"], u["kind"]
        state_ent = state.get(name) if isinstance(state.get(name), dict) else {}
        rec = {
            "name": name, "url": u["url"], "kind": kind,
            "http_ms": 0, "channel": "", "bytes": 0, "sha256": "",
            "sites": 0, "lives": 0, "parses": 0,
            "merged_sites": 0, "merged_lives": 0, "merged_parses": 0,
            "grade": "不可用", "error": "",
            "status": tag, "fail_count": int(state_ent.get("fail_count", 0)),
            "last_ok_at": state_ent.get("last_ok_at", ""),
            "decode": d_method, "success_url": ok_url or "",
        }
        rec["raw_status"] = raw_st
        if raw_st in raw_store.RUN_TRIGGER_STATUSES and not u.get("canary"):
            rawstore_changed.append(name)   # canary 只监控不合并，其变化不驱动重跑
        if not fetchable_ok:
            checks.append(rec)
            interfaces.append(rec)
            print(f"  SKIP {name}（{STATUS_CN.get(tag, tag)}）", flush=True)
            continue

        try:
            record_latency(u["url"], int(fetch_ms))   # 任务7：记录拉取耗时
        except Exception:  # noqa: BLE001
            pass

        if raw is not None:
            rec["bytes"] = len(raw)
            rec["sha256"] = sha12(raw)
            snapshot_paths.append(snapshot_save(name, kind, raw, now))
            # O5 同内容镜像短路：配置内容与已处理上游 sha256 一致时跳过解析合并
            if kind == "tvbox" and rec["sha256"] and rec["sha256"] in seen_sha:
                rec["mirror_of"] = seen_sha[rec["sha256"]]
                rec["status"] = "ok"
                rec["grade"] = "镜像"
                record_result(state, name, True, whitelist_manual, url=u.get("url"))  # 健康分照常刷新，主域失效时可接管
                retry_record_success(u["url"])   # 任务5：恢复后清除退避
                rec["fail_count"] = 0
                rec["last_ok_at"] = state[name].get("last_ok_at", "")
                checks.append(rec)
                interfaces.append(rec)
                mirror_count += 1
                print(f"  MIRROR {name}: 内容与 {rec['mirror_of']} 一致（sha {rec['sha256']}），跳过合并", flush=True)
                continue
            if rec["sha256"]:
                seen_sha[rec["sha256"]] = name

        ok_eval, status_tag, detail, err = evaluate_upstream(u, raw)
        rec["status"] = status_tag
        rec["error"] = err or ""
        # V12：先算失败类型，供 record_result 差异化阈值
        _fail_kind = classify_failure(info, err, raw) if not ok_eval else None
        outcome = record_result(state, name, ok_eval, whitelist_manual,
                                url=u.get("url"), fail_kind=_fail_kind)
        if outcome == "disabled_now":
            disabled_now_list.append(name)
        rec["fail_count"] = int(state[name].get("fail_count", 0))
        rec["last_ok_at"] = state[name].get("last_ok_at", "")
        if raw is None:
            rec["error"] = info
        else:
            rec["channel"] = info
        # 任务4：拉取并解析成功后记录配置变更（归一化 sha256，仅内容真正变化才写行）
        if ok_eval and raw is not None:
            try:
                _uclog.record(u["url"], detail.get("cfg") if kind == "tvbox" else raw, size=len(raw))
            except Exception:  # noqa: BLE001 —— 变更追踪失败不阻断主流程
                pass
        # 任务5：成功清退避；失败按分类进退避（404 不进退避，走 raw-store 删除保护）
        if ok_eval:
            retry_record_success(u["url"])
        else:
            _cat = classify_failure(info, err, raw)
            record_failure(u["url"], _cat, err or info)
            if _cat == "parse_error":
                print(f"  [告警] {name} 上游解析失败（{str(err or info)[:80]}），需人工确认格式", flush=True)
            retry_record_failure(u["url"], _cat, now_naive)

        if not ok_eval:
            checks.append(rec)
            interfaces.append(rec)
            print(f"  {'DEGRADED' if status_tag == 'degraded' else 'FAIL'} {name}: {err or info}", flush=True)
            continue

        if u.get("canary"):
            # 第十三批：canary 只监控不合并——健康分/快照照常，内容不进 tvbox.json/live.json
            rec["grade"] = "canary"
            checks.append(rec)
            interfaces.append(rec)
            print(f"  CANARY {name}: 内容校验通过（{rec['bytes']}B），仅监控不合并", flush=True)
            continue

        # ---- 合并 ----
        if kind == "tvbox":
            cfg = detail["cfg"]
            # 成人专供上游：站点照常收（classify_site 会整仓强制 adult → adult.json），
            # 直播照常收（打上 _adult_only，稍后下放 adult_live.json），
            # 但 parses / 全局 spider / wallpaper 一律不收——它们是主配置的全局字段，
            # 名字带成人特征会直接漏进非成人产物。
            _a_only = name.lower() in ADULT_ONLY_ORIGINS
            cfg_sites = [s for s in (cfg.get("sites") or [])
                         if isinstance(s, dict) and s.get("key") and s.get("api")]
            cfg_lives = [l for l in (cfg.get("lives") or []) if isinstance(l, dict) and l.get("name")]
            cfg_parses = ([] if _a_only else
                          [p for p in (cfg.get("parses") or [])
                           if isinstance(p, dict) and p.get("name")])
            added_s = added_l = added_p = 0
            repl_s = repl_l = repl_p = 0
            sc = upstream_score(name, state)
            for s in cfg_sites:
                k = merge_key_site(s)
                if not k:
                    continue
                if k not in sites_by_key:
                    sites_by_key[k] = rewrite_gh(s)
                    site_origin_name[k] = name
                    site_origin_score[k] = sc
                    added_s += 1
                elif sc > site_origin_score.get(k, -10 ** 9):
                    # O1 健康度仲裁：来源更健康的上游接管同 key 站点（同分保持先到先得，避免抖动）
                    sites_by_key[k] = rewrite_gh(s)
                    site_origin_name[k] = name
                    site_origin_score[k] = sc
                    repl_s += 1
            for l in cfg_lives:
                k = merge_key_live(l)
                if not k:
                    continue
                if k not in lives_by_name:
                    lives_by_name[k] = rewrite_gh(l)
                    live_origin_score[k] = sc
                    added_l += 1
                elif sc > live_origin_score.get(k, -10 ** 9):
                    lives_by_name[k] = rewrite_gh(l)
                    repl_l += 1
                if _a_only and isinstance(lives_by_name.get(k), dict):
                    lives_by_name[k]["_adult_only"] = True   # 稍后下放成人直播池
            for p in cfg_parses:
                k = merge_key_parse(p)
                if not k:
                    continue
                if k not in parses_by_name:
                    parses_by_name[k] = rewrite_gh(p)
                    parse_origin_score[k] = sc
                    added_p += 1
                elif sc > parse_origin_score.get(k, -10 ** 9):
                    parses_by_name[k] = rewrite_gh(p)
                    repl_p += 1
            valid = bool(cfg_sites)
            rec.update(
                sites=len(cfg_sites), lives=len(cfg_lives), parses=len(cfg_parses),
                merged_sites=added_s, merged_lives=added_l, merged_parses=added_p,
                grade=grade_of(len(cfg_sites), valid), channel=info,
            )
            if _a_only:
                rec["adult_only"] = True
            for gk in ("spider", "wallpaper"):
                if _a_only:
                    break   # 成人专供上游不贡献主配置的全局字段
                if gk in cfg and gk not in merged and isinstance(cfg[gk], str):
                    merged[gk] = rewrite_gh(cfg[gk])
                    if gk == "spider":
                        spider_origin_info = (name, u["url"].rsplit("/", 1)[0] + "/")
            # 记下**每个**上游自己的 spider（不管有没有被选成全局），
            # 供 assign_origin_spiders 给这些源补回它原本该用的那份包
            if isinstance(cfg.get("spider"), str) and cfg["spider"]:
                upstream_spider[name] = cfg["spider"]
            print(f"  OK   {name}: sites={len(cfg_sites)} lives={len(cfg_lives)} "
                  f"parses={len(cfg_parses)} (+{added_s}/{added_l}/{added_p} repl {repl_s}/{repl_l}/{repl_p}) "
                  f"{rec['bytes']}B #{rec['sha256']}", flush=True)
        else:
            print(f"  OK   {name}: {detail['entries']} 条频道 {rec['bytes']}B #{rec['sha256']}", flush=True)
        checks.append(rec)
        interfaces.append(rec)

    # 2026-09-21 点播+容错线：黑名单单轮安全阀（判定与回滚逻辑见 apply_blacklist_round_cap）
    disabled_now_list = apply_blacklist_round_cap(
        state, disabled_now_list, len(active_upstreams), BLACKLIST_ROUND_CAP_RATIO)
    sync_blacklist_auto(state)
    save_state(state)
    if disabled_now_list:
        print(f"  本轮自动停用：{', '.join(disabled_now_list)}", flush=True)

    # C4：收集本轮新入库上游（raw_store ST_NEW），供合并后对其贡献站点做零延迟验活
    # C5：上游内容突变检测（对比基线，只告警不自动停用）
    try:
        detect_upstream_anomaly(checks)
    except Exception as _e:  # noqa: BLE001
        print(f"  [C5] 突变检测异常（不阻断）：{_e}", flush=True)

    new_upstream_names = [r["name"] for r in interfaces
                          if r.get("raw_status") == raw_store.ST_NEW and r.get("kind") == "tvbox"]
    if new_upstream_names:
        print(f"[C4] 新入库上游 {len(new_upstream_names)} 个：{', '.join(new_upstream_names[:10])}", flush=True)

    usable_config = [r for r in interfaces if r["kind"] == "tvbox" and r["grade"] != "不可用"]
    if not usable_config:
        print("所有配置类上游均不可用，中止（不产出配置）", flush=True)
        return 1

    # ---- 变化驱动重跑门控（2026-09-27 落库改造）----
    # raw-store 判定全部上游原始文件无变化（含「上游已删沿用最后可用版」——内容同样
    # 无变化，绝不因上游删除触发下游删除）且已有已发布产物时，跳过本轮聚合：
    # 产物继续引用上一版；探活/验活由 validate.yml 与各 probe 步骤照常承担。
    # 上游有任一变化（new/changed/restored/changed_recovered）→ 照常全量聚合。
    if (raw_store.ENABLED and not FORCE_FULL_RUN and not rawstore_changed
            and os.path.exists("tvbox.json") and os.path.exists("live.json")):
        skip_doc = {
            "date": raw_store.today(),
            "mode": "skipped_unchanged",
            "note": ("全部上游原始文件无变化（raw-store sha256 比对），跳过聚合，沿用既有产物；"
                     "上游删除沿用最后可用版不触发重跑；探活由 validate/巡检承担"),
            "upstreams_total": len(active_upstreams),
            "changed": [],
        }
        os.makedirs("state", exist_ok=True)
        with open(os.path.join("state", "raw_run.json"), "w", encoding="utf-8") as f:
            json.dump(skip_doc, f, ensure_ascii=False, indent=1)
        print("[raw-store] 全部上游无变化 → 跳过聚合，沿用既有产物（详见 state/raw_run.json）", flush=True)
        return 0
    # 全量重跑路径：留下变化台账，供审计与追踪「哪次变化触发了重跑」
    os.makedirs("state", exist_ok=True)
    with open(os.path.join("state", "raw_run.json"), "w", encoding="utf-8") as f:
        json.dump({"date": raw_store.today(), "mode": "full",
                   "changed": rawstore_changed,
                   "note": "本轮有上游原始文件变化（或首轮/FORCE_FULL_RUN），已执行全量聚合"},
                  f, ensure_ascii=False, indent=1)

    dup_drops = secondary_dedup_sites(sites_by_key, site_origin_name, site_origin_score)
    if dup_drops:
        print(f"    二级去重：剔除 {len(dup_drops)} 个 api/ext 指纹重复站点（保留健康来源）", flush=True)
    mirror_drops = apply_mirror_dedup(sites_by_key, site_origin_name, site_origin_score)
    if mirror_drops:
        print(f"    三级去重：剔除 {len(mirror_drops)} 个同库镜像站点（片名指纹，保留可用性最好的一份）", flush=True)
    # P1-1：功能等价去重（不同 key 同后端）——dedup_mirrors.functional_equiv(a, b) 是两两比较函数，
    # 返回 True 表示两站功能等价。这里两两迭代，等价时按 site_origin_score 仲裁保留高分者。
    try:
        import dedup_mirrors
        if hasattr(dedup_mirrors, "functional_equiv"):
            _fe_keys = list(sites_by_key.keys())
            _fe_drops: list = []
            _dropped_set: set = set()
            for _i in range(len(_fe_keys)):
                _ka = _fe_keys[_i]
                if _ka in _dropped_set:
                    continue
                _sa = sites_by_key[_ka]
                for _j in range(_i + 1, len(_fe_keys)):
                    _kb = _fe_keys[_j]
                    if _kb in _dropped_set:
                        continue
                    _sb = sites_by_key[_kb]
                    try:
                        if dedup_mirrors.functional_equiv(_sa, _sb):
                            # 保留 origin_score 更高者，低的 drop
                            _score_a = site_origin_score.get(_ka, 0)
                            _score_b = site_origin_score.get(_kb, 0)
                            _drop = _ka if _score_a < _score_b else _kb
                            _keep = _kb if _drop == _ka else _ka
                            if _drop not in _dropped_set:
                                _fe_drops.append(_drop)
                                _dropped_set.add(_drop)
                                sites_by_key.pop(_drop, None)
                            # 被 drop 的是 _ka 则外层循环该 a 已无效，跳出内层
                            if _drop == _ka:
                                break
                    except Exception:  # noqa: BLE001
                        continue
            if _fe_drops:
                print(f"    四级去重（功能等价）：剔除 {len(_fe_drops)} 个同后端站点", flush=True)
        else:
            print("    [P1-1] 功能等价去重未启用（dedup_mirrors.functional_equiv 不存在）", flush=True)
    except Exception as _e:  # noqa: BLE001
        print(f"    [P1-1] 功能等价去重未启用（{_e}）", flush=True)
    sites = list(sites_by_key.values())
    lives = list(lives_by_name.values())
    parses = list(parses_by_name.values())
    print(f"[2/6] 合并完成：{len(sites)} sites / {len(lives)} lives / {len(parses)} parses", flush=True)

    # ---- 解析池清洗（解决「一堆没用的解析」）----
    # 站点去重只看 key，无法处理「同一 URL 多个不同 name」的解析池；调用 clean_parses
    # 做结构校验 + 私有地址剔除 + URL 规范化去重 + TCP 主机探活（沙箱/CI 受限时可走
    # SKIP_PARSE_PROBE=1 跳过；安全阀保障网络故障不会清空解析池）。
    skip_probe = os.environ.get("SKIP_PARSE_PROBE", "0") == "1"
    parses, parse_stats = clean_parses(parses, do_probe=not skip_probe)
    print(f"[2/6] 解析清洗：{parse_stats['before']} → {parse_stats['after']}"
          f"（无效 {parse_stats['dropped_invalid']} / 私有 {parse_stats['dropped_private']}"
          f" / 重复 {parse_stats['dropped_duplicate']} / 不可达 {parse_stats['dropped_unreachable']}"
          f"{' / ⚠安全阀触发' if parse_stats['safety_valve_triggered'] else ''}）",
          flush=True)
    # 解析池回写：parses 在 [5/6] 输出装配时统一写入 tvbox["parses"]（vod 由 tvbox
    # 派生自动继承）；此处 tvbox/vod 尚未构建，提前引用会 UnboundLocalError
    # （2026-09-23 CI run 35767489299 实证）。

    # ---- 上游投票预扫（防关键词单匹配误杀）----
    # 给每个站点打上 _origin 标签（来自 site_origin_name），用强信号 + 覆盖表 + 误报
    # 白名单 + 短剧词 判定成人站，按上游仓库计数。后续 classify_site 调用会读
    # _origin + origin_votes 做仓库级聚合判定。
    origin_votes: dict = {}
    for s in sites:
        key = s.get("key")
        if not key:
            continue
        origin = site_origin_name.get(key) or ""
        if origin:
            s["_origin"] = origin
        cat = classify_site_strong_only(s, category_overrides)
        if cat == "adult":
            origin_votes[origin.lower()] = origin_votes.get(origin.lower(), 0) + 1
    # C4：对新上游贡献的站点做零延迟验活（前 3 个 api，2/3 过即 healthy）
    if new_upstream_names:
        _new_sites = [s for s in sites if (s.get("_origin") or "") in new_upstream_names]
        if _new_sites:
            _qs = _quick_probe_sites(_new_sites)
            print(f"[C4] 新源验活：抽样 {_qs['sampled']} 站，healthy {_qs['healthy']} → {_qs['verdict']}"
                  f"（probe/new_sites.json）", flush=True)
    # ---- [3/6] 测速验活：仅 type 0/1 且 api 为 http(s) 的直连站点 ----
    def testable(s: dict) -> bool:
        return s.get("type") in (0, 1) and isinstance(s.get("api"), str) and s["api"].startswith("http")

    def first_m3u8_uri(body: bytes, base_url: str):
        """取 m3u8 正文里第一条真实 URI 行（跳过 # 注释行），相对路径按 base_url 拼接。"""
        for raw in body.decode("utf-8", "replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith(("http://", "https://")):
                return line
            return urllib.parse.urljoin(base_url, line)
        return None

    def probe_m3u8_content(uri: str, depth: int, base_ms: int):
        """取 uri 前 MAX_BODY 字节计时；若仍是 m3u8（master→子索引）则下钻，最多 2 层。

        返回累计耗时（含索引），取不到可播放内容返回 None。"""
        if depth > 2:
            return None
        try:
            status, body, elapsed = http_get(uri, TEST_TIMEOUT, MAX_BODY)
        except Exception:  # noqa: BLE001
            return None
        if status not in (200, 206) or not body:
            return None
        if body[:64].lstrip().lower().startswith(b"#extm3u"):
            nxt = first_m3u8_uri(body, uri)
            if not nxt:
                return None  # 纯索引无分片，不算可播放内容
            return probe_m3u8_content(nxt, depth + 1, base_ms + elapsed)
        return base_ms + elapsed

    def check_site(s: dict):
        """验活 + 实测「取到内容耗时」，返回 (ok, ms)。

        ms 是拿到有效内容的完整耗时——含 DNS/建连/正文读取，不是空连通快。
        正文三形态皆认：JSON（{ 头）/ XML（< 头）/ m3u8（#EXTM3U 头）；
        m3u8 命中后下钻到真实分片（master→子索引→分片，最多 2 层）取前 MAX_BODY
        字节计时，ms = 索引 + 分片累计耗时——测的才是「到能播放的内容」的速度，
        而不是空索引；分片取不到视为失败。HTML 错误页等无效正文一律失败。
        V2：与 probe_sites.probe_http_site L1 口径对齐（HTTP200 + 非 HTML + 可解析内容头）。
        V4：每次 http_get 前取同域信号量，避免并发拉满后被目标站 WAF 封。
        V8：历史慢源（>5s）单次超时缩到 3s，避免拖慢整体验活。
        """
        url = s["api"]
        ms = 0
        # V8：历史慢源缩短超时（_hist_ms_by_key 在 submit 前从 sites_probe.json 预加载）
        _to = 3 if _hist_ms_by_key.get(s.get("key"), 0) > 5000 else TEST_TIMEOUT
        sem = _domain_semaphore(url)   # V4：同域信号量
        for _ in range(2):  # 失败重试一次
            try:
                sem.acquire()
                try:
                    status, body, elapsed = http_get(url, _to, MAX_BODY)
                finally:
                    sem.release()
                ms = elapsed
                if status == 200 and body:
                    head = body[:1024].lstrip()
                    low = head.lower()
                    if head[:1] in (b"{", b"<") and b"<html" not in low:
                        return True, ms
                    if low.startswith(b"#extm3u"):
                        nxt = first_m3u8_uri(body, url)
                        if nxt:
                            seg_ms = probe_m3u8_content(nxt, 1, ms)
                            if seg_ms is not None:
                                return True, seg_ms
            except Exception:  # noqa: BLE001
                pass
        return False, ms

    to_test = [] if SKIP_SITE_TEST else [s for s in sites if testable(s)]
    limit = int(os.environ.get("SITE_LIMIT", "0"))
    if limit > 0:
        to_test = to_test[:limit]
    # 站点链接指纹缓存（2026-09-28）：仓库/上游配置照拉不受影响；直连站点链接若
    # api+ext 指纹未变 且 上次验活通过 且 未超 TTL，复用结论跳过重测（失败站不入
    # 缓存，下轮照常重测，O3 回捞语义不变）。
    fv_cache = load_fv_cache()
    _fv_hits: list = []
    if fv_cache:
        _fv_retest: list = []
        for s in to_test:
            if fv_cache_hit(fv_cache, site_fingerprint(s)):
                _fv_hits.append(s)
            else:
                _fv_retest.append(s)
        to_test = _fv_retest
    if _fv_hits:
        print(f"[3/6] 站点链接缓存：{len(_fv_hits)} 个未变且 TTL 内通过的链接复用结论"
              f"（TTL {FV_CACHE_TTL_DAYS} 天），{len(to_test)} 个需实测", flush=True)
    print(f"[3/6] 站点验活：{len(to_test)}/{len(sites)} 个直连站点，并发 {CONCURRENCY} ...", flush=True)
    t0 = time.time()
    # V8：预加载历史 check_ms（sites_probe.json），供慢源超时缩短与排序使用
    _hist_ms_by_key: dict = {}
    try:
        with open(PROBE_FILE, encoding="utf-8") as _pf:
            _probe_doc = json.load(_pf)
        for _k, _v in (_probe_doc.get("sites") or _probe_doc).items():
            if isinstance(_v, dict) and _v.get("check_ms"):
                _hist_ms_by_key[_k] = int(_v["check_ms"])
    except Exception:  # noqa: BLE001
        pass
    # V8：提交前按 (健康分 desc, 历史 ms asc) 排序——快源/高优先源先测，慢源不阻塞整体
    _health_score = {s.get("key"): site_origin_score.get(s.get("key"), 0) for s in to_test}
    to_test = sorted(to_test, key=lambda s: (-_health_score.get(s.get("key"), 0),
                                              _hist_ms_by_key.get(s.get("key"), 10**9)))
    verdict: dict = {}  # key -> (ok, ms)：ok=验活通过，ms=取到有效内容耗时（最后一轮）
    # 缓存命中的站回填结论（复用上次通过时的 ms），不参与实测
    for s in _fv_hits:
        verdict[s["key"]] = (True, int(fv_cache[site_fingerprint(s)].get("ms", 0)))
    with cf.ThreadPoolExecutor(CONCURRENCY) as ex:
        futs = {ex.submit(check_site, s): s for s in to_test}
        done = 0
        for fut in cf.as_completed(futs):
            s = futs[fut]
            try:
                verdict[s["key"]] = fut.result()
            except Exception:  # noqa: BLE001
                verdict[s["key"]] = (False, 0)
            done += 1
            if done % 100 == 0:
                print(f"  ... {done}/{len(to_test)} ({time.time()-t0:.0f}s)", flush=True)
    # 回写站点链接验活缓存：实测通过的按指纹入缓存；实测失败的删旧条目（下轮重测）
    _fv_new_ts = time.time()
    _fv_mutated = False
    for s in to_test:
        fp = site_fingerprint(s)
        ok, ms = verdict.get(s.get("key")) or (False, 0)
        if ok:
            fv_cache[fp] = {"ok": True, "ms": int(ms or 0), "ts": _fv_new_ts,
                            "key": s.get("key"), "api": str(s.get("api"))[:160]}
            _fv_mutated = True
        elif fp in fv_cache:
            del fv_cache[fp]
            _fv_mutated = True
    # 剪掉已不在本轮产物里的指纹（站被去重/剔除后不留僵尸缓存）
    _live_fps = {site_fingerprint(s) for s in (to_test + _fv_hits)}
    if _live_fps and len(fv_cache) > len(_live_fps) + 20:  # 有可观增量才剪
        _drop = [fp for fp in fv_cache if fp not in _live_fps]
        if _drop:
            for fp in _drop:
                del fv_cache[fp]
            _fv_mutated = True
    if _fv_mutated:
        save_fv_cache(fv_cache)
        print(f"    [fv_cache] 站点链接验活缓存更新：{len(fv_cache)} 条（state/fv_cache.json）", flush=True)

    removed = []
    kept_sites = []
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    for s in sites:
        if testable(s) and (verdict.get(s["key"]) or (True, 0))[0] is False:
            # O3 站点验活历史：连续 SITE_FAIL_LIMIT 轮失败才剔除；未达阈值暂留观察
            ent = apply_site_verdict(site_state, s.get("key") or "", s.get("name") or "", False, now_str)
            if ent.get("removed"):
                removed.append({
                    "key": s.get("key"), "name": s.get("name"),
                    "api": s.get("api"),
                    "reason": f"连续 {ent.get('fails', 0)} 轮验活失败（>= {SITE_FAIL_LIMIT} 轮剔除）",
                })
            else:
                kept_sites.append(s)
        else:
            if testable(s):
                apply_site_verdict(site_state, s.get("key") or "", s.get("name") or "", True, now_str)
            kept_sites.append(s)
    save_site_state(site_state)
    tested_pass = sum(1 for v in verdict.values() if v and v[0])
    print(f"    通过 {tested_pass}/{len(to_test)}，剔除 {len(removed)}，保留 {len(kept_sites)} 站点", flush=True)

    # ---- 站点速度：把「取到内容耗时」并入 sites_probe.json，作为新鲜排序依据 ----
    check_latency: dict = {k: int(v[1]) for k, v in verdict.items() if v[0] and v[1] > 0}
    if check_latency:
        _ordered = sorted(check_latency.items(), key=lambda kv: kv[1])
        _p50 = _ordered[len(_ordered) // 2][1]
        print(f"    速度实测：{len(check_latency)} 站取到内容耗时中位 {_p50}ms"
              f"（最快 {_ordered[0][1]}ms / {_ordered[0][0][:24]}）", flush=True)
        _ck_stats = merge_check_latency(PROBE_FILE, check_latency, now_str)
        if _ck_stats.get("written"):
            print(f"    速度数据已并入 {PROBE_FILE}（{len(check_latency)} 条 check_ms）", flush=True)

    # P1-1 聚合结果缓存：对全量 kept_sites 算一次分类（short/adult/vod），
    # 后续 adult 剔除 / short 拆分 / adult 拆分统一读 map，消除 classify_site 重复调用 3 次。
    # 必须在 adult 分流前基于全量 kept_sites 算（否则分流后丢分类）。
    def _build_category_map(sites_list, overrides, ovotes):
        return {s.get("key"): classify_site(s, overrides, ovotes)
                for s in sites_list if isinstance(s, dict) and s.get("key")}
    site_category_map: dict = _build_category_map(kept_sites, category_overrides, origin_votes)

    # ---- 成人内容发布开关（默认不发布，见 PUBLISH_ADULT 的说明）----
    adult_excluded_sites: list = []
    _gate_hits: list = []  # 门禁同口径终扫命中（站点级，PUBLISH_ADULT=1 时跳过终扫）
    if not PUBLISH_ADULT:
        before = len(kept_sites)
        adult_excluded_sites = [s for s in kept_sites if site_category_map.get(s.get("key")) == "adult"]
        kept_sites = [s for s in kept_sites if site_category_map.get(s.get("key")) != "adult"]
        if adult_excluded_sites:
            print(f"    [adult] 不声明模式：从主产物剔除 {len(adult_excluded_sites)} 个成人分类站点"
                  f"（{before} → {len(kept_sites)}）；成人源完整写入仓库根 adult.json"
                  f"（随 daily 提交更新，不进 Release/Pages/导航页）",
                  flush=True)
        # 门禁同口径终扫（P0-2 红线对齐）：classify_site 词表与门禁词表是两套词表，
        # 漂移即泄漏（run 36187372853 实证 3562 处）。此处用门禁自己的扫描语义
        # 复扫全部剩余站点，命中者重定向 adult.json 通道——合并层产出按构造等于
        # 门禁可放行；误报白名单（guarded）命中与门禁同口径留在常规产物。
        kept_sites, _gate_hits, _guarded_n = _split_by_adult_gate(kept_sites)
        if _gate_hits:
            adult_excluded_sites.extend(s for s, _ in _gate_hits)
            print(f"    [adult] 门禁同口径终扫：{len(_gate_hits)} 个站点命中成人特征，"
                  f"重定向 adult.json（{before} → {len(kept_sites)}，白名单放行 {_guarded_n} 处）",
                  flush=True)
            for _s, _h in _gate_hits[:20]:
                print(f"      - {_s.get('name')}（{_s.get('_origin') or '~'}）"
                      f"rule={_h[0].get('rule')} val={(_h[0].get('value') or '')[:40]}",
                      flush=True)

    # ---- [4/6] 直播源分类测速优选 ----
    print("[4/6] 直播源分类测速优选（Guovin 上游 → 央视/卫视/港台/其他）...", flush=True)
    m3u_entries = []
    for (u, fetchable_ok, tag), (u2, raw, info, _ok_url, _d_method, _raw_st, _fetch_ms) in zip(fetchable, fetched):
        if u["kind"] != "m3u" or raw is None:
            continue
        try:
            for name, group, url in parse_m3u(raw):
                # 过滤 Guovin 列表头的「更新时间」伪频道与纯日期条目
                if re.search(r"更新时间|update.?time", group, re.I):
                    continue
                if re.match(r"^\d{4}-\d{2}-\d{2}", name):
                    continue
                m3u_entries.append((name, group, url))
        except Exception:  # noqa: BLE001
            pass
    seen_pairs = set()
    dedup_entries = []
    for name, group, url in m3u_entries:
        pk = (name, url)
        if pk not in seen_pairs:
            seen_pairs.add(pk)
            dedup_entries.append((name, group, url))
    print(f"    共 {len(m3u_entries)} 条，去重后 {len(dedup_entries)} 条", flush=True)
    live_stats = {}
    if dedup_entries:
        live_stats = build_live_outputs(dedup_entries)
        for key, label in CATEGORY_LABELS:
            entry_name = f"Guovin·{label}"
            if os.path.exists(os.path.join(LIVES_DIR, f"live_{key}.txt")) and entry_name not in lives_by_name:
                lives_by_name[entry_name] = rewrite_gh({
                    "name": entry_name, "type": 0,
                    "url": f"{REPO_RAW}/lives/live_{key}.txt",
                    "epg": "https://live.fanmingming.cn/e.xml",
                })
    lives = list(lives_by_name.values())

    # ---- [5/6] 产出配置 ----
    # 2026-09-21 点播+容错线：空产物守卫（必须在写任何产物文件之前执行）。
    # 上一版已提交产物 = 工作树里的 tvbox.json（守卫在覆盖它之前返回，即天然保留上次缓存）；
    # 判定逻辑见 empty_guard_check / read_prev_counts。
    _cur = {"sites": len(kept_sites), "lives": len(lives), "parses": len(parses)}
    _prev = read_prev_counts("tvbox.json")
    _blocked = empty_guard_check(_cur, _prev, EMPTY_GUARD_DROP_RATIO)
    if _blocked:
        _guard_note = {
            "triggered_at": generated_at,
            "current": _cur, "previous": _prev,
            "reasons": _blocked,
            "action": "跳过本轮产物写入/提交/Release，保留上次缓存，下轮重试",
        }
        try:
            os.makedirs("state", exist_ok=True)
            with open("state/guard_last.json", "w", encoding="utf-8") as _f:
                json.dump(_guard_note, _f, ensure_ascii=False, indent=1)
        except Exception:  # noqa: BLE001
            pass
        print("[守卫] 空产物守卫触发，本轮不产出、不提交、不发布：", flush=True)
        for _b in _blocked:
            print(f"    - {_b}", flush=True)
        print("    已保留上次缓存（工作树 tvbox.json 未被覆盖）；详见 state/guard_last.json", flush=True)
        return 2

    # ---- 门禁同口径终扫（直播/解析/全局字段）----
    # 上游合并的 lives 条目与 parses 此前不做 adult 过滤（直播仅靠 live.json 清洗
    # 循环的 5 个硬编码 token），同样存在词表漂移泄漏面。统一在写主产物前按门禁
    # 口径处理：直播条目重定向 adult.json，解析与顶层字符串字段直接剔除。
    lives, _life_gate_hits, _life_guarded = _split_by_adult_gate(
        [l for l in lives if isinstance(l, dict)])
    _life_gate_items = [l for l, _ in _life_gate_hits]
    parses, _parse_gate_hits, _parse_guarded = _split_by_adult_gate(
        [p for p in parses if isinstance(p, dict)])
    if _life_gate_hits or _parse_gate_hits:
        print(f"    [adult] 门禁同口径终扫：{len(_life_gate_hits)} 条直播重定向 adult.json / "
              f"{len(_parse_gate_hits)} 条解析剔除（白名单放行 {_life_guarded + _parse_guarded} 处）",
              flush=True)
        for _l, _h in _life_gate_hits[:10]:
            print(f"      - live:{_l.get('name')} rule={_h[0].get('rule')} "
                  f"val={(_h[0].get('value') or '')[:40]}", flush=True)
        for _p, _h in _parse_gate_hits[:10]:
            print(f"      - parse:{_p.get('name')} rule={_h[0].get('rule')} "
                  f"val={(_h[0].get('value') or '')[:40]}", flush=True)

    tvbox = dict(merged)
    tvbox["sites"] = kept_sites
    tvbox["lives"] = lives
    tvbox["parses"] = parses
    # 广告拦截基线注入（P0 体验）：上游配置普遍不带 ad/tihuan，播放器端无拦截配置时
    # 播放页广告切片/顶部跑马灯会直接漏进交付产物。本仓自维护 rules/ad_block.json
    # （广告域+统计追踪域单一词表，可审计），上游带了则尊重上游（合并去重），没带用基线。
    try:
        _ad_rule = json.load(open("rules/ad_block.json", encoding="utf-8"))
        _ad_base = [str(x) for x in (_ad_rule.get("ad") or []) if str(x).strip()]
        _th_base = [str(x) for x in (_ad_rule.get("tihuan") or []) if str(x).strip()]

        def _merge_ad_list(cur, base):
            cur = cur if isinstance(cur, (list, str)) else []
            if isinstance(cur, str):
                cur = [x.strip() for x in re.split(r"[,;\s]+", cur) if x.strip()]
            out, seen = [], set()
            for x in list(cur) + list(base):
                if x and x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        tvbox["ad"] = _merge_ad_list(tvbox.get("ad"), _ad_base)
        tvbox["tihuan"] = _merge_ad_list(tvbox.get("tihuan"), _th_base)
        print(f"    [ad_block] ad={len(tvbox['ad'])} 条 / tihuan={len(tvbox['tihuan'])} 条"
              f"（基线 rules/ad_block.json + 上游并集）", flush=True)
    except Exception as _ae:  # noqa: BLE001
        print(f"    [ad_block] 注入未生效（不阻断）：{_ae}", flush=True)
    # 解析质量排序（P0）：依据 probe/parses_probe.json 按质量分重排——
    # 响应速度 > 格式规范(JSON) > 无广告 > 稳定性；失效排最后、广告排倒数第二。
    # 无探活数据（首次运行）保持原序；任何异常不阻断每日构建。
    try:
        import parse_quality
        _ranked = parse_quality.rank_parses(parses)
        if _ranked is not parses:
            parses = _ranked
            tvbox["parses"] = parses
    except Exception as _eq:
        print(f"    [parse_quality] 排序未生效（保持原序）：{_eq}", flush=True)
    # 门禁同口径终扫（顶层字符串字段）：spider/wallpaper 等非容器字段命中即剔除
    #（正常值为本地 jar 相对路径或壁纸图 URL，不可能命中词表；命中即上游注入）。
    for _gk in list(tvbox.keys()):
        if isinstance(tvbox.get(_gk), str):
            _real, _guarded = adult_gate_scan(tvbox[_gk])
            if _real:
                print(f"    [adult] 门禁同口径终扫：顶层字段 {_gk} 命中成人特征，剔除"
                      f"（rule={_real[0].get('rule')} val={(_real[0].get('value') or '')[:40]}）",
                      flush=True)
                tvbox.pop(_gk)
    # 关键：给「走全局 spider」的源补回它来源上游那份 spider，否则它们会指向不含所需爬虫类的包
    osp_stats = assign_origin_spiders(tvbox, site_origin_name, upstream_spider, spider_origin_info)
    if osp_stats.get("assigned"):
        print(f"    按来源上游补回 spider 的源：{osp_stats['assigned']} 个"
              f"（与全局同包 {osp_stats.get('same_as_global', 0)}、上游未声明 "
              f"{osp_stats.get('origin_no_spider', 0)}）", flush=True)
    # raw-store 依赖每日验证开关：上游有变化（或 always）才逐依赖验证（变化驱动重跑）；
    # 上游全无变化 ⇒ 依赖集合与内容不变，整组跳过验证、沿用 deps/ 与 raw-vod/ 缓存。
    global RAW_VOD_VERIFY_ACTIVE
    RAW_VOD_VERIFY_ACTIVE = (
        raw_store.ENABLED and RAW_VOD_VERIFY != "off"
        and (RAW_VOD_VERIFY == "always" or bool(rawstore_changed)))
    dep_stats = collect_and_rewrite_deps(tvbox, site_origin_name, spider_origin_info)
    loc_stats = localize_external_refs(tvbox)
    # 安全网：没能落库的 per-site jar 撤掉，避免留下客户端解析不了的相对路径
    prune_unlocalized_jars(tvbox)
    # 按「分类 → 搜索可用性 → 实测速度」重排站点（实现见 scripts/rank_sites.py）
    rank_stats = apply_rank(tvbox)
    # 任务8：产物版本号（YYYY-MM-DD-bN，同日多次构建自增）与北京时间更新时间。
    # TVBox 忽略未知字段，不影响解析；vod.json 由 tvbox 派生，自动继承。
    today_str = now.strftime("%Y-%m-%d")
    build_no = 1
    try:
        with open("tvbox.json", encoding="utf-8") as _pf:
            _prev = json.load(_pf)
        _pv = str(_prev.get("version", ""))
        if _pv.startswith(today_str + "-b"):
            build_no = int(_pv.rsplit("-b", 1)[-1]) + 1
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    tvbox["version"] = f"{today_str}-b{build_no}"
    tvbox["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    # P1-2：产出前终验（复用 check_site/http_get 只测 L1；失败只标记不剔除）
    _final_verification: dict = {"tested": 0, "passed": 0, "failed_keys": [], "cache_hits": 0}
    try:
        _fv_targets = [s for s in (tvbox.get("sites") or [])
                       if s.get("type") in (0, 1) and isinstance(s.get("api"), str)
                       and s["api"].startswith("http")]
        if _fv_targets and not SKIP_SITE_TEST:
            # 站点链接缓存：[3/6] 验活刚写过的指纹未变直接复用结论，终验只补测漏网的。
            # 注意：本处只读缓存不写回——P1-2 是宽松 L1 判据（200+有体），写回会污染
            # [3/6] 严格验活（正文形态/分片下钻）用的结论口径。
            _fv_cache2 = load_fv_cache()
            _fv_recheck = [s for s in _fv_targets
                           if not fv_cache_hit(_fv_cache2, site_fingerprint(s))]
            _fv_cache_hits = len(_fv_targets) - len(_fv_recheck)
            _final_verification["cache_hits"] = _fv_cache_hits
            print(f"    [P1-2] 产出前终验：{_fv_cache_hits} 站命中站点链接缓存跳过 / "
                  f"{len(_fv_recheck)} 站 L1 补测（并发64/超时3s）...", flush=True)
            def _fv_probe(s):
                try:
                    st, body, _ms = http_get(s["api"], 3, 4096)
                    return s.get("key"), (st == 200 and bool(body))
                except Exception:
                    return s.get("key"), False
            with cf.ThreadPoolExecutor(64) as _fex:
                for _k, _ok in _fex.map(_fv_probe, _fv_recheck):
                    _final_verification["tested"] += 1
                    if _ok:
                        _final_verification["passed"] += 1
                    else:
                        _final_verification["failed_keys"].append(_k)
            _final_verification["passed"] += _fv_cache_hits
            print(f"    [P1-2] 终验完成：{_final_verification['passed']}/{_final_verification['tested'] + _fv_cache_hits} 通过"
                  f"（补测 {len(_fv_recheck)} + 缓存 {_fv_cache_hits}；失败 {len(_final_verification['failed_keys'])} 站只标记不剔除）", flush=True)
    except Exception as _e:  # noqa: BLE001
        print(f"    [P1-2] 终验异常（不阻断）：{_e}", flush=True)
    # 环④ P0 死引用剥离闸门：主产物写文件前，剔除本地 ./deps 引用缺失的站点并登记
    # local_ref_audit；死引用站点进配置只会让用户导入后大面积播坏（2026-09-28 五环
    # 评估：重下载修复成功率仅 2%，剥离为唯一有效动作）。vod 在下方由 tvbox 派生，
    # 剔除一次即同步作用于 tvbox.json / vod.json / stores / short / adult 全部产物。
    local_ref_audit: dict = {}
    _tv_sites = tvbox.get("sites") or []
    if MAIN_DROP_DEAD_REFS:
        tvbox["sites"] = filter_local_ref_sites(_tv_sites, os.getcwd(), "tvbox.json", local_ref_audit)
    else:
        _vod_drops = [{"key": s.get("key"), "name": s.get("name"), "missing": _missing_local_refs(s, os.getcwd())}
                      for s in _tv_sites if _missing_local_refs(s, os.getcwd())]
        if _vod_drops:
            local_ref_audit["tvbox.json(仅记录)"] = _vod_drops
            print(f"    [local-ref] 审计发现 {len(_vod_drops)} 个死引用站点（MAIN_DROP_DEAD_REFS=0 仅记录不剔除）", flush=True)
    # P0-3：写主产物前剥离内部字段（_origin/_health/_latency_ms/_probe_* 等）。
    # 注意：此处 tvbox 仍保留 _origin 供后续 vod 派生/adult 排序使用；写文件用剥离副本。
    tvbox_out = _strip_internal_fields(tvbox)
    with open("tvbox.json", "w", encoding="utf-8") as f:
        json.dump(tvbox_out, f, ensure_ascii=False, indent=1)
    # 任务9：紧凑版（无空格无换行），内容与可读版完全一致
    with open("tvbox_min.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(tvbox_out, ensure_ascii=False, separators=(",", ":")))

    # ---- 拆分产物：vod.json（点播）+ live.json（直播）----
    # vod.json = tvbox 去掉 lives（保留 spider / wallpaper / sites / parses 等点播相关字段）；
    # live.json = {"lives": [...]}，并确保汇总 lives/ 目录的分类文件条目（央视/卫视/港台/其他）。
    vod = {k: v for k, v in tvbox.items() if k != "lives"}
    # 同步 _origin 到 vod.sites 派生对象（后续 adult 分类按 _origin 归类排序）。
    # 2026-09-23 热修：原位置在 vod 构建前引用 vod，CI run 35770088851 实证
    # UnboundLocalError;vod 为 tvbox 浅拷贝,移到构建后打标,语义不变。
    for s in (vod.get("sites") or []):
        key = s.get("key")
        if key and not s.get("_origin"):
            origin = site_origin_name.get(key) or ""
            if origin:
                s["_origin"] = origin
    live = {"lives": [l for l in lives if isinstance(l, dict) and l.get("name")]}
    # ---- 直播重构：以本次实测聚合为主入口（央视/卫视/港台分组 + 核心频道多线路）----
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    curated_lives, adult_lives = build_curated_lives(repo_dir)
    # 门禁同口径终扫命中的直播条目下放 adult.json（与既有「成人直播」通道同格式）
    for l in _life_gate_items:
        adult_lives.append({
            "name": l.get("name"), "type": l.get("type", 1),
            "url": l.get("url"), "group": "成人直播",
        })
    # 1. 移除 live.json 里已知不可用的相对路径 / 本地代理条目；保留其余第三方作为备用
    _REJECT_PREFIX = ("http://127.0.0.1", "http://localhost", "http://0.0.0.0")
    _ALLOWED_SCHEME = ("http://", "https://")
    cleaned = []
    for l in live["lives"]:
        u = (l.get("url") or "")
        if not u:
            continue
        if not u.startswith(_ALLOWED_SCHEME):
            continue
        if any(u.startswith(p) for p in _REJECT_PREFIX):
            continue
        # 折叠双协议
        while "https://https://" in u or "http://http://" in u:
            u = u.replace("https://https://", "https://", 1)
            u = u.replace("http://http://", "http://", 1)
        l["url"] = u
        # 成人主题 lives 一律下放到 adult.json；成人专供上游的整条直播也下放
        # （它的频道名可能很干净，关键词扫不到，但上游已被判定成人特征）
        if l.pop("_adult_only", None) or any(
                k in str(l.get("name") or "").lower()
                for k in ("传媒816", "18+", "成人", "pron", "live18")):
            adult_lives.append({
                "name": l.get("name"), "type": l.get("type", 1),
                "url": l.get("url"), "group": "成人直播",
            })
            continue
        cleaned.append(l)
    # 2026-09-23 live.json 大分类组织：每条源按 group 归入 7 大分类，组内按名字排序
    _BIG = ("央视", "卫视", "地方", "港台", "轮播", "直播", "其他")

    def _live_group_of(name):
        n = str(name or "")
        if re.search(r"cctv|cgtn|央视|中央", n, re.I):
            return "央视"
        if "卫视" in n:
            return "卫视"
        if any(k in n for k in ("港", "台", "TVB", "翡翠", "澳")) and "电台" not in n:
            return "港台"
        if any(k in n for k in ("轮播", "一起看")):
            return "轮播"
        if any(k in n for k in ("虎牙", "斗鱼", "哔哩", "b站", "bilibili", "咪咕", "电竞", "直播", "体育", "MV")):
            return "直播"
        return "其他"

    for _l in cleaned:
        if not _l.get("group"):
            _l["group"] = _live_group_of(_l.get("name"))
    # 2026-09-23 用户指令「把那些没用的解析都去掉」：第三方杂源（重复/失效大量存在，
    # 实测 167 条里仅少量可用且与聚合重复）不再进入 live.json，只保留仓库自有
    # 聚合精选条目（2026-09-26 起为 7 条分组接口：聚合·分类直播·<组>，
    # 指向 lives/groups/<组>.txt）。
    # 成人主题条目仍在上面的循环里下放 adult.json，不受影响。
    live["lives"] = curated_lives
    # P0-3：vod 写文件用剥离副本（vod.sites 仍带 _origin 供后续 short/adult 分类排序）
    vod_out = _strip_internal_fields(vod)
    with open("vod.json", "w", encoding="utf-8") as f:
        json.dump(vod_out, f, ensure_ascii=False, indent=1)
    # 任务9：紧凑版
    with open("vod_min.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(vod_out, ensure_ascii=False, separators=(",", ":")))
    # P0-2：live.json 补紧凑版
    live_out = _strip_internal_fields(live)
    with open("live.json", "w", encoding="utf-8") as f:
        json.dump(live_out, f, ensure_ascii=False, indent=1)
    with open("live_min.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(live_out, ensure_ascii=False, separators=(",", ":")))

    # ---- 多仓拆分：stores/{cms,app,pan,csp,duocang,pan_ck}.json ----
    stores_summary = build_stores(vod, category_overrides, repo_dir)

    # ---- 拆分产物：short.json（短剧）+ adult.json（成人），独立收录不剥离 vod ----
    # vod.json 保持完整（含所有点播站点）；short/adult 为分类独立配置。
    # parses 复用 vod 全集：TVBox 站点不引用 parses（playUrl/jar 才是站点自有播放方式），
    # parses 是全局播放器池，单独配置需自带全集才不至于某些解析器不可用。
    short_sites = [s for s in (vod.get("sites") or []) if site_category_map.get(s.get("key")) == "short"]
    if PUBLISH_ADULT:
        adult_sites = [s for s in (vod.get("sites") or []) if site_category_map.get(s.get("key")) == "adult"]
    else:
        # 不声明模式下 vod.sites 里已经没有成人源了（前面已剔除），用当时留存的那份
        adult_sites = adult_excluded_sites
    # P0 防回归：主配置死引用已在产物写入前的剥离闸门处理（见 local_ref_audit 上方注释）；
    # 这里对分类产物再核验一次（正常应为零剔除，兜住分类衍生出的独立配置）。
    short_sites = filter_local_ref_sites(short_sites, repo_dir, "short.json", local_ref_audit)
    adult_sites = filter_local_ref_sites(adult_sites, repo_dir, "adult.json", local_ref_audit)
    short_doc = {k: v for k, v in vod.items() if k not in ("lives", "sites")}
    short_doc["sites"] = short_sites
    if not short_doc.get("spider"):
        short_doc.pop("spider", None)
    adult_doc = {k: v for k, v in vod.items() if k not in ("lives", "sites")}
    adult_doc["lives"] = adult_lives
    # 按上游来源归类；同源块内按「取到内容耗时」升序（用户 2026-09-23 要求：有内容的
    # 加载速度快的排前面），没实测到的沉到同源末尾，再按 name 稳定收尾
    adult_sites_sorted = sorted(
        [s for s in adult_sites if isinstance(s, dict)],
        key=lambda x: ((x.get("_origin") or "~"),
                       check_latency.get(x.get("key"), 10 ** 9),
                       (x.get("name") or "")),
    )
    # 成人站点验收（按所有者 2026-09-23 指令：搜索有结果 + 可播放为准并排序）
    adult_sites_verified, adult_verify_stats = verify_adult_sites(
        adult_sites_sorted, check_latency, timeout=8)
    # 所有者 2026-09-23 口径（评论 7688619739198819507 + 7688623894944681185）：
    # 「只要可播放的，播放不了的就不要留」+「csp 不剔除」——剔除的只有可外部
    # 验证但实测不可播放的站点；csp/jar 类（不可外部验证）保留、排实测可播放之后。
    adult_kept = [s for s in adult_sites_verified
                  if s.get("_probe_play_ok") or s.get("_probe_unverified")]
    adult_doc["sites"] = adult_kept
    # 所有者 2026-09-23 指令：adult.json 不需要解析接口——去掉 parses 字段，
    # 成人分类只保留站点；直播单独拆出 adult_live.json（按所有者同批指令）。
    adult_doc.pop("parses", None)
    adult_doc.pop("lives", None)
    if not adult_doc.get("spider"):
        adult_doc.pop("spider", None)
    # 成人直播源：测速 + 抽首流验活 + 按加载速度排序（所有者 2026-09-23 指令：
    # 「可访问、加载有内容、按加载速度排序」），单独写到 adult_live.json；
    # 所有者后续指令：不可访问的剔除留保。
    adult_lives_sorted, adult_live_stats = probe_adult_lives(adult_lives, timeout=8, max_bytes=32768)
    adult_lives_alive = [l for l in adult_lives_sorted if l.get("_probe_stream_ok")]
    adult_live_doc = {"lives": adult_lives_alive}
    if adult_doc.get("spider"):
        # 直播配置一般不需 spider；保留以防个别源依赖
        adult_live_doc["spider"] = adult_doc["spider"]
    # _probe_* 是内部验收标记，不得泄漏进产物；产出前剥掉
    _PROBE_KEYS = ("_probe_play_ok", "_probe_search_ok", "_probe_unverified", "_probe_stream_ok")
    adult_doc["sites"] = [{k: v for k, v in s.items() if k not in _PROBE_KEYS}
                          for s in adult_doc["sites"]]
    adult_live_doc["lives"] = [{k: v for k, v in l.items() if k not in _PROBE_KEYS}
                               for l in adult_live_doc["lives"]]
    # P0-3 + P0-2：short.json 写剥离副本 + 紧凑版
    short_out = _strip_internal_fields(short_doc)
    with open("short.json", "w", encoding="utf-8") as f:
        json.dump(short_out, f, ensure_ascii=False, indent=1)
    with open("short_min.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(short_out, ensure_ascii=False, separators=(",", ":")))
    # 所有者 2026-09-22/23 指令：adult.json / adult_live.json 每天产出并随 daily 提交更新到仓库；
    # 「只是不声明」：不进 Release 附件白名单 / Pages / 导航页，也不在 README 与日报声明。
    # P0-3 + P0-2：adult.json 写剥离副本（_PROBE_KEYS 已剥，通用剥离兜底 _origin 等）+ 紧凑版
    adult_out = _strip_internal_fields(adult_doc)
    with open("adult.json", "w", encoding="utf-8") as f:
        json.dump(adult_out, f, ensure_ascii=False, indent=1)
    with open("adult_min.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(adult_out, ensure_ascii=False, separators=(",", ":")))
    # 2026-09-23 修复（daily run 35816486949 / 35830045274 连续 failure 实证）：
    # adult_live.json 不再由 daily 生成覆写。所有者指令升级后它是「频道级全量验活
    # （8578 频道逐条实测）+ 按加载到有效内容的速度排序」的静态人工维护产物
    # （含 adult_live_channels/cat1..21.txt）；daily 的粗粒度源级探活版本会覆盖掉它。
    # 且本文件每轮重写但不在提交白名单 → 成为未暂存改动 →
    # `git pull --rebase origin main` 报 "You have unstaged changes" 退出 128。
    print("[skip] adult_live.json 保持仓库现版（频道级验活静态产物），本轮不覆写", flush=True)
    # 按上游仓库归类的拆分（供 status.json 报告）
    from collections import Counter as _C
    adult_origin_breakdown = _C()
    for s in adult_sites_sorted:
        adult_origin_breakdown[s.get("_origin") or "~(无origin)"] += 1
    adult_out = f"adult.json（{len(adult_sites_verified)} sites 可播放 {adult_verify_stats['play_ok']}/{adult_verify_stats['before']}）+ adult_live.json（{len(adult_lives_sorted)} lives 可访问 {adult_live_stats['stream_ok']}/{adult_live_stats['before']}）"
    print(f"[5/6] 产出：tvbox.json / vod.json（{len(vod.get('sites', []))} sites + {len(vod.get('parses', []))} parses）"
          f" / short.json（{len(short_sites)} sites + {len(parses)} parses）"
          f" / {adult_out}"
          f" / live.json（{len(live['lives'])} 条直播源 / 聚合精选：单接口·分类全在文件内分组）/ list.json", flush=True)

    # 公开清单「不声明」口径见 public_list_filter()：成人特征上游 URL 不进 list.json
    _pub_interfaces, _hidden_upstreams = public_list_filter(interfaces)
    if _hidden_upstreams:
        print(f"    [adult] 公开清单剥除 {len(_hidden_upstreams)} 个成人特征上游（不进 list.json，"
              f"内部账本与成人池不受影响）：", flush=True)
        for _h in _hidden_upstreams[:5]:
            print(f"      - {_h[:72]}", flush=True)

    with open("list.json", "w", encoding="utf-8") as f:
        json.dump(_pub_interfaces, f, ensure_ascii=False, indent=1)
    # P0-2：list.json 补紧凑版
    with open("list_min.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(_pub_interfaces, ensure_ascii=False, separators=(",", ":")))

    checks_doc = write_checks(checks, generated_at)
    update_readme_availability(checks)

    # ---- 快照合并产物 + 保留期清理 ----
    merged_dir = os.path.join(SNAPSHOT_DIR, now.strftime("%Y-%m-%d"))
    os.makedirs(merged_dir, exist_ok=True)
    with open(os.path.join(merged_dir, f"tvbox_merged__{now.strftime('%H%M%S')}.json"), "wb") as f:
        f.write(open("tvbox.json", "rb").read())
    pruned = snapshot_prune(SNAPSHOT_RETENTION_DAYS)
    if pruned:
        print(f"    快照清理：移除 {', '.join(pruned)}（保留最近 {SNAPSHOT_RETENTION_DAYS} 天）", flush=True)

    # ---- status.json（增强：上游健康度 + 产物指纹） ----
    products = {}
    for p in ("tvbox.json", "vod.json", "live.json", "short.json", "adult.json",
              "list.json", "status.json", CHECKS_FILE,
              os.path.join(LIVES_DIR, "live.txt"), os.path.join(LIVES_DIR, "live_cctv.txt"),
              os.path.join(LIVES_DIR, "live_weishi.txt"), os.path.join(LIVES_DIR, "live_gangtai.txt"),
              os.path.join(LIVES_DIR, "live_other.txt"),
              os.path.join(STORES_DIR, "duocang.json"), os.path.join(STORES_DIR, "cms.json"),
              os.path.join(STORES_DIR, "app.json"), os.path.join(STORES_DIR, "pan.json"),
              os.path.join(STORES_DIR, "csp.json"), os.path.join(STORES_DIR, "pan_ck.json")):
        if os.path.exists(p):
            b = open(p, "rb").read()
            products[p] = {"bytes": len(b), "sha256": sha12(b)}

    status = {
        "generated_at": generated_at,
        "summary": {
            "interfaces_total": len(interfaces),
            "interfaces_usable": len(usable_config),
            "interfaces_full": sum(1 for r in usable_config if r["grade"] == "完全可用"),
            "interfaces_partial": sum(1 for r in usable_config if r["grade"] == "部分可用"),
            "interfaces_dead": sum(1 for r in interfaces if r["kind"] == "tvbox" and r["grade"] == "不可用"),
            "sites_total": len(sites),
            "sites_kept": len(kept_sites),
            "sites_short": len(short_sites),
            "sites_adult": len(adult_sites),
            "sites_tested": len(to_test),
            "sites_tested_pass": tested_pass,
            "sites_removed": len(removed),
            "sites_untested": len(sites) - len(to_test),
            "sites_secondary_dedup": len(dup_drops),
            "mirrors_skipped": mirror_count,
            "adult_gate_sweep": {
                "note": "P0-2 红线对齐（2026-09-26）：写主产物前按门禁口径终扫，"
                        "站点/直播命中重定向 adult.json，解析/顶层字符串命中剔除；"
                        "词表事实源=state/vocab/categories.json（单一维护）",
                "sites_redirected": len(_gate_hits),
                "lives_redirected": len(_life_gate_hits),
                "parses_dropped": len(_parse_gate_hits),
            },
            "lives": len(lives),
            "parses": len(parses),
            "deps_total": dep_stats["total"],
            "deps_collected": dep_stats["collected"],
            "deps_rewritten": dep_stats["rewritten"],
            "deps_localized_candidates": loc_stats["candidates"],
            "deps_localized_ok": loc_stats["localized"],
            "deps_localized_rewritten": loc_stats["rewritten"],
            "deps_localized_kept": loc_stats["kept"],
            "deps_api_endpoints_untouched": loc_stats["api_endpoints_untouched"],
        },
        "upstreams_health": {
            "note": "checks.json 的摘要镜像；disabled=连续不达标自动停用，blacklisted=手动黑名单",
            "threshold": {"fail_limit": FAIL_LIMIT,
                          "min_bytes_tvbox": MIN_BYTES_TVBOX, "min_bytes_m3u": MIN_BYTES_M3U},
            **checks_doc["summary"],
            "disabled_now": disabled_now_list,
            "snapshot_files": len(snapshot_paths),
            "snapshot_pruned": pruned,
        },
        "spider": {
            "note": "O7b 全局 spider 来源与指纹（清单最前可用上游，依赖本地化后指向 deps/）",
            "origin": (spider_origin_info or ("", ""))[0],
            "value": tvbox.get("spider", "") if isinstance(tvbox.get("spider"), str) else "",
        },
        "site_verdicts": {
            "note": f"O3 站点验活历史记忆；连续 {SITE_FAIL_LIMIT} 轮失败剔除，通过自动复位回捞",
            "tracked": len(site_state),
            "removed": sum(1 for v in site_state.values() if isinstance(v, dict) and v.get("removed")),
        },
        "site_speed": {
            "note": "check_ms = 取到有效配置内容的完整耗时（DNS+建连+正文读取），已并入 sites_probe.json 供 rank_sites 排序；adult.json 同源块内也按此升序",
            "measured": len(check_latency),
            "p50_ms": (sorted(check_latency.values())[len(check_latency) // 2]
                       if check_latency else None),
            "probe_file": PROBE_FILE,
        },
        "runtime": {
            "gh_mirrors": GH_MIRRORS,
            "probe_interval_days": PROBE_INTERVAL_DAYS,
            "site_fail_limit": SITE_FAIL_LIMIT,
            "category_overrides": len(category_overrides),
            "secondary_dedup_dropped": dup_drops[:50],
        },
        "raw_store": {
            "note": ("输入层原始源镜像（raw/=上游原样留档，raw-vod/=点播依赖留档）；"
                     "upstream_deleted=上游已删但本地保留最后可用版，发布产物继续引用"),
            "upstreams": raw_store.summarize(os.path.join(raw_store.RAW_DIR)),
            "upstreams_changed": rawstore_changed,
            "vod_deps": raw_store.summarize(raw_store.RAW_VOD_DIR),
            "vod_verify_active": RAW_VOD_VERIFY_ACTIVE,
            "vod_dep_transitions": dep_stats.get("raw_counts", {}),
        },
        "adult_clean": {
            "note": "2026-09-23 adult.json 生成逻辑优化：多信号分类 + 解析池清洗 + 上游归类",
            "parses_clean_stats": parse_stats,
            "origin_votes_strong_signal": origin_votes,
            "adult_breakdown_by_origin": dict(adult_origin_breakdown),
        },
        "lives_by_category": live_stats,
        "stores": stores_summary,
        "local_ref_audit": {
            "note": "写入前核验站点 ./ 本地依赖；主配置(tvbox/vod)与分类产物死引用站点均已剔除（MAIN_DROP_DEAD_REFS=0 时主配置仅记录）",
            "dropped": local_ref_audit,
        },
        "products": {"note": "产物 sha256 指纹（前 12 位）与字节数", "items": products},
        # P1-6：interfaces/removed_sites/upstreams_health 详细字段迁到 exports/upstream_status.json
        "top_interfaces": sorted(
            ({"name": r["name"], "sites": r["sites"], "http_ms": r["http_ms"], "grade": r["grade"]}
             for r in usable_config), key=lambda x: (-x["sites"], x["http_ms"]),
        )[:15],
    }
    # P1-6：详细上游状态迁 exports/upstream_status.json（status.json 只留摘要）
    # 公开账本同「不声明」口径：interfaces 用已过滤的 _pub_interfaces，removed 记录同规则再过一遍
    try:
        os.makedirs("exports", exist_ok=True)
        _removed_pub, _rm_hidden = public_list_filter(removed)
        if _rm_hidden:
            print(f"    [adult] upstream_status removed_sites 剥除 {len(_rm_hidden)} 条", flush=True)
        _upstream_detail = {"interfaces": _pub_interfaces, "removed_sites": _removed_pub,
                             "upstreams_health": status.get("upstreams_health", {}),
                             "generated_at": generated_at}
        with open("exports/upstream_status.json", "w", encoding="utf-8") as _uf:
            json.dump(_upstream_detail, _uf, ensure_ascii=False, indent=1)
    except OSError:
        pass
    with open("status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)

    print(f"[6/6] 输出完成：tvbox.json / vod.json / live.json / short.json / adult.json / list.json / status.json / checks.json / lives/* / stores/* @ {generated_at}",
          flush=True)
    # 依赖收集worker线程可能因网络挂起（Windows下urllib connect对防火墙静默丢包不超时），
    # shutdown(wait=False)后仍阻止进程退出。所有产出已落盘，强制退出确保CI不超时。
    os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
