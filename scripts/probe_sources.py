#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_sources.py — 全部采集入口链接清单 + 可达性探测

汇集项目当前实际在用的所有采集链接（不是搜索关键词，是真实抓取的地址）：
  A 固定上游（fetch_merge.UPSTREAMS，41 条）
  B canary 收编池（state/extra_upstreams.json）
  C 种子仓（discover_upstreams.SEEDS 的 README，3 个）
  D Gitee 候选（radar 评估过的 gitee.com 链接）
  E 文章/配置站（radar 候选池里 Web 路抓到的非 GitHub 链接）
  F Gitee 曲线挖到的 57 个仓库全名对应的 raw 入口
并发探测 HTTP 状态/延迟/内容形态（json/m3u/html/other），产出：
  radar/source_probe.json  逐条明细（可入 DB 做上游健康）
  .workbuddy/audit/采集链接清单.html  可上传资料库的清单页（200 可导入的单独成章）

用法：python scripts/probe_sources.py [--concurrency 16] [--retest-only]
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
os.chdir(ROOT)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tvbox-radar",
      "Accept": "*/*"}
# 镜像兜底序（ghf 系最快，2026-09-19 测速择优产物）
GH_MIRROR = ("https://ghf.xn--eqrr82bzpe.top", "https://gh.927223.xyz",
             "https://gh.xxooo.cf", "https://ghproxy.net")


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def gh_proxy_urls(url):
    """githubusercontent 直连常被墙：返回 直连 + 4 镜像 共 5 个候选。
    镜像形态与 canary 池既有约定一致：镜像 + 完整 URL（含 scheme）。
    例：https://ghproxy.net/https://raw.githubusercontent.com/qist/tvbox/master/js.json"""
    if "githubusercontent.com" not in url:
        return [url]
    out = [url]
    for m in GH_MIRROR:
        out.append(m.rstrip("/") + "/" + url)
    return out


def http_probe(url, timeout=10, max_bytes=65536):
    req = urllib.request.Request(url, headers=UA)
    t0 = datetime.now()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(max_bytes)
            ms = int((datetime.now() - t0).total_seconds() * 1000)
            ct = r.headers.get("Content-Type", "")
            txt = raw[:2000].decode("utf-8", "replace")
            if txt.startswith("#EXTM3U"):
                kind = "m3u"
            elif txt.lstrip().startswith(("{", "[")):
                kind = "json"
            elif "<html" in txt[:300].lower():
                kind = "html"
            else:
                kind = "other"
            sites = 0
            if kind == "json":
                try:
                    d = json.loads(raw.decode("utf-8", "replace"))
                    s = d.get("sites") or d.get("video") or (d if isinstance(d, list) else [])
                    sites = len(s)
                except Exception:
                    pass
            return {"ok": True, "status": r.status, "ms": ms, "kind": kind,
                    "bytes": len(raw), "sites": sites, "final_url": r.geturl(),
                    "ct": ct}
    except Exception as e:
        ms = int((datetime.now() - t0).total_seconds() * 1000)
        code = getattr(e, "code", None)
        return {"ok": False, "status": code or "ERR", "ms": ms, "err": str(e)[:80],
                "final_url": None}


def probe_one(item, workers_hint=1):
    """单条探测；raw.githubusercontent 自动走镜像序直到成功。"""
    urls = gh_proxy_urls(item["url"])
    results = []
    for i, u in enumerate(urls):
        r = http_probe(u)
        r["url"] = u
        results.append(r)
        if r["ok"] and r.get("status") == 200:
            break
    best = next((x for x in results if x["ok"]), results[-1])
    best["attempts"] = len(results)
    item.update({k: best.get(k) for k in
                 ("ok", "status", "ms", "kind", "bytes", "sites", "final_url")
                 if k in best})
    if not best["ok"]:
        item["err"] = best.get("err", str(best.get("status")))
    return item


