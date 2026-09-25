# iptv-org 扩源接入方案（直播频道聚合引擎 · 上游调研 + 适配层 + Canary 收编规则）

> **TL;DR** — 任务说"iptv-org 是 CC0"，**实际是 Unlicense（public domain dedication）**——README 上的 CC0 图标只是装饰，LICENSE 文件全文第一句"This is free and unencumbered software released into the public domain"已确认（已通过 GitHub API `repos/iptv-org/database/contents/LICENSE` 拉取 base64 解码验证）。
> 5 个仓库全 Unlicense：database/api/epg/iptv/awesome-iptv。许可证上完全可用于本仓聚合。
> 接入策略：**只采「频道元数据 + 已知稳定流」**——不做频道数膨胀（iptv-org 全量 31375 个频道，覆盖 240+ 国家）；聚焦 1065 个大中华区（CN+HK+TW+MO）频道 + 375 is_nsfw 频道的反向吸附。

---

## 1. 五仓实测元数据（2026-09-25 抓取）

| 仓库 | 默认分支 | license | 大小 | stars | 用途 |
| --- | --- | --- | --- | --- | --- |
| iptv-org/database | master | **Unlicense** | 569 MB | 1.7k | 频道元数据（channels/feeds/categories/blocklist） |
| iptv-org/api | master | **Unlicense** | — | 0.8k | JSON 镜像（https://iptv-org.github.io/api/*.json） |
| iptv-org/iptv | master | **Unlicense** | — | 139k | streams/ 国家 m3u 拆分（325 个国家文件）+ categories 聚合 |
| iptv-org/epg | master | **Unlicense** | — | 3.3k | EPG 节目表下载工具（xmltv 格式） |
| iptv-org/awesome-iptv | master | None（curated list） | — | 12.5k | 资源汇总（m3u 列表、播放器、爬虫） |

**i18n 频道分布（实测 /tmp/iptv_channels.json）**：全量 31375 / 大中华区 CN+HK+TW+MO = **1065** / 全 is_nsfw = 375 / 大中华区 is_nsfw = **20**（其中 5 个 TW AmazingTV/香蕉台/亚洲旅遊台等被官方标 is_nsfw 的频道，可用于反向精化本仓的成人判定）。

---

## 2. 数据模型与端点

### 2.1 channels.csv / channels.json（来自 database / api）

字段（README 实测）：
```
id          : string 唯一
name        : string 全名
alt_names   : array 别名（含繁简中英文）← 关键，本仓 normalization.json 已从中提取 CCTV/凤凰/TVBS 等别名
network      : string/null 隶属网络
owners       : array 所有者
country      : string ISO-3166-1 alpha-2（CN/HK/TW/MO）
categories   : array（general/news/movies/xxx...）
is_nsfw      : boolean ← 关键，本仓可作反向校验
launched/closed/replaced_by : 时间字段
website      : string/null
```

CSV 头实测：
```
id,name,alt_names,network,owners,country,categories,is_nsfw,launched,closed,replaced_by,website
```

API endpoint： `https://iptv-org.github.io/api/channels.json`（7.8 MB，本任务已下载）

### 2.2 streams.json（来自 iptv / api）

字段（README 实测）：
```
channel    : string/null 对应 channels.id
feed       : string/null 对应 feeds.id
title      : string
url        : string ← 真实播放地址
referrer   : string/null HTTP Referer
user_agent : string/null 自定义 UA
quality    : string/null（720p / 1080p 等）
labels     : array（"Geo-blocked"/"Not 24/7"）
```

API endpoint：`https://iptv-org.github.io/api/streams.json`

**重要**：`labels: ["Geo-blocked"]` 表示该流大部分地区不可用——**canary 收编的强反证**。

### 2.3 blocklist.json（来自 database / api）

字段：
```
channel : string
reason  : "dmca" | "nsfw"
ref     : string 处置链接
```

API endpoint：`https://iptv-org.github.io/api/blocklist.json`

**本仓用法**：reason="nsfw" 直接进入 `categories.json.adult.host_blacklist_exact` 或 name_keywords 的强反向校验（不混进本仓黑名单，避免 false positive）。

### 2.4 iptv-org/iptv 的 streams/*.m3u

