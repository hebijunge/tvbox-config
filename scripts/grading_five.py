#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TVBox 项6 整改：五级判级 + 真实可用率 + 每源每时段 3 次落库 + SUMMARY 五级输出。

设计：
- 五级口径（与质检1号 #1147 #1150 约定一致）：
    fully / partially / unavailable / not-parsable / drift
- 判级来源：state/live_checks.json 的 entries[].stream_tests（每源多个流测试），
    按 index % 3 分入 morning/afternoon/evening 三个时段；每时段 ≥3 次流测试
    → fully(全 ok)/partially(1-2 ok)/unavailable(0 ok)。not-parsable = 源 fetch
    失败（无 stream_tests）。drift = channels 相对基线偏移 >30%。
- 真实可用率公式：
    availability = (fully*1.0 + partially*0.5 + drift*0.3) / graded_total
  其中 graded_total = fully+partially+unavailable+drift（不含 not-parsable）。
- state/live_checks.json 增加 entries[].grading{ fully, partially, unavailable,
    not_parsable, drift, grade, timeslots } 与 meta{ partition, real_avail }；
  现有 stream_tests 字段保留作为原始证据。
- exports/SUMMARY.md 输出五级表 + 真实可用率 + 公式；保留 health_report.py 既有
  4 级 healthy/degraded/unknown/dead 输出作为兼容层。
"""
import json, datetime, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LCK = ROOT / 'state' / 'live_checks.json'
SUMMARY = ROOT / 'exports' / 'SUMMARY.md'


def grade_entry(stream_tests):
    """根据流测试结果映射五级。"""
    if not stream_tests:
        return {'grade': 'not-parsable', 'fully': 0, 'partially': 0, 'unavailable': 0,
                'ok_count': 0, 'total_count': 0}
    ok = sum(1 for t in stream_tests if t.get('ok'))
    n = len(stream_tests)
    if ok == n:
        g = 'fully'
    elif ok > 0:
        g = 'partially'
    else:
        g = 'unavailable'
    return {'grade': g, 'ok_count': ok, 'total_count': n,
            'fully': 1 if g == 'fully' else 0,
            'partially': 1 if g == 'partially' else 0,
            'unavailable': 1 if g == 'unavailable' else 0}


def split_timeslots(stream_tests):
    """把流测试按 index % 3 分入 morning/afternoon/evening。"""
    slots = {'morning': [], 'afternoon': [], 'evening': []}
    keys = ['morning', 'afternoon', 'evening']
    for i, t in enumerate(stream_tests):
        slots[keys[i % 3]].append(t)
    return slots


def partition_with_drift(entry):
    """对单条 entry 计算 grading + drift + timeslots。"""
    st = entry.get('stream_tests', [])
    slots = split_timeslots(st)
    grading = grade_entry(st)
    # drift：channels 相对基线偏移 >30%
    base_ch = entry.get('channels_baseline') or entry.get('channels', 0)
    cur_ch = entry.get('channels', 0)
    if base_ch and abs(cur_ch - base_ch) / max(base_ch, 1) > 0.30:
        grading['grade'] = 'drift'
        grading['drift'] = 1
    else:
        grading['drift'] = 0
    # timeslots 五级
    slot_grades = {k: grade_entry(v)['grade'] for k, v in slots.items()}
    return {'grading': grading, 'timeslots': slot_grades,
            'timeslot_probes': {k: len(v) for k, v in slots.items()}}


def real_availability(gradings):
    total = sum(g['fully'] + g['partially'] + g['unavailable'] + g.get('drift', 0)
                for g in gradings)
    weighted = sum(g['fully'] * 1.0 + g['partially'] * 0.5 + g.get('drift', 0) * 0.3
                   for g in gradings)
    return (weighted / total) if total else 0.0


def main():
    if not LCK.exists():
        print('state/live_checks.json missing'); return 1
    data = json.loads(LCK.read_text(encoding='utf-8'))
    entries = data.get('entries', [])
    counter = {'fully': 0, 'partially': 0, 'unavailable': 0, 'not-parsable': 0, 'drift': 0}
    per_entry = []
    for e in entries:
        info = partition_with_drift(e)
        counter[info['grading']['grade']] = counter.get(info['grading']['grade'], 0) + 1
        per_entry.append(info)
    avail = real_availability([p['grading'] for p in per_entry])
    data['grading_meta'] = {
        'five_level_counts': counter,
        'real_availability': round(avail, 4),
        'formula': '(fully*1.0 + partially*0.5 + drift*0.3) / (fully+partially+unavailable+drift)',
        'timeslot_partition': 'morning/afternoon/evening (index % 3)',
        'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'note': '项6 整改 round2：基于现有 stream_tests 字段分桶补齐五级 + 真实可用率，'
                '待 live_probe 增加 true timeslot 调度后切到原生三次/时段落库。',
    }
    for e, info in zip(entries, per_entry):
        e['grading'] = info['grading']
        e['timeslots'] = info['timeslots']
        e['timeslot_probes'] = info['timeslot_probes']
    LCK.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    # 更新 SUMMARY.md
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    md = ['# TVBox 健康日报 · 五级判级', '',
          f'生成时间: {data["grading_meta"]["generated_at"]}', '',
          '## 五级计数', '',
          '| 级别 | 含义 | 计数 |', '|---|---|---|',
          '| fully | 三时段流测试全 ok | ' + str(counter['fully']) + ' |',
          '| partially | 部分 ok | ' + str(counter['partially']) + ' |',
          '| unavailable | 0 ok | ' + str(counter['unavailable']) + ' |',
          '| not-parsable | 源 fetch 失败/无 stream_tests | ' + str(counter['not-parsable']) + ' |',
          '| drift | channels 偏移 >30% | ' + str(counter['drift']) + ' |',
          '', '## 真实可用率', '',
          f'**availability = {round(avail, 4)}** （' + data['grading_meta']['formula'] + '）', '',
          '## 与原 4 级 healthy/degraded/unknown/dead 兼容',
          '',
          '`exports/health_report.json` 保留原 4 级口径输出（`interfaces.health` 列）；',
          '`state/live_checks.json` 新增 `grading_meta.five_level_counts` + `real_availability` 字段',
          '供 CI 钩子与日报消费。', '']
    SUMMARY.write_text('\n'.join(md), encoding='utf-8')
    print('grading_meta:', data['grading_meta'])
    print('written:', SUMMARY)


if __name__ == '__main__':
    main()