# -*- coding: utf-8 -*-
"""csp 爬虫类静态安检：扫本机全部可读 jar（deps/ 已下载的 + CSP_WORKDIR 里的），产出类存在性报告。

国内本机跑（CI 没有 SDK/dexdump，不在 CI 跑）。用法（cwd=仓库根）：
  py -3.12 scripts/csp_jar_scan.py
环境变量：
  DEXDUMP        android build-tools 里的 dexdump 可执行文件（缺失即 fail-fast，不出报告）
  CSP_WORKDIR    缓存/报告目录，默认 %LOCALAPPDATA%/Temp/csp-harness（仓库外）
  CSP_POOL_DIRS  jar 池根目录，os.pathsep 分隔，默认 deps 与 <CSP_WORKDIR>/cspjars

产物 <CSP_WORKDIR>/csp_jar_scan.json：
  {generated_at, pool:{files,dup_skipped,parsed,failed}, risk_jars:[...],
   classes:{类名:{present, jar}}, config_jars:[{url, error}]}
下一步 scripts/csp_static_merge.py 把「类在整池里都不存在」的高置信判定合进 probe/csp_probe.json。

口径说明：全池搜不到 = 与真机 C0 同语义（TVBox 加载必然失败）；池里搜到但没测过功能的
不写等级，留给真机工装。config 声明了自己的 jar 而那个 jar 下不动时**不能**拿别的 jar 的
缺席当证据，所以判定只看「类在池中的存在性」，下不动的 jar 记进 config_jars 供人看。
"""
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

MIN_JAR_BYTES = 20 * 1024
MAX_JAR_BYTES = 200 * 1024 * 1024
EXEC_SIGS = [b"Ljava/lang/Runtime;", b"ProcessBuilder", b"getRuntime",
             b"loadLibrary", b"/proc/self/maps"]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                                    # 复用 fetch_merge 的下载通道
WORK = os.environ.get("CSP_WORKDIR") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Temp", "csp-harness")
REPORT = os.path.join(WORK, "csp_jar_scan.json")
POOL_DIRS = (os.environ.get("CSP_POOL_DIRS") or
             os.pathsep.join(["deps", os.path.join(WORK, "cspjars")])).split(os.pathsep)


def out(msg):
    print(msg, flush=True)


def dexdump_path():
    p = os.environ.get("DEXDUMP") or shutil.which("dexdump")
    if p:
        return p if os.path.exists(p) else None      # 显式给了路径却不存在：停下来问人，别静默出空池
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    for sub in ("build-tools",):
        base = os.path.join(sdk or "", sub)
        if not os.path.isdir(base):
            continue
        for v in sorted(os.listdir(base), reverse=True):
            for name in ("dexdump.exe", "dexdump"):
                cand = os.path.join(base, v, name)
                if os.path.exists(cand):
                    return cand
    return None


def jar_candidates():
    """池内候选文件：按 (大小, sha1) 去重——同一个 pg.jar 在 deps 里能躺十几份。"""
    by_size = {}
    for root in POOL_DIRS:
        if not os.path.isdir(root):
            continue
        for dirpath, _, names in os.walk(root):
            for fn in names:
                p = os.path.join(dirpath, fn)
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    continue
                if MIN_JAR_BYTES <= sz <= MAX_JAR_BYTES:
                    by_size.setdefault(sz, []).append(p)
    files, dropped = [], 0
    for sz, paths in sorted(by_size.items()):
        if len(paths) == 1:
            files.append(paths[0])
            continue
        seen = set()
        for p in paths:
            with open(p, "rb") as f:
                digest = hashlib.sha1(f.read()).hexdigest()
            if digest in seen:
                dropped += 1
                continue
            seen.add(digest)
            files.append(p)
    return files, dropped


