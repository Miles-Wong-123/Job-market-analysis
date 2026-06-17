"""bytedance adapter 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_market.adapters.base import RawJob
from job_market.adapters.bytedance import ByteDanceAdapter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "bytedance_jobs_p1.json"


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
        self.gets: list[str] = []

    def get(self, url: str, **_: Any) -> FakeResponse:
        self.gets.append(url)
        return FakeResponse({})

    def post(self, url: str, json: dict[str, Any] | None = None, **_: Any) -> FakeResponse:
        self.posts.append(json or {})
        offset = (json or {}).get("offset", 0)
        if offset == 0:
            return FakeResponse(self._page1)
        return FakeResponse({"code": 0, "data": {"count": 5, "job_post_list": []}})


@pytest.fixture
def page1() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_lists_yields_5_raw_jobs(page1: dict[str, Any]) -> None:
    page1["data"]["count"] = 5  # 一页就完
    adapter = ByteDanceAdapter()
    fetcher = FakeFetcher(page1)
    raws = list(adapter.list_jobs(fetcher))  # type: ignore[arg-type]
    assert len(raws) == 5
    assert raws[0].source_url.endswith("/A30001/detail")
    # 确认带了 portal_type=4（校招）
    assert all(p["portal_type"] == 4 for p in fetcher.posts)
    # 确认先 GET 了 listing 拿 cookie
    assert any("/campus/position" in u for u in fetcher.gets)


def test_normalize_field_mapping(page1: dict[str, Any]) -> None:
    adapter = ByteDanceAdapter()
    p = page1["data"]["job_post_list"][1]  # 推荐算法
    n = adapter.normalize(RawJob(source_url="x", payload=p))
    assert n.job_id == "bytedance:7321000000000000002"
    assert n.title == "推荐算法工程师 - 今日头条"
    assert n.location == ["北京", "上海"]
    assert n.posted_at == "2024-06-09"  # 1717891200000 ms
    assert n.department == "Data-Recommendation"
    assert n.extra["category_name"] == "算法"
    assert "PyTorch" in n.requirements


def test_normalize_missing_id_raises() -> None:
    adapter = ByteDanceAdapter()
    with pytest.raises(ValueError, match="id"):
        adapter.normalize(RawJob(source_url="x", payload={"title": "x"}))


def test_pagination_stops_at_count(page1: dict[str, Any]) -> None:
    page1["data"]["count"] = 5
    adapter = ByteDanceAdapter()
    fetcher = FakeFetcher(page1)
    list(adapter.list_jobs(fetcher))  # type: ignore[arg-type]
    # 5 条 / 10 页面 → 一页就停
    assert len(fetcher.posts) == 1
