# 多版本输出方案（标准版 / 增强版）

> 状态：待确认

## 背景与问题陈述

- 不同 TVBox 客户端分支对字段格式容忍度不同：
  - 老分支要求 `ext` 是 string，`spider` 是裸 url。
  - 新分支支持 `ext` 是 dict（结构化配置），`spider` 支持 `url;md5` 格式校验。
- 单份 tvbox.json 无法同时满足：给标准版塞 dict 会让老客户端崩；给增强版塞 string 又浪费了结构化能力。

## 方案设计

### 11.1 双产物

| 文件 | 定位 | ext 格式 | spider 格式 | group 名长度 |
| --- | --- | --- | --- | --- |
| `tvbox.json`（标准版） | 兼容所有分支 | **必须 string** | **裸 url**（无 ;md5; 后缀） | < 50 字符 |
| `tvbox_pro.json`（增强版） | 新分支 | 保留 dict | `url;md5` | 不限 |

### 11.2 生成方式

CI 末尾从内部结构化数据 `state/sites.normalized.json` 一次性渲染两份：
- 标准版渲染器：ext dict → JSON.stringify 成 string；spider 字段剥离 `;md5;` 段；group 名截断到 50 字符。
- 增强版渲染器：原样输出 ext dict，spider 保留 `;md5;`。

### 11.3 主流分支字段支持差异（待实测补全）

| 分支 | ext 类型 | spider ;md5; | 长 group |
| --- | --- | --- | --- |
| TVBox 原版 | string only | 支持 | 支持 |
| TVMe | dict 支持 | 支持 | 待实测 |
| 秋英 | 待实测 | 待实测 | 待实测 |
| 其它 fork | 待实测 | 待实测 | 待实测 |

### 11.4 兼容性测试方法

- 写一个 `tests/compat_matrix.py`，用真实客户端 APK（或自动化 mock）对两份产物分别跑：
  - 能否解析 JSON
  - 能否加载前 100 个 site
  - 能否搜索一个关键词
- 结果落 `exports/compat_matrix.json`。

## 影响评估

| 面 | 影响 |
| --- | --- |
| 仓库体积 | 多一份 tvbox_pro.json（约等于 tvbox.json 大小） |
| CI 时长 | 多一次渲染，< 2s |
| 用户端 | 老用户继续用 tvbox.json；新客户端用户可换 tvbox_pro.json |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：写两个渲染器，先产出 tvbox_pro.json 副本，不替换 tvbox.json。
2. **阶段 2**：在不同客户端实测 tvbox_pro.json。
3. **阶段 3**：确认标准版渲染器不破坏现有 tvbox.json（字节级 diff 应仅在 ext/spider 字段）。

## 回滚方案

- `PRO_BUILD=0` 环境变量不生成 tvbox_pro.json。
- 标准版渲染器出问题：直接用增强版原产物作为 tvbox.json。

## 需用户确认的决策点

1. 增强版文件名 `tvbox_pro.json` 是否接受？
2. group 名 50 字符上限是否合适？
3. 是否需要第三份"极简版"（见 lite-config）？还是 lite 单独方案？
