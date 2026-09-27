# 上游多维评分收编方案

> 状态：待确认

## 背景与问题陈述

- 当前 `candidate_upstreams.json` 收编逻辑较粗：主要靠"是否能拉到 JSON + 字段是否齐"这种二值判定。
- 上游质量参差：有的站点 100% 可用，有的半挂；有的每天更新，有的半年不动；有的夹带大量成人内容；有的配置字段可疑（比如 spider 路径指向奇怪 jar）。
- 需要一个**连续评分**替代二值收编，让"边缘可用"的上游进 canary 而不是直接拒。

## 方案设计

### 2.1 评分公式

```
score = 0.30 * uniqueness       # 独有站点数（该上游独有的站点占比）
      + 0.30 * availability     # 实测可用率（最近 7 天探针通过率）
      + 0.15 * freshness         # 更新频率（commit/抓取时间新鲜度）
      + 0.10 * deps_integrity    # 依赖完整性（jar/js 是否都能下到）
      + 0.10 * adult_ratio_inv   # 成人比例反向（1 - adult_ratio）
      + 0.05 * config_sane_inv   # 配置可疑度反向（字段是否规范）
```

各维度归一化到 `[0, 1]`：

| 维度 | 归一化方式 |
| --- | --- |
| uniqueness | 该上游独有站点数 / 全部上游总站点数；cap 1.0 |
| availability | 最近 7 天 probe 成功次数 / 总 probe 次数 |
| freshness | `exp(-days_since_last_update / 30)`，30 天前衰减到 ~0.37 |
| deps_integrity | 已下载成功的依赖数 / 声明依赖总数 |
| adult_ratio_inv | `1 - adult_sites / total_sites`，避免高分上游夹带大量成人 |
| config_sane_inv | 配置字段校验通过率（url 合法、spider 非空、ext 类型正确等） |

### 2.2 三级阈值

| 分数 | 级别 | 处置 |
| --- | --- | --- |
| ≥ 70 | 正式收编 | 直接并入 `state/upstreams/`，每日正常跑 |
| 40 ~ 70 | canary | 进 canary 池，不直接进 tvbox.json，观察 7 天 |
| < 40 | 仅监控 | 记录到 `state/upstreams/watchlist.json`，不产出站点，每周复盘一次 |

### 2.3 与现有 unique 收编对比

| 维度 | 现有 unique 收编 | 新方案 |
| --- | --- | --- |
| 判定粒度 | 二值（独有 / 重复） | 连续分数 |
| 边缘上游 | 直接拒 | 进 canary 观察 |
| 成人夹带 | 靠 adult_gate 硬拦 | 评分里直接扣分 |
| 更新不频繁 | 不感知 | freshness 维度扣分 |
| 依赖缺失 | 不感知 | deps_integrity 维度扣分 |

### 2.4 测试方法

- 用过去 30 天的历史探针数据回放：把每个上游的 availability/freshness 算出来，人工 review top-20 / bottom-20 分数是否合理。
- 边界 case：新上游（无历史）默认 availability=0.5，进 canary 不进正式。
- 权重调参：先按上表权重上线，跑 2 周后看分布（期望 70+ 占 20%、40-70 占 50%、<40 占 30%），若分布畸高/畸低再调。

## 影响评估

| 面 | 影响 |
| --- | --- |
| 上游数量 | canary 池会变大（预计 +50~200 个边缘上游），state/ 体积略增 |
| CI 时长 | 多一步评分计算，预计 < 30s |
| 产物质量 | 高分上游权重更高，低分上游被过滤，tvbox.json 整体可用率上升 |
| 误杀风险 | 新上游无历史数据，可能被 freshness 误判低分；用 canary 缓冲 |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：写 `scripts/upstream_score.py`，离线跑一遍现有 candidate_upstreams.json，输出 `exports/upstream_scores.json`（不入产物，仅观察）。
2. **阶段 2**：人工 review 分布，调权重。
3. **阶段 3**：把评分结果接入收编决策——≥70 正常收编，40-70 进 canary，<40 进 watchlist。
4. **阶段 4**：连续观察 14 天。

## 回滚方案

- 评分模块独立，`.github/workflows/daily.yml` 里加环境变量 `UPSTREAM_SCORING=0` 即可切回旧 unique 收编逻辑。
- canary / watchlist 数据落在 `state/upstreams/`，删除对应文件即回滚。

## 需用户确认的决策点

1. 权重配比是否接受（0.30/0.30/0.15/0.10/0.10/0.05）？
2. 三级阈值 70/40 是否合理？
3. <40 的上游是"完全忽略"还是"每周扫一次重新评分"？
