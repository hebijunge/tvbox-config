"""csp 真机五关批量驱动（本机国内网络 + root 测试机）。

流程：读 tvbox.json + 全池扫描报告 → 挑「类在非加固 jar 里可寻址、但 probe 里没结论」的站
     → 把需要的 jar 推到设备 → 分块跑 Main2（每块 adb 调用控制在几分钟内，可反复续跑）
     → 拉回 jsonl → 合并进 probe/csp_probe.json。

用法：
  py -3.12 csp_device_batch.py plan              只看计划与分块数
  py -3.12 csp_device_batch.py push              推 jar 与 jobs
  py -3.12 csp_device_batch.py run [块数]         跑前 N 块（默认 1）
  py -3.12 csp_device_batch.py merge              拉结果并合并进 probe
环境变量：CSP_WORKDIR（默认 %LOCALAPPDATA%/Temp/csp-harness）、TVBOX_APK（设备侧宿主 apk 路径）
"""
import collections
import json
import os
import re
import subprocess
import sys
import urllib.parse

WORK = os.environ.get("CSP_WORKDIR") or os.path.join(
    os.environ.get("TEMP", "/tmp"), "csp-harness")
REPO = os.getcwd()      # cwd=仓库根：plan|push|run|merge
DEV_JAR = "/data/local/tmp/cspjars"
CHUNK = 40
CALL_MS = os.environ.get("CSP_CALL_MS", "20000")   # 单关调用上限(ms)；慢站复测可临时调大
PKG = "com.tvtest"          # 宿主包名：提供 catvod 接口与 Context
HOST_APK = os.environ.get("TVBOX_APK") or ""


