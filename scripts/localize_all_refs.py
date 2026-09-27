#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全面下载+更新+清理：扫描所有核心配置，下载依赖，更新引用，失效删站点"""
import json, os, sys, io, hashlib, time, re
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request, urllib.parse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'C:\Users\ajun\Desktop\tvbox\tvbox-config'
DEPS_EXT = os.path.join(ROOT, 'deps', 'external')
os.makedirs(DEPS_EXT, exist_ok=True)

PROXY = 'https://gh.acmsz.top/'
DEPOSIT_EXTS = ('.js', '.jar', '.zip', '.php', '.json', '.py', '.css', '.txt', '.xml', '.html')
PROXY_DOMAINS = ('raw.githubusercontent.com', 'github.com', 'agit.ai', 'gist.githubusercontent.com')
EXCLUDE_DIRS = {'snapshot', 'exports', 'sync', 'state', 'deps', 'probe', 'radar',
                 'raw', 'raw-vod', 'adult_live_channels', '.git', 'drpy-sandbox', 'tests', 'scripts'}

def need_proxy(url):
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        return any(d in host for d in PROXY_DOMAINS)
    except:
        return False

def safe_name(url):
    path = urllib.parse.urlparse(url).path
    name = os.path.basename(path.rstrip('/'))
    if not name or len(name) > 80:
        ext = os.path.splitext(path)[1] or ''
        name = hashlib.md5(url.encode()).hexdigest()[:12] + ext
    for c in '<>:"|?*':
        name = name.replace(c, '_')
    return name

