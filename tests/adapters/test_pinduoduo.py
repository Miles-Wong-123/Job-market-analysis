"""pinduoduo adapter 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_market.adapters.base import RawJob
from job_market.adapters.pinduoduo import PinduoduoAdapter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "pinduoduo_jobs_p1.json"


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
        if (json or {}).get("pageNo") == 1:
            return FakeResponse(self._page1)
        return FakeResponse({"data": {"total": 5, "list": []}})


@pytest.fixture
def page1() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_lists_with_campus_filter(page1: dict[str, Any]) -> None:
    page1["data"]["total"] = 5
    adapter = PinduoduoAdapter()
    fetcher = FakeFetcher(page1)
    raws = list(adapter.list_jobs(fetcher))  # type: ignore[arg-type]
    assert len(raws) == 5
    assert all(p["recruitTypeCode"] == "campus" for p in fetcher.posts)


def test_normalize_handles_epoch_ms(page1: dict[str, Any]) -> None:
    adapter = PinduoduoAdapter()
    n = adapter.normalize(RawJob(source_url="x", payload=page1["data"]["list"][1]))
    assert n.job_id == "pinduoduo:PDD-3002"
    assert n.posted_at == "2024-06-07"  # 1717718400000 ms = 2024-06-07
    assert n.education == "硕士"
