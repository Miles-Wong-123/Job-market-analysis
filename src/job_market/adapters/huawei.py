"""华为校招 adapter — 尝试 JSON API，必要时 Playwright 兜底。

# 选择说明（top-of-file 注释）：
# career.huawei.com 是 Vue SPA，反爬较强。research agent 的探测结论：
#   - 候选 API：`https://career.huawei.com/reccampportal/services/portal/portaljob/jobList`
#   - 直 GET / POST 在多数环境下返回 404 或被反爬拦截
#   - 站点完全是 client-side render，意味着 SPA 渲染后才能拿到岗位列表
# 所以本 adapter 同时实现两条路径：
#   1. **JSON API 优先**：构造 POST，如果 200 + JSON 形如已知 schema，直接解析
#   2. **Playwright 兜底**：当 API 路径返回 404/403/HTML 时，懒加载 playwright
#      启动 chromium，加载 listing 页面，等岗位列表渲染出来后从全局 window 状态
#      或截获的 XHR 中拿数据
#
# Playwright 是可选依赖（pyproject 的 [project.optional-dependencies].playwright），
# 这里 lazy import，避免其他 adapter 的用户被迫安装 chromium。
#
# TODO[live-verify]: API 路径与 schema 都未在本会话验证；上线时若 JSON 路径不通，
# 切到 Playwright 路径并用 DevTools 抓真实接口名替换。

API = "https://career.huawei.com/reccampportal/services/portal/portaljob/jobList"
LISTING = "https://career.huawei.com/reccampportal/portal5/campus-recruitment.html"
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from job_market.adapters._common import parse_date, split_locations
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.fetcher import Fetcher

API = "https://career.huawei.com/reccampportal/services/portal/portaljob/jobList"
LISTING = "https://career.huawei.com/reccampportal/portal5/campus-recruitment.html"
PAGE_SIZE = 10
MAX_PAGES = 200

log = logging.getLogger(__name__)


class HuaweiAdapter(CampusAdapter):
    company = "huawei"
    rate_limit_qps = 0.5  # 反爬更紧，限速调慢
    robots_probe_url = LISTING

    def list_jobs(self, fetcher: Fetcher) -> Iterator[RawJob]:
        # 1. JSON API 优先
        yielded_any = False
        try:
            yield from self._list_via_json(fetcher)
            yielded_any = True
        except _JsonPathFailed as exc:
            log.info("华为 JSON API 不通（%s），尝试 Playwright 兜底", exc)

        if yielded_any:
            return

        # 2. Playwright 兜底
        try:
            yield from self._list_via_playwright()
        except ImportError:
            log.warning("华为 adapter 兜底失败：未安装 playwright（pip install -e .[playwright]）")
        except Exception as exc:  # noqa: BLE001
            log.warning("华为 Playwright 兜底也失败：%s", exc)

    # --- 路径 1：JSON API ---

    def _list_via_json(self, fetcher: Fetcher) -> Iterator[RawJob]:
        for page in range(1, MAX_PAGES + 1):
            body = {
                "pageNum": page,
                "pageSize": PAGE_SIZE,
                "keyWord": "",
                "jobFamClsCode": "",
                "jobFamCode": "",
                "countryCode": "",
                "cityCode": "",
                "recruitType": "校园招聘",
            }
            resp = fetcher.post(API, json=body)
            if resp.status_code != 200:
                raise _JsonPathFailed(f"status={resp.status_code}")
            try:
                data = resp.json().get("data") or {}
            except (ValueError, AttributeError) as exc:
                raise _JsonPathFailed(f"非 JSON 响应：{exc}") from exc
            rows = data.get("list") or []
            if not rows:
                if page == 1:
                    raise _JsonPathFailed("第一页就是空，疑似 schema 变更")
                return
            for r in rows:
                jid = r.get("jobId") or r.get("id")
                yield RawJob(
                    source_url=f"https://career.huawei.com/reccampportal/portal5/campus-job-detail.html?jobId={jid}"
                    if jid
                    else LISTING,
                    payload=r,
                )
            total = data.get("totalRecord", 0)
            if page * PAGE_SIZE >= total:
                return

    # --- 路径 2：Playwright 兜底 ---

    def _list_via_playwright(self) -> Iterator[RawJob]:
        # 懒加载：未装 playwright 直接抛 ImportError，被上面捕获并降级
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        captured: list[dict] = []

        def _on_response(response):  # type: ignore[no-untyped-def]
            try:
                if "/portaljob/jobList" in response.url:
                    body = response.json()
                    rows = ((body.get("data") or {}).get("list")) or []
                    captured.extend(rows)
            except Exception:  # noqa: BLE001
                pass

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.on("response", _on_response)
            page.goto(LISTING, wait_until="networkidle", timeout=60_000)
            # 简单翻页：点几次"下一页"，最多 50 次防呆
            for _ in range(50):
                if not page.locator("text=下一页").first.is_enabled():
                    break
                page.locator("text=下一页").first.click()
                page.wait_for_load_state("networkidle", timeout=30_000)
            browser.close()

        for r in captured:
            jid = r.get("jobId") or r.get("id")
            yield RawJob(
                source_url=f"https://career.huawei.com/reccampportal/portal5/campus-job-detail.html?jobId={jid}"
                if jid
                else LISTING,
                payload=r,
            )

    def normalize(self, raw: RawJob) -> NormalizedJob:
        p = raw.payload
        jid = str(p.get("jobId") or p.get("id") or "")
        if not jid:
            raise ValueError("Huawei payload 缺 jobId")
        return NormalizedJob(
            job_id=f"huawei:{jid}",
            company="huawei",
            title=str(p.get("jobName") or "").strip(),
            description=str(p.get("jobResponsibility") or ""),
            requirements=str(p.get("jobRequirement") or ""),
            location=split_locations(p.get("cityName") or p.get("countryName")),
            education=p.get("eduDegree") or None,
            job_type="校招",
            department=str(p.get("jobFamilyName") or "") or None,
            posted_at=parse_date(p.get("postingDate")),
            source_url=raw.source_url,
            raw_payload=p,
            extra={
                "country_name": p.get("countryName"),
                "recruit_type": p.get("recruitType"),
            },
        )


class _JsonPathFailed(RuntimeError):
    """JSON API 路径走不通的内部信号。"""


# 让模块级导入不污染：playwright 没装也能 import 这个 adapter
__all__ = ["HuaweiAdapter"]
