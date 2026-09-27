# 优化前基线指标（2026-09-27）

## 配置文件体积
| 文件 | 大小(bytes) | 大小(KB) |
|------|------------|----------|
| tvbox.json | 1569630 | 1532.84 |
| vod.json | 1476964 | 1442.35 |
| live.json | 213 | 0.21 |
| short.json | 111974 | 109.35 |
| adult.json | 39426 | 38.50 |
| list.json | 93178 | 90.99 |
| status.json | 713366 | 696.65 |
| wogg.json | 24711 | 24.13 |
| checks.json | 96433 | 94.17 |

## stores/ 子仓
| 文件 | 大小(bytes) |
|------|------------|
| stores/csp.json | 1206237 |
| stores/csp_proxy.json | 295733 |
| stores/cms.json | 89768 |
| stores/cms_proxy.json | 68070 |
| stores/pan.json | 169539 |
| stores/pan_proxy.json | 82704 |
| stores/app.json | 39296 |
| stores/app_proxy.json | 35163 |

## 源数量
| 指标 | 数值 |
|------|------|
| tvbox.json sites | 3504 |
| tvbox.json lives | 408 |
| tvbox.json parses | 133 |
| vod.json sites | 3504 |
| short.json sites | 101 |
| adult.json sites | 104 |

## 内部字段
- sites 中唯一内部字段: `_origin`（3504个，占总字段10%）
- lives 中无内部字段

## 依赖
| 指标 | 数值 |
|------|------|
| deps/ 总大小 | 366.07 MB |
| deps/ 文件数 | 3271 |

## CI 基线（来自 PRD）
- 构建时间: 90-120 分钟
- CONCURRENCY: 20
- DEP_CONCURRENCY: 16

## 代码规模
- fetch_merge.py: 4165 行
- scripts/: 55 个辅助脚本
- .github/workflows/: 9 个 yml
