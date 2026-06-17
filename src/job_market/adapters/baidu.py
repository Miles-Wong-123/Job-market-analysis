"""百度校招 adapter — POST form-encoded（AJAX path）。

API：`https://talent.baidu.com/jobs/list-ajax`
分页：pageNum + pageNumOnePage
关键过滤：recruitType=2（校招）
schema：data.list[]: {id, name, description, education, serviceConditionName,
       projectTypeName, workPlaceName, lastUpdateTime}; total at data.totalNum

TODO[live-verify]: 站点是 SSR + AJAX 双形态；如果 list-ajax 路径下线了可以
回退到解析 talent.baidu.com/jobs/list 的 HTML 表格。
"""

from __future__ import annotations

from collections.abc import Iterator

from job_market.adapters._common import parse_date, split_locations
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.fetcher import Fetcher

API = "https://talent.baidu.com/jobs/list-ajax"
LISTING = "https://talent.baidu.com/jobs/list"
PAGE_SIZE = 10
MAX_PAGES = 200


class BaiduAdapter(CampusAdapter):
    company = "baidu"
    rate_limit_qps = 1.0
    robots_probe_url = LISTING

    def list_jobs(self, fetcher: Fetcher) -> Iterator[RawJob]:
        try:
            fetcher.get(LISTING)
        except Exception:  # noqa: BLE001
            pass

        for page in range(1, MAX_PAGES + 1):
            data = {
                "recruitType": "2",
                "pageNum": str(page),
                "pageNumOnePage": str(PAGE_SIZE),
                "keyWord": "",
                "serviceCondition": "2,3,4,5,6,7,8",
                "projectType": "",
            }
            resp = fetcher.post(API, data=data)
            if resp.status_code != 200:
                return
            payload = resp.json().get("data") or {}
            rows = payload.get("list") or []
            if not rows:
                return
            for r in rows:
                jid = r.get("id")
                yield RawJob(
                    source_url=f"https://talent.baidu.com/jobs/detail/{jid}"
                    if jid
                    else LISTING,
                    payload=r,
                )
            total = payload.get("totalNum", 0)
            if page * PAGE_SIZE >= total:
                return

    def normalize(self, raw: RawJob) -> NormalizedJob:
        p = raw.payload
        jid = str(p.get("id") or "")
        if not jid:
            raise ValueError("Baidu payload 缺 id")
        return NormalizedJob(
            job_id=f"baidu:{jid}",
            company="baidu",
            title=str(p.get("name") or "").strip(),
            description=str(p.get("description") or ""),
            requirements="",
            location=split_locations(p.get("workPlaceName")),
            education=p.get("education") or None,
            job_type="校招",
            department=str(p.get("projectTypeName") or "") or None,
            posted_at=parse_date(p.get("lastUpdateTime")),
            source_url=raw.source_url,
            raw_payload=p,
            extra={
                "service_condition": p.get("serviceConditionName"),
                "project_type": p.get("projectTypeName"),
            },
        )
