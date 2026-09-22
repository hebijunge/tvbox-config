#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox 配置每日拉取合并脚本 v2（stdlib only，无第三方依赖）

流程：拉取上游清单（一上游一适配器）→ 内容质量门槛（最小字节/行数 + sha256 指纹）
      → 连续不过自动停用（黑白名单三层）+ 停用上游低频探活回捞
      → 合并去重（按 key 冲突时健康度仲裁 + api/ext 指纹二级去重 + 同内容镜像短路）
      → 测速验活（type 0/1 直连站点）→ 连续 N 轮失败才剔除（站点验活历史记忆，通过自动回捞）
      → 直播源分类测速优选（央视/卫视/港台分组 txt，测速全挂频道保底收录）
      → 快照存档（snapshot/<日期>/）→ 输出 tvbox.json / list.json / status.json / checks.json
      → README 可用性锚点回写

对应第二期调研路线图：
  P0 上游验活门槛（joevess 教训 + Guovin 机制）
  P0 直播源上游收编（Guovin/iptv-api gd 分支 + Releases 双通道）
  P1 每日快照存档（kimwang1978/collect-txt 模式）
  P1 黑白名单分文件（kimwang + Guovin 模式）
  P1 分类测速优选（Supprise0901/TVBox_live 模式）
  P1 checks.json 校验产物 + 内容指纹 + 通过时间（azhansy/ds-tvbox 模式）
  P2 一上游一适配器（HerbertHe/iptv-sources 模式）
  P2 域名替换层（hl128k/tvbox 思路）
