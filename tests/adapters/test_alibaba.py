"""alibaba adapter 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_market.adapters.alibaba import AlibabaAdapter
from job_market.adapters.base import RawJob

FIXTURE = Path(__file__).parent.parent / "fixtures" / "alibaba_jobs_p1.json"


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
        if (json or {}).get("pageIndex") == 1:
            return FakeResponse(self._page1)
        return FakeResponse({"content": {"total": 5, "datas": []}})


@pytest.fixture
def page1() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_lists_yields_5_with_campus_filter(page1: dict[str, Any]) -> None:
    page1["content"]["total"] = 5
    adapter = AlibabaAdapter()
    fetcher = FakeFetcher(page1)
    raws = list(adapter.list_jobs(fetcher))  # type: ignore[arg-type]
    assert len(raws) == 5
    assert all(p["channelType"] == "campus" for p in fetcher.posts)


def test_normalize_two_locations(page1: dict[str, Any]) -> None:
    adapter = AlibabaAdapter()
    p = page1["content"]["datas"][1]  # 阿里云算法
    n = adapter.normalize(RawJob(source_url="x", payload=p))
    assert n.job_id == "alibaba:80010002"
    assert n.title == "算法工程师-阿里云"
    assert n.location == ["北京", "杭州"]
    assert n.posted_at == "2026-06-07"
    assert n.education == "硕士"
    assert n.department == "阿里云-通义实验室"
    assert n.extra["category_name"] == "算法工程师"


def test_normalize_missing_id_raises() -> None:
    adapter = AlibabaAdapter()
    with pytest.raises(ValueError, match="id"):
        adapter.normalize(RawJob(source_url="x", payload={"name": "x"}))
