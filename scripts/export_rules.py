#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_rules.py — 规则库物化（P0 硬标准：词表/规则文件随包内置、离线可重建）。

单一事实源 = live_aggregate.py 代码常量（历轮真机产物补漏沉淀，非人工编造；
成人域名表根域来自 adult 实际产物 5372 频道统计）。本脚本把常量导出为
rules/*.json，供：本地包内置、跨语言消费、人工审阅与 diff 追溯。

产出：
  rules/adult_keywords.json       频道名词表（PORN_KW + 番号/括号/纯数字判定说明）
  rules/adult_host_blacklist.json 域名黑名单（后缀域 + 子串 token）
  rules/adult_source_patterns.json 上游整源标记正则（ADULT_SOURCE_RE.pattern）
  rules/channel_norm.json         频道名标准化/分类规则（组序、港台/直播/轮播词表、
                                  省级/县级归属表、别名表）
用法：python scripts/export_rules.py（幂等，内容不变则 sha256 不变）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import live_aggregate as la  # noqa: E402


def main():
    os.makedirs(os.path.join(ROOT, "rules"), exist_ok=True)

    docs = {
        "adult_keywords.json": {
            "_说明": "频道级 adult 词表（P0-2 第二重判定）。事实源=live_aggregate.PORN_KW，"
                     "历轮真机产物补漏沉淀；is_adult()=词表命中 ∨ 纯数字短台位 ∨ "
                     "【水果派/免费/愛欲】括号标 ∨ AV 番号日期码。",
            "porn_keywords": list(la.PORN_KW),
            "pure_number_station": r"^\d{1,3}$",
            "bracket_tag": la.ADULT_BRACKET_TAG.pattern,
            "date_code": la.ADULT_DATE_CODE.pattern,
        },
        "adult_host_blacklist.json": {
            "_说明": "域名级 adult 黑名单（P0-2 第三重判定）。后缀域根域取自仓库 adult "
                     "实际产物（adult.json/adult_live.json/adult_live_channels.json，"
                     "5372 频道）播放与接口域名频次统计；子串 token 匹配任意后缀变体；"
                     "裸 IP 不入表。is_adult_url()=host 后缀命中 ∨ token 子串命中。",
            "suffix_domains": list(la.ADULT_HOSTS),
            "host_tokens": list(la.ADULT_HOST_TOKENS),
        },
        "adult_source_patterns.json": {
            "_说明": "上游整源级 adult 标记（P0-2 第一重判定）。sid/url/源名任一命中即整源剔除。",
            "pattern": la.ADULT_SOURCE_RE.pattern,
        },
        "channel_norm.json": {
            "_说明": "频道名标准化与六分类规则（P0-1）。判定序=来源源标记(chunwan→春晚组) "
                     "> adult 词表/域名 > 央视(CCTV/CGTN) > 港台 > 卫视 > 直播 > 轮播 "
                     "> 电台 > 地方(县级表→省级词表) > 其他。剥离规则：清晰度后缀、"
                     "[bd/hd]来源标签、括号标注、繁简归一、别名表、台/频道尾缀。",
            "group_order": list(la.BIG_ORDER),
            "hktw_keywords": list(la.HKTW_KW),
            "zhibo_keywords": list(la.ZHIBO_KW),
            "lunbo_keywords": list(la.LUNBO_KW),
            "province_table": {p: list(kws) for p, kws in la.PROVINCE_TABLE},
            "county_to_province": dict(la.COUNTY_PROV),
            "alias_map": dict(la.ALIAS_MAP),
            "hk_block_keywords": list(la.HK_BLOCK_KW),
            "hk_order_keywords": list(la.HK_ORDER_KW),
            "tw_keywords": list(la.TW_KW),
        },
    }
    for fn, doc in docs.items():
        p = os.path.join(ROOT, "rules", fn)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=False)
            f.write("\n")
        print("[rules] %s (%d bytes)" % (p, os.path.getsize(p)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
