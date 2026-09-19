"""每日构建前的 GitHub 镜像复测：实测候选镜像的延迟与下载速度，动态重排 GH_MIRRORS。

背景：公共镜像寿命短（6-18 个月）、速度随时间漂移。产出配置的内部引用与入口线路
统一使用 GH_MIRRORS[0]（GHPROXY），因此每次构建前用本项目真实文件实测一轮，
把存活且最快的镜像排到首位。用户设备无法直连 raw.githubusercontent.com（2026-09-19 确认）。

用法：python scripts/mirror_probe.py
  - 检测到 GITHUB_ENV 环境变量时，把重排后的顺序写入 GH_MIRRORS（fetch_merge.py 自动读取）；
  - 全部候选不可达时不写环境变量，fetch_merge.py 回退内置默认顺序；
  - 任何异常都不抛出（exit 0），探测失败不阻塞每日构建。

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

# 候选镜像（域名式前缀，支持 raw + release；顺序仅是初始值，实际以实测为准）
CANDIDATES = [
    "https://gh-proxy.com/",
    "https://gh.zwy.one/",
    "https://ghproxy.cxkpro.top/",
    "https://v6.gh-proxy.org/",
    "https://ghproxy.net/",
    "https://ghfast.top/",
    "https://gh.llkk.cc/",
    "https://raw.ihtw.moe/",
    "https://ghp.ci/",
    "https://mirror.ghproxy.com/",
    "https://gh-proxy.net/",
    "https://ghproxy.homeboyc.cn/",
]

UA = {"User-Agent": "tvbox-config-mirror-probe"}


def _fetch(url, timeout):
    t0 = time.time()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ttfb = time.time() - t0
        n = len(r.read())
    return ttfb, n, time.time() - t0


def probe_small(prefix):
    """小文件两连测，取最好成绩；两次都失败判不可达。"""
    best = None
    for _ in range(2):
        try:
            ttfb, n, total = _fetch(prefix + TARGET_SMALL, timeout=12)
            if n > 0:
                best = round(ttfb * 1000)
                break
        except Exception:
            continue
    return best


def probe_big(prefix):
    """中文件吞吐实测，返回 KB/s；失败返回 0。"""
    try:
        ttfb, n, total = _fetch(prefix + TARGET_BIG, timeout=30)
        if n < 100_000:
            return 0
        return round(n / 1024 / max(total, 0.01))
    except Exception:
        return 0


def probe_one(prefix):
    ttfb = probe_small(prefix)
    kbps = probe_big(prefix) if ttfb is not None else 0
    return {"prefix": prefix, "ttfb_ms": ttfb, "KBps": kbps,
            "alive": ttfb is not None, "score_ok": ttfb is not None and kbps > 0}


def main():
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(probe_one, CANDIDATES))

    # 排序：存活且大文件可测速的按速度降序 → 仅小文件存活的按延迟升序 → 不可达垫底
    ok_both = sorted([r for r in results if r["alive"] and r["KBps"] > 0],
                     key=lambda r: -r["KBps"])
    ok_small = sorted([r for r in results if r["alive"] and r["KBps"] == 0],
                      key=lambda r: r["ttfb_ms"])
    dead = [r for r in results if not r["alive"]]
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
        "dead": [r["prefix"] for r in dead],
        "ranking": [{"prefix": r["prefix"].rstrip("/"), "ttfb_ms": r["ttfb_ms"],
                     "KBps": r["KBps"]} for r in ordered],
    }
    print("== 镜像实测排名 ==")
    for i, r in enumerate(ordered, 1):
        print(f"  {i}. {r['prefix'].rstrip('/')}  ttfb={r['ttfb_ms']}ms  {r['KBps']}KB/s")
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
