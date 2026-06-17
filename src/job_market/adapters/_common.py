"""adapter 之间共用的小工具：地点拆分、日期解析、字段安全取值。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


_LOC_SEP = re.compile(r"[、,/，;；\|]")


def split_locations(s: str | list[Any] | None) -> list[str]:
    """把 "深圳、北京" / "深圳/上海" / list 形式的地点字段统一成 list[str]。"""
    if s is None:
        return []
    if isinstance(s, list):
        return [str(x).strip() for x in s if str(x).strip()]
    parts = _LOC_SEP.split(str(s))
    return [x.strip() for x in parts if x.strip()]


_CN_DATE = re.compile(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})")
_TS_FMTS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    "%Y-%m-%d",
)


def parse_date(value: Any) -> str | None:
    """把各种公司返回的日期字段统一成 ``YYYY-MM-DD``。

    支持：
    - "2026年06月10日"
    - "2026-06-10" / "2026/06/10"
    - "2026-06-10 12:30:00"
    - epoch 毫秒（int）
    - 已经是 datetime
    解析不出来返回 ``None``，不抛异常。
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, (int, float)):
        # 毫秒或秒
        ts = float(value)
        if ts > 1e12:  # 毫秒
            ts /= 1000
        try:
            return datetime.fromtimestamp(ts).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    m = _CN_DATE.search(s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    for fmt in _TS_FMTS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def first_nonempty(*values: Any) -> str:
    """从一串候选里取第一个非空字符串；常用于多版本字段名兼容。"""
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""
