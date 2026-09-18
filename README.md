# tvbox-config

TVBox 配置每日自动拉取合并仓库，由 GitHub Actions 定时运行。

## 使用方式

在 TVBox / 影视仓等应用的「配置地址」中填入：

```
https://raw.githubusercontent.com/hebijunge/tvbox-config/main/tvbox.json
```

直连不畅可用代理前缀：

```
https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/tvbox.json
```

jsDelivr CDN 通道：

```
https://cdn.jsdelivr.net/gh/hebijunge/tvbox-config@main/tvbox.json
```

固定引用最新 Release（双通道发布，永远指向最近一次产物）：

```
https://github.com/hebijunge/tvbox-config/releases/download/latest/tvbox.json
```

## 点播 / 直播拆分订阅（2026-09-18 起）

除完整合并版 `tvbox.json` 外，仓库同时拆分产出两份独立订阅，按需取用：

**点播配置 `vod.json`**（sites + parses + spider，不含直播）：

```
https://raw.githubusercontent.com/hebijunge/tvbox-config/main/vod.json
```

```
https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/vod.json
```

```
https://cdn.jsdelivr.net/gh/hebijunge/tvbox-config@main/vod.json
```

**直播配置 `live.json`**（lives 数组，汇总 lives/ 目录央视 / 卫视 / 港台 / 其他分类与各上游直播源）：

```
https://raw.githubusercontent.com/hebijunge/tvbox-config/main/live.json
```

```
https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/live.json
```

```
https://cdn.jsdelivr.net/gh/hebijunge/tvbox-config@main/live.json
```

Release 通道同样提供 `vod.json` / `live.json`（`.../releases/download/latest/vod.json`）。

## 短剧 / 成人独立订阅（2026-09-18 起）

新增两份分类独立配置，`vod.json` 保持完整不剥离——独立收录是按关键词分类器从合并配置中筛出短剧/成人站点，并新增 6 条 GitHub 试探性专项上游（qist/duanju/duoduo/wogg、gao/duanju、nxppru/duanju、cluntop/duanju，实测全部 404 已记入自动黑名单，分类器从既有 1028 个站点筛得 23 short + 95 adult）。

**短剧配置 `short.json`**（独立收录「短剧/微短剧/duanju/七猫/河马/围观/好看/星芽/果果/红果/黄果/黄豆/锦鲤/偷乐/上头」等关键词命中的 23 个站点 + 全集 parses）：

```
https://raw.githubusercontent.com/hebijunge/tvbox-config/main/short.json
```

```
https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/short.json
```

```
https://cdn.jsdelivr.net/gh/hebijunge/tvbox-config@main/short.json
```

**成人配置 `adult.json`**（独立收录「成人/18+/jav/porn/麻豆/果冻/天美/精东/色播/丝袜/美腿/91/非凡/量子/色花糖/JavBus/JavDb/Missav/玩偶姐姐/朱古力/PikPak/磁力」等关键词命中的 95 个站点 + 全集 parses；不含短剧/普通站点）：

```
https://raw.githubusercontent.com/hebijunge/tvbox-config/main/adult.json
```

```
https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/adult.json
```

```
https://cdn.jsdelivr.net/gh/hebijunge/tvbox-config@main/adult.json
```

Release 通道同样提供 `short.json` / `adult.json`（`.../releases/download/latest/short.json` 等）。

**说明**：分类器扫站点 `name` / `key` / `api` / `ext` 字段命中关键词（短剧 21 词、成人 33 词），冲突时短剧优先避免误吞。parses 复用全集——TVBox 站点不直接引用 parses（playUrl/jar 才是站点自有播放方式），parses 是全局播放器池，单独配置需自带全集才不至于某些解析器不可用。

## 产物文件

| 文件 | 说明 |
|------|------|
| `tvbox.json` | 合并去重后的统一配置（sites / lives / parses） |
| `vod.json` | 点播拆分订阅：sites + parses + spider（jar/js 依赖路径同 tvbox.json，指向 ./deps/）；**不剥离短剧/成人，保持完整** |
| `live.json` | 直播拆分订阅：lives 数组，汇总 lives/ 目录央视 / 卫视 / 港台 / 其他分类直播与各上游直播源 |
| `short.json` | 短剧独立订阅：23 个短剧类站点（按 name/key/api/ext 关键词筛出）+ 全集 parses |
| `adult.json` | 成人独立订阅：95 个成人类站点（按 name/key/api/ext 关键词筛出）+ 全集 parses |
| `list.json` | 上游接口清单，含每条接口的测试记录（响应耗时、分级、合并贡献） |
| `status.json` | 状态可视化：总量统计（含 sites_short / sites_adult）、上游健康度、直播分类统计、产物指纹、验活剔除明细、Top 接口 |
| `checks.json` | 上游校验状态：状态/字节数/sha256 指纹/连续失败计数/最近通过时间 |
| `lives/live.txt` | 分类合并直播源（txt 格式） |
| `lives/live_cctv.txt` 等 | 央视 / 卫视 / 港台 / 其他 分类直播（测速优选后输出） |
| `snapshot/<日期>/` | 每日快照存档：每份上游原始文件原样留存（保留最近 14 天） |
| `state/` | 上游健康状态 + 黑白名单（auto/manual 三层）+ 域名映射表 |
| `radar/candidates.json` | 源雷达每周扫描的候选上游（人工确认后收编） |
| `candidate_upstreams.json` | issue 自动收录的候选池（issue → PR） |

