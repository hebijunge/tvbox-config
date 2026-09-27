# fetch_merge.py 拆分方案（225KB 单文件模块化）

> 状态：待确认

## 背景与问题陈述

- `scripts/fetch_merge.py` 单文件 225KB，承担了：上游配置抓取、依赖收集、成人内容闸门、站点分类、配置加载、合并写出等多职责。
- 单文件过大导致：review diff 噪声巨大、IDE 索引慢、模块间边界模糊、无法对单一职责写独立单测。
- 已有 `_commit.py` 等独立小脚本的先例，本仓具备模块化拆分的工程基础。

## 方案设计

### 4.1 目标模块划分

| 新文件 | 职责 | 从 fetch_merge.py 抽出的内容 |
| --- | --- | --- |
| `scripts/merge_core.py` | 核心合并循环：上游配置 → 归一化 → 去重 → 写出 tvbox.json | 主 merge 函数、tuple 排序、group 组装 |
| `scripts/dep_collector.py` | 从站点配置里解析 jar/js 依赖、下载到 deps/、写 manifest | jar/js url 提取、下载重试、sha256 校验 |
| `scripts/adult_gate.py` | 成人内容闸门：识别 adult 站点/频道，分流到 adult.json / adult_live.json | host 黑名单、name 关键词、source_marker 判定 |
| `scripts/classifier.py` | 站点分类：电影/剧/综艺/动漫/纪录片/体育 → group 字段 | 品类词表匹配、group 归一化 |
| `scripts/config_loader.py` | 加载上游 JSON、缓存、TTL、错误兜底 | HTTP 抓取、本地缓存、candidate_upstreams.json 读取 |

### 4.2 入口保持兼容

`fetch_merge.py` 瘦身为入口 + re-export：
```python
# scripts/fetch_merge.py（拆分后）
from merge_core import run_merge        # noqa: F401
from dep_collector import collect_deps  # noqa: F401
from adult_gate import gate_adult       # noqa: F401
from classifier import classify_site   # noqa: F401
from config_loader import load_upstream # noqa: F401

if __name__ == "__main__":
    run_merge()
```

外部调用方（CI、`python scripts/fetch_merge.py`）零改动。

### 4.3 文件间依赖图

```
config_loader.py   ← 被所有人依赖（无内部依赖）
       ↑
classifier.py      ← 依赖 config_loader（读品类词表）
       ↑
adult_gate.py      ← 独立（只读 host_blacklist / name_keywords）
       ↑
dep_collector.py   ← 依赖 config_loader（读上游 url）
       ↑
merge_core.py      ← 依赖上面所有
       ↑
fetch_merge.py     ← 入口，re-export
```

**依赖方向严格单向**：底层不允许 import 上层，避免循环。

### 4.4 迁移步骤（机械搬运，不改逻辑）

1. 先 `git mv scripts/fetch_merge.py scripts/fetch_merge.py.bak`（保险，不入库）。
2. 按函数边界切：用 IDE "Move Function to Module" 功能，每次搬一组强相关函数到新文件。
3. 每搬一次跑一次 `python -c "import scripts.fetch_merge"` 确保 import 链不断。
4. 全部搬完后跑 `python scripts/fetch_merge.py --dry-run` 对比拆分前后 `tvbox.json` 字节级 diff（**必须零 diff**，这是底线）。
5. 写 `tests/test_merge_core.py` / `tests/test_adult_gate.py` 等模块级单测。

## 影响评估

| 面 | 影响 |
| --- | --- |
| CI 行为 | 零变化（入口签名不变） |
| 仓库体积 | 脚本总行数不变，单文件从 225KB 拆成 5~6 个 ~30KB 文件 |
| 维护性 | 分类器改逻辑只动 classifier.py，review 范围缩小 |
| 风险 | 机械搬运过程中漏 import 会直接 fail-fast，CI 兜底 |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：建 5 个空模块文件，仅做 `from x import *` 转发，跑通 dry-run。
2. **阶段 2**：每次搬一个职责块（建议顺序：config_loader → classifier → adult_gate → dep_collector → merge_core），每搬一次跑 dry-run + 单测。
3. **阶段 3**：补模块级单测覆盖率到主干关键路径。
4. **阶段 4**：删除 `fetch_merge.py.bak`。

## 回滚方案

- 任一阶段失败：`git revert` 拆分 commit；`.bak` 文件保留到阶段 4 才删，期间可随时恢复。
- dry-run 出现非零 diff：立刻回滚到上一个拆分 commit，重审搬运过程。

## 需用户确认的决策点

1. 是否接受拆成 5 个模块？还是希望更粗粒度（比如只拆成 `fetch_merge/` 包 + 3 个文件）？
2. 模块名是否沿用本方案建议（merge_core / dep_collector / adult_gate / classifier / config_loader）？
3. 是否在本次拆分同时做逻辑优化？建议**纯机械拆分 + 零逻辑改动**，优化单独立项。
