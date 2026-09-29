"""每日构建前的 GitHub 镜像复测：实测候选镜像的延迟与下载速度，动态重排 GH_MIRRORS。

背景：公共镜像寿命短（6-18 个月）、速度随时间漂移。产出配置的内部引用与入口线路
统一使用 GH_MIRRORS[0]（GHPROXY），因此每次构建前用本项目真实文件实测一轮，
把存活且最快的镜像排到首位。用户设备无法直连 raw.githubusercontent.com（2026-09-19 确认）。

用法：python scripts/mirror_probe.py
  - 检测到 GITHUB_ENV 环境变量时，把重排后的顺序写入 GH_MIRRORS（fetch_merge.py 自动读取）；
  - 全部候选不可达时不写环境变量，fetch_merge.py 回退内置默认顺序；
  - 任何异常都不抛出（exit 0），探测失败不阻塞每日构建。

防假成功校验（2026-09-19 实测报告 github-proxy-report.md 核心发现）：
  部分失效镜像对文件请求返回 HTTP 200，但响应体是 HTML 首页冒充文件（实测 4 站如此），
  仅按状态码/字节数判断会把 HTML 当配置写进产物。因此：
  - 小文件 stores/duocang.json（JSON）：首字符必须是 { 或 [；
  - 大文件 spider.jar（zip 包）：前 4 字节必须是 PK\x03\x04；
  - 校验不过的候选判 dead，在输出中单列为「假成功」，不参与排序。

测速对象：
  - 小文件 stores/duocang.json（~1KB）：TTFB 延迟（配置加载体验）；
  - 大文件 deps/jar/yt_a4a15fb7.jar（8.0MB，每站最多读 4MB）：**吞吐速度按「首包之后的
    传输段」计算**，不含 TTFB。此前用 1.9MB 的 jar，字节太少容易被 CDN 热缓存和首包
    延迟主导，慢镜像与快镜像分不开（2026-09-29 所有者要求改用大文件实测）。
    大文件全部 404/拉不动时自动退化到 1.9MB 兜底包，再不行退化为纯延迟排序。
  - 每站总时限 12s（MIRROR_PROBE_DEADLINE）：到点按已读字节算速度并标记截断，慢镜像
    不许磨时间；低于 MIRROR_MIN_KBPS（默认 100KB/s）判慢，直接移出 GH_MIRRORS。
    全部被判慢时（并发压穿 runner 带宽等）保留测速结果，避免镜像池被清空。
  - 大文件每站采 2 次取**较差的一次**（MIRROR_PROBE_SAMPLES=1 可退回单次）。理由：
    并发共享带宽 + 镜像侧缓存冷热，单样本轮间排名乱跳（2026-09-29 实测同一镜像
    两轮 2822KB/s ↔ 375KB/s，名次从第 2 掉到第 23），而首位会被写进静态 JSON 的
    外链前缀，必须可复现。取较差值而非平均，是宁可低估也不给侥幸高分让位。
  - 结果落盘 state/mirror_ranking.json（保留最近 7 轮），fetch_merge.py 在没有
    GH_MIRRORS 环境变量时读它，本地跑不再退到静态默认顺序。
  - 直连 raw.githubusercontent.com 在本环境被墙（2026-09-29 复测 RemoteDisconnected），
    所以测速只能经镜像前缀，这正是产物里引用镜像前缀的原因。
"""

import collections
import concurrent.futures as cf
import json
import os
import re
import time
import urllib.parse
import urllib.request

RAW_BASE = "https://raw.githubusercontent.com/hebijunge/tvbox-config/main"
TARGET_SMALL = RAW_BASE + "/stores/duocang.json"
# 依次尝试：8MB jar 优先，路径迁移时退化到 1.9MB
TARGETS_BIG = [RAW_BASE + "/deps/jar/yt_a4a15fb7.jar",
               RAW_BASE + "/deps/jar/spider_8955438d.jar"]
