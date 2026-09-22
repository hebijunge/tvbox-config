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

## 在线导航页（2026-09-22 起，第三条通路）

**https://hebijunge.github.io/tvbox-config/** —— 纯静态导航页（`index.html`），与配置产物同域托管：

- 订阅入口：每份配置 raw / ghproxy / jsDelivr / Pages / Release 多线路并列，一键复制，一线不畅换下一条；
- 健康度总览：读 `exports/health_report.json` 实时渲染（读数失败自动降级提示）；
- 直播分类：央视 / 卫视 / 港台 / 其他 txt 直达；
- 离线包下载：`tvbox-latest.zip` Pages 同域 + Release 双入口。

> 前置（一次性）：仓库 Settings → Pages → Build and deployment → Source 选「GitHub Actions」，之后每日 CI 成功自动部署（`.github/workflows/pages.yml`）。

## 健康清单订阅（2026-09-20 起，推荐）

全量配置里约一半源是死的（站点关停/防盗链失效）。`exports/` 按实测健康度分层导出，**推荐默认订阅 `healthy.json`**（实测能搜能播的源）：

```
https://raw.githubusercontent.com/hebijunge/tvbox-config/main/exports/healthy.json
```

```
https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/exports/healthy.json
```

| 文件 | 内容 |
|---|---|
| `exports/all.json` | 全部（带 `_health/_checked_at/_latency_ms/_source` 标注） |
| `exports/healthy.json` | **仅实测能搜/能播**（体感最好） |
| `exports/usable.json` | healthy + degraded（能连通即可） |
| `exports/vod|spider|localjs|pan|short.json` | 按用途分类 |
| `exports/health_index.json` | key→健康/检测时间/延迟/来源 索引（文本 diff 友好） |

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

## 短剧独立订阅（2026-09-18 起）

新增分类独立配置，`vod.json` 保持完整不剥离——独立收录是按关键词分类器从合并配置中筛出短剧站点，并新增 6 条 GitHub 试探性专项上游（qist/duanju/duoduo/wogg、gao/duanju、nxppru/duanju、cluntop/duanju，实测全部 404 已记入自动黑名单，分类器从既有 1028 个站点筛得 23 个短剧站点）。

**短剧配置 `short.json`**（独立收录「短剧/微短剧/duanju/七猫/河马/围观/好看/星芽/果果/红果/黄果/黄豆/锦鲤/偷乐/上头」等关键词命中的站点 + 全集 parses）：

```
https://raw.githubusercontent.com/hebijunge/tvbox-config/main/short.json
```

```
https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/short.json
```

```
https://cdn.jsdelivr.net/gh/hebijunge/tvbox-config@main/short.json
```

需要恢复合并行为时，本地跑：

```bash
python scripts/fetch_merge.py
```

**说明**：分类器扫站点 `name` / `key` / `api` / `ext` 字段命中关键词（短剧 21 词），冲突时短剧优先避免误吞。parses 复用全集——TVBox 站点不直接引用 parses（playUrl/jar 才是站点自有播放方式），parses 是全局播放器池，单独配置需自带全集才不至于某些解析器不可用。

## 产物文件

