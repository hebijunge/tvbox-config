# 源类型多样性保障方案

> 状态：待确认

## 背景与问题陈述

- TVBox 站点按实现方式分几大类：CMS（type=1，自带 API）、聚合（type=3）、spider（jar 包）、drpy（py 脚本）、JS、直播（m3u）。
- 过度依赖单一源类型有风险：比如 spider 类如果集体被封，整片源就废了。
- 需要对每类源设最低"优质上游数"下限，不足时定向补。

## 方案设计

### 6.1 最低优质上游数下限

| 源类型 | 最低优质上游数 | 说明 |
| --- | --- | --- |
| CMS (type=1) | ≥ 10 | 最稳，量大 |
| 聚合 (type=3) | ≥ 5 | 依赖 CMS，自身轻量 |
| Spider (jar) | ≥ 10 | drpy-sandbox 跑，依赖 deps/ |
| drpy (py) | ≥ 5 | 脚本化，灵活 |
| JS | ≥ 10 | 轻量，启动快 |
| 直播 (m3u) | ≥ 5 | 独立维度，见 live-vod-parallel |

"优质"= upstream-evaluation 评分 ≥ 60。

### 6.2 不足时的定向搜索

每日 CI 末尾跑 `scripts/diversity_check.py`：
- 统计当前各类优质上游数。
- 若某类 < 下限，输出告警到 `exports/diversity_alert.json`，并开 GitHub issue（或复用现有关键指标下降告警通道）。
- 候选搜索关键词：
  - CMS：`tvbox cms 采集`、`苹果cms 资源`
  - Spider：`tvbox spider jar 2026`
  - drpy：`drpy 源 仓库`
  - JS：`tvbox js 源`

### 6.3 与 coverage-analysis 的关系

- coverage-analysis 看"品类缺口"（电影/剧/...）。
- source-type-diversity 看"类型缺口"（CMS/spider/...）。
- 两者正交，交叉后才能定位"哪个品类缺哪种类型的源"。

## 影响评估

| 面 | 影响 |
| --- | --- |
| CI 时长 | < 5s |
| 产物 | tvbox.json 不变；多一个告警文件 |
| 补源压力 | 告警是软提醒，不自动加源 |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：写 `scripts/diversity_check.py`，只统计不告警。
2. **阶段 2**：人工 review 一周数据，确定合理下限。
3. **阶段 3**：开启告警（issue 或 console.warn）。

## 回滚方案

- 纯监控脚本，删即回滚。

## 需用户确认的决策点

1. 各类下限是否接受？（CMS≥10 / spider≥10 / JS≥10 / 聚合≥5 / drpy≥5 / 直播≥5）
2. 告警走 issue 还是只写文件？
3. 是否需要"自动补源"，还是只告警人工处理？
