#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TVBox 项1 整改完整版：站点清洗 + _proxy 镜像 + lives 频道（含 tvbox/vod/sync 三处 lives 数组） + 词表补齐。"""
import json, re, copy, datetime, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB = json.loads((ROOT / 'state' / 'vocab' / 'categories.json').read_text(encoding='utf-8'))
INVENTORY = ROOT / 'state' / 'adult_cleaning_inventory.json'

ROUND2_HOSTS = ['apiyutu.com', 'slapibf.com', 'jable.tv', 'madouse.la', 'siwazyw.com',
                '91porn.com', '91md.la', 'pornhub.com']
ROUND2_KEYWORDS = ['玉兔', '小黄书', '乱伦', 'madouse', '麻豆', 'jable']
KEEP_NAME_WHITELIST = {'影视森林'}
HOST_PAT = re.compile(VOCAB['adult']['host_blacklist_pattern'], re.I)
LIVE_ADULT_KW = set(VOCAB['adult']['name_keywords']) | set(ROUND2_KEYWORDS)
ADULT_LIVE = ROOT / 'adult_live_channels.json'


def is_adult_site(site):
    if not isinstance(site, dict): return False, 'not_dict'
    key = (site.get('key') or '').strip(); name = (site.get('name') or '').strip()
    api = (site.get('api') or '').strip(); jar = (site.get('jar') or '').strip()
    ext = site.get('ext') if isinstance(site.get('ext'), dict) else {}
    text = f"{key} {name} {api} {jar} {json.dumps(ext, ensure_ascii=False)}".lower()
    if key in KEEP_NAME_WHITELIST or name in KEEP_NAME_WHITELIST:
        return False, 'whitelisted_name'
    for tok in VOCAB['adult']['host_blacklist_exact'] + ROUND2_HOSTS:
        if tok and tok.lower() in text: return True, f'host:{tok}'
    if HOST_PAT.search(text): return True, 'host_pat'
    for kw in VOCAB['adult']['name_keywords']:
        if kw and kw.lower() in text: return True, f'kw:{kw}'
    for kw in ROUND2_KEYWORDS:
        if kw and kw.lower() in text: return True, f'kw_new:{kw}'
    return False, 'clean'


def is_adult_live(L):
    if not isinstance(L, dict): return False
    txt = f"{L.get('name','')} {L.get('group','')} {L.get('url','')}".lower()
    return any(k.lower() in txt for k in LIVE_ADULT_KW)