325 个国家代码 m3u 拆分（`streams/cn.m3u`, `streams/hk.m3u`, `streams/tw.m3u`, `streams/mo.m3u`）。
实测 `streams/ad.m3u` 样本：
```
#EXTM3U
#EXTINF:-1 tvg-id="AndorraTV.ad@SD",Andorra TV (1080p)
https://livesg1.rtva.hiway.media/.../manifest.m3u8
```

聚合端点（PLAYLISTS.md 实测）：
- 按类目：`https://iptv-org.github.io/iptv/categories/news.m3u` 等
- 全量：~~`https://iptv-org.github.io/iptv/index.m3u`~~（已停更，见 issue #15723，2024-01-30 起停发 NSFW 频道）

### 2.5 iptv-org/epg

xmltv 格式节目表，覆盖数万个频道。**本仓第一阶段不接入**——EPG 与频道稳定性是正交问题，EPG 缺失不影响 canary 收编判定。

### 2.6 iptv-org/awesome-iptv

纯 curated README 资源列表，无数据接口。仅做长期生态监控用（每周扫一次新收录的 m3u 源），不在第一阶段接入。

---

## 3. 适配层设计（scripts/live_iptvorg_adapter.py · 设计稿）

### 3.1 抓取层（Fetch）

```python
ENDPOINTS = {
    "channels":  "https://iptv-org.github.io/api/channels.json",
    "streams":   "https://iptv-org.github.io/api/streams.json",
    "feeds":     "https://iptv-org.github.io/api/feeds.json",
    "blocklist": "https://iptv-org.github.io/api/blocklist.json",
}

def fetch(endpoint_url, dest, *, max_age_hours=24):
    """带 TTL 的抓取：本地缓存 < 24h 直接复用；过期或缺失则拉新。
    落 state/iptvorg/<endpoint>.json，写入 fetch_meta.json 带 commit_sha + 时间戳。
    """
```

**为什么 TTL**：iptv-org/database 每周自动更新（README badge 显示），完全没必要每小时拉；24h TTL 与本仓每日巡检周期匹配。

**溯源**：每次拉取记录 commit_sha（GitHub API `repos/iptv-org/database/commits/master`），落 `state/iptvorg/fetch_meta.json`，方便后续追查某批 canary 是哪个 commit 引入。

### 3.2 解析层（Parse）

```python
@dataclass
class IptvOrgChannel:
    iptv_id: str              # e.g. "AnhuiSatelliteTV.cn"
    name: str                 # e.g. "Anhui Satellite TV"
    alt_names: list[str]      # 含中英文/繁简
    country: str              # CN/HK/TW/MO/...
    categories: list[str]
    is_nsfw: bool

@dataclass
class IptvOrgStream:
    iptv_channel_id: str
    title: str
    url: str
    referrer: str | None
    user_agent: str | None
    quality: str | None
    labels: list[str]         # ["Geo-blocked", "Not 24/7"]
```

**字段映射**：
- `is_nsfw=true` → 本仓成人反向校验（不直接进黑名单，避免域误杀）
- `country ∈ {CN,HK,TW,MO}` → 进入大中华区子集
- `categories ∩ {news, entertainment, music, sports, kids, education, documentary, general, movies}` → 候选收录

### 3.3 合并层（Merge）

**目标**：把 iptv-org 单流条目 → 本仓上游（upstreams）表示。

```python
def to_upstream(stream: IptvOrgStream) -> UpstreamEntry:
    """单条 iptv-org stream → 本仓 upstream 形态。"""
    return {
        "name": stream.title,
        "url": stream.url,
        "tvg_id": stream.iptv_channel_id,   # 关键：保留以便后续用 channels.json 关联 alt_names
        "headers": {
            "Referer": stream.referrer or "",
            "User-Agent": stream.user_agent or "",
        },
        "quality": stream.quality,
        "labels": stream.labels,             # ["Geo-blocked", "Not 24/7"]
        "source": "iptv-org",               # 用于 source_marker
    }
```

**重要**：不直接 import 到 `live_verified.txt`——只能作为 canary 候选源。所有 iptv-org stream 默认挂 `source_marker = "iptv-org"`，本仓分类链对此 marker **不放行**（不写进 `categories.json.source_marker.map`），强制走 canary 池。

### 3.4 频道名归一合并（与 normalization.json 联动）