## 运行机制

1. **定时**：北京时间每日 06:00 与 18:00 各跑一次拉取合并（`.github/workflows/daily.yml`），00:30 独立验活（`validate.yml`），周一 11:00 源雷达扫描（`radar.yml`），均支持手动触发。
2. **质量门槛（P0）**：每份上游除 HTTP 可达外，还须通过最小字节数（配置 ≥512B、m3u ≥1KB）/ 最小条目数门槛，并记录内容 sha256 指纹——HTTP 200 不等于有货。
3. **自动停用（P0/P1）**：连续 3 次不达标的上游自动停用（写入 `state/blacklist_auto.txt`），可用后自动恢复；`state/whitelist_manual.txt` 可豁免，`state/blacklist_manual.txt` 可强制拉黑。
4. **拉取与解析（P2 一上游一适配器）**：上游以 kind 分派解析器（`tvbox`=json 配置 / `m3u`=直播列表），新增源只加一条配置，互不影响。
5. **合并去重**：sites 按 key、lives/parses 按 name 全局去重，上游清单顺序即优先级，同名先到先得、不覆盖已有源。
6. **链接代理**：配置内的 GitHub 原链统一加 `ghproxy.net` 前缀；上游换域名时可在 `state/domain_map.json` 配置映射自动改写（P2 域名替换层）。
7. **测速验活**：type 0/1 直连站点并发测活（6 秒超时，失败重试一次），连续失败自动剔除；直播源按央视/卫视/港台/其他分类，逐 URL 测速排序，每频道保留前 3 条。
8. **快照存档（P1）**：每次运行把各上游原始文件存入 `snapshot/<日期>/`（带时间戳文件名），合并产物一并留存，可回滚与失效溯源。
9. **双通道发布（P2）**：产物同时提交 main 分支与 Releases（`latest` 标签固定指向最新），README 由 `checks.json` 自动回写各上游可用性状态（🟢🟡🔴）。
10. **社区收录（P2）**：提 issue 按模板推荐上游 → 机器人自动验活 → 可用者自动开 PR 登记 `candidate_upstreams.json`，人工确认后收编。

## 上游清单

| 分组 | 来源 |
|------|------|
| 聚合 CMS | ccAzy/juhe-tvapi（107 个采集源） |
| qist/tvbox | jsm / js / dianshi / fty / XYQ / 0821 / 0825 / 0826 / 0827 / 367 / 9918 / 99188 |
| gaotianliuyun/gao | js / XYQ / 0821 / 0825 / 0826 / 0827 |
| cluntop/tvbox | jsm / box / fun / aa / bb / wv / yt / test |
| nxppru/tvbox | jsm / js / dianshi / fty / XYQ / 0821 / 0825 / 0826 / 0827 |
| 独立接口 | 俊哥 top98（home.jundie.top:81/top98.json） |
| 直播源（新增） | Guovin/iptv-api gd 分支 + Releases 双通道（分类测速后分组输出） |

## 上游可用性（自动回写）

