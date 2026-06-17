"""网易校招 adapter — GET querystring。

API：`https://campus.163.com/app/searchJobList`
分页：currentPage + pageSize
schema：data.list[]: {id, postName, postType, postCity, postDept, postDuty,
       postRequirement, releaseTime}; total at data.totalCount

TODO[live-verify]: 站点页面渲染做了 SPA 改造，API 路径以 2024 公开脚本为准。
"""

from __future__ import annotations

from collections.abc import Iterator

from job_market.adapters._common import parse_date, split_locations
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.fetcher import Fetcher

API = "https://campus.163.com/app/searchJobList"
LISTING = "https://campus.163.com/app/"
PAGE_SIZE = 20
MAX_PAGES = 100


class NetEaseAdapter(CampusAdapter):
    company = "netease"
    rate_limit_qps = 1.0
    robots_probe_url = LISTING

    def list_jobs(self, fetcher: Fetcher) -> Iterator[RawJob]:
        for page in range(1, MAX_PAGES + 1):
            params = {
                "currentPage": str(page),
                "pageSize": str(PAGE_SIZE),
                "keyword": "",
                "postType": "",
                "postCity": "",
                "postDept": "",
            }
            resp = fetcher.get(API, params=params)
            if resp.status_code != 200:
                return
            data = resp.json().get("data") or {}
            rows = data.get("list") or []
            if not rows:
                return
            for r in rows:
                jid = r.get("id")
                yield RawJob(
                    source_url=f"https://campus.163.com/app/jobDetail.do?id={jid}"
                    if jid
                    else LISTING,
                    payload=r,
                )
            total = data.get("totalCount", 0)
            if page * PAGE_SIZE >= total:
                return

    def normalize(self, raw: RawJob) -> NormalizedJob:
        p = raw.payload
        jid = str(p.get("id") or "")
        if not jid:
            raise ValueError("NetEase payload 缺 id")
        return NormalizedJob(
            job_id=f"netease:{jid}",
            company="netease",
            title=str(p.get("postName") or "").strip(),
            description=str(p.get("postDuty") or ""),
            requirements=str(p.get("postRequirement") or ""),
            location=split_locations(p.get("postCity")),
            education=p.get("eduDegree") or None,
            job_type="校招",
            department=str(p.get("postDept") or "") or None,
            posted_at=parse_date(p.get("releaseTime")),
            source_url=raw.source_url,
            raw_payload=p,
            extra={"post_type": p.get("postType")},
        )