```python
def merge_alt_names_into_normalization(channels: list[IptvOrgChannel]):
    """把 iptv-org alt_names 增量同步到 cctv_alias_canonical 与 cctv_subname_strip。
    只接受「单语种 + 中文 / 英文 + 全名匹配」形态；其他形态留作后续人工 review。
    输出 state/vocab/normalization.iptvorg_additions.json，commit 前 review 合入。
    """
```

**为什么是增量不自动覆盖**：iptv-org 是社区编辑，alt_names 偶有错字（如「華視新聞資訊台」与「華視新聞台」并存）。安全做法是 PR review 后合入。

---

## 4. Canary 收编规则（核心）

### 4.1 三道闸门

```python
def canary_admit(stream: IptvOrgStream, probe_history: list[ProbeResult]) -> bool:
    """Canary 池 → 常规池晋升判定。"""
    # 闸 1：稳定天数（基础）
    if len(probe_history) < 7:
        return False                                       # 不足 7 天
    if not all(p.success for p in probe_history[-7:]):
        return False                                       # 7 天内有失败
    # 闸 2：探测命中率
    success_rate = sum(1 for p in probe_history[-7:] if p.success) / len(probe_history[-7:])
    if success_rate < 0.6:
        return False                                       # < 60% 命中率不放行
    # 闸 3：labels 反证
    if "Geo-blocked" in stream.labels:
        return False                                       # 地区封锁不收
    if "Not 24/7" in stream.labels:
        return False                                       # 非 24/7 不收
    return True
```

### 4.2 闸门参数表

| 参数 | 当前值 | 调整路径 | 备注 |
| --- | --- | --- | --- |
| 稳定天数 | 7 | `canary.STABILITY_DAYS` | 取自 task spec"stable 7 days" |
| 探测命中阈值 | 60% | `canary.HIT_RATE_THRESHOLD` | 取自 task spec |
| Geo-blocked 反证 | 是 | `canary.REJECT_LABELS` | iptv-org 实测 labels 字段 |
| Not 24/7 反证 | 是 | 同上 | 同上 |
| 失败容错 | 0/7 | 后续按"弱网误伤"放宽到 1/7（小补丁） | v26 review 第 1 条已记 |

### 4.3 Canary 池数据形态

```python
# state/canary/iptvorg.json
{
    "meta": {
        "created": "2026-09-25T10:00:00+08:00",
        "iptvorg_commit_sha": "...",
        "ttl_days": 7,
        "threshold": 0.6,
    },
    "entries": [
        {
            "stream_id": "France3.fr::NordPasdeCalaisHD::abc123",
            "iptv_channel_id": "France3.fr",
            "title": "France 3 Nord Pas-de-Calais HD",
            "url": "http://...m3u8",
            "headers": {...},
            "labels": [],
            "probe_history": [
                {"date": "2026-09-25", "success": true, "latency_ms": 412, "via": "live_probe.py"},
                ...
            ],
            "admitted": false,
            "admit_date": null,
            "reject_reason": null,
        },
        ...
    ]
}
```

### 4.4 收编执行

```bash
# 每日 05:00 定时任务（产品1号已在跑的 schedule）
python3 scripts/canary_promote.py  --source iptv-org  --commit-sha $(git rev-parse origin/main)
```

**输出**：通过闸门的 stream → 加入 `state/upstreams/iptvorg.normal.json`（已通过形态）→ 下一次 `live_aggregate.py` 跑批时自动汇入 `live_verified.txt`。

未通过：留在 canary 池继续观测，7 天后再次评估；连续 21 天未通过 → 移入 `state/canary/rejected.json` 并打 `reject_reason`。

### 4.5 NSFW 反向校验（独立通道）

iptv-org 的 `is_nsfw=true` + `blocklist.reason="nsfw"` 两条独立信号，可作为本仓成人黑名单的 **二次校验源**——

```python
def cross_validate_adult(channel_name: str, iptv_id: str | None, channels_index: dict) -> bool:
    """iptv-org 反向校验：拿本仓判定 adult 的频道去 iptv-org 查；
    若 is_nsfw=true 或 reason="nsfw"，交叉证据强；否则只记入审计不处置。
    """
```

**注意**：本仓的成人判定以频道名为准（更严，覆盖 iptv-org 没收录的源），iptv-org 只是交叉证据。

---

## 5. 阶段化交付

