#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台路径安全工具（全仓库唯一事实源）。

背景
----
依赖落库路径从 URL path 段拼接，镜像前缀 URL（``https://<镜像>/https://raw...``）
的 path 含 ``https:`` 带冒号目录名，在 Windows 上 ``WinError 123``。Linux 可创建但
提交后任何 Windows 用户 clone 整体失败。因此全平台统一 sanitize，保证 CI 产物路径
在所有平台可创建。

此前 ``fetch_merge._sanitize_seg``、``raw_store._safe_seg/safe_rel`` 各自实现，
语义略有差异（raw_store 未处理 Windows 保留名）。本模块收敛为单一实现，所有文件
落库统一走 ``safe_join`` / ``safe_segment``。

用法
----
    from pathutil import safe_segment, safe_join, is_windows_safe, check_path_length

    rel = safe_join("deps", origin, url_path_segment)
    ok, why = is_windows_safe(rel)
    truncated = check_path_length(rel, max_len=240)  # 超限时用 md5 截断末段
"""
import hashlib
import os
import re

# Windows 非法字符（<>:"|?* 及控制字符）
_WIN_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')

# Windows 保留设备名（不含扩展名前缀时整体保留名也非法，如 CON.txt 合法但 CON 非法）
_WIN_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})

# 路径长度上限（留余量，Windows MAX_PATH=260，取 240）
MAX_PATH = 240


def safe_segment(seg: str) -> str:
    """清洗单个路径段：替换 Windows 非法字符、去末尾点空格、规避保留名。

    全平台统一以 Windows 非法字符集为兜底标准——Linux 能创建的路径若含这些字符，
    提交后 Windows 用户 clone 会整体失败，故必须在源头清洗。
    """
    if seg is None:
        return "_"
    s = _WIN_BAD_CHARS.sub("_", seg)
    s = s.rstrip(" .")  # Windows 禁止以点或空格结尾
    if not s:
        return "_"
    # 保留名检测：取第一个 . 之前的部分（CON.txt 合法，CON 非法）
    if s.split(".", 1)[0].upper() in _WIN_RESERVED:
        s = "_" + s
    return s


def safe_join(*parts: str) -> str:
    """拼接路径并逐段清洗，保留 ``/`` 分隔符（仓库内统一正斜杠）。

    空段、``.``、``..`` 被过滤（``..`` 向上跳转在落库场景下无意义且有逃逸风险）。
    """
    segs = []
    for p in parts:
        if not p:
            continue
        for s in p.replace("\\", "/").split("/"):
            if s in ("", ".", ".."):
                continue
            segs.append(safe_segment(s))
    return "/".join(segs) if segs else "_"


def is_windows_safe(rel_path: str) -> tuple:
    """检查相对路径是否在 Windows 上可创建。

    返回 (bool, reason)：True 表示安全；False 时 reason 说明问题。
    用于 CI Windows 兼容性检查 job 的断言。
    """
    if not rel_path:
        return False, "empty path"
    parts = rel_path.replace("\\", "/").split("/")
    for i, seg in enumerate(parts):
        if not seg:
            return False, f"segment[{i}] is empty"
        if _WIN_BAD_CHARS.search(seg):
            return False, f"segment[{i}] '{seg}' contains Windows illegal chars"
        if seg != seg.rstrip(" ."):
            return False, f"segment[{i}] '{seg}' ends with dot/space"
        if seg.split(".", 1)[0].upper() in _WIN_RESERVED:
            return False, f"segment[{i}] '{seg}' is Windows reserved name"
    if len(rel_path) > MAX_PATH:
        return False, f"path length {len(rel_path)} > {MAX_PATH}"
    return True, ""


def check_path_length(rel_path: str, max_len: int = MAX_PATH) -> str:
    """路径长度检查：超过 max_len 时用 md5 截断最后一个路径段。

    保留目录结构不变，仅缩短文件名段。截断后记录到日志（调用方负责打印）。
    返回处理后的路径。
    """
    if len(rel_path) <= max_len:
        return rel_path
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) < 2:
        # 单段超长：直接 md5 截断
        h = hashlib.md5(rel_path.encode()).hexdigest()[:16]
        ext = os.path.splitext(rel_path)[1]
        return h + ext
    # 截断最后一段（文件名），保留扩展名
    last = parts[-1]
    base, ext = os.path.splitext(last)
    h = hashlib.md5(last.encode()).hexdigest()[:16]
    parts[-1] = h + ext
    result = "/".join(parts)
    # 若目录部分本身就超长，递归截断倒数第二段
    if len(result) > max_len and len(parts) >= 2:
        dir_part = "/".join(parts[:-1])
        truncated_dir = check_path_length(dir_part, max_len - len(parts[-1]) - 1)
        result = truncated_dir + "/" + parts[-1]
    return result


def sanitize_for_filename(name: str, max_len: int = 80) -> str:
    """将任意字符串转为安全文件名（用于 remote 依赖等无路径结构的场景）。"""
    s = safe_segment(name)
    if len(s) > max_len:
        h = hashlib.md5(s.encode()).hexdigest()[:12]
        ext = os.path.splitext(s)[1]
        s = h + ext
    return s


def case_collisions(paths) -> list:
    """列出仅大小写不同的同目录路径组（Windows/macOS 上会互相覆盖）。

    返回 [[p1, p2, ...], ...]，组内按字节序排序；无冲突时返回空列表。
    """
    groups = {}
    for p in set(paths):
        groups.setdefault(p.lower(), []).append(p)
    return [sorted(v) for v in groups.values() if len(v) > 1]


def demote_rel(rel: str, identity: str = None) -> str:
    """给大小写互撞的路径生成唯一名：末段文件名追加 ``~<md5(标识)[:6]>``。

    标识默认取整条路径，因此同一个 loser 在任何机器、任何一轮都得到同一个新名字；
    调用方可显式传入更稳定的身份（如账本 key）来固定跨轮命名。
    """
    d, f = rel.rsplit("/", 1) if "/" in rel else ("", rel)
    base, ext = os.path.splitext(f)
    tag = hashlib.md5((identity or rel).encode()).hexdigest()[:6]
    return f"{d}/{base}~{tag}{ext}" if d else f"{base}~{tag}{ext}"


def resolve_case_collisions(paths) -> dict:
    """为大小写互撞的路径分配唯一名，返回 {原路径: 消解后路径}。

    落库路径由 URL 段原样派生，上游同名文件常只差大小写（``IPTV.m3u`` /
    ``iptv.m3u``）。Linux CI 上两者共存无碍，Windows 上后写入者覆盖前者——本地
    拿到的内容与 git 记录、与账本里各自登记的 sha256 全部错位，且检出后
    ``git status`` 会永久显示该文件被修改，驱动 daily 反复重写同一份大文件。

    消解规则必须与平台无关且可复现，否则本地与 CI 会各自造出不同文件名，
    账本再也对不上：组内按字节序取第一个为胜者保留原名，其余交给
    :func:`demote_rel` 降级，冲突时再追加序号。
    """
    out = {}
    for group in case_collisions(paths):
        claimed = set()
        for i, p in enumerate(group):
            if i == 0:
                out[p] = p
                claimed.add(p.lower())
                continue
            cand = demote_rel(p)
            n = 0
            while cand.lower() in claimed:
                n += 1
                cand = demote_rel(p, identity=f"{p}#{n}")
            out[p] = cand
            claimed.add(cand.lower())
    for p in set(paths) - set(out):
        out[p] = p
    return out
