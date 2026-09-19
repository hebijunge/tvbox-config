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
  - 中文件 deps/qist/jsm/jar/spider.jar（~1.9MB）：吞吐速度（依赖下载体验）；
    该文件 404（未来路径变更）时自动退化为纯延迟排序。
"""

import concurrent.futures as cf
import json
import os
import time
import urllib.request

RAW_BASE = "https://raw.githubusercontent.com/hebijunge/tvbox-config/main"
TARGET_SMALL = RAW_BASE + "/stores/duocang.json"
TARGET_BIG = RAW_BASE + "/deps/qist/jsm/jar/spider.jar"

# 候选镜像（域名式前缀，支持 raw + release；顺序仅是初始值，实际以每日实测重排为准）。
# 候选池 2026-09-19 依据两份独立实测报告合并更新：
#   A《GitHub代理实测榜单》太原家宽 12.25MB git 包实测（极速/快速档）；
#   B《github-proxy-report》海外节点 91.5MB Release + sha256 实测（真可用/黑名单）。
# 两报告测试环境不同，速度绝对值不可直接对比，真假判定通用；实际顺序以本轮实测为准。
# 已剔除（报告B黑名单/实测失效）：gh.llkk.cc、ghp.ci、mirror.ghproxy.com、
#   ghproxy.homeboyc.cn、ghproxy.cn、ghproxy.link、mirror.houlang.cloud、down.npee.cn、
#   moeyy.cn/gh-proxy；ghproxy.net（B 实测截断 27KB/s、A 仅 97KB/s）；gh-proxy.net（无实测证据）。
CANDIDATES = [
    # —— 报告B 真可用/可用档（海外节点实测，sha256 三方一致）——
    "https://gh-proxy.com/",        # B 第一 20.5MB/s 三轮极稳；A 太原视角仅 145KB/s（环境差异）
    "https://ghfast.top/",          # B 第二 10MB/s
    "https://gh.xmly.dev/",         # B 第三 8.4MB/s
    "https://githubproxy.cc/",      # B 7.2MB/s；A 中速档 1740KB/s（双报告交叉可用）
    "https://ghproxy.cc/",          # B 7.3MB/s（慢启动）
    "https://gh.sixyin.com/",       # B 4.9MB/s；A 862KB/s
    "https://proxy.vvvv.ee/",       # B 6.3MB/s
    # —— 报告A 极速档 Top13（太原 ≥3MB/s）——
    "https://gh.xxooo.cf/",
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


def probe_big(prefix):
    """中文件吞吐实测，返回 (KB/s, is_fake)；失败返回 (0, False)。"""
    try:
        _ttfb, body, total = _fetch(prefix + TARGET_BIG, timeout=30)
        if len(body) < 100_000:
            return 0, False
        if not body.startswith(b"PK\x03\x04"):  # jar 即 zip 包，魔数 PK
            return 0, True
        return round(len(body) / 1024 / max(total, 0.01)), False
    except Exception:
        return 0, False


def probe_one(prefix):
    ttfb, fake_small = probe_small(prefix)
    if fake_small:
        return {"prefix": prefix, "ttfb_ms": None, "KBps": 0,
                "alive": False, "fake": True, "score_ok": False}
    kbps, fake_big = probe_big(prefix) if ttfb is not None else (0, False)
    return {"prefix": prefix, "ttfb_ms": ttfb, "KBps": kbps,
            "alive": ttfb is not None, "fake": fake_big,
            "score_ok": ttfb is not None and kbps > 0}


def main():
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(probe_one, CANDIDATES))

    # 排序：存活且大文件可测速的按速度降序 → 仅小文件存活的按延迟升序 → 不可达/假成功垫底
    ok_both = sorted([r for r in results if r["alive"] and r["KBps"] > 0],
                     key=lambda r: -r["KBps"])
    ok_small = sorted([r for r in results if r["alive"] and r["KBps"] == 0],
                      key=lambda r: r["ttfb_ms"])
    fake = [r for r in results if r["fake"]]
    dead = [r for r in results if not r["alive"] and not r["fake"]]
    ordered = ok_both + ok_small

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

    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "first": ordered[0]["prefix"].rstrip("/") if ordered else None,
        "alive": len(ok_both) + len(ok_small),
        "fake_success": [r["prefix"] for r in fake],
        "dead": [r["prefix"] for r in dead],
        "ranking": [{"prefix": r["prefix"].rstrip("/"), "ttfb_ms": r["ttfb_ms"],
                     "KBps": r["KBps"]} for r in ordered],
    }
    print("== 镜像实测排名 ==")
    for i, r in enumerate(ordered, 1):
        print(f"  {i}. {r['prefix'].rstrip('/')}  ttfb={r['ttfb_ms']}ms  {r['KBps']}KB/s")
    for r in fake:
        print(f"  x. {r['prefix'].rstrip('/')}  假成功（HTTP 200 但内容非目标文件，判 dead）")
    for r in dead:
        print(f"  x. {r['prefix'].rstrip('/')}  不可达")
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
