"""tencent adapter 测试：分页循环走 fixture，字段映射完整。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_market.adapters.tencent import TencentAdapter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "tencent_jobs_p1.json"


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeFetcher:
    """模拟 Fetcher：把 fixture 当第 1 页，第 2 页起返回空 Posts 让循环停住。"""

    def __init__(self, page1: dict[str, Any]) -> None:
        self._page1 = page1
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, str] | None = None, **_: Any) -> FakeResponse:
        self.calls.append({"url": url, "params": params or {}})
        idx = int((params or {}).get("pageIndex", "1"))
        if idx == 1:
            return FakeResponse(self._page1)
        return FakeResponse({"Code": 200, "Data": {"Count": 5, "Posts": []}})


@pytest.fixture
def fixture_payload() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_list_jobs_paginates_and_yields_raw(fixture_payload: dict[str, Any]) -> None:
    adapter = TencentAdapter()
    fetcher = FakeFetcher(fixture_payload)

    # fixture 里 Count=1234 但只放了 5 条。让分页循环以 totalCount 判停：
    # 把 Count 改成 5 模拟一页就完
    fixture_payload["Data"]["Count"] = 5
    raws = list(adapter.list_jobs(fetcher))  # type: ignore[arg-type]

    assert len(raws) == 5
    assert raws[0].source_url.startswith("https://careers.tencent.com/jobdesc.html")
    assert raws[0].payload["RecruitPostName"].startswith("后端")

    # 校招过滤：attrId=2
    assert all(c["params"]["attrId"] == "2" for c in fetcher.calls)


def test_normalize_maps_all_fields(fixture_payload: dict[str, Any]) -> None:
    adapter = TencentAdapter()
    raw = adapter.normalize.__wrapped__ if hasattr(adapter.normalize, "__wrapped__") else adapter.normalize
    post = fixture_payload["Data"]["Posts"][0]

    from job_market.adapters.base import RawJob
    n = adapter.normalize(RawJob(source_url=post["PostURL"], payload=post))

    assert n.job_id == "tencent:1700000000000000001"
    assert n.company == "tencent"
    assert n.title == "后端开发工程师（Java方向）"
    assert "腾讯云" in n.description or "Java" in n.description
    assert n.location == ["深圳"]
    assert n.posted_at == "2026-06-10"
    assert n.department == "TEG"
    assert n.job_type == "校招"
    assert n.extra["product_name"] == "腾讯云"


def test_normalize_missing_post_id_raises(fixture_payload: dict[str, Any]) -> None:
    adapter = TencentAdapter()
    from job_market.adapters.base import RawJob

    with pytest.raises(ValueError, match="PostId"):
        adapter.normalize(RawJob(source_url="x", payload={"RecruitPostName": "x"}))


def test_split_locations_handles_separators() -> None:
    from job_market.adapters._common import split_locations

    assert split_locations("深圳") == ["深圳"]
    assert split_locations("深圳、北京") == ["深圳", "北京"]
    assert split_locations("深圳/上海;广州") == ["深圳", "上海", "广州"]
    assert split_locations(None) == []
    assert split_locations("") == []


def test_parse_date_handles_chinese_format() -> None:
    from job_market.adapters._common import parse_date

    assert parse_date("2026年06月10日") == "2026-06-10"
    assert parse_date("2026-06-10") == "2026-06-10"
    assert parse_date(None) is None
    assert parse_date("乱码") is None


def test_invalid_posts_are_skipped(fixture_payload: dict[str, Any]) -> None:
    adapter = TencentAdapter()
    # 把第一条标记为 IsValid=False
    fixture_payload["Data"]["Posts"][0]["IsValid"] = False
    fixture_payload["Data"]["Count"] = 5
    fetcher = FakeFetcher(fixture_payload)

    raws = list(adapter.list_jobs(fetcher))  # type: ignore[arg-type]
    assert len(raws) == 4
    assert all(r.payload.get("IsValid", True) for r in raws)