# 每站最多读多少字节、单站总时限、单次读超时、判慢门槛。
# 时限必须是 wall-clock 总时限：urllib 的 timeout 只管单次 socket 读，
# 慢镜像每次读都在超时内返回，可以合法磨满几分钟把整轮拖住（2026-09-29 实测
# wget.la 17KB/s 单站磨了 240s，整轮从 90s 涨到 4m14s）。到点就用已读字节算速度。
PROBE_BYTES = int(os.environ.get("MIRROR_PROBE_BYTES", "4194304"))
PROBE_DEADLINE = float(os.environ.get("MIRROR_PROBE_DEADLINE", "12"))
PROBE_READ_TIMEOUT = int(os.environ.get("MIRROR_PROBE_READ_TIMEOUT", "8"))
MIN_KBPS = int(os.environ.get("MIRROR_MIN_KBPS", "100"))
# 每站大文件采样次数，取较差的一次（见模块 docstring 的轮间抖动实测）
PROBE_SAMPLES = max(1, int(os.environ.get("MIRROR_PROBE_SAMPLES", "2")))
# 并发：越低干扰越小，排名越可复现（6 路并发曾把排名变成掷骰子）
WORKERS = int(os.environ.get("MIRROR_PROBE_WORKERS", "3"))
RANKING_FILE = os.environ.get("MIRROR_RANKING_FILE", "state/mirror_ranking.json")
RANKING_KEEP_ROUNDS = int(os.environ.get("MIRROR_RANKING_KEEP_ROUNDS", "7"))

# 候选镜像（域名式前缀，支持 raw + release；顺序仅是初始值，实际以每日实测重排为准）。
# 候选池 2026-09-19 依据两份独立实测报告合并更新：
#   A《GitHub代理实测榜单》太原家宽 12.25MB git 包实测（极速/快速档）；
#   B《github-proxy-report》海外节点 91.5MB Release + sha256 实测（真可用/黑名单）。
# 两报告测试环境不同，速度绝对值不可直接对比，真假判定通用；实际顺序以本轮实测为准。
# 已剔除（报告B黑名单/实测失效）：gh.llkk.cc、ghp.ci、mirror.ghproxy.com、
#   ghproxy.homeboyc.cn、ghproxy.cn、ghproxy.link、mirror.houlang.cloud、down.npee.cn、
#   moeyy.cn/gh-proxy；ghproxy.net（B 实测截断 27KB/s、A 仅 97KB/s）；gh-proxy.net（无实测证据）。
CANDIDATES = [
    # —— 2026-09-29 所有者指令：本机实测不可达者移出候选池 ——
    #   ghfast.top（不可达）、ghproxy.cc（不可达）、gh.xxooo.cf（不可达）已删。
    # —— 报告B 真可用/可用档（海外节点实测，sha256 三方一致）——
    "https://gh-proxy.com/",        # B 第一 20.5MB/s 三轮极稳；A 太原视角仅 145KB/s（环境差异）
    "https://gh.acmsz.top/",        # 所有者 09-29 指定：本机 1.86MB 实测 0.82MB/s 最快
    "https://gh.xmly.dev/",         # B 第三 8.4MB/s
    "https://githubproxy.cc/",      # B 7.2MB/s；A 中速档 1740KB/s（双报告交叉可用）
    "https://gh.sixyin.com/",       # B 4.9MB/s；A 862KB/s
    "https://proxy.vvvv.ee/",       # B 6.3MB/s
    # —— 报告A 极速档 Top13（太原 ≥3MB/s）——
    "https://github.dpik.top/",
    "https://gh.halonice.com/",
    "https://gh.padao.fun/",
    "https://github.cnxiaobai.com/",
    "https://cfgh.ikgy.top/",
    "https://ghproxy.felicity.land/",
    "https://gh.927223.xyz/",
    "https://30006000.xyz/",
    "https://ghproxy.imciel.com/",
    "https://wget.la/",
    "https://gh.dpik.top/",
    "https://github.tbap.top/",
    # —— 报告A 快速档（2-3MB/s）代表 ——
    "https://github.mayx.eu.org/",
    "https://git.820828.xyz/",
    "https://gh.zwy.one/",          # 原候选保留；A 2960KB/s
    "https://github.boringhex.top/",
    "https://fastgit.cc/",
    "https://github.mxw.qzz.io/",
    "https://gh.felicity.ac.cn/",
    "https://ghf.xn--eqrr82bzpe.top/",  # 报告A 21名 2833KB/s（中文域名 ghf.无名氏.top 的 IDNA 形式）
    # —— 原候选中实测仍存活的兜底 ——
    "https://ghproxy.cxkpro.top/",  # A 742KB/s 存活
    "https://v6.gh-proxy.org/",     # 历史实测存活兜底（两份报告均未覆盖）
]

UA = {"User-Agent": "tvbox-config-mirror-probe"}

