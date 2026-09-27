# 上游级去重方案（配置指纹 + Jaccard 相似度）

> 状态：待确认

## 背景与问题陈述

- 当前去重是**站点级**的：同一个 url 的站点只保留一份。
- 但上游之间经常是**整包重复**：A 上游和 B 上游整体 80% 站点相同，只是名字略改。站点级去重识别不出这种"整包双胞胎"。
- 整包重复会让 tvbox.json 体积虚高，且探针浪费在重复站点上。

## 方案设计

### 4.1 配置内容指纹（归一化 sha256）

对每个上游配置做归一化后取 sha256：

```python
def fingerprint(upstream_config):
    # 1. 只保留 sites 数组，按 site.key 排序
    sites = sorted(upstream_config.get("sites", []), key=lambda s: s["key"])
    # 2. 每个 site 只保留稳定字段（name/url/type/spider），剔除可能变动的备注/ext 里的时间戳
    normalized = [
        {"key": s["key"], "name": s["name"], "url": s["url"], "type": s.get("type")}
        for s in sites
    ]
    # 3. sha256
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
```

- 完全相同的上游 → 相同指纹 → 直接标 duplicate。
- 字段轻微差异（name 改字、ext 多一项）→ 指纹不同，但 Jaccard 仍高。

### 4.2 站点集合 Jaccard 相似度

```python
def jaccard(a_sites, b_sites):
    A = {s["key"] for s in a_sites}
    B = {s["key"] for s in b_sites}
    return len(A & B) / len(A | B) if (A | B) else 0.0
```

对所有上游两两计算 Jaccard（N=上游数，O(N²)，目前上游数 < 50，可接受）。

### 4.3 标记策略

| 指纹 | Jaccard | 处置 |
| --- | --- | --- |
| 完全相同 | 1.0 | 自动标 duplicate_of，保留评分高的那个 |
| 不同 | > 0.8 | 标 `suspected_duplicate`，进人工 review 队列 |
| 不同 | 0.5 ~ 0.8 | 记录相似度，不自动处置 |
| 不同 | < 0.5 | 无 |

### 4.4 误杀防护

- 人工标记 `manual_keep=true` 的上游，即使 Jaccard > 0.8 也不自动去重。
- 保留哪个：选 upstream-evaluation 分数高的；同分则选更新时间更近的。
- 被标记 duplicate 的上游不直接删除，而是 `disabled=true`，tvbox.json 里不产出，但 `state/upstreams/` 里保留记录可恢复。

## 影响评估

| 面 | 影响 |
| --- | --- |
| tvbox.json 体积 | 预计减少 10~20%（去重整包双胞胎） |
| 探针时长 | 重复站点不再重复 probe，CI 总时长下降 |
| 误杀风险 | >0.8 才自动，0.5~0.8 仅记录；人工 keep 标记兜底 |
| 计算开销 | N² 两两比较，N<50 时 < 1s |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：写 `scripts/upstream_dedup.py`，输出 `exports/upstream_similarity.json`（矩阵，仅观察）。
2. **阶段 2**：人工 review top 高相似对，确认是否真重复。
3. **阶段 3**：开启自动标记 `duplicate_of`，但不实际禁用（dry-run）。
4. **阶段 4**：确认无误杀后，自动禁用低分项。

## 回滚方案

- `DEDUP_DRY_RUN=1` 切回只标记不处置。
- 误禁用的上游：手动改 `disabled=false` 即可。

## 需用户确认的决策点

1. Jaccard 阈值 0.8 是否合适？调高到 0.9 更保守。
2. 人工 keep 标记怎么录入？（候选：`state/upstreams/manual_keep.json` 名单）
3. 被去重的上游是否完全从 tvbox.json 移除，还是保留但降权？
