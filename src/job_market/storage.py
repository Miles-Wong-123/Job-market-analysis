"""SQLite 存储 + 原始 JSONL 双写。

normalize 后的 row 通过 `upsert_jobs` 进 SQLite；每家公司的原始响应
通过 `write_raw` 落到 `data/raw/<日期>/<公司>.jsonl`，方便后续重跑归一化。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from job_market.adapters.base import RawJob

log = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    company       TEXT NOT NULL,
    title         TEXT,
    category      TEXT,
    subcategory   TEXT,
    description   TEXT,
    requirements  TEXT,
    tech_keywords TEXT,    -- JSON 数组
    location      TEXT,    -- JSON 数组
    education     TEXT,
    job_type      TEXT,
    department    TEXT,
    posted_at     TEXT,
    crawled_at    TEXT NOT NULL,
    source_url    TEXT,
    raw_payload   TEXT,    -- JSON 对象
    parsing_error INTEGER NOT NULL DEFAULT 0
);
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_crawled_at ON jobs(crawled_at);",
)

COLUMNS = (
    "job_id",
    "company",
    "title",
    "category",
    "subcategory",
    "description",
    "requirements",
    "tech_keywords",
    "location",
    "education",
    "job_type",
    "department",
    "posted_at",
    "crawled_at",
    "source_url",
    "raw_payload",
    "parsing_error",
)


class Storage:
    """轻量 SQLite 封装。线程安全靠每次 `connect` 拿新连接（SQLite 默认）。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            for stmt in INDEXES:
                conn.execute(stmt)
            conn.commit()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def upsert_jobs(self, rows: Sequence[dict[str, Any]]) -> int:
        """批量 INSERT OR REPLACE。返回写入条数。"""
        if not rows:
            return 0
        placeholders = ",".join("?" * len(COLUMNS))
        sql = f"INSERT OR REPLACE INTO jobs ({','.join(COLUMNS)}) VALUES ({placeholders})"
        values = [tuple(row.get(col) for col in COLUMNS) for row in rows]
        with self._conn() as conn:
            conn.executemany(sql, values)
            conn.commit()
        return len(values)

    def count(self, where: str = "", params: Sequence[Any] = ()) -> int:
        sql = "SELECT COUNT(*) FROM jobs"
        if where:
            sql += f" WHERE {where}"
        with self._conn() as conn:
            return conn.execute(sql, params).fetchone()[0]


def write_raw(
    raw_dir: str | Path,
    company: str,
    raws: Iterable[RawJob],
    *,
    run_date: date | None = None,
) -> Path:
    """把一家公司的原始响应写入 `data/raw/<日期>/<公司>.jsonl`，覆盖式。

    每行一个 JSON 对象 `{source_url, payload}`。即使 normalize 失败也照写，
    raw 是事后修复归一化逻辑的依据。
    """
    run_date = run_date or date.today()
    dir_ = Path(raw_dir) / run_date.isoformat()
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"{company}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for raw in raws:
            f.write(json.dumps({"source_url": raw.source_url, "payload": raw.payload}, ensure_ascii=False))
            f.write("\n")
    return path