# ---------------- 新镜像发现（固定池之外的增量来源） ----------------
# 从公网挖新代理，两条路：
#   1. GitHub API 搜「gh-proxy / ghproxy」相关仓库，读它们的 README 与 homepage ——
#      公共实例域名通常就写在项目首页；有 GITHUB_TOKEN 配额更高，本地无 token 也能匿名搜。
#   2. Bing 搜「github 加速 镜像 域名 列表」等中文清单帖，抓搜索结果页正文再抽域名。
#      与 discover_upstreams.discover_web 同一姿态：只访问搜索引擎已收录的公开页面，
#      不登录、不碰验证页。
# 提取只认「镜像前缀」这一确证形态（https://<host>/<可选路径>/https?://(raw.githubusercontent|github).com/...），
# 裸域名一律不算，避免把博客站、图床、EPG 站误当镜像。
# 准入还有一道内容一致性闸门：新面孔必须把本项目一个 8MB jar 原样吐回来
# （sha256 与工作区文件逐字节相等）才允许进池——镜像篡改/截断/HTML 冒充都拦得住。
# 局限要写明白：这只证明它对「本仓路径」转发忠实；第三方上游内容是否被改，
# 本地没有可信参照物，无法在此闸门内验证，靠 fetch_merge 侧的 md5/sha256 与人工抽查兜。
# 每轮最多试 NEW_PER_ROUND 个新面孔；近 RECENT_TEST_DAYS 天测过的跳过；
# 判死/判慢/内容不符的进 DEAD_MEMORY 冷却 DEAD_COOLDOWN_DAYS 天，不再骚扰。
MIRROR_LIST_URLS = [u.strip() for u in os.environ.get("MIRROR_LIST_URLS", "").split(",")
                    if u.strip()]
NEW_PER_ROUND = int(os.environ.get("MIRROR_NEW_PER_ROUND", "8"))
DEAD_COOLDOWN_DAYS = int(os.environ.get("MIRROR_DEAD_COOLDOWN_DAYS", "30"))
RECENT_TEST_DAYS = int(os.environ.get("MIRROR_RECENT_TEST_DAYS", "3"))
DISCOVERED_CACHE = os.environ.get("MIRROR_DISCOVERED_CACHE", "state/mirror_discovered.json")
DEAD_MEMORY = os.environ.get("MIRROR_DEAD_MEMORY", "state/mirror_dead.json")
DISCOVER_CACHE_DAYS = float(os.environ.get("MIRROR_DISCOVER_CACHE_DAYS", "2"))
ONLINE_MAX_PAGES = int(os.environ.get("MIRROR_ONLINE_MAX_PAGES", "12"))
ONLINE_MAX_BYTES = 800_000
GH_SEARCH_QUERIES = ["gh-proxy", "ghproxy", "github 加速 镜像"]
GH_SEARCH_REPOS_CAP = int(os.environ.get("MIRROR_GH_SEARCH_REPOS", "12"))
BING_QUERIES = ["github 加速 镜像 域名 列表", "gh-proxy 公共实例 地址",
                "github raw 镜像 站 地址 ghproxy", "ghproxy 可用 域名 2026"]
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PAGE_HOST_RE = re.compile(r"(csdn\.net|zhihu\.com|cnblogs\.com|jianshu\.com|"
                          r"weixin\.qq\.com|segmentfault\.com|36kr\.com|"
                          r"sspai\.com|v2ex\.com|githubusercontent\.com)")
URL_RE = re.compile(r"https?://[^\s\"'<>()\[\],;]+")
PREFIX_PAT = re.compile(
    r"https?://([A-Za-z0-9][A-Za-z0-9._-]*\.[A-Za-z]{2,})/[^\s\"'<>\\)]{0,60}?https?://"
    r"(?:raw\.githubusercontent\.com|github\.com)/")
# 明显不是镜像的：被代理的源站本身与短链服务
PREFIX_HOST_DENY = {"raw.githubusercontent.com", "bit.ly", "t.ly", "github.com",
                    "githubusercontent.com"}


def extract_prefix_hosts(text):
    """从文本里提取「镜像前缀」形态的域名 → Counter（引用次数越多越可能活着）。"""
    c = collections.Counter()
    for m in PREFIX_PAT.finditer(text or ""):
        h = m.group(1).lower()
        if h not in PREFIX_HOST_DENY:
            c[h] += 1
    return c


