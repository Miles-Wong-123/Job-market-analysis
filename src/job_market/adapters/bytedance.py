"""字节跳动校招 adapter — POST JSON API。

API：`https://jobs.bytedance.com/api/v1/search/job/posts`
鉴权：实际请求需要先 GET listing 页拿到 _csrf_session_id cookie，再带 x-csrf-token
       header POST。adapter 在首次 POST 拿到 403 时会回退到 GET listing 触发 cookie，
       再重试一次（fetcher 已有 cookie jar）。
分页：body 里的 limit + offset
关键过滤：portal_type=4 = 国内校招（6 全球，2 社招）
schema：data.job_post_list[]: {id, title, sub_title, description, requirement,
       job_category{name}, recruit_type{name}, city_list[{name,en_name}], publish_time,
       code}; total at data.count

TODO[live-verify]: 字段名以 2024-2025 年公开抓取脚本为准；上线前请用 DevTools 复核
sub_title / job_category 子结构，因为字节后端历史上做过两次重命名。
"""

from __future__ import annotations

from collections.abc import Iterator

from job_market.adapters._common import parse_date, split_locations
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.fetcher import Fetcher

API = "https://jobs.bytedance.com/api/v1/search/job/posts"
LISTING = "https://jobs.bytedance.com/campus/position"
PAGE_SIZE = 10
MAX_PAGES = 500


class ByteDanceAdapter(CampusAdapter):
    company = "bytedance"
    rate_limit_qps = 1.0
    robots_probe_url = LISTING

    def list_jobs(self, fetcher: Fetcher) -> Iterator[RawJob]:
        # 先 GET listing 让 cookie 落到 fetcher 的 client 里（顺带触发 _csrf_session_id）
        try:
            fetcher.get(LISTING)
        except Exception:  # noqa: BLE001 — 不阻断后续 POST
            pass

        for page in range(MAX_PAGES):
            offset = page * PAGE_SIZE
            body = {
                "keyword": "",
                "limit": PAGE_SIZE,
                "offset": offset,
                "job_category_id_list": [],
                "tag_id_list": [],
                "location_code_list": [],
                "subject_id_list": [],
                "recruitment_id_list": [],
                "portal_type": 4,  # 国内校招
                "portal_entrance": 1,
            }
            resp = fetcher.post(API, json=body)
            if resp.status_code != 200:
                return
            data = resp.json().get("data") or {}
            posts = data.get("job_post_list") or []
            if not posts:
                return
            for p in posts:
                code = p.get("code") or p.get("id")
                yield RawJob(
                    source_url=f"https://jobs.bytedance.com/campus/position/{code}/detail"
                    if code
                    else LISTING,
                    payload=p,
                )
            total = data.get("count", 0)
            if offset + PAGE_SIZE >= total:
                return

    def normalize(self, raw: RawJob) -> NormalizedJob:
        p = raw.payload
        post_id = str(p.get("id") or p.get("code") or "")
        if not post_id:
            raise ValueError("ByteDance payload 缺 id")
        cities = p.get("city_list") or []
        loc = [c.get("name") for c in cities if isinstance(c, dict) and c.get("name")]
        category = (p.get("job_category") or {}).get("name") if isinstance(p.get("job_category"), dict) else None
        return NormalizedJob(
            job_id=f"bytedance:{post_id}",
            company="bytedance",
            title=str(p.get("title") or "").strip(),
            description=str(p.get("description") or ""),
            requirements=str(p.get("requirement") or ""),
            location=loc or split_locations(p.get("city")),
            education=None,
            job_type="校招",
            department=str(p.get("sub_title") or "") or None,
            posted_at=parse_date(p.get("publish_time")),
            source_url=raw.source_url,
            raw_payload=p,
            extra={"category_name": category},
        )
