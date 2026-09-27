# 精简版配置方案（tvbox_lite.json）

> 状态：待确认

## 背景与问题陈述

- 当前 tvbox.json 含 4048 sites / 408 lives / 133 parses，体积大（待实测，估计 > 5MB）。
- 车机 / 老盒子 / 低配手机拉这个配置会慢，且内存吃紧。
- 需要一份"top N 精选"精简版，体积控制在 ~500KB，覆盖主流需求即可。

## 方案设计

### 12.1 筛选标准

| 类别 | 数量 | 筛选依据 |
| --- | --- | --- |
| sites | top 500 | 按 ranking-scoring 综合分排序取前 500 |
| lives | top 100 | 按 live 探针成功率排序取前 100 |
| parses | top 20 | 按解析成功率排序取前 20 |

### 12.2 体积控制

目标 ≤ 500KB：
- 500 sites × 平均 ~500B = 250KB
- 100 lives × 平均 ~300B = 30KB
- 20 parses × 平均 ~200B = 4KB
- 头尾 + group 信息 ≈ 50KB
- 余量 ~160KB 缓冲

若超 500KB，优先砍 lives，再砍 parses，最后砍 sites。

### 12.3 更新同步机制

- 每日 CI 主流程产出 tvbox.json 后，跑 `scripts/build_lite.py` 从 tvbox.json 里筛 top N。
- 不单独维护筛选逻辑，主配置更新即 lite 同步更新。

## 影响评估

| 面 | 影响 |
| --- | --- |
| 仓库体积 | 多一份 tvbox_lite.json（~500KB） |
| CI 时长 | < 2s |
| 用户端 | 低配设备可用 lite；高端设备继续用全量 |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：写 `scripts/build_lite.py`，从 tvbox.json 筛 top N，输出 tvbox_lite.json。
2. **阶段 2**：实测 lite 体积是否 ≤ 500KB；不达标调 N。
3. **阶段 3**：在低配设备实测流畅度。

## 回滚方案

- 删 build_lite.py 调用即停止产出 lite。
- lite 是派生文件，不影响主产物。

## 需用户确认的决策点

1. top 500 sites / 100 lives / 20 parses 是否合适？
2. 体积上限 500KB 是否合适？
3. lite 版是否也分标准版/增强版两份？还是只出一份标准版？
