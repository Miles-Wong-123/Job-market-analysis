"""京东校招 adapter — POST form-encoded（zhaopin.jd.com 路径）。

API：`https://zhaopin.jd.com/web/job/job_listJson`
分页：pageNo + pageSize
关键过滤：jobType=2（校招）
schema：resultData.resultList[]: {id, jobName, jobReqDeptName, jobAreaCode,
       jobAreaName, jobReqType, jobBrief, jobDuty, jobDemand, modifyDate};
       total at resultData.totalCount

TODO[live-verify]: 京东校招在 campus.jd.com 走 SSO，所以选 zhaopin.jd.com 这个老 portal。
字段名以社区脚本为准；上线时要确认 jobType 数值（2=校招？历史也用过 1）。
"""

from __future__ import annotations

from collections.abc import Iterator

from job_market.adapters._common import parse_date, split_locations
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.fetcher import Fetcher

API = "https://zhaopin.jd.com/web/job/job_listJson"
LISTING = "https://zhaopin.jd.com/web/job"
PAGE_SIZE = 10
MAX_PAGES = 200


class JDAdapter(CampusAdapter):
    company = "jd"
    rate_limit_qps = 1.0
    robots_probe_url = LISTING

    def list_jobs(self, fetcher: Fetcher) -> Iterator[RawJob]:
        try:
            fetcher.get(LISTING)
        except Exception:  # noqa: BLE001
            pass

        for page in range(1, MAX_PAGES + 1):
            data = {
                "command": "jobList",
                "pageNo": str(page),
                "pageSize": str(PAGE_SIZE),
                "keyword": "",
                "jobType": "2",
                "jobAreaCode": "",
            }
            resp = fetcher.post(API, data=data)
            if resp.status_code != 200:
                return
            payload = resp.json().get("resultData") or {}
            rows = payload.get("resultList") or []
            if not rows:
                return
            for r in rows:
                jid = r.get("id") or r.get("jobReqLkid")
                yield RawJob(
                    source_url=f"https://zhaopin.jd.com/web/job/job_detail?jobId={jid}"
                    if jid
                    else LISTING,
                    payload=r,
                )
            total = payload.get("totalCount", 0)
            if page * PAGE_SIZE >= total:
                return

    def normalize(self, raw: RawJob) -> NormalizedJob:
        p = raw.payload
        jid = str(p.get("id") or p.get("jobReqLkid") or "")
        if not jid:
            raise ValueError("JD payload 缺 id")
        return NormalizedJob(
            job_id=f"jd:{jid}",
            company="jd",
            title=str(p.get("jobName") or "").strip(),
            description=str(p.get("jobBrief") or p.get("jobDuty") or ""),
            requirements=str(p.get("jobDemand") or ""),
            location=split_locations(p.get("jobAreaName")),
            education=p.get("eduDegree") or None,
            job_type="校招",
            department=str(p.get("jobReqDeptName") or "") or None,
            posted_at=parse_date(p.get("modifyDate") or p.get("createDate")),
            source_url=raw.source_url,
            raw_payload=p,
            extra={"job_req_type": p.get("jobReqType")},
        )
