# 成人内容独立仓库方案（hebijunge/tvbox-adult）

> 状态：待确认

## 背景与问题陈述

- 主仓库当前直接跟踪：`adult.json`、`adult_live.json`、`json_adult/`、`adult_live_channels/`、`adult_live_channels.json`。
- 成人内容与普通内容在法律风险、分发渠道、平台审核上完全不同：主仓挂 GitHub 公开页 `index.html` 时，成人内容共存容易触发 GitHub TOS 审查。
- 普通用户拉 `tvbox.json` 时不需要这些文件；混在一起既增大主仓体积，又让普通用户误触。
- 已有独立仓库 `hebijunge/tvbox-adult` 的命名预留（待创建）。

## 方案设计

### 5.1 仓库拆分

| 仓库 | 内容 | 可见性 |
| --- | --- | --- |
| `hebijunge/tvbox-config`（主仓，现状） | 普通 sites / lives / parses / 脚本 / docs | public |
| `hebijunge/tvbox-adult`（新建） | adult.json / adult_live.json / json_adult/ / adult_live_channels/ | **private** 或 public-pages 配访问控制 |

### 5.2 迁移步骤

```bash
# 1. 本地新建空仓 hebijunge/tvbox-adult
# 2. 把现有成人文件整体推过去
git clone git@github.com:hebijunge/tvbox-adult.git
cd tvbox-adult
# 从主仓拷贝历史：
git filter-repo --source ../tvbox-config \
  --path adult.json --path adult_live.json \
  --path json_adult/ --path adult_live_channels/ \
  --path adult_live_channels.json \
  --to-subdirectory-filter adult
git push origin main
```

### 5.3 主仓 CI 双写

主仓 `daily.yml` 改造：
- 主 job 继续产出 `tvbox.json` / `live.json`（普通内容）。
- 新增 step：成人内容分支用 `git clone` 拉 `tvbox-adult` 到 `./_adult_repo/`，把当天新算的 adult 配置写进去，commit & push。
- 用 GitHub Deploy Key（写权限只给 tvbox-adult 仓）。

伪代码：
```yaml
- name: sync adult to tvbox-adult repo
  env:
    ADULT_DEPLOY_KEY: ${{ secrets.ADULT_DEPLOY_KEY }}
  run: |
    mkdir -p ~/.ssh
    echo "$ADULT_DEPLOY_KEY" > ~/.ssh/id_ed25519
    chmod 600 ~/.ssh/id_ed25519
    git clone git@github.com:hebijunge/tvbox-adult.git _adult_repo
    cp adult.json adult_live.json _adult_repo/adult/
    cp -r json_adult _adult_repo/adult/
    cp -r adult_live_channels _adult_repo/adult/
    cd _adult_repo
    git config user.name "ci-bot"
    git config user.email "ci@example.com"
    git add -A
    git commit -m "ci: sync adult config $(date -u +%F)" || echo "no changes"
    git push origin main
```

### 5.4 主仓 .gitignore

```
# 成人内容迁出到独立仓 tvbox-adult
adult.json
adult_live.json
adult_live_channels.json
json_adult/
adult_live_channels/
```

注意：`.gitignore` 只影响未来；历史里的成人文件仍在主仓 git 历史里。若要彻底清除需 `git filter-repo` 重写历史（高风险，见决策点）。

### 5.5 用户使用方式变更

- 普通用户：继续用 `https://hebijunge.github.io/tvbox-config/tvbox.json`，**完全无感知**。
- 需要成人内容的用户：自行添加 `https://hebijunge.github.io/tvbox-adult/adult/adult.json` 作为第二份配置。
- TVBox 客户端支持多配置导入，用户自行切换。

## 影响评估

| 面 | 影响 |
| --- | --- |
| 主仓体积 | 减少 adult.json + json_adult/ + adult_live_channels/ 占用（待实测，估计 < 50MB） |
| GitHub TOS 风险 | 主仓 public 页面不再含成人内容，审查风险下降 |
| CI 复杂度 | 多一步 clone + push 第二个仓，需管理 Deploy Key |
| 维护成本 | 两个仓要同步跑 CI；adult 仓可复用同一套脚本（git submodule 或 clone 后跑） |
| 用户端 | 普通用户零感知；高级用户多一条配置 URL |

## 实施步骤（分阶段可回滚）

1. **阶段 1**：创建 `tvbox-adult` 空仓，把当前成人文件推一份过去（不删主仓）。
2. **阶段 2**：主仓 CI 加双写 step，观察一周 adult 仓是否每日正确更新。
3. **阶段 3**：主仓 `.gitignore` 加成人文件 + `git rm --cached`；主仓停止跟踪。
4. **阶段 4（可选）**：评估是否用 `git filter-repo` 把历史里的成人文件也清掉。

## 回滚方案

- 阶段 2/3 出问题：删掉 `.gitignore` 里的成人文件行，`git add adult*.json json_adult adult_live_channels` 重新追踪即可。
- Deploy Key 失效：CI 双写 step fail，adult 仓停更，但主仓产物不受影响。
- 历史改写（阶段 4）：重写前 mirror 备份；回滚 force-push 备份。

## 需用户确认的决策点

1. `tvbox-adult` 仓库可见性：public / private / 还是用 GitHub Pages 配 Basic Auth？
2. 是否接受阶段 4 的历史改写？（不改写的话，public 主仓历史里仍能翻到成人文件）
3. 成人内容 CI 是否需要独立跑探针？还是直接复用主仓算好的 adult 列表同步过去即可？