| 文件 | 说明 |
|------|------|
| `tvbox.json` | 合并去重后的统一配置（sites / lives / parses） |
| `vod.json` | 点播拆分订阅：sites + parses + spider（jar/js 依赖路径同 tvbox.json，指向 ./deps/）；**不剥离短剧，保持完整** |
| `live.json` | 直播拆分订阅：lives 数组，汇总 lives/ 目录央视 / 卫视 / 港台 / 其他分类直播与各上游直播源 |
| `short.json` | 短剧独立订阅：23 个短剧类站点（按 name/key/api/ext 关键词筛出）+ 全集 parses |
| `list.json` | 上游接口清单，含每条接口的测试记录（响应耗时、分级、合并贡献） |
| `status.json` | 状态可视化：总量统计（含 sites_short）、上游健康度、直播分类统计、产物指纹、验活剔除明细、Top 接口 |
| `checks.json` | 上游校验状态：状态/字节数/sha256 指纹/连续失败计数/最近通过时间 |
| `lives/live.txt` | 分类合并直播源（txt 格式） |
| `lives/live_cctv.txt` 等 | 央视 / 卫视 / 港台 / 其他 分类直播（测速优选后输出） |
| `snapshot/<日期>/` | 每日快照存档：每份上游原始文件原样留存（保留最近 14 天） |
| `state/` | 上游健康状态 + 黑白名单（auto/manual 三层）+ 域名映射表 |
| `radar/discovered.json` | 全网自动发现的候选上游（六路，含评分与证据） |
| `radar/candidate_eval.json` | 候选独有度评估（unique = 相对现有库的新增站点数） |
| `probe/*.json` | 四路实测产物（sites/spider/js/csp/drpy），CI 只读复用 |
| `drpy-sandbox/` | drpy Node 沙箱（宿主 + 引擎），CI 每日实测本地 JS 源 |
| `exports/` | 按健康度导出的订阅清单（见上方「健康清单订阅」） |
| `candidate_upstreams.json` | issue 自动收录的候选池（issue → PR） |
| `index.html` | 在线导航页（Pages 同域部署，见上方「在线导航页」） |

## 运行机制

