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

## 产物文件

| 文件 | 说明 |
|------|------|
| `tvbox.json` | 合并去重后的统一配置（sites / lives / parses） |
| `list.json` | 上游接口清单，含每条接口的测试记录（响应耗时、分级、合并贡献） |
| `status.json` | 状态可视化：总量统计、上游健康度、直播分类统计、产物指纹、验活剔除明细、Top 接口 |
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
<!-- availability:end -->

## 本地运行

```bash
python3 scripts/fetch_merge.py
# 可用环境变量调并发：CONCURRENCY=12 python3 scripts/fetch_merge.py
# 独立验活（不产出配置）：python3 scripts/check_upstreams.py
# 源雷达扫描：python3 scripts/radar_scan.py
```

仅依赖 Python 3.8+ 标准库，无第三方包。
