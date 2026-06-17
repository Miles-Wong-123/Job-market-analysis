"""小米校招 adapter — POST JSON。

API：`https://hr.xiaomi.com/api/website-pc/recruit/position/list`
分页：pageNo + pageSize
关键过滤：recruitType=1（校招）
schema：data.list[]: {jobId, jobName, recruitType, workPlace, jobCategory,
       jobDuty, jobRequirement, publishTime}; total at data.total

TODO[live-verify]: research agent 报告说历史路径常变；上线时如果 404 要换为
`/api/recruit/position/list` 或 `/api/website-pc/job/list`。
"""

from __future__ import annotations

from collections.abc import Iterator

from job_market.adapters._common import parse_date, split_locations
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.fetcher import Fetcher

API = "https://hr.xiaomi.com/api/website-pc/recruit/position/list"
LISTING = "https://hr.xiaomi.com/web/campus"
PAGE_SIZE = 20
MAX_PAGES = 100


class XiaomiAdapter(CampusAdapter):
    company = "xiaomi"
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
                "recruitType": 1,
                "workPlaceList": [],
                "jobCategoryList": [],
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
                    source_url=f"https://hr.xiaomi.com/web/job-detail?jobId={jid}"
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
            raise ValueError("Xiaomi payload 缺 jobId")
        return NormalizedJob(
            job_id=f"xiaomi:{jid}",
            company="xiaomi",
            title=str(p.get("jobName") or "").strip(),
            description=str(p.get("jobDuty") or ""),
            requirements=str(p.get("jobRequirement") or ""),
            location=split_locations(p.get("workPlace")),
            education=p.get("eduDegree") or None,
            job_type="校招",
            department=str(p.get("departmentName") or "") or None,
            posted_at=parse_date(p.get("publishTime")),
            source_url=raw.source_url,
            raw_payload=p,
            extra={"job_category": p.get("jobCategory")},
        )
