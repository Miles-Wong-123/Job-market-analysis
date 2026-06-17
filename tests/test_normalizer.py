"""normalizer 测试：happy path、normalize 抛错、缺字段、非技术岗丢弃。"""

from __future__ import annotations

import json

from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.normalizer import normalize_record


CATEGORY_RULES = [
    ("algorithm", ["算法", "推荐"]),
    ("backend", ["后端", "Java", "服务端"]),
    ("frontend", ["前端", "React"]),
]
TECH_KEYWORDS = ["python", "java", "go", "react", "kubernetes"]


class _FakeAdapter(CampusAdapter):
    company = "fake"

    def __init__(self, behavior: str = "ok") -> None:
        super().__init__()
        self.behavior = behavior

    def list_jobs(self, fetcher):  # type: ignore[override]
        return iter([])

    def normalize(self, raw: RawJob) -> NormalizedJob:
        if self.behavior == "raise":
            raise ValueError("schema 变了")
        if self.behavior == "missing_title":
            return NormalizedJob(
                job_id="fake:1",
                company="fake",
                title="",
                description="",
                requirements="",
                location=[],
                education=None,
                job_type="校招",
                department=None,
                posted_at=None,
                source_url=raw.source_url,
                raw_payload=raw.payload,
            )
        if self.behavior == "non_tech":
            return NormalizedJob(
                job_id="fake:2",
                company="fake",
                title="产品经理-社交方向",
                description="负责产品规划",
                requirements="",
                location=["北京"],
                education="本科",
                job_type="校招",
                department=None,
                posted_at=None,
                source_url=raw.source_url,
                raw_payload=raw.payload,
            )
        return NormalizedJob(
            job_id="fake:3",
            company="fake",
            title="后端开发工程师",
            description="Java 服务端，使用 Kubernetes",
            requirements="熟悉 Python 加分",
            location=["北京", "上海"],
            education="本科",
            job_type="校招",
            department="基础架构",
            posted_at="2026-06-01",
            source_url=raw.source_url,
            raw_payload=raw.payload,
        )


def _raw() -> RawJob:
    return RawJob(source_url="https://example.com/job/1", payload={"id": 1})


def test_happy_path() -> None:
    res = normalize_record(_FakeAdapter("ok"), _raw(), category_rules=CATEGORY_RULES, tech_keywords=TECH_KEYWORDS)
    assert res.row is not None
    assert res.parsing_error is False
    assert res.dropped_non_tech is False
    assert res.row["job_id"] == "fake:3"
    assert res.row["category"] == "backend"
    # JSON 列：解码后才能比较
    assert json.loads(res.row["tech_keywords"]) == ["python", "java", "kubernetes"]
    assert json.loads(res.row["location"]) == ["北京", "上海"]
    assert res.row["parsing_error"] == 0


def test_normalize_raises_flags_parsing_error_and_keeps_raw() -> None:
    res = normalize_record(_FakeAdapter("raise"), _raw(), category_rules=CATEGORY_RULES, tech_keywords=TECH_KEYWORDS)
    assert res.row is not None
    assert res.parsing_error is True
    assert res.row["parsing_error"] == 1
    assert json.loads(res.row["raw_payload"]) == {"id": 1}
    # 主键有兜底
    assert res.row["job_id"].startswith("fake:fallback:")


def test_missing_title_flags_parsing_error() -> None:
    res = normalize_record(_FakeAdapter("missing_title"), _raw(), category_rules=CATEGORY_RULES, tech_keywords=TECH_KEYWORDS)
    assert res.row is not None
    assert res.parsing_error is True
    assert res.row["parsing_error"] == 1


def test_non_tech_role_dropped() -> None:
    res = normalize_record(_FakeAdapter("non_tech"), _raw(), category_rules=CATEGORY_RULES, tech_keywords=TECH_KEYWORDS)
    assert res.row is None
    assert res.dropped_non_tech is True
    assert res.parsing_error is False