def _http_text(url, timeout=15, cap=ONLINE_MAX_BYTES, headers=None):
    """通用取文本：任何异常都返回空串（发现路不许影响测速主流程）。"""
    hdr = {"User-Agent": BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9",
           "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}
    hdr.update(headers or {})
    try:
        req = urllib.request.Request(url, headers=hdr)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(cap).decode("utf-8", "ignore")
    except Exception:
        return ""


def _round_epoch(rounds):
    """把 ranking 里的 generated_at（UTC 字符串）转成 epoch 秒，供「近 N 天测过」判断。"""
    import calendar
    out = []
    for rd in rounds or []:
        try:
            stamp = calendar.timegm(time.strptime(str(rd.get("generated_at")),
                                                  "%Y-%m-%d %H:%M:%S UTC"))
        except (ValueError, TypeError):
            stamp = 0
        out.append((stamp, rd))
    return out


def gh_search_hosts():
    """路 1：GitHub API 搜代理相关仓库，从搜索结果描述 / homepage / README 抽镜像前缀。

    匿名也能搜（10 次/分钟），带 GITHUB_TOKEN 配额更高。本环境 GitHub 直连被墙时
    这里整条返回空，不影响 Bing 路与固定池。"""
    hosts = collections.Counter()
    tok = (os.environ.get("GITHUB_TOKEN") or "").strip()
    hdr = {"Accept": "application/vnd.github+json"}
    if tok:
        hdr["Authorization"] = "Bearer " + tok
    seen_repos = set()
    for q in GH_SEARCH_QUERIES:
        url = ("https://api.github.com/search/repositories?"
               + urllib.parse.urlencode({"q": q, "sort": "updated",
                                         "per_page": GH_SEARCH_REPOS_CAP}))
        raw = _http_text(url, timeout=12, headers=hdr)
        try:
            items = (json.loads(raw) or {}).get("items") or []
        except ValueError:
            continue
        for it in items:
            full = it.get("full_name") or ""
            blob = " ".join(filter(None, [it.get("description"), it.get("homepage")]))
            hosts.update(extract_prefix_hosts(blob))
            if not full or full in seen_repos:
                continue
            seen_repos.add(full)
            readme = _http_text("https://api.github.com/repos/%s/readme" % full,
                                timeout=12, cap=1_500_000,
                                headers={**hdr, "Accept": "application/vnd.github.raw"})
            hosts.update(extract_prefix_hosts(readme))
    return hosts


def bing_pages(q, per=10):
    """必应搜索（cn.bing.com 国内稳定）。返回 (SERP 原文, 结果页 URL 列表)。"""
    url = "https://cn.bing.com/search?" + urllib.parse.urlencode({"q": q, "count": per})
    html = _http_text(url)
    found = []
    for m in URL_RE.finditer(html):
        u = m.group(0).rstrip(".,;)")
        if re.search(r"(bing\.com|microsoft|msn\.com)", u, re.I):
            continue
        if PAGE_HOST_RE.search(u):
            found.append(u)
    return html, list(dict.fromkeys(found))[:per]


def bing_hosts():
    """路 2：搜索引擎找公开清单帖，SERP 正文与帖子正文一起抽前缀。"""
    hosts = collections.Counter()
    pages = []
    for q in BING_QUERIES:
        html, found = bing_pages(q)
        hosts.update(extract_prefix_hosts(html))
        pages += found
    for p in list(dict.fromkeys(pages))[:ONLINE_MAX_PAGES]:
        hosts.update(extract_prefix_hosts(_http_text(p)))
    return hosts


def fetch_list_hosts(urls):
    """路 3（可选）：MIRROR_LIST_URLS 显式提供的纯文本清单，按同一正则提取。"""
    hosts = collections.Counter()
    for u in urls:
        hosts.update(extract_prefix_hosts(_http_text(u)))
    return hosts


def online_hosts(force=False):
    """汇总三路公网来源，落盘缓存 DISCOVER_CACHE_DAYS 天（挖一次够几轮用）。"""
    now = time.time()
    cache = _load_json(DISCOVERED_CACHE, {})
    if not force and cache.get("hosts") and \
            now - cache.get("scanned_at", 0) < DISCOVER_CACHE_DAYS * 86400:
        return collections.Counter(cache["hosts"])
    hosts = collections.Counter()
    hosts.update(gh_search_hosts())
    hosts.update(bing_hosts())
    hosts.update(fetch_list_hosts(MIRROR_LIST_URLS))
    try:
        os.makedirs(os.path.dirname(DISCOVERED_CACHE) or ".", exist_ok=True)
        with open(DISCOVERED_CACHE, "w", encoding="utf-8") as f:
            json.dump({"scanned_at": now,
                       "queries": {"github": GH_SEARCH_QUERIES, "bing": BING_QUERIES},
                       "list_urls": MIRROR_LIST_URLS,
                       "hosts": dict(hosts.most_common(300))}, f,
                      ensure_ascii=False, indent=1)
    except OSError:
        pass
    return hosts


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or default
    except (OSError, ValueError):
        return default


def _recent_tested(fixed_hosts, rounds, dead, now=None):
    """本轮该跳过的 host：固定池 + 近 RECENT_TEST_DAYS 天测过的 + 冷却中的判死站。"""
    now = now or time.time()
    skip = set(fixed_hosts)
    for stamp, rd in _round_epoch(rounds):
        if now - stamp > RECENT_TEST_DAYS * 86400:
            continue
        for key in ("ranking", "discovered"):
            for row in rd.get(key) or []:
                h = _host_of(row.get("prefix") or "")
                if h:
                    skip.add(h)
    for h, info in (dead or {}).items():
        if info.get("at", 0) >= now - DEAD_COOLDOWN_DAYS * 86400:
            skip.add(h)
    return skip


def discover_hosts(fixed_hosts, rounds, dead, hosts=None):
    """返回本轮要新试的 [(https://host/ , 出现次数)]，按公网出现频次降序，最多 NEW_PER_ROUND 个。"""
    hosts = hosts if hosts is not None else online_hosts()
    skip = _recent_tested(fixed_hosts, rounds, dead)
    out = []
    for h, n in hosts.most_common():
        if h in skip or h in PREFIX_HOST_DENY:
            continue
        out.append((f"https://{h}/", n))
        if len(out) >= NEW_PER_ROUND:
            break
    return out


def verify_prefix_content(prefix, deadline=None):
    """内容一致性闸门：镜像必须把本项目那个 8MB jar **逐字节原样**吐回来。

    截断、HTML 冒充、改写内容都在这里拦下——新面孔来自公网陌生页面，进池前先验一次。
    时限默认 60s：8MB 在 60s 内下不完就是 <140KB/s，本来也过不了测速门槛，直接拒。
    局限见模块注释：只覆盖本仓路径的转发忠实性。"""
    import hashlib
    deadline = deadline or float(os.environ.get("MIRROR_VERIFY_DEADLINE", "60"))
    local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         TARGETS_BIG[0].split("/main/", 1)[-1])
    if not os.path.isfile(local):
        return True  # 无参照物时不拦（CI 上 jar 在仓内，正常不会走到这里）
    want = hashlib.sha256()
    with open(local, "rb") as f:
        while True:
            blk = f.read(262144)
            if not blk:
                break
            want.update(blk)
    want = want.hexdigest()
    got = hashlib.sha256()
    t0 = time.time()
    try:
        req = urllib.request.Request(prefix + TARGETS_BIG[0], headers=UA)
        with urllib.request.urlopen(req, timeout=PROBE_READ_TIMEOUT) as r:
            n = 0
            while True:
                if time.time() - t0 > deadline:
                    return False  # 超时未完：视为不合格（慢且不可靠）
                chunk = r.read(262144)
                if not chunk:
                    break
                got.update(chunk)
                n += len(chunk)
                if n > 40_000_000:
                    return False
    except Exception:
        return False
    return got.hexdigest() == want