def out(msg):
    sys.stdout.buffer.write((str(msg) + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()


def sh(cmd, shell=False):
    r = subprocess.run(cmd, capture_output=True, shell=shell)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def adb(args):
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run(["adb", "shell"] + args, capture_output=True, env=env)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def safe_name(url):
    return re.sub(r"\W+", "_", url)[-70:]


def bare(u):
    m = re.search(r"(https?://raw\.githubusercontent\.com/\S+?)(;md5;.*)?$", u or "")
    if m:
        return m.group(1)
    p = re.sub(r";md5.*", "", u or "")
    i = p.find("raw.githubusercontent.com")
    return ("https://" + p[i:]) if i >= 0 else p


def jar_url_index(manifest="deps/manifest.json"):
    """本地 jar 路径 -> 它当初的下载地址。代理 stub 壳的解密链只认原始 url。"""
    idx = {}
    if os.path.exists(manifest):
        for v in json.load(open(manifest, encoding="utf-8")).values():
            if isinstance(v, dict) and v.get("local") and v.get("url"):
                idx.setdefault(v["local"].replace("\\", "/"), v["url"])
    return idx


def jar_tiers(rep):
    """jar -> native / exec-only。只有 native（自载 .so）才该排除：那类要在设备上跑原生代码。"""
    tiers = {}
    for r in rep.get("risk_jars", []):
        f = (r.get("file") or "").replace("\\", "/")
        tiers[f] = "native" if "native-assets" in (r.get("signs") or []) else "exec-only"
    return tiers


MAX_INLINE = 200_000          # 单条规则文件内联上限；再大的进 jobs.json 会把块撑爆
REMOTE_TIMEOUT = 10           # 远程 ext 单个候选的取数上限
LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "::1")


def is_rule(text):
    """返回体像规则（JSON / maccms XML 模板）才值得内联；HTML 报错页不算。"""
    t = (text or "").lstrip("﻿ \t\r\n")
    if not t:
        return False
    if t[0] in "{[":
        return True
    low = t[:400].lower()
    if "<html" in low or "<!doctype html" in low:
        return False
    return low.startswith("<?xml") or "<class" in low or "dd\"" in low


def remote_exts(cfg):
    """cfg 里需要联网取的远程 ext 段（本机/内网端点排除：那是设备侧服务）。

    逗号也切：不少 csp 站的 ext 是 `https://a,https://b,https://c` 形式的**备用域名列表**，
    spider 会挨个试。只取第一个就判死 = 假死（wencai 就是这么被误判的：首域已撤，
    后面两个域还活着）。
    """
    got = []
    for seg in str(cfg or "").split("$$$"):
        for head in seg.strip().split(";md5;")[0].split(","):
            head = head.strip()
            if not head.startswith(("http://", "https://")):
                continue
            try:
                host = urllib.parse.urlparse(head).hostname or ""
            except ValueError:
                continue
            if host in LOCAL_HOSTS or host.startswith("192.168.") or host.startswith("10."):
                continue
            got.append(head)
    return got


RULE_SUFFIX = (".json", ".txt", ".xml", ".js")


def classify_miss(url, status=None, text=""):
    """远程 ext 取不到时，只有「规则文件本身不在了」才构成已亡。

    为什么必须有这条：xyq/xp 系里大量站的 ext 就是**站点根 URL**（spider 自己抓首页解析），
    返回整页 HTML 是正常形态。把它当「规则亡了」就是自己造假死——上一版就这么误判了
    31 个站（www.mutefun.tv 返回 165KB 正常页面、www.czzy.site 是活的门户）。
    域名解析不了（DoH 复核过）不受此限：站点自己都不存在了。
    """
    is_file = urllib.parse.urlparse(url).path.lower().endswith(RULE_SUFFIX)
    if not is_file:
        return ""
    if status in (404, 410):
        return "gone-%s" % status
    low = (text or "")[:300].lower()
    if "<html" in low or "<!doctype" in low:
        return "lander-html"
    return ""


def prefetch_remote(urls, workers=8):
    """在国内把这些远程 ext 各取一次 → (fetched, dead)。

    fetched: {url: 规则文本 或 None}   None=取过但没拿到规则形态
    dead:    {url: 死因}               只对「结构性已亡」下结论（见下）

    为什么在本机取：xyq/xbpq 系 spider 在 init 里自己联网拉规则，而设备网络与本机不同，
    拉不到就 homeContent 静默返回空串——采样 60 个「静默 G0」，57 个是空串，其中 44 个的
    ext 就是远程规则 URL。不取回来内联，就是把工装没喂到位记成站点能力。

    死因门槛（与 probe_endpoints 同一口径）：
      * 域名解析失败必须过 DoH 复核（阿里+Google 都 NOERROR 且无答案）——只凭本机一台
        解析器判死，就是 2026-09-29「本地网络误杀 adult.json 104 站」的同款事故；
      * 404/410/返回 HTML 壳 = 规则文件确实不在这地址上了；
      * 超时/连接重置/TLS = 环境性，不下结论（留未测）。
    """
    urls = list(dict.fromkeys([u for u in (urls or []) if remote_exts(u)]))
    if not urls:
        return {}, {}
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    try:
        from probe_endpoints import doh_cached
        from probe_sites import gh_retry_candidates, http_get
    except ImportError as e:
        out("缺 scripts/probe_sites.py 或 probe_endpoints.py，远程 ext 不内联（%s）" % e)
        return {}, {}

    def one(u):
        host = urllib.parse.urlparse(u).hostname or ""
        why = []
        for cand in [u] + list(gh_retry_candidates(u))[:3]:
            try:
                st, body, _ms, _ct = http_get(cand, REMOTE_TIMEOUT, MAX_INLINE)
            except Exception as e:
                msg = str(e)
                if "getaddrinfo" in msg or "11001" in msg:
                    verdict, detail = doh_cached(host, REMOTE_TIMEOUT)
                    if verdict is False:
                        return None, "域名无解析记录(DoH一致:%s)" % detail[:60]
                    why.append("DNS未确认")        # 本机解析失败但 DoH 说还在：环境性
                elif "timed out" in msg or "10054" in msg:
                    why.append("env")
                else:
                    why.append(type(e).__name__)
                continue
            text = body.decode("utf-8", "replace") if st == 200 and body else ""
            if st == 200 and is_rule(text) and 20 < len(text) < MAX_INLINE:
                return text, ""
            why.append(classify_miss(cand, st, text) or "env")
        w = ";".join(why)
        if "gone-" in w or "lander-html" in w:
            return None, w[:60]
        return None, ""                          # 环境性/未确认：不判

    fetched, dead = {}, {}
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for u, (text, why) in zip(urls, ex.map(one, urls)):
            fetched[u] = text
            if why:
                dead[u] = why
    out("远程 ext %d 个：可内联 %d，确认已亡 %d" % (len(urls), sum(1 for v in fetched.values() if v), len(dead)))
    return fetched, dead


def inline_ext(cfg, fetched=None):
    """把 `./deps/x.json` 这类相对路径 ext 换成文件内容本身，返回 (新 cfg, 备注)。

    为什么必须换：宿主 app 在加载站点前会用 AssetManager 把相对路径读成规则文本再喂给 spider，
    app_process 复现不了这一步。直接把路径串交给 init，xBPQ/XYQHiker 这一类就把它当 JSON 解析，
    报 `JSONException: End of input`——那是工装没喂到位，不是站点死（824 假死事故的同一族）。
    本机真机对照：同样 8 个 G0 站，内联规则内容后 7 个变 G1（首页出结构）。

    远程 ext 走 fetched（prefetch_remote 的结果）：不在这里发网络请求，保证本函数可测、
    也保证 plan/push 重复调用不会重复打网络。

    备注里写清每段的结果（内联了多少字 / 文件缺失 / 超限），合并判级时能复盘证据链。
    """
    if not isinstance(cfg, str) or not cfg.strip():
        return cfg, ""
    fetched = fetched or {}
    parts, notes = [], []
    for seg in cfg.split("$$$"):
        head = seg.strip().split(";md5;")[0]
        if head.startswith(("http://", "https://")):
            if "," in head:
                parts.append(seg)          # 备用域列表：spider 自己挨个试，改写反而破坏语义
                notes.append("未内联(备用域列表)")
            elif not fetched:
                parts.append(seg)
                notes.append("未内联(远程未取数)")
            elif head in fetched and fetched[head]:
                parts.append(fetched[head])
                notes.append("内联远程(%s:%d字)" % (head[:40], len(fetched[head])))
            elif head in fetched:
                parts.append(seg)
                notes.append("未内联(远程取不到:%s)" % head[:40])
            else:
                parts.append(seg)          # 设备侧服务（127.0.0.1 的 token 文件等）
                notes.append("未内联(本机端点)")
            continue
        if not head.startswith(("./", "assets://")):
            parts.append(seg)
            continue
        rel = urllib.parse.unquote(head[2:] if head.startswith("./") else head[len("assets://"):])
        try:
            with open(rel, "rb") as fh:
                raw = fh.read()
        except OSError as e:
            parts.append(seg)
            notes.append("未内联(%s:%s)" % (head, type(e).__name__))
            continue
        if not (20 < len(raw) < MAX_INLINE):
            parts.append(seg)
            notes.append("未内联(%s:大小%s)" % (head, len(raw)))
            continue
        parts.append(raw.decode("utf-8", "replace"))
        notes.append("内联(%s:%d字)" % (head, len(raw)))
    return "$$$".join(parts), ";".join(notes)


def build_jobs(prefetch=True):
    rep = json.load(open(os.path.join(WORK, "csp_jar_scan.json"), encoding="utf-8"))
    present = {c: (v["jar"] or "").replace("\\", "/") for c, v in rep["classes"].items()}
    tiers = jar_tiers(rep)
    urls = jar_url_index()
    tv = json.load(open("tvbox.json", encoding="utf-8"))
    probe = json.load(open("probe/csp_probe.json", encoding="utf-8"))
    done = {s["key"]: s for s in probe["sites"] if s.get("level") not in (None, "C?")}
    cand, skipped_guard, skipped_missing, seen = [], 0, 0, set()
    for s in tv.get("sites", []):
        api = str(s.get("api") or "")
        if not api.startswith("csp_"):
            continue
        cls = api[4:]
        key = s.get("key") or s.get("name")
        if key in done or key in seen:
            continue
        jar = present.get(cls)
        if not jar:
            continue
        if tiers.get(jar) == "native":
            skipped_guard += 1          # 自载 .so 的壳：不在设备上执行原生代码
            continue
        if not os.path.exists(jar):
            # 扫描报告里说类在池里，但当前 deps/ 里文件没了：push 推不上设备，
            # 白占槽位还跑不出结论（CNFE→C0→被 merge 当 load 丢弃）。诚实处理：
            # 本地没这个 jar = 判不了，直接跳过，等重拉后下一轮再测。
            skipped_missing += 1
            continue
        seen.add(key)
        ext = s.get("ext")
        cfg = ext if isinstance(ext, str) else (json.dumps(ext, ensure_ascii=False)
                                                if isinstance(ext, dict) else "")
        cand.append((key, cls, jar, cfg, urls.get(jar) or bare(tv.get("spider") or ""),
                     (s.get("name") or "")[:24]))
    # 远程 ext 一次并发取回（~416 个 URL，串行取会把 plan 拖成十几分钟）
    fetched, dead = ({}, {})
    if prefetch:
        need = []
        for _, _, _, cfg, _, _ in cand:
            need.extend(remote_exts(cfg))
        fetched, dead = prefetch_remote(need)
        json.dump(dead, open(os.path.join(WORK, "ext_dead.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    jobs = []
    for key, cls, jar, cfg0, url, name in cand:
        cfg, cfg_note = inline_ext(cfg0, fetched)
        jobs.append({"id": key, "cls": cls, "jar": DEV_JAR + "/" + safe_name(jar),
                     "src": jar, "cfg": cfg, "url": url,
                     "cfg_ref": cfg0 if cfg != cfg0 else "", "cfg_note": cfg_note,
                     "tier": tiers.get(jar, "clean"), "name": name})
    return jobs, skipped_guard, skipped_missing, len(done)


def apply_ext_dead(sites_by_key, pending, dead, now):
    """把「配置依赖确认已亡」的站写成 C0（证据 ext_dep），返回条数。

    只动没有结论的站：真机跑实过（C1-C5）说明它并不依赖这个 ext（或 ext 只是可选参数），
    不能因为 URL 死了就降级——与 csp_static_merge「真机结论冲突不降级」同一条规矩。
    pending: [(key, name, cls, [ext_url, ...])]；dead: {url: 死因}（prefetch_remote 已把
    环境性失败剔在外面，进这里的都是域名无记录(DoH 一致)/规则文件 404/规则变 HTML 壳）。
    多域名 ext 要**全部**候选都确认亡才判死：spider 自己会挨个试备用域。
    """
    n = 0
    for key, name, cls, urls in pending:
        urls = list(urls)
        causes = [dead.get(u) for u in urls]
        why = ";".join([c for c in causes if c])
        has_verdict = key in sites_by_key and sites_by_key[key].get("level") not in (None, "C?")
        if not urls or len(causes) != len([c for c in causes if c]) or has_verdict:
            continue
        sites_by_key[key] = {"key": key, "name": name[:24], "kind": "csp", "cls": cls,
                             "level": "C0", "ms": None,
                             "flags": {"home": False, "cat": False, "search": False},
                             "evidence": {"ext_dep": "remote-rule-unreachable",
                                          "cause": why[:120], "url": urls[0][:120],
                                          "tried": len(urls)},
                             "err": "ext-dead:" + why[:80], "probed_at": now}
        n += 1
    return n


def cmd_ext():
    """5h：csp 站的远程 ext（规则/接口）在国内到底取不取到——取不到就是配置层面已亡。

    为什么单独一路：真机侧这类站一律 homeContent 返回空串（spider 自己吞了拉规则的失败），
    工装既不能据此判死也不该永远挂着未测；而 ext URL 可达性是能在国内直接证伪的。
    实测 416 个远程 ext 里只有 3 个还能取回规则形态，250 个域名解析不了。
    """
    tv = json.load(open("tvbox.json", encoding="utf-8"))
    probe = json.load(open("probe/csp_probe.json", encoding="utf-8"))
    by_key = {s["key"]: s for s in probe["sites"]}
    pending, seen = [], set()
    for s in tv.get("sites", []):
        api = str(s.get("api") or "")
        if not api.startswith("csp_"):
            continue
        key = s.get("key") or s.get("name")
        if not key or key in seen:
            continue
        seen.add(key)
        if by_key.get(key, {}).get("level") not in (None, "C?"):
            continue
        urls = remote_exts(s.get("ext") if isinstance(s.get("ext"), str)
                           else json.dumps(s.get("ext") or "", ensure_ascii=False))
        if urls:
            pending.append((key, (s.get("name") or "")[:24], api[4:], urls))
    need = [u for _, _, _, us in pending for u in us]
    _f, dead = prefetch_remote(need)
    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")
    n = apply_ext_dead(by_key, pending, dead, now)
    probe["sites"] = list(by_key.values())
    probe["generated_at"] = now
    lv = collections.Counter(x.get("level") for x in probe["sites"])
    probe["summary"] = dict(probe.get("summary") or {}, total=len(probe["sites"]), levels=dict(lv),
                            ext_dead_added=n)
    json.dump(probe, open("probe/csp_probe.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    out("远程 ext 待判 %d 站，确认已亡 %d，写入 C0 %d 条；csp_probe 总 %d，分布 %s"
        % (len(pending), len(dead), n, len(probe["sites"]), dict(lv)))


def cmd_plan():
    jobs, guard, missing, done = build_jobs()
    jars = sorted(set(j["src"] for j in jobs))
    tiers = collections.Counter(j["tier"] for j in jobs)
    out("已有结论 %d；native 壳跳过 %d；本地缺 jar 跳过 %d；本轮可测站 %d（clean %d / exec-only 壳 %d），"
        "涉及 jar %d 个，分块 %d" % (done, guard, missing, len(jobs), tiers["clean"],
                                    tiers["exec-only"], len(jars),
                                    (len(jobs) + CHUNK - 1) // CHUNK))
    json.dump(jobs, open(os.path.join(WORK, "device_jobs.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    for j in jars[:8]:
        out("   jar: " + j)


def cmd_push():
    jobs, *_ = build_jobs()
    jars = sorted(set(j["src"] for j in jobs))
    adb(["mkdir", "-p", DEV_JAR])
    pushed = miss = 0
    for src in jars:
        if not os.path.exists(src):
            miss += 1
            continue
        dest = DEV_JAR + "/" + safe_name(src)
        rc, _ = adb(["test", "-f", dest])
        if rc == 0:
            pushed += 1
            continue
        rc, o = sh(["adb", "push", src, dest])
        pushed += 1 if rc == 0 else 0
    out("jar 推送完成 %d/%d（本地缺文件 %d）" % (pushed, len(jars), miss))
    # jobs 分块推
    for i in range(0, len(jobs), CHUNK):
        part = jobs[i:i + CHUNK]
        p = os.path.join(WORK, "jobs_%03d.json" % (i // CHUNK))
        json.dump(part, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        sh(["adb", "push", p, "/data/local/tmp/" + os.path.basename(p)])
    out("jobs 分块推送 %d 块" % ((len(jobs) + CHUNK - 1) // CHUNK))


def cmd_run(nblocks):
    rc, o = adb(["ls", "/data/local/tmp/"])
    listed = re.split(r"\s+", o)
    files = [f for f in listed if f.startswith("jobs_")]
    # 续跑：已经出过结果的块（done_*）跳过，被超时打断后重跑不重复花钱
    finished = {f.replace("done_", "jobs_").replace(".jsonl", ".json") for f in listed
                if f.startswith("done_")}
    pending = [f for f in sorted(files) if f not in finished]
    out("跳过已完成 %d 块，剩 %d 块" % (len(files) - len(pending), len(pending)))
    blocks = pending[:nblocks]
    host = HOST_APK
    if not host:
        rc2, o2 = adb(["pm path com.tvtest"])
        host = next((l.split(":", 1)[1].strip() for l in o2.splitlines()
                     if l.startswith("package:")), "")
    out("宿主 apk=%s；本轮跑 %d 块" % (host[:60], len(blocks)))
    for f in blocks:
        idx = f.replace("jobs_", "").replace(".json", "")
        outjson = "/data/local/tmp/res_%s.jsonl" % idx
        inner = ("cd /data/local/tmp; CLASSPATH=/data/local/tmp/runner2.jar:%s "
                 "app_process / Main2 /data/local/tmp/%s %s %s %s 2>&1 | tail -3"
                 % (host, f, outjson, PKG, CALL_MS))
        rc, o = adb(["su", "-c", inner])
        out("[%s] rc=%s %s" % (idx, rc, o.strip().replace("\n", " | ")[:220]))
        adb(["mv", "-f", outjson, "/data/local/tmp/done_%s.jsonl" % idx])


def device_verdict(row, cls):
    """→ (可写入的等级 或 None, 不收的原因)。

    真机只证明「能跑到第几关」：
      * stub（Amns/Guard 这类转发壳）真身在宿主运行时里解密，app_process 复现不了注入链；
      * 类没加载起来（C0）区分不了「真没这个类」和「我们的 DexClassLoader 用不了它」
        ——能进 jobs 的类都是全池扫描说找得到的；
      * 装上但一关没过（G0）多半是 ext/依赖没喂到位，留给下一轮。
    三者都不构成站点判定；判死留给静态口径（csp_static_merge：全池缺席 + 自带 jar 读到过）。
    """
    if cls.endswith("Amns") or "Guard" in cls:
        return None, "stub"
    lvl = row.get("level")
    if lvl == "C0":
        return None, "load"
    if lvl and lvl.startswith("G"):
        gates = int(row.get("gates") or 0)
        return ("C%d" % gates, "") if gates >= 1 else (None, "g0")
    return (lvl or "C?"), ""


def untrusted_c0(row):
    """证据不足的判死：C0 只认两类结构化证据。

    * `static`：csp_static_merge——类在全池可读 jar 里都不存在，且该站自带 jar 确实读到过；
    * `ext_dep`：5h——远程规则/接口在国内确认已亡（域名无记录过 DoH 复核、404、HTML 壳）。

    v1 runner 的 CLASSPATH 里没挂宿主 apk，spider 接口找不到 → 整批 ClassNotFoundException
    写成 C0，802 个假死就这么进了产物（一半连 evidence 都是空的）。设备侧的 C0 同样只说明
    "我们这套工装没能把类跑起来"，判不起死。证据不足的判死一律退回未测，下一轮要么被真机
    跑实、要么由 csp_static_merge 重新判。
    """
    if row.get("level") != "C0":
        return False
    ev = row.get("evidence") or {}
    return not (ev.get("static") or ev.get("ext_dep"))


def cmd_merge():
    rc, o = adb(["ls", "/data/local/tmp/"])
    parts = sorted(f for f in re.split(r"\s+", o) if f.startswith("done_"))
    jmap = {}
    jp = os.path.join(WORK, "device_jobs.json")
    if os.path.exists(jp):
        for j in json.load(open(jp, encoding="utf-8")):
            jmap[j["id"]] = j
    rows = []
    for p in parts:
        lp = os.path.join(WORK, p)
        sh(["adb", "pull", "/data/local/tmp/" + p, lp])
        if not os.path.exists(lp):
            continue
        for line in open(lp, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line.startswith("{"):
                rows.append(json.loads(line))
    probe = json.load(open("probe/csp_probe.json", encoding="utf-8"))
    kept = [s for s in probe["sites"] if not untrusted_c0(s)]
    purged = len(probe["sites"]) - len(kept)
    by_key = {s["key"]: s for s in kept}
    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")
    upd = 0
    skipped = collections.Counter()
    for r in rows:
        key = r.get("id")
        if not key:
            continue
        job = jmap.get(key) or {}
        cls = job.get("cls") or ""
        r.setdefault("cls", cls)
        r.setdefault("name", job.get("name", key))
        lvl, skip = device_verdict(r, cls)
        if lvl is None:
            skipped[skip] += 1
            continue
        gates = int(r.get("gates") or 0)
        by_key[key] = {"key": key, "name": r.get("name", "")[:24], "kind": "csp",
                       "cls": (r.get("cls") or ""), "level": lvl,
                       "ms": r.get("ms"),
                       "flags": {"home": bool(r.get("home")), "cat": bool(r.get("cat")),
                                 "search": bool(r.get("search"))},
                       "evidence": {"device": "app-process-five-gate",
                                    "detail": bool(r.get("detail")), "play": bool(r.get("play")),
                                    "catCount": r.get("catCount"), "searchHit": r.get("searchHit"),
                                    # ext 是相对路径的站，喂进去的是内联后的规则内容；留出处供复盘
                                    "cfg_ref": (job.get("cfg_ref") or "")[:96],
                                    "cfg_note": (job.get("cfg_note") or "")[:96],
                                    "gates": gates},
                       "err": (r.get("err") or "")[:240], "probed_at": now}
        upd += 1
    probe["sites"] = list(by_key.values())
    probe["generated_at"] = now
    from collections import Counter
    lv = Counter(x.get("level") for x in probe["sites"])
    probe["summary"] = dict(probe.get("summary") or {}, total=len(probe["sites"]), levels=dict(lv),
                            purged_untrusted_c0=purged,
                            note="真机只证明「能跑到第几关」（C1-C5）；判死 C0 一律出自静态口径"
                                 "（全池类缺席 + 该站自带 jar 确实读到过）。2026-10-01 起 "
                                 "app_process runner 挂宿主 apk，CLASSPATH 齐全")
    json.dump(probe, open("probe/csp_probe.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    out("合并 %d 条；不收 stub %d / 类没加载起来 %d / 零关通过 %d；"
        "清掉无证据旧 C0 %d；csp_probe 总 %d，分布 %s" % (
            upd, skipped["stub"], skipped["load"], skipped["g0"], purged,
            len(probe["sites"]), dict(lv)))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if cmd == "plan":
        cmd_plan()
    elif cmd == "push":
        cmd_push()
    elif cmd == "run":
        cmd_run(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    elif cmd == "merge":
        cmd_merge()
    elif cmd == "ext":
        cmd_ext()
    else:
        out("用法: plan|push|run [块数]|merge|ext")
