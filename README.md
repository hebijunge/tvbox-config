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

## 产物文件

| 文件 | 说明 |
|------|------|
| `tvbox.json` | 合并去重后的统一配置（sites / lives / parses） |
| `list.json` | 上游接口清单，含每条接口的测试记录（响应耗时、分级、合并贡献） |
| `status.json` | 状态可视化：总量统计、可用性分级、站点验活结果、剔除明细、Top 接口 |

## 运行机制

1. **定时**：北京时间每日 06:00 与 18:00 各跑一次（`.github/workflows/daily.yml`），支持手动触发（Actions 页面 Run workflow）。
2. **拉取**：从上游清单（`scripts/fetch_merge.py` 中的 `UPSTREAMS`）逐个拉取配置，失败自动走 ghproxy 备用通道重试。
3. **分级**：完全可用（HTTP 可达 + 合法 JSON + 站点 ≥10）/ 部分可用（1–9 站）/ 不可用（拉取失败或无站点）。
4. **合并去重**：sites 按 key、lives/parses 按 name 全局去重，上游清单顺序即优先级，同名先到先得、不覆盖已有源。
5. **链接代理**：配置内的 GitHub 原链统一加 `ghproxy.net` 前缀。
6. **测速验活**：type 0/1 直连站点并发测活（6 秒超时，失败重试一次），连续失败自动剔除；jar/js/drpy 等无法可靠测活的站点保留并计入 untested。
7. **提交**：产物有变更才 commit + push，无变更跳过。

## 上游清单

| 分组 | 来源 |
|------|------|
| 聚合 CMS | ccAzy/juhe-tvapi（107 个采集源） |
| qist/tvbox | jsm / js / dianshi / fty / XYQ / 0821 / 0825 / 0826 / 0827 / 367 / 9918 / 99188 |
| gaotianliuyun/gao | js / XYQ / 0821 / 0825 / 0826 / 0827 |
| cluntop/tvbox | jsm / box / fun / aa / bb / wv / yt / test |
| nxppru/tvbox | jsm / js / dianshi / fty / XYQ / 0821 / 0825 / 0826 / 0827 |
| 独立接口 | 俊哥 top98（home.jundie.top:81/top98.json） |

## 本地运行

```bash
python3 scripts/fetch_merge.py
# 可用环境变量调并发：CONCURRENCY=12 python3 scripts/fetch_merge.py
```

仅依赖 Python 3.8+ 标准库，无第三方包。
