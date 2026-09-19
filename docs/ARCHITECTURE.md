# TVBox 接口聚合 · 架构与运行手册

主线：**每日搜集全网接口 → 汇总去重分类 → 实测 → 依赖入库 → 导出接口文件**。
本文说明项目结构、模块职责、数据模型、调度策略，以及五个环节的实现方案与可靠性设计。

---

## 1. 总体流程

```
 ┌─ 采集 ─┐   ┌─ 汇总 ─┐   ┌─ 实测 ─┐   ┌─ 入库 ─┐   ┌─ 导出 ─┐
 四路发现    拉取合并     HTTP L1-3    SQLite     全部/健康
 独有度评估  三级去重     type3 连通   接口+检测   可用/按类型
 canary 收编 依赖落库     csp 真机五关 依赖+上游   健康索引
             分类排序     drpy 沙箱五关
 └────────────────────────────────────────────────────────────┘
      ↑______________ 探针吃上一轮产物（一轮延迟自洽）______________↓
```

设计上的一个关键取舍：**实测在合并之前跑，吃的是上一轮产物**。
因为探针需要 `tvbox.json` 才能测，而合并又需要探针结论——一轮延迟即可自洽，避免鸡生蛋问题。

---

## 2. 项目结构

```
tvbox-config/
├── scripts/                      全部流程脚本（见 §3）
├── probe/                        实测产物：sites/spider/js/csp/drpy_probe.json
│                                 （CI 只读复用，不重复跑真机/沙箱）
├── radar/                        采集产物：discovered.json（候选池）
│                                          candidate_eval.json（独有度评估）
├── state/                        运行状态：extra_upstreams.json（canary）
│                                          mirror_groups.json / sites_state.json
│                                          blacklist_auto.txt / tvbox.db（不入库）
├── drpy-sandbox/                 drpy Node 沙箱（已入库，CI 每日跑）
│                                 host.mjs + drpy2.min.js + drpy-core-lite.min.js + package.json
├── exports/                      导出清单（TVBox 可直接导入）
├── deps/                         依赖落库：jar / js / json，按上游分目录
├── snapshot/                     14 天快照（可回滚）
├── stores/                       分类分发：app / cms / csp / pan …
├── lives/                        直播源聚合结果
└── .github/workflows/daily.yml   每日调度
```

---

## 3. 核心模块职责

| 模块 | 环节 | 职责 | 输入 → 输出 |
|---|---|---|---|
| `discover_upstreams.py` | 采集 | 四路发现：代码搜索 / 仓库搜索(topic) / 种子 README 递归 / **血统反查** | GitHub API → `radar/discovered.json` |
| `evaluate_candidates.py` | 采集 | 算「独有站点数」，按 unique 收编 canary | 候选池 + tvbox.json → `state/extra_upstreams.json` |
| `fetch_merge.py` | 汇总 | 拉取 49 上游、字节/条目双门槛、三级去重、分类、依赖落库 | 上游 → `tvbox.json` / `vod/short/live.json` / `deps/` |
| `dedup_mirrors.py` | 去重 | 同库换域名镜像识别（片名集合 Jaccard） | → `state/mirror_groups.json` |
| `probe_sites.py` | 实测 | HTTP 型 L1 分类 / L2 搜索 / L3 取链播放（支持 XML） | → `probe/sites_probe.json` |
| `probe_spiders.py` | 实测 | type3 源真实地址连通性 | → `probe/spider_probe.json` |
| `probe_js.py` | 实测 | JS 分类页实测 | → `probe/js_probe.json` |
| *(外部)* csp 真机 | 实测 | 682 个 csp 爬虫源五关（root 真机） | → `probe/csp_probe.json` |
| `drpy_probe.py` + `drpy-sandbox/` | 实测 | 270 个本地 JS 源五关（Node 沙箱，**已接入 CI 每日跑**） | → `probe/drpy_probe.json` |
| *(外部)* csp 真机 | 实测 | 682 个 csp 爬虫源五关（root 真机，手工产出） | → `probe/csp_probe.json` |
| `rank_sites.py` | 分类 | 写 group、校正 searchable、按 分类→可搜→档位→速度 排序 | → `tvbox.ranked.json` |
| `store.py` | 入库 | SQLite：接口/检测历史/依赖/上游，幂等 upsert | → `state/tvbox.db` |
| `export_healthy.py` | 导出 | 全部 / 健康 / 可用 / 按类型 / 健康索引 | → `exports/*.json` |
| `health_report.py` | 观测 | 与快照对比，算新增 / 掉线 / 恢复 / 移除（点播+直播） | → `exports/health_report.json` + 快照 |
| `dep_audit.py` | 观测 | deps/ 重复与未引用分析（**只报告不删**） | → `state/dep_audit.json` |
| `store.py --probe-lives` | 实测 | 直播源连通性（拉源地址看是否返回频道列表） | → `lives.health` |

