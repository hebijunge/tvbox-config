# 加权综合分排序方案（替代 tuple 排序）

> 状态：待确认

## 背景与问题陈述

- 当前 `tvbox.ranked.json` 的排序是 tuple 排序：按固定字段依次比较（例如先 avail 再 latency 再 ...），硬编码在 fetch_merge.py 里。
- tuple 排序的问题：硬权重、无法调参、不同维度量纲不一致（avail 是 0~1、latency 是 ms）直接比较，量纲大的维度会主导结果。
- 需要一个归一化加权综合分，权重可配。

## 方案设计

### 7.1 综合分公式

```
score = w1 * avail_rank_inv
      + w2 * latency_norm
      + w3 * stability
      + w4 * richness
      + w5 * freshness
      + w6 * group_confidence
```

| 维度 | 含义 | 归一化方式 |
| --- | --- | --- |
| avail_rank_inv | 可用性排名倒数 | 排名越靠前分越高：`1 - rank/total` |
| latency_norm | 延迟（越小越好） | `1 - (latency_ms - min) / (max - min)`，截断到 [0,1] |
| stability | 稳定性（历史成功率） | 直接 0~1 |
| richness | 内容丰富度（影片数 / 分类数） | min(normalize, 1.0) |
| freshness | 更新新鲜度 | `exp(-days_since_update/30)` |
| group_confidence | 分类置信度 | 词表匹配强度，0~1 |

### 7.2 权重环境变量

```yaml
# CI env
RANK_WEIGHTS: "avail=0.30,latency=0.15,stability=0.20,richness=0.15,freshness=0.10,group=0.10"
```

脚本启动时 parse 字符串，缺省权重用内置默认。调权重无需改代码，改 CI 环境变量即可。

默认权重：
| 维度 | w |
| --- | --- |
| avail_rank_inv | 0.30 |
| stability | 0.20 |
| latency_norm | 0.15 |
| richness | 0.15 |
| freshness | 0.10 |
| group_confidence | 0.10 |

### 7.3 与 tuple 排序对比

| 维度 | tuple 排序 | 加权综合分 |
| --- | --- | --- |
| 权重 | 隐式（字段顺序） | 显式可配 |
| 量纲 | 不统一 | 全部归一化到 [0,1] |
| 调参 | 改代码 | 改环境变量 |
| 结果可解释性 | 低（为什么 A 在 B 前？） | 高（每维贡献可打印） |

### 7.4 回滚（--legacy）

```bash
python scripts/rank_sites.py --legacy   # 走旧 tuple 排序
python scripts/rank_sites.py            # 走新加权综合分
```

CI 里加 `RANK_LEGACY=1` 环境变量一键切回。

## 影响评估

| 面 | 影响 |
| --- | --- |
| tvbox.json 顺序 | 会变（用户前 N 个源可能换） |
| CI 时长 | 多一步归一化+加权，< 2s |
| 可调性 | 大幅提升 |
| 风险 | 权重不当会把差源排前面；--legacy 兜底 |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：写 `scripts/rank_sites.py`，同时产出 `tvbox.ranked.json`（新算法）和 `tvbox.ranked.legacy.json`（旧算法）。
2. **阶段 2**：人工对比 top-100 排序差异，确认新算法合理。
3. **阶段 3**：新算法切为默认，旧算法保留 `--legacy` 入口。

## 回滚方案

- `RANK_LEGACY=1` 环境变量切回 tuple 排序。
- 旧排序逻辑不删，保留在 `rank_sites.py` 里。

## 需用户确认的决策点

1. 默认权重是否接受（0.30/0.20/0.15/0.15/0.10/0.10）？
2. latency_norm 的 min/max 是用全局还是 per-group？
3. group_confidence 这个维度是否必要？还是先去掉？
