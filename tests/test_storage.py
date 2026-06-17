"""storage 测试：建表、INSERT OR REPLACE 主键替换、crawled_at 更新、原始 JSONL 回放、索引存在。"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from job_market.adapters.base import RawJob
from job_market.storage import Storage, write_raw


def _row(job_id: str, *, crawled_at: str, title: str = "后端开发") -> dict:
    return {
        "job_id": job_id,
        "company": "fake",
        "title": title,
        "category": "backend",
        "subcategory": None,
        "description": "",
        "requirements": "",
        "tech_keywords": "[]",
        "location": "[]",
        "education": "本科",
        "job_type": "校招",
        "department": None,
        "posted_at": None,
        "crawled_at": crawled_at,
        "source_url": "https://example.com/" + job_id,
        "raw_payload": "{}",
        "parsing_error": 0,
    }


def test_schema_created_with_indexes(tmp_path: Path) -> None:
    db = tmp_path / "jobs.db"
    Storage(db)
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        assert "job_id" in cols and "category" in cols and "parsing_error" in cols
        idx = {r[1] for r in conn.execute("PRAGMA index_list(jobs)")}
        assert "idx_jobs_company" in idx
        assert "idx_jobs_category" in idx
        assert "idx_jobs_crawled_at" in idx


def test_upsert_replaces_existing_row(tmp_path: Path) -> None:
    s = Storage(tmp_path / "jobs.db")
    s.upsert_jobs([_row("fake:1", crawled_at="2026-06-17T10:00:00")])
    s.upsert_jobs([_row("fake:1", crawled_at="2026-06-17T11:00:00", title="升级版后端")])
    assert s.count() == 1
    with sqlite3.connect(tmp_path / "jobs.db") as conn:
        row = conn.execute("SELECT title, crawled_at FROM jobs WHERE job_id='fake:1'").fetchone()
    assert row[0] == "升级版后端"
    assert row[1] == "2026-06-17T11:00:00"


def test_upsert_empty_rows_is_noop(tmp_path: Path) -> None:
    s = Storage(tmp_path / "jobs.db")
    assert s.upsert_jobs([]) == 0
    assert s.count() == 0


def test_write_raw_round_trip(tmp_path: Path) -> None:
    raws = [
        RawJob(source_url="https://example.com/1", payload={"id": 1, "title": "后端"}),
        RawJob(source_url="https://example.com/2", payload={"id": 2}),
    ]
    path = write_raw(tmp_path / "raw", "fake", raws, run_date=date(2026, 6, 17))
    assert path.exists()
    assert path.parent.name == "2026-06-17"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["source_url"] == "https://example.com/1"
    assert parsed[0]["payload"] == {"id": 1, "title": "后端"}


def test_write_raw_overwrites_same_day(tmp_path: Path) -> None:
    write_raw(tmp_path / "raw", "fake", [RawJob("https://example.com/1", {"id": 1})], run_date=date(2026, 6, 17))
    path = write_raw(tmp_path / "raw", "fake", [RawJob("https://example.com/2", {"id": 2})], run_date=date(2026, 6, 17))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["source_url"] == "https://example.com/2"