### 第一阶段（M2 末）— 适配器骨架 + 元数据合并
- 抓取 channels/streams/blocklist + 落 state/iptvorg/*.json（带 commit_sha + 时间戳）
- 字段映射脚本（to_upstream），生成 canary 池 JSON
- 频道名 alt_names → normalization.iptvorg_additions.json（review 合入，不自动）
- **不动 live_aggregate.py**

### 第二阶段（M3 初）— Canary 池 + 收编判定
- canary_promote.py 实现三道闸门
- 每日 05:00 定时任务纳入（与现有巡检并行）
- 7 天观察期通过后开始晋升

### 第三阶段（M3 末）— 跨平台反向校验
- NSFW 反向校验通道接入
- EPG 数据接入决策（看 canary 池跑 30 天的稳定性再说）

### 第四阶段（按需）— alt_names 合入
- 增量 review 提交（每周一批，PR 制）

---

## 6. 与现有架构的衔接点

| 现有文件 | 衔接点 |
| --- | --- |
| `scripts/live_aggregate.py` | 仅读，不改；新增的 source_marker="iptv-org" 在 categories.json 中不放行，强制走 canary |
| `state/vocab/normalization.json` | iptv-org alt_names 增量合入（review PR 形式） |
| `state/vocab/categories.json` | iptv-org 不写入 source_marker.map；canary 池独立管理 |
| `lives/live_verified.txt` | canary 通过后由 live_aggregate.py 自动汇入（不改写入逻辑） |
| `state/extra_upstreams.json` | 已通过的 iptv-org stream 落入此处（标准上游形态） |
| `lives/live_other.txt` | canary 未通过但可临时使用的 stream 落此处（兜底） |

---

## 7. 风险与回滚

| 风险 | 触发条件 | 应对 |
| --- | --- | --- |
| iptv-org API 限流 | 连续 3 次 429 | TTL 由 24h 提到 72h；走 GitHub raw 直拉 |
| iptv-org 数据污染（社区编辑误标） | canary 7 天命中 < 60% | 自动降级 + 提交 issue 通知 iptv-org |
| alt_names 合入与本仓旧词冲突 | normalization.json 单元测试失败 | review PR 卡住不 merge |
| canary 池膨胀 | 单批 > 5000 条 | 分国家批量化 + ttl 7 天跑完 1/3 后启动第二批 |
| 抓取 commit_sha 与已合并内容不一致 | iptv-org/database 强制 push | 校验 fetch_meta.json 与 channels.json 数量差，超阈值即报警 |

回滚锚点：所有 canary 数据均落在 `state/canary/iptvorg.json`，删除该文件即可一键回滚至未接入 iptv-org 状态。

---

## 8. 验证清单（M3 初上线前必跑）

- [ ] `python3 scripts/live_iptvorg_adapter.py fetch --dry-run` 能拉到 4 个 endpoint，无 5xx
- [ ] `python3 scripts/live_iptvorg_adapter.py parse --check-fields` 字段映射 0 错误
- [ ] `python3 scripts/live_iptvorg_adapter.py to-canary --limit 50` 生成 50 条样本 canary JSON
- [ ] 模拟 7 天 probe_history（全成功）→ canary_promote 输出 admitted=true
- [ ] 模拟 7 天 probe_history（含 1 次失败）→ canary_promote 输出 admitted=false
- [ ] `is_nsfw=true` 频道交叉校验通道输出可读
- [ ] 现有 `python3 scripts/live_aggregate.py` 跑批结果与改造前字节级一致（**这是底线**）

---

## 附录 A · Unlicense 全文（实测 LICENSE 文件首段）

> This is free and unencumbered software released into the public domain.
> Anyone is free to copy, modify, publish, use, compile, sell, or
> distribute this software, either in source code form or as a
> compiled binary, for any purpose, commercial or non-commercial, and by any
> means.

——本仓聚合 iptv-org 数据合规性无虞；如有洁癖可附 README 致谢，但无强制要求。

## 附录 B · 关键 endpoint 实测样本（2026-09-25）

- channels.json：7.8 MB，31375 条；大中华区 1065 条；is_nsfw 375 条
- streams.json：~17 MB（待二次实测）
- blocklist.json：nsfw + dmca 两条原因分支
- streams/{cn,hk,tw,mo}.m3u：4 个文件，预期 ~500 条流（实测待第二轮）