1. **定时**：北京时间每日 03:00 单轮跑拉取合并（`.github/workflows/daily.yml`，cron `0 19 * * *` UTC；2026-09-22 与实现对齐——旧文档写的 06:00/18:00 双轮已过时），成功后自动部署 GitHub Pages（`pages.yml`）；00:30 独立验活（`validate.yml`），周一 11:00 源雷达扫描（`radar.yml`），均支持手动触发。
2. **质量门槛（P0）**：每份上游除 HTTP 可达外，还须通过最小字节数（配置 ≥512B、m3u ≥1KB）/ 最小条目数门槛，并记录内容 sha256 指纹——HTTP 200 不等于有货。
3. **自动停用（P0/P1）**：连续 3 次不达标的上游自动停用（写入 `state/blacklist_auto.txt`），可用后自动恢复；`state/whitelist_manual.txt` 可豁免，`state/blacklist_manual.txt` 可强制拉黑。
4. **拉取与解析（P2 一上游一适配器）**：上游以 kind 分派解析器（`tvbox`=json 配置 / `m3u`=直播列表），新增源只加一条配置，互不影响。
5. **合并去重**：sites 按 key、lives/parses 按 name 全局去重，上游清单顺序即优先级，同名先到先得、不覆盖已有源。
6. **链接代理**：配置内的 GitHub 原链统一加 `ghproxy.net` 前缀；上游换域名时可在 `state/domain_map.json` 配置映射自动改写（P2 域名替换层）。
7. **测速验活**：type 0/1 直连站点并发测活（6 秒超时，失败重试一次），连续失败自动剔除；直播源按央视/卫视/港台/其他分类，逐 URL 测速排序，每频道保留前 3 条。
8. **快照存档（P1）**：每次运行把各上游原始文件存入 `snapshot/<日期>/`（带时间戳文件名），合并产物一并留存，可回滚与失效溯源。
9. **三通道发布（P2）**：产物同时提交 main 分支、Releases（`latest` 标签固定指向最新）与 GitHub Pages 导航页（`https://hebijunge.github.io/tvbox-config/`，2026-09-22 起，白名单组目录、adult 系产物不入）；README 由 `checks.json` 自动回写各上游可用性状态（🟢🟡🔴）。Release 白名单外陈旧资产每日由 `scripts/release_cleanup.py` 自动清理（`adult.json` 按受限产物保留，见下方「受限内容说明」）。
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
| juhe-tvapi | 🟢 可用 | 48064 | `b69a04e7bc88` | 0 | 2026-09-22 06:30:49 |
| qist/jsm | 🟢 可用 | 48137 | `0295e05994b0` | 0 | 2026-09-22 06:30:49 |
| qist/js | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| qist/dianshi | 🟢 可用 | 47535 | `213cd1a7fdd3` | 0 | 2026-09-22 06:30:49 |
| qist/fty | 🟢 可用 | 13087 | `bff9512df27f` | 0 | 2026-09-22 06:30:49 |
| qist/XYQ | 🟢 可用 | 19198 | `701eabdf0716` | 0 | 2026-09-22 06:30:49 |
| qist/0821 | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| qist/0825 | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| qist/0826 | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| qist/0827 | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| qist/367 | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| qist/9918 | 🟢 可用 | 14844 | `0a99c448723d` | 0 | 2026-09-22 06:30:49 |
| qist/99188 | 🟢 可用 | 17359 | `12943dc6aeeb` | 0 | 2026-09-22 06:30:49 |
| gao/js | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| gao/XYQ | 🟢 可用 | 19203 | `82db008c0fa4` | 0 | 2026-09-22 06:30:49 |
| gao/0821 | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| gao/0825 | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| gao/0826 | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| gao/0827 | 🟢 可用 | 9973 | `1c2b6b2f9aa0` | 0 | 2026-09-22 06:30:49 |
| cluntop/jsm | 🟢 可用 | 39195 | `64ed34df8e91` | 0 | 2026-09-22 06:30:49 |
| cluntop/box | 🟢 可用 | 37191 | `8bd8e97001a0` | 0 | 2026-09-22 06:30:49 |
| cluntop/fun | 🟢 可用 | 39183 | `28b47fda08a6` | 0 | 2026-09-22 06:30:49 |
| cluntop/aa | 🟢 可用 | 15833 | `ad1c4cccfcf6` | 0 | 2026-09-22 06:30:49 |
| cluntop/bb | 🟢 可用 | 2829 | `74b99efdc008` | 0 | 2026-09-22 06:30:49 |
| cluntop/wv | 🟢 可用 | 3406 | `67f0882ad97b` | 0 | 2026-09-22 06:30:49 |
| cluntop/yt | ⚫ 已停用 | - | `-` | 3 | - |
| cluntop/test | 🟢 可用 | 1162 | `1777259f409a` | 0 | 2026-09-22 06:30:49 |
| nxppru/jsm | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| nxppru/js | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| nxppru/dianshi | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| nxppru/fty | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| nxppru/XYQ | 🟢 可用 | 19198 | `701eabdf0716` | 0 | 2026-09-22 06:30:49 |
| nxppru/0821 | 🟢 可用 | 23880 | `ad4b43a69284` | 0 | 2026-09-22 06:30:49 |
| nxppru/0825 | 🟢 可用 | 27504 | `b25e72496c84` | 0 | 2026-09-22 06:30:49 |
| nxppru/0826 | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| nxppru/0827 | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| top98 | 🟢 可用 | 16543 | `9e3411a57300` | 0 | 2026-09-22 06:30:49 |
| wex/newwex | 🟢 可用 | 33812 | `bf328c1aff90` | 0 | 2026-09-22 06:30:49 |
| pg/jsm | 🟢 可用 | 34366 | `aca21bfad0bf` | 0 | 2026-09-22 06:30:49 |
| fatcat/tv | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| liu673cn/m | 🚫 黑名单 | - | `-` | 0 | 2026-09-20 06:58:54 |
| deepseek/8815wmz | 🟢 可用 | 26365 | `148468c3697d` | 0 | 2026-09-22 06:30:49 |
| deepseek/gaoops404 | 🟢 可用 | 17628 | `761624cbc30c` | 0 | 2026-09-22 06:30:49 |
| deepseek/gao777520 | 🟢 可用 | 17628 | `761624cbc30c` | 0 | 2026-09-22 06:30:49 |
| tushen6/tvbox | 🟢 可用 | 23470 | `3e68e5a7b625` | 0 | 2026-09-22 06:30:49 |
| victor/tvbox | 🟢 可用 | 35363 | `980421f040e1` | 0 | 2026-09-22 06:30:49 |
| franksun/cks2026 | 🟢 可用 | 24970 | `1cc66beecd13` | 0 | 2026-09-22 06:30:49 |
| guovin-gd-ipv4 | 🟢 可用 | 106329 | `7b6f299f36c3` | 0 | 2026-09-22 06:30:49 |
| guovin-release | 🟢 可用 | 263085 | `30e78fb068be` | 0 | 2026-09-22 06:30:49 |
| 3377-iptv | 🟢 可用 | 578188 | `aa03de219648` | 0 | 2026-09-22 06:30:49 |
| kshao123-tv | 🟢 可用 | 678568 | `bdfd91bd9089` | 0 | 2026-09-22 06:30:49 |
| bestfan-status | 🟢 可用 | 50613 | `fe8748967c87` | 0 | 2026-09-22 06:30:49 |
| bruce0422-iptv | 🟢 可用 | 817965 | `279abd4bb862` | 0 | 2026-09-22 06:30:49 |
| juntv-main | 🟢 可用 | 326085 | `b6e0b76c2663` | 0 | 2026-09-22 06:30:49 |
| zhi35-iptv | 🟢 可用 | 81089 | `607b1fdb7993` | 0 | 2026-09-22 06:30:49 |
| itcoffe-itv | 🟢 可用 | 798857 | `7e80f572af7e` | 0 | 2026-09-22 06:30:49 |
| xuy132-tv | 🟢 可用 | 259983 | `016ff0b03618` | 0 | 2026-09-22 06:30:49 |
| svefnz-iptvn | 🟢 可用 | 72105 | `bbccdf6e3352` | 0 | 2026-09-22 06:30:49 |
| yoursmile66-tvbox | 🟢 可用 | 117777 | `4b8bef904f08` | 0 | 2026-09-22 06:30:49 |
| kilvn-iptv | 🔴 失效 | - | `-` | 2 | - |
| ibert-fmml | 🟢 可用 | 26772 | `ff2ecd34f25e` | 0 | 2026-09-22 06:30:49 |
| ibert-ycl | 🟢 可用 | 35330 | `29b8274ab609` | 0 | 2026-09-22 06:30:49 |
| vbskycn-iptv4 | 🟢 可用 | 117705 | `bbe1807e5e2c` | 0 | 2026-09-22 06:30:49 |
| iill-gather | 🔴 失效 | - | `-` | 2 | - |
| zbds-iptv4 | 🔴 失效 | - | `-` | 2 | - |
| yuechan-iptv | 🟢 可用 | 33963 | `dfd5fc114051` | 0 | 2026-09-22 06:30:49 |
| burningc4-iptv | 🟢 可用 | 8021 | `6a888a9258bd` | 0 | 2026-09-22 06:30:49 |
| zwc456baby-iptv | 🟡 降级 | 6410 | `ef3e8dbfe005` | 2 | - |
| hujingguang-cntv | 🟢 可用 | 10774 | `7ee7d1050d98` | 0 | 2026-09-22 06:30:49 |
| qist/duanju | ⚫ 已停用 | - | `-` | 3 | - |
| qist/duoduo | ⚫ 已停用 | - | `-` | 3 | - |
| qist/wogg | ⚫ 已停用 | - | `-` | 3 | - |
| gao/duanju | ⚫ 已停用 | - | `-` | 3 | - |
| nxppru/duanju | ⚫ 已停用 | - | `-` | 3 | - |
| cluntop/duanju | ⚫ 已停用 | - | `-` | 3 | - |
| auto/1-36s | 🟢 可用 | 21835 | `a64969e74ce2` | 0 | 2026-09-22 06:30:49 |
| auto/2-106s | 🟢 可用 | 69634 | `b71483ed7603` | 0 | 2026-09-22 06:30:49 |
| auto/3-58s | 🟢 可用 | 27984 | `698fa344cf80` | 0 | 2026-09-22 06:30:49 |
| auto/4-47s | 🟢 可用 | 31861 | `ee096b1b5258` | 0 | 2026-09-22 06:30:49 |
| auto/5-80s | 🟢 可用 | 21741 | `9622a8b3f1d9` | 0 | 2026-09-22 06:30:49 |
| auto/6-15s | 🟢 可用 | 3826 | `3a7f5c216ed7` | 0 | 2026-09-22 06:30:49 |
| auto/7-102s | 🟢 可用 | 26329 | `c929d7ddc5f4` | 0 | 2026-09-22 06:30:49 |
| auto/8-151s | 🟢 可用 | 46130 | `e3b73fd47fdc` | 0 | 2026-09-22 06:30:49 |
| auto/9-49s | 🟢 可用 | 31475 | `6c6878f92153` | 0 | 2026-09-22 06:30:49 |
| auto/10-203s | 🟢 可用 | 48029 | `dccdf94ca897` | 0 | 2026-09-22 06:30:49 |
| auto/11-30s | 🟢 可用 | 27424 | `bf143ab3ea48` | 0 | 2026-09-22 06:30:49 |
| auto/12-27s | 🟢 可用 | 8737 | `4cd6fd0b453b` | 0 | 2026-09-22 06:30:49 |
| auto/13-132s | 🟢 可用 | 53027 | `e5995b893b81` | 0 | 2026-09-22 06:30:49 |
| auto/14-36s | 🟢 可用 | 21212 | `7f6e48fd10e3` | 0 | 2026-09-22 06:30:49 |
| auto/15-62s | 🟢 可用 | 30571 | `6ad54de84583` | 0 | 2026-09-22 06:30:49 |
| auto/16-75s | 🟢 可用 | 43652 | `13d988470aa3` | 0 | 2026-09-22 06:30:49 |
| auto/17-46s | 🟢 可用 | 18841 | `69a386e02cf4` | 0 | 2026-09-22 06:30:49 |
| auto/18-168s | 🟢 可用 | 46988 | `6d9f850cfaf6` | 0 | 2026-09-22 06:30:49 |
| auto/19-65s | 🟢 可用 | 28213 | `c28653b1da98` | 0 | 2026-09-22 06:30:49 |
| auto/20-37s | 🟢 可用 | 34760 | `d075229bec43` | 0 | 2026-09-22 06:30:49 |
| auto/21-64s | 🟢 可用 | 34512 | `0108c4461cae` | 0 | 2026-09-22 06:30:49 |
| auto/22-48s | 🟢 可用 | 18598 | `2d83952867f6` | 0 | 2026-09-22 06:30:49 |
| auto/23-88s | 🟢 可用 | 24795 | `6bb0f6525e12` | 0 | 2026-09-22 06:30:49 |
| auto/24-33s | 🟢 可用 | 9973 | `1c2b6b2f9aa0` | 0 | 2026-09-22 06:30:49 |
| auto/25-298s | 🟢 可用 | 51621 | `3f30881d2458` | 0 | 2026-09-22 06:30:49 |
| auto/26-23s | 🟢 可用 | 11386 | `544d32ef2192` | 0 | 2026-09-22 06:30:49 |
| auto/27-64s | 🔴 失效 | 12760 | `ca678e545e57` | 2 | - |
| auto/28-25s | 🟢 可用 | 9830 | `902cfed503fa` | 0 | 2026-09-22 06:30:49 |
| auto/29-6s | 🟢 可用 | 11727 | `67584f126f48` | 0 | 2026-09-22 06:30:49 |
| auto/30-11s | 🟢 可用 | 1614 | `be2bf6a3f432` | 0 | 2026-09-22 06:30:49 |
| auto/31-6s | 🟢 可用 | 1446 | `5ed31290e1db` | 0 | 2026-09-22 06:30:49 |
| auto/32-14s | 🟢 可用 | 3076 | `fe6fc5aab85d` | 0 | 2026-09-22 06:30:49 |
| auto/33-24s | 🔴 失效 | 3116 | `2aa1c30106fe` | 1 | - |
| auto/34-26s | 🔴 失效 | 14743 | `b80dd6c648e6` | 1 | - |
| auto/35-9s | 🟢 可用 | 8567 | `1df7e0a084d7` | 0 | 2026-09-22 06:30:49 |
<!-- availability:end -->

