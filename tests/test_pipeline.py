"""pipeline 端到端测试：3 家 mock adapter，一家中途抛错，确认隔离 + 入库 + raw 写入。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from job_market.adapters import base as base_mod
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob
from job_market.pipeline import PipelineConfig, run_pipeline


# --- 构造 3 家假 adapter ---


class GoodAdapter(CampusAdapter):
    company = "good"

    def list_jobs(self, fetcher):  # type: ignore[override]
        for i in range(3):
            yield RawJob(source_url=f"https://good.example.com/{i}", payload={"id": i})

    def normalize(self, raw: RawJob) -> NormalizedJob:
        i = raw.payload["id"]
        return NormalizedJob(
            job_id=f"good:{i}",
            company="good",
            title="后端开发工程师",
            description="Java 服务端，分布式",
            requirements="",
            location=["北京"],
            education="本科",
            job_type="校招",
            department=None,
            posted_at=None,
            source_url=raw.source_url,
            raw_payload=raw.payload,
        )


class BadAdapter(CampusAdapter):
    company = "bad"

    def list_jobs(self, fetcher):  # type: ignore[override]
        yield RawJob(source_url="https://bad.example.com/1", payload={"id": 1})
        raise RuntimeError("schema 变了")

    def normalize(self, raw: RawJob) -> NormalizedJob:
        return NormalizedJob(
            job_id="bad:1",
            company="bad",
            title="后端开发",
            description="",
            requirements="",
            location=[],
            education=None,
            job_type="校招",
            department=None,
            posted_at=None,
            source_url=raw.source_url,
            raw_payload=raw.payload,
        )


class MixedAdapter(CampusAdapter):
    """混合：1 个技术岗 + 1 个非技术岗（应被丢弃）。"""

    company = "mixed"

    def list_jobs(self, fetcher):  # type: ignore[override]
        yield RawJob(source_url="https://mixed.example.com/tech", payload={"k": "tech"})
        yield RawJob(source_url="https://mixed.example.com/pm", payload={"k": "pm"})

    def normalize(self, raw: RawJob) -> NormalizedJob:
        if raw.payload["k"] == "tech":
            return NormalizedJob(
                job_id="mixed:tech",
                company="mixed",
                title="算法工程师-推荐方向",
                description="Python, PyTorch",
                requirements="",
                location=["上海"],
                education="硕士",
                job_type="校招",
                department=None,
                posted_at=None,
                source_url=raw.source_url,
                raw_payload=raw.payload,
            )
        return NormalizedJob(
            job_id="mixed:pm",
            company="mixed",
            title="产品经理-社交方向",
            description="",
            requirements="",
            location=[],
            education=None,
            job_type="校招",
            department=None,
            posted_at=None,
            source_url=raw.source_url,
            raw_payload=raw.payload,
        )


# --- fixture：把 discover_adapters 替换成上面三个 ---


@pytest.fixture
def patched_adapters(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        base_mod,
        "discover_adapters",
        lambda: {"good": GoodAdapter, "bad": BadAdapter, "mixed": MixedAdapter},
    )
    # pipeline 模块也 import 了，所以再 patch 一份
    from job_market import pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "discover_adapters", lambda: {"good": GoodAdapter, "bad": BadAdapter, "mixed": MixedAdapter})


@pytest.fixture
def config_files(tmp_path: Path) -> dict[str, Path]:
    companies_yaml = tmp_path / "companies.yaml"
    companies_yaml.write_text(
        "companies:\n  good: {enabled: true, rate_limit_qps: 100}\n  bad: {enabled: true, rate_limit_qps: 100}\n  mixed: {enabled: true, rate_limit_qps: 100}\n",
        encoding="utf-8",
    )
    categories_yaml = tmp_path / "categories.yaml"
    categories_yaml.write_text(
        "algorithm:\n  patterns: [算法, 推荐]\nbackend:\n  patterns: [后端, Java]\n",
        encoding="utf-8",
    )
    tech_keywords_yaml = tmp_path / "tech_keywords.yaml"
    tech_keywords_yaml.write_text("- python\n- java\n- pytorch\n", encoding="utf-8")
    return {
        "companies": companies_yaml,
        "categories": categories_yaml,
        "tech_keywords": tech_keywords_yaml,
    }


def test_pipeline_isolates_failures_persists_others(
    tmp_path: Path,
    patched_adapters: None,
    config_files: dict[str, Path],
) -> None:
    cfg = PipelineConfig(
        db_path=tmp_path / "jobs.db",
        raw_dir=tmp_path / "raw",
        companies_yaml=config_files["companies"],
        categories_yaml=config_files["categories"],
        tech_keywords_yaml=config_files["tech_keywords"],
    )
    summary = run_pipeline(cfg)

    by_company = {c.company: c for c in summary.companies}
    assert set(by_company) == {"good", "bad", "mixed"}

    # good：3 条，全部技术岗
    assert by_company["good"].fetched == 3
    assert by_company["good"].kept == 3
    assert by_company["good"].error is None

    # bad：抛了异常，但抛错前已 yield 了 1 条
    assert by_company["bad"].error is not None
    assert "schema" in by_company["bad"].error or "RuntimeError" in by_company["bad"].error

    # mixed：1 技术 + 1 非技术
    assert by_company["mixed"].kept == 1
    assert by_company["mixed"].dropped_non_tech == 1

    # SQLite 中应有 good:0/1/2 + bad:1（异常前已抓的）+ mixed:tech，共 5 条
    with sqlite3.connect(tmp_path / "jobs.db") as conn:
        ids = [r[0] for r in conn.execute("SELECT job_id FROM jobs ORDER BY job_id")]
    assert "good:0" in ids and "good:1" in ids and "good:2" in ids
    assert "mixed:tech" in ids
    # 非技术岗一定不在
    assert "mixed:pm" not in ids

    # raw JSONL：每家公司各一份
    raw_root = tmp_path / "raw"
    day_dirs = list(raw_root.iterdir())
    assert len(day_dirs) == 1
    files = {p.name for p in day_dirs[0].iterdir()}
    assert files == {"good.jsonl", "bad.jsonl", "mixed.jsonl"}

    # bad.jsonl 至少有 1 行（异常前已抓的）
    bad_lines = (day_dirs[0] / "bad.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(bad_lines) == 1
    assert json.loads(bad_lines[0])["payload"] == {"id": 1}


def test_disabled_company_skipped(
    tmp_path: Path,
    patched_adapters: None,
    config_files: dict[str, Path],
) -> None:
    config_files["companies"].write_text(
        "companies:\n  good: {enabled: false}\n  bad: {enabled: false}\n  mixed: {enabled: true, rate_limit_qps: 100}\n",
        encoding="utf-8",
    )
    cfg = PipelineConfig(
        db_path=tmp_path / "jobs.db",
        raw_dir=tmp_path / "raw",
        companies_yaml=config_files["companies"],
        categories_yaml=config_files["categories"],
        tech_keywords_yaml=config_files["tech_keywords"],
    )
    summary = run_pipeline(cfg)
    by_company = {c.company: c for c in summary.companies}
    assert by_company["good"].skipped_reason == "disabled in config"
    assert by_company["bad"].skipped_reason == "disabled in config"
    assert by_company["mixed"].kept == 1
