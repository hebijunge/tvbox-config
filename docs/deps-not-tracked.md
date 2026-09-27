# deps/ 不入库方案（CI 重建 + Release 附件兜底）

> 状态：待确认

## 背景与问题陈述

- `deps/` 当前 710 MB，7857 条 manifest + 493 个 `.jar`，是仓库体积最大的单一目录。
- deps 本质是**上游 spider 运行时依赖缓存**：每次 `fetch_merge.py` 跑批时从各上游配置里解析出 jar/js 引用，下载到本地供 drpy-sandbox 执行。
- 这部分内容**可从上游重新拉取**，且每日都在变；把它当源码 commit 进 git，既让 diff 噪声巨大，又把 git 当 CDN 用。
- 当前 snapshot/ 已经做过类似的"原始抓取缓存不入库、归档到 Release"的改造（见 .gitignore 注释），deps/ 是下一个候选。

## 方案设计

### 2.1 目录职责重新划分

| 路径 | 新职责 | 是否入库 |
| --- | --- | --- |
| `deps/` | 纯运行时缓存（当前 .jar / .js 实体） | **不入库**，加入 .gitignore |
| `deps_manifest/`（新） | 7857 条 manifest 元数据（JSON，含 sha256、来源 url、版本） | 入库，纯文本 diff 友好 |
| `_deps/`（已存在） | 已有目录，确认其职责不冲突 | 视现状保留 |

### 2.2 CI 重建流程

```
daily.yml:
  step1: checkout（不含 deps/）
  step2: python scripts/refresh_deps.py
         —— 读取 deps_manifest/*.json
         —— 对每条记录：
            a) 若 Release 附件 deps-cache-<date>.zip 命中 sha256 → 直接解压
            b) 否则从上游 url 重新下载 → 校验 sha256 → 落 deps/
  step3: 若重建失败 > 阈值 → 从上一个 Release 附件恢复"最后可用版"
  step4: 继续 fetch_merge.py 主流程
```

### 2.3 Release 附件兜底

- 每日 CI 成功后，把当天 `deps/` 打 zip 上传到 GitHub Release `deps-cache`（覆盖式，保留最近 7 天）。
- 文件名：`deps-cache-YYYYMMDD.zip`，附 `SHA256SUMS.txt`。
- CI 失败时优先取最近一个 sha256 校验通过的附件恢复，避免"上游全挂导致当天产物空白"。

### 2.4 raw-store 删除保护影响

当前 `docs/RAW_STORE.md` 描述的 raw-store 是上游配置原文快照，与 deps/ 是两层：
- raw-store：上游 JSON 配置原文（文本，已部分归档到 Release snapshot-archive）。
- deps/：配置里引用到的 jar/js 二进制。

本方案**不触碰 raw-store**，只把 deps/ 的二进制实体挪出 git。raw-store 的删除保护逻辑保持不变。

### 2.5 CI 恢复速度估算

| 场景 | 预计耗时 |
| --- | --- |
| 命中 Release 附件，解压 700MB | ~30s（GitHub Actions 带宽 ~100MB/s） |
| 未命中，从上游重新下载 493 个 jar | 视上游 RTT，历史经验 3~8 分钟 |
| 附件损坏且上游全挂 | CI 直接 fail，不产出当天 tvbox.json（与现状 fail 语义一致） |

当前 CI timeout 150min，新增重建步骤预算 10 分钟，余量充足。

### 2.6 用户使用方式变更

- **TVBox 终端用户**：无感知，`tvbox.json` 拉的还是同一份 URL。
- **本地开发者**：clone 后必须跑一次 `python scripts/refresh_deps.py` 才能本地复现 CI；不能再 `git pull` 完就直接跑 drpy-sandbox。README 需补一行说明。

## 影响评估

| 面 | 影响 |
| --- | --- |
| 仓库体积 | 当前 clone ~700MB → 预期 < 50MB（仅脚本+配置+manifest） |
| CI 时长 | 每日多 30s~8min 重建；但 checkout 阶段从拉 700MB 变成拉 < 50MB，**总时长可能反而下降** |
| 历史追溯 | 旧 jar 版本仍在 git 历史里（本方案不做历史改写）；新 jar 版本可在 Release 附件 + deps_manifest 里追 |
| 稳定性风险 | 上游 url 失效会导致重建失败；Release 附件是兜底 |
| 磁盘占用（CI runner） | ephemeral runner，无影响；本地开发者需多留 ~700MB |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：写 `scripts/refresh_deps.py`，支持"读 manifest → 先试 Release 附件 → 再试上游 url"两级回源；本地跑通。
2. **阶段 2**：把 7857 条 manifest 从 deps/ 抽离到 `deps_manifest/`（纯 JSON，文本），单独 commit。
3. **阶段 3**：`.gitignore` 加 `deps/`，`git rm -r --cached deps/`；CI 加 refresh_deps 步骤。
4. **阶段 4**：连续观察 7 天 CI；确认 Release 附件自动上传脚本正常。
5. **阶段 5**：再考虑是否配合 git-lfs-migration 方案，把历史里的 jar 也清掉。

## 回滚方案

- 任一阶段出问题：`.gitignore` 移除 `deps/` 一行，`git add deps/` 重新追踪即可。
- refresh_deps.py 失败：CI 里 `continue-on-error: false` 会让当天产物不发布，用户仍看上一版 tvbox.json（与现状一致）。
- Release 附件被误删：CI 自动降级到上游重新下载；都失败则当天 fail。

## 需用户确认的决策点

1. manifest 抽离到 `deps_manifest/` 是否接受？还是希望继续塞在 deps/ 里（那样就没法 ignore 整目录）？
2. Release 附件保留 7 天够不够？磁盘配额是否够（每日 700MB × 7 ≈ 5GB）？
3. 是否接受"本地开发者 clone 后必须手动跑 refresh_deps.py"这一使用方式变更？
