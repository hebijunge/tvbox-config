# 直播 / 点播并行 CI 方案

> 状态：待确认

## 背景与问题陈述

- 当前 `.github/workflows/daily.yml` 是单 job，串行跑：点播聚合（`fetch_merge.py`）→ 直播聚合（`live_aggregate.py`）→ 质检 → 发布。
- CI timeout 150min，已逼近上限。
- 点播产物 `tvbox.json`（4048 sites）和直播产物 `live.json`（408 lives）在业务上是独立的两份配置，但流水线里被绑在同一条 job 里，互相拖累。
- 点播上游挂掉会让直播也跟着失败；反之亦然。

## 方案设计

### 3.1 数据依赖梳理

| 共享资产 | 点播 fetch_merge | 直播 live_aggregate | 是否冲突 |
| --- | --- | --- | --- |
| `probe/*.json`（csp_probe / drpy_probe / js_probe / sites_probe / spider_probe） | 读 | 写 live_probe（独立文件） | 无冲突（直播写自己的 live_probe） |
| `state/`（canary / upstreams / vocab） | 读+写 upstreams 下点播子目录 | 读+写 upstreams/live_* | **子目录隔离，无写冲突** |
| `deps/` | 读（jar/js 运行时） | 不读 | 直播无需 deps |
| `candidate_upstreams.json` | 读 | 读 live_* 段 | 只读，无冲突 |
| 产物 `tvbox.json` / `live.json` | 写 tvbox.json | 写 live.json | 互不覆盖 |

**结论**：两者数据耦合度低，可以安全拆成两个并行 job。

### 3.2 拆 job 设计

```yaml
jobs:
  vod:        # 点播：fetch_merge.py → tvbox.json
    runs-on: ubuntu-latest
    steps: [checkout, refresh_deps, fetch_merge, upload artifact tvbox.json]
  live:       # 直播：live_aggregate.py → live.json
    runs-on: ubuntu-latest
    steps: [checkout, live_aggregate, upload artifact live.json]
  publish:    # 汇总：下载两 artifact → config_validate → 发布
    needs: [vod, live]
    steps: [download-artifact, validate, deploy]
```

### 3.3 Artifact 传递

- `vod` job 上传 `tvbox.json` + `tvbox.ranked.json` + `vod.json`。
- `live` job 上传 `live.json` + `adult_live.json`（若保留在主仓）。
- `publish` job 下载后做联合校验（例如 sites↔parses 引用完整性）。

### 3.4 CI 总耗时预估

| 阶段 | 当前串行 | 并行后 |
| --- | --- | --- |
| checkout + deps 准备 | ~1min | ~1min（两 job 各做一次，共 2min 墙钟内并行） |
| 点播聚合 | ~50min | ~50min |
| 直播聚合 | ~30min | ~30min（与点播并行） |
| 质检 + 发布 | ~5min | ~5min（publish job） |
| **墙钟总时长** | **~86min** | **~56min** |

节省约 30min，timeout 150min 余量从 64min 拉到 94min。

### 3.5 冲突处理

- 两 job 同时写 `state/upstreams/`：通过子目录硬隔离（`state/upstreams/vod/*` vs `state/upstreams/live/*`），publish 阶段再合并写回主分支。
- 两 job 同时 push：不允许直接 push。所有产物由 publish job 统一 commit（复用 `_commit.py` 管道方式）。
- 一边失败另一边成功：publish job `if: always()`，把成功那份发出去，失败那份留 issue 告警；不让一份失败拖死另一份。

### 3.6 与现有 probe 缓存的关系

`c91c6c9b` 引入的"24h 内 healthy 且 <2s 的源复用结论"目前写在 `probe/*.json`。两 job 并行后：
- vod job 读 `probe/{csp,drpy,js,sites,spider}_probe.json`
- live job 读 `probe/live_probe.json`
- 两个 job 都**只读** probe 结果，刷新 probe 的步骤仍由 vod job 负责（probe 主要是给点播用的）。

## 影响评估

| 面 | 影响 |
| --- | --- |
| CI 时长 | 墙钟从 ~86min 降到 ~56min |
| CI 成本 | GitHub Actions 分钟数：两个并行 job 总机时略增（checkout 做两次），但墙钟更快 |
| 故障隔离 | 点播挂不影响直播发布；直播挂不影响点播发布 |
| 调试复杂度 | 需要看两个 job 日志，本地复现要分别跑两条命令 |
| 用户端 | 无感知 |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：在 daily.yml 里把 live_aggregate 抽成独立 step，加 `continue-on-error: true`，先观察一周是否真解耦。
2. **阶段 2**：拆成 `vod` / `live` 两个 job，artifact 传递用 `actions/upload-artifact@v4`。
3. **阶段 3**：加 `publish` 汇总 job，做联合校验 + 统一发布。
4. **阶段 4**：观察 7 天，确认无数据竞争。

## 回滚方案

- 任一阶段出问题：daily.yml 改回单 job 串行结构（git revert 单个 commit）。
- artifact 传递出问题：临时让 live job 直接 push（不推荐，仅应急）。

## 需用户确认的决策点

1. 是否接受 vod / live 互相独立发布（一边挂时另一边照常更新）？
2. publish job 失败时，是否接受"两份产物都不发"，还是"成功的那份先发"？
3. 是否需要把 adult_live 也独立成第三个 job？
