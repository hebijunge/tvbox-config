#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全网上游自动发现：把「人工维护的 40 条清单」升级为「自动检索 + 自动评级 + canary 收编」。

四路发现（有 GITHUB_TOKEN 时全开，否则自动降级，不会报错）：
  1. 代码搜索   搜 TVBox 配置特征串，捞出「没人 star 但内容对」的新仓（**需要 token**）
  2. 仓库搜索   按 topic / 关键词找聚合仓（未认证也可用）
  3. 种子递归   导航仓 README → 内部链接 → 二级页面
  4. 血统反查   从已收录源的 GitHub 地址反查同仓其他配置（同族 json 常成批存在）

每条候选做 L0 形态探测（JSON 含 sites / #EXTM3U / txt）并打分，产出：
    radar/discovered.json      候选池（含评分与证据，供人工查看）
    state/extra_upstreams.json canary 名单（fetch_merge.py 会自动并入拉取）

用法
----
    python scripts/discover_upstreams.py                       # 全路发现
    python scripts/discover_upstreams.py --max-repos 10
    python scripts/discover_upstreams.py --no-code-search      # 跳过需要 token 的一路
"""

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = {"User-Agent": "tvbox-config-radar", "Accept": "*/*"}
GH_ACCEPT = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _load_token() -> str:
    """取 GitHub token：优先环境变量（CI 里用 secrets.GITHUB_TOKEN），
    其次读仓库外的本地凭据文件（保证 token 永远不落进版本库）。"""
    env = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if env.strip():
        return env.strip()
    for p in (os.path.expanduser("~/.workbuddy/secrets/tvbox-github-token"),
              os.path.expanduser("~/.github-token")):
        try:
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    tok = f.read().strip()
                if tok:
                    return tok
        except OSError:
            continue
    return ""


TOKEN = _load_token()

# 配置特征串：能命中「已经是一份 TVBox 配置」的仓库，而不是泛泛的 tvbox 关键词
CODE_QUERIES = [
    '"api.php/provide/vod" extension:json',
    '"sites" "spider" "parses" extension:json',
    '"type": 3 "spider" extension:json',
]
REPO_QUERIES = [
    "tvbox in:name,description",
    "topic:tvbox",
    "topic:tvbox-config",
    "topic:catvod",
    "topic:tvbox-interface",
    "影视仓 in:name,description",
    "tvbox config in:name,description",
    "catvod in:name,description",
    "iptv in:name,description",
]
SEEDS = [
    ("QingNing", "https://raw.githubusercontent.com/Zhou-Li-Bin/Tvbox-QingNing/main/README.md"),
    ("ngo5", "https://raw.githubusercontent.com/ngo5/IPTV/main/README.md"),
    ("dongyubin", "https://raw.githubusercontent.com/dongyubin/IPTV/main/README.md"),
    # 2026-09-21 点播+容错线：noimank/tvbox 走发现通道（第二批/第三批报告判定：不直接作上游，
    # 其 tvboxmuti.json 为多仓索引，经种子路展开比单点接入更稳）
    ("noimank", "https://raw.githubusercontent.com/noimank/tvbox/main/tvboxmuti.json"),
]

URL_RE = re.compile(r"https?://[^\s\"'<>\\)\]]+", re.I)
DROP_RE = re.compile(
    r"github\.com/[^/]+/[^/]+/(tree|blob|issues|pull|actions)|img\.shields\.io|badge|"
    r"avatars|\.png|\.jpg|\.svg|\.ico|\.webp|\.zip|\.apk|\.exe", re.I)


def http_get(url, timeout=10, max_bytes=0, headers=None):
    """拉取；raw.githubusercontent.com 直连不通时走镜像兜底。

    实测：种子 README 与候选探测在本地/CI 都可能遇到 raw 直连失败（三路种子全挂），
    没有兜底会让第 3 路直接失效——所以这里必须带镜像回退。
    """
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(max_bytes) if max_bytes else r.read()
    except Exception:
        if "raw.githubusercontent.com" in url:
            mirror = "https://ghproxy.net/" + url
            req2 = urllib.request.Request(mirror, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req2, timeout=timeout) as r:
                return r.status, r.read(max_bytes) if max_bytes else r.read()
        raise


def gh_api(path, params=None):
    """GitHub REST 调用。无 token 时用匿名配额，超限返回 None 而不抛错。"""
    url = "https://api.github.com" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = dict(GH_ACCEPT)
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        st, raw = http_get(url, 20, 0, headers)
        return json.loads(raw.decode("utf-8", "replace")) if st == 200 else None
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def raw_url(full_name, branch, path):
    """构造 raw 地址。路径必须编码：仓库里带空格的文件名（如 'IPTV Playlist.m3u'）会直接让 URL 非法。"""
    return (f"https://raw.githubusercontent.com/{full_name}/"
            f"{urllib.parse.quote(branch, safe='')}/{urllib.parse.quote(path, safe='/')}")


def sites_of(doc):
    """从各种顶层形态里提取站点数组 —— 上游格式并不统一。

    实测教训：只看「顶层 dict + sites 键」会把有效配置误判成垃圾。
    例如 mingjunkirs/tv-config-aggregator 的 sources.json（顶层是数组/嵌套），
    按旧逻辑被判为 other、score 压到 30，但它实际带来 17 个独有站点。
    所以判据必须是「能不能解析出站点数组」，而不是「结构长什么样」。
    """
    if isinstance(doc, list):
        return [x for x in doc if isinstance(x, dict) and (x.get("api") or x.get("name"))]
    if isinstance(doc, dict):
        for key in ("sites", "video"):
            v = doc.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        # 嵌套形态：{"data":{"sites":[...]}} / {"config":{...}}
        for k in ("data", "result", "config", "list"):
            sub = doc.get(k)
            if isinstance(sub, dict):
                for key in ("sites", "video"):
                    sv = sub.get(key)
                    if isinstance(sv, list):
                        return [x for x in sv if isinstance(x, dict)]
    return []


def probe_candidate(url):
    """L0 形态探测：判断候选到底是 tvbox 配置、m3u 还是别的。"""
    r = {"url": url, "reachable": False, "kind": None, "score": 0, "evidence": {}}
    try:
        st, raw = http_get(url, 12, 300_000)
    except Exception as e:  # noqa: BLE001  探测边界：单条候选的任何异常都不该打断整轮扫描
        r["error"] = f"{type(e).__name__}"[:60]
        return r
    if st != 200 or not raw:
        r["error"] = f"HTTP {st}"
        return r
    r["reachable"] = True
    r["bytes"] = len(raw)
    text = raw.decode("utf-8", "replace").lstrip("\ufeff \t\r\n")

    if text.startswith("#EXTM3U") or "#EXTM3U" in text[:2000]:
        entries = text.count("#EXTINF")
        r.update({"kind": "m3u", "score": 30 + (30 if entries >= 20 else 10),
                  "evidence": {"entries": entries}})
        return r
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        r.update({"kind": "other", "score": 0})
        return r
    # 关键修正：以「能否解析出站点数组」为准（兼容裸数组/嵌套），不再因顶层非 dict 就判废
    sites = sites_of(doc)
    if not sites:
        r.update({"kind": "json(非配置)", "score": 0})
        return r
    is_dict = isinstance(doc, dict)
    lives = doc.get("lives") if is_dict else []
    parses = doc.get("parses") if is_dict else []
    spider = bool(doc.get("spider")) if is_dict else False
    score = 60
    n = len(sites)
    if n >= 10:
        score += 20
    elif n >= 3:
        score += 10
    if spider:
        score += 10
    r.update({"kind": "tvbox", "score": min(score, 100),
              "evidence": {"sites": n, "lives": len(lives or []), "parses": len(parses or []),
                           "spider": spider}})
    return r


def known_urls():
    """已收录的上游 URL，避免重复推荐。"""
    urls, repos = set(), set()
    try:
        from fetch_merge import ALL_UPSTREAMS  # noqa: PLC0415
        for u in ALL_UPSTREAMS:
            urls.add(u.get("url", ""))
            m = re.search(r"raw\.githubusercontent\.com/([^/]+/[^/]+)/", u.get("url", ""))
            if m:
                repos.add(m.group(1))
    except ImportError:
        pass
    # 血统反查：从 deps manifest 里提取出处的仓库
    for f in ("deps/manifest.json",):
        if os.path.isfile(f):
            try:
                with open(f, encoding="utf-8") as fh:
                    txt = fh.read()
                for m in re.finditer(r"raw\.githubusercontent\.com/([^/\"\s]+/[^/\"\s]+)/", txt):
                    repos.add(m.group(1))
            except OSError:
                pass
    return urls, repos


def discover_code_search(max_repos, pages=2):
    """第 1 路：GitHub 代码搜索（需 token）。支持翻页扩大召回。"""
    if not TOKEN:
        print("  [跳过] 代码搜索需要 GITHUB_TOKEN", flush=True)
        return set()
    repos = set()
    for q in CODE_QUERIES:
        total = 0
        for page in range(1, max(1, pages) + 1):
            doc = gh_api("/search/code", {"q": q, "per_page": 30, "page": page, "sort": "indexed"})
            if not doc:
                break
            n = 0
            for item in doc.get("items", []):
                fn = (item.get("repository") or {}).get("full_name")
                if fn:
                    repos.add(fn)
                    n += 1
            total += n
            if n == 0:
                break                      # 该查询已翻到最后一页
            time.sleep(2)
        print(f"  [代码搜索] {q[:40]} → {total} 仓", flush=True)
    return set(list(repos)[:max_repos])


def discover_repo_search(max_repos):
    """第 2 路：仓库搜索（未认证可用）。"""
    repos = set()
    for q in REPO_QUERIES:
        doc = gh_api("/search/repositories", {"q": q, "sort": "updated", "per_page": 30})
        if not doc:
            print(f"  [仓库搜索] {q[:30]} → 无结果/受限", flush=True)
            continue
        for item in doc.get("items", []):
            repos.add(item.get("full_name"))
        print(f"  [仓库搜索] {q[:30]} → {doc.get('total_count')} 命中", flush=True)
        time.sleep(1)
    return set(list(repos)[:max_repos])


def discover_seeds():
    """第 3 路：种子仓 README 及其二级链接。"""
    urls = set()
    for name, url in SEEDS:
        try:
            st, raw = http_get(url, 12, 600_000)
        except (urllib.error.URLError, OSError, ValueError):
            print(f"  [种子] {name} 拉取失败", flush=True)
            continue
        text = raw.decode("utf-8", "replace")
        found = 0
        for m in URL_RE.finditer(text):
            u = m.group(0).rstrip(".,;")
            if DROP_RE.search(u):
                continue
            if re.search(r"\.(json|m3u|txt)(\?|$)|/tvbox|/live", u, re.I):
                urls.add(u)
                found += 1
        print(f"  [种子] {name} → {found} 条候选链接", flush=True)
    return urls


# ---- 2026-09-21 点播+容错线：第二批 P1 —— laoma2053/awesome-zhuiju-free 作为扩源第五路 ----
# 9234★，机器可读清单 resources/resources.json（category=tvbox_config 条目）
# + 每日 Actions 验活 reports/availability.json。只取验活 reachable 的条目进候选流，
# L0 探测仍会二次把关；验活不过的如实丢弃（报告已记录 401/403 的 restricted 情况）。
ZHUIJU_RES = "https://raw.githubusercontent.com/laoma2053/awesome-zhuiju-free/main/resources/resources.json"
ZHUIJU_AVAIL = "https://raw.githubusercontent.com/laoma2053/awesome-zhuiju-free/main/reports/availability.json"


def discover_zhuiju():
    try:
        st, raw = http_get(ZHUIJU_RES, 15, 2_000_000)
        res = json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001 —— 第五路整体可失败，不影响其它六路
        print(f"  [追剧] resources.json 拉取失败：{e}", flush=True)
        return set()
    resources = res.get("resources", []) if isinstance(res, dict) else []
    tvbox = [r for r in resources if r.get("category") == "tvbox_config" and r.get("url")]

    ok_ids = set()
    try:
        st2, raw2 = http_get(ZHUIJU_AVAIL, 15, 2_000_000)
        avail = json.loads(raw2.decode("utf-8", "replace"))
        for r in avail.get("results", []):
            if r.get("status") == "reachable":
                ok_ids.add(r.get("resource_id"))
    except Exception as e:  # noqa: BLE001 —— 验活清单缺失时退化为不筛（交给 L0 探测兜底）
        print(f"  [追剧] availability.json 拉取失败（退化为不筛验活）：{e}", flush=True)
        ok_ids = None

    urls = set()
    skipped = 0
    for r in tvbox:
        if ok_ids is not None and r.get("id") not in ok_ids:
            skipped += 1
            continue
        u = r["url"].strip()
        if u.startswith("http"):
            urls.add(u)
    print(f"  [追剧] tvbox_config {len(tvbox)} 条，验活通过 {len(urls)} 条"
          f"（验活不过丢弃 {skipped} 条）", flush=True)
    return urls


# ---- 2026-09-21 点播+容错线：第四批 P2 —— QingNing README 结构化分节解析 ----
# README 为「> * **【标签】名称：**」+ 下一行 URL 的配对格式（标签驱动，不做数量硬编码；
# 实测快照漂移：调研日 单仓122/多仓12/直播12，当日快照 单仓114/多仓10/直播类8）。
# 【单仓】【多仓】URL → 返回给候选流；【电视】【广播】等直播类 URL → 落 radar/live_seeds.json
# 转直播线任务，不进点播候选流；【成人】等敏感标签一律跳过。
QN_README = SEEDS[0][1]
QN_LIVE_LABELS = {"电视", "广播", "小飞电视", "频道多多", "直播"}
QN_SKIP_LABELS = {"成人", "推荐老手", "国外的没有"}


def discover_qingning(live_out="radar/live_seeds.json"):
    try:
        st, raw = http_get(QN_README, 15, 600_000)
    except Exception as e:  # noqa: BLE001
        print(f"  [青柠] README 拉取失败：{e}", flush=True)
        return set(), set()
    lines = raw.decode("utf-8", "replace").split("\n")
    warehouse, live, cur = set(), set(), None
    for ln in lines:
        m = re.search(r"【([^】]+)】", ln)
        if m:
            cur = m.group(1).strip()
            continue
        if cur is None:
            continue
        um = re.search(r"https?://[^\s\"'<>\\)\]]+", ln)
        if not um:
            continue
        u = um.group(0).rstrip(".,;")
        if cur in QN_LIVE_LABELS:
            live.add(u)
        elif cur not in QN_SKIP_LABELS and cur in ("单仓", "多仓"):
            warehouse.add(u)
        cur = None
    print(f"  [青柠] 单仓/多仓 {len(warehouse)} 条进候选流，直播类 {len(live)} 条转直播线",
          flush=True)
    if live:
        try:
            os.makedirs(os.path.dirname(live_out) or ".", exist_ok=True)
            with open(live_out, "w", encoding="utf-8") as f:
                json.dump({"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "note": "QingNing README 直播类标签解析结果，转直播线任务处理，不进点播候选流",
                           "source": QN_README, "total": len(live), "urls": sorted(live)},
                          f, ensure_ascii=False, indent=1)
        except OSError as e:
            print(f"  [青柠] live_seeds 写入失败：{e}", flush=True)
    return warehouse, live


def discover_lineage(known_repos, max_repos):
    """第 4 路：血统反查 —— 已收录源所在仓库的同 owner 其他仓。

    同族配置常成批存在（一个人/组织往往维护好几个 box 仓）。从已知 owner 反查，
    能捞到「已经在生态内、有同源血统、但我们还没收录」的配置——
    比满网乱搜的命中率高得多。
    """
    owners, seen = [], set()
    for full in known_repos:
        if "/" not in full:
            continue
        owner = full.split("/")[0]
        if owner and owner not in seen:
            seen.add(owner)
            owners.append(owner)
    repos = set()
    for owner in owners[:30]:
        # /users/{owner}/repos 对组织同样有效（GitHub 会跟随重定向）
        doc = gh_api(f"/users/{owner}/repos", {"per_page": 30, "sort": "updated"})
        if not doc or not isinstance(doc, list):
            continue
        n = 0
        for it in doc:
            fn = it.get("full_name")
            if fn and fn not in known_repos:
                repos.add(fn)
                n += 1
        if n:
            print(f"  [血统反查] {owner} → {n} 个新仓", flush=True)
        time.sleep(1)
    return set(list(repos)[:max_repos])


# ---------------- 第 5 路：Gitee ----------------
# 国内大量 TVBox 配置托管在 Gitee（GitHub 常连不上，很多作者首选 Gitee），
# 此前四路全部走 GitHub，等于漏掉整个国内盘。Gitee OpenAPI(v5) 匿名即可用。
# 在 GitHub 配置文件里挖「引用了 gitee.com 的配置」，从中提取 Gitee 仓库全名。
# （Gitee 自家搜索 API 已被平台限制为空、网页搜索需登录+WAF，见 discover_gitee 注释）
GITEE_HUNT_QUERIES = [
    '"gitee.com" "sites" "spider" extension:json',
    '"gitee.com" "api.php/provide/vod" extension:json',
]


def _gitee_token() -> str:
    """Gitee token：优先环境变量，其次读仓库外秘密文件（绝不入库）。"""
    env = os.environ.get("GITEE_TOKEN") or ""
    if env.strip():
        return env.strip()
    for p in (os.path.expanduser("~/.workbuddy/secrets/tvbox-gitee-token"),):
        try:
            if os.path.isfile(p):
                t = open(p, encoding="utf-8").read().strip()
                if t:
                    return t
        except OSError:
            continue
    return ""


def gitee_api(path, params=None):
    """Gitee OpenAPI v5。搜索类接口必须认证（匿名一律空结果/受限）。"""
    url = "https://gitee.com/api/v5" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    tok = _gitee_token()
    if tok:
        url += ("&" if "?" in url else "?") + "access_token=" + urllib.parse.quote(tok)
    try:
        st, raw = http_get(url, 20, 0, {"Accept": "application/json"})
        return json.loads(raw.decode("utf-8", "replace")) if st == 200 else None
    except Exception:
        return None


def gitee_raw_url(full_name, branch, path):
    return (f"https://gitee.com/{full_name}/raw/"
            f"{urllib.parse.quote(branch, safe='')}/{urllib.parse.quote(path, safe='/')}")


def gitee_files_of(full_name):
    """列出 Gitee 仓库里值得探测的配置文件。"""
    info = gitee_api(f"/repos/{full_name}")
    if not info:
        return []
    branch = info.get("default_branch") or "master"
    tree = gitee_api(f"/repos/{full_name}/git/trees/{branch}", {"recursive": "1"})
    if not tree:
        return []
    out = []
    for it in tree.get("tree", []):
        p = it.get("path") or ""
        if it.get("type") != "blob":
            continue
        if not p.lower().endswith((".json", ".m3u", ".txt")):
            continue
        if (it.get("size") or 0) < 500 or (it.get("size") or 0) > 12 * 1024 * 1024:
            continue
        if re.search(r"(node_modules|package-lock|tsconfig|\.min\.)", p, re.I):
            continue
        out.append(p)
    out.sort(key=lambda p: (0 if re.search(r"(tvbox|box|jsm|js|config|api)", p, re.I) else 1, len(p)))
    return [(full_name, branch, p) for p in out[:8]]


def discover_gitee(max_repos):
    """第 5 路：发现 Gitee 上的 TVBox 配置仓库。

    【平台现实，实测结论】
      * Gitee 搜索 API 已被平台限制：任何账号、任何关键词都返回空 []（匿名与带 token 一致）；
      * 网页搜索被 WAF 直接 405 拦截；
      * 但「仓库详情 / 文件树」API 完全可用 —— 只要知道仓库全名就能展开。
    所以改为曲线方案：用 GitHub 代码搜索挖「配置里引用的 gitee.com 仓库全名」，
    再用 Gitee 文件树 API 展开这些仓库（需 GITHUB_TOKEN；GITEE_TOKEN 用于文件树配额）。
    """
    if not TOKEN:
        print("  [Gitee] 需要 GITHUB_TOKEN（从 GitHub 配置里挖 gitee 全名），跳过", flush=True)
        return set()
    if not _gitee_token():
        print("  [Gitee] 未设置 GITEE_TOKEN，展开仓库时走匿名配额（可能受限）", flush=True)
    repos = set()
    for q in GITEE_HUNT_QUERIES:
        doc = gh_api("/search/code", {"q": q, "per_page": 30})
        if not doc:
            print(f"  [Gitee挖取] {q[:44]} → 无结果/受限", flush=True)
            continue
        pulled = 0
        for item in doc.get("items", []):
            repo = item.get("repository") or {}
            fn, path = repo.get("full_name"), item.get("path")
            if not (fn and path):
                continue
            try:
                _, body = http_get(raw_url(fn, repo.get("default_branch") or "master", path),
                                   12, 200_000)
                pulled += 1
                text = body.decode("utf-8", "replace")
                for m in re.finditer(r"gitee\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text):
                    name = m.group(1).rstrip(".")
                    # 排除明显不是仓库的截断（如 .../raw/master.json 这类被误抓的路径段）
                    if name.lower().endswith((".json", ".js", ".m3u", ".txt", ".png", ".jpg")):
                        continue
                    repos.add(name)
            except Exception:
                continue
        print(f"  [Gitee挖取] {q[:44]} → 扫 {pulled} 个文件", flush=True)
        time.sleep(2)
    print(f"  [Gitee] 从 GitHub 配置中挖到 {len(repos)} 个 Gitee 仓库全名", flush=True)
    return set(list(repos)[:max_repos])


# ---------------- 第 6 路：搜索引擎 + 文章页（博客 / CSDN / 微信公众号）----------------
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
SEARCH_QUERIES = [
    "tvbox 接口 json",
    "影视仓 接口 地址 最新",
    "tvbox 配置 json 地址",
    "site:mp.weixin.qq.com tvbox 接口",
    "site:blog.csdn.net tvbox 接口",
]
PAGE_HOST_RE = re.compile(
    r"(mp\.weixin\.qq\.com|blog\.csdn\.net|cnblogs\.com|zhuanlan\.zhihu\.com|"
    r"juejin\.cn|segmentfault\.com|github\.io|wordpress\.com)", re.I)


def bing_search(q, per=12):
    """必应搜索（cn.bing.com 国内稳定）。返回结果里的文章页 URL。"""
    url = "https://cn.bing.com/search?" + urllib.parse.urlencode({"q": q, "count": per})
    req = urllib.request.Request(url, headers={
        "User-Agent": BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode("utf-8", "replace")
    out = []
    for m in URL_RE.finditer(html):
        u = m.group(0).rstrip(".,;")
        if re.search(r"(bing\.com|microsoft|msn\.com)", u, re.I):
            continue
        if PAGE_HOST_RE.search(u) or u.lower().endswith((".html", ".htm")):
            out.append(u)
    return list(dict.fromkeys(out))[:per]


def discover_web(max_pages=20):
    """第 6 路：搜索引擎找文章页（CSDN/博客园/知乎/**微信公众号**），从正文提取接口链接。

    微信的姿态（合规优先）：不调用微信私有 API、不登录、不碰搜狗微信验证页 ——
    只通过 Bing 的 site:mp.weixin.qq.com 发现**公开文章页**（浏览器可直接打开的那种），
    从正文提取作者主动公开的接口地址。抓取限并发 3、每页 400KB，失败即跳过。
    """
    pages = set()
    for q in SEARCH_QUERIES:
        try:
            found = bing_search(q)
            pages |= set(found)
            print(f"  [Web搜索] {q} → {len(found)} 个页面", flush=True)
        except Exception as e:  # noqa: BLE001  单路失败不影响其他路
            print(f"  [Web搜索] {q} → 失败 {str(e)[:40]}", flush=True)
        time.sleep(1)
    pages = [u for u in pages if PAGE_HOST_RE.search(u)][:max_pages]
    print(f"  [Web搜索] 待抓取文章页 {len(pages)} 个", flush=True)

    def grab(u):
        try:
            st, raw = http_get(u, 12, 400_000,
                               {"User-Agent": BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
            if st == 200:
                return URL_RE.findall(raw.decode("utf-8", "replace"))
        except Exception:
            pass
        return []

    urls = set()
    with cf.ThreadPoolExecutor(3) as ex:
        for links in ex.map(grab, pages):
            for l in links:
                l = l.rstrip(".,;")
                if re.search(r"\.(json|m3u|txt)(\?|$)", l, re.I) and not DROP_RE.search(l):
                    urls.add(l)
    print(f"  [Web搜索] 从文章正文提取 {len(urls)} 条接口候选", flush=True)
    return urls


def json_files_of(full_name):
    """列出一个仓库里值得探测的配置类文件。"""
    info = gh_api(f"/repos/{full_name}")
    if not info:
        return []
    branch = info.get("default_branch") or "main"
    tree = gh_api(f"/repos/{full_name}/git/trees/{branch}", {"recursive": "1"})
    if not tree:
        return []
    out = []
    for it in tree.get("tree", []):
        p = it.get("path") or ""
        if it.get("type") != "blob":
            continue
        if not p.lower().endswith((".json", ".m3u", ".txt")):
            continue
        if (it.get("size") or 0) < 500 or (it.get("size") or 0) > 12 * 1024 * 1024:
            continue
        if re.search(r"(node_modules|package-lock|tsconfig|\.min\.)", p, re.I):
            continue
        out.append(p)
    out.sort(key=lambda p: (0 if re.search(r"(tvbox|box|jsm|js|config|api)", p, re.I) else 1, len(p)))
    return [(full_name, branch, p) for p in out[:8]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-repos", type=int, default=20, help="每路最多展开的仓库数")
    ap.add_argument("--top", type=int, default=80, help="候选池上限")
    ap.add_argument("--no-code-search", action="store_true")
    ap.add_argument("--no-lineage", action="store_true", help="跳过第 4 路血统反查")
    ap.add_argument("--no-gitee", action="store_true", help="跳过第 5 路 Gitee 搜索")
    ap.add_argument("--no-web", action="store_true", help="跳过第 6 路搜索引擎+文章页")
    ap.add_argument("--max-pages", type=int, default=20, help="第 6 路最多抓取的文章页数")
    ap.add_argument("--pages", type=int, default=2, help="代码搜索翻页数（扩大召回）")
    ap.add_argument("--out", default="radar/discovered.json")
    ap.add_argument("--canary-out", default="state/extra_upstreams.json")
    ap.add_argument("--canary-score", type=int, default=80, help="进入 canary 的最低分")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    os.chdir(repo)
    known, known_repos = known_urls()
    print(f"[discover] 已知上游 {len(known)} 条 / 已知仓库 {len(known_repos)} 个", flush=True)

    repos = set()
    if not args.no_code_search:
        repos |= discover_code_search(args.max_repos, pages=args.pages)
    repos |= discover_repo_search(args.max_repos)
    if not args.no_lineage:
        repos |= discover_lineage(known_repos, args.max_repos)
    repo_urls = discover_seeds()
    # 第 2.5 路（2026-09-21 点播+容错线）：zhuiju 机器可读清单 + QingNing 结构化分节
    repo_urls |= discover_zhuiju()
    qn_warehouse, qn_live = discover_qingning()
    repo_urls |= qn_warehouse
    # 结构化解析出的直播类 URL 不进点播候选流；种子通用抽取若把 QingNing 的
    # .m3u/.live 直播链接吸了进来，在这里按解析结果做差集隔离
    repo_urls -= qn_live

    # 第 6 路：搜索引擎 + 文章页（博客/CSDN/微信公众号公开文章）
    if not args.no_web:
        repo_urls |= discover_web(args.max_pages)

    # 第 5 路 Gitee 单独展开（raw 地址构造方式与 GitHub 不同）
    if not args.no_gitee:
        g_repos = discover_gitee(args.max_repos)
        fresh_g = [r for r in g_repos if r and r not in known_repos]
        print(f"[discover] Gitee 待展开仓库 {len(fresh_g)} 个", flush=True)
        with cf.ThreadPoolExecutor(8) as ex:
            for files in ex.map(gitee_files_of, fresh_g[: args.max_repos]):
                for fn, br, p in files:
                    repo_urls.add(gitee_raw_url(fn, br, p))

    fresh_repos = [r for r in repos if r and r not in known_repos]
    print(f"[discover] 待展开仓库 {len(fresh_repos)} 个", flush=True)

    candidates = set(repo_urls)
    with cf.ThreadPoolExecutor(8) as ex:
        for files in ex.map(json_files_of, fresh_repos[: args.max_repos]):
            for fn, br, p in files:
                candidates.add(raw_url(fn, br, p))

    candidates = {u for u in candidates if u and u not in known}
    print(f"[discover] 候选 {len(candidates)} 条，开始 L0 探测 ...", flush=True)

    results = []
    with cf.ThreadPoolExecutor(16) as ex:
        for r in ex.map(probe_candidate, list(candidates)[: args.top * 3]):
            if r.get("reachable"):
                results.append(r)
    results.sort(key=lambda r: -r["score"])

    good = [r for r in results if r.get("kind") == "tvbox" and r["score"] >= 70]
    canary = [r for r in results if r["score"] >= args.canary_score and r.get("kind") == "tvbox"]

    # 2026-09-25 合并层成人泄漏治理：canary 由全网自动捞回，无人工审核必经，
    # 上游 URL 命中门禁同口径（PORN_KW/域名黑名单/源模式）即拒收——避免配置内容
    # 进 tvbox.json 触发合并扫除、接口元数据进 list.json 命中门禁。剔除明细入
    # 雷达报告供人工追溯，但 canary 列表永不收录此类源（修复点对点：曾吸入
    # jigedos/1024 仓作为 auto/15-46s 进 list.json [142]）。
    import live_aggregate as _la

    def _adult_rule_of(url: str):
        low = url.lower()
        for kw in _la.PORN_KW:
            if kw.lower() in low:
                return "porn_kw:%s" % kw[:16]
        if _la.is_adult_url(url):
            return "host_blacklist"
        m = _la.ADULT_SOURCE_RE.search(url)
        if m:
            return "source_pattern:%s" % m.group(0)[:24]
        return None

    canary_kept, canary_dropped = [], []
    for r in canary:
        rule = _adult_rule_of(r["url"])
        if rule:
            canary_dropped.append({"url": r["url"], "rule": rule, "score": r["score"]})
        else:
            canary_kept.append(r)
    canary = canary_kept
    if canary_dropped:
        print(f"[discover] canary 成人特征剔除 {len(canary_dropped)} 条：")
        for d in canary_dropped:
            print(f"    - {d['url']}  rule={d['rule']}", flush=True)

    doc = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "自动发现的上游候选；高分配置已同步进 state/extra_upstreams.json 作为 canary 自动拉取",
        "auth": "token" if TOKEN else "anonymous",
        "queries": {"code": CODE_QUERIES, "repo": REPO_QUERIES},
        "summary": {"candidates": len(candidates), "reachable": len(results),
                    "tvbox_configs": len(good), "canary": len(canary),
                    "canary_dropped_adult": len(canary_dropped)},
        "candidates": results[: args.top],
        "canary_dropped_adult": canary_dropped,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    # canary 名单：交给 fetch_merge.py 自动并入拉取，挂了会被自动黑名单兜住
    extra = []
    for i, r in enumerate(canary):
        extra.append({"name": f"auto/{i+1}-{r['evidence'].get('sites', 0)}s",
                      "kind": "tvbox", "url": r["url"], "auto": True,
                      "score": r["score"]})
    os.makedirs(os.path.dirname(args.canary_out) or ".", exist_ok=True)
    with open(args.canary_out, "w", encoding="utf-8") as f:
        json.dump({"generated_at": doc["generated_at"], "upstreams": extra}, f,
                  ensure_ascii=False, indent=1)

    print(f"[discover] 完成：可达 {len(results)}，真配置 {len(good)}，canary {len(extra)}")
    for r in results[:10]:
        ev = r.get("evidence", {})
        print(f"   {r['score']:3d}  {r.get('kind'):8} sites={ev.get('sites', '-'):<5} {r['url'][:88]}")
    print(f"[discover] 产物 -> {args.out} / {args.canary_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
