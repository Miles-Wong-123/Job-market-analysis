"""meituan adapter 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_market.adapters.base import RawJob
from job_market.adapters.meituan import MeituanAdapter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "meituan_jobs_p1.json"


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

    def post(self, url: str, json: dict[str, Any] | None = None, **_: Any) -> FakeResponse:
        self.posts.append(json or {})
        if (json or {}).get("pageNum") == 1:
            return FakeResponse(self._page1)
        return FakeResponse({"data": {"totalCount": 5, "list": []}})


@pytest.fixture
def page1() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_lists_with_campus_recruit_type(page1: dict[str, Any]) -> None:
    page1["data"]["totalCount"] = 5
    adapter = MeituanAdapter()
    fetcher = FakeFetcher(page1)
    raws = list(adapter.list_jobs(fetcher))  # type: ignore[arg-type]
    assert len(raws) == 5
    assert all(p["recruitType"] == 2 for p in fetcher.posts)


def test_normalize_two_cities(page1: dict[str, Any]) -> None:
    adapter = MeituanAdapter()
    n = adapter.normalize(RawJob(source_url="x", payload=page1["data"]["list"][1]))
    assert n.job_id == "meituan:MT-7002"
    assert n.location == ["北京", "上海"]
    assert n.posted_at == "2026-06-07"
    assert n.extra["job_family"] == "算法"


def test_normalize_missing_id_raises() -> None:
    adapter = MeituanAdapter()
    with pytest.raises(ValueError):
        adapter.normalize(RawJob(source_url="x", payload={}))
