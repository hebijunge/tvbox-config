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


def inline_ext(cfg):
    """把 `./deps/x.json` 这类相对路径 ext 换成文件内容本身，返回 (新 cfg, 备注)。

    为什么必须换：宿主 app 在加载站点前会用 AssetManager 把相对路径读成规则文本再喂给 spider，
    app_process 复现不了这一步。直接把路径串交给 init，xBPQ/XYQHiker 这一类就把它当 JSON 解析，
    报 `JSONException: End of input`——那是工装没喂到位，不是站点死（824 假死事故的同一族）。
    本机真机对照：同样 8 个 G0 站，内联规则内容后 7 个变 G1（首页出结构）。

    备注里写清每段的结果（内联了多少字 / 文件缺失 / 超限），合并判级时能复盘证据链。
    """
    if not isinstance(cfg, str) or not cfg.strip():
        return cfg, ""
    parts, notes = [], []
    for seg in cfg.split("$$$"):
        head = seg.strip().split(";md5;")[0]
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


def build_jobs():
    rep = json.load(open(os.path.join(WORK, "csp_jar_scan.json"), encoding="utf-8"))
    present = {c: (v["jar"] or "").replace("\\", "/") for c, v in rep["classes"].items()}
    tiers = jar_tiers(rep)
    urls = jar_url_index()
    tv = json.load(open("tvbox.json", encoding="utf-8"))
    probe = json.load(open("probe/csp_probe.json", encoding="utf-8"))
    done = {s["key"]: s for s in probe["sites"] if s.get("level") not in (None, "C?")}
    jobs, skipped_guard, skipped_missing, seen = [], 0, 0, set()
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
        url = urls.get(jar) or bare(tv.get("spider") or "")
        cfg0 = cfg
        cfg, cfg_note = inline_ext(cfg)
        jobs.append({"id": key, "cls": cls, "jar": DEV_JAR + "/" + safe_name(jar),
                     "src": jar, "cfg": cfg, "url": url,
                     "cfg_ref": cfg0 if cfg != cfg0 else "", "cfg_note": cfg_note,
                     "tier": tiers.get(jar, "clean"), "name": (s.get("name") or "")[:24]})
    return jobs, skipped_guard, skipped_missing, len(done)


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
                 "app_process / Main2 /data/local/tmp/%s %s %s 2>&1 | tail -3"
                 % (host, f, outjson, PKG))
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
    """证据不足的判死：C0 只认静态口径（全池缺席 + 自带 jar 确实读到过）。

    v1 runner 的 CLASSPATH 里没挂宿主 apk，spider 接口找不到 → 整批 ClassNotFoundException
    → 802 个 C0 就这么进了产物（其中一半连 evidence 都是空的）。设备侧的 C0 同样只说明
    "我们这套工装没能把类跑起来"，判不起死。证据不足的判死一律退回未测，下一轮要么被真机
    跑实、要么由 csp_static_merge 重新判。
    """
    if row.get("level") != "C0":
        return False
    return not (row.get("evidence") or {}).get("static")


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
    else:
        out("用法: plan|push|run [块数]|merge")
