# 上游自动晋升 / 降级闭环方案

> 状态：待确认

## 背景与问题陈述

- `state/canary/` 当前已有 canary 池概念（iptv-org 适配器已落地），但缺一套通用的"canary → 正式 → 降级 → 黑名单"生命周期。
- 上游会随时间变质：今天好的，半年后可能挂；今天差的，修复后可能变好。
- 需要自动化闭环，避免人工 review 每个上游的每日状态。

## 方案设计

### 3.1 状态机

```
                ┌──────────────────────────────┐
                ▼                              │
[new] ──观察期──> [canary] ──连续7天达标──> [stable]
                │                              │
                │                              ├──连续14天失败率>50%──> [canary]
                │                              │
                │                              └──连续30天不可达──> [blacklist]
                │
                └──连续21天未达标──> [blacklist]
```

状态枚举：`new / canary / stable / blacklist`。

### 3.2 晋升规则（canary → stable）

```python
def should_promote(entry, history):
    # 条件 1：在 canary 池至少 7 天
    if days_since(entry.canary_since) < 7:
        return False
    # 条件 2：连续 7 天探针成功率 >= 80%
    recent = history[-7:]
    if len(recent) < 7:
        return False
    success_rate = sum(p.success for p in recent) / len(recent)
    if success_rate < 0.8:
        return False
    # 条件 3：无连续 2 天失败
    for i in range(1, len(recent)):
        if not recent[i].success and not recent[i-1].success:
            return False
    return True
```

### 3.3 降级规则（stable → canary）

```python
def should_demote(entry, history):
    recent = history[-14:]
    if len(recent) < 14:
        return False
    fail_rate = sum(1 for p in recent if not p.success) / len(recent)
    return fail_rate > 0.5   # 连续 14 天失败率 > 50%
```

降级后回到 canary 池，重新走晋升流程；30 天内不重复降级（避免抖动）。

### 3.4 黑名单规则

```python
def should_blacklist(entry, history):
    recent = history[-30:]
    if len(recent) < 30:
        return False
    return all(not p.success for p in recent)   # 连续 30 天不可达
```

黑名单后从 `state/upstreams/` 移除，写入 `state/upstreams/blacklist.json`；90 天后自动从黑名单移除，重新进 new 观察期（防止上游修复后永远无法回归）。

### 3.5 promotion_log.jsonl 格式

```jsonl
{"date":"2026-09-27","upstream":"example.com/xyz","from":"canary","to":"stable","reason":"7d success_rate=0.92","score":78.2}
{"date":"2026-09-27","upstream":"old.example.com","from":"stable","to":"canary","reason":"14d fail_rate=0.57","score":38.1}
{"date":"2026-09-27","upstream":"dead.example.com","from":"canary","to":"blacklist","reason":"30d unreachable","score":5.0}
```

每日一行，append-only；用于事后追溯"为什么这个上游被踢了"。

### 3.6 与 upstream-evaluation 的关系

- evaluation 算分数（瞬时），promotion 看历史（连续窗口）。
- 两者互补：evaluation 决定"新上游从哪起步"，promotion 决定"老上游怎么流转"。

## 影响评估

| 面 | 影响 |
| --- | --- |
| CI 时长 | 多一步状态机评估，< 10s |
| 上游数量 | 稳定后进出平衡，总数波动 < 5% |
| 误升降级 | 晋升门槛高（7 天连续 80%），误晋升概率低；降级有 14 天窗口缓冲 |
| 人工干预 | 黑名单 90 天自动复活，避免永久误杀 |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：写 `scripts/upstream_lifecycle.py`，状态机纯函数化，单测覆盖。
2. **阶段 2**：每日 CI 末尾跑一次 lifecycle 评估，结果写 `promotion_log.jsonl`，但**不实际流转**（dry-run）。
3. **阶段 3**：观察 14 天日志，人工 review 升降级是否合理。
4. **阶段 4**：开启实际流转（写 `state/upstreams/`）。

## 回滚方案

- `LIFECYCLE_DRY_RUN=1` 环境变量可随时切回 dry-run。
- 状态机数据都在 `state/upstreams/*.json`，备份一份出问题直接还原。
- 黑名单误杀：手动从 `blacklist.json` 删除对应条目即可。

## 需用户确认的决策点

1. 晋升窗口 7 天 / 降级窗口 14 天 / 黑名单 30 天，是否接受？
2. 晋升成功率阈值 80%、降级失败率阈值 50%，是否合理？
3. 黑名单 90 天自动复活是否合适？还是希望永久拉黑人工 review？