def _host_of(url):
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1).lower() if m else ""


def remember_dead(dead, prefixes, reason, kbps=None):
    now = time.time()
    for p in prefixes:
        h = _host_of(p if isinstance(p, str) else p.get("prefix"))
        if not h or h in {x.rstrip("/").split("//")[-1] for x in CANDIDATES}:
            continue  # 固定池成员只在本轮移出 GH_MIRRORS，不写冷却（每日仍要复测）
        dead[h] = {"reason": reason, "KBps": kbps, "at": now}
    return dead


def _fetch(url, timeout):
    t0 = time.time()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ttfb = time.time() - t0
        body = r.read()
    return ttfb, body, time.time() - t0


def _is_fake_body(body):
    """假成功判定：HTTP 200 但内容不是目标文件（HTML 首页冒充/错误页），须判 dead。"""
    if not body:
        return True
    if body.lstrip()[:1] in (b"{", b"["):  # duocang.json 是 JSON
        return False
    low = body[:256].lower()
    return b"<!doctype" in low or b"<html" in low


def probe_small(prefix):
    """小文件两连测，取最好成绩；返回 (ttfb_ms or None, is_fake)。两次都失败判不可达。"""
    best = None
    for _ in range(2):
        try:
            ttfb, body, _total = _fetch(prefix + TARGET_SMALL, timeout=12)
            if _is_fake_body(body):
                return None, True
            if body:
                best = round(ttfb * 1000)
                break
        except Exception:
            continue
    return best, False


