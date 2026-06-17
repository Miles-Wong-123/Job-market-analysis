"""归一化层：把 adapter 输出的 NormalizedJob 转成可直接入库的 dict。

职责：
1. 调用 adapter 的 normalize；捕获异常 → 标 parsing_error，保留 raw_payload
2. 检查必填字段 (job_id, title)，缺失 → 标 parsing_error
3. 是否技术岗判断；非技术岗返回 None（pipeline 据此丢弃，不入库）
4. 类别分配 + 技术词抽取 + 完整字段组装
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.classifier import (
    CategoryRules,
    assign_category,
    extract_tech_keywords,
    is_tech_role,
)

log = logging.getLogger(__name__)


@dataclass(slots=True)
class NormalizeResult:
    """单条记录归一化结果。`row=None` 表示已被判为非技术岗、应丢弃。"""

    row: dict[str, Any] | None
    parsing_error: bool
    dropped_non_tech: bool


def normalize_record(
    adapter: CampusAdapter,
    raw: RawJob,
    *,
    category_rules: CategoryRules,
    tech_keywords: list[str],
    crawled_at: datetime | None = None,
) -> NormalizeResult:
    """把一条原始岗位转成入库 row。

    返回三种状态之一：
    - 正常：row 是 dict，parsing_error=False
    - 解析异常或缺字段：row 是 dict（用 raw 兜底），parsing_error=True
    - 非技术岗：row=None，dropped_non_tech=True
    """
    crawled_at = crawled_at or datetime.now(UTC)
    parsing_error = False
    normalized: NormalizedJob | None = None

    try:
        normalized = adapter.normalize(raw)
    except Exception as exc:  # noqa: BLE001 — 任何异常都不应中断公司批次
        log.warning("[%s] normalize 失败：%s（保留 raw payload）", adapter.company, exc)
        parsing_error = True

    # 字段补全 / 异常兜底
    if normalized is None or not (normalized.job_id or "").strip() or not (normalized.title or "").strip():
        parsing_error = True
        title = (normalized.title if normalized else "") or ""
        description = (normalized.description if normalized else "") or ""
    else:
        title = normalized.title
        description = normalized.description

    # 是否技术岗：基于 title + description 判断；缺字段时保守视为技术岗
    # （让 parsing_error 标记吸引人工审视，而不是悄悄丢弃）
    if not parsing_error and not is_tech_role(title, description):
        return NormalizeResult(row=None, parsing_error=False, dropped_non_tech=True)

    # 组装 row
    if normalized is not None:
        haystack = "\n".join(filter(None, [normalized.title, normalized.description, normalized.requirements]))
        category = assign_category(normalized.title, normalized.description, category_rules) if not parsing_error else "tech_other"
        keywords = extract_tech_keywords(haystack, tech_keywords)
        row = {
            "job_id": normalized.job_id or _fallback_job_id(adapter.company, raw),
            "company": normalized.company or adapter.company,
            "title": normalized.title or "",
            "category": category,
            "subcategory": normalized.subcategory,
            "description": normalized.description or "",
            "requirements": normalized.requirements or "",
            "tech_keywords": json.dumps(keywords, ensure_ascii=False),
            "location": json.dumps(normalized.location or [], ensure_ascii=False),
            "education": normalized.education,
            "job_type": normalized.job_type or "",
            "department": normalized.department,
            "posted_at": normalized.posted_at,
            "crawled_at": crawled_at.isoformat(timespec="seconds"),
            "source_url": normalized.source_url or raw.source_url,
            "raw_payload": json.dumps(raw.payload, ensure_ascii=False),
            "parsing_error": int(parsing_error),
        }
    else:
        # 完全没拿到 NormalizedJob，纯 raw 兜底
        row = {
            "job_id": _fallback_job_id(adapter.company, raw),
            "company": adapter.company,
            "title": "",
            "category": "tech_other",
            "subcategory": None,
            "description": "",
            "requirements": "",
            "tech_keywords": "[]",
            "location": "[]",
            "education": None,
            "job_type": "",
            "department": None,
            "posted_at": None,
            "crawled_at": crawled_at.isoformat(timespec="seconds"),
            "source_url": raw.source_url,
            "raw_payload": json.dumps(raw.payload, ensure_ascii=False),
            "parsing_error": 1,
        }

    return NormalizeResult(row=row, parsing_error=parsing_error, dropped_non_tech=False)


def _fallback_job_id(company: str, raw: RawJob) -> str:
    """没拿到 normalized.job_id 时，用 source_url 哈希做兜底，保证主键稳定。"""
    import hashlib

    h = hashlib.sha1(raw.source_url.encode("utf-8")).hexdigest()[:12]
    return f"{company}:fallback:{h}"
