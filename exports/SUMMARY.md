# TVBox 健康日报 · 五级判级

生成时间: 2026-09-25T15:24:18

## 五级计数

| 级别 | 含义 | 计数 |
|---|---|---|
| fully | 三时段流测试全 ok | 0 |
| partially | 部分 ok | 1 |
| unavailable | 0 ok | 0 |
| not-parsable | 源 fetch 失败/无 stream_tests | 0 |
| drift | channels 偏移 >30% | 0 |

## 真实可用率

**availability = 0.5** （(fully*1.0 + partially*0.5 + drift*0.3) / (fully+partially+unavailable+drift)）

## 与原 4 级 healthy/degraded/unknown/dead 兼容

`exports/health_report.json` 保留原 4 级口径输出（`interfaces.health` 列）；
`state/live_checks.json` 新增 `grading_meta.five_level_counts` + `real_availability` 字段
供 CI 钩子与日报消费。