---

## 4. 数据模型（SQLite，`state/tvbox.db`）

| 表 | 主键 | 关键字段 | 用途 |
|---|---|---|---|
| `interfaces` | `key` | name, api, type, ext, jar, group_name, source, first_seen, last_seen, last_check_at, **health**, latency_ms, level, reason, health_rank, fail_streak | 接口当前态 |
| `checks` | 自增 | key, checked_at, ok, status_code, latency_ms, level, reason, probe | **检测历史**（追加，滚动保留 30 天） |
| `deps` | key+dep_type+dep_ref | local_path, md5, upstream | 依赖关系：jar / ext 文件 / 本地 js / 全局 spider |
| `upstreams` | url | ok, sites_count, new_sites, fail_streak | 上游健康 |
| `runs` | 自增 | stage, started_at, ended_at, ok, note | 运行日志 |

**健康分级**：`healthy`（实测能搜/能播：L3 / C3+ / D3+）> `degraded`（能连通但能力弱）> `unknown`（未测或超时，不妄判）> `dead`（实测失败：C0 / D0 / L0）。

**探针权威性（关键）**：一个源会被多路探针各测一次，深度差别很大。
`health_rank` 记录判定来源的优先级（csp/drpy 五关=4 > HTTP L级=3 > js S级=2 > spider 连通性=1）。
**浅探针的结论不能覆盖深探针**——否则会出现「五关全通的源被连通性探针判 dead」的荒谬结果。

---

## 5. 调度策略（daily.yml，每日 03:00 CST + 手动触发）

| # | 阶段 | 脚本 | 失败处理 |
|---|---|---|---|
| 1 | 镜像测速择优 | `mirror_probe.py` | 失败回退默认镜像序 |
| 2 | 实测（吃上一轮） | `probe_sites/spiders/js` + `dedup_mirrors` | `continue-on-error` |
| 3 | 发现 + 评估收编 | `discover_upstreams.py` → `evaluate_candidates.py` | 同上（**顺序不可颠倒**） |
| 4 | 汇总合并 | `fetch_merge.py` | 必须成功 |
| 5 | 入库 | `store.py --ingest-sites/--ingest-lives/--probe-lives/--ingest-probes --prune --stats` | 同上 |
| 6 | 导出 | `export_healthy.py` | 同上 |
| 6.5 | 观测 | `health_report.py`（趋势）+ `dep_audit.py`（依赖审计） | 同上 |
| 7 | 提交 + Release 发布 | git + Release latest | 无变更则跳过提交 |

**幂等**：DB 全部 upsert；导出每次全量重写；探针可反复重跑；合并可重入。
**增量**：探针吃上一轮产物；canary 累积；检测历史追加 + 30 天滚动清理；快照保留 14 天。
**失败重试**：单条失败绝不带崩整轮（`fetch_merge` 的 `work()` try/except、`probe` 的 `safe()`、`evaluate` 的逐候选 try）；阶段级用 `continue-on-error`，关键阶段（合并）才要求必须成功。
**日志**：统一 `[模块 HH:MM:SS]` 前缀 + `flush=True`，CI 中不会因缓冲丢失进度。

---

## 6. 各环节实现要点

### 6.1 采集
四路发现互补：代码搜索捞「没人 star 但内容对」的新仓（需 token，可翻页）；仓库搜索按 topic/关键词；种子 README 递归拿二级链接；**血统反查**从已收录源的同 owner 反查其他仓（产出最高，实测单 owner 可达 29 个新仓）。

