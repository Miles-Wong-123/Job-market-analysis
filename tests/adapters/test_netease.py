"""netease adapter 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_market.adapters.base import RawJob
from job_market.adapters.netease import NetEaseAdapter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "netease_jobs_p1.json"


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeFetcher:
    def __init__(self, page1: dict[str, Any]) -> None:
        self._page1 = page1
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, str] | None = None, **_: Any) -> FakeResponse:
        self.calls.append({"url": url, "params": params or {}})
        if (params or {}).get("currentPage") == "1":
            return FakeResponse(self._page1)
        return FakeResponse({"data": {"totalCount": 5, "list": []}})


@pytest.fixture
def page1() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_lists_paginated(page1: dict[str, Any]) -> None:
    page1["data"]["totalCount"] = 5
    adapter = NetEaseAdapter()
    fetcher = FakeFetcher(page1)
    raws = list(adapter.list_jobs(fetcher))  # type: ignore[arg-type]
    assert len(raws) == 5


def test_normalize_basic(page1: dict[str, Any]) -> None:
    adapter = NetEaseAdapter()
    n = adapter.normalize(RawJob(source_url="x", payload=page1["data"]["list"][0]))
    assert n.job_id == "netease:NE-1001"
    assert n.title == "服务端开发工程师-游戏"
    assert n.location == ["杭州"]
    assert n.posted_at == "2026-06-08"
    assert n.department == "网易雷火"
