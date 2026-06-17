"""jd adapter 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_market.adapters.base import RawJob
from job_market.adapters.jd import JDAdapter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "jd_jobs_p1.json"


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeFetcher:
    def __init__(self, page1: dict[str, Any]) -> None:
        self._page1 = page1
        self.posts: list[dict[str, Any]] = []

    def get(self, url: str, **_: Any) -> FakeResponse:
        return FakeResponse({})

    def post(self, url: str, data: dict[str, Any] | None = None, **_: Any) -> FakeResponse:
        self.posts.append(data or {})
        if (data or {}).get("pageNo") == "1":
            return FakeResponse(self._page1)
        return FakeResponse({"resultData": {"totalCount": 5, "resultList": []}})


@pytest.fixture
def page1() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_lists_with_jobtype_2(page1: dict[str, Any]) -> None:
    page1["resultData"]["totalCount"] = 5
    adapter = JDAdapter()
    fetcher = FakeFetcher(page1)
    raws = list(adapter.list_jobs(fetcher))  # type: ignore[arg-type]
    assert len(raws) == 5
    assert all(p["jobType"] == "2" for p in fetcher.posts)


def test_normalize_basic(page1: dict[str, Any]) -> None:
    adapter = JDAdapter()
    n = adapter.normalize(RawJob(source_url="x", payload=page1["resultData"]["resultList"][1]))
    assert n.job_id == "jd:JD-9002"
    assert n.title == "算法工程师-广告"
    assert n.location == ["北京"]
    assert n.posted_at == "2026-06-07"
    assert n.education == "硕士"
