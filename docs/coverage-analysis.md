# 覆盖度缺口分析方案

> 状态：待确认

## 背景与问题陈述

- 当前 tvbox.json 有 4048 个 sites，但"数量多"不等于"覆盖好"。
- 用户实际需求是按品类找片：电影、剧、综艺、动漫、纪录片、体育——可能某一类源已经泛滥，另一类只有 2 个源。
- 需要量化"每个品类/地域/语言/源类型"的覆盖情况，找出缺口，再定向补源。

## 方案设计

### 5.1 统计维度

| 维度 | 取值示例 |
| --- | --- |
| 品类 | 电影 / 剧集 / 综艺 / 动漫 / 纪录片 / 体育 / 少儿 / 其他 |
| 地域 | 大陆 / 港 / 台 / 欧美 / 日韩 / 东南亚 / 其他 |
| 语言 | 中文 / 英语 / 日语 / 韩语 / 其他 |
| 源类型 | CMS(type=1) / 聚合(type=3) /  spider(jar) / drpy / JS / 直播 |

每个站点按多标签打标（一个源可能同时覆盖电影+剧、大陆+港）。

### 5.2 分类词表设计

`config/category_vocab.json`：
```json
{
  "movie":  {"keywords": ["电影", "影院", "film", "movie"], "weight": 1.0},
  "series": {"keywords": ["电视剧", "剧集", "连续剧", "tv"], "weight": 1.0},
  "variety":{"keywords": ["综艺", "真人秀", "variety"], "weight": 1.0},
  "anime":  {"keywords": ["动漫", "动画", "anime"], "weight": 1.0},
  "doc":    {"keywords": ["纪录", "documentary"], "weight": 1.0},
  "sport":  {"keywords": ["体育", "直播", "sport"], "weight": 1.0}
}
```

打标规则：site.name / group 字段命中关键词 → 打对应品类标签；多命中则多标签。

地域/语言词表同理（`region_vocab.json` / `language_vocab.json`）。

### 5.3 缺口判定阈值

| 品类 | 优质源最低数 | 缺口判定 |
| --- | --- | --- |
| 电影 | ≥ 30 | < 15 即缺口 |
| 剧集 | ≥ 30 | < 15 即缺口 |
| 综艺 | ≥ 10 | < 5 即缺口 |
| 动漫 | ≥ 10 | < 5 即缺口 |
| 纪录片 | ≥ 5 | < 2 即缺口 |
| 体育 | ≥ 5 | < 2 即缺口 |

"优质源"= upstream-evaluation 评分 ≥ 60 的源。

### 5.4 定向发现关键词

发现缺口后，输出 `exports/coverage_gaps.json`：
```json
{
  "gaps": [
    {"category": "documentary", "current": 1, "target": 5,
     "search_keywords": ["纪录片 CMS", "documentary movie site", "纪录片采集"]}
  ]
}
```

这些关键词供人工/自动化去 GitHub 搜新上游（`site:github.com tvbox 纪录片`）。

## 影响评估

| 面 | 影响 |
| --- | --- |
| CI 时长 | 多一步统计，< 5s |
| 产物 | tvbox.json 不变；多一个 `exports/coverage_report.json` 供人看 |
| 误判 | 词表命中可能漏标，靠人工 review 修正 |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：写词表 `config/category_vocab.json`，先粗后细。
2. **阶段 2**：写 `scripts/coverage_analyze.py`，对现有 tvbox.json 跑一遍，输出报告。
3. **阶段 3**：人工 review 报告，看是否符合直觉；调整词表。
4. **阶段 4**：把缺口列表喂给上游发现流程（候选：weekly job 自动搜 GitHub）。

## 回滚方案

- 纯分析脚本，不影响产物；随时可删。
- 词表误标：改词表即可，不影响已产出的 tvbox.json。

## 需用户确认的决策点

1. 品类词表是否接受上面 6 类？要不要加少儿/音乐/MV？
2. 地域维度是否必要？还是先只做品类+源类型两维？
3. 缺口补源是自动搜 GitHub，还是只输出报告人工找？
