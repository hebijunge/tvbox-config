# 分组顺序动态化方案

> 状态：待确认

## 背景与问题陈述

- 当前 group 顺序是固定写死的 `GROUP_ORDER` 列表（例如 电影→剧集→综艺→...）。
- 但 group 内源的质量每天都在变：今天"电影-CMS"组里全是死源，应该排后面；"动漫-drpy"组里全是优质源，应该排前面。
- 固定 GROUP_ORDER 无法反映这种动态变化。

## 方案设计

### 10.1 组质量分公式

```
group_score = 0.4 * avg(avail_rank_inv)
            + 0.3 * avg(searchable_rate)
            + 0.3 * avg(latency_norm)
```

对每个 group：
- 取组内所有 site 的 avail_rank_inv / 可搜率 / latency_norm 平均。
- 加权求和得到组质量分。

### 10.2 替代固定 GROUP_ORDER

每日 CI 末尾算一次所有 group 的质量分，按分数降序排列，写 `state/group_order.json`：

```json
{
  "updated_at": "2026-09-27T03:00:00+08:00",
  "order": ["电影-CMS", "剧集-CMS", "动漫-drpy", "综艺-聚合", "..."],
  "scores": {"电影-CMS": 0.82, "剧集-CMS": 0.75, "...": 0.61}
}
```

下次产出 tvbox.json 时，按这个顺序排 group。

### 10.3 稳定化处理

为避免 group 顺序每天抖动（今天 A 在前明天 B 在前）：
- 组质量分差异 < 0.05 时保持原顺序（hysteresis）。
- 连续 3 天排名上升/下降超过 5 位才实际调整。

## 影响评估

| 面 | 影响 |
| --- | --- |
| tvbox.json | group 顺序变，组内 site 顺序不变 |
| CI 时长 | < 2s |
| 用户端 | 好源组自然排前，找片更快 |
| 抖动风险 | 加 hysteresis 后应平稳 |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：写 `scripts/group_rank.py`，每日输出 `state/group_order.json`，但 tvbox.json 仍用固定 GROUP_ORDER。
2. **阶段 2**：人工 review 一周 group_order.json 是否合理。
3. **阶段 3**：切为动态顺序。

## 回滚方案

- `DYNAMIC_GROUP_ORDER=0` 环境变量切回固定 GROUP_ORDER。
- `state/group_order.json` 删除即回滚。

## 需用户确认的决策点

1. 组质量分权重（avail 0.4 / search 0.3 / latency 0.3）是否接受？
2. hysteresis 阈值 0.05、连续 3 天是否合适？
3. 是否与 group-compound 方案一起上线？还是先上 group-compound 再上动态顺序？
