## Why

User wants to understand the macro structure of demand for tech roles in 校招 (Chinese big-tech campus recruitment) — which directions, which tech stacks, which cities, which education levels are most in demand — to inform their own job-search decisions. No existing tool gives a clean snapshot across the 10 target 大厂 in a SQL-queryable form, with non-tech roles filtered out and tech keywords extracted. We have an approved design in `docs/superpowers/specs/2026-06-17-job-market-crawler-design.md` and need to translate it into shippable code.

## What Changes

- Stand up a Python project under `src/job_market/` with adapter-per-company architecture, SQLite + raw JSON storage, and a Jupyter trends report
- Add a unified `Fetcher` (httpx + per-host token-bucket rate limit, ≤1 QPS per host, ≤10 QPS global, robots.txt check at startup, exponential backoff on 5xx)
- Add a `CampusAdapter` abstract base class and concrete adapters for ByteDance, Alibaba, Tencent, Meituan, JD, NetEase, Xiaomi, Pinduoduo, Baidu, and Huawei (Huawei may require Playwright fallback)
- Add a two-stage classifier: `is_tech_role()` drops non-tech roles before storage; `assign_category()` maps survivors into 13 tech categories (`algorithm`, `ai`, `backend`, `frontend`, `mobile`, `client`, `embedded`, `hardware`, `data`, `infra`, `security`, `qa`, `tech_other`)
- Add YAML-driven dictionaries for categories and tech keywords (`config/categories.yaml`, `config/tech_keywords.yaml`) so word lists can iterate without code change
- Add SQLite storage with the `jobs` table from the design doc, indexed by `company`, `category`, `crawled_at`; double-write raw payloads to `data/raw/YYYY-MM-DD/<company>.jsonl` for replay
- Add CLI entry `python -m job_market crawl` that runs the full pipeline with per-company error isolation
- Add `notebooks/trends.ipynb` producing 6 charts: company×category stacked bar, tech-keyword top 30, location pie, education distribution by category, subcategory top-N, overall summary

## Capabilities

### New Capabilities

- `job-collection`: Discover and fetch public campus-job listings from each target 大厂's official site, behind a uniform `CampusAdapter` contract, with shared HTTP fetching, per-host rate limiting, retries, and robots.txt compliance.
- `tech-classification`: Filter out non-tech roles and classify survivors into 13 tech categories, plus extract a normalized `tech_keywords` list — all driven by versioned YAML dictionaries so word lists evolve without code change.
- `job-storage`: Persist normalized jobs into SQLite (`jobs.db`) with raw-payload double-write to dated JSONL files, indexed for the analysis queries the trends notebook needs, and resilient to per-record `parsing_error`.
- `crawler-pipeline`: Orchestrate the end-to-end crawl: load config, instantiate enabled adapters, run companies in parallel with error isolation, emit per-company stats, and surface failures without taking down siblings.
- `trends-reporting`: Produce a one-shot Jupyter notebook that reads `jobs.db` and answers the user's macro questions (in-demand directions, tech stacks, cities, education levels) via 6 deterministic chart cells.

### Modified Capabilities

<!-- None — this is a greenfield project, no existing specs to delta. -->

## Impact

- **New code**: `src/job_market/` package, `tests/`, `config/*.yaml`, `notebooks/trends.ipynb`, `pyproject.toml`, updates to `README.md`
- **New runtime dependencies**: `httpx[http2]`, `pyyaml`, `pydantic` (or stdlib `dataclasses`), `playwright` (optional, lazy-imported, only if a Huawei-style adapter needs it), `jupyter`, `pandas`, `matplotlib`
- **New dev dependencies**: `pytest`, `pytest-mock`, `ruff`
- **New artifacts on disk**: `data/jobs.db`, `data/raw/YYYY-MM-DD/<company>.jsonl` (gitignored)
- **Network behavior**: Outbound HTTPS only to the 10 target companies' public 校招 endpoints; transparent UA; robots.txt checked at startup; total throughput ≤ 10 QPS, per-host ≤ 1 QPS
- **No** changes to existing files outside `openspec/`, `docs/`, and the new package structure; no existing specs to break
