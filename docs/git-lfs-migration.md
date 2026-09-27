# Git LFS 迁移方案（deps/*.jar 二进制大文件）

> 状态：待确认

## 背景与问题陈述

- `deps/` 当前 710 MB，其中 `.jar` 文件 493 个，占仓库体积大头。
- 7857 条 manifest 文本文件可以 diff，但 `.jar` 是二进制：每次上游 spider 升级都会让 git 对象库膨胀，clone/fetch 时间线性恶化。
- 当前 `.gitignore` 只忽略了 `state/*.db`、`snapshot/`、`sync/` 等运行时产物，`deps/` 整目录仍在 git 历史里。
- GitHub 单文件 100MB 硬上限虽未触发，但仓库整体已逼近"普通 clone 体验很差"的区间。

## 方案设计

### 1.1 两种迁移路线对比

| 维度 | 路线 A：`git lfs track`（仅新文件生效） | 路线 B：`git lfs migrate import --everything`（重写历史） |
| --- | --- | --- |
| 历史 jar 是否迁出 | 否，旧 commit 仍含二进制 | 是，全部历史对象转 LFS 指针 |
| commit hash | 不变 | **全部改写**（HEAD 及所有历史） |
| 仓库当前体积 | 不变，仅增量止住膨胀 | `.git` 瘦身后再 clone 可降 60%+ |
| 协作方影响 | 无，老 clone 仍可用 | 所有协作者必须重新 clone/fetch 强制覆盖 |
| 可逆性 | 完全可逆（删 .gitattributes 即可） | 回滚需 `git lfs migrate export` 或备份镜像 |
| 执行风险 | 低 | **高**（force push + 历史改写 + 未推送的本地分支丢失） |

### 1.2 推荐起步：路线 A（仅新文件生效）

```bash
git lfs install
git lfs track "*.jar"
git lfs track "deps/**/*.jar"
git add .gitattributes
git commit -m "chore: track *.jar via Git LFS"
```

`.gitattributes` 落点：
```
*.jar filter=lfs diff=lfs merge=lfs -text
deps/**/*.jar filter=lfs diff=lfs merge=lfs -text
```

此后所有新增/修改的 `.jar` 自动走 LFS。旧 jar 仍在历史对象里，但不再继续膨胀。

### 1.3 后续是否升级到路线 B

路线 A 跑 2~4 周，观察：
- 每日 `git push` 增量是否明显下降；
- CI `actions/checkout` 是否需要 `lfs: true`；
- `.git/objects` 体积趋势是否企稳。

若仍嫌大，再评估路线 B。**本仓单人维护、无其他协作者**，路线 B 的协作成本实际很低，但 force-push 一旦出错仍需远端 reflog 兜底。

### 1.4 CI 改动

`.github/workflows/daily.yml` 中 checkout 步骤加 `lfs: true`：
```yaml
- uses: actions/checkout@v4
  with:
    lfs: true
```
否则 CI 拉下来的 `.jar` 是指针文本，drpy/js 沙箱会跑不起来。

## 影响评估

| 面 | 影响 |
| --- | --- |
| clone 大小 | 路线 A：首次 clone 仍 ~700MB，之后增量显著下降；路线 B：重 clone 可降至 ~200MB |
| CI 时长 | 多一步 LFS 下载，预计 +10~30s（GitHub 国内 RTT 抖动需观察） |
| 用户端 | TVBox 客户端只消费 `tvbox.json`，不 clone 仓库，**零感知** |
| 仓库体积增长 | 新增 jar 增量从"整文件 blobs"变为"小指针 + LFS 对象存储"，主仓 `.git` 不再膨胀 |
| GitHub 存储配额 | LFS 1GB 带宽/月免费额度需评估；493 个 jar 若全部重写历史，首月带宽可能吃紧 |

## 实施步骤（分阶段可回滚）

1. **阶段 0（本方案待确认后）**：本地 `git lfs install`，加 `.gitattributes`，仅提交文本规则。
2. **阶段 1**：下一版 deps 升级时观察新 jar 是否走 LFS；CI 开 `lfs: true` 并行跑一周对比。
3. **阶段 2（可选）**：跑 `git lfs migrate import --include="*.jar" --everything`，备份原 `.git` 目录后 force-push。
4. **阶段 3**：在 README 写明"本仓使用 Git LFS，请 `git lfs install` 后再 clone"。

## 回滚方案

- 路线 A：删除 `.gitattributes` 中两行 LFS 规则，commit 后即恢复普通追踪；已推 LFS 的对象保留在服务端但不影响运行。
- 路线 B：重写前 `git clone --mirror` 备份 bare 仓库到本地；回滚时 force-push 备份镜像的 refs 即可。

## 需用户确认的决策点

1. 是否接受路线 B 的全量历史改写（commit hash 全部变化）？
2. GitHub LFS 免费带宽是否够用？是否需要自备 LFS 服务器或忽略 LFS、改用 Release 附件分发 jar（见 deps-not-tracked 方案）？
3. 是否同时 track 其他大文件类型（如 `*.zip`、`*.wasm`、`drpy-sandbox/` 下二进制）？
