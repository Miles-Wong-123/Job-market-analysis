"""腾讯校招 adapter — 公开 GET API。

API：`https://careers.tencent.com/tencentcareer/api/post/Query`
鉴权：无（直 GET 即可）
分页：`pageIndex` 从 1 起，`pageSize` 默认 10
关键过滤：`attrId=2` 表示校园招聘
schema：`{Code, Data: {Count, Posts: [{PostId, RecruitPostName, CountryName,
LocationName, BGName, CategoryName, ProductName, Responsibility,
LastUpdateTime, PostURL, RequireWorkYearsName, IsValid}]}}`

LastUpdateTime 形如 "2026年06月10日"，归一化时转 "2026-06-10"。
"""

from __future__ import annotations

import time
from collections.abc import Iterator

from job_market.adapters._common import parse_date, split_locations
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.fetcher import Fetcher

API = "https://careers.tencent.com/tencentcareer/api/post/Query"
PAGE_SIZE = 10
MAX_PAGES = 200  # 1234 条 * 10/页 = 124 页，留一倍冗余


class TencentAdapter(CampusAdapter):
    company = "tencent"
    rate_limit_qps = 1.0
    robots_probe_url = "https://careers.tencent.com/tencentcareer/api/post/Query"

    def list_jobs(self, fetcher: Fetcher) -> Iterator[RawJob]:
        for page in range(1, MAX_PAGES + 1):
            params = {
                "timestamp": str(int(time.time() * 1000)),
                "attrId": "2",  # 校园招聘
                "pageIndex": str(page),
                "pageSize": str(PAGE_SIZE),
                "language": "zh-cn",
                "area": "cn",
                "keyword": "",
            }
            resp = fetcher.get(API, params=params)
            if resp.status_code != 200:
                return
            data = resp.json().get("Data") or {}
            posts = data.get("Posts") or []
            if not posts:
                return
            for p in posts:
                if not p.get("IsValid", True):
                    continue
                yield RawJob(
                    source_url=p.get("PostURL") or API,
                    payload=p,
                )
            total = data.get("Count", 0)
            if page * PAGE_SIZE >= total:
                return

    def normalize(self, raw: RawJob) -> NormalizedJob:
        p = raw.payload
        post_id = str(p.get("PostId") or p.get("RecruitPostId") or "")
        if not post_id:
            raise ValueError("Tencent payload 缺 PostId")
        return NormalizedJob(
            job_id=f"tencent:{post_id}",
            company="tencent",
            title=str(p.get("RecruitPostName") or "").strip(),
            description=str(p.get("Responsibility") or ""),
            requirements="",
            location=split_locations(p.get("LocationName")),
            education=None,
            job_type="校招",
            department=str(p.get("BGName") or "") or None,
            posted_at=parse_date(p.get("LastUpdateTime")),
            source_url=raw.source_url,
            raw_payload=p,
            extra={
                "category_name": p.get("CategoryName"),
                "product_name": p.get("ProductName"),
                "country_name": p.get("CountryName"),
                "require_work_years": p.get("RequireWorkYearsName"),
            },
        )
