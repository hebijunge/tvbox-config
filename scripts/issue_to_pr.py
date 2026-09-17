#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
issue 自动转 PR（P2，laoma2053/awesome-zhuiju-free 模式）：
  用户按模板提 issue 推荐上游 → 本脚本从 issue body 提取 URL 并验活 →
  可用者写入 candidate_upstreams.json → 开分支提交 → 自动创建 PR。
运行于 GitHub Actions（issue 触发），凭据用 GITHUB_TOKEN，不落明文。
"""
import json
import os
import re
import sys
import time
import urllib.request

UA = {"User-Agent": "issue-to-pr", "Accept": "application/vnd.github+json"}
URL_RE = re.compile(r"https?://[^\s\"'<>\\)\]]+", re.I)
DROP_RE = re.compile(r"github\.com/hebijunge/tvbox-config|img\.shields\.io|\.png|\.jpg|\.svg|\.ico|\.webp", re.I)


def api(method: str, path: str, token: str, payload=None):
    url = f"https://api.github.com{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={**UA, "Authorization": f"Bearer {token}"}, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    return json.loads(body) if body else {}


def check_url(u: str):
    for attempt in (u, "https://ghproxy.net/" + u if "github" in u else u):
        try:
            req = urllib.request.Request(attempt, headers={"User-Agent": "okhttp/3.15"})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read(20480)
            if r.status == 200 and len(body) > 100:
                return {"url": u, "ok": True, "bytes": len(body),
                        "latency_ms": int((time.time() - t0) * 1000), "checked_via": attempt}
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"[:100]
    return {"url": u, "ok": False, "error": last}


def main() -> int:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    issue_number = os.environ.get("ISSUE_NUMBER", "")
    issue_body = os.environ.get("ISSUE_BODY", "")
    if not (token and repo and issue_number):
        print("缺少 GH_TOKEN / GITHUB_REPOSITORY / ISSUE_NUMBER，跳过")
        return 0

    urls = []
    seen = set()
    for m in URL_RE.finditer(issue_body or ""):
        u = m.group(0).rstrip(".,;")
        if DROP_RE.search(u) or u in seen:
            continue
        seen.add(u)
        urls.append(u)
    if not urls:
        print("issue 中未发现候选 URL，跳过")
        return 0
    print(f"提取到 {len(urls)} 个候选 URL：{urls}")

    results = [check_url(u) for u in urls]
    valid = [r for r in results if r["ok"]]
    for r in results:
        print(("OK  " if r["ok"] else "FAIL") + " " + r["url"])

    # 更新 candidate_upstreams.json
    with open("candidate_upstreams.json", "r", encoding="utf-8") as f:
        doc = json.load(f)
    added = 0
    for r in valid:
        if any(c["url"] == r["url"] for c in doc.get("candidates", [])):
            continue
        doc.setdefault("candidates", []).append({
            "url": r["url"], "bytes": r["bytes"], "latency_ms": r["latency_ms"],
            "issue": f"#{issue_number}", "added_via": "issue-to-pr",
        })
        added += 1
    if added == 0:
        print("无新增候选（均已登记或全部不可用），仅回评 issue")
    else:
        doc["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC"
        with open("candidate_upstreams.json", "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)

    comment = (
        f"🤖 自动验活结果（issue-to-pr）：\n\n"
        + "".join(f"- {'✅ 可用' if r['ok'] else '❌ 不可用'} {r['url']}"
                  + (f"（{r['bytes']}B, {r['latency_ms']}ms）" if r["ok"] else f"（{r.get('error', '')}）") + "\n"
                  for r in results)
        + ("\n✅ 已自动登记进 `candidate_upstreams.json` 并发起 PR，人工确认后收编进每日拉取清单。"
           if added else "\n候选未收编：已登记或验活未通过。")
    )
    api("POST", f"/repos/{repo}/issues/{issue_number}/comments", token, {"body": comment})
    if added == 0:
        return 0

    # 开分支 → 提交 → 建 PR
    branch = f"issue-{issue_number}-upstream"
    from urllib.request import Request  # noqa: E402
    ref = api("GET", f"/repos/{repo}/git/ref/heads/main", token)
    base_sha = ref["object"]["sha"]
    try:
        api("POST", f"/repos/{repo}/git/refs", token,
            {"ref": f"refs/heads/{branch}", "sha": base_sha})
    except Exception:
        pass  # 分支已存在
    # 取候选文件当前 blob
    try:
        cf = api("GET", f"/repos/{repo}/contents/candidate_upstreams.json?ref={branch}", token)
        cf_sha = cf["sha"]
    except Exception:
        cf_sha = None
    content = open("candidate_upstreams.json", "rb").read()
    import base64
    put = {"message": f"chore: add upstream candidates from issue #{issue_number}",
           "content": base64.b64encode(content).decode(), "branch": branch}
    if cf_sha:
        put["sha"] = cf_sha
    api("PUT", f"/repos/{repo}/contents/candidate_upstreams.json", token, put)
    pr = api("POST", f"/repos/{repo}/pulls", token, {
        "title": f"收录 issue #{issue_number} 推荐的上游源",
        "head": branch, "base": "main",
        "body": comment + "\n\n（由 issue-to-pr 工作流自动创建，请人工确认后合并）",
    })
    print(f"PR 已创建: {pr.get('html_url', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