def dex_classes(dexdump, path, tmp):
    """返回 {classes, execs, native}；解不动返回 {"err": 原因}——绝不返回空 classes。

    空 classes 会被下游读成「这些类都不存在」，一路把整批站判死。
    """
    try:
        z = zipfile.ZipFile(path)
        names = z.namelist()
        dexes = {n: z.read(n) for n in names if n.endswith(".dex")}
        native = [n for n in names if n.startswith("assets/") and
                  (n.endswith(".so") or "guard" in n.lower())]
    except Exception as e:
        return {"err": "zip:" + str(e)[:100]}
    if not dexes:
        return {"err": "no-dex-entry"}
    classes, execs, parsed = set(), set(), 0
    for n, raw in dexes.items():
        for sig in EXEC_SIGS:
            if sig in raw:
                execs.add(sig.decode())
        try:
            with open(tmp, "wb") as f:
                f.write(raw)
            r = subprocess.run([dexdump, "-f", tmp], capture_output=True, timeout=180)
            txt = r.stdout.decode("utf-8", "replace")
        except Exception:
            continue
        if r.returncode != 0 or "Class descriptor" not in txt:
            continue
        classes.update(m.group(1).split("/")[-1]
                       for m in re.finditer(r"Class descriptor\s+:\s+'L([^']+);'", txt))
        parsed += 1
    if parsed == 0:
        return {"err": "dexdump-parsed-nothing"}
    if native:
        execs.add("native-assets")
    return {"classes": classes, "execs": execs, "native": native}


def config_csp_classes(path="tvbox.json"):
    tv = json.load(open(path, encoding="utf-8"))
    wanted = set()
    for s in tv.get("sites", []):
        api = str(s.get("api") or "")
        if api.startswith("csp_"):
            wanted.add(api[4:])
    return wanted, tv


def main():
    if getattr(sys.stdout, "encoding", "").lower().replace("-", "") not in ("utf8", "utf-8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dexdump = dexdump_path()
    if not dexdump:
        out("缺 dexdump：设 DEXDUMP 指向 android build-tools/dexdump(.exe)，或设 ANDROID_HOME。"
            "本次不产出 csp_jar_scan.json（不覆写上一轮好数据）。")
        return 2
    os.makedirs(WORK, exist_ok=True)
    cands, dup_skipped = jar_candidates()
    out(f"jar 池候选 {len(cands)} 个（内容去重跳过 {dup_skipped}），池目录 {POOL_DIRS}")
    wanted, tv = config_csp_classes()
    classes, risk_jars, failed, parsed_files = {}, [], [], []
    parsed = 0
    t0 = time.time()

    def one(p):
        fd, t = tempfile.mkstemp(suffix=".dex", dir=WORK)
        os.close(fd)
        try:
            return p, dex_classes(dexdump, p, t)
        finally:
            try:
                os.remove(t)
            except OSError:
                pass

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, (p, res) in enumerate(ex.map(one, cands), 1):
            if res.get("err"):
                failed.append({"file": p, "err": res["err"]})
            else:
                parsed += 1
                parsed_files.append(p)
                for c in res["classes"]:
                    if c in wanted and c not in classes:
                        classes[c] = p
                if res["execs"]:
                    risk_jars.append({"file": p, "signs": sorted(res["execs"])})
            if i % 25 == 0 or i == len(cands):
                out(f"[{i}/{len(cands)}] 解析成功 {parsed} 类命中 {len(classes)}/{len(wanted)} "
                    f"用时 {int(time.time() - t0)}s")
    if parsed < 10:
        out(f"只解析成功 {parsed}/{len(cands)} 个 jar，池子不可信，不写报告。")
        return 3
    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "pool": {"files": len(cands), "dup_skipped": dup_skipped, "parsed": parsed, "failed": len(failed),
                       "dexdump": dexdump, "roots": POOL_DIRS},
              "wanted": len(wanted),
              "pool_files": [os.path.relpath(p, os.getcwd()).replace("\\", "/")
                             for p in sorted(parsed_files)],
              "classes": {c: {"present": True, "jar": os.path.relpath(j, os.getcwd()).replace("\\", "/")}
                          for c, j in classes.items()},
              "absent": sorted(c for c in wanted if c not in classes),
              "risk_jars": risk_jars[:400], "jar_failures": failed[:400]}
    json.dump(report, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out(f"池：{parsed}/{len(cands)} 个 jar 解析成功；配置里 {len(wanted)} 个 csp 类中"
        f"在池内可寻址 {len(classes)}、全无 {len(report['absent'])} → {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