def _fetch_stream(url, timeout, cap, deadline):
    """流式读取至多 cap 字节，受 wall-clock 总时限 deadline 约束。
    返回 (ttfb_ms, 实读字节, 传输段秒数, 前4字节, 是否按时截断)；
    传输段秒数不含首包延迟，吞吐只反映持续下载速度。读途中断流/超时不丢弃：
    已收到的字节照样参与测速（那正是它慢的证据）。"""
    t0 = time.time()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ttfb = time.time() - t0
        head = r.read(4) or b""
        n = len(head)
        t1 = time.time()
        truncated = False
        while n < cap:
            left = deadline - (time.time() - t1)
            if left <= 0:
                truncated = True
                break
            try:
                chunk = r.read(min(262144, cap - n))
            except Exception:
                truncated = True  # 单次读超时/连接断：按已读字节计速
                break
            if not chunk:
                break
            n += len(chunk)
        return round(ttfb * 1000), n, max(time.time() - t1, 0.01), head, truncated


def probe_big(prefix):
    """大文件吞吐实测（不含 TTFB），每站采 PROBE_SAMPLES 次、取较差的一次。
    返回 (KB/s, is_fake, 实读字节, 截断)。拉不动返回 (0, False, 0, False)。"""
    worst = None
    for target in TARGETS_BIG:
        for _ in range(PROBE_SAMPLES):
            try:
                _ttfb, n, secs, head, trunc = _fetch_stream(
                    prefix + target, PROBE_READ_TIMEOUT, PROBE_BYTES, PROBE_DEADLINE)
            except Exception:
                continue  # 连首包都没回来，换下一次采样/兜底文件
            if not head.startswith(b"PK\x03\x04"):  # jar 即 zip 包，魔数 PK
                if n >= 200_000:
                    return 0, True, n, trunc  # 拉到实质内容却不是 zip → 假成功
                continue  # 多半是 404 小页，换兜底文件再判
            if n < 65_536 and not trunc:
                continue  # 样本太小且不是被时限截断，不作数
            kbps = round(n / 1024 / secs)
            if worst is None or kbps < worst[0]:
                worst = (kbps, False, n, trunc)
        if worst is not None:
            return worst
    return 0, False, 0, False


def probe_one(prefix, origin="fixed"):
    base = {"prefix": prefix, "origin": origin, "ttfb_ms": None, "KBps": 0,
            "bytes": 0, "alive": False, "fake": False, "content_bad": False,
            "truncated": False, "score_ok": False}
    if origin == "discovered" and not verify_prefix_content(prefix):
        base["content_bad"] = True  # 公网陌生前缀：内容不忠实直接出局，不测速不入池
        return base
    ttfb, fake_small = probe_small(prefix)
    if fake_small:
        base["fake"] = True
        return base
    kbps, fake_big, nbytes, trunc = (probe_big(prefix) if ttfb is not None
                                     else (0, False, 0, False))
    base.update({"ttfb_ms": ttfb, "KBps": kbps, "bytes": nbytes,
                 "alive": ttfb is not None, "fake": fake_big, "truncated": trunc,
                 "score_ok": ttfb is not None and kbps > 0})
    return base


