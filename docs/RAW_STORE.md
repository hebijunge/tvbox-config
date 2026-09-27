# raw-store：原始源落库 + 变化检测 + 上游删除保护（2026-09-27）

直播与点播流水线的**输入层改造**：上游依赖文件先原样入库（字节级镜像或 sha256 账本），
每日做哈希变化检测——变了才重跑下游聚合，没变直接沿用既有产物；**上游删除/404 时
绝不跟随删除本地最后可用版本**。清洗分类探活逻辑照常运行，只是改为在入库后的原始文件上跑。

## 目录结构

```
raw/                    上游原始文件镜像（字节级留档，按来源命名）
├── live/               直播上游（txt/m3u 原样落盘）
│   ├── manifest.json   哈希清单（sha256/size/状态/日期/history）
│   └── <来源>.m3u|txt
├── vod/                点播 tvbox 配置类上游（json 原样落盘，解码前字节）
│   ├── manifest.json
│   └── <来源>.json
└── history 只随文件产生：raw/<store>/history/<日>/<文件>  上一版按日归档

raw-vod/                点播依赖账本（只记 sha256，不落字节，见下「为什么是账本」）
└── manifest.json       key = "<origin>|<url>"，与 deps/ 布局镜像（path=tv1/dep1.js）

deps/                   点播依赖生效文件（现状不变）——账本模式下它本身就是
                        「最后可用版」的落盘，管线从不删除它
state/raw_run.json      每轮台账：mode=full|skipped_unchanged、changed 源名单
state/raw_audit.json    审计报告（scripts/raw_audit.py 产出）
```

## 每日流程（daily-fetch 内嵌，无新工作流）

1. **拉取即入库**：每个上游下载到的原始字节（解码前）先 `raw_store.ingest` 入库
   ——直播 m3u → `raw/live/`，tvbox 配置 → `raw/vod/`（均字节级留档）。
   点播依赖在收集阶段入 `raw-vod/` 账本（`store_bytes=False`）。
2. **哈希变化检测**：sha256 与清单比对 → `new / changed / unchanged /
   changed_recovered / restored` 五种转移；上游 404 → `mark_deleted`
   （只改清单标记，绝不删文件）。
3. **变化驱动重跑**：`state/raw_run.json` 记台账。全部上游 `unchanged` 且已有
   tvbox.json/live.json → **跳过聚合直接结束**（探活由 validate.yml/巡检独立承担）；
   任一源 changed → 全量聚合照常。canary 上游只监控不合并，其变化不驱动重跑。
4. **历史留档**：字节级库在内容变化时把旧版归档 `raw/<store>/history/<今日>/<文件>`，
   清单 history 环形保留最近 `RAW_HISTORY_KEEP=60` 条。
5. **差异审计**：`python3 scripts/raw_audit.py`（见下）。

## 上游删除保护（关键边界）

上游文件被删除/404 时，**本地不跟随删除**：

- **直播/tvbox 配置上游**：拉取失败时从 `raw/<store>/` 取最后可用字节继续走
  正常评估/合并，清单标 `status=deleted_upstream`（含 `deleted_at`/`deleted_reason`）。
  发布产物继续引用最后可用版内容；日志与 list.json 记录
  「上游已删/不可达，raw-store 沿用最后可用版（<日> 标记 deleted_upstream）」。
- **点播依赖**：`raw-vod/` 账本标 `deleted_upstream`，deps/ 生效文件原样保留，
  本轮以 deps/ 本地文件（最后可用版）继续参与合并，产物引用不丢。
- **不会被自动黑名单打死**：沿用存档后该源照常通过质量门槛（内容没变），
  `fail_count` 不累积——保护不会经由「连续 3 次失败自动停用」路径丢源。
- **只有上游恢复**（重新可下载）才覆盖更新：内容与存档一致 → `recovered`
  清除删除标记；有更新 → `changed_recovered` 正常升级。

边界：变化检测只解决「上游文件有没有变」，不解决「上游内部线路死活」——
直播探活剔除（live-prune）照常保留，两者互补。

## 为什么 raw-vod/ 是账本模式（只记 sha256 不落字节）

deps/ 已 700MB+/7720 文件，再镜像一份字节会让仓库体积翻倍失控；且 deps/ 生效
文件本身就是「最后可用版」的落盘（管线从不删除它）。账本承担**变化与删除留痕**
（sha256/size/状态/日期/history），字节事实源就在 deps/。直播与 tvbox 配置类上游
体量小（KB 级/日更），保留字节级镜像 + history 归档。

`RAW_VOD_VERIFY` 控制依赖验证频率：`on-change`（默认，上游配置有变化才逐依赖
拉上游验证——配置不变则依赖不变）/ `always`（每日全量验证）/ `off`（关闭）。

## 审计脚本用法

```bash
python3 scripts/raw_audit.py                  # 输出 state/raw_audit.json + 控制台摘要
python3 scripts/raw_audit.py --max-sample 5   # 每源 dropped 样例条数
```

- **直播侧**：逐源解析 raw/live/ 入库镜像（与生产同一 parse_m3u 口径）→ URL 集合，
  与 lives/*.txt（含 groups/）发布产物对比 → 每源 kept/dropped 计数与 dropped 样例，
  可定位「这个 URL 是哪个源贡献的、现在产物里没有」（典型去向：探活死链剔除/分组筛选）。
- **点播侧**：raw-vod/ 账本 sha256 vs deps/ 生效文件实际 sha256 → match/mismatch/missing；
  mismatch = deps 文件被人工改过或账本过期；deleted_upstream 依赖的 deps 文件仍存在
  = 删除保护生效。

## 环境开关

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RAW_STORE` | `1` | `0` 关闭整层（回退旧行为） |
| `RAW_HISTORY_KEEP` | `60` | 每源 history 环形保留条数 |
| `RAW_VOD_VERIFY` | `on-change` | 点播依赖上游验证频率（on-change/always/off） |
| `FORCE_FULL_RUN` | `0` | `1` 忽略无变化门控强制全量聚合 |

## 实测记录（2026-09-27，本地 E2E 三轮，fixture 上游 127.0.0.1:8899）

- **R1 全新入库**：tv1（tvbox 配置）+ m3u1（4 频道 m3u）+ 2 依赖 →
  `raw/live`、`raw/vod` 字节落盘，`raw-vod` 账本 2 条（ledger=true、无字节文件），
  deps 2 文件，tvbox.json spider 改写 `./deps/tv1/spider.jar`，live 产物 4 频道，
  `raw_run.json mode=full changed=[tv1]`。
- **R2 无变化**：上游零字节差异 → `[raw-store] 全部上游无变化 → 跳过聚合`，
  `raw_run.json mode=skipped_unchanged`，tvbox/live/vod 三产物 sha256+mtime 均未变。
- **R3 删除保护**：tv1.json 删除（404）+ dep1.js 删除（404）+ m3u1 加频道改链 →
  m3u1 changed 触发重跑；tv1 沿用存档（list.json 记 deleted_upstream + 404 原因），
  **tvbox.json sha256 与删除前完全一致**；dep1.js deps 文件 sha 不变、账本标
  `deleted_upstream`；tv1 `fail_count=0` 未被自动停用；新频道 CCTV13/cctv1-v2 进产物。
- **审计**：直播 raw URL 5 → 产物 5（kept 100%）；点播账本 2 条全 match、
  deleted_upstream 1 条保护生效。