<!-- availability:start -->
| 上游 | 状态 | 字节数 | 指纹 | 连续失败 | 最近通过 |
|------|------|--------|------|----------|----------|
| juhe-tvapi | 🟢 可用 | 47615 | `ac0b24e0c0bf` | 0 | 2026-09-18 12:41:46 |
| qist/jsm | 🟢 可用 | 47845 | `166d33ec3429` | 0 | 2026-09-18 12:41:46 |
| qist/js | 🟢 可用 | 52718 | `59829950158d` | 0 | 2026-09-18 12:41:46 |
| qist/dianshi | 🟢 可用 | 47243 | `a96a6395ee73` | 0 | 2026-09-18 12:41:46 |
| qist/fty | 🟢 可用 | 13088 | `c30dd4e8b027` | 0 | 2026-09-18 12:41:46 |
| qist/XYQ | 🟢 可用 | 19198 | `701eabdf0716` | 0 | 2026-09-18 12:41:46 |
| qist/0821 | 🟢 可用 | 23882 | `e6ad00dd38ff` | 0 | 2026-09-18 12:41:46 |
| qist/0825 | 🟢 可用 | 27643 | `2dfa63eb159d` | 0 | 2026-09-18 12:41:46 |
| qist/0826 | 🟢 可用 | 12110 | `cc09f8e5ec8f` | 0 | 2026-09-18 12:41:46 |
| qist/0827 | 🟢 可用 | 9964 | `b5ef20d275d4` | 0 | 2026-09-18 12:41:46 |
| qist/367 | 🟢 可用 | 55563 | `3da1c845d84a` | 0 | 2026-09-18 12:41:46 |
| qist/9918 | 🟢 可用 | 14844 | `0a99c448723d` | 0 | 2026-09-18 12:41:46 |
| qist/99188 | 🟢 可用 | 17359 | `12943dc6aeeb` | 0 | 2026-09-18 12:41:46 |
| gao/js | 🟢 可用 | 51621 | `3f30881d2458` | 0 | 2026-09-18 12:41:46 |
| gao/XYQ | 🟢 可用 | 19203 | `82db008c0fa4` | 0 | 2026-09-18 12:41:46 |
| gao/0821 | 🟢 可用 | 22974 | `a3bc1da94be9` | 0 | 2026-09-18 12:41:46 |
| gao/0825 | 🟢 可用 | 27518 | `8c86c98c389d` | 0 | 2026-09-18 12:41:46 |
| gao/0826 | 🟢 可用 | 10559 | `f9bc0b6d11b0` | 0 | 2026-09-18 12:41:46 |
| gao/0827 | 🟢 可用 | 9973 | `1c2b6b2f9aa0` | 0 | 2026-09-18 12:41:46 |
| cluntop/jsm | 🟢 可用 | 38829 | `c843b53c4826` | 0 | 2026-09-18 12:41:46 |
| cluntop/box | 🟢 可用 | 33826 | `85f9e3b32dde` | 0 | 2026-09-18 12:41:46 |
| cluntop/fun | 🟢 可用 | 39183 | `28b47fda08a6` | 0 | 2026-09-18 12:41:46 |
| cluntop/aa | 🟢 可用 | 15624 | `e35f08660e3d` | 0 | 2026-09-18 12:41:46 |
| cluntop/bb | 🟢 可用 | 2829 | `74b99efdc008` | 0 | 2026-09-18 12:41:46 |
| cluntop/wv | 🟢 可用 | 3406 | `67f0882ad97b` | 0 | 2026-09-18 12:41:46 |
| cluntop/yt | ⚫ 已停用 | - | `-` | 3 | - |
| cluntop/test | 🟢 可用 | 1162 | `1777259f409a` | 0 | 2026-09-18 12:41:46 |
| nxppru/jsm | 🟢 可用 | 24514 | `03b17169741e` | 0 | 2026-09-18 12:41:46 |
| nxppru/js | 🟢 可用 | 52714 | `cc4480eca92b` | 0 | 2026-09-18 12:41:46 |
| nxppru/dianshi | 🟢 可用 | 23736 | `5b236636b4e6` | 0 | 2026-09-18 12:41:46 |
| nxppru/fty | 🟢 可用 | 13088 | `c30dd4e8b027` | 0 | 2026-09-18 12:41:46 |
| nxppru/XYQ | 🟢 可用 | 19198 | `701eabdf0716` | 0 | 2026-09-18 12:41:46 |
| nxppru/0821 | 🟢 可用 | 23880 | `ad4b43a69284` | 0 | 2026-09-18 12:41:46 |
| nxppru/0825 | 🟢 可用 | 27504 | `b25e72496c84` | 0 | 2026-09-18 12:41:46 |
| nxppru/0826 | 🟢 可用 | 12108 | `4e78ad55f07e` | 0 | 2026-09-18 12:41:46 |
| nxppru/0827 | 🟢 可用 | 9973 | `1c2b6b2f9aa0` | 0 | 2026-09-18 12:41:46 |
| top98 | 🟢 可用 | 16543 | `9e3411a57300` | 0 | 2026-09-18 12:41:46 |
| guovin-gd-ipv4 | 🟢 可用 | 106329 | `7b6f299f36c3` | 0 | 2026-09-18 12:41:46 |
| guovin-release | 🟢 可用 | 302552 | `ec4e232c11b9` | 0 | 2026-09-18 12:41:46 |
| qist/duanju | ⚫ 已停用 | - | `-` | 3 | - |
| qist/duoduo | ⚫ 已停用 | - | `-` | 3 | - |
| qist/wogg | ⚫ 已停用 | - | `-` | 3 | - |
| gao/duanju | ⚫ 已停用 | - | `-` | 3 | - |
| nxppru/duanju | ⚫ 已停用 | - | `-` | 3 | - |
| cluntop/duanju | ⚫ 已停用 | - | `-` | 3 | - |
<!-- availability:end -->

## 本地运行

```bash
python3 scripts/fetch_merge.py
# 可用环境变量调并发：CONCURRENCY=12 python3 scripts/fetch_merge.py
# 独立验活（不产出配置）：python3 scripts/check_upstreams.py
# 源雷达扫描：python3 scripts/radar_scan.py
```

仅依赖 Python 3.8+ 标准库，无第三方包。
