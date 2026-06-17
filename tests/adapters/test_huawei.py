"""huawei adapter 测试。

注意：Playwright 兜底路径不在单测覆盖（依赖浏览器 + 真站点），
仅测 JSON 路径 + normalize。Playwright 路径靠 12.3 联网验收。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_market.adapters.base import RawJob
from job_market.adapters.huawei import HuaweiAdapter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "huawei_jobs_p1.json"


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
        return FakeResponse({"data": {"totalRecord": 5, "list": []}})


@pytest.fixture
def page1() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_json_path_yields_5_jobs(page1: dict[str, Any]) -> None:
    page1["data"]["totalRecord"] = 5
    adapter = HuaweiAdapter()
    fetcher = FakeFetcher(page1)
    raws = list(adapter.list_jobs(fetcher))  # type: ignore[arg-type]
    assert len(raws) == 5
    assert all(p["recruitType"] == "校园招聘" for p in fetcher.posts)


def test_normalize_basic(page1: dict[str, Any]) -> None:
    adapter = HuaweiAdapter()
    n = adapter.normalize(RawJob(source_url="x", payload=page1["data"]["list"][1]))
    assert n.job_id == "huawei:HW-4002"
    assert n.title == "AI算法工程师"
    assert n.location == ["北京"]
    assert n.posted_at == "2026-06-07"
    assert n.education == "硕士"
    assert n.department == "AI"


def test_json_404_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON 返回非 200 时 list_jobs 静默返回（Playwright 路径未装时也不抛）。"""
    adapter = HuaweiAdapter()

    class FailFetcher:
        def get(self, url: str, **_: Any) -> FakeResponse:
            return FakeResponse({})

        def post(self, url: str, json: dict[str, Any] | None = None, **_: Any) -> FakeResponse:
            return FakeResponse({}, status_code=404)

    raws = list(adapter.list_jobs(FailFetcher()))  # type: ignore[arg-type]
    assert raws == []  # 没有 playwright 时降级为空集