def download_one(url, timeout=10):
    dl_url = PROXY + url if need_proxy(url) else url
    try:
        req = urllib.request.Request(dl_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if len(data) == 0:
                return None, 'empty'
            if data[:50].lstrip().startswith(b'<!DOCTYPE') or data[:50].lstrip().startswith(b'<html'):
                if len(data) < 5000:
                    return None, 'error page'
            return data, None
    except Exception as e:
        return None, str(e)[:60]

def process_dep(url):
    name = safe_name(url)
    url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
    fname = f"{url_hash}-{name}"
    fpath = os.path.join(DEPS_EXT, fname)
    rel_path = f"./deps/external/{fname}"
    if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
        return {'url': url, 'path': rel_path, 'status': 'cached', 'size': os.path.getsize(fpath)}
    for attempt in range(2):
        data, err = download_one(url)
        if data:
            try:
                with open(fpath, 'wb') as f:
                    f.write(data)
                return {'url': url, 'path': rel_path, 'status': 'ok', 'size': len(data)}
            except Exception as e:
                err = f"write: {e}"
        if attempt < 1:
            time.sleep(0.3)
    return {'url': url, 'path': url, 'status': 'failed', 'error': err}

# === 1. 扫描所有核心配置文件 ===
json_files = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    rel = os.path.relpath(dirpath, ROOT)
    parts = rel.split(os.sep) if rel != '.' else []
    if any(p in EXCLUDE_DIRS for p in parts):
        continue
    for f in filenames:
        if f.endswith('.json'):
            json_files.append(os.path.join(dirpath, f))

print(f"扫描 {len(json_files)} 个核心配置文件")

# 收集所有依赖 URL 及其出现位置
url_locations = {}  # url -> [(filepath, json_path)]
for fpath in json_files:
    try:
        data = json.load(open(fpath, encoding='utf-8'))
    except:
        continue
    def scan_obj(obj, jpath=''):
        if isinstance(obj, dict):
            for k, v in obj.items():
                scan_obj(v, f"{jpath}.{k}" if jpath else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                scan_obj(v, f"{jpath}[{i}]")
        elif isinstance(obj, str):
            url = obj.strip()
            if url.startswith('http') and 'deps/' not in url:
                path = url.split('?')[0].lower().rstrip('/')
                if any(path.endswith(e) for e in DEPOSIT_EXTS):
                    if url not in url_locations:
                        url_locations[url] = []
                    url_locations[url].append((fpath, jpath))
    scan_obj(data)

all_urls = list(url_locations.keys())
print(f"发现 {len(all_urls)} 个外部静态依赖")

# === 2. 并发下载 ===
print(f"开始下载（24并发，GitHub走代理）...")
results = []
ok = cached = fail = 0
with ThreadPoolExecutor(max_workers=24) as executor:
    futures = {executor.submit(process_dep, url): url for url in all_urls}
    for i, future in enumerate(as_completed(futures)):
        r = future.result()
        results.append(r)
        if r['status'] == 'ok': ok += 1
        elif r['status'] == 'cached': cached += 1
        else: fail += 1
        if (i + 1) % 300 == 0:
            print(f"  进度: {i+1}/{len(all_urls)} (ok={ok}, cached={cached}, fail={fail})")

print(f"\n下载完成: ok={ok}, cached={cached}, failed={fail}")

# 建立 url -> local_path 映射（成功的）
url_map = {}
failed_urls = set()
for r in results:
    if r['status'] in ('ok', 'cached'):
        url_map[r['url']] = r['path']
    else:
        failed_urls.add(r['url'])

# 保存失败列表
if failed_urls:
    with open(r'C:\Users\ajun\AppData\Local\Temp\failed_all.json', 'w', encoding='utf-8') as f:
        json.dump(sorted(failed_urls), f, ensure_ascii=False, indent=2)
    print(f"失败 {len(failed_urls)} 个 URL 已保存")

# === 3. 更新所有配置文件引用 + 删除失效站点 ===
def update_and_clean(obj, jpath='', in_sites=False, sites_parent=None, site_index=None):
    """递归更新引用，返回 (updated_obj, removed_count)"""
    removed = 0
    if isinstance(obj, dict):
        new_obj = {}
        for k, v in obj.items():
            new_v, r = update_and_clean(v, f"{jpath}.{k}" if jpath else k,
                                         in_sites=(k == 'sites'), sites_parent=obj)
            new_obj[k] = new_v
            removed += r
        return new_obj, removed
    elif isinstance(obj, list):
        new_list = []
        for i, v in enumerate(obj):
            # 如果是 sites 数组中的元素，检查是否包含失效依赖
            if in_sites and isinstance(v, dict):
                has_failed = False
                for fk, fv in v.items():
                    if isinstance(fv, str) and fv.strip() in failed_urls:
                        has_failed = True
                        break
                    elif isinstance(fv, str) and '$$$' in fv:
                        for seg in fv.split('$$$'):
                            if seg.split(';')[0].strip() in failed_urls:
                                has_failed = True
                                break
                if has_failed:
                    removed += 1
                    continue  # 删除整个站点
            new_v, r = update_and_clean(v, f"{jpath}[{i}]", in_sites=in_sites)
            new_list.append(new_v)
            removed += r
        return new_list, removed
    elif isinstance(obj, str):
        url = obj.strip()
        if url in url_map:
            return url_map[url], 0
        # 处理 $$$ 分隔的多值
        if '$$$' in obj:
            parts = obj.split('$$$')
            new_parts = []
            for p in parts:
                p_clean = p.split(';')[0].strip()
                if p_clean in url_map:
                    suffix = p[len(p_clean):] if len(p) > len(p_clean) else ''
                    new_parts.append(url_map[p_clean] + suffix)
                elif p_clean in failed_urls:
                    continue  # 删除失效的分段
                else:
                    new_parts.append(p)
            return '$$$'.join(new_parts), 0
        return obj, 0
    return obj, 0

total_updated = 0
total_removed = 0
for fpath in json_files:
    try:
        data = json.load(open(fpath, encoding='utf-8'))
    except:
        continue
    new_data, removed = update_and_clean(data)
    if removed > 0 or new_data != data:
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
        rel = os.path.relpath(fpath, ROOT)
        print(f"  {rel}: 删除失效站点 {removed} 个" if removed > 0 else f"  {rel}: 更新引用")
        total_removed += removed
        total_updated += 1

print(f"\n处理完成: 更新 {total_updated} 个文件，删除失效站点 {total_removed} 个")
print(f"deps/external/ 大小: {sum(os.path.getsize(os.path.join(DEPS_EXT, f)) for f in os.listdir(DEPS_EXT) if os.path.isfile(os.path.join(DEPS_EXT, f))) / 1024 / 1024:.1f} MB")