## 接口实测与排序（2026-09-19 起）

产物里的 `sites` 不再是「上游清单顺序 + 无分组」，而是按**分类 → 搜索可用性 → 实测速度**排列。

**实测分三层**（`scripts/probe_sites.py`）：

| 层级 | 判据 | 含义 |
|------|------|------|
| L1 | `?ac=list` 返回 JSON **或 XML** 且含真实 list | 接口有片库 |
| L2 | 热词 `?wd=` 能命中 | 可搜索 |
| L3 | `?ac=detail` 取到播放地址且 m3u8 首片可读 | 能出片 |
| L? | 连接层失败（RST/超时） | 本机网络问题，**不判死** |
| L0 | 200 但无有效数据 / 明确错误码 | 确认不可用 |

其中 XML 是 TVBox `type 0` 接口格式，只认 JSON 会把它们全部误判为不可用。

`type 3` 的源（占 82%，无法直接用 HTTP 验证）走 `scripts/probe_spiders.py`：从本地下好的 drpy 规则文件里提取 `host`、从 `ext` 配置里提取站点地址，再做连通性探测──这样给「访问速度」这个维度补了约 390 个源的数据。

**排序规则**：`分类分组` → `实测可搜优先` → `实测速度升序` → 无速度数据时按结构完整度（规则文件缺失的死源沉底）。分组写入 `site.group`，取值：`采集站` `直连点播` `蜘蛛源` `本地JS` `网盘` `短剧` `其他`。