> **收编标准必须是「独有站点数 unique」，不是 discover 的 score。**
> 实测证明两者无关：score 30 的候选带来 17 个新站点，score 90 的只有 3 个。
> 生态里互相抄配置极普遍，`unique = 候选指纹(sha1(api+ext)) 不在当前库中的数量` 才是真正的增量。
> 判据也应是「能否解析出站点数组」，而非「顶层是否 dict」——裸数组/嵌套配置曾被大量误判为垃圾。

### 6.2 去重与分类
三级去重：① `key` ② `api+ext` 指纹 ③ 同库镜像（L1 片名集合 Jaccard，剔 61 个）。
分类写 `group` 八类：采集站 / 直连点播 / 蜘蛛源 / 本地JS / 网盘 / 短剧 / 成人 / 其他。
排序键：分类 → 实测可搜 → 可用性档位 → 速度。

### 6.3 实测
覆盖不同类型：HTTP 采集接口（L1-L3）、type3 连通性、drpy Node 沙箱五关（**CI 每日自动**）、csp 真机五关（**手工**）。
记录状态码、延迟、等级、失败原因；**超时/本机不可达记为 unknown 而非 dead**（避免误杀）。

**时效降权**：csp 真机无法在 CI 跑，产物会随时间陈旧。`rank_sites.py` 的 `stale_days()` 会在产物超过
`PROBE_STALE_DAYS`（默认 7 天）时把该探针整体置空、不参与排序——宁可不用，也不拿旧结论给今天的源排位。

> **drpy 沙箱的两个约束**：① 纯 Node + curl，故能在 CI 直接跑（这是它比 csp 真机更适合自动化的原因）；
> ② **引擎必须与 `drpy-core-lite.min.js` 同目录**——`drpy2.min.js` 内部相对自身路径 import 它，
> 直接用 `lib/` 下那份引擎会报 `ERR_MODULE_NOT_FOUND`。所以沙箱自带完整两份。

### 6.4 入库
见 §4。DB **不入库**（二进制逐日膨胀），检测历史的可追溯性由 `exports/health_index.json`（纯文本，diff 友好）承担——每天 diff 能直接看出哪些源从 healthy 掉成 dead。

### 6.5 导出
以 `tvbox.json` 为骨架（保证字段完整），用 DB 健康结论增强，附加字段统一 `_` 前缀（TVBox 会忽略陌生字段，不影响兼容）：

| 文件 | 内容 |
|---|---|
| `all.json` | 全部（带健康标注） |
| `healthy.json` | 仅实测能搜能播（**体感最好，推荐默认订阅**） |
| `usable.json` | healthy + degraded（能连通即可） |
| `vod/spider/localjs/pan/short.json` | 按类型 |
| `live.json` | 直播源 |
| `health_index.json` | key→健康/检测时间/延迟/来源 索引 |

每个站点都带：`_health`、`_checked_at`（最后检测时间）、`_latency_ms`、`_level`、`_source`（来源）、`_type`（用途）。

---

## 7. 几条踩过的坑（务必遵守）

1. **不要用 `git pull` 同步本仓库**：远端 377 个文件名在 Windows 非法，会整体报 `invalid path`。用 `.workbuddy/tvbox-sync/sync_tvbox_config.py`。
2. **本地 Windows 产出的 `tvbox.json` 不提交**：URL 里的 `https:` 被安全化成 `https_`，与 CI(Linux) 布局不一致。CI 产物才是权威。
3. **合并别顶掉各上游的全局 spider**：每个上游声明的 `spider` 不同，统一改写会让源找不到爬虫类（曾致 256 类 / 359 源失效）。已由 `assign_origin_spiders()` 修复。
4. **「无报错 ≠ 能用」**：自建宿主跑第三方代码，先把传参/ext/jar/Context 对齐真实宿主，再谈结论。
5. **访问 `raw.githubusercontent.com` 必须带镜像兜底**：否则种子与探测会成片失败。
6. **Windows 上不要用 `os.path.normpath` 处理产物里的相对路径**：它会转成反斜杠，与磁盘的正斜杠路径永远匹配不上。
   `dep_audit.py` 第一版因此得出「868 个依赖 100% 未引用」的假结果——**照它清理会把全部依赖删光**，所以依赖审计坚持「只报告不删」。
7. **drpy 引擎必须与 `drpy-core-lite.min.js` 同目录**：引擎内部相对自身路径 import 它，用 `lib/` 那份会 `ERR_MODULE_NOT_FOUND`。
