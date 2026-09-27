# 分支兼容性校验方案

> 状态：待确认

## 背景与问题陈述

- 当前 `config_validate.py` 只校验 JSON 结构合法性，不校验"字段格式是否兼容主流 TVBox 分支"。
- 已经出过 ext 用 dict 导致老客户端崩的事故（或潜在风险）。
- 需要在标准版产出前，自动做字段格式校验 + 自动转换。

## 方案设计

### 14.1 标准版字段格式规则

```python
RULES = {
    "ext_must_be_string": True,     # ext 字段必须是 string，不能是 dict
    "spider_no_md5_suffix": True,   # spider 字段不能含 ;md5; 后缀
    "group_max_length": 50,         # group 字段最长 50 字符
    "searchable_in": [0, 1, 2],     # searchable 必须是这三个值之一
    "type_in": [0, 1, 3, 4],        # type 必须是这几个值之一
}
```

### 14.2 校验流程

`config_validate.py` 扩展：
1. 加载产出的 tvbox.json。
2. 遍历所有 sites：
   - `ext` 是 dict → 自动 `json.dumps(ext)` 转 string。
   - `spider` 含 `;md5;` → 截断到 `;` 前。
   - `group` 长度 > 50 → 截断到 50 字符（加告警）。
3. 校验不通过且无法自动修复的，fail CI。

### 14.3 自动转换兼容格式

```python
def normalize_for_standard(site):
    if isinstance(site.get("ext"), dict):
        site["ext"] = json.dumps(site["ext"], ensure_ascii=False)
    if ";" in site.get("spider", ""):
        site["spider"] = site["spider"].split(";")[0]
    if len(site.get("group", "")) > 50:
        site["group"] = site["group"][:50]
    return site
```

### 14.4 与 multi-branch-output 的关系

- multi-branch-output 是"生成两份"，branch-compatibility 是"产出前先校验+规范化"。
- 标准版渲染器直接调用 `normalize_for_standard`，增强版跳过。

## 影响评估

| 面 | 影响 |
| --- | --- |
| CI 时长 | < 2s |
| 产物质量 | 标准版 tvbox.json 保证字段格式合规 |
| 风险 | 自动转换可能丢信息（ext dict → string 后客户端解析行为可能略变） |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：在 `config_validate.py` 加规则校验，仅告警不修改。
2. **阶段 2**：人工 review 告警，确认规则合理。
3. **阶段 3**：开启自动转换。

## 回滚方案

- `COMPAT_STRICT=0` 仅告警不 fail。
- 自动转换函数出问题：跳过 normalize，直接用原始字段。

## 需用户确认的决策点

1. group 长度上限 50 字符是否合适？
2. ext dict → string 自动转换是否可接受？还是宁可 fail 让人工处理？
3. 是否需要把规则也写进 README 让上游贡献者知道？