"""
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import urllib.error
import concurrent.futures as cf
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts 内互相导入
from config_decode import decode_config   # 吸收点 P1-1：混淆配置解码链（独立实现）

BEIJING = timezone(timedelta(hours=8))
UA = {"User-Agent": "okhttp/3.15", "Accept": "*/*"}
FETCH_TIMEOUT = 15          # 单次拉取超时（秒）

# 吸收点 P1-3：上游拉取 UA 池（设计借鉴自参考仓库调研，代码独立实现）。
# 拉取失败时轮换 UA + 指纹头重试，覆盖部分上游对单一 okhttp UA 的选择性拦截。
UA_POOL_VOD = [
    {"User-Agent": "okhttp/3.15", "X-Requested-With": "com.iptvbox.tvbox"},
    {"User-Agent": "okhttp/4.9.3", "X-Requested-With": "com.iptvbox.tvbox"},
    {"User-Agent": "TVBox/1.0.0", "X-Requested-With": "com.github.tvbox.osc"},
    {"User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; Pixel 3 XL Build/SQ1A.220205.002)", "X-Requested-With": "com.iptvbox.tvbox"},
    {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36", "X-Requested-With": ""},
    {"User-Agent": "okhttp/3.12.0", "X-Requested-With": "com.box.tvbox"},
]
UA_ROTATE_MAX = int(os.environ.get("UA_ROTATE_MAX", "3"))   # 单 URL 的 UA 轮换上限（含首次）

TEST_TIMEOUT = 6            # 站点验活单次超时（秒）
CONCURRENCY = int(os.environ.get("CONCURRENCY", "20"))
MAX_BODY = 4096             # 验活最多读取字节数
# O7 ghproxy 单点依赖缓解：拉取侧按镜像列表依次轮换；产出配置改写固定用主镜像（静态 JSON 无法做客户端容灾）
# 镜像排序依据（2026-09-19 实测本项目文件）：gh-proxy.com TTFB 657ms/1551KB/s 双优；
# gh.zwy.one 624KB/s（用户侧 Release 实测 7119KB/s）；ghproxy.cxkpro.top 434KB/s（用户侧 5292KB/s）；
# v6.gh-proxy.org 260KB/s；ghproxy.net 47KB/s（慢管但稳定）；ghfast.top/gh.llkk.cc/rwa.ihtw.moe/ghp.ci
# 沙箱侧限流/502 不可作首选，留作轮换兜底（GitHub runner 与用户侧网络画像不同，可能表现更好）。
GH_MIRRORS = [m.strip() for m in os.environ.get(
    "GH_MIRRORS",
    "https://gh-proxy.com/,https://gh.zwy.one/,https://ghproxy.cxkpro.top/,https://v6.gh-proxy.org/,"
    "https://ghproxy.net/,https://ghfast.top/,https://gh.llkk.cc/,https://raw.ihtw.moe/,https://ghp.ci/"
).split(",") if m.strip()]
GHPROXY = GH_MIRRORS[0] if GH_MIRRORS else "https://gh-proxy.com/"

REPO_RAW = "https://raw.githubusercontent.com/hebijunge/tvbox-config/main"

# ---- P0：内容质量门槛参数 ----
MIN_BYTES_TVBOX = int(os.environ.get("MIN_BYTES_TVBOX", "512"))    # 配置类上游最小字节数
MIN_ITEMS_TVBOX = int(os.environ.get("MIN_ITEMS_TVBOX", "1"))      # 至少含多少条 sites/lives/parses
CANARY_MIN_BYTES = int(os.environ.get("CANARY_MIN_BYTES", "5120"))  # canary 上游内容校验最小字节（batch11 P1-1：HEAD 200 + 5KB 内容校验）
MIN_BYTES_M3U = int(os.environ.get("MIN_BYTES_M3U", "1024"))       # m3u 类上游最小字节数
MIN_ENTRIES_M3U = int(os.environ.get("MIN_ENTRIES_M3U", "50"))     # m3u 至少多少条频道

# ---- P0/P1：连续失败自动停用（黑白名单）----
STATE_FILE = os.environ.get("STATE_FILE", "state/upstreams_state.json")
BLACKLIST_AUTO = os.environ.get("BLACKLIST_AUTO", "state/blacklist_auto.txt")
BLACKLIST_MANUAL = os.environ.get("BLACKLIST_MANUAL", "state/blacklist_manual.txt")
WHITELIST_MANUAL = os.environ.get("WHITELIST_MANUAL", "state/whitelist_manual.txt")
FAIL_LIMIT = int(os.environ.get("UPSTREAM_FAIL_LIMIT", "3"))       # 连续 N 次不达标自动停用
# 2026-09-21 点播+容错线：黑名单单轮安全阀（来自 riowang88 设计文档）。
# 单轮「本次停用」数超过上游总数 30% 时，判定为网络抖动等系统性误判而非
# 上游集体长期失效：只警告、不落盘（本轮停用全部回滚，fail_count 保留，
# 真失效的源下一轮仍会正常触发停用），防止一次抖动误杀大量源。
# 与连续 3 次失败自动停用互补：黑名单管长期失效，安全阀管单轮抖动。
BLACKLIST_ROUND_CAP_RATIO = float(os.environ.get("BLACKLIST_ROUND_CAP_RATIO", "0.30"))
# 2026-09-21 点播+容错线：空产物守卫（借鉴 tengxiaobao「聚合失败保留上次缓存」）。
# 本轮 sites/lives/parses 任一为空、或较上一版已提交产物萎缩超 80% 时，
# 判定本轮聚合结果异常：跳过全部产物写入与提交/发布（exit 2），保留上次
# 缓存，写 state/guard_last.json 日报下轮重试。与安全阀互补：安全阀管
# 「单轮停用抖动」，守卫管「合并产物塌方」。
EMPTY_GUARD_DROP_RATIO = float(os.environ.get("EMPTY_GUARD_DROP_RATIO", "0.80"))
PROBE_INTERVAL_DAYS = int(os.environ.get("DISABLED_PROBE_DAYS", "7"))  # O2 停用上游每隔 N 天探活回捞

# O3 站点验活历史记忆（连续 N 轮失败才剔除，通过自动回捞）
SITE_STATE_FILE = os.environ.get("SITE_STATE_FILE", "state/sites_state.json")
SITE_FAIL_LIMIT = int(os.environ.get("SITE_FAIL_LIMIT", "3"))
# 短剧/成人分类人工覆盖表：{"<site key>": "short|adult|vod"}，优先级高于关键词分类
CATEGORY_OVERRIDE_FILE = os.environ.get("CATEGORY_OVERRIDE_FILE", "state/category_overrides.json")

# ---- P1：快照存档 ----
SNAPSHOT_DIR = os.environ.get("SNAPSHOT_DIR", "snapshot")
SNAPSHOT_RETENTION_DAYS = int(os.environ.get("SNAPSHOT_RETENTION_DAYS", "14"))

# ---- P1：直播分类测速优选 ----
LIVE_SPEEDTEST = os.environ.get("LIVE_SPEEDTEST", "1") == "1"
LIVE_TIMEOUT = int(os.environ.get("LIVE_TIMEOUT", "4"))
LIVE_CONCURRENCY = int(os.environ.get("LIVE_CONCURRENCY", "24"))
LIVE_MAX_URLS = int(os.environ.get("LIVE_MAX_URLS", "1200"))       # 单轮测速 URL 总量上限
LIVE_PER_CHANNEL = int(os.environ.get("LIVE_PER_CHANNEL", "3"))    # 每频道保留条数
LIVE_FALLBACK_CHANNELS = int(os.environ.get("LIVE_FALLBACK_CHANNELS", "100"))  # O6 测速全挂频道的保底收录上限
LIVE_MIN_SPEED = float(os.environ.get("LIVE_MIN_SPEED", "0.2"))    # MB/s；低于此速率降权排序（只降权不删除）
LIVE_SPEED_RANGE = int(os.environ.get("LIVE_SPEED_RANGE", str(1 << 20)))  # 测速抽样字节数（HTTP Range 抽 1MB 实测吞吐）
LIVES_DIR = os.environ.get("LIVES_DIR", "lives")
CHECKS_FILE = os.environ.get("CHECKS_FILE", "checks.json")
DOMAIN_MAP_FILE = os.environ.get("DOMAIN_MAP_FILE", "state/domain_map.json")
README_FILE = os.environ.get("README_FILE", "README.md")

# 上游清单（点播配置类）：顺序仍影响收录次序，但同名 key 冲突时按来源健康分仲裁（O1）——
# 最近成功时间新、连续失败少的上游接管；健康分相同保持先到先得（不误伤已有源、避免抖动）
# 一上游一适配器：kind 决定拉取后如何解析（tvbox=json 配置 / m3u=直播列表）
UPSTREAMS = [
    {"name": "juhe-tvapi", "kind": "tvbox",
     "url": "https://raw.githubusercontent.com/ccAzy/juhe-tvapi/main/config.json"},
    {"name": "qist/jsm", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/jsm.json"},
    {"name": "qist/js", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/js.json"},
    {"name": "qist/dianshi", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/dianshi.json"},
    {"name": "qist/fty", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/fty.json"},
    {"name": "qist/XYQ", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/XYQ.json"},
    {"name": "qist/0821", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0821.json"},
    {"name": "qist/0825", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0825.json"},
    {"name": "qist/0826", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0826.json"},
    {"name": "qist/0827", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/0827.json"},
    {"name": "qist/367", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/367.json"},
    {"name": "qist/9918", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/9918.json"},
    {"name": "qist/99188", "kind": "tvbox", "url": "https://raw.githubusercontent.com/qist/tvbox/master/99188.json"},
    {"name": "gao/js", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/js.json"},
    {"name": "gao/XYQ", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/XYQ.json"},
    {"name": "gao/0821", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0821.json"},
    {"name": "gao/0825", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0825.json"},
    {"name": "gao/0826", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0826.json"},
    {"name": "gao/0827", "kind": "tvbox", "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0827.json"},
    {"name": "cluntop/jsm", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/jsm.json"},
    {"name": "cluntop/box", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/box.json"},
    {"name": "cluntop/fun", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/fun.json"},
    {"name": "cluntop/aa", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/aa.json"},
    {"name": "cluntop/bb", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/bb.json"},
    {"name": "cluntop/wv", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/wv.json"},
    {"name": "cluntop/yt", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/yt.json"},
    {"name": "cluntop/test", "kind": "tvbox", "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/test.json"},
    {"name": "nxppru/jsm", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/jsm.json"},
    {"name": "nxppru/js", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/js.json"},
    {"name": "nxppru/dianshi", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/dianshi.json"},
    {"name": "nxppru/fty", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/fty.json"},
    {"name": "nxppru/XYQ", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/XYQ.json"},
    {"name": "nxppru/0821", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0821.json"},
    {"name": "nxppru/0825", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0825.json"},
    {"name": "nxppru/0826", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0826.json"},
    {"name": "nxppru/0827", "kind": "tvbox", "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/0827.json"},
    {"name": "top98", "kind": "tvbox", "url": "http://home.jundie.top:81/top98.json"},
    # ---- 2026-09-19 接K20260729 清单验活后新增（实测报告：飞书云文档 WinbdkIMEoGWfNxVTrVcqtpGnxs）----
    # 王二小 kstore：96 sites（spider 2026-09-17 版），直连 152ms；容灾备选 http://tv.999888987.xyz/（63 sites 旧版）暂不收
    {"name": "wex/newwex", "kind": "tvbox", "url": "https://9280.kstore.vip/newwex.json",
     "mirrors": ["http://new.xn--4kq62z5rby2qupq9ub.top"]},
    # PG：74 sites / 29 lives；spider 为相对路径 ./pg.jar，依赖同源 jar（依赖收集失败时走自动黑名单）
    {"name": "pg/jsm", "kind": "tvbox", "url": "https://www.252035.xyz/p/jsm.json"},
    # 肥猫：39 sites；必须用 /tv 路径（根路径 / 为损坏配置）；IDN 域名已转 punycode 供 urllib 直连
    {"name": "fatcat/tv", "kind": "tvbox", "url": "http://xn--z7x900a.net/tv"},
    # 老刘备：234 sites（容错解析通过）；ghproxy.net 为单点依赖，失效时会被自动停用
    {"name": "liu673cn/m", "kind": "tvbox", "url": "https://ghproxy.net/https://raw.githubusercontent.com/liu673cn/box/main/m.json",
     "mirrors": ["https://raw.githubusercontent.com/liu673cn/box/main/m.json"]},  # 吸收点 P1-2：消除 ghproxy.net 单点
    # ---- 2026-09-20 DeepSeek 报告实测收录（仅纯 JSON 可合并源；图片伪装/加密/多仓类进订阅清单不进此处，避免被判 dead 进黑名单）----
    {"name": "deepseek/8815wmz", "kind": "tvbox", "url": "https://8815.kstore.vip/tvbox/wmz"},          # 105 sites
    {"name": "deepseek/gaoops404", "kind": "tvbox", "url": "https://raw.giteeusercontent.com/gaoops404/tvbox-config/raw/main/tvbox.json"},  # 52 sites
    {"name": "deepseek/gao777520", "kind": "tvbox", "url": "https://gitlab.com/gao777520/tvbox-config/raw/main/tvbox.json"},  # 52 sites
    # ---- 2026-09-21 点播+容错线：六批调研新增上游（jsDelivr 实拉 + parse_tvbox 等效验证后纳入）----
    # tushen6/Tomorrow（2278★，2026-09-21 当日有推送）：根目录 tvbox.json 33 sites / 1 lives / 9 parses
    {"name": "tushen6/tvbox", "kind": "tvbox", "url": "https://raw.githubusercontent.com/tushen6/Tomorrow/master/tvbox.json"},
    # victor1616888/TVBOX-Q（2026-09-21 当日有推送）：根目录 tvbox.json 116 sites / 12 lives / 9 parses（含 // 行内注释，经状态机清洗可解析）
    {"name": "victor/tvbox", "kind": "tvbox", "url": "https://raw.githubusercontent.com/victor1616888/TVBOX-Q/master/tvbox.json"},
    # franksun1211/TVBOX（228★，2026-09-12 推送）：CKS2026.json 60 sites / 2 lives / 4 parses（内含 /* */ 块注释，经状态机清洗可解析）；
    # XCTV.json（APP/TVBoxOSC/XC/，教育向直播源）转直播线任务处理；qiaoji8.json 等其余 19 个配置已登记 candidate_upstreams.json 候选池走 canary 收编
    {"name": "franksun/cks2026", "kind": "tvbox", "url": "https://raw.githubusercontent.com/franksun1211/TVBOX/main/CKS2026.json"},
    # ---- 2026-09-22 吸收 lubin776/tvbox-api-backup list.txt：45 条接口与既有清单全量对比去重后新增 20 条 ----
    # 对比基线：UPSTREAMS + LIVE_UPSTREAMS + SHORTS_ADULT + canary(state/extra_upstreams.json) + candidate_upstreams.json。
    # 重复不加：肥猫(fatcat/tv)、挺好、小马、心魔、俊宇(top98)、clun、动漫（既有 UPSTREAMS 或 canary 已收）；
    #   王二小/王二小2线（aiwex.json 与既有 wex/newwex 字节级一致）。
    # 同内容变体不重复收：饭太硬 2~6 线（与主线 19683B 字节一致）、嗷呜 /tv 与 config.webp（与 aowu.json 同内容 78 sites）。
    # 不可用不硬塞（验活证据同期归档）：潇洒(APP清单非配置)、南风两线(AES 布局 decode 链解不开)、
    #   嗨哥魔改(## 注释行主管线不识别)、时光(字符串含裸控制符 json.loads 拒收)、传说/分享者(返回 HTML)、
    #   驸马(404)、小米(占位文本「后会有期」)。
    # 中文路径/IDN 一律 percent-encode/punycode 供 urllib 直连；伪装扩展名（.png 等）内容已实测可被 decode 链解析。
    {"name": "bocai/x4pro", "kind": "tvbox", "url": "https://0.12yue.de5.net/5/x4pro.json"},  # 菠菜pro：206 sites
    {"name": "bocai/x4", "kind": "tvbox", "url": "https://0.12yue.de5.net/5/x4.json"},        # 菠菜园：55 sites
    {"name": "bocai/update", "kind": "tvbox",
     "url": "https://0.12yue.de5.net/tvbox/%E6%9B%B4%E6%96%B0%E4%B8%93%E7%94%A8%E6%8E%A5%E5%8F%A3.json"},  # 更新专用接口：11 sites
    {"name": "xingfu/bbm", "kind": "tvbox", "url": "http://150.158.52.248/tgyg/bbm.json"},    # 幸福年年：127 sites / 9 lives
    # 饭太硬主线：JPEG 伪装壳，decode 链 shell_base64 解出；47 sites / 6 lives（2~6 线同内容字节一致未收）
    # 第七批（2026-09-22）：4 个同源镜像（sha256 与主 URL 逐字节一致）并入 mirrors
    {"name": "fantaiying/tv", "kind": "tvbox", "url": "http://www.xn--sss604efuw.net/tv",
     "mirrors": ["http://www.xn--sss604efuw.cc/tv", "http://fty.xxooo.cf/tv",
                 "http://fty.888484.xyz/tv", "http://fty.333232.xyz/tv"]},
    # 嗷呜：三线同内容（aowu.json / 嗷呜.tv 伪装 / config.webp 壳），收无解码依赖的纯 JSON 线；78 sites / 7 lives
    {"name": "aowu/kstore", "kind": "tvbox", "url": "https://9763.kstore.vip/aowu.json"},
    # 少儿频道：25 sites（纯 JSON 无直播）
    {"name": "shaoer/tv", "kind": "tvbox",
     "url": "https://0.12yue.de5.net/5/tv%E5%B0%91%E5%84%BF.json"},
    {"name": "feimao2/catvod", "kind": "tvbox", "url": "https://jk.catvod.site"},              # 肥猫2线：22 sites（与 fatcat/tv 不同内容）
    {"name": "laozhang/serv00", "kind": "tvbox", "url": "https://zhangqun1818.serv00.net/zq/api.json"},  # 老张：19 sites
    # 周J：27 sites / 4 lives；沙箱直连 raw 超时，主 URL 走 gh-proxy.com（同 liu673cn/m 口径，直连留作镜像）
    {"name": "zhouj/box", "kind": "tvbox",
     "url": "https://gh-proxy.com/raw.githubusercontent.com/zhoujck/config/main/box",
     "mirrors": ["https://raw.githubusercontent.com/zhoujck/config/main/box"]},
    {"name": "cainisi/tv", "kind": "tvbox", "url": "https://tv.xn--yhqu5zs87a.top"},           # 菜妮丝：55 sites
    {"name": "xiaxia/qk4k", "kind": "tvbox", "url": "https://11405.kstore.space/xiaye/qk4k.json"},  # 夏夏影视：43 sites
    {"name": "xiaokai/kai", "kind": "tvbox", "url": "https://jihulab.com/jyqhkd/kd/-/raw/main/kai.json"},  # 小凯：28 sites
    {"name": "dongli/chigua", "kind": "tvbox", "url": "https://chigua.eu.org"},                # 东篱：93 sites / 12 lives（壳 base64 解码）
    {"name": "juwan/xhz", "kind": "tvbox", "url": "http://xhztv.top/xhz"},                     # 聚玩：54 sites
    # 哈吉米：伪装 .png 扩展名实为纯 JSON；175 sites / 11 lives（URL 已 percent-encode）
    {"name": "hajimi/kstore", "kind": "tvbox",
     "url": "https://17264.kstore.space/%E5%93%88%E5%9F%BA%E7%B1%B3.png"},
    {"name": "zhenliu/cccimg", "kind": "tvbox",
     "url": "https://cccimg.com/down.php/7d1f30263b3f2bf3deda2d7faeef4844.zhen6"},            # 真六：47 sites / 9 lives
    # 小虎斑：2423 AES-128-CBC 加密配置，decode 链 aes2423 解出；64 sites / 1 lives（IDN+中文路径已转码）
    {"name": "xiaohuban/hb", "kind": "tvbox",
     "url": "http://hb.xn--yet24tmq1a.site:25252/%E4%BB%85%E4%BE%9B%E6%B5%8B%E8%AF%95"},
    # 天神：PNG 伪装 + 壳 + AES 双层解码链；102 sites；主 URL 走 raw 直连（实测可达），gh-proxy 留作镜像
    {"name": "tianshen/iy", "kind": "tvbox",
     "url": "https://raw.githubusercontent.com/IY-CPU/IY/main/%E5%A4%A9%E7%A5%9EIY.png",
     "mirrors": ["https://gh-proxy.com/raw.githubusercontent.com/IY-CPU/IY/main/%E5%A4%A9%E7%A5%9EIY.png"]},
    # 星微Vip：伪装路径「测试勿传」实为纯 JSON；60 sites / 3 lives（URL 已 percent-encode）
    {"name": "xingwei/kstore", "kind": "tvbox",
     "url": "https://7337.kstore.vip/xw/%E6%B5%8B%E8%AF%95%E5%8B%BF%E4%BC%A0"},
    # ---- 第七批 P1 点播大源入口收编（2026-09-22，task 7688297741897698251）----
    # 来源：Lightconer/tvbox-ysc-config config/sources.json（34 条）+ Supprise0901/tvbox_live warehouse.txt（66 条）。
    # 全量 100 条经三层归一去重 + 逐条验证：21 条新收（下）、5 条并入既有 mirrors、12 条与既有
    # UPSTREAMS/canary URL 重复、10 条内容同源不重收、51 条不可用（502/404/SSL/格式坏）不硬塞。
    # 验证口径：fetch 成功 + decode_config + parse_tvbox 过 MIN_BYTES/MIN_ITEMS 门槛；中文域名转 punycode、
    # 中文路径 percent-encode（生产 fetch_merge 同口径）；裸 IP 条目为单点源，失效由自动黑名单兜底。
    # 王二小放牛娃 tvbox 面：63 sites / 2 lives（另一面 new.王二小放牛娃.top 与 wex/newwex 同内容，已并入其 mirrors）
    {"name": "ysc/wangxiaoer-tvbox", "kind": "tvbox", "url": "http://tvbox.xn--4kq62z5rby2qupq9ub.top"},
    # ---- Supprise0901/api 仓单（gh-proxy 前缀 blob 链接实测可直出 JSON，保持已验证形态）----
    # 天天&巧计：31 sites / 1 live / 5 parses
    {"name": "sv/tiantian-qiaoji", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/tiantian.json"},
    # api 总仓：90 sites / 8 lives / 15 parses
    {"name": "sv/api", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/api.json"},
    # 肥猫 blob 面：50 sites；fatcat/tv 主源本轮三次 502 无法做内容比对，归属待复验（自动黑名单兜底）
    {"name": "sv/feimao", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/feimao.json"},
    # 王二小 blob 面：78 sites / 2 lives
    {"name": "sv/wangxiaoer", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/wangxiaoer.json"},
    # 小布点：74 sites
    {"name": "sv/xiaobudian", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/xiaobudian.json"},
    # 小米：32 sites / 1 live
    {"name": "sv/xiaomi", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/xiaomi.json"},
    # 小傻：134 sites / 1 live / 9 parses（本批最大面之一）
    {"name": "sv/xiaosa", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://github.com/Supprise0901/api/blob/main/xiaosa.json"},
    # 龙在此(关注TG@stymei1)：234 sites / 3 lives / 27 parses，单接口站点数之最
    {"name": "sv/liucn-m", "kind": "tvbox", "url": "https://raw.liucn.cc/box/m.json"},
    # 科技长青：72 sites（kstore 直连）
    {"name": "sv/changqing", "kind": "tvbox", "url": "https://13413.kstore.space/tv/changqing.json"},
    # 东曦视界：82 sites / 1 live / 10 parses
    {"name": "sv/iqinu", "kind": "tvbox", "url": "https://box.iqinu.com/"},
    # 分享者：168 sites / 9 lives / 25 parses（maoystv/6）
    {"name": "sv/fenxiangzhe", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://raw.githubusercontent.com/maoystv/6/main/001.json"},
    # 乐哥短剧：41 sites / 1 live / 15 parses（短剧专面，lege0001/TVbox）
    {"name": "sv/lege-dj", "kind": "tvbox",
     "url": "https://gh-proxy.org/https://raw.githubusercontent.com/lege0001/TVbox/refs/heads/main/TV/dj.json"},
    # 真心(FongMi-z)：43 sites（www.252035.xyz 与 pg/jsm 同主机不同路径）
    {"name": "sv/fongmi-z", "kind": "tvbox", "url": "https://www.252035.xyz/z/FongMi.json"},
    # 小哥哥：86 sites / 1 live；裸 IP:3 单点源，失效走自动黑名单
    {"name": "sv/xiaogege", "kind": "tvbox", "url": "http://47.96.82.41:3/"},
    # 全影多仓(影视仓.com)：43 sites / 3 lives（IDN 已转 punycode）
    {"name": "sv/quanying", "kind": "tvbox", "url": "http://xn--5mqx81b535a.com/"},
    # ---- play.iptv365.org 系列（路径含中文，已 percent-encode；round3 复测全过）----
    # 天微：97 sites
    {"name": "sv/tianwei", "kind": "tvbox",
     "url": "https://play.iptv365.org/%E5%A4%A9%E5%BE%AE/api.json"},
    # 天天开心：126 sites（本批站点数次高）
    {"name": "sv/tiantiankaixin", "kind": "tvbox",
     "url": "https://play.iptv365.org/%E5%A4%A9%E5%A4%A9%E5%BC%80%E5%BF%83/api.json"},
    # 香雅情：55 sites
    {"name": "sv/xiangyaqing", "kind": "tvbox",
     "url": "https://play.iptv365.org/%E9%A6%99%E9%9B%85%E6%83%85/api.json"},
    # 白嫖：9 sites
    {"name": "sv/baipiao", "kind": "tvbox",
     "url": "https://play.iptv365.org/%E7%99%BD%E5%AB%96/api.json"},
    # 戏曲音乐：10 sites
    {"name": "sv/xiquyinyue", "kind": "tvbox",
     "url": "https://play.iptv365.org/%E6%88%8F%E6%9B%B2%E9%9F%B3%E4%B9%90/api.json"},
]

# P0：直播源上游。2026-09-21 直播线融合扩容（六批调研落地，task 7687996812807916527）：
# 原 2 条（guovin 双通道）扩至 22 条；2026-09-22 第七批扩容（多仓调研+多App调研落地）再增 5 仓 6 条，共 28 条。全部经 live_probe 验活后纳入：
#   ok = L1+L2+L3 全过；format_only = L2 过、L3 沙箱抽样全挂（保留，交 CI 侧验活）；
#   blocked = 沙箱网关 502 无法判定（保留，交 CI 侧验活）；curl 复核项已单独注明。
# 沙箱内不可达不代表死链（CI 侧 raw 直连可达）；运行期任一上游连续 FAIL_LIMIT=3 次
# 失败会被自动停用进 blacklist_auto.txt，无需人工值守。
LIVE_UPSTREAMS = [
    # ---- 原有：guovin 双通道 ----
    {"name": "guovin-gd-ipv4", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/ipv4/result.m3u"},
    {"name": "guovin-release", "kind": "m3u",
     "url": "https://github.com/Guovin/iptv-api/releases/download/playlist-latest/result.m3u"},
    # ---- 第二批（3377/Kshao123/best-fan）----
    {"name": "3377-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/3377/IPTV/master/output/result.m3u"},  # 验活 ok 2261 频道
    {"name": "kshao123-tv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/Kshao123/TV/master/output/result.m3u"},  # 验活 format_only 2688 频道
    {"name": "bestfan-status", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_all_status.m3u8"},  # 验活 ok 164 频道带分辨率标注
    # ---- 第三批（Bruce0422/JunTV/zhi35/iTCoffe）----
    {"name": "bruce0422-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/Bruce0422/iptv-api/master/output/result.m3u"},  # 验活 ok 3217 频道（Guovin fork，每日 6:00/18:00）
    {"name": "juntv-main", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/alantang1977/JunTV/main/output/result.m3u"},  # 验活 ok 1317 频道（master 分支 404，已改 main）
    {"name": "zhi35-iptv", "kind": "m3u",
     "url": "https://live.zhi35.com/iptv.m3u"},  # probe 误判 binary_body（gzip），curl 复核 200/51272B 有效 m3u
    {"name": "itcoffe-itv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/iTCoffe/Collect-iTV/main/Internet_iTV.m3u"},  # 验活 format_only 3241 频道
    # ---- 第五批（xuy132/svefnz/yoursmile66）----
    {"name": "xuy132-tv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/xuy132/TV/master/output/result.txt"},  # 验活 ok 2648 条 txt 格式（每日 6:00/18:00）
    {"name": "svefnz-iptvn", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/svefnz/IPTVN/Files/IPTV.m3u"},  # 验活 ok 338 频道含港澳台（默认分支 Files）
    {"name": "yoursmile66-tvbox", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/yoursmile66/TVBox/main/live.txt"},  # 验活 ok 1156 条多线路 txt
    # ---- 第六批（Collect-IPTV 系独有上游）----
    {"name": "kilvn-iptv", "kind": "m3u",
     "url": "https://live.kilvn.com/iptv.m3u"},  # blocked=沙箱网关 502 无法判定，交 CI 验活
    {"name": "ibert-fmml", "kind": "m3u",
     "url": "https://m3u.ibert.me/txt/fmml_itv.txt"},  # 验活 format_only 189 频道
    {"name": "ibert-ycl", "kind": "m3u",
     "url": "https://m3u.ibert.me/ycl_iptv.m3u"},  # probe 瞬时 fetch_error，curl 复核 200/35330B 有效
    {"name": "vbskycn-iptv4", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/vbskycn/iptv/master/tv/iptv4.m3u"},  # 验活 ok 527 频道
    {"name": "iill-gather", "kind": "m3u",
     "url": "https://tv.iill.top/m3u/Gather"},  # blocked=沙箱网关 502 无法判定，交 CI 验活
    {"name": "zbds-iptv4", "kind": "m3u",
     "url": "https://live.zbds.org/tv/iptv4.m3u"},  # blocked=沙箱网关 502 无法判定，交 CI 验活
    {"name": "yuechan-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/YueChan/Live/main/IPTV.m3u"},  # 验活 format_only 96 频道
    {"name": "burningc4-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/BurningC4/Chinese-IPTV/master/TV-IPV4.m3u"},  # 验活 format_only 58 频道
    {"name": "zwc456baby-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/zwc456baby/iptv_alive/master/live.m3u"},  # 验活 ok 30 频道
    {"name": "hujingguang-cntv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/hujingguang/ChinaIPTV/main/cnTV_AutoUpdate.m3u8"},  # 验活 ok 60 频道
    # ---- 第七批（多仓调研+多App调研落地，2026-09-22）：5 仓 6 条 ----
    {"name": "ccsh-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/ccsh/iptv/main/live.m3u"},  # 验活 ok 2324 频道 47 组（MIT，全自动聚合产物，L3 抽样 3/5）
    {"name": "kimwang-bbxx365lite", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/kimwang1978/collect-txt/main/bbxx365_lite.m3u"},  # 验活 ok 7434 频道 24 组（每日归一化精简产物，沙箱 raw 直拉 200；全量版 bbxx365.m3u 25233 频道体积 4.3MB 未采用）
    {"name": "iptv0610-xp", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/0610840119/iptv-api/master/output/xp_result.m3u"},  # 验活 ok 683 频道 8 组（Guovin 变体秒播级，master 分支）
    {"name": "fanmingming-index", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/index.m3u"},  # 验活 format_only 94 频道（运营商鉴权流沙箱 403/404；CI 侧同仓 Pages 域名产物已验 ok/82 频道，交 live-validate 复核）
    {"name": "yang-gather", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/YanG-1989/m3u/main/Gather.m3u"},  # 验活 ok 123 频道（斗鱼/虎牙等大街源聚合；CI 侧 live_checks 同 URL 组验活 ok/123 频道）
    {"name": "yang-migu", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/YanG-1989/m3u/main/Migu.m3u"},  # 验活 format_only 43 频道（咪咕回看流 gslbserv.itv.cmvideo.cn 沙箱 403，交 CI 验活）
    # ---- 第十三批吸收实施（batch11 P1-1 / batch12 建议落地）：Romaxa55 canary ----
    # canary 语义：只监控不合并。cn.m3u 43 条 < MIN_ENTRIES_M3U=50 属设计内（不套通用门槛），
    # evaluate_upstream 走 canary 专用分支：fetch 200（由 fetch_raw 保证）+ 内容 >= CANARY_MIN_BYTES，
    # 日拉取在合并前跳过（canary continue）。GitHub Pages 静态产物 6h 自动验活；
    # 风险备注（batch11 调研）：README 带 MegaV VPN 商业推广，内容劣化由自动黑名单停用、可随时下线本条目。
    {"name": "romaxa55-cn", "kind": "m3u", "canary": True,
     "url": "https://romaxa55.github.io/world_ip_tv/output/cn.m3u"},  # 2026-09-22 沙箱实测 200/6946B，PARSERS['m3u'] 解析 43 条
    # ---- 第十四批吸收实施（batch8 建议优先融合①·单播面）：xisohi/CHINA-IPTV 分省分运营商源 ----
    # 主列表 TV/live.txt 1231 频道 / 90 域名 / 89 个为新增（batch8 重叠量化）；仓库 1820★ 当日活跃。
    # 组播面（Multicast/ 97 文件，rtp://239.x）不入此表——公网不可达，由 live_aggregate
    # 独立附录输出 lives/live_multicast.txt（内网限定标注）。
    {"name": "xisohi-china-iptv", "kind": "m3u",
     "url": "https://raw.githubusercontent.com/xisohi/CHINA-IPTV/main/TV/live.txt"},  # 2026-09-22 沙箱实测 200/133750B，解析 1231 频道
]
# 报告点名的上游未纳入本次 LIVE_UPSTREAMS（有据记录，非遗漏）：
# - tzdr.com/iptv.txt（第六批）：沙箱两次 fetch_error + curl 000 不可达，不硬塞；
# - alantang1977/JunTV master 分支：404，已改用 main 分支（见上 juntv-main）；
# - suxuang/iptv、Kimentanm/iptv（第六批）：与 guovin 系产物重复，避免同质翻倍；
# - 裸 IP 175.178.251.183：报告未点名核实，不臆造；
# - Zhou-Li-Bin/Tvbox-QingNing README 直播源 12 条（第四批 P2 可选）：落点为 README 抓取，
#   不在本任务允许改动的文件清单内，暂不纳入。

# 试探性短剧/成人专项上游：失败/降级均不影响主流程（自动黑名单保护）
# 2026-09-18 实测 GitHub 搜索后，仅找到 duanju_juhe.js（猫/河马/星芽/牛牛 聚合）的 js 源片段
# 与若干订阅链接列表（非 json 配置），故此处仅尝试 jsm.json 系仓库下可能存在的
# duanju/duoduo 类 tvbox 配置分支。命中则纳入 short.json；否则被自动停用。
SHORTS_ADULT_UPSTREAMS = [
    {"name": "qist/duanju", "kind": "tvbox", "category": "short",
     "url": "https://raw.githubusercontent.com/qist/tvbox/master/duanju.json"},
    {"name": "qist/duoduo", "kind": "tvbox", "category": "short",
     "url": "https://raw.githubusercontent.com/qist/tvbox/master/duoduo.json"},
    {"name": "qist/wogg", "kind": "tvbox", "category": "adult",
     "url": "https://raw.githubusercontent.com/qist/tvbox/master/wogg.json"},
    {"name": "gao/duanju", "kind": "tvbox", "category": "short",
     "url": "https://raw.githubusercontent.com/gaotianliuyun/gao/master/duanju.json"},
    {"name": "nxppru/duanju", "kind": "tvbox", "category": "short",
     "url": "https://raw.githubusercontent.com/nxppru/tvbox/master/duanju.json"},
    {"name": "cluntop/duanju", "kind": "tvbox", "category": "short",
     "url": "https://raw.githubusercontent.com/cluntop/tvbox/main/duanju.json"},
]

ALL_UPSTREAMS = UPSTREAMS + LIVE_UPSTREAMS + SHORTS_ADULT_UPSTREAMS

UPSTREAM_BASES = {u["name"]: u["url"].rsplit("/", 1)[0] + "/" for u in (UPSTREAMS + SHORTS_ADULT_UPSTREAMS) if u.get("kind") == "tvbox"}

# 自动发现产出的 canary 上游（scripts/discover_upstreams.py -> state/extra_upstreams.json）。
# 默认关闭：自动收编陌生配置会让订阅引入未经审核的内容（含未知 jar/js），
# 需要显式 EXTRA_UPSTREAMS=1 才并入；开启后失效由现有自动黑名单兜住。
EXTRA_UPSTREAMS_FILE = os.environ.get("EXTRA_UPSTREAMS_FILE", "state/extra_upstreams.json")
EXTRA_UPSTREAMS_ON = os.environ.get("EXTRA_UPSTREAMS", "0") == "1"

# ---------------- 成人内容发布开关（默认「不声明」模式，2026-09-22 所有者指令） ----------------
# 所有者指令：adult.json 每天随 daily 聚合产出并提交更新到仓库，但「只是不声明」——
# 不公开传播 / 宣传：不进 Release 附件白名单、不进 GitHub Pages、不进导航页、不在日报/README 中声明。
# 默认（PUBLISH_ADULT=0，「不声明」模式）：
#   1) 成人分类的站点不进 tvbox.json / vod.json（主产物口径不变）；
#   2) 仓库根 adult.json 每日照常产出（成人站点 + 成人直播），由 daily.yml 随提交白名单更新；
#      公开通路的隔离由三处保证：Release 上传白名单不含它、pages.yml 组目录双保险剔除、
#      导航页与 README 均无其入口与说明；
#   3) 不再写 .workbuddy 本地留档（留档职能由仓库根 adult.json 取代，
#      同时避免 pack_local 把它收进 Release 附件 zip）。
# PUBLISH_ADULT=1（完整公开模式）：成人站点同时进 tvbox.json / vod.json；
#   需要打进本地 zip 时给 pack_local.py 传 --adult adult.json。
PUBLISH_ADULT = os.environ.get("PUBLISH_ADULT", "0") == "1"



def load_extra_upstreams() -> list:
    """读取 canary 上游名单；开关关闭或文件缺失时返回空列表。"""
    if not EXTRA_UPSTREAMS_ON or not os.path.isfile(EXTRA_UPSTREAMS_FILE):
        return []
    try:
        with open(EXTRA_UPSTREAMS_FILE, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for u in doc.get("upstreams", []):
        url, kind = u.get("url"), u.get("kind")
        if url and kind in PARSERS:
            ent = {"name": u.get("name") or url[-28:], "kind": kind, "url": url, "auto": True}
            # 吸收点 P1-2：canary 名单同样支持 mirrors 多镜像选通
            if isinstance(u.get("mirrors"), list) and u["mirrors"]:
                ent["mirrors"] = [m for m in u["mirrors"] if isinstance(m, str) and m]
            out.append(ent)
    if out:
        print(f"    canary 上游 {len(out)} 个已并入本轮拉取（EXTRA_UPSTREAMS=1）", flush=True)
    return out


# ==================== 短剧/成人分类（独立收录 short.json / adult.json） ====================
# 关键词来源：现有 tvbox.json 22 条短剧站点 + 39 条成人站点的 name/key/api 关键字汇总（2026-09-18 扫描）
# 命中规则：name 或 key 含任一关键词则归入；name/key 均不命中时扫描 api 主机/路径作为兜底
SHORT_KEYWORDS = [
    "短剧", "微短剧", "短剧场",   # 中文
    "duanju", "duanjucat", "duanjumao", "shortplay", "short_play",  # 拼音/英文
    "七猫", "河马", "围观", "好看", "星芽", "果果", "红果", "黄果", "黄豆",
    "锦鲤", "偷乐", "上头", "聚合短剧",
]
ADULT_LIVE_SOURCES = [
    # fish2018/lib 成人直播/成人影片（每个都在 sandbox 实测过 http 200 + 至少一条流抽样通过）
    ("18+合集",   "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/18+.txt",        10679),
    ("live18",     "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/live18.txt",    8917),
    ("pron",       "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/pron.m3u",         64),
    ("国产传媒",   "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/几个传媒.txt",   3331),
    ("成人传媒",   "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/成人传媒.txt",   2980),
    ("成人电影",   "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/成人电影.txt",  14873),
    ("18资源丰富", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/18资源丰富.txt", 5564),
    ("花活",       "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/花活.txt",        2540),
    ("天美传媒816", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/天美传媒816.txt", 23),
    ("果冻传媒816", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/果冻传媒816.txt", 63),
    ("精东影业816", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/精东影业816.txt", 24),
    ("麻豆传媒816", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/麻豆传媒816.txt", 12),
    ("星空传媒816", "https://ghproxy.net/https://raw.githubusercontent.com/fish2018/lib/main/txt/星空传媒816.txt", 46),
]


def build_curated_lives(repo_dir: str):
    """产出 lives/live_verified.txt + 聚合精选 entry + 优质第三方 live entries + 成人 lives。
    调用本函数后，写入 live.json / adult.json 时各取所需。"""
    import os as _os
    sys.path.insert(0, _os.path.join(repo_dir, "scripts"))
    try:
        import live_aggregate as _la  # noqa: WPS433
        _la.main(repo=repo_dir, out_txt=_os.path.join("lives", "live_verified.txt"),
                 out_json="live_channels.json")
    except Exception as e:  # 单次聚合失败不影响主流程
        print("[curated] live_aggregation 跳过：", e.getMessage() if hasattr(e, "getMessage") else e, flush=True)

    ver_txt_url = "https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/lives/live_verified.txt"
    curated = [{
        "name": "聚合·分类直播(央视/卫视/地方/港台/轮播/直播/其他)",
        "type": 1,
        "url": ver_txt_url,
        "ua": "TVBox",
        "epg": "https://epg.pw/api/v1/getEpgInfo?token=tvbox",
    }]

    # 优质第三方直播源（来自本次会话 live_probe 实测 status=ok）
    THIRD_PARTY_OK = {
        "Guovin·央视": "https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/lives/live_cctv.txt",
        "Guovin·卫视": "https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/lives/live_satellite.txt",
        "Guovin·港台": "https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/lives/live_hkmo_tw.txt",
        "Guovin·其他": "https://ghproxy.net/https://raw.githubusercontent.com/hebijunge/tvbox-config/main/lives/live_other.txt",
        "Guovin·总集": "https://ghproxy.net/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u",
        "YY·轮播":    "https://sub.ottiptv.cc/yylunbo.m3u",
        "虎牙一起看":  "https://sub.ottiptv.cc/huyayqk.m3u",
        "斗鱼一起看":  "https://sub.ottiptv.cc/douyuyqk.m3u",
        "B站直播":     "https://sub.ottiptv.cc/bililive.m3u",
        "咪咕歌手":    "https://mgtv.ottiptv.cc/mglist.m3u",
    }
    for nm, u in THIRD_PARTY_OK.items():
        curated.append({"name": nm, "type": 1, "url": u})

    adult_lives = []
    for name, url, ch_count in ADULT_LIVE_SOURCES:
        adult_lives.append({
            "name": "成人·" + name,
            "type": 1,
            "url": url,
            "group": "成人直播",
            "channels": ch_count,
        })
    return curated, adult_lives


ADULT_KEYWORDS = [
    # 明确成人/色情关键词（收紧：去除通用资源站误匹配）
    "成人", "18+", "porn", "麻豆", "果冻", "天美", "精东", "色播", "传媒",
    "花活", "丝袜", "美腿", "hsck", "jav", "1024", "91porn", "91md", "91panta", "91splt", "91bobo", "91精品",
    "色花糖", "玩偶", "朱古力", "Missav", "missav",
    "Xojav", "JavBus", "JavDb", "涩涩", "Websites",
    # 扩张：常见成人站点标志词
    "xvideos", "pornhub", "xhamster", "hdsemj", "tokyo-hot",
    # 限定形容词（"敏感词"语义强）— 仅作为最后防线
    "裸聊", "裸播", "黄播", "黄网", "瑟瑟情",
    # 2026-09-21 点播+容错线：高置信词 ×10 增量（来源：实读 ccAzy separate_sources.py
    # 词表后人工挑选，走本表关键词匹配而非其删除式过滤；均为社区普遍使用的成人
    # 站名/黑话，误匹配风险低）
    "探花", "蜜桃", "糖心", "海角", "含羞草", "草榴", "秋霞", "番号", "无码", "里番",
]


def classify_site(s, overrides: dict = None) -> str:
    """返回 'short' / 'adult' / 'vod'。短剧与成人为独立收录分类，其余保持 vod。
    人工覆盖表（state/category_overrides.json，key -> 分类）优先于关键词匹配。"""
    if not isinstance(s, dict):
        return "vod"
    name = s.get("name") or ""
    key = s.get("key") or ""
    if overrides and key and key in overrides:
        return overrides[key]
    api = s.get("api") or ""
    ext = s.get("ext")
    ext_str = ""
    if isinstance(ext, str):
        ext_str = ext
    elif isinstance(ext, dict):
        ext_str = json.dumps(ext, ensure_ascii=False)
    # 跳过纯 MD5 key（上游用 32 位 hex 当 key，会与关键字如 "91"/"jav" 误撞）
    key_use = "" if (len(key) == 32 and all(c in "0123456789abcdef" for c in key.lower())) else key
    target = f"{name} {key_use} {api} {ext_str}".lower()
    # 优先短剧匹配（避免成人站点关键词误吞）
    if any(kw.lower() in target for kw in SHORT_KEYWORDS):
        return "short"
    if any(kw.lower() in target for kw in ADULT_KEYWORDS):
        return "adult"
    return "vod"


# 2026-09-23 改为多信号分级。强信号单命中即判 adult；弱信号需 ≥2 命中或上游投票佐证，
# 避免「吃瓜」「迷妹」等通用词单独命中误杀 vod 站；已知误报 key 进白名单强制 vod。
# 上游投票：同 repo 内强信号命中 ≥2 个站点 → 该 repo 其余未分类站也按投票结果走 adult。
STRONG_ADULT_TOKENS = [
    # 上游/官方标记
    "🔞",
    # 国际化成人平台（品牌词，零误匹配风险）
    "pornhub", "xvideos", "xhamster", "tokyo-hot",
    "javbus", "javdb", "xojav", "missav",
    "91porn", "91md", "hdsemj",
    # 明确成人 api 域名（社区共识的成人 CMS 后端）
    "souavzy", "pgxdy", "dadiapi", "lbapi9", "xrbsp", "jcspcj8",
    "caiji25", "sdszyapi", "hsck",
    # 明确站点标志词（带数字/连字符变体）
    "18av", "4kav", "4k-av", "cableav", "netflav", "owoav", "souav", "黄av",
    # 明确中文成人站点品牌
    "麻豆", "果冻传媒", "天美传媒", "精东传媒",
]

WEAK_ADULT_TOKENS = [
    "成人", "18+", "porn", "传媒", "色播", "丝袜", "美腿",
    "花活", "1024",
    "91panta", "91splt", "91bobo", "91精品",
    "色花糖", "玩偶", "朱古力", "涩涩",
    "裸聊", "裸播", "黄播", "黄网", "瑟瑟情",
    "探花", "蜜桃", "糖心", "海角", "含羞草", "草榴", "秋霞", "番号", "无码", "里番",
    "淫水", "色屌丝", "咪咪资源", "嗨片", "吃瓜", "迷妹", "黄果", "熊猫资源",
    "果冻", "天美", "精东",
]

# 已知误报白名单：key 命中强制 vod（这些是网盘/通用资源站，与成人无关）
ADULT_FALSE_POSITIVE_KEYS = {
    "webdav", "webdav1", "webdav2", "webdav3",
    "clouddrive", "aliyundrive", "aliyundrive2",
}
ADULT_FALSE_POSITIVE_NAME_FRAGMENTS = (
    "webdav", "web dav", "clouddrive", "阿里云盘", "alist",
)


def _classify_target_text(s: dict) -> str:
    """构造大小写归一化的搜索串（name + api + ext + 净化 key），跳过 32 位 MD5 key 防误撞。"""
    name = s.get("name") or ""
    api = s.get("api") or ""
    ext = s.get("ext")
    ext_str = ""
    if isinstance(ext, str):
        ext_str = ext
    elif isinstance(ext, dict):
        ext_str = json.dumps(ext, ensure_ascii=False)
    key = s.get("key") or ""
    key_use = "" if (len(key) == 32 and all(c in "0123456789abcdef" for c in key.lower())) else key
    return f"{name} {key_use} {api} {ext_str}".lower()


def classify_site(s, overrides: dict = None, origin_votes: dict = None) -> str:
    """返回 'short' / 'adult' / 'vod'。多信号分级：
    1) 人工覆盖表（state/category_overrides.json）优先；
    2) 已知误报 key/name → vod 兜底；
    3) 短剧关键词优先（避免成人词误吞短剧）；
    4) 强信号关键词 → adult；
    5) 弱信号关键词：单命中 → 仅当上游已 ≥1 站被判 adult 才升 adult；多命中 → 直接 adult；
    6) 其余 vod。

    origin_votes: {上游名: 强信号 adult 命中数}；None 表示不启用上游投票。
    """
    if not isinstance(s, dict):
        return "vod"
    key_raw = s.get("key") or ""
    key = key_raw.lower()
    name = s.get("name") or ""

    # 1. 人工覆盖表（保持原大小写匹配语义，避免与既有 state/category_overrides.json 冲突）
    if overrides and key_raw and key_raw in overrides:
        return overrides[key_raw]

    # 2. 已知误报白名单
    if key in ADULT_FALSE_POSITIVE_KEYS:
        return "vod"
    name_lower = name.lower()
    if any(frag in name_lower for frag in ADULT_FALSE_POSITIVE_NAME_FRAGMENTS):
        return "vod"

    target = _classify_target_text(s)

    # 3. 短剧关键词优先（保留原逻辑）
    if any(kw.lower() in target for kw in SHORT_KEYWORDS):
        return "short"

    # 4. 强信号关键词直接判 adult
    if any(t.lower() in target for t in STRONG_ADULT_TOKENS):
        return "adult"

    # 5. 弱信号关键词：单命中需上游投票；多命中直接判
    weak_hits = [t for t in WEAK_ADULT_TOKENS if t.lower() in target]
    if weak_hits:
        if len(weak_hits) >= 2:
            return "adult"
        # 单命中：查上游投票
        if origin_votes:
            site_origin = (s.get("_origin") or s.get("origin") or "").lower()
            if site_origin and origin_votes.get(site_origin, 0) >= 1:
                return "adult"

    return "vod"


def classify_site_strong_only(s, overrides: dict = None) -> str:
    """只用强信号 + 覆盖表 + 短剧词 + 误报白名单判定成人，用于上游投票预扫。
    弱信号在此场景不参与计数，避免把低置信度站计入上游投票而误伤同级站。"""
    if not isinstance(s, dict):
        return "vod"
    key = (s.get("key") or "").lower()
    if overrides and key and key in overrides:
        return overrides[key]
    if key in ADULT_FALSE_POSITIVE_KEYS:
        return "vod"
    name_lower = (s.get("name") or "").lower()
    if any(frag in name_lower for frag in ADULT_FALSE_POSITIVE_NAME_FRAGMENTS):
        return "vod"
    target = _classify_target_text(s)
    if any(kw.lower() in target for kw in SHORT_KEYWORDS):
        return "short"
    if any(t.lower() in target for t in STRONG_ADULT_TOKENS):
        return "adult"
    return "vod"


# ==================== 解析池（parses）清洗 ====================
# adult.json 等分类产物复用 vod 的 parses 全集（TVBox 站点不依赖 parses，parses 是
# 全局播放器池）。但历史版本未做去重，导致「一堆没用的解析」：
#   · 同一 URL 多个不同 name（如 jx.xmflv.com 至少 5 个别名）
#   · localhost/127.0.0.1/192.168.x 等本地代理引用（用户环境不可用）
#   · 类型错误（type 为字符串 "1" 而非 int）
#   · 占位 url（type 3 的 "Demo"/"Web" 内置功能，重复 6/7 次应各留一条）
# 修复目标：结构校验 + 私有地址剔除 + URL 规范化去重 + 可选 TCP 探活 + 安全阀
_VALID_PARSE_TYPES = {0, 1, 2, 3, 4}
_LOOPBACK_HOSTS = {"localhost", "0.0.0.0", "::1", "[::1]"}


def _is_private_host(host: str) -> bool:
    """判断主机名是否属于本地/回环/内网。IPv4 用 octet 解析，IPv6 走文本判定。"""
    if not host:
        return False
    h = host.lower().strip("[]")
    if h in _LOOPBACK_HOSTS:
        return True
    if h == "127.0.0.1" or h.startswith("127."):
        return True
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        try:
            o = [int(p) for p in parts]
            if o[0] == 10:
                return True
            if o[0] == 192 and o[1] == 168:
                return True
            if o[0] == 172 and 16 <= o[1] <= 31:
                return True
            if o[0] == 169 and o[1] == 254:
                return True
        except Exception:
            return False
    return False


def _normalize_parse_url(u: str) -> str:
    """规范化解析 URL 用于去重：去 scheme、host 小写、剥末尾斜杠、剥 query/fragment。
    内置 type 3 占位（"Demo"/"Web"）按字面保留大小写一致。"""
    if not isinstance(u, str):
        return ""
    u = u.strip()
    if u in ("Demo", "Web"):
        return u  # TVBox type 3 内置功能占位
    if "://" in u:
        u = u.split("://", 1)[1]
    u = u.split("?", 1)[0].split("#", 1)[0]
    u = u.rstrip("/")
    # host 小写，路径保持原样
    if "/" in u:
        host, _, path = u.partition("/")
        return f"{host.lower()}/{path}"
    return u.lower()


def _coerce_parse_type(t) -> int | None:
    """接受 int / 数字字符串；其余返回 None（视为无效）。"""
    if isinstance(t, int):
        return t
    if isinstance(t, str):
        s = t.strip()
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            try:
                return int(s)
            except Exception:
                return None
    return None


def clean_parses(parses: list, *, do_probe: bool = True, probe_timeout: float = 4.0) -> tuple:
    """解析池清洗：返回 (cleaned_parses, stats)。

    清洗步骤：
    1) 结构校验：非 dict / 缺 name / 缺 url → 剔除；type 数字字符串 → int 保留；
       type 不在 {0,1,2,3,4} 或为 None 且 URL 是占位 → 剔除。
    2) 私有/回环主机剔除（localhost / 127.* / 10.* / 192.168.* / 172.16-31.* / 169.254.*）。
    3) URL 规范化去重（scheme-insensitive、host-lowercase、no trailing slash）：
       同一规范化 URL 保留第一条。
    4) 可选 TCP 主机探活（do_probe=True 时）：仅对 type 0/1/2 且 URL 非占位者做 DNS 解析 + TCP 握手，
       不可达主机 → 剔除。安全阀：若剔除率 > 80% 视为网络故障，回退为「仅做 1-3 步」
       （保护沙箱/受限环境下不会把整个解析池清空）。

    stats dict 字段：before / after / dropped_invalid / dropped_private / dropped_duplicate /
    dropped_unreachable / probe_alive / probe_dead / safety_valve_triggered
    """
    stats = {
        "before": len(parses),
        "after": 0,
        "dropped_invalid": 0,
        "dropped_private": 0,
        "dropped_duplicate": 0,
        "dropped_unreachable": 0,
        "probe_alive": 0,
        "probe_dead": 0,
        "safety_valve_triggered": False,
        "do_probe": bool(do_probe),
    }

    step1: list = []
    for p in parses:
        if not isinstance(p, dict):
            stats["dropped_invalid"] += 1
            continue
        name = p.get("name")
        url = p.get("url")
        if not isinstance(name, str) or not name:
            stats["dropped_invalid"] += 1
            continue
        if not isinstance(url, str) or not url:
            stats["dropped_invalid"] += 1
            continue
        # type 校正
        coerced = _coerce_parse_type(p.get("type"))
        if coerced is not None:
            new_p = dict(p)
            new_p["type"] = coerced
            if url in ("Demo", "Web"):
                new_p["type"] = 3
            step1.append(new_p)
        elif url in ("Demo", "Web"):
            # 占位 url 缺 type → 补 type=3
            new_p = dict(p)
            new_p["type"] = 3
            step1.append(new_p)
        else:
            stats["dropped_invalid"] += 1
            continue

    step2: list = []
    for p in step1:
        url = p["url"]
        if url in ("Demo", "Web"):
            step2.append(p)
            continue
        # 解析主机
        host = ""
        try:
            if "://" in url:
                tail = url.split("://", 1)[1]
            else:
                tail = url
            host = tail.split("/", 1)[0]
            host = host.split(":", 1)[0]
        except Exception:
            stats["dropped_invalid"] += 1
            continue
        if _is_private_host(host):
            stats["dropped_private"] += 1
            continue
        step2.append(p)

    step3: list = []
    seen_urls: set = set()
    for p in step2:
        key = _normalize_parse_url(p["url"])
        if key in seen_urls:
            stats["dropped_duplicate"] += 1
            continue
        seen_urls.add(key)
        step3.append(p)

    # 探活（可选）
    if do_probe and step3:
        probe_targets: list = []
        probe_idx: dict = {}
        for i, p in enumerate(step3):
            url = p["url"]
            if url in ("Demo", "Web"):
                continue
            if p.get("type") not in (0, 1, 2):
                continue
            host = ""
            port = 0
            try:
                tail = url.split("://", 1)[1] if "://" in url else url
                hp = tail.split("/", 1)[0]
                if ":" in hp:
                    host, port_s = hp.rsplit(":", 1)
                    port = int(port_s) if port_s.isdigit() else 0
                else:
                    host = hp
            except Exception:
                continue
            if not host or _is_private_host(host):
                continue
            if not port:
                port = 443 if url.startswith("https") else 80
            probe_targets.append((i, host, port))

        alive_idx: set = set()
        if probe_targets:
            import concurrent.futures as _cf
            import socket as _socket
            from urllib.parse import urlparse as _urlparse
            def _probe(arg):
                i, host, port = arg
                try:
                    ip = _socket.gethostbyname(host)
                    s = _socket.create_connection((ip, port), timeout=probe_timeout)
                    s.close()
                    return i, True
                except Exception:
                    return i, False
            with _cf.ThreadPoolExecutor(min(16, len(probe_targets))) as ex:
                for i, ok in ex.map(_probe, probe_targets):
                    if ok:
                        alive_idx.add(i)
                    else:
                        stats["probe_dead"] += 1

        # 安全阀：剔除率 > 80% 视为网络故障，回退保留全部
        if probe_targets and stats["probe_dead"] / len(probe_targets) > 0.80:
            stats["safety_valve_triggered"] = True
            stats["probe_dead"] = 0
            stats["after"] = len(step3)
            return step3, stats

        step4 = []
        for i, p in enumerate(step3):
            if i in alive_idx or p["url"] in ("Demo", "Web") or p.get("type") not in (0, 1, 2):
                step4.append(p)
                if i in alive_idx:
                    stats["probe_alive"] += 1
            else:
                if p.get("type") in (0, 1, 2):
                    stats["dropped_unreachable"] += 1
        stats["after"] = len(step4)
        return step4, stats

    stats["after"] = len(step3)
    return step3, stats


# ==================== 依赖收集（jar / js / json 库文件） ====================
DEPS_DIR = "deps"
MANIFEST_PATH = os.path.join(DEPS_DIR, "manifest.json")
DEP_TIMEOUT = 25
DEP_MAX_BYTES = 8 * 1024 * 1024
DEP_CONCURRENCY = int(os.environ.get("DEP_CONCURRENCY", "8"))
# 沙箱/CI 网络受限时可跳过站点验活或强制用缓存
SKIP_SITE_TEST = os.environ.get("SKIP_SITE_TEST", "0") == "1"
SKIP_REFRESH = os.environ.get("SKIP_REFRESH", "0") == "1"

_IDNA_CACHE = {}


def _idna_host(host: str) -> str:
    """中文域名手动 punycode（urllib 对部分中文域名内置 idna 会抛错）。"""
    if host.isascii():
        return host
    if host in _IDNA_CACHE:
        return _IDNA_CACHE[host]
    labels = []
    for lab in host.split("."):
        if lab.isascii():
            labels.append(lab)
        else:
            try:
                labels.append("xn--" + lab.encode("punycode").decode())
            except Exception:
                labels.append(lab)
    out = ".".join(labels)
    _IDNA_CACHE[host] = out
    return out


def dep_lenient_json(text: str) -> bool:
    if text.startswith("\ufeff"):
        text = text[1:]
    # 2026-09-21 点播+容错线：改用主管线同款状态机清洗（去 // 行注释（含行内）、
    # /* */ 块注释、尾随逗号，且不误伤字符串内双斜杠）。原正则只剥「整行 //」，
    # 实测 franksun1211/TVBOX 的 CKS2026.json（/* */ 块注释）与
    # victor1616888/TVBOX-Q 的 tvbox.json（值后行内 // 注释）都会解析失败。
    text = strip_comments_and_clean(text)
    try:
        json.loads(text)
        return True
    except Exception:
        return False


def dep_classify(kind_hint: str, content: bytes) -> str:
    """按内容判定依赖类型: jar / js / json / unknown（伪装扩展名靠内容识别）。"""
    if content[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "jar"
    if content[:3] == b"dex\n":
        return "jar"
    if content[:2] == b"\x1f\x8b":
        return "data"  # gzip 数据文件（如 pikpakclass.db.gz 分享码库）
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return "unknown"
    low = text[:2000].lower()
    if "<html" in low or "<!doctype" in low:
        return "unknown"
    if kind_hint == "json":
        try:
            json.loads(text)
            return "json"
        except Exception:
            return "json" if dep_lenient_json(text) else "data"
    if re.search(r"\b(function|var|let|const|import|export|require)\b", text[:4000]) or "=>" in text[:1000]:
        return "js"
    return "data"  # 其余可解码纯文本（TSV 分享码库等）视为数据文件


def dep_download(url: str):
    """原 URL → ghproxy 镜像列表轮换兜底。返回 (bytes, channel) 或 (None, err)。"""
    import urllib.parse
    # 非 ASCII 域名（如中文域名）punycode 化：urllib 发请求头走 latin-1，unicode host 必挂 UnicodeEncodeError
    p = urllib.parse.urlsplit(url)
    if p.hostname and not p.hostname.isascii():
        host = _idna_host(p.hostname)
        netloc = f"{host}:{p.port}" if p.port else host
        url = urllib.parse.urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
    attempts = [url]
    if "github" in url and "ghproxy" not in url:
        attempts.extend(m + url for m in GH_MIRRORS)
    attempts = [
        urllib.parse.quote(u, safe="%/:=&?~#+!$,;'@()*[]|") if not u.isascii() else u
        for u in attempts
    ]
    last = ""
    for i, u in enumerate(attempts):
        try:
            status, data, _ = http_get(u, DEP_TIMEOUT, DEP_MAX_BYTES)
            if status == 200 and data:
                return data, ("direct" if i == 0 else "mirror")
            last = f"HTTP {status}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"[:120]
    return None, last


def is_file_ref(v: str):
    """识别配置字符串里的依赖文件引用。返回 ('rel'|'abs', path) 或 None。"""
    v = v.strip()
    if not v or "{name}" in v or "{cateId}" in v or "{catePg}" in v:
        return None
    base = v.split(";")[0]
    if "$$$" in base:
        return None
    if base.startswith("./") or base.startswith("../") or base.startswith("/"):
        return ("rel", base)
    if re.match(r"^https?://", base):
        host = urllib.parse.urlparse(base).netloc
        if "127.0.0.1" in host or "localhost" in host:
            return None
        path = base.split("?")[0].lower()
        if path.endswith((".js", ".jar", ".zip", ".php")):
            return ("abs", base)
    return None


_WIN_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def _win_safe_seg(seg: str) -> str:
    """Windows 下把路径段里的非法字符替换掉。

    只有在 `os.name == 'nt'` 时才生效 —— **Linux/CI 行为一字不改**，产物布局保持一致。
    为什么需要：依赖落库的本地路径是从 URL 的 path 段拼出来的，而镜像前缀 URL
    （`https://gh-proxy.org/https://raw.githubusercontent.com/...`）的 path 里带 `https:`，
    在 Windows 上 `os.makedirs` 直接抛 `WinError 123 文件名、目录名或卷标语法不正确`。
    这类路径在 Linux 上是合法目录名（本仓库里已有 `deps/liu673cn/m/https:/raw...` 这种真实案例），
    所以问题只在本地 Windows 复现，CI 上永远看不到。
    """
    if os.name != "nt":
        return seg
    s = _WIN_BAD_CHARS.sub("_", seg)
    # Windows 还禁止以点或空格结尾，且保留名（CON/PRN/NUL…）也要避开
    s = s.rstrip(" .")
    if not s:
        return "_"
    if s.upper().split(".")[0] in ("CON", "PRN", "AUX", "NUL",
                                   "COM1", "COM2", "COM3", "COM4",
                                   "LPT1", "LPT2", "LPT3"):
        s = "_" + s
    return s


def dep_local_path(origin: str, url: str) -> str:
    if origin == "remote":
        name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or ""
        if not name or len(name) > 80:
            name = hashlib.md5(url.encode()).hexdigest()[:12]
        return f"{DEPS_DIR}/remote/{_win_safe_seg(name)}"
    u = urllib.parse.urlparse(url)
    segs = u.path.lstrip("/").split("/")
    if u.netloc == "raw.githubusercontent.com" and len(segs) > 3:
        segs = segs[3:]  # 剥离 owner/repo/branch，路径与仓库已入库布局一致
    segs = [_win_safe_seg(s) for s in segs if s not in ("", ".")]
    path = "/".join(segs)
    if not path:
        path = hashlib.md5(url.encode()).hexdigest()[:12]
    return f"{DEPS_DIR}/{_win_safe_seg(origin)}/{path}"


def load_manifest() -> dict:
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _spider_canon(ref, origin: str):
    """把 spider 值归一成绝对 URL，用于判断「是不是同一份包」。

    不能直接比字符串：全局 spider 在上一轮产出里已经被改写成 `./deps/xxx/jar/spider.jar`，
    而上游原始值写的是 `./jar/spider.jar` —— 字面不同、指向同一份包。
    """
    if not isinstance(ref, str) or not ref.strip():
        return None
    r = is_file_ref(ref.split(";md5;")[0])
    if not r:
        return None
    where, pathv = r
    if where == "abs":
        return pathv
    base = UPSTREAM_BASES.get(origin, "")
    return urllib.parse.urljoin(base, pathv) if base else None


def _global_spider_url(tvbox: dict, spider_origin: dict):
    """全局 spider 归一成绝对 URL，用于与各个上游的 spider 比「是不是同一份包」。

    两种来源都要能处理：
      1) 本次合并刚选定的值 —— 形如 `./jar/spider.jar`，用 spider_origin 的 base 拼；
      2) 上一轮产出里已被落库改写的值 —— 形如 `./deps/qist/jsm/jar/spider.jar`，
         这时不能再拿上游 base 去拼（会拼出不存在的路径），而应从 `deps/<上游>/` 反推上游。
    """
    sp = tvbox.get("spider")
    if not isinstance(sp, str) or not sp.strip():
        return None
    r = is_file_ref(sp.split(";md5;")[0])
    if not r:
        return None
    where, pathv = r
    if where == "abs":
        return pathv
    p = pathv.lstrip("./")
    if p.startswith("deps/"):
        rest = p[len("deps/"):]
        # 上游名里含 '/'（如 qist/jsm），取最长匹配的那个前缀
        for k in sorted(UPSTREAM_BASES, key=len, reverse=True):
            if rest.startswith(k + "/"):
                # 关键：剥掉 deps/<上游>/ 前缀还原成上游内的相对路径，再按上游 base 拼接。
                # 直接 urljoin(base, './deps/...') 会拼出一个上游根本不存在的路径。
                return _spider_canon("./" + rest[len(k) + 1:], k)
    if spider_origin:
        return _spider_canon(sp, spider_origin[0])
    return None


def assign_origin_spiders(tvbox: dict, site_origin_name: dict, upstream_spider: dict,
                          spider_origin: dict = None) -> dict:
    """让每个源用它「来源上游」声明的那份 spider jar。

    ---- 为什么必须这么做 ----
    每个上游配置都声明自己的顶层 spider，而且**各不相同**：
        qist/js、qist/0825  → ./jar/pg_upgraded.jar
        gao/js、nxppru/js   → ./jar/pg.jar
        cluntop/aa          → ./jar/pro.jar
        cluntop/wv          → ./jar/WvSpider.jar
        qist/0826、qist/fty → ./jar/fan.txt
        wex/newwex          → http://oss4liview.moji.com/...
    而合并只能保留一份全局 spider（先到先得）。凡是 `jar` 字段为空、走全局 spider 的源，
    就会被指向一个**不含它所需爬虫类**的包 —— 客户端加载爬虫时抛 ClassNotFoundException，
    这些源直接变成「坏的」。实测受影响 256 个爬虫类 / 359 个源，而它们在真实 TVBox 里本来是能用的。

    这跟「合并丢掉上游语义」是同一类问题：合并只留下了站点数据，丢掉了「这个源该配哪份运行时」。

    ---- 做法 ----
    给这些源的 `jar` 字段补上「它来源上游的那份 spider」原文，后续 collect_and_rewrite_deps 会
    按 origin 把它落库到 deps/<上游>/... 并改写成仓库内相对路径 + md5，与站点自带 jar 走同一条路。
    与全局 spider 指向同一份包的不写（省体积）。
    """
    if os.environ.get("ORIGIN_SPIDER", "1") != "1":
        return {"skipped": 1}

    g_url = _global_spider_url(tvbox, spider_origin)
    stats = {"assigned": 0, "same_as_global": 0, "origin_no_spider": 0, "no_origin": 0,
             "not_file_ref": 0}
    for s in tvbox.get("sites") or []:
        if not isinstance(s, dict) or s.get("jar"):
            continue                                  # 自带 jar 的源不动
        api = str(s.get("api") or "")
        if not (api.startswith("csp_") or api.startswith("./")):
            continue                                  # 只有 csp/js 爬虫源才吃 spider
        origin = site_origin_name.get(s.get("key"))
        if not origin:
            stats["no_origin"] += 1
            continue
        sp = upstream_spider.get(origin)
        if not isinstance(sp, str) or not sp:
            stats["origin_no_spider"] += 1
            continue
        sp_url = _spider_canon(sp, origin)
        if not sp_url:
            stats["not_file_ref"] += 1
            continue
        if g_url and sp_url == g_url:
            stats["same_as_global"] += 1
            continue
        s["jar"] = sp
        stats["assigned"] += 1
    return stats


def prune_unlocalized_jars(tvbox: dict) -> dict:
    """安全网：把没能落库的 per-site `jar` 撤掉，回退成走全局 spider。

    场景：assign_origin_spiders 给某源补了上游的 spider（如 `./jar/pro.jar`），但该包下载失败 /
    被自动黑名单拦下 → collect_and_rewrite_deps 会「保留原值」，于是产物里留下一个**相对路径**。
    客户端拿到 `./jar/pro.jar` 会按配置所在 URL 去解析，多半 404 —— 比不写更糟。
    所以：确认本地没有对应文件的一律撤掉，宁可回退到全局 spider。
    """
    stats = {"checked": 0, "pruned": 0}
    for s in tvbox.get("sites") or []:
        if not isinstance(s, dict) or not s.get("jar"):
            continue
        stats["checked"] += 1
        r = is_file_ref(str(s["jar"]).split(";md5;")[0])
        if not r or r[0] == "abs":
            continue                                   # 绝对 URL 与本地已改写路径都不动
        local = r[1].lstrip("./").replace("/", os.sep)
        if not os.path.exists(local):
            s.pop("jar", None)
            stats["pruned"] += 1
    if stats["pruned"]:
        print(f"    撤回未能落库的 jar 引用：{stats['pruned']} 个（回退为全局 spider）", flush=True)
    return stats


def collect_and_rewrite_deps(tvbox: dict, site_origin: dict, spider_origin: dict):
    """收集 tvbox 配置中的 jar/js/json 依赖到 deps/ 并把引用改写为仓库相对路径。
    site_origin: key -> origin 名；spider_origin: (origin 名, base url)
    返回统计 dict；同时更新 deps/manifest.json。"""
    import urllib.parse

    manifest = load_manifest()
    now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S +08:00")

    # ---- 1. 生成 (origin, url) 待收集清单 ----
    entries = []  # (kind_hint, url, origin)

    def add_ref(kind_hint: str, ref: str, origin: str, base: str):
        r = is_file_ref(ref)
        if not r:
            return
        where, pathv = r
        url = urllib.parse.urljoin(base, pathv) if where == "rel" else pathv
        e = (kind_hint, url, origin)
        if e not in entries:
            entries.append(e)

    if isinstance(tvbox.get("spider"), str) and spider_origin:
        add_ref("jar", tvbox["spider"].split(";md5;")[0], spider_origin[0], spider_origin[1])
    for s in tvbox.get("sites", []):
        origin = site_origin.get(s.get("key"))
        if not origin:
            continue
        base = UPSTREAM_BASES.get(origin, "")
        if not base:
            continue
        # api 也纳管：规则 js 常写在 api 字段（如 cat 系列 ./cat/MyCatBookan.js），
        # 与 jar/ext 同等落库，否则产物里留悬空相对路径、客户端 404。
        # is_file_ref 只认 .jar/.js/.json/.zip/.css/.txt 等文件后缀，
        # type 1 的 HTTP 端点（/api.php/provide/vod）不以文件后缀结尾，天然不会被误收。
        for field in ("jar", "ext", "api"):
            v = s.get(field)
            if isinstance(v, str):
                hint = "jar" if field == "jar" else ("js" if v.lower().split("?")[0].endswith(".js") else "json")
                for seg in (v.split("$$$") if "$$$" in v else [v]):
                    add_ref(hint, seg, origin, base)
            elif isinstance(v, dict):
                for v2 in v.values():
                    if isinstance(v2, str):
                        for seg in (v2.split("$$$") if "$$$" in v2 else [v2]):
                            add_ref("json", seg, origin, base)

    # ---- 2. 并发下载/校验/入库 ----
    def work(e):
        kind_hint, url, origin = e
        lp = dep_local_path(origin, url)
        fp = os.path.join(lp)
        rec = {"key": f"{origin}|{url}", "url": url, "origin": origin, "local": lp,
               "ok": False, "kind": "", "md5": "", "size": 0, "err": "", "channel": ""}
        if os.path.exists(fp) and os.path.getsize(fp) > 0:
            content = open(fp, "rb").read()
        else:
            content, ch = dep_download(url)
            rec["channel"] = ch if content else str(ch)
            if content is None:
                rec["err"] = str(ch)
                return rec
        hint = {"jar": "jar", "zip": "jar", "js": "js", "json": "json", "php": "jar"}.get(
            url.lower().split("?")[0].rsplit(".", 1)[-1], "")
        kind = dep_classify(hint, content)
        rec["kind"] = kind
        rec["size"] = len(content)
        rec["md5"] = hashlib.md5(content).hexdigest()
        if kind == "unknown":
            rec["err"] = f"content not js/jar/json ({content[:24]!r})"
            return rec
        try:
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, "wb").write(content)
        except OSError as e:
            # 单条依赖落盘失败（典型：Windows 上 URL 拼出的目录名含非法字符）
            # 绝不能让它把整轮合并带崩 —— 记成这条失败，其它依赖照常收集。
            rec["err"] = f"落盘失败 {type(e).__name__}: {str(e)[:80]}"
            return rec
        rec["ok"] = True
        return rec

    ok_map: dict = {}
    print(f"[deps] 收集 {len(entries)} 个依赖（并发 {DEP_CONCURRENCY}）...", flush=True)
    with cf.ThreadPoolExecutor(DEP_CONCURRENCY) as ex:
        futs = {ex.submit(work, e): e for e in entries}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            rec = fut.result()
            if rec["ok"]:
                ok_map[rec["key"]] = rec
            if i % 50 == 0:
                print(f"  ... {i}/{len(entries)}", flush=True)

    # ---- 2b. 规则 js 内部相对 import 递归落库（限深 1 层）----
    # cat 规则集形态：每个规则 js 顶部 `import { _ } from './lib/cat.js'`，公共库必须随规则
    # 一起落库，否则客户端加载规则时 import 404（Bookan[cat] 等 6 个 cat 源因此曾全灭）。
    # base 用「该 js 文件自身的 url」做 urljoin（标准 ESM 相对语义），比 relpath 反推可靠。
    IMPORT_JS_RE = re.compile(r"""(?:from\s*|import\s*\(\s*|require\(\s*)['"](\.{1,2}/[^'"]+\.js)['"]""")

    def scan_js_imports():
        added = 0
        for rec in list(ok_map.values()):
            if rec.get("kind") != "js" or not rec.get("ok"):
                continue
            try:
                text = open(rec["local"], encoding="utf-8", errors="replace").read()[:65536]
            except OSError:
                continue
            for m in IMPORT_JS_RE.finditer(text):
                imp = m.group(1)  # './lib/cat.js' 或 '../lib/cat.js'
                target_url = urllib.parse.urljoin(rec["url"], imp)
                rkey = f"{rec['origin']}|{target_url}"
                if rkey in ok_map:
                    continue
                entries.append(("js", target_url, rec["origin"]))
                added += 1
        return added

    n_imp = scan_js_imports()
    if n_imp:
        print(f"  [deps] 规则 js 内部 import 追加 {n_imp} 个公共库依赖...", flush=True)
        with cf.ThreadPoolExecutor(DEP_CONCURRENCY) as ex:
            futs2 = {ex.submit(work, e): e for e in entries[-n_imp:]}
            for fut in cf.as_completed(futs2):
                rec2 = fut.result()
                if rec2["ok"]:
                    ok_map[rec2["key"]] = rec2

    # ---- 3. 失败项回退：manifest 缓存 ----
    for e in entries:
        key = f"{e[2]}|{e[1]}"
        if key not in ok_map and SKIP_REFRESH and key in manifest:
            m = manifest[key]
            if os.path.exists(m["local"]):
                ok_map[key] = {"key": key, "url": e[1], "origin": e[2], "local": m["local"],
                               "ok": True, "kind": m["kind"], "md5": m["md5"],
                               "size": m.get("size", 0), "err": "", "channel": "manifest-cache"}

    # ---- 4. 改写引用 ----
    stats = {"total": len(entries), "collected": len(ok_map), "rewritten": 0, "kept": 0, "spider": 0}
    missing = []

    def md5_of(local: str):
        if not os.path.exists(local):
            missing.append(local)
            return None
        with open(local, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    if isinstance(tvbox.get("spider"), str) and spider_origin:
        key = f"{spider_origin[0]}|{tvbox['spider'].split(';md5;')[0] if is_file_ref(tvbox['spider'].split(';md5;')[0]) else tvbox['spider']}"
        # spider 的 url 已在 entries 里以 (origin, base) 生成，直接按 url 查
        sk = None
        for e in entries:
            if e[2] == spider_origin[0] and e[0] == "jar":
                sk = ok_map.get(f"{e[2]}|{e[1]}")
                if sk:
                    break
        if sk:
            md5v = md5_of(sk["local"])
            if md5v:
                tvbox["spider"] = f"./{sk['local']};md5;{md5v}"
                stats["spider"] = 1

    for s in tvbox.get("sites", []):
        origin = site_origin.get(s.get("key"))
        if not origin:
            continue
        for field in ("jar", "ext", "api"):
            v = s.get(field)
            vals = []
            if isinstance(v, str):
                vals = [(field, None, v)]
            elif isinstance(v, dict):
                vals = [(field, k2, v2) for k2, v2 in v.items() if isinstance(v2, str)]
            for f0, k2, raw in vals:
                if "$$$" in raw:
                    segs = raw.split("$$$")
                    changed = False
                    for si, seg in enumerate(segs):
                        r = is_file_ref(seg)
                        if not r:
                            continue
                        if f0 == "api" and not (r[0] == "rel" and seg.lower().split("?")[0].endswith(".js")):
                            continue  # api 字段只改写「相对 js 规则」，绝不动 HTTP 端点
                        base2 = UPSTREAM_BASES.get(origin, "")
                        url2 = urllib.parse.urljoin(base2, r[1]) if r[0] == "rel" else r[1]
                        rec2 = ok_map.get(f"{origin}|{url2}")
                        if not rec2:
                            continue
                        md52 = md5_of(rec2["local"])
                        if md52 is None:
                            continue
                        segs[si] = f"./{rec2['local']}"
                        changed = True
                        stats["rewritten"] += 1
                    if changed:
                        if k2 is None:
                            s[f0] = "$$$".join(segs)
                        else:
                            s[f0][k2] = "$$$".join(segs)
                    continue
                r = is_file_ref(raw)
                if not r:
                    continue
                if f0 == "api" and not (r[0] == "rel" and raw.lower().split("?")[0].endswith(".js")):
                    continue  # api 字段只改写「相对 js 规则」，绝不动 HTTP 端点
                base = UPSTREAM_BASES.get(origin, "")
                url = urllib.parse.urljoin(base, r[1]) if r[0] == "rel" else r[1]
                rec = ok_map.get(f"{origin}|{url}")
                if not rec:
                    stats["kept"] += 1
                    continue
                md5v = md5_of(rec["local"])
                if md5v is None:
                    stats["kept"] += 1
                    continue
                if f0 == "jar":
                    had = ";md5;" in raw
                    new = f"./{rec['local']};md5;{md5v}" if had else f"./{rec['local']}"
                    if k2 is None:
                        s[f0] = new
                    else:
                        s[f0][k2] = new
                else:
                    new = f"./{rec['local']}"
                    if k2 is None:
                        s[f0] = new
                    else:
                        s[f0][k2] = new
                stats["rewritten"] += 1
    if missing:
        print(f"  [deps] WARN 缺失本地文件 {len(missing)} 个，如 {missing[:3]}", flush=True)

    # ---- 5. 更新 manifest ----
    for rec in ok_map.values():
        manifest[rec["key"]] = {"url": rec["url"], "origin": rec["origin"], "local": rec["local"],
                                "md5": rec["md5"], "kind": rec["kind"], "size": rec["size"],
                                "channel": rec.get("channel", ""), "updated_at": now}
    os.makedirs(DEPS_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"[deps] 完成：收集 {stats['collected']}/{stats['total']}，改写 {stats['rewritten']} 处引用，"
          f"spider {'已修复' if stats['spider'] else '未变'}", flush=True)
    return stats



# ---------------- 依赖外链落库兜底层：collect_and_rewrite_deps 漏网的外部静态引用 ----------------
# 背景（2026-09-19 用户指令「依赖文件落库，相关的路径引用改成仓库路径」）：
#   collect_and_rewrite_deps 只处理 origin 明确、UPSTREAM_BASES 可回溯的站点引用；
#   去重/合并后 origin 丢失的站点，其 ext 里残留第三方绝对 URL（.js/.json/.txt）。
#   本层按 URL 兜底：下载 → deps/localized/ 落库 → 引用改写为 ./deps/... 仓库相对路径
#   （主配置相对路径，子仓经 _absolutize 转为 REPO_RAW 绝对路径）。
#   API 端点（非静态文件后缀）、127.0.0.1/localhost 本机代理、本仓库自身链接一律不动。
#   与 collect_and_rewrite_deps 同口径：已存在非空文件直接复用（保留现值不回源覆盖）、
#   下载失败/内容不可识别 → 保留原 URL 不改写。

MIRROR_PREFIX_RE = re.compile(r"^(https?://[^/]*(?:ghproxy|gh-proxy|ghfast|moeyy|gh\.llkk\.cc|gh\.zwy\.one|raw\.ihtw\.moe|ghp\.ci)[^/]*)/(https?://)")


import urllib.parse


def _static_ext_ref(seg: str):
    """ext 段落识别：第三方静态文件 URL（.js/.json/.txt/.zip）→ 归一化 URL；其余 None。

    .php 端点（dr_py 服务器等）是动态 API 不落库；;md5;/;params; 链只取首段判型。"""
    s = seg.strip()
    if not s or s.startswith("./") or s.startswith("../"):
        return None
    base = s.split(";")[0]
    if "$$$" in base or not re.match(r"^https?://", base):
        return None
    host = urllib.parse.urlparse(base).netloc
    if not host or "127.0.0.1" in host or "localhost" in host:
        return None
    if "hebijunge/tvbox-config" in base:  # 本仓库自身引用已是仓库路径
        return None
    # 镜像前缀归一化：ghproxy/gh-proxy/ghfast/moeyy 前缀剥成裸源 URL 再统一走 dep_download 镜像轮换
    m = MIRROR_PREFIX_RE.match(base)
    url = f"{m.group(2)}{base[m.end(2):]}" if m else base
    path = url.split("?")[0].lower()
    if not path.endswith((".js", ".json", ".txt", ".zip")):
        return None
    return url


def localize_external_refs(tvbox: dict) -> dict:
    """扫描 sites 的 jar/ext，把第三方静态依赖文件下载落库 deps/localized/ 并改写为仓库路径。"""
    manifest = load_manifest()
    now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S +08:00")

    # ---- 1. 收集唯一 URL（jar 用 is_file_ref 识别含 .jar/.zip/.php；ext 走 _static_ext_ref） ----
    candidates: dict = {}   # url -> kind_hint
    api_untouched = 0

    def add(field: str, seg: str):
        nonlocal api_untouched
        seg = seg.strip()
        if not seg:
            return
        if field == "jar":
            r = is_file_ref(seg)
            if not r or r[0] != "abs":
                return
            url = r[1]
            if "127.0.0.1" in url or "localhost" in url or "hebijunge/tvbox-config" in url:
                return
            candidates.setdefault(url, "jar")
        else:
            url = _static_ext_ref(seg)
            if url:
                hint = "js" if url.lower().split("?")[0].endswith(".js") else (
                    "jar" if url.lower().split("?")[0].endswith(".zip") else "json")
                candidates.setdefault(url, hint)
            elif re.match(r"^https?://", seg.split(";")[0]) and "$$$" not in seg:
                api_untouched += 1  # API 端点等非静态引用：保持原样

    for s in tvbox.get("sites", []):
        for field in ("jar", "ext"):
            v = s.get(field)
            if isinstance(v, str):
                for seg in v.split("$$$"):
                    add(field, seg)
            elif isinstance(v, dict):
                for v2 in v.values():
                    if isinstance(v2, str):
                        for seg in v2.split("$$$"):
                            add(field, seg)

    # ---- 2. 下载/复用/校验（并发，与 collect_and_rewrite_deps 同口径） ----
    def local_path_of(url: str) -> str:
        name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or ""
        name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name)[:60]
        return f"{DEPS_DIR}/localized/{hashlib.md5(url.encode()).hexdigest()[:10]}-{name}"

    def work(url_kind):
        url, hint = url_kind
        lp = local_path_of(url)
        rec = {"url": url, "local": lp, "ok": False, "kind": "", "md5": "", "size": 0, "err": "", "channel": ""}
        if os.path.exists(lp) and os.path.getsize(lp) > 0:
            content = open(lp, "rb").read()
            rec["channel"] = "keep-existing"
        else:
            content, ch = dep_download(url)
            rec["channel"] = ch if content else str(ch)
            if content is None:
                rec["err"] = str(ch)
                return rec
        kind = dep_classify(hint, content)
        if kind == "unknown":  # HTML/伪装内容：不改写，保留原 URL
            rec["err"] = f"content not js/jar/json ({content[:24]!r})"
            return rec
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        open(lp, "wb").write(content)
        rec.update({"ok": True, "kind": kind, "size": len(content),
                    "md5": hashlib.md5(content).hexdigest()})
        return rec

    ok_map: dict = {}
    if candidates:
        print(f"[deps-2] 外链落库兜底：{len(candidates)} 个第三方静态依赖（API 端点 {api_untouched} 处保持不动）...", flush=True)
        with cf.ThreadPoolExecutor(DEP_CONCURRENCY) as ex:
            for rec in ex.map(work, candidates.items()):
                if rec["ok"]:
                    ok_map[rec["url"]] = rec
                else:
                    print(f"  [deps-2] 保留原链 {rec['url'][:80]} ← {rec['err'][:80]}", flush=True)

    # ---- 3. 改写引用 ----
    stats = {"candidates": len(candidates), "localized": len(ok_map), "rewritten": 0,
             "kept": 0, "api_endpoints_untouched": api_untouched, "files": len(ok_map)}

    def rewrite_seg(field: str, seg: str) -> str:
        def ref_of(local: str) -> str:
            # 引用一律相对仓库根的 ./deps/...（DEPS_DIR 被环境变量指向绝对路径时也能正确改写）
            return local if not os.path.isabs(local) else os.path.relpath(local)
        if field == "jar":
            r = is_file_ref(seg)
            if not r or r[0] != "abs":
                return seg
            rec = ok_map.get(r[1])
            if not rec:
                stats["kept"] += 1
                return seg
            return f"./{ref_of(rec['local'])};md5;{rec['md5']}" if ";md5;" in seg else f"./{ref_of(rec['local'])}"
        url = _static_ext_ref(seg)
        if not url:
            return seg
        rec = ok_map.get(url)
        if not rec:
            stats["kept"] += 1
            return seg
        return f"./{ref_of(rec['local'])}"

    def apply_field(field: str, v):
        if isinstance(v, str):
            if "$$$" in v:
                return "$$$".join(rewrite_seg(field, x) for x in v.split("$$$"))
            return rewrite_seg(field, v)
        if isinstance(v, dict):
            return {k: apply_field(field, v2) for k, v2 in v.items()}
        return v

    if ok_map:
        for s in tvbox.get("sites", []):
            for field in ("jar", "ext"):
                if field in s:
                    new = apply_field(field, s[field])
                    if new != s.get(field):
                        s[field] = new
                        stats["rewritten"] += 1

    # ---- 4. manifest 记录（origin=localized，与 collect 共用一份 manifest） ----
    for rec in ok_map.values():
        manifest[f"localized|{rec['url']}"] = {"url": rec["url"], "origin": "localized",
                                               "local": rec["local"], "md5": rec["md5"],
                                               "kind": rec["kind"], "size": rec["size"],
                                               "channel": rec.get("channel", ""), "updated_at": now}
    os.makedirs(DEPS_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"[deps-2] 完成：落库 {stats['localized']}/{stats['candidates']}，改写 {stats['rewritten']} 个站点字段，"
          f"保留原链 {stats['kept']} 处，API 端点 {stats['api_endpoints_untouched']} 处未动", flush=True)
    return stats



def strip_comments_and_clean(text: str) -> str:
    """去 BOM、去行注释与块注释（状态机，不误伤字符串内双斜杠）、去尾随逗号。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    cleaned = "".join(out)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


def gh_url(u: str) -> str:
    """GitHub 链接换主镜像通道 GH_MIRRORS[0]（产出配置改写用；拉取侧走 GH_MIRRORS 列表轮换）。"""
    if not GH_MIRRORS or "ghproxy" in u or any(u.startswith(m.rstrip("/")) for m in GH_MIRRORS):
        return u
    if re.match(r"^https?://(raw\.)?githubusercontent\.com/", u) or re.match(
        r"^https?://github\.com/[^/]+/[^/]+/(raw|releases|archive)/", u
    ):
        return GHPROXY + u
    return u


def http_get(url: str, timeout: int, max_bytes: int = 0, rng=None, ua: str = None, xrw: str = None):
    """返回 (status, bytes, elapsed_ms)。非 2xx 抛异常。
    rng=(start, end) 时带 Range 头抽段请求（直播测速用，不整段下载）。
    ua/xrw 传入时覆盖默认 UA / 加 X-Requested-With 指纹头（P1-3 UA 池轮换）。"""
    headers = dict(UA)
    if ua:
        headers["User-Agent"] = ua
    if xrw:
        headers["X-Requested-With"] = xrw
    if rng:
        headers["Range"] = f"bytes={rng[0]}-{rng[1]}"
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(max_bytes) if max_bytes else r.read()
    return r.status, data, int((time.time() - t0) * 1000)


# ---------------- P2：域名替换层 ----------------

def load_domain_map() -> dict:
    try:
        with open(DOMAIN_MAP_FILE, "r", encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m, dict):
            return {str(k): str(v) for k, v in m.items() if k and v and not str(k).startswith("_")}
    except Exception:  # noqa: BLE001
        pass
    return {}


DOMAIN_MAP = {}


def map_domain(value):
    """对 URL 字符串应用 state/domain_map.json 的域名/前缀替换（上游换域名时改写而非丢源）。

    O 小点加固：完整 URL 按 host 边界匹配替换（避免子串误伤路径/其他域名）；
    非 URL 字符串回退到原子串替换行为。
    """
    if not DOMAIN_MAP or not isinstance(value, str):
        return value
    for old, new in DOMAIN_MAP.items():
        if old and old in value:
            value = _replace_host(value, old, new)
    return value


def _replace_host(value: str, old: str, new: str) -> str:
    m = re.match(r"^(https?://)([^/?#]+)(.*)$", value, re.I)
    if not m:
        return value.replace(old, new)
    scheme, netloc, rest = m.groups()
    host = netloc.rsplit("@", 1)[-1].split(":")[0]
    if host == old:
        new_host = new
    elif host.endswith("." + old):
        new_host = host[: -len(old)] + new
    else:
        return value
    return f"{scheme}{netloc.replace(host, new_host, 1)}{rest}"


# ---------------- P0：拉取与解析（一上游一适配器） ----------------

def fetch_raw(url: str, mirrors=None, ua_pool=None):
    """多通道重试（吸收点 P1-2 多镜像选通 / P1-3 UA 轮换，独立实现）。
    尝试顺序：主 URL → mirrors 逐个 → ghproxy 镜像列表（仅 GitHub 链接）。
    主 URL 与用户镜像每个失败后按 UA 池轮换重试（上限 UA_ROTATE_MAX 组）；
    ghproxy 兜底通道保持默认 UA 单次尝试（控制最坏尝试次数）。
    返回 (raw_bytes, channel, success_url) 或 (None, err, "")。"""
    import urllib.parse
    pool = ua_pool if ua_pool is not None else UA_POOL_VOD
    base_urls = [url]
    for m in (mirrors or []):
        if isinstance(m, str) and m and m not in base_urls:
            base_urls.append(m)
    gh_urls = ([m + url for m in GH_MIRRORS if m + url not in base_urls]
               if ("github" in url and "ghproxy" not in url) else [])
    last_err = ""
    for ch, u in enumerate(base_urls):
        for pair in pool[:UA_ROTATE_MAX]:
            try:
                status, raw, _ms = http_get(
                    u, FETCH_TIMEOUT,
                    ua=pair.get("User-Agent"),
                    xrw=pair.get("X-Requested-With") or None)
                if ch == 0:
                    return raw, "direct", u
                return raw, f"mirror:{urllib.parse.urlparse(u).netloc}", u
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"[:120]
    for u in gh_urls:
        try:
            status, raw, _ms = http_get(u, FETCH_TIMEOUT)
            return raw, f"mirror:{urllib.parse.urlparse(u).netloc}", u
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"[:120]
    return None, last_err, ""


def parse_tvbox(raw: bytes):
    """适配器：TVBox json 配置。返回 dict。"""
    txt = raw.decode("utf-8", "replace")
    cfg = json.loads(strip_comments_and_clean(txt))
    if not isinstance(cfg, dict):
        raise ValueError("top-level is not an object")
    return cfg


EXTINF_RE = re.compile(r"^#EXTINF:?\s*-?\d+\s*(.*)$")


TXT_GENRE_RE = re.compile(r"^(.*?)[，,]\s*#genre#\s*$", re.IGNORECASE)


def parse_m3u(raw: bytes):
    """适配器：m3u/txt 直播列表。返回 [(频道名, 分组, url)]。
    支持两种格式（2026-09-21 直播线融合，第三批 P3）：
    1) m3u：#EXTINF...group-title="分组",频道名 + 换行 URL；
    2) txt 频道格式（Bruce0422/JunTV 等部分产物）：「分组,#genre#」行声明分组，
       其后「频道名,url1#url2」行，多线路以 # 分隔（仅收 http/https 线路）。"""
    txt = raw.decode("utf-8", "replace")
    entries = []
    attr_name = None
    group = ""
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            m = EXTINF_RE.match(line)
            rest = m.group(1) if m else ""
            gm = re.search(r'group-title="([^"]*)"', rest)
            group = gm.group(1).strip() if gm else ""
            attr_name = rest.rsplit(",", 1)[-1].strip() if "," in rest else rest.strip()
            continue
        if line.startswith("#"):
            continue
        gm = TXT_GENRE_RE.match(line)
        if gm:
            group = gm.group(1).strip()
            attr_name = None
            continue
        if "," in line and not attr_name:
            name, _, urls = line.partition(",")
            got = False
            for u in urls.split("#"):
                u = u.strip()
                if u.lower().startswith(("http://", "https://")):
                    entries.append((name.strip(), group, u))
                    got = True
            if got:
                continue
        if attr_name:
            entries.append((attr_name, group, line))
            attr_name = None
    return entries


PARSERS = {"tvbox": parse_tvbox, "m3u": parse_m3u}


def evaluate_upstream(u: dict, raw):
    """P0 质量门槛。返回 (ok, status, detail, error)。
    status: ok / degraded（解析成功但不达门槛，不参与合并）/ dead（拉取或解析失败）。"""
    try:
        parser = PARSERS[u["kind"]]
    except KeyError:
        return False, "dead", {}, f"unknown kind {u.get('kind')}"
    if raw is None:
        return False, "dead", {}, "fetch failed"
    if u.get("canary"):
        # 第十三批：canary 上游专用门槛——HTTP 200 已由 fetch_raw 保证 + 内容 >= CANARY_MIN_BYTES。
        # 不套通用门槛：romaxa55 cn.m3u 43 条 < MIN_ENTRIES_M3U=50，设计内只监控不合并，
        # 健康分照常进出 record_result（连续失败自动停用对 canary 同样生效）。
        ok_c = len(raw) >= CANARY_MIN_BYTES
        return ok_c, ("ok" if ok_c else "degraded"), {"bytes": len(raw)}, \
            ("" if ok_c else f"canary content check failed: {len(raw)}B < {CANARY_MIN_BYTES}B")
    if len(raw) < (MIN_BYTES_M3U if u["kind"] == "m3u" else MIN_BYTES_TVBOX):
        return False, "degraded", {}, f"too small ({len(raw)} bytes)"
    try:
        parsed = parser(raw)
    except Exception as e:  # noqa: BLE001
        return False, "dead", {}, f"{type(e).__name__}: {e}"[:120]
    if u["kind"] == "tvbox":
        n = sum(len(parsed.get(k) or []) for k in ("sites", "lives", "parses"))
        if n < MIN_ITEMS_TVBOX:
            return False, "degraded", {"items": n}, "no usable items"
        return True, "ok", {"items": n, "cfg": parsed}, ""
    else:
        if len(parsed) < MIN_ENTRIES_M3U:
            return False, "degraded", {"entries": len(parsed)}, f"only {len(parsed)} entries"
        return True, "ok", {"entries": len(parsed)}, ""


# ---------------- P0/P1：状态、黑白名单 ----------------

def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)


def read_name_list(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    except Exception:  # noqa: BLE001
        return []


def record_result(state: dict, name: str, ok: bool, whitelist_manual: list) -> str:
    """更新连续失败计数；达阈值自动停用（手动白名单保护）。返回 'ok'/'disabled_now'/'failing'。"""
    now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    ent = state.get(name) if isinstance(state.get(name), dict) else {}
    if ok:
        ent.update({"fail_count": 0, "last_ok_at": now, "disabled": False, "disabled_reason": ""})
        state[name] = ent
        return "ok"
    fc = int(ent.get("fail_count", 0)) + 1
    ent["fail_count"] = fc
    ent["last_fail_at"] = now
    disabled_now = ""
    if fc >= FAIL_LIMIT and name not in whitelist_manual and not ent.get("disabled"):
        ent["disabled"] = True
        ent["disabled_reason"] = f"连续 {fc} 次不达标，自动停用"
        disabled_now = "disabled_now"
    state[name] = ent
    return disabled_now or "failing"


def sync_blacklist_auto(state: dict):
    """把自动停用的上游回写 blacklist_auto.txt（自动层）。"""
    names = sorted(n for n, v in state.items() if isinstance(v, dict) and v.get("disabled"))
    os.makedirs(os.path.dirname(BLACKLIST_AUTO) or ".", exist_ok=True)
    with open(BLACKLIST_AUTO, "w", encoding="utf-8") as f:
        f.write("# 自动黑名单：连续不达标自动停用的上游（由脚本维护，勿手工编辑）\n")
        for n in names:
            f.write(n + "\n")


def load_site_state() -> dict:
    try:
        with open(SITE_STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_site_state(site_state: dict):
    os.makedirs(os.path.dirname(SITE_STATE_FILE) or ".", exist_ok=True)
    with open(SITE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(site_state, f, ensure_ascii=False, indent=1, sort_keys=True)


def apply_site_verdict(site_state: dict, key: str, name: str, ok: bool, now: str) -> dict:
    """O3 站点验活历史记忆：连续 SITE_FAIL_LIMIT 轮失败才从配置剔除；任一轮通过即复位（自动回捞）。"""
    ent = site_state.get(key) if isinstance(site_state.get(key), dict) else {}
    ent["name"] = name
    ent.setdefault("removed", False)
    if ok:
        ent["fails"] = 0
        ent["last_ok_at"] = now
        ent["removed"] = False
        ent.pop("removed_at", None)
    else:
        ent["fails"] = int(ent.get("fails", 0)) + 1
        ent["last_fail_at"] = now
        if ent["fails"] >= SITE_FAIL_LIMIT and not ent.get("removed"):
            ent["removed"] = True
            ent["removed_at"] = now
    site_state[key] = ent
    return ent


def load_category_overrides() -> dict:
    """人工分类覆盖表：{"<site key>": "short|adult|vod"}，优先级高于关键词自动分类。"""
    try:
        with open(CATEGORY_OVERRIDE_FILE, "r", encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m, dict):
            return {str(k): str(v) for k, v in m.items()
                    if str(v) in ("short", "adult", "vod")}
    except Exception:  # noqa: BLE001
        pass
    return {}


def enabled_of(u: dict, state: dict, blacklist_manual: list, whitelist_manual: list):
    """返回 (是否拉取, 状态标签)。手动黑名单 > 自动停用（白名单可豁免自动停用）> 启用。
    O2：自动停用超过 PROBE_INTERVAL_DAYS 的上游低频探活一次，成功即自动回捞。"""
    name = u["name"]
    if name in blacklist_manual:
        return False, "blacklisted"
    ent = state.get(name) if isinstance(state.get(name), dict) else {}
    if ent.get("disabled") and name not in whitelist_manual:
        last_fail = ent.get("last_fail_at", "") or ""
        if PROBE_INTERVAL_DAYS > 0 and last_fail:
            try:
                now_naive = datetime.now(BEIJING).replace(tzinfo=None)
                dt = now_naive - datetime.strptime(last_fail, "%Y-%m-%d %H:%M:%S")
                if dt.days >= PROBE_INTERVAL_DAYS:
                    return True, "probe"
            except ValueError:
                pass
        return False, "disabled"
    return True, "enabled"


def upstream_score(name: str, state: dict) -> float:
    """O1 健康度仲裁分：最近成功时间为主（当天 100，每过一天 -10），连续失败每次 -5。
    无成功记录 = 0 分（新上游首轮成功后即达 ~100，可参与同 key 仲裁）。"""
    ent = state.get(name)
    if not isinstance(ent, dict):
        return 0.0
    fc = int(ent.get("fail_count", 0) or 0)
    ok_at = ent.get("last_ok_at", "") or ""
    try:
        # last_ok_at 为北京本地时间字符串（naive），统一按 naive 比较
        now_naive = datetime.now(BEIJING).replace(tzinfo=None)
        days = (now_naive - datetime.strptime(ok_at, "%Y-%m-%d %H:%M:%S")).days
    except (ValueError, TypeError):
        return 0.0
    return max(0.0, 100.0 - days * 10.0) - fc * 5.0


# ---------------- P1：快照存档 ----------------

def snapshot_save(name: str, kind: str, raw: bytes, now: datetime) -> str:
    date_dir = os.path.join(SNAPSHOT_DIR, now.strftime("%Y-%m-%d"))
    os.makedirs(date_dir, exist_ok=True)
    ext = "m3u" if kind == "m3u" else "json"
    path = os.path.join(date_dir, f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}__{now.strftime('%H%M%S')}.{ext}")
    with open(path, "wb") as f:
        f.write(raw)
    return path


def snapshot_prune(keep_days: int) -> list:
    """只保留最近 keep_days 个日期目录，控制仓库体积。"""
    if not os.path.isdir(SNAPSHOT_DIR) or keep_days <= 0:
        return []
    dates = sorted(d for d in os.listdir(SNAPSHOT_DIR)
                   if os.path.isdir(os.path.join(SNAPSHOT_DIR, d)) and re.match(r"^\d{4}-\d{2}-\d{2}$", d))
    removed = []
    for d in dates[:-keep_days]:
        shutil.rmtree(os.path.join(SNAPSHOT_DIR, d), ignore_errors=True)
        removed.append(d)
    return removed


# ---------------- P1：直播分类测速优选 ----------------

def category_of(channel: str, group: str) -> str:
    text = f"{group} {channel}"
    up = text.upper()
    if re.search(r"CCTV|CGTN|CETV|央视", up):
        return "cctv"
    if "卫视" in text:
        return "weishi"
    if re.search(r"香港|台湾|凤凰|TVB|翡翠|明珠|澳门|港台|星空|华视|中天|东森|民视|三立|TVBS|HKTW|HK\b|TW\b", up):
        return "gangtai"
    return "other"


CATEGORY_LABELS = [("cctv", "央视"), ("weishi", "卫视"), ("gangtai", "港台"), ("other", "其他")]


def speed_test(entries, limit: int):
    """并发测速，返回 (lat, spd)。
    lat = {url: latency_ms}，仅 HTTP 200/206 且有数据的 URL 计入；
    spd = {url: MB/s}，对同一请求按实际收到字节数折算吞吐（第一批 P2：
    借鉴 guovin 三维测速中最值得的一维——HTTP Range 抽 LIVE_SPEED_RANGE 字节实测，
    低于 LIVE_MIN_SPEED 的源降权排序、不删除）。
    完全失败的 URL 不在结果里（仍走 O6 保底通道）。"""
    urls = []
    seen = set()
    for _name, _group, url in entries:
        if url not in seen:
            seen.add(url)
            urls.append(url)
    if limit > 0 and len(urls) > limit:
        urls = urls[:limit]  # 顺序即上游优先级，截前 limit 个
    lat = {}
    spd = {}
    print(f"    测速 {len(urls)} 条直播 URL（并发 {LIVE_CONCURRENCY}，单条 {LIVE_TIMEOUT}s，"
          f"Range 抽 {LIVE_SPEED_RANGE >> 10}KB）...", flush=True)

    def probe(u):
        try:
            st, body, ms = http_get(u, LIVE_TIMEOUT, LIVE_SPEED_RANGE,
                                    rng=(0, LIVE_SPEED_RANGE - 1))
            if st in (200, 206) and body:
                dt = ms / 1000.0
                if dt > 0:
                    spd[u] = len(body) / dt / (1 << 20)  # MB/s
                return u, ms
        except Exception:  # noqa: BLE001
            pass
        return u, None

    with cf.ThreadPoolExecutor(LIVE_CONCURRENCY) as ex:
        for u, ms in ex.map(probe, urls):
            if ms is not None:
                lat[u] = ms
    return lat, spd


# ---------------- P0：本地相对路径依赖核验（防死引用写入配置） ----------------

LOCAL_REF_RE = re.compile(r"\./[A-Za-z0-9_\-.\/\u4e00-\u9fff%]+")


def _collect_local_refs(entry) -> list:
    """从站点条目收集 ./ 开头的本地相对路径引用（api/jar/ext 及 ext dict 值）。

    ext 可能是 $$$ 组合串（csp_XBPQ 系：本地路径$$$目标URL$$$参数...），需分段后逐段识别，
    不能把整串当一个本地路径。
    """
    refs: list = []

    def scan(v: str):
        for seg in v.split("$$$"):
            seg = seg.strip()
            if seg.startswith("./"):
                refs.append(seg)
            else:
                refs.extend(m.group(0) for m in LOCAL_REF_RE.finditer(seg))

    if not isinstance(entry, dict):
        return refs
    for field in ("api", "jar", "ext"):
        v = entry.get(field)
        if isinstance(v, str):
            scan(v)
        elif isinstance(v, dict):
            for v2 in v.values():
                if isinstance(v2, str):
                    scan(v2)
    return sorted(set(r[2:] for r in refs if r.startswith("./")))


def _missing_local_refs(entry, repo_dir: str) -> list:
    return [p for p in _collect_local_refs(entry)
            if not os.path.isfile(os.path.join(repo_dir, p))]


def filter_local_ref_sites(sites: list, repo_dir: str, target: str, registry: dict) -> list:
    """写入配置前核验站点 ./ 本地依赖在仓库中真实存在；缺失则剔除该站点并登记到 registry。

    registry 由调用方写入 status.json 的 local_ref_audit，防止每日拉取把死引用写回配置。
    """
    kept, drops = [], []
    for s in sites:
        missing = _missing_local_refs(s, repo_dir)
        if missing:
            drops.append({"key": s.get("key"), "name": s.get("name"), "missing": missing})
        else:
            kept.append(s)
    if drops:
        registry[target] = drops
        print(f"    [local-ref] {target}: 剔除 {len(drops)} 个死引用站点: "
              + ", ".join((d["key"] or "?") for d in drops), flush=True)
    return kept


def build_live_outputs(entries) -> dict:
    """分类 →（可选测速排序）→ 每频道取前 N 条 → 输出 lives/*.txt。返回分类统计 dict。
    测速排序规则（2026-09-21 直播线融合）：吞吐 >= LIVE_MIN_SPEED 的源优先；
    慢速源降权排后但保留（只降权不删除）；完全连不上的 URL 仍剔除走 O6 保底。"""
    os.makedirs(LIVES_DIR, exist_ok=True)
    lat, spd = speed_test(entries, LIVE_MAX_URLS) if LIVE_SPEEDTEST else ({}, {})

    per_cat = {k: [] for k, _ in CATEGORY_LABELS}
    for name, group, url in entries:
        per_cat[category_of(name, group)].append((name, url))

    stats = {}
    for key, label in CATEGORY_LABELS:
        items = per_cat[key]
        if lat:
            by_ch = {}
            for name, url in items:
                ms = lat.get(url)
                if ms is None:
                    continue  # 完全连不上的 URL 剔除（O6 保底兜住）；慢速源不删、仅降权
                by_ch.setdefault(name, []).append((spd.get(url, 0.0), ms, url))
            ranked = []
            for name in sorted(by_ch):
                # 排序键：达速源（吞吐>=LIVE_MIN_SPEED）在前，组内吞吐降序 → 延迟升序 → URL 稳定序
                for _bps, ms, url in sorted(
                        by_ch[name],
                        key=lambda t: (0 if t[0] >= LIVE_MIN_SPEED else 1, -t[0], t[1], t[2])
                )[:LIVE_PER_CHANNEL]:
                    ranked.append((name, url, ms))
            # O6 保底：所有线路测速全挂的频道（多为跑批网络环境误杀）按字母序收录在组尾
            tested_channels = set(by_ch)
            fallback_ch = {}
            for name, url in items:
                if name not in tested_channels:
                    fallback_ch.setdefault(name, []).append(url)
            fallback_used = 0
            for name in sorted(fallback_ch):
                if fallback_used >= LIVE_FALLBACK_CHANNELS:
                    break
                for url in fallback_ch[name][:LIVE_PER_CHANNEL]:
                    ranked.append((name, url, None))
                    fallback_used += 1
        else:
            seen_ch = {}
            ranked = []
            for name, url in items:
                seen_ch.setdefault(name, [])
                if len(seen_ch[name]) < LIVE_PER_CHANNEL:
                    seen_ch[name].append(url)
                    ranked.append((name, url, None))
        stats[key] = {"channels": len({n for n, _u, _ms in ranked}), "urls": len(ranked),
                      "input_urls": len(items), "speed_tested": bool(lat),
                      "slow_speed_urls": (sum(1 for _n, u, ms in ranked
                                              if ms is not None and spd.get(u, 0.0) < LIVE_MIN_SPEED)
                                          if lat else 0),
                      "fallback_urls": (sum(1 for _n, _u, ms in ranked if ms is None) if lat else 0)}
        if not ranked:
            continue
        path = os.path.join(LIVES_DIR, f"live_{key}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{label},#genre#\n")
            for name, url, _ms in ranked:
                f.write(f"{name},{url}\n")
        print(f"    {label}: {stats[key]['channels']} 频道 / {stats[key]['urls']} 条 -> {path}", flush=True)

    with open(os.path.join(LIVES_DIR, "live.txt"), "w", encoding="utf-8") as f:
        for key, _label in CATEGORY_LABELS:
            p = os.path.join(LIVES_DIR, f"live_{key}.txt")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as pf:
                    f.write(pf.read())
    return stats


# ---------------- P1：checks.json + README 回写 ----------------

def sha12(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def write_checks(records: list, generated_at: str) -> dict:
    order = {"ok": 0, "degraded": 1, "dead": 2, "disabled": 3, "blacklisted": 4}
    recs = sorted(records, key=lambda r: order.get(r.get("status"), 5))
    doc = {
        "generated_at": generated_at,
        "note": "每条含最近检测时间、内容 sha256 指纹（前 12 位）、字节数与连续失败计数（azhansy/ds-tvbox checks.json 模式）",
        "summary": {
            "total": len(recs),
            "ok": sum(1 for r in recs if r["status"] == "ok"),
            "degraded": sum(1 for r in recs if r["status"] == "degraded"),
            "dead": sum(1 for r in recs if r["status"] == "dead"),
            "disabled": sum(1 for r in recs if r["status"] == "disabled"),
            "blacklisted": sum(1 for r in recs if r["status"] == "blacklisted"),
        },
        "upstreams": recs,
    }
    with open(CHECKS_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


ICONS = {"ok": "🟢", "degraded": "🟡", "dead": "🔴", "disabled": "⚫", "blacklisted": "🚫"}
STATUS_CN = {"ok": "可用", "degraded": "降级", "dead": "失效", "disabled": "已停用",
             "blacklisted": "黑名单", "probe": "🔵探活", "mirror": "镜像"}


def update_readme_availability(records: list) -> bool:
    """README 内 availability:start/end 锚点间回写可用性表（laoma2053 模式）。"""
    try:
        with open(README_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:  # noqa: BLE001
        return False
    lines = ["| 上游 | 状态 | 字节数 | 指纹 | 连续失败 | 最近通过 |",
             "|------|------|--------|------|----------|----------|"]
    for r in records:
        lines.append(
            "| {name} | {icon} {st} | {bt} | `{fp}` | {fc} | {ok_at} |".format(
                name=r.get("name", ""), icon=ICONS.get(r.get("status"), "⚪"),
                st=STATUS_CN.get(r.get("status"), r.get("status", "")),
                bt=r.get("bytes", 0) or "-", fp=r.get("sha256", "") or "-",
                fc=r.get("fail_count", 0), ok_at=r.get("last_ok_at", "-") or "-"))
    table = "\n".join(lines)
    start = "<!-- availability:start -->"
    end = "<!-- availability:end -->"
    if start in content and end in content:
        pre = content.split(start, 1)[0]
        post = content.split(end, 1)[1]
        content = f"{pre}{start}\n{table}\n{end}{post}"
    else:
        content = content.rstrip() + f"\n\n## 上游可用性（自动回写）\n\n{start}\n{table}\n{end}\n"
    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    return True


# ---------------- 合并辅助（保持既有口径） ----------------

def grade_of(nsites: int, valid: bool) -> str:
    if not valid or nsites <= 0:
        return "不可用"
    if nsites >= 10:
        return "完全可用"
    return "部分可用"


def merge_key_site(s: dict):
    return s.get("key")


def merge_key_live(l: dict):
    return l.get("name")


def merge_key_parse(p: dict):
    return p.get("name")


def site_fingerprint(s: dict) -> str:
    """O4 二级去重指纹：api + ext 内容（不同 key、功能相同的镜像/复刻站点）。"""
    api = (s.get("api") or "").strip().rstrip("/")
    ext = s.get("ext")
    if isinstance(ext, dict):
        ext_s = json.dumps(ext, ensure_ascii=False, sort_keys=True)
    elif isinstance(ext, str):
        ext_s = ext.strip()
    else:
        ext_s = ""
    return hashlib.sha1(f"{api}\n{ext_s}".encode("utf-8")).hexdigest()[:16]


def secondary_dedup_sites(sites_by_key: dict, site_origin_name: dict, site_origin_score: dict) -> list:
    """O4 二级去重：api+ext 指纹相同的站点只留一份，保留来源健康分高者（同分保留先收录者）。
    返回剔除明细列表。"""
    groups: dict = {}
    for k, s in sites_by_key.items():
        groups.setdefault(site_fingerprint(s), []).append(k)
    dropped = []
    for keys in groups.values():
        if len(keys) < 2:
            continue
        keys.sort(key=lambda k: (-(site_origin_score.get(k) or 0.0), k))
        keeper = keys[0]
        for k in keys[1:]:
            dropped.append({"dropped_key": k, "kept_key": keeper,
                            "dropped_origin": site_origin_name.get(k, ""),
                            "kept_origin": site_origin_name.get(keeper, "")})
            sites_by_key.pop(k, None)
            site_origin_name.pop(k, None)
            site_origin_score.pop(k, None)
    return dropped


# ---------------- 三级去重：同库镜像站（片名指纹，证据来自 scripts/probe_sites.py） ----------------
# 一级按 key、二级按 api+ext 指纹都抓不到「同库换域名/换路径」的重复：
#   zuidapi.com 与 zuidazy.co、sdzyapi.com 与 xsd.sdzyapi.com、
#   bfzyapi.com/api.php/provide/vod 与 .../vod/?ac=list
# probe_sites.py 在 L1 抓到的片名集合做 Jaccard 判定（实测 96 个源里 61 个属镜像冗余），
# 结果落在 state/mirror_groups.json，合并阶段据此只保留可用性最好的一份。
MIRROR_GROUPS_FILE = os.environ.get("MIRROR_GROUPS_FILE", "state/mirror_groups.json")
MIRROR_DEDUP = os.environ.get("MIRROR_DEDUP", "1") == "1"


def load_mirror_groups() -> dict:
    """读取镜像分组，返回 {被剔除的 key: 保留的 key}。文件缺失或关闭开关时返回空。"""
    if not MIRROR_DEDUP or not os.path.isfile(MIRROR_GROUPS_FILE):
        return {}
    try:
        with open(MIRROR_GROUPS_FILE, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    mapping = {}
    for g in doc.get("groups", []):
        keep = (g.get("keep") or {}).get("key")
        if not keep:
            continue
        for d in g.get("drops", []):
            if d.get("key"):
                mapping[d["key"]] = keep
    return mapping


def apply_mirror_dedup(sites_by_key: dict, site_origin_name: dict, site_origin_score: dict) -> list:
    """三级去重：剔除同库镜像站点，保留可用性最好的一份。

    仅当保留者本身还在集合中时才剔除，避免出现「剔了重复、留下的也已被删」的空洞。
    """
    mapping = load_mirror_groups()
    if not mapping:
        return []
    dropped = []
    for key, keep in mapping.items():
        if key not in sites_by_key or keep not in sites_by_key:
            continue
        s = sites_by_key.pop(key)
        site_origin_name.pop(key, None)
        site_origin_score.pop(key, None)
        dropped.append({"dropped_key": key, "kept_key": keep,
                        "dropped_name": s.get("name"), "reason": "同库镜像（片名指纹）"})
    return dropped


SORT_ENABLED = os.environ.get("SITE_RANK", "1") == "1"
PROBE_FILE = os.environ.get("PROBE_FILE", "probe/sites_probe.json")
SPIDER_PROBE_FILE = os.environ.get("SPIDER_PROBE_FILE", "probe/spider_probe.json")
JS_PROBE_FILE = os.environ.get("JS_PROBE_FILE", "probe/js_probe.json")
# 真机 csp 实测产物（.workbuddy/csp-test 跑出来后提交进仓库，CI 侧只读复用）
CSP_PROBE_FILE = os.environ.get("CSP_PROBE_FILE", "probe/csp_probe.json")


def merge_check_latency(probe_path: str, latency: dict, now_str: str) -> dict:
    """把 [3/6] 验活实测的「取到内容耗时」合并进 sites_probe.json。

    每条站点记录新增 check_ms / check_at 附加字段——不动 l1/l2 等探针原字段，
    不影响搜索可用性判定；rank_sites.speed_of 会优先使用新鲜的 check_ms 排序。
    """
    doc: dict = {}
    if os.path.isfile(probe_path):
        try:
            with open(probe_path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            doc = {}
    if not isinstance(doc, dict):
        doc = {}
    entries = {r.get("key"): r for r in (doc.get("sites") or [])
               if isinstance(r, dict) and r.get("key")}
    for key, ms in (latency or {}).items():
        ent = entries.get(key)
        if ent is None:
            ent = {"key": key}
            entries[key] = ent
            doc.setdefault("sites", []).append(ent)
        ent["check_ms"] = int(ms)
        ent["check_at"] = now_str
    doc["check_summary"] = {
        "generated_at": now_str,
        "measured": len(latency or {}),
        "unit": "ms；取到有效配置内容的完整耗时（DNS+建连+正文读取）",
    }
    try:
        with open(probe_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
    except OSError:
        return {"written": 0}
    return {"written": len(latency or {})}


def apply_rank(tvbox: dict) -> dict:
    """按「分类 → 搜索可用性 → 实测速度」重排 sites，并写 group / 校正 searchable。

    排序键：分类分组 → 实测可搜优先 → 实测速度升序（无速度的按结构完整度兜底）。
    探针产物缺失时静默跳过，绝不因为缺测速数据而影响出配置。
    """
    if not SORT_ENABLED:
        return {}
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        from rank_sites import rank_sites  # noqa: PLC0415
    except ImportError:
        print("    排序模块不可用（scripts/rank_sites.py 缺失），跳过排序", flush=True)
        return {}

    def _load(path):
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    probe, spider = _load(PROBE_FILE), _load(SPIDER_PROBE_FILE)
    js_probe = _load(JS_PROBE_FILE)
    csp_probe = _load(CSP_PROBE_FILE)
    if not probe and not spider and not js_probe and not csp_probe:
        print("    无探针产物，跳过排序（先跑 scripts/probe_*.py）", flush=True)
        return {}
    ranked, stats = rank_sites(tvbox.get("sites") or [], probe, spider, None, js_probe, csp_probe)
    tvbox["sites"] = ranked
    groups = {k.split(":", 1)[1]: v for k, v in stats.items() if k.startswith("group:")}
    speed = {k.split(":", 1)[1]: v for k, v in stats.items() if k.startswith("speed:")}
    fixes = {k.split(":", 1)[1]: v for k, v in stats.items() if k.startswith("searchable:")}
    print(f"    分类分组：{groups}", flush=True)
    print(f"    速度数据：{speed}；searchable 校正：{fixes}", flush=True)
    return dict(stats)


def rewrite_gh(value):
    """对 site/live/parse 字段里的 GitHub 原链统一加主镜像前缀（先过域名替换层）。"""
    if isinstance(value, str):
        return gh_url(map_domain(value))
    if isinstance(value, list):
        return [rewrite_gh(v) for v in value]
    if isinstance(value, dict):
        return {k: rewrite_gh(v) for k, v in value.items()}
    return value




# ---------------- 多仓拆分（stores/）：按接口类型归类 + cms/app 实测排序 + 网盘 CK 清单 ----------------

STORES_DIR = os.environ.get("STORES_DIR", "stores")
STORE_TIMEOUT = int(os.environ.get("STORE_TIMEOUT", "6"))
STORE_CONCURRENCY = int(os.environ.get("STORE_CONCURRENCY", "16"))
# CMS 标准接口形态：api.php 系（type0 xml / type1 json）、provide/vod、inc/api 及苹果CMS 变体
CMS_API_RE = re.compile(r"api\.php|provide/vod|inc/api|atas\.php", re.I)
# 网盘类 csp 识别：key / name / ext 三路命中（key、name 任一命中即归网盘仓）
PAN_KEY_RE = re.compile(
    r"pan|quark|ucshare|aliyun|thunder|xunlei|pikpak|(^|[^0-9])115|pan123|baidu|tianyi|guangya|"
    r"panso|pika|hunhe|miaosou|dapan|qianfan|yiso|zhaozy|upyun|funletu|gitcafe|webdav|alist|"
    r"clouddrive|share|yunpan|yunso|yundisk", re.I)
PAN_NAME_RE = re.compile(
    r"网盘|夸克|阿里云|迅雷|天翼|移动云|云盘|115|PikPak|123盘|百度盘|UC盘|盘搜|聚合盘|阿里盘", re.I)
PAN_EXT_RE = re.compile(
    r"token\.json|quark|aliyundrive|pikpak|yun\.139|189pc|thunder|mypikpak", re.I)

# 网盘 CK 获取端点表：ck_field 与 token.json 字段一一对应（实测后随 stores/pan_ck.json 发布）。
# 注：api.extscreen.com/aliyundrive/token 直接来自 token.json 的 open_api_url 字段，其余为各盘官方登录入口。
PAN_CK_ENDPOINTS = [
    {"disk": "阿里云盘", "ck_field": "token / open_token", "method": "POST 中转",
     "api": "http://api.extscreen.com/aliyundrive/token",
     "note": "open_api_url 默认中转，POST 传 refresh_token 换 open_token"},
    {"disk": "夸克网盘", "ck_field": "quark_cookie", "method": "网页登录",
     "api": "https://pan.quark.cn", "note": "浏览器登录后 F12 复制 Cookie 全量"},
    {"disk": "UC网盘", "ck_field": "uc_cookie", "method": "网页登录",
     "api": "https://drive.uc.cn", "note": "浏览器登录后 F12 复制 Cookie 全量"},
    {"disk": "天翼云盘", "ck_field": "thunder_username/password + captchatoken", "method": "账密+验证码",
     "api": "https://m.cloud.189.cn/login.html", "note": "账密写入 token.json，登录需验证码"},
    {"disk": "115网盘", "ck_field": "cookie(UID/CID/SEID)", "method": "扫码",
     "api": "https://qrcodeapi.115.com/api/1.0/user/1.0/qrcode/token/", "note": "扫码拿二维码 → 轮询确认换 cookie"},
    {"disk": "PikPak", "ck_field": "pikpak_username/password", "method": "账密",
     "api": "https://user.mypikpak.com/v1/auth/token", "note": "OAuth password grant，账密直接换 token"},
    {"disk": "移动云盘", "ck_field": "yd_auth", "method": "App 抓包",
     "api": "https://passport.yun.139.com", "note": "App 登录后抓包取 auth 值"},
    {"disk": "百度网盘", "ck_field": "cookie(BDUSS)", "method": "网页登录",
     "api": "https://pan.baidu.com", "note": "浏览器登录后复制 BDUSS"},
]


def store_kind_of(s: dict, overrides: dict) -> str:
    """站点 → 子仓归类：cms / app / pan / csp。short/adult 已有独立产物（short/adult.json），此处跳过。"""
    if classify_site(s, overrides) in ("short", "adult"):
        return "skip"
    t = s.get("type")
    if t in (0, 1, "0", "1"):
        api = str(s.get("api") or "")
        return "cms" if CMS_API_RE.search(api) else "app"
    key = str(s.get("key") or "")
    name = str(s.get("name") or "")
    ext = s.get("ext")
    if isinstance(ext, str):
        ext_s = ext
    elif ext is None:
        ext_s = ""
    else:
        try:
            ext_s = json.dumps(ext, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            ext_s = ""
    if PAN_KEY_RE.search(key) or PAN_NAME_RE.search(name) or PAN_EXT_RE.search(ext_s):
        return "pan"
    return "csp"


def cms_speed_test(sites: list) -> dict:
    """对 cms/app 站点 api 并发探测（追加 ac=list），返回 {api: ms}（失败不在结果里）。"""
    apis, seen = [], set()
    for s in sites:
        api = str(s.get("api") or "")
        if api.startswith(("http://", "https://")) and api not in seen:
            seen.add(api)
            apis.append(api)

    def probe(api):
        u = api + ("&" if "?" in api else "?") + "ac=list"
        try:
            st, body, ms = http_get(u, STORE_TIMEOUT, 4096)
            if st == 200 and body:
                return api, ms
        except Exception:  # noqa: BLE001
            pass
        return api, None

    lat: dict = {}
    print(f"    多仓：cms/app 接口测速 {len(apis)} 条（并发 {STORE_CONCURRENCY}，超时 {STORE_TIMEOUT}s）...", flush=True)
    with cf.ThreadPoolExecutor(STORE_CONCURRENCY) as ex:
        for api, ms in ex.map(probe, apis):
            if ms is not None:
                lat[api] = ms
    return lat


def _absolutize(v, base: str = None):
    """子仓内 ./ 相对引用 → 仓库绝对路径（默认 REPO_RAW，代理版传镜像前缀 base）。

    子仓位于 stores/ 下，TVBox 按配置 URL 解析相对路径，不改写会指向 stores/deps/ 而失效；
    ext 支持 $$$ 组合串，需逐段改写；产物为 raw 链接，经 gh_url 套镜像前缀（用户设备直连不了 raw）。"""
    base = base or REPO_RAW
    if isinstance(v, str):
        if "$$$" in v:
            return "$$$".join(_absolutize(seg, base) for seg in v.split("$$$"))
        if v.startswith("./"):
            return gh_url(f"{base}/{v[2:]}")
        return v
    if isinstance(v, list):
        return [_absolutize(x, base) for x in v]
    if isinstance(v, dict):
        return {k: _absolutize(x, base) for k, x in v.items()}
    return v


def csp_searchable_filter(sites: list, repo_dir: str) -> tuple:
    """蜘蛛仓只保留可搜索的接口（2026-09-19 用户指令「核心逻辑只保留可搜索的接口」）。

    信号链（有证据才剔，证据不足保留，不误杀）：
      1. site 显式 searchable == 0 → 剔（上游明说不支持搜索）
      2. ext dict 显式 searchable == 0 → 剔
      3. ext 为本地 ./deps/... 但文件不存在 → 剔（ext 404 站点加载即失败，必然搜不了）
      4. ext 为本地 .js 且文件在盘上：内容含 searchable: 0 → 剔（drpy js 惯例 0/1/2，取头部 64KB 判定）
    返回 (kept, dropped, stats)。"""
    import collections
    dropped: list = []
    by_reason: collections.Counter = collections.Counter()

    def drop(s, why):
        by_reason[why] += 1
        if len(dropped) < 200:
            dropped.append({"key": s.get("key"), "name": s.get("name"), "reason": why})

    kept = []
    for s in sites:
        if str(s.get("searchable")) == "0":
            drop(s, "site.searchable=0")
            continue
        v = s.get("ext")
        if isinstance(v, dict):
            if str(v.get("searchable")) == "0":
                drop(s, "ext.searchable=0")
            else:
                kept.append(s)
            continue
        if isinstance(v, str) and v.strip().startswith("./"):
            p = v.strip().split(";")[0][2:]
            fp = os.path.join(repo_dir, p)
            if not os.path.isfile(fp):
                drop(s, "ext文件缺失(死源)")
                continue
            try:
                with open(fp, "rb") as f:
                    head = f.read(65536).decode("utf-8", "ignore")
            except OSError:
                kept.append(s)
                continue
            if re.search(r"searchable\s*[:=]\s*0\b", head):
                drop(s, "js.searchable=0")
            else:
                kept.append(s)
            continue
        kept.append(s)  # 无 ext / http ext / 无标注：证据不足，保留
    stats = {"total": len(sites), "kept": len(kept), "dropped": len(sites) - len(kept),
             "by_reason": dict(by_reason), "dropped_sample": dropped}
    return kept, dropped, stats


def build_stores(vod: dict, overrides: dict, repo_dir: str) -> dict:
    """按接口类型拆分多仓并写 stores/*.json，返回写入 status.json 的摘要。

    产物：
      stores/cms.json    CMS 标准接口（type 0/1，api.php 系），按实测延迟升序
      stores/app.json    App 型接口（type 0/1 非标准 api），按实测延迟升序
      stores/pan.json    网盘类 csp（需 token.json 填 CK 的均在其中，needs_ck 标记）
      stores/csp.json    其余 csp 蜘蛛站
      stores/pan_ck.json 网盘 CK 获取指引（端点实测可达性）
      stores/duocang.json 多仓入口（纯 urls 格式，条目直挂配置本体，只含 CMS/蜘蛛两条代理线路）
    每个子仓自带 spider/parses/wallpaper/flags 可独立挂载；./ 相对依赖改写为仓库绝对路径并套镜像前缀。
    """
    sites = vod.get("sites") or []
    kinds: dict = {}
    for i, s in enumerate(sites):
        kinds.setdefault(store_kind_of(s, overrides), []).append((i, s))
    cms_app = kinds.get("cms", []) + kinds.get("app", [])
    lat = cms_speed_test([s for _, s in cms_app])

    def ordered(pairs):
        # 实测延迟升序，未测出（失败/超时）置尾；同延迟保持原相对顺序
        return [s for _, s in sorted(pairs, key=lambda t: (lat.get(str(t[1].get("api") or ""), 10 ** 9), t[0]))]

    gh1 = GH_MIRRORS[0].rstrip("/")  # 常量自带尾部斜杠，去重避免出现 //https:// 双斜杠

    def mkdoc(ss):
        doc = {f: _absolutize(vod[f], REPO_RAW)
               for f in ("spider", "wallpaper", "parses", "flags") if vod.get(f) is not None}
        ss2 = []
        for s in ss:
            s2 = dict(s)
            for f in ("jar", "ext"):
                if f in s2:
                    s2[f] = _absolutize(s2[f], REPO_RAW)
            ss2.append(s2)
        doc["sites"] = ss2
        return doc

    os.makedirs(STORES_DIR, exist_ok=True)
    counts: dict = {}
    stores_meta = (("cms", "cms.json", "CMS接口仓(按速度排序)"),
                   ("app", "app.json", "App接口仓(按速度排序)"),
                   ("pan", "pan.json", "网盘仓"),
                   ("csp", "csp.json", "蜘蛛仓(csp)"))
    csp_filter_stats = None
    for k, fname, _label in stores_meta:
        if k in ("cms", "app"):
            ss = ordered(kinds.get(k, []))
        elif k == "csp":
            # 蜘蛛仓只保留可搜索的接口（用户指令），剔除明细见 status.json
            ss, _csp_dropped, csp_filter_stats = csp_searchable_filter(
                [s for _, s in kinds.get(k, [])], repo_dir)
        else:
            ss = [s for _, s in kinds.get(k, [])]
        with open(os.path.join(STORES_DIR, fname), "w", encoding="utf-8") as f:
            json.dump(mkdoc(ss), f, ensure_ascii=False, indent=1)
        counts[k] = len(ss)

    # 网盘 CK 清单：needs_ck = ext 引用 token.json（需填 CK/账密才出内容）
    pan_rows = []
    for _, s in kinds.get("pan", []):
        ext = s.get("ext")
        ext_s = ext if isinstance(ext, str) else (json.dumps(ext, ensure_ascii=False) if ext else "")
        pan_rows.append({"key": s.get("key"), "name": s.get("name"),
                         "needs_ck": bool(ext_s and "token.json" in ext_s)})
    pan_rows.sort(key=lambda r: (not r["needs_ck"], str(r["name"])))

    # CK 获取端点实测：服务端有响应（含非 2xx）即算可达
    ck_endpoints = []
    for e in PAN_CK_ENDPOINTS:
        rec = dict(e)
        try:
            st, _body, ms = http_get(e["api"], 8, 512)
            rec.update({"reachable": True, "http_status": st, "ms": ms})
        except urllib.error.HTTPError as he:
            # 非 2xx 也是服务端真实响应（POST-only 端点对 GET 回 404/405 属正常）＝域名可达
            rec.update({"reachable": True, "http_status": he.code})
        except Exception as ex_:  # noqa: BLE001
            rec.update({"reachable": False, "err": f"{type(ex_).__name__}: {ex_}"[:120]})
        ck_endpoints.append(rec)
    with open(os.path.join(STORES_DIR, "pan_ck.json"), "w", encoding="utf-8") as f:
        json.dump({
            "note": "网盘 CK 填写指引：CK/账密统一填本仓库 deps/qist/js/lib/token.json（字段见各站点 ck_field）；"
                    "该文件非空时 daily 保留现值不回源覆盖",
            "token_file": "./deps/qist/js/lib/token.json",
            "endpoints": ck_endpoints,
        }, f, ensure_ascii=False, indent=1)

    # 多仓入口：对齐社区标准格式（参考 z.qiqiv.cn/123.txt）——顶层只有 urls、条目直挂配置本体。
    # 实测教训（2026-09-19 用户影视仓截图「Json解析失败No value for urls」）：storeHouse+urls 双格式会让
    # 影视仓走 storeHouse 分支、把条目再按「仓」解析（要求 urls），直挂的 sites 配置就会报错；
    # 纯 urls 格式下 App 把条目当配置加载，与参考仓行为一致。
    # 用户指定（2026-09-19）：入口只保留 CMS 接口仓与蜘蛛仓两条线路（App 接口仓、网盘仓不进入口，
    # 对应文件仍照常生成，可单独挂载）；「代理」指入口 JSON 本身经 ghproxy 镜像加速拉取。
    # 依赖引用一律仓库路径（用户指令「依赖文件落库，相关的路径引用改成仓库路径」）：
    # 子仓内部 spider/ext 引用为 raw.githubusercontent.com 本仓库绝对路径（_absolutize 产出），
    # 第三方静态依赖已由 collect_and_rewrite_deps + localize_external_refs 落库 deps/，
    # 不再生成 *_proxy.json 镜像前缀变体（用户网络实测可达 raw，镜像前缀反而引入单点故障）。
    entry = []
    for k, fname, label in stores_meta:
        if k in ("app", "pan"):
            continue
        entry.append({"url": f"{gh1}/{REPO_RAW}/stores/{fname}", "name": f"{label}·代理"})
    duocang = {"urls": entry}
    with open(os.path.join(STORES_DIR, "duocang.json"), "w", encoding="utf-8") as f:
        json.dump(duocang, f, ensure_ascii=False, indent=1)

    def top10(k):
        return [{"name": s.get("name"), "ms": lat[str(s.get("api") or "")]}
                for s in ordered(kinds.get(k, []))[:10] if str(s.get("api") or "") in lat]

    print(f"[5.5/6] 多仓：cms {counts['cms']} / app {counts['app']} / pan {counts['pan']} / csp {counts['csp']}"
          f" → stores/（接口测速通过 {len(lat)}/{len(cms_app)}）", flush=True)
    return {
        "note": "按接口类型拆分多仓：cms/app 按实测延迟升序；stores/duocang.json 为多仓入口（纯 urls 格式对齐社区标准，只含 CMS/蜘蛛两条代理线路）；子仓内部依赖引用一律本仓库路径（第三方静态依赖已落库 deps/localized/）",
        "counts": counts,
        "entry_mirror": gh1,
        "speed_tested": len(cms_app),
        "speed_ok": len(lat),
        "csp_searchable_filter": ({"total": csp_filter_stats["total"],
                                   "kept": csp_filter_stats["kept"],
                                   "dropped": csp_filter_stats["dropped"],
                                   "by_reason": csp_filter_stats["by_reason"]}
                                  if csp_filter_stats else None),
        "cms_speed_top10": top10("cms"),
        "app_speed_top10": top10("app"),
        "pan_sites": pan_rows,
        "pan_ck_endpoints": [{"disk": e["disk"], "api": e["api"], "reachable": e.get("reachable", False),
                              "http_status": e.get("http_status")} for e in ck_endpoints],
    }


# ---- 2026-09-21 点播+容错线：容错函数化（便于构造空场景做单元测试）----

def read_prev_counts(path="tvbox.json") -> dict:
    """读上一版产物（工作树 tvbox.json）的三类条目数；读不到返回 {}。"""
    try:
        with open(path, "r", encoding="utf-8") as _f:
            _p = json.load(_f)
        return {"sites": len(_p.get("sites") or []),
                "lives": len(_p.get("lives") or []),
                "parses": len(_p.get("parses") or [])}
    except Exception:  # noqa: BLE001 —— 首轮无历史产物属正常
        return {}


def empty_guard_check(cur: dict, prev: dict, drop_ratio: float = None) -> list:
    """空产物守卫判定：返回触发原因列表（空列表 = 通过）。
    任一维度为 0，或相对上一版萎缩超 drop_ratio，即判定本轮产物异常。"""
    if drop_ratio is None:
        drop_ratio = EMPTY_GUARD_DROP_RATIO
    blocked = []
    for _dim, _cnt in cur.items():
        if _cnt == 0:
            blocked.append(f"{_dim}=0（空产物）")
        elif prev.get(_dim, 0) > 0 and _cnt < prev[_dim] * (1 - drop_ratio):
            blocked.append(f"{_dim} {prev[_dim]}→{_cnt}（萎缩超 {drop_ratio:.0%}）")
    return blocked


def apply_blacklist_round_cap(state: dict, disabled_now_list: list,
                              round_total: int, ratio: float = None) -> list:
    """黑名单单轮安全阀：本轮拟停用数超过上游总数 ratio（默认 30%）时判定为
    网络抖动等单轮系统性误判，回滚全部 disabled 标志（fail_count 保留，
    sync_blacklist_auto 按 disabled 标志回写，故黑名单文件本轮不会有任何新增），
    返回回滚后的空列表；未超阈值时原样返回。"""
    if ratio is None:
        ratio = BLACKLIST_ROUND_CAP_RATIO
    round_cap = max(1, int(round_total * ratio))
    if not disabled_now_list or len(disabled_now_list) <= round_cap:
        return disabled_now_list
    print(f"  [安全阀] 本轮拟自动停用 {len(disabled_now_list)} 个，超过上游总数 {round_total} 的 "
          f"{ratio:.0%}（阈值 {round_cap} 个）——判定为网络抖动等单轮系统性误判："
          f"全部回滚、不落盘黑名单（fail_count 保留，真失效下轮仍会正常停用）", flush=True)
    print(f"  [安全阀] 回滚名单：{', '.join(disabled_now_list)}", flush=True)
    for _n in disabled_now_list:
        _ent = state.get(_n)
        if isinstance(_ent, dict) and _ent.get("disabled"):
            _ent["disabled"] = False
            _ent["disabled_reason"] = ""
    return []


def main() -> int:
    global DOMAIN_MAP
    DOMAIN_MAP = load_domain_map()
    now = datetime.now(BEIJING)
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S") + " +08:00"

    state = load_state()
    site_state = load_site_state()          # O3 站点验活历史
    category_overrides = load_category_overrides()  # 人工分类覆盖表
    blacklist_manual = read_name_list(BLACKLIST_MANUAL)
    whitelist_manual = read_name_list(WHITELIST_MANUAL)

    interfaces = []          # 每条上游的测试记录（list.json，保持原字段）
    checks = []              # P1 校验状态记录（checks.json）
    merged: dict = {}        # 全局字段
    spider_origin_info = None
    site_origin_name: dict = {}   # site key -> 来源上游名
    upstream_spider: dict = {}     # 上游名 -> 它自己声明的顶层 spider（合并只能留一份全局的，其余靠它补回）
    site_origin_score: dict = {}  # site key -> 来源上游健康分（O1 同 key 仲裁）
    live_origin_score: dict = {}  # live name -> 来源上游健康分
    parse_origin_score: dict = {} # parse name -> 来源上游健康分
    seen_sha: dict = {}           # 内容 sha12 -> 首个上游名（O5 镜像短路）
    mirror_count = 0
    sites_by_key: dict = {}
    lives_by_name: dict = {}
    parses_by_name: dict = {}

    active_upstreams = ALL_UPSTREAMS + load_extra_upstreams()
    for u in active_upstreams:          # canary 上游的相对路径依赖也要能解析
        if u.get("kind") == "tvbox" and u.get("name") not in UPSTREAM_BASES:
            UPSTREAM_BASES[u["name"]] = u["url"].rsplit("/", 1)[0] + "/"
    print(f"[1/6] 拉取 {len(active_upstreams)} 个上游（含 {len(LIVE_UPSTREAMS)} 个直播源上游）...", flush=True)
    fetchable = []
    for u in active_upstreams:
        ok, tag = enabled_of(u, state, blacklist_manual, whitelist_manual)
        fetchable.append((u, ok, tag))

    def do_fetch(item):
        u, ok, _tag = item
        if not ok:
            return u, None, "skipped", "", ""
        raw, info, ok_url = fetch_raw(u["url"], u.get("mirrors"))
        d_method = ""
        # 吸收点 P1-1：混淆配置解码（仅 tvbox 配置类；明文零开销直通，
        # 解码失败按候选失败处理，绝不把密文残留进下游解析/快照）。
        if raw is not None and u.get("kind") == "tvbox":
            raw, d_method = decode_config(raw)
            if raw is None:
                info = f"decode failed: {d_method}"
        return u, raw, info, ok_url, d_method

    with cf.ThreadPoolExecutor(min(8, CONCURRENCY)) as ex:
        fetched = list(ex.map(do_fetch, fetchable))

    snapshot_paths = []
    disabled_now_list = []
    for (u, fetchable_ok, tag), (u2, raw, info, ok_url, d_method) in zip(fetchable, fetched):
        name, kind = u["name"], u["kind"]
        state_ent = state.get(name) if isinstance(state.get(name), dict) else {}
        rec = {
            "name": name, "url": u["url"], "kind": kind,
            "http_ms": 0, "channel": "", "bytes": 0, "sha256": "",
            "sites": 0, "lives": 0, "parses": 0,
            "merged_sites": 0, "merged_lives": 0, "merged_parses": 0,
            "grade": "不可用", "error": "",
            "status": tag, "fail_count": int(state_ent.get("fail_count", 0)),
            "last_ok_at": state_ent.get("last_ok_at", ""),
            "decode": d_method, "success_url": ok_url or "",
        }
        if not fetchable_ok:
            checks.append(rec)
            interfaces.append(rec)
            print(f"  SKIP {name}（{STATUS_CN.get(tag, tag)}）", flush=True)
            continue

        if raw is not None:
            rec["bytes"] = len(raw)
            rec["sha256"] = sha12(raw)
            snapshot_paths.append(snapshot_save(name, kind, raw, now))
            # O5 同内容镜像短路：配置内容与已处理上游 sha256 一致时跳过解析合并
            if kind == "tvbox" and rec["sha256"] and rec["sha256"] in seen_sha:
                rec["mirror_of"] = seen_sha[rec["sha256"]]
                rec["status"] = "ok"
                rec["grade"] = "镜像"
                record_result(state, name, True, whitelist_manual)  # 健康分照常刷新，主域失效时可接管
                rec["fail_count"] = 0
                rec["last_ok_at"] = state[name].get("last_ok_at", "")
                checks.append(rec)
                interfaces.append(rec)
                mirror_count += 1
                print(f"  MIRROR {name}: 内容与 {rec['mirror_of']} 一致（sha {rec['sha256']}），跳过合并", flush=True)
                continue
            if rec["sha256"]:
                seen_sha[rec["sha256"]] = name

        ok_eval, status_tag, detail, err = evaluate_upstream(u, raw)
        rec["status"] = status_tag
        rec["error"] = err or ""
        outcome = record_result(state, name, ok_eval, whitelist_manual)
        if outcome == "disabled_now":
            disabled_now_list.append(name)
        rec["fail_count"] = int(state[name].get("fail_count", 0))
        rec["last_ok_at"] = state[name].get("last_ok_at", "")
        if raw is None:
            rec["error"] = info
        else:
            rec["channel"] = info

        if not ok_eval:
            checks.append(rec)
            interfaces.append(rec)
            print(f"  {'DEGRADED' if status_tag == 'degraded' else 'FAIL'} {name}: {err or info}", flush=True)
            continue

        if u.get("canary"):
            # 第十三批：canary 只监控不合并——健康分/快照照常，内容不进 tvbox.json/live.json
            rec["grade"] = "canary"
            checks.append(rec)
            interfaces.append(rec)
            print(f"  CANARY {name}: 内容校验通过（{rec['bytes']}B），仅监控不合并", flush=True)
            continue

        # ---- 合并 ----
        if kind == "tvbox":
            cfg = detail["cfg"]
            cfg_sites = [s for s in (cfg.get("sites") or [])
                         if isinstance(s, dict) and s.get("key") and s.get("api")]
            cfg_lives = [l for l in (cfg.get("lives") or []) if isinstance(l, dict) and l.get("name")]
            cfg_parses = [p for p in (cfg.get("parses") or []) if isinstance(p, dict) and p.get("name")]
            added_s = added_l = added_p = 0
            repl_s = repl_l = repl_p = 0
            sc = upstream_score(name, state)
            for s in cfg_sites:
                k = merge_key_site(s)
                if not k:
                    continue
                if k not in sites_by_key:
                    sites_by_key[k] = rewrite_gh(s)
                    site_origin_name[k] = name
                    site_origin_score[k] = sc
                    added_s += 1
                elif sc > site_origin_score.get(k, -10 ** 9):
                    # O1 健康度仲裁：来源更健康的上游接管同 key 站点（同分保持先到先得，避免抖动）
                    sites_by_key[k] = rewrite_gh(s)
                    site_origin_name[k] = name
                    site_origin_score[k] = sc
                    repl_s += 1
            for l in cfg_lives:
                k = merge_key_live(l)
                if not k:
                    continue
                if k not in lives_by_name:
                    lives_by_name[k] = rewrite_gh(l)
                    live_origin_score[k] = sc
                    added_l += 1
                elif sc > live_origin_score.get(k, -10 ** 9):
                    lives_by_name[k] = rewrite_gh(l)
                    repl_l += 1
            for p in cfg_parses:
                k = merge_key_parse(p)
                if not k:
                    continue
                if k not in parses_by_name:
                    parses_by_name[k] = rewrite_gh(p)
                    parse_origin_score[k] = sc
                    added_p += 1
                elif sc > parse_origin_score.get(k, -10 ** 9):
                    parses_by_name[k] = rewrite_gh(p)
                    repl_p += 1
            valid = bool(cfg_sites)
            rec.update(
                sites=len(cfg_sites), lives=len(cfg_lives), parses=len(cfg_parses),
                merged_sites=added_s, merged_lives=added_l, merged_parses=added_p,
                grade=grade_of(len(cfg_sites), valid), channel=info,
            )
            for gk in ("spider", "wallpaper"):
                if gk in cfg and gk not in merged and isinstance(cfg[gk], str):
                    merged[gk] = rewrite_gh(cfg[gk])
                    if gk == "spider":
                        spider_origin_info = (name, u["url"].rsplit("/", 1)[0] + "/")
            # 记下**每个**上游自己的 spider（不管有没有被选成全局），
            # 供 assign_origin_spiders 给这些源补回它原本该用的那份包
            if isinstance(cfg.get("spider"), str) and cfg["spider"]:
                upstream_spider[name] = cfg["spider"]
            print(f"  OK   {name}: sites={len(cfg_sites)} lives={len(cfg_lives)} "
                  f"parses={len(cfg_parses)} (+{added_s}/{added_l}/{added_p} repl {repl_s}/{repl_l}/{repl_p}) "
                  f"{rec['bytes']}B #{rec['sha256']}", flush=True)
        else:
            print(f"  OK   {name}: {detail['entries']} 条频道 {rec['bytes']}B #{rec['sha256']}", flush=True)
        checks.append(rec)
        interfaces.append(rec)

    # 2026-09-21 点播+容错线：黑名单单轮安全阀（判定与回滚逻辑见 apply_blacklist_round_cap）
    disabled_now_list = apply_blacklist_round_cap(
        state, disabled_now_list, len(active_upstreams), BLACKLIST_ROUND_CAP_RATIO)
    sync_blacklist_auto(state)
    save_state(state)
    if disabled_now_list:
        print(f"  本轮自动停用：{', '.join(disabled_now_list)}", flush=True)

    usable_config = [r for r in interfaces if r["kind"] == "tvbox" and r["grade"] != "不可用"]
    if not usable_config:
        print("所有配置类上游均不可用，中止（不产出配置）", flush=True)
        return 1

    dup_drops = secondary_dedup_sites(sites_by_key, site_origin_name, site_origin_score)
    if dup_drops:
        print(f"    二级去重：剔除 {len(dup_drops)} 个 api/ext 指纹重复站点（保留健康来源）", flush=True)
    mirror_drops = apply_mirror_dedup(sites_by_key, site_origin_name, site_origin_score)
    if mirror_drops:
        print(f"    三级去重：剔除 {len(mirror_drops)} 个同库镜像站点（片名指纹，保留可用性最好的一份）", flush=True)
    sites = list(sites_by_key.values())
    lives = list(lives_by_name.values())
    parses = list(parses_by_name.values())
    print(f"[2/6] 合并完成：{len(sites)} sites / {len(lives)} lives / {len(parses)} parses", flush=True)

    # ---- 解析池清洗（解决「一堆没用的解析」）----
    # 站点去重只看 key，无法处理「同一 URL 多个不同 name」的解析池；调用 clean_parses
    # 做结构校验 + 私有地址剔除 + URL 规范化去重 + TCP 主机探活（沙箱/CI 受限时可走
    # SKIP_PARSE_PROBE=1 跳过；安全阀保障网络故障不会清空解析池）。
    skip_probe = os.environ.get("SKIP_PARSE_PROBE", "0") == "1"
    parses, parse_stats = clean_parses(parses, do_probe=not skip_probe)
    print(f"[2/6] 解析清洗：{parse_stats['before']} → {parse_stats['after']}"
          f"（无效 {parse_stats['dropped_invalid']} / 私有 {parse_stats['dropped_private']}"
          f" / 重复 {parse_stats['dropped_duplicate']} / 不可达 {parse_stats['dropped_unreachable']}"
          f"{' / ⚠安全阀触发' if parse_stats['safety_valve_triggered'] else ''}）",
          flush=True)
    # 解析池回写：parses 在 [5/6] 输出装配时统一写入 tvbox["parses"]（vod 由 tvbox
    # 派生自动继承）；此处 tvbox/vod 尚未构建，提前引用会 UnboundLocalError
    # （2026-09-23 CI run 35767489299 实证）。

    # ---- 上游投票预扫（防关键词单匹配误杀）----
    # 给每个站点打上 _origin 标签（来自 site_origin_name），用强信号 + 覆盖表 + 误报
    # 白名单 + 短剧词 判定成人站，按上游仓库计数。后续 classify_site 调用会读
    # _origin + origin_votes 做仓库级聚合判定。
    origin_votes: dict = {}
    for s in sites:
        key = s.get("key")
        if not key:
            continue
        origin = site_origin_name.get(key) or ""
        if origin:
            s["_origin"] = origin
        cat = classify_site_strong_only(s, category_overrides)
        if cat == "adult":
            origin_votes[origin.lower()] = origin_votes.get(origin.lower(), 0) + 1
    # _origin 无需二次同步到 vod.sites：vod 由 tvbox 浅拷贝派生、tvbox["sites"] =
    # kept_sites 与上面 `sites` 是同一批 dict 对象，首循环已全部打上标签；rank_sites
    # 的 dict 拷贝也会带上 _origin。（原 vod.get("sites") 提前引用已在 CI
    # run 35769498157 实证为 UnboundLocalError，删除。）

    # ---- [3/6] 测速验活：仅 type 0/1 且 api 为 http(s) 的直连站点 ----
    def testable(s: dict) -> bool:
        return s.get("type") in (0, 1) and isinstance(s.get("api"), str) and s["api"].startswith("http")

    def check_site(s: dict):
        """验活 + 实测「取到内容耗时」，返回 (ok, ms)。

        ms 是拿到有效配置正文（JSON/XML 头）的完整耗时——含 DNS/建连/正文读取，
        不是空连通快；正文无效（HTML 错误页等）一律视为失败，不给速度。
        """
        url = s["api"]
        ms = 0
        for _ in range(2):  # 失败重试一次
            try:
                status, body, elapsed = http_get(url, TEST_TIMEOUT, MAX_BODY)
                ms = elapsed
                if status == 200 and body:
                    head = body[:1024].lstrip()
                    low = head.lower()
                    if head[:1] in (b"{", b"<") and b"<html" not in low:
                        return True, ms
            except Exception:  # noqa: BLE001
                pass
        return False, ms

    to_test = [] if SKIP_SITE_TEST else [s for s in sites if testable(s)]
    limit = int(os.environ.get("SITE_LIMIT", "0"))
    if limit > 0:
        to_test = to_test[:limit]
    print(f"[3/6] 站点验活：{len(to_test)}/{len(sites)} 个直连站点，并发 {CONCURRENCY} ...", flush=True)
    t0 = time.time()
    verdict: dict = {}  # key -> (ok, ms)：ok=验活通过，ms=取到有效内容耗时（最后一轮）
    with cf.ThreadPoolExecutor(CONCURRENCY) as ex:
        futs = {ex.submit(check_site, s): s for s in to_test}
        done = 0
        for fut in cf.as_completed(futs):
            s = futs[fut]
            try:
                verdict[s["key"]] = fut.result()
            except Exception:  # noqa: BLE001
                verdict[s["key"]] = (False, 0)
            done += 1
            if done % 100 == 0:
                print(f"  ... {done}/{len(to_test)} ({time.time()-t0:.0f}s)", flush=True)

    removed = []
    kept_sites = []
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    for s in sites:
        if testable(s) and (verdict.get(s["key"]) or (True, 0))[0] is False:
            # O3 站点验活历史：连续 SITE_FAIL_LIMIT 轮失败才剔除；未达阈值暂留观察
            ent = apply_site_verdict(site_state, s.get("key") or "", s.get("name") or "", False, now_str)
            if ent.get("removed"):
                removed.append({
                    "key": s.get("key"), "name": s.get("name"),
                    "api": s.get("api"),
                    "reason": f"连续 {ent.get('fails', 0)} 轮验活失败（>= {SITE_FAIL_LIMIT} 轮剔除）",
                })
            else:
                kept_sites.append(s)
        else:
            if testable(s):
                apply_site_verdict(site_state, s.get("key") or "", s.get("name") or "", True, now_str)
            kept_sites.append(s)
    save_site_state(site_state)
    tested_pass = sum(1 for v in verdict.values() if v and v[0])
    print(f"    通过 {tested_pass}/{len(to_test)}，剔除 {len(removed)}，保留 {len(kept_sites)} 站点", flush=True)

    # ---- 站点速度：把「取到内容耗时」并入 sites_probe.json，作为新鲜排序依据 ----
    check_latency: dict = {k: int(v[1]) for k, v in verdict.items() if v[0] and v[1] > 0}
    if check_latency:
        _ordered = sorted(check_latency.items(), key=lambda kv: kv[1])
        _p50 = _ordered[len(_ordered) // 2][1]
        print(f"    速度实测：{len(check_latency)} 站取到内容耗时中位 {_p50}ms"
              f"（最快 {_ordered[0][1]}ms / {_ordered[0][0][:24]}）", flush=True)
        _ck_stats = merge_check_latency(PROBE_FILE, check_latency, now_str)
        if _ck_stats.get("written"):
            print(f"    速度数据已并入 {PROBE_FILE}（{len(check_latency)} 条 check_ms）", flush=True)

    # ---- 成人内容发布开关（默认不发布，见 PUBLISH_ADULT 的说明）----
    adult_excluded_sites: list = []
    if not PUBLISH_ADULT:
        before = len(kept_sites)
        adult_excluded_sites = [s for s in kept_sites if classify_site(s, category_overrides, origin_votes) == "adult"]
        kept_sites = [s for s in kept_sites if classify_site(s, category_overrides, origin_votes) != "adult"]
        if adult_excluded_sites:
            print(f"    [adult] 不声明模式：从主产物剔除 {len(adult_excluded_sites)} 个成人分类站点"
                  f"（{before} → {len(kept_sites)}）；成人源完整写入仓库根 adult.json"
                  f"（随 daily 提交更新，不进 Release/Pages/导航页）",
                  flush=True)

    # ---- [4/6] 直播源分类测速优选 ----
    print("[4/6] 直播源分类测速优选（Guovin 上游 → 央视/卫视/港台/其他）...", flush=True)
    m3u_entries = []
    for (u, fetchable_ok, tag), (u2, raw, info, _ok_url, _d_method) in zip(fetchable, fetched):
        if u["kind"] != "m3u" or raw is None:
            continue
        try:
            for name, group, url in parse_m3u(raw):
                # 过滤 Guovin 列表头的「更新时间」伪频道与纯日期条目
                if re.search(r"更新时间|update.?time", group, re.I):
                    continue
                if re.match(r"^\d{4}-\d{2}-\d{2}", name):
                    continue
                m3u_entries.append((name, group, url))
        except Exception:  # noqa: BLE001
            pass
    seen_pairs = set()
    dedup_entries = []
    for name, group, url in m3u_entries:
        pk = (name, url)
        if pk not in seen_pairs:
            seen_pairs.add(pk)
            dedup_entries.append((name, group, url))
    print(f"    共 {len(m3u_entries)} 条，去重后 {len(dedup_entries)} 条", flush=True)
    live_stats = {}
    if dedup_entries:
        live_stats = build_live_outputs(dedup_entries)
        for key, label in CATEGORY_LABELS:
            entry_name = f"Guovin·{label}"
            if os.path.exists(os.path.join(LIVES_DIR, f"live_{key}.txt")) and entry_name not in lives_by_name:
                lives_by_name[entry_name] = rewrite_gh({
                    "name": entry_name, "type": 0,
                    "url": f"{REPO_RAW}/lives/live_{key}.txt",
                    "epg": "https://live.fanmingming.cn/e.xml",
                })
    lives = list(lives_by_name.values())

    # ---- [5/6] 产出配置 ----
    # 2026-09-21 点播+容错线：空产物守卫（必须在写任何产物文件之前执行）。
    # 上一版已提交产物 = 工作树里的 tvbox.json（守卫在覆盖它之前返回，即天然保留上次缓存）；
    # 判定逻辑见 empty_guard_check / read_prev_counts。
    _cur = {"sites": len(kept_sites), "lives": len(lives), "parses": len(parses)}
    _prev = read_prev_counts("tvbox.json")
    _blocked = empty_guard_check(_cur, _prev, EMPTY_GUARD_DROP_RATIO)
    if _blocked:
        _guard_note = {
            "triggered_at": generated_at,
            "current": _cur, "previous": _prev,
            "reasons": _blocked,
            "action": "跳过本轮产物写入/提交/Release，保留上次缓存，下轮重试",
        }
        try:
            os.makedirs("state", exist_ok=True)
            with open("state/guard_last.json", "w", encoding="utf-8") as _f:
                json.dump(_guard_note, _f, ensure_ascii=False, indent=1)
        except Exception:  # noqa: BLE001
            pass
        print("[守卫] 空产物守卫触发，本轮不产出、不提交、不发布：", flush=True)
        for _b in _blocked:
            print(f"    - {_b}", flush=True)
        print("    已保留上次缓存（工作树 tvbox.json 未被覆盖）；详见 state/guard_last.json", flush=True)
        return 2

    tvbox = dict(merged)
    tvbox["sites"] = kept_sites
    tvbox["lives"] = lives
    tvbox["parses"] = parses
    # 关键：给「走全局 spider」的源补回它来源上游那份 spider，否则它们会指向不含所需爬虫类的包
    osp_stats = assign_origin_spiders(tvbox, site_origin_name, upstream_spider, spider_origin_info)
    if osp_stats.get("assigned"):
        print(f"    按来源上游补回 spider 的源：{osp_stats['assigned']} 个"
              f"（与全局同包 {osp_stats.get('same_as_global', 0)}、上游未声明 "
              f"{osp_stats.get('origin_no_spider', 0)}）", flush=True)
    dep_stats = collect_and_rewrite_deps(tvbox, site_origin_name, spider_origin_info)
    loc_stats = localize_external_refs(tvbox)
    # 安全网：没能落库的 per-site jar 撤掉，避免留下客户端解析不了的相对路径
    prune_unlocalized_jars(tvbox)
    # 按「分类 → 搜索可用性 → 实测速度」重排站点（实现见 scripts/rank_sites.py）
    rank_stats = apply_rank(tvbox)
    with open("tvbox.json", "w", encoding="utf-8") as f:
        json.dump(tvbox, f, ensure_ascii=False, indent=1)

    # ---- 拆分产物：vod.json（点播）+ live.json（直播）----
    # vod.json = tvbox 去掉 lives（保留 spider / wallpaper / sites / parses 等点播相关字段）；
    # live.json = {"lives": [...]}，并确保汇总 lives/ 目录的分类文件条目（央视/卫视/港台/其他）。
    vod = {k: v for k, v in tvbox.items() if k != "lives"}
    live = {"lives": [l for l in lives if isinstance(l, dict) and l.get("name")]}
    # ---- 直播重构：以本次实测聚合为主入口（央视/卫视/港台分组 + 核心频道多线路）----
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    curated_lives, adult_lives = build_curated_lives(repo_dir)
    # 1. 移除 live.json 里已知不可用的相对路径 / 本地代理条目；保留其余第三方作为备用
    _REJECT_PREFIX = ("http://127.0.0.1", "http://localhost", "http://0.0.0.0")
    _ALLOWED_SCHEME = ("http://", "https://")
    cleaned = []
    for l in live["lives"]:
        u = (l.get("url") or "")
        if not u:
            continue
        if not u.startswith(_ALLOWED_SCHEME):
            continue
        if any(u.startswith(p) for p in _REJECT_PREFIX):
            continue
        # 折叠双协议
        while "https://https://" in u or "http://http://" in u:
            u = u.replace("https://https://", "https://", 1)
            u = u.replace("http://http://", "http://", 1)
        l["url"] = u
        # 成人主题 lives 一律下放到 adult.json
        if any(k in (l.get("name") or "").lower() for k in ("传媒816", "18+", "成人", "pron", "live18")):
            adult_lives.append({
                "name": l.get("name"), "type": l.get("type", 1),
                "url": l.get("url"), "group": "成人直播",
            })
            continue
        cleaned.append(l)
    # 聚合精选 + 第三方实测 ok 在前；其余按名字升序保留
    live["lives"] = curated_lives + sorted(
        [l for l in cleaned if l not in curated_lives],
        key=lambda x: (x.get("name") or "")
    )
    with open("vod.json", "w", encoding="utf-8") as f:
        json.dump(vod, f, ensure_ascii=False, indent=1)
    with open("live.json", "w", encoding="utf-8") as f:
        json.dump(live, f, ensure_ascii=False, indent=1)

    # ---- 多仓拆分：stores/{cms,app,pan,csp,duocang,pan_ck}.json ----
    stores_summary = build_stores(vod, category_overrides, repo_dir)

    # ---- 拆分产物：short.json（短剧）+ adult.json（成人），独立收录不剥离 vod ----
    # vod.json 保持完整（含所有点播站点）；short/adult 为分类独立配置。
    # parses 复用 vod 全集：TVBox 站点不引用 parses（playUrl/jar 才是站点自有播放方式），
    # parses 是全局播放器池，单独配置需自带全集才不至于某些解析器不可用。
    short_sites = [s for s in (vod.get("sites") or []) if classify_site(s, category_overrides, origin_votes) == "short"]
    if PUBLISH_ADULT:
        adult_sites = [s for s in (vod.get("sites") or []) if classify_site(s, category_overrides, origin_votes) == "adult"]
    else:
        # 不声明模式下 vod.sites 里已经没有成人源了（前面已剔除），用当时留存的那份
        adult_sites = adult_excluded_sites
    # P0 防回归：写入前核验站点 ./ 本地依赖真实存在。分类产物（short/adult）死引用站点剔除；
    # vod 仅审计记录不剔除。剔除明细写入 status.json 的 local_ref_audit。
    local_ref_audit: dict = {}
    _vod_drops = [{"key": s.get("key"), "name": s.get("name"), "missing": _missing_local_refs(s, repo_dir)}
                  for s in (vod.get("sites") or []) if _missing_local_refs(s, repo_dir)]
    if _vod_drops:
        local_ref_audit["vod.json(仅记录)"] = _vod_drops
        print(f"    [local-ref] vod.json: 审计发现 {len(_vod_drops)} 个死引用站点（仅记录不剔除）", flush=True)
    short_sites = filter_local_ref_sites(short_sites, repo_dir, "short.json", local_ref_audit)
    adult_sites = filter_local_ref_sites(adult_sites, repo_dir, "adult.json", local_ref_audit)
    short_doc = {k: v for k, v in vod.items() if k not in ("lives", "sites")}
    short_doc["sites"] = short_sites
    if not short_doc.get("spider"):
        short_doc.pop("spider", None)
    adult_doc = {k: v for k, v in vod.items() if k not in ("lives", "sites")}
    adult_doc["lives"] = adult_lives
    # 按上游来源归类；同源块内按「取到内容耗时」升序（用户 2026-09-23 要求：有内容的
    # 加载速度快的排前面），没实测到的沉到同源末尾，再按 name 稳定收尾
    adult_sites_sorted = sorted(
        [s for s in adult_sites if isinstance(s, dict)],
        key=lambda x: ((x.get("_origin") or "~"),
                       check_latency.get(x.get("key"), 10 ** 9),
                       (x.get("name") or "")),
    )
    adult_doc["sites"] = adult_sites_sorted
    if not adult_doc.get("spider"):
        adult_doc.pop("spider", None)
    with open("short.json", "w", encoding="utf-8") as f:
        json.dump(short_doc, f, ensure_ascii=False, indent=1)
    # 所有者 2026-09-22 指令：adult.json 每天产出并随 daily 提交更新到仓库；
    # 「只是不声明」：不进 Release 附件白名单 / Pages / 导航页，也不在 README 与日报声明。
    with open("adult.json", "w", encoding="utf-8") as f:
        json.dump(adult_doc, f, ensure_ascii=False, indent=1)
    # 按上游仓库归类的拆分（供 status.json 报告）
    from collections import Counter as _C
    adult_origin_breakdown = _C()
    for s in adult_sites_sorted:
        adult_origin_breakdown[s.get("_origin") or "~(无origin)"] += 1
    adult_out = f"adult.json（{len(adult_sites)} sites + {len(adult_lives)} lives + {len(parses)} parses）"
    print(f"[5/6] 产出：tvbox.json / vod.json（{len(vod.get('sites', []))} sites + {len(vod.get('parses', []))} parses）"
          f" / short.json（{len(short_sites)} sites + {len(parses)} parses）"
          f" / {adult_out}"
          f" / live.json（{len(live['lives'])} 条直播源 / 其中聚合 1 条 + 第三方精选）/ list.json", flush=True)

    with open("list.json", "w", encoding="utf-8") as f:
        json.dump(interfaces, f, ensure_ascii=False, indent=1)

    checks_doc = write_checks(checks, generated_at)
    update_readme_availability(checks)

    # ---- 快照合并产物 + 保留期清理 ----
    merged_dir = os.path.join(SNAPSHOT_DIR, now.strftime("%Y-%m-%d"))
    os.makedirs(merged_dir, exist_ok=True)
    with open(os.path.join(merged_dir, f"tvbox_merged__{now.strftime('%H%M%S')}.json"), "wb") as f:
        f.write(open("tvbox.json", "rb").read())
    pruned = snapshot_prune(SNAPSHOT_RETENTION_DAYS)
    if pruned:
        print(f"    快照清理：移除 {', '.join(pruned)}（保留最近 {SNAPSHOT_RETENTION_DAYS} 天）", flush=True)

    # ---- status.json（增强：上游健康度 + 产物指纹） ----
    products = {}
    for p in ("tvbox.json", "vod.json", "live.json", "short.json", "adult.json",
              "list.json", "status.json", CHECKS_FILE,
              os.path.join(LIVES_DIR, "live.txt"), os.path.join(LIVES_DIR, "live_cctv.txt"),
              os.path.join(LIVES_DIR, "live_weishi.txt"), os.path.join(LIVES_DIR, "live_gangtai.txt"),
              os.path.join(LIVES_DIR, "live_other.txt"),
              os.path.join(STORES_DIR, "duocang.json"), os.path.join(STORES_DIR, "cms.json"),
              os.path.join(STORES_DIR, "app.json"), os.path.join(STORES_DIR, "pan.json"),
              os.path.join(STORES_DIR, "csp.json"), os.path.join(STORES_DIR, "pan_ck.json")):
        if os.path.exists(p):
            b = open(p, "rb").read()
            products[p] = {"bytes": len(b), "sha256": sha12(b)}

    status = {
        "generated_at": generated_at,
        "summary": {
            "interfaces_total": len(interfaces),
            "interfaces_usable": len(usable_config),
            "interfaces_full": sum(1 for r in usable_config if r["grade"] == "完全可用"),
            "interfaces_partial": sum(1 for r in usable_config if r["grade"] == "部分可用"),
            "interfaces_dead": sum(1 for r in interfaces if r["kind"] == "tvbox" and r["grade"] == "不可用"),
            "sites_total": len(sites),
            "sites_kept": len(kept_sites),
            "sites_short": len(short_sites),
            "sites_adult": len(adult_sites),
            "sites_tested": len(to_test),
            "sites_tested_pass": tested_pass,
            "sites_removed": len(removed),
            "sites_untested": len(sites) - len(to_test),
            "sites_secondary_dedup": len(dup_drops),
            "mirrors_skipped": mirror_count,
            "lives": len(lives),
            "parses": len(parses),
            "deps_total": dep_stats["total"],
            "deps_collected": dep_stats["collected"],
            "deps_rewritten": dep_stats["rewritten"],
            "deps_localized_candidates": loc_stats["candidates"],
            "deps_localized_ok": loc_stats["localized"],
            "deps_localized_rewritten": loc_stats["rewritten"],
            "deps_localized_kept": loc_stats["kept"],
            "deps_api_endpoints_untouched": loc_stats["api_endpoints_untouched"],
        },
        "upstreams_health": {
            "note": "checks.json 的摘要镜像；disabled=连续不达标自动停用，blacklisted=手动黑名单",
            "threshold": {"fail_limit": FAIL_LIMIT,
                          "min_bytes_tvbox": MIN_BYTES_TVBOX, "min_bytes_m3u": MIN_BYTES_M3U},
            **checks_doc["summary"],
            "disabled_now": disabled_now_list,
            "snapshot_files": len(snapshot_paths),
            "snapshot_pruned": pruned,
        },
        "spider": {
            "note": "O7b 全局 spider 来源与指纹（清单最前可用上游，依赖本地化后指向 deps/）",
            "origin": (spider_origin_info or ("", ""))[0],
            "value": tvbox.get("spider", "") if isinstance(tvbox.get("spider"), str) else "",
        },
        "site_verdicts": {
            "note": f"O3 站点验活历史记忆；连续 {SITE_FAIL_LIMIT} 轮失败剔除，通过自动复位回捞",
            "tracked": len(site_state),
            "removed": sum(1 for v in site_state.values() if isinstance(v, dict) and v.get("removed")),
        },
        "site_speed": {
            "note": "check_ms = 取到有效配置内容的完整耗时（DNS+建连+正文读取），已并入 sites_probe.json 供 rank_sites 排序；adult.json 同源块内也按此升序",
            "measured": len(check_latency),
            "p50_ms": (sorted(check_latency.values())[len(check_latency) // 2]
                       if check_latency else None),
            "probe_file": PROBE_FILE,
        },
        "runtime": {
            "gh_mirrors": GH_MIRRORS,
            "probe_interval_days": PROBE_INTERVAL_DAYS,
            "site_fail_limit": SITE_FAIL_LIMIT,
            "category_overrides": len(category_overrides),
            "secondary_dedup_dropped": dup_drops[:50],
        },
        "adult_clean": {
            "note": "2026-09-23 adult.json 生成逻辑优化：多信号分类 + 解析池清洗 + 上游归类",
            "parses_clean_stats": parse_stats,
            "origin_votes_strong_signal": origin_votes,
            "adult_breakdown_by_origin": dict(adult_origin_breakdown),
        },
        "lives_by_category": live_stats,
        "stores": stores_summary,
        "local_ref_audit": {
            "note": "写入前核验站点 ./ 本地依赖；short/adult 死引用站点已剔除，vod 仅记录",
            "dropped": local_ref_audit,
        },
        "products": {"note": "产物 sha256 指纹（前 12 位）与字节数", "items": products},
        "interfaces": interfaces,
        "removed_sites": removed,
        "top_interfaces": sorted(
            ({"name": r["name"], "sites": r["sites"], "http_ms": r["http_ms"], "grade": r["grade"]}
             for r in usable_config), key=lambda x: (-x["sites"], x["http_ms"]),
        )[:15],
    }
    with open("status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)

    print(f"[6/6] 输出完成：tvbox.json / vod.json / live.json / short.json / adult.json / list.json / status.json / checks.json / lives/* / stores/* @ {generated_at}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
