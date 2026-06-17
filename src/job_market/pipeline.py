"""Pipeline 编排器：load config → 启用 adapter → robots 检查 → 并行抓 → 归一化 → 入库 + 双写。

错误隔离三层：
- 单条记录 normalize 失败 → 标 parsing_error，不影响公司批次
- 一家公司 list_jobs 抛异常 → 记录失败，不影响兄弟公司
- 配置/环境失败 → 整体退出非零（仅在 CLI 层判定）
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from job_market.adapters.base import CampusAdapter, RawJob, discover_adapters
from job_market.classifier import CategoryRules, load_categories, load_tech_keywords
from job_market.fetcher import Fetcher, FetcherConfig
from job_market.normalizer import normalize_record
from job_market.storage import Storage, write_raw

log = logging.getLogger(__name__)


@dataclass(slots=True)
class CompanyResult:
    """单家公司抓取结果。汇总到 RunSummary 用于打印 + exit code。"""

    company: str
    fetched: int = 0
    kept: int = 0
    dropped_non_tech: int = 0
    parsing_errors: int = 0
    duration_s: float = 0.0
    error: str | None = None  # 公司级失败的异常信息
    skipped_reason: str | None = None  # robots / 未启用


@dataclass(slots=True)
class RunSummary:
    companies: list[CompanyResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def total_kept(self) -> int:
        return sum(c.kept for c in self.companies)


@dataclass(slots=True)
class PipelineConfig:
    db_path: Path
    raw_dir: Path
    companies_yaml: Path
    categories_yaml: Path
    tech_keywords_yaml: Path
    max_workers: int = 10


def load_companies_config(path: str | Path) -> dict[str, dict[str, Any]]:
    """读取 companies.yaml。返回 {company: {enabled, rate_limit_qps, ...}}。"""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    companies = raw.get("companies", raw)
    if not isinstance(companies, dict):
        raise ValueError(f"{path} 顶层应为 companies map 或直接 map of companies")
    return companies


def _run_one_company(
    adapter: CampusAdapter,
    fetcher: Fetcher,
    category_rules: CategoryRules,
    tech_keywords: list[str],
    storage: Storage,
    raw_dir: Path,
    run_date: date,
    crawled_at: datetime,
) -> CompanyResult:
    """跑一家公司：fetch → normalize → 累积入库行 + 原始记录。"""
    result = CompanyResult(company=adapter.company)
    t0 = time.monotonic()
    rows: list[dict[str, Any]] = []
    raw_records: list[RawJob] = []

    try:
        for raw in adapter.list_jobs(fetcher):
            result.fetched += 1
            raw_records.append(raw)
            res = normalize_record(
                adapter,
                raw,
                category_rules=category_rules,
                tech_keywords=tech_keywords,
                crawled_at=crawled_at,
            )
            if res.parsing_error:
                result.parsing_errors += 1
            if res.dropped_non_tech:
                result.dropped_non_tech += 1
                continue
            if res.row is not None:
                rows.append(res.row)
    except Exception as exc:  # noqa: BLE001 — 公司级隔离
        result.error = f"{type(exc).__name__}: {exc}"
        log.exception("[%s] 抓取失败，跳过", adapter.company)

    # 入库 + 原始 JSONL（即使中途失败也尽量保留已抓部分）
    if rows:
        try:
            storage.upsert_jobs(rows)
            result.kept = len(rows)
        except Exception as exc:  # noqa: BLE001
            log.exception("[%s] 写库失败", adapter.company)
            result.error = (result.error or "") + f"; storage: {exc}"
    if raw_records:
        try:
            write_raw(raw_dir, adapter.company, raw_records, run_date=run_date)
        except Exception as exc:  # noqa: BLE001
            log.exception("[%s] 写 raw 失败", adapter.company)
            result.error = (result.error or "") + f"; raw: {exc}"

    result.duration_s = time.monotonic() - t0
    return result


def run_pipeline(
    config: PipelineConfig,
    *,
    on_company_done: Callable[[CompanyResult], None] | None = None,
) -> RunSummary:
    """主入口：加载配置、启动 adapter、并行抓、汇总。

    `on_company_done` 在每家公司返回时回调一次，便于 CLI 流式打印或
    在 KeyboardInterrupt 时还原已完成的进度。
    """
    summary = RunSummary()
    crawled_at = datetime.now(UTC)
    run_date = crawled_at.date()

    # 加载词典 + 公司配置
    category_rules = load_categories(config.categories_yaml)
    tech_keywords = load_tech_keywords(config.tech_keywords_yaml)
    companies_cfg = load_companies_config(config.companies_yaml)

    # 发现 adapter 类
    adapter_classes = discover_adapters()

    # 实例化启用的 adapter
    adapters: list[CampusAdapter] = []
    for company, cfg in companies_cfg.items():
        cfg = cfg or {}
        if not cfg.get("enabled", True):
            res = CompanyResult(company=company, skipped_reason="disabled in config")
            summary.companies.append(res)
            if on_company_done:
                on_company_done(res)
            continue
        cls = adapter_classes.get(company)
        if cls is None:
            res = CompanyResult(company=company, skipped_reason="no adapter module found")
            summary.companies.append(res)
            log.warning("找不到 %s 的 adapter，跳过", company)
            if on_company_done:
                on_company_done(res)
            continue
        try:
            instance = cls(rate_limit_qps=cfg.get("rate_limit_qps"))
        except Exception as exc:  # noqa: BLE001
            res = CompanyResult(company=company, error=f"init failed: {exc}")
            summary.companies.append(res)
            if on_company_done:
                on_company_done(res)
            continue
        adapters.append(instance)

    # 准备 storage + fetcher
    storage = Storage(config.db_path)
    fetcher = Fetcher(FetcherConfig(default_qps=1.0))

    # 启动时 robots.txt 检查（基于一个探测 URL；adapter 可在自身实现里再细查）
    runnable: list[CampusAdapter] = []
    for ad in adapters:
        probe = getattr(ad, "robots_probe_url", None)
        if probe and not fetcher.check_robots(probe):
            res = CompanyResult(
                company=ad.company, skipped_reason=f"robots.txt disallows {probe}"
            )
            summary.companies.append(res)
            log.info("[%s] robots.txt 禁止 %s，跳过", ad.company, probe)
            if on_company_done:
                on_company_done(res)
            continue
        runnable.append(ad)

    # 并行跑公司
    if runnable:
        with ThreadPoolExecutor(max_workers=min(config.max_workers, len(runnable))) as pool:
            futures = {
                pool.submit(
                    _run_one_company,
                    ad,
                    fetcher,
                    category_rules,
                    tech_keywords,
                    storage,
                    config.raw_dir,
                    run_date,
                    crawled_at,
                ): ad
                for ad in runnable
            }
            try:
                for fut in as_completed(futures):
                    res = fut.result()
                    summary.companies.append(res)
                    if on_company_done:
                        on_company_done(res)
            except KeyboardInterrupt:
                # 取消还没开始的 future；正在跑的会自然收尾
                for f in futures:
                    f.cancel()
                fetcher.close()
                raise

    fetcher.close()
    return summary