def collect_links():
    links = {}  # url -> dict

    def add(url, cat, name="", extra=None):
        url = url.strip()
        if not url.startswith("http"):
            return
        if url in links:
            links[url]["cats"].add(cat)
        else:
            links[url] = {"url": url, "cats": {cat}, "name": name,
                          **(extra or {})}

    # A 固定上游
    import sys
    sys.path.insert(0, HERE)
    try:
        from fetch_merge import ALL_UPSTREAMS
        # 手动黑名单（state/blacklist_manual.txt，每行一个上游名）：命中的永不进清单
        bl = set()
        blp = os.path.join("state", "blacklist_manual.txt")
        if os.path.isfile(blp):
            for ln in open(blp, encoding="utf-8"):
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    bl.add(ln)
        for u in ALL_UPSTREAMS:
            if u["name"] in bl:
                continue
            add(u["url"], "固定上游", u.get("name", ""))
    except Exception as e:
        log("固定上游导入失败: %s" % e)

    # B canary
    try:
        ex = json.load(open("state/extra_upstreams.json", encoding="utf-8"))
        for u in ex.get("upstreams", []):
            add(u["url"], "canary", u.get("name", ""))
    except Exception as e:
        log("canary 读取失败: %s" % e)

    # C 种子仓
    src = open(os.path.join(HERE, "discover_upstreams.py"), encoding="utf-8").read()
    m = re.search(r"^SEEDS = \[(.*?)\n\]", src, re.M | re.S)
    for name, url in re.findall(r'\(\s*"([^"]+)"\s*,\s*"(https?://[^"]+)"\s*\)', m.group(1)):
        add(url, "种子仓", name)

    # D+e radar 候选（Gitee 曲线 + Web 路 + 配置站）
    try:
        disc = json.load(open("radar/discovered.json", encoding="utf-8"))
        for c in disc.get("candidates", []):
            add(c.get("url", ""), "Gitee候选" if "gitee.com" in c.get("url", "")
                else ("Web/配置站" if c.get("kind") == "tvbox" else "候选"),
                c.get("url", ""))
        ev = json.load(open("radar/candidate_eval.json", encoding="utf-8"))
        for c in ev.get("candidates", []):
            add(c.get("url", ""), "评估候选")
    except Exception as e:
        log("radar 候选读取失败: %s" % e)

    out = list(links.values())
    for it in out:
        it["cats"] = sorted(it["cats"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--retest-only", action="store_true",
                    help="只重测上轮非 200 的（幂等增量）")
    args = ap.parse_args()

    links = collect_links()
    log("全部采集链接（去重后）：%d 条" % len(links))
    cat_cnt = {}
    for it in links:
        for c in it["cats"]:
            cat_cnt[c] = cat_cnt.get(c, 0) + 1
    log("来源构成：" + " ".join("%s %d" % (k, v) for k, v in sorted(cat_cnt.items())))

    # 增量：上轮 ok 的复用（24h 内）
    prev = {}
    if os.path.isfile("radar/source_probe.json") and args.retest_only:
        p = json.load(open("radar/source_probe.json", encoding="utf-8"))
        for s in p.get("sources", []):
            prev[s["url"]] = s
    todo, reused = [], []
    now = datetime.now()
    for it in links:
        old = prev.get(it["url"])
        if old and old.get("ok") and (now - datetime.fromisoformat(old.get("probed_at", "2000-01-01"))).days < 1:
            it["probed_at"] = old["probed_at"]
            it.update({k: old.get(k) for k in ("status", "ms", "kind", "sites", "ok")})
            reused.append(it)
        else:
            todo.append(it)
    if reused:
        log("增量复用 24h 内 200 的 %d 条，实际探测 %d 条" % (len(reused), len(todo)))

    done = 0
    with cf.ThreadPoolExecutor(args.concurrency) as ex:
        for it in ex.map(lambda x: probe_one(x), todo):
            done += 1
            if done % 20 == 0:
                log("进度 %d/%d" % (done, len(todo)))

    ok = [i for i in links if i.get("ok")]
    bad = [i for i in links if not i.get("ok")]
    log("探测完成：200 可用 %d / 不可用 %d" % (len(ok), len(bad)))

    report = {
        "generated_at": now.isoformat(timespec="seconds"),
        "total": len(links), "ok": len(ok), "bad": len(bad),
        "sources": sorted(links, key=lambda x: (not x.get("ok"), x["url"])),
    }
    os.makedirs("radar", exist_ok=True)
    json.dump(report, open("radar/source_probe.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # HTML 清单页（200 可导入的单独成章）
    import html as H
    def rows(items, show_sites=True):
        out = ""
        for it in items:
            out += ('<tr class="%s"><td class="u">%s</td><td>%s</td><td>%s</td>'
                    '<td>%s</td><td>%s</td><td>%s</td></tr>\n' % (
                        "ok" if it.get("ok") else "bad",
                        H.escape(it["url"]),
                        H.escape("/".join(it["cats"])),
                        H.escape(str(it.get("name") or "")),
                        H.escape(str(it.get("status") if it.get("ok") else it.get("err", ""))),
                        ("%d" % it["ms"]) if it.get("ok") else "-",
                        H.escape(str(it.get("kind", ""))) if show_sites else "",
                        ))
        return out
    status_rows = "\n".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (H.escape(k), v)
        for k, v in cat_cnt.items())
    htm = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>采集链接清单与可达性探测 {now.strftime('%m-%d %H:%M')}</title>
<style>
body{{font:14px/1.6 -apple-system,"Microsoft YaHei",sans-serif;margin:0;background:#f6f7f9;color:#1c1c1e}}
header{{background:#fff;border-bottom:1px solid #e3e5e8;padding:18px 26px;position:sticky;top:0;z-index:9}}
h1{{font-size:17px;margin:0 0 6px}} nav a{{margin-right:12px;font-size:13px;color:#185fa5;text-decoration:none}}
input{{padding:6px 12px;border:1px solid #c9ccd1;border-radius:8px;width:min(380px,55vw);font-size:13px;margin-left:14px}}
main{{padding:18px 26px;max-width:1200px;margin:0 auto}}
section{{background:#fff;border:1px solid #e3e5e8;border-radius:12px;padding:16px 20px;margin:16px 0}}
h2{{font-size:14px;margin:0 0 8px;border-left:4px solid #185fa5;padding-left:10px}}
p{{color:#444;margin:4px 0;font-size:13px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}}
th{{background:#f0f3f7;text-align:left;position:sticky;top:56px}}
th,td{{border:1px solid #e3e5e8;padding:4px 8px}}
tr.ok td:first-child{{border-left:3px solid #1d9e75}}
tr.bad td:first-child{{border-left:3px solid #e24b4a}}
.u{{color:#0c447c;font-family:Consolas,monospace;font-size:11.5px;word-break:break-all}}
.kpis{{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0}}
.kpi{{border:1px solid #e3e5e8;border-radius:10px;padding:8px 16px;text-align:center;background:#fff}}
.kpi b{{display:block;font-size:20px;color:#185fa5}} .kpi span{{font-size:12px;color:#666}}
</style></head><body>
<header><h1>采集链接清单 · 可达性探测 <small style="font-weight:400;color:#666">{now.strftime('%Y-%m-%d %H:%M')} · GitHub 直连自动走镜像兜底</small></h1>
<nav><a href="#a">200 可导入</a><a href="#b">全部明细</a><a href="#c">来源构成</a><input id="q" placeholder="搜索（地址/来源）…" oninput="f(this.value)"></nav></header>
<main>
<div class="kpis">
<div class="kpi"><b>{report['total']}</b><span>全部采集链接（去重）</span></div>
<div class="kpi"><b>{len(ok)}</b><span>200 可用</span></div>
<div class="kpi"><b>{len(bad)}</b><span>不可用</span></div>
<div class="kpi"><b>{sum(1 for i in ok if i.get('kind')=='json')}</b><span>可解析 JSON 配置</span></div>
</div>
<section id="a"><h2>200 可导入（{len(ok)} 条，全部实测 HTTP 200）</h2>
{rows(ok)}
</section>
<section id="b"><h2>不可用 / 全量明细（{len(bad)} 条失败）</h2>
{rows(bad)}
</section>
<section id="c"><h2>来源构成</h2>
<table>{status_rows}</table>
<p>固定上游=fetch_merge.UPSTREAMS · canary=评估收编池 · 种子仓=README 递归 · Gitee候选/Web配置站=发现路产出 · 探测含 ghproxy 镜像兜底（raw.githubusercontent 直连失败自动换镜像重试）。</p>
</section>
</main>
<script>function f(q){{q=q.toLowerCase();document.querySelectorAll('main table').forEach(t=>{{t.querySelectorAll('tbody tr, tr').forEach(tr=>{{tr.style.display=tr.textContent.toLowerCase().includes(q)?'':'none'}})}})}}
</script></body></html>"""
    import os as _os
    adir = os.path.join(".workbuddy", "audit")
    _os.makedirs(adir, exist_ok=True)
    html_path = os.path.join(adir, "采集链接清单.html")
    open(html_path, "w", encoding="utf-8").write(htm)
    log("产物：radar/source_probe.json + %s" % html_path)

    top_sites = sorted([i for i in ok if i.get("sites")], key=lambda x: -x["sites"])
    print("\n=== 带站点数的 TOP10（可导入价值最高）===")
    for i in top_sites[:10]:
        print("  %4d 站  %6sms  %s" % (i["sites"], i.get("ms", 0), i["url"][:70]))
    print("\n=== 失败样例 ===")
    for i in bad[:8]:
        print("  %-10s %s  %s" % (i.get("status", "ERR"), i["url"][:60], str(i.get("err", ""))[:40]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
