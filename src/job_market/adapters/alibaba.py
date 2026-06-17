"""阿里巴巴校招 adapter — POST JSON。

API：`https://talent.alibaba.com/position/search`
分页：pageIndex（1 起）+ pageSize
关键过滤：channelType=campus
schema：content.datas[]: {id, name, description, requirement, departmentName,
       workLocations[], categories[], lastUpdateTime, recruitType}; total at
       content.total

TODO[live-verify]: 阿里 talent 站点用 Aliyun 反爬，初次直 POST 可能拿不到 cookie，
首次调用前我们先 GET listing 让 cookie 落到 fetcher；上线时如果还 403 需要换
careers.aliyun.com 镜像或加 Origin header。
"""

from __future__ import annotations

from collections.abc import Iterator

from job_market.adapters._common import parse_date, split_locations
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.fetcher import Fetcher

API = "https://talent.alibaba.com/position/search"
LISTING = "https://talent.alibaba.com/campus/position-list"
PAGE_SIZE = 10
MAX_PAGES = 500


class AlibabaAdapter(CampusAdapter):
    company = "alibaba"
    rate_limit_qps = 1.0
    robots_probe_url = LISTING

    def list_jobs(self, fetcher: Fetcher) -> Iterator[RawJob]:
        try:
            fetcher.get(LISTING)
        except Exception:  # noqa: BLE001
            pass

        for page in range(1, MAX_PAGES + 1):
            body = {
                "channelType": "campus",
                "pageIndex": page,
                "pageSize": PAGE_SIZE,
                "keyWord": "",
                "departmentIds": [],
                "workLocations": [],
            }
            resp = fetcher.post(API, json=body)
            if resp.status_code != 200:
                return
            content = resp.json().get("content") or {}
            datas = content.get("datas") or []
            if not datas:
                return
            for d in datas:
                jid = d.get("id")
                yield RawJob(
                    source_url=f"https://talent.alibaba.com/off-campus/position-detail?positionId={jid}"
                    if jid
                    else LISTING,
                    payload=d,
                )
            total = content.get("total", 0)
            if page * PAGE_SIZE >= total:
                return

    def normalize(self, raw: RawJob) -> NormalizedJob:
        p = raw.payload
        jid = str(p.get("id") or "")
        if not jid:
            raise ValueError("Alibaba payload 缺 id")
        locs_raw = p.get("workLocations") or []
        if isinstance(locs_raw, list):
            locs = [
                str(x.get("name") if isinstance(x, dict) else x).strip()
                for x in locs_raw
                if x
            ]
        else:
            locs = split_locations(locs_raw)
        cats = p.get("categories") or []
        cat_name = None
        if cats and isinstance(cats[0], dict):
            cat_name = cats[0].get("name")
        return NormalizedJob(
            job_id=f"alibaba:{jid}",
            company="alibaba",
            title=str(p.get("name") or "").strip(),
            description=str(p.get("description") or ""),
            requirements=str(p.get("requirement") or ""),
            location=locs,
            education=p.get("degree") or None,
            job_type="校招",
            department=str(p.get("departmentName") or "") or None,
            posted_at=parse_date(p.get("lastUpdateTime")),
            source_url=raw.source_url,
            raw_payload=p,
            extra={"category_name": cat_name, "recruit_type": p.get("recruitType")},
        )