**反向增强**：探针结论会回写 `searchable` ── 上游自报可搜但实测搜不出结果的源会被标 0，客户端搜索时跳过它们，直接减少无效请求。

**同库镜像去重**（`scripts/dedup_mirrors.py`）：一级按 key、二级按 api+ext 指纹都抓不到「同一片库换域名」（如 `zuidapi.com` 与 `zuidazy.co`、`sdzyapi.com` 与 `xsd.sdzyapi.com`）。该脚本用 L1 抓到的片名集合算 Jaccard 相似度识别同源，证据不足一律不合并。实测 1222 个站点里剔除 61 个重复。

**全网上游发现**（`scripts/discover_upstreams.py`）：**六路**发现 → L0 形态探测（以「能否解析出站点数组」为准，兼容裸数组/嵌套）→ 候选池落 `radar/discovered.json`：

| 路 | 渠道 | 说明 |
|---|---|---|
| 1 | GitHub 代码搜索 | 特征串捞「没人 star 但内容对」的仓（需 token，可翻页） |
| 2 | GitHub 仓库搜索 | topic / 关键词 |
| 3 | 种子 README 递归 | 能捞到**非 GitHub 公开配置站**（szyyds.cn 等），依赖镜像兜底 |
| 4 | 血统反查 | 从已收录仓 owner 反查同作者其他仓（产出最高） |
| 5 | Gitee | 平台搜索 API 已被禁（返回空）、网页被 WAF 405 → 曲线方案：GitHub 搜「引用 gitee.com 的配置」挖仓库全名，再用 Gitee 文件树 API 展开（需 `GITEE_TOKEN`） |
| 6 | 搜索引擎 + 文章页 | Bing 搜 CSDN/博客园/知乎/**微信公众号公开文章**，从正文提取接口。微信不硬爬：只访问搜索引擎已收录的公开文章页（合规） |

**收编标准 = 独有站点数（unique），不是评分**：生态互相抄配置极普遍，实测 score 30 的候选带来 17 个新站点、score 90 的只带来 3 个。
`scripts/evaluate_candidates.py` 算 unique（候选指纹 sha1(api+ext) 不在当前库的数量），`--min-unique 3 --write-canary` 写 canary 池。
**canary 已默认开启**（`EXTRA_UPSTREAMS=1`，daily.yml），失效由自动黑名单兜底；要停用改回 `0`。

**按来源上游保留 spider**（2026-09-19 起，开关 `ORIGIN_SPIDER=1` 默认开）：

每个上游配置都声明自己的顶层 `spider`，而且各不相同（`./jar/pg.jar`、`./jar/pg_upgraded.jar`、
`./jar/pro.jar`、`./jar/WvSpider.jar`、`./jar/fan.txt`、某个 oss 直链…），但合并只能保留**一份**全局 spider。
凡是 `jar` 字段为空、走全局 spider 的源，就会被指向一个**不含它所需爬虫类**的包 ——
客户端加载爬虫时抛 `ClassNotFoundException`，这些源直接变成「坏的」。
实测受影响 **256 个爬虫类 / 359 个源**（`ProxySpider` 23 个、`WvSpider` 11 个…），
而它们在真实 TVBox 里本来都是能用的。

`assign_origin_spiders()` 在依赖收集前给这些源的 `jar` 补上「它来源上游的那份 spider」，
后续 `collect_and_rewrite_deps` 按 origin 落库到 `deps/<上游>/...` 并改写成仓库内路径 + md5，
与站点自带 jar 走同一条路。与全局 spider 指向同一份包的不写（省体积）。
比较用的是**解析后的绝对 URL**，不是字符串 —— 全局值在上一轮产出里已被改写成本地路径
（`./deps/qist/jsm/jar/spider.jar`），字面与上游的 `./jar/spider.jar` 不同却指向同一份包。

关掉：`ORIGIN_SPIDER=0`。

**csp 爬虫源真机实测**：`type 3` 的 `csp_*` 源（约 700 个）必须在 Android 运行时里跑，纯 HTTP 测不了。
做法是自建最小宿主 APK（`DexClassLoader` 加载爬虫 jar + 宿主实现 `crawler.Spider` 基类），
在 root 真机上实跑 **首页 / 分类 / 搜索 / 详情 / 播放** 五关，评级：

| 等级 | 含义 |
|---|---|
| C5 | 五关全通 |
| C4 | 详情通过、播放不可用 |
| C3 | 搜索通过 |
| C2 | 分类通过 |
| C1 | 仅首页通过 |
| C0 | 加载或首页失败 |
| C? | 超时/网络问题，不判死 |

工程在本地 `.workbuddy/csp-test/`（宿主源码 + 构建脚本 + 任务生成 + 结果转换），**不进版本库**；
产物 `probe/csp_probe.json` 提交后由 CI 只读复用（真机测试无法在 Actions 里跑）。

> 注意：部分爬虫依赖的混淆库类在打包时被裁掉（`com.github.catvod.spider.merge.*` 缺失一百余个），
> 这类源的详情/播放关必然失败且**在真实 TVBox 上同样失败**，属源自身缺陷。

**csp 产物时效降权**（`rank_sites.py`）：真机测试无法进 CI，产物会随时间陈旧。实测产物超过 `PROBE_STALE_DAYS`（默认 7 天）不再参与排序——宁可不用，也不拿旧结论给今天的源排位。

**drpy 本地 JS 源：Node 沙箱五关实测**（`scripts/drpy_probe.py` + `drpy-sandbox/`，**已接入 CI 每日跑**）：
约 280 个 type=3 源的 api 指向 `drpy2.min.js`（规则在 `ext` 指向的 .js 文件），纯 HTTP 探针拿不到「能不能搜到片」。
沙箱用与 TVBox 同款引擎（`drpy2 3.9.52beta3`）真跑五关，评级 D5（五关全通）/D4（详情）/D3（搜索）/D2（分类）/D1（首页）/D0（失败）。
两个硬约束：① 宿主 `pdfa` 对纯选择器规则必须返回节点 outerHTML 数组（引擎后续链式解析要用）；② **引擎必须与 `drpy-core-lite.min.js` 同目录**（引擎内部相对自身路径 import 它）。
实测 270 源：D5 8 / D4 3 / D3 9 / D2 77 / D1 42 / D0 131——官源（爱奇艺/腾讯/360）与直播（虎牙/斗鱼）类质量最高。

**直播源实测**（`store.py --probe-lives`）：拉源地址看是否返回频道列表（≥10 频道 healthy、1~9 degraded、拉不到 dead）。实测 144 条：healthy 19 / degraded 15 / dead 110。

**入库与健康体系**（`scripts/store.py`，SQLite `state/tvbox.db`，不入库）：

| 表 | 内容 |
|---|---|
| `interfaces` | 接口当前态：地址/类型/来源/最后检测/健康状态/连续失败 |
| `checks` | 检测历史（追加，滚动保留 30 天；以产物 generated_at 作检测时间保证重复导入幂等） |
| `deps` | 依赖关系：jar / ext 文件 / 本地 js / 全局 spider |
| `upstreams` / `lives` / `runs` | 上游健康 / 直播源 / 运行日志 |

健康分级：`healthy`（实测能搜能播）> `degraded`（能连通但能力弱）> `unknown`（未测/超时，不妄判）> `dead`（实测失败）。
**探针权威性**：五关实测（csp/drpy）> HTTP L级 > js S级 > 连通性——浅探针的结论不能覆盖深探针，否则会出现「五关全通被判 dead」。

观测配套：`health_report.py`（与快照对比，报新增/掉线/恢复/移除，产物 `exports/health_report.json`）、`dep_audit.py`（deps/ 重复与未引用分析，**只报告不删**）。
**一键编排**：`python3 scripts/run_all.py` 本地完整复现 CI 七阶段（镜像测速 → 探针 → drpy 沙箱 → 六路发现 → 评估收编 → 合并 → 入库/导出/日报/审计），支持 `--from N` 从指定阶段续跑。

## 本地运行

```bash
python3 scripts/fetch_merge.py
# 可用环境变量调并发：CONCURRENCY=12 python3 scripts/fetch_merge.py
# 独立验活（不产出配置）：python3 scripts/check_upstreams.py
# 源雷达扫描：python3 scripts/radar_scan.py

# 接口实测（先跑探针，再做去重与排序；daily.yml 已自动串联）
python3 scripts/probe_sites.py --only http          # L1-L3 实测 HTTP 型接口
python3 scripts/probe_spiders.py                    # type3 源连通性实测
python3 scripts/dedup_mirrors.py                    # 同库镜像识别
python3 scripts/rank_sites.py                       # 分类 + 排序（产出 tvbox.ranked.json）
python3 scripts/discover_upstreams.py               # 全网上游发现
# 国内直连被阻断时给探针加代理：--proxy http://127.0.0.1:7890
```

仅依赖 Python 3.8+ 标准库，无第三方包。


## 受限内容说明（2026-09-22 起）

- **仓库根 `adult.json` 为受限内容产物，按所有者 2026-09-22 明确决策保留**：文件与 raw 链接不删除；但它是**历史遗留的独立产物**，不在每日发布白名单内（不随 CI 更新、不进 Release 上传清单、不进 GitHub Pages、不进本 README 与导航页的任何订阅入口）。
- 合规处理与保留并行：保留产物本身的同时，切断其在所有**公开推广通路**的露出（此页即唯一公开说明位），内容分级 18+，仅供自行部署的成年用户按需取用。
- 如需成人分类的最新构建产物：本地运行 `python3 scripts/fetch_merge.py` 并设 `PUBLISH_ADULT=1`（产物只落在本地，不提交、不发布）。
- 评估报告（2026-09-22）曾建议删除仓库根 `adult.json` 以消除合规缺口；所有者裁决为保留，故本轮以「保留 + 通路隔离 + 明示声明」替代删除方案。