def clean_sites_file(path, label, all_inv):
    if not path.exists(): return 0
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or 'sites' not in data: return 0
    kept, removed = [], []
    seen_local = set()
    ap = ROOT / 'adult.json'
    if ap.exists():
        for s in json.loads(ap.read_text(encoding='utf-8')).get('sites', []):
            seen_local.add((s.get('key'), s.get('api')))
    for idx, site in enumerate(data.get('sites', [])):
        is_a, reason = is_adult_site(site)
        if is_a:
            removed.append(site)
            all_inv.append({'file': label, 'idx': idx, 'key': site.get('key'), 'name': site.get('name'),
                            'api': site.get('api'), 'reason': reason, 'destination': 'adult.json',
                            'round': 2, 'ts': datetime.datetime.now().isoformat(timespec='seconds')})
        else:
            kept.append(site)
    data['sites'] = kept
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    if removed:
        adult = json.loads(ap.read_text(encoding='utf-8')) if ap.exists() else {'sites': []}
        adult.setdefault('sites', [])
        for s in removed:
            k = (s.get('key'), s.get('api'))
            if k in seen_local: continue
            seen_local.add(k)
            adult['sites'].append({**copy.deepcopy(s), '_adult_round': 2})
        ap.write_text(json.dumps(adult, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return len(removed)


def clean_lives_in_obj(data, label, all_inv):
    """清洗 JSON 对象中的 lives 列表；原地修改 data。"""
    if 'lives' not in data or not isinstance(data['lives'], list): return 0
    kept, removed = [], []
    for idx, L in enumerate(data['lives']):
        if is_adult_live(L):
            removed.append(L)
            all_inv.append({'file': f'{label}:lives', 'idx': idx, 'key': L.get('name'), 'name': L.get('name'),
                            'api': (L.get('url') or '')[:80], 'reason': 'live:porn_kw',
                            'destination': 'adult_live_channels.json', 'round': 2,
                            'ts': datetime.datetime.now().isoformat(timespec='seconds')})
        else:
            kept.append(L)
    data['lives'] = kept
    if removed:
        al = []
        if ADULT_LIVE.exists():
            ex = json.loads(ADULT_LIVE.read_text(encoding='utf-8'))
            al = ex if isinstance(ex, list) else ex.get('channels', [])
        for L in removed: al.append({**L, '_adult_round': 2})
        ADULT_LIVE.write_text(json.dumps({'channels': al}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return len(removed)


def update_vocab():
    for h in ROUND2_HOSTS:
        if h not in VOCAB['adult']['host_blacklist_exact']:
            VOCAB['adult']['host_blacklist_exact'].append(h)
        tk = h.split('.')[0]
        if tk not in VOCAB['adult'].get('host_blacklist_tokens', []):
            VOCAB['adult'].setdefault('host_blacklist_tokens', []).append(tk)
    for kw in ROUND2_KEYWORDS:
        if kw not in VOCAB['adult']['name_keywords']:
            VOCAB['adult']['name_keywords'].append(kw)
    VOCAB['version'] = '2026-09-25.2'
    VOCAB.setdefault('source_note', '')
    _R2_NOTE = '2026-09-25 项1 整改 round2：补 host 8 域 + kw 6 词（含 jable 大小写）；处理 _proxy 镜像 + tvbox/vod/sync 三处 lives 数组（依据 QC #1150 预确认）'
    if _R2_NOTE not in VOCAB['source_note']:
        VOCAB['source_note'] += ' | ' + _R2_NOTE
    (ROOT / 'state' / 'vocab' / 'categories.json').write_text(json.dumps(VOCAB, ensure_ascii=False, indent=2), encoding='utf-8')


def update_inventory(entries):
    inv = json.loads(INVENTORY.read_text(encoding='utf-8')) if INVENTORY.exists() else {'round1': [], 'round2': [], 'meta': {}}
    inv.setdefault('round2', []).extend(entries)
    inv.setdefault('meta', {})['round2_total'] = len(inv['round2'])
    inv['meta']['round2_ts'] = datetime.datetime.now().isoformat(timespec='seconds')
    INVENTORY.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    all_inv = []
    counts = {}
    # 1) sites 类（含 _proxy 镜像）
    for f in ['tvbox.json', 'vod.json', 'short.json', 'stores/cms.json', 'stores/csp.json',
              'stores/cms_proxy.json', 'stores/csp_proxy.json']:
        counts[f] = clean_sites_file(ROOT / f, f, all_inv)
    # 2) tvbox/vod 内 lives 数组（站点文件自带 lives）
    for f in ['tvbox.json', 'vod.json']:
        p = ROOT / f
        if not p.exists(): continue
        d = json.loads(p.read_text(encoding='utf-8'))
        n = clean_lives_in_obj(d, f, all_inv)
        if n: p.write_text(json.dumps(d, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        counts[f'{f}:lives'] = n
    # 3) sync 由 tvbox 派生
    sync_path = ROOT / 'sync' / 'feishu_config_latest.json'
    if (ROOT / 'tvbox.json').exists():
        tvbox = json.loads((ROOT / 'tvbox.json').read_text(encoding='utf-8'))
        sync_path.write_text(json.dumps(tvbox, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        counts['sync:regen'] = 1
    # 4) 词表 + 清单
    update_vocab(); update_inventory(all_inv)
    print('counts:', counts, '| inventory entries:', len(all_inv))


if __name__ == '__main__':
    main()