def save_ranking(summary):
    """落盘测速历史（最新一轮在前，保留 RANKING_KEEP_ROUNDS 轮）。
    本地跑没有 $GITHUB_ENV，靠这个文件把当日实测交给 fetch_merge 用；
    同时供其挑选「多轮都靠前」的稳定镜像做外链改写主镜像。"""
    rounds = []
    try:
        if os.path.isfile(RANKING_FILE):
            old = json.load(open(RANKING_FILE, encoding="utf-8")) or {}
            rounds = old.get("rounds") or []
    except Exception as e:  # noqa: BLE001
        print(f"  [mirror_probe] 旧排名文件不可读（重建）：{type(e).__name__}: {e}")
    rounds.insert(0, {"generated_at": summary["generated_at"],
                      "first": summary["first"],
                      "ranking": summary["ranking"],
                      "discovered": summary.get("discovered") or [],
                      "slow_dropped": summary["slow_dropped"],
                      "fake_success": summary["fake_success"],
                      "dead": summary["dead"]})
    doc = {"version": 1, "big_file": summary["big_file"],
           "probe_bytes_cap": summary["probe_bytes_cap"],
           "probe_deadline_sec": summary["probe_deadline_sec"],
           "min_kbps_floor": summary["min_kbps_floor"],
           "samples": summary["samples"], "workers": summary["workers"],
           "rounds": rounds[:RANKING_KEEP_ROUNDS]}
    try:
        os.makedirs(os.path.dirname(RANKING_FILE) or ".", exist_ok=True)
        with open(RANKING_FILE, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f"  [mirror_probe] 实测已落盘 {RANKING_FILE}"
              f"（{len(doc['rounds'])} 轮历史）")
    except OSError as e:
        print(f"  [mirror_probe] 落盘失败（不阻断，fetch_merge 回退默认顺序）：{e}")


