"""拼多多校招 adapter — POST JSON（careers.pddglobalhr.com）。

API：`https://careers.pddglobalhr.com/api/job/list`
分页：pageNo + pageSize
关键过滤：recruitTypeCode=campus
schema：data.list[]: {jobId, jobName, jobCategoryName, cityName, recruitTypeName,
       jobDescription, jobRequirement, updateTime}; total at data.total

TODO[live-verify]: 拼多多反爬较强（research agent 直接 GET 拿到 403），
首次请求可能要先 GET listing；上线时如果还是 403，需要降级到 Playwright 兜底。
"""

from __future__ import annotations

from collections.abc import Iterator

from job_market.adapters._common import parse_date, split_locations
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.fetcher import Fetcher

API = "https://careers.pddglobalhr.com/api/job/list"
LISTING = "https://careers.pddglobalhr.com/campus/grad"
PAGE_SIZE = 20
MAX_PAGES = 100


class PinduoduoAdapter(CampusAdapter):
    company = "pinduoduo"
    rate_limit_qps = 1.0
    robots_probe_url = LISTING

    def list_jobs(self, fetcher: Fetcher) -> Iterator[RawJob]:
        try:
            fetcher.get(LISTING)
        except Exception:  # noqa: BLE001
            pass

        for page in range(1, MAX_PAGES + 1):
            body = {
                "pageNo": page,
                "pageSize": PAGE_SIZE,
                "keyword": "",
                "jobCategoryCodes": [],
                "cityCodes": [],
                "recruitTypeCode": "campus",
            }
            resp = fetcher.post(API, json=body)
            if resp.status_code != 200:
                return
            data = resp.json().get("data") or {}
            rows = data.get("list") or []
            if not rows:
                return
            for r in rows:
                jid = r.get("jobId") or r.get("id")
                yield RawJob(
                    source_url=f"https://careers.pddglobalhr.com/campus/grad/detail?jobId={jid}"
                    if jid
                    else LISTING,
                    payload=r,
                )
            total = data.get("total", 0)
            if page * PAGE_SIZE >= total:
                return

    def normalize(self, raw: RawJob) -> NormalizedJob:
        p = raw.payload
        jid = str(p.get("jobId") or p.get("id") or "")
        if not jid:
            raise ValueError("Pinduoduo payload 缺 jobId")
        return NormalizedJob(
            job_id=f"pinduoduo:{jid}",
            company="pinduoduo",
            title=str(p.get("jobName") or "").strip(),
            description=str(p.get("jobDescription") or ""),
            requirements=str(p.get("jobRequirement") or ""),
            location=split_locations(p.get("cityName")),
            education=p.get("eduDegree") or None,
            job_type="校招",
            department=str(p.get("departmentName") or "") or None,
            posted_at=parse_date(p.get("updateTime")),
            source_url=raw.source_url,
            raw_payload=p,
            extra={"job_category": p.get("jobCategoryName")},
        )
