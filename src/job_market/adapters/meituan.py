"""美团校招 adapter — POST JSON。

API：`https://zhaopin.meituan.com/api/web/jobList`
分页：pageNum + pageSize
关键过滤：recruitType=2（校招）
schema：data.list[]: {id, jobName, jobFamily, workCity, recruitType,
       jobDescription, jobRequirement, jobBrief, updateTime, code};
       total at data.totalCount

TODO[live-verify]: 美团 SPA 需要先访问 /web/campus 拿 session cookie；adapter 已在
list_jobs 开头做了一次 GET。如果上线时 401，可能需要补 Origin header。字段名
来自社区脚本，需要 DevTools 复核（特别是 jobFamily 是否拆成对象）。
"""

from __future__ import annotations

from collections.abc import Iterator

from job_market.adapters._common import parse_date, split_locations
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.fetcher import Fetcher

API = "https://zhaopin.meituan.com/api/web/jobList"
LISTING = "https://zhaopin.meituan.com/web/campus"
PAGE_SIZE = 20
MAX_PAGES = 200


class MeituanAdapter(CampusAdapter):
    company = "meituan"
    rate_limit_qps = 1.0
    robots_probe_url = LISTING

    def list_jobs(self, fetcher: Fetcher) -> Iterator[RawJob]:
        try:
            fetcher.get(LISTING)
        except Exception:  # noqa: BLE001
            pass

        for page in range(1, MAX_PAGES + 1):
            body = {
                "pageNum": page,
                "pageSize": PAGE_SIZE,
                "queryWord": "",
                "jobFamily": [],
                "workCity": [],
                "recruitType": 2,
            }
            resp = fetcher.post(API, json=body)
            if resp.status_code != 200:
                return
            data = resp.json().get("data") or {}
            rows = data.get("list") or []
            if not rows:
                return
            for r in rows:
                code = r.get("code") or r.get("id")
                yield RawJob(
                    source_url=f"https://zhaopin.meituan.com/web/position/{code}"
                    if code
                    else LISTING,
                    payload=r,
                )
            total = data.get("totalCount", 0)
            if page * PAGE_SIZE >= total:
                return

    def normalize(self, raw: RawJob) -> NormalizedJob:
        p = raw.payload
        jid = str(p.get("id") or p.get("code") or "")
        if not jid:
            raise ValueError("Meituan payload 缺 id")
        family = p.get("jobFamily")
        if isinstance(family, dict):
            family_name = family.get("name")
        else:
            family_name = family
        return NormalizedJob(
            job_id=f"meituan:{jid}",
            company="meituan",
            title=str(p.get("jobName") or "").strip(),
            description=str(p.get("jobDescription") or p.get("jobBrief") or ""),
            requirements=str(p.get("jobRequirement") or ""),
            location=split_locations(p.get("workCity")),
            education=p.get("degree") or None,
            job_type="校招",
            department=str(p.get("bgName") or "") or None,
            posted_at=parse_date(p.get("updateTime")),
            source_url=raw.source_url,
            raw_payload=p,
            extra={"job_family": family_name},
        )