def main():
    rounds_hist = _load_json(RANKING_FILE, {}).get("rounds") or []
    dead_mem = _load_json(DEAD_MEMORY, {})
    fixed_hosts = {_host_of(p) for p in CANDIDATES}
    new_hosts = discover_hosts(fixed_hosts, rounds_hist, dead_mem)
    hits = {p: n for p, n in new_hosts}
    if new_hosts:
        print(f"  [发现] 公网新面孔 {len(new_hosts)} 个（先验内容忠实性再测速）："
              + " ".join(f"{_host_of(p)}×{n}" for p, n in new_hosts))
    tasks = [(p, "fixed") for p in CANDIDATES] + [(p, "discovered") for p, _n in new_hosts]
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(lambda t: probe_one(*t), tasks))

    # 分档：达标镜像按速度降序 → 仅小文件存活的按延迟升序 → 判慢/不可达/假成功/内容不符淘汰
    measured = sorted([r for r in results if r["alive"] and r["KBps"] > 0],
                      key=lambda r: -r["KBps"])
    fast = [r for r in measured if r["KBps"] >= MIN_KBPS]
    slow = [r for r in measured if r["KBps"] < MIN_KBPS]
    ok_small = sorted([r for r in results if r["alive"] and r["KBps"] == 0],
                      key=lambda r: r["ttfb_ms"])
    fake = [r for r in results if r["fake"]]
    bad_content = [r for r in results if r["content_bad"]]
    dead = [r for r in results if not r["alive"] and not r["fake"] and not r["content_bad"]]
    # 判慢的不进 GH_MIRRORS：留着只会在拉取时白等一轮时限。全部被判慢时（例如
    # runner 侧带宽被并发压穿）保留测速结果，避免把镜像池清空。
    if fast:
        ordered = fast + ok_small
    else:
        ordered = measured + ok_small
        slow = []

    # MIRROR_PIN：用户侧手动钉首位（仓库 Actions Variable / 环境变量皆可）。
    # 探测视角是 CI runner 的网络，不代表用户手机侧；用户实测更快者可钉住首位，其余仍自动重排。
    pin = os.environ.get("MIRROR_PIN", "").strip()
    if pin:
        pinned = None
        rest = []
        for r in ordered:
            if r["prefix"].rstrip("/") == pin.rstrip("/"):
                pinned = r
            else:
                rest.append(r)
        if pinned:
            ordered = [pinned] + rest
            print(f"MIRROR_PIN 生效：首位固定为 {pin.rstrip('/')}")

    pool_set = {r["prefix"].rstrip("/") for r in ordered}
    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "first": ordered[0]["prefix"].rstrip("/") if ordered else None,
        "alive": len(fast) + len(slow) + len(ok_small),
        "big_file": TARGETS_BIG[0],
        "probe_bytes_cap": PROBE_BYTES,
        "probe_deadline_sec": PROBE_DEADLINE,
        "min_kbps_floor": MIN_KBPS,
        "samples": PROBE_SAMPLES,
        "workers": WORKERS,
        "fake_success": [r["prefix"] for r in fake],
        "slow_dropped": [{"prefix": r["prefix"].rstrip("/"), "KBps": r["KBps"]}
                         for r in slow],
        "dead": [r["prefix"] for r in dead],
        "ranking": [{"prefix": r["prefix"].rstrip("/"), "ttfb_ms": r["ttfb_ms"],
                     "KBps": r["KBps"], "bytes": r["bytes"],
                     "capped": r["truncated"], "origin": r["origin"]}
                    for r in ordered],
        # 新面孔全量留档（含被淘汰的）：既给人看战果，也让下一轮跳过它们
        "discovered": [{"prefix": r["prefix"].rstrip("/"), "hits": hits.get(r["prefix"], 0),
                        "KBps": r["KBps"], "ttfb_ms": r["ttfb_ms"],
                        "alive": r["alive"], "fake": r["fake"],
                        "content_bad": r["content_bad"],
                        "in_pool": r["prefix"].rstrip("/") in pool_set}
                       for r in results if r["origin"] == "discovered"],
    }
    print("== 镜像实测排名 ==")
    print(f"  吞吐口径：大文件 {TARGETS_BIG[0].rsplit('/', 1)[-1]}，"
          f"每站最多读 {PROBE_BYTES // 1024}KB、总时限 {PROBE_DEADLINE:.0f}s，"
          f"每站采 {PROBE_SAMPLES} 次取较差值，并发 {WORKERS} 路；<{MIN_KBPS}KB/s 判慢淘汰")
    for i, r in enumerate(ordered, 1):
        flag = "（按时限截断）" if r["truncated"] else ""
        tag = " *新" if r["origin"] == "discovered" else ""
        print(f"  {i}. {r['prefix'].rstrip('/')}{flag}  ttfb={r['ttfb_ms']}ms  "
              f"{r['KBps']}KB/s（读 {r['bytes'] / 1048576:.1f}MB）{tag}")
    for r in slow:
        print(f"  ~. {r['prefix'].rstrip('/')}  {r['KBps']}KB/s 判慢，已移出 GH_MIRRORS")
    for r in fake:
        print(f"  x. {r['prefix'].rstrip('/')}  假成功（HTTP 200 但内容非目标文件，判 dead）")
    for r in bad_content:
        print(f"  x. {r['prefix'].rstrip('/')}  内容不一致（未原样返回目标 jar），拒入池")
    for r in dead:
        print(f"  x. {r['prefix'].rstrip('/')}  不可达")
    if summary["discovered"]:
        added = [d for d in summary["discovered"] if d["in_pool"]]
        print(f"  [发现] 公网 {len(summary['discovered'])} 个新面孔，"
              f"通过忠实性+测速入池 {len(added)} 个"
              + ("：" + " ".join(f"{d['prefix'].split('//')[-1].rstrip('/')} "
                                 f"{d['KBps']}KB/s" for d in added) if added else ""))
    # 判死记忆：本轮出局的新面孔记入冷却，DEAD_COOLDOWN_DAYS 内不再浪费测速额度
    rejected = ([r["prefix"] for r in bad_content] + [r["prefix"] for r in fake]
                + [r["prefix"] for r in dead] + [r["prefix"] for r in slow])
    rejected = [p for p in rejected if _host_of(p) not in fixed_hosts]
    if rejected:
        remember_dead(dead_mem, rejected, "probe-rejected")
        try:
            os.makedirs(os.path.dirname(DEAD_MEMORY) or ".", exist_ok=True)
            with open(DEAD_MEMORY, "w", encoding="utf-8") as f:
                json.dump(dead_mem, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
    if ordered:
        save_ranking(summary)
    print(json.dumps(summary, ensure_ascii=False))

    if not ordered:
        print("所有候选不可达，不写 GH_MIRRORS，fetch_merge.py 回退内置默认顺序")
        return

    new_mirrors = ",".join(r["prefix"] for r in ordered)
    gh_env = os.environ.get("GITHUB_ENV")
    if gh_env:
        with open(gh_env, "a", encoding="utf-8") as f:
            f.write(f"GH_MIRRORS={new_mirrors}\n")
        print(f"GH_MIRRORS 已写入 GITHUB_ENV（{len(ordered)} 个存活镜像，首位 {ordered[0]['prefix'].rstrip('/')}）")
    else:
        print(f"GH_MIRRORS={new_mirrors}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 探测绝不阻塞每日构建
        print(f"mirror_probe 异常（忽略，回退默认顺序）: {type(e).__name__}: {e}")
