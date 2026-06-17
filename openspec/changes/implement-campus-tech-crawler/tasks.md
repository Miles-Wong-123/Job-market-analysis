## 1. Project scaffolding

- [x] 1.1 Create `pyproject.toml` (PEP 621), Python ≥ 3.11, src layout, package name `job_market`
- [x] 1.2 Declare runtime deps: `httpx[http2]`, `pyyaml`, `tenacity` (or equivalent retry helper if preferred), and an optional extra `playwright` for the lazy fallback
- [x] 1.3 Declare dev deps: `pytest`, `pytest-mock`, `ruff`, `jupyter`, `pandas`, `matplotlib`
- [x] 1.4 Create the package skeleton: `src/job_market/{__init__.py,__main__.py,cli.py,fetcher.py,normalizer.py,classifier.py,storage.py,pipeline.py}` and `src/job_market/adapters/{__init__.py,base.py}`
- [x] 1.5 Create `config/{companies.yaml,categories.yaml,tech_keywords.yaml}` with starter content from the design doc
- [x] 1.6 Create `tests/` skeleton: `tests/__init__.py`, `tests/fixtures/`, `tests/adapters/__init__.py`
- [x] 1.7 Update `.gitignore` to exclude `data/`, `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`
- [x] 1.8 Update `README.md` with one-paragraph project summary, install steps, and the `python -m job_market crawl` invocation
- [x] 1.9 Verify `pip install -e .[dev]` succeeds and `python -m job_market --help` prints (placeholder OK at this stage)

## 2. Adapter contract and core dataclasses

- [x] 2.1 In `adapters/base.py`, define `RawJob` dataclass (`source_url: str`, `payload: dict`)
- [x] 2.2 Define `NormalizedJob` dataclass with the full field list from the spec (`job_id`, `company`, `title`, `description`, `requirements`, `location`, `education`, `job_type`, `department`, `posted_at`, `source_url`, `raw_payload`)
- [x] 2.3 Define `CampusAdapter(ABC)` with class attrs `company: str`, `rate_limit_qps: float = 1.0`, abstract methods `list_jobs(fetcher)` and `normalize(raw)`
- [x] 2.4 Add a registry helper that discovers `CampusAdapter` subclasses under `adapters/` by import + subclass walk, keyed by `company`
- [x] 2.5 Write `tests/adapters/test_base.py` covering: subclass missing abstract methods raises, registry returns instances per `companies.yaml`

## 3. Fetcher: HTTP + rate limit + retry + robots

- [x] 3.1 Implement a per-host token-bucket rate limiter (thread-safe, default 1 QPS)
- [x] 3.2 Implement `Fetcher` wrapping `httpx.Client(http2=True)`; `get(url, **kw)` and `post(url, json=..., **kw)` go through the per-host limiter
- [x] 3.3 Add exponential-backoff retry (1s/2s/4s, max 3 attempts) for 5xx and `httpx.RequestError`; never retry 4xx
- [x] 3.4 Set the User-Agent to a real browser UA + `job-market-analysis/<version> (+contact)` suffix; document in README that this is non-spoofing identification
- [x] 3.5 Add a `check_robots(url) -> bool` helper using `urllib.robotparser`, with the response cached per host
- [x] 3.6 Write `tests/test_fetcher.py`: mocked transport that returns 503 then 200, asserts retry + backoff timing; per-host bucket spaces requests; 4xx returns immediately
- [x] 3.7 Write `tests/test_robots.py`: serves a small `robots.txt` from a fake transport, asserts allow/deny decisions

## 4. Classifier: tech-role filter + category + tech keywords

- [x] 4.1 Implement `load_categories(path) -> list[(name, [pattern...])]` preserving file order so first-match-wins works
- [x] 4.2 Implement `is_tech_role(title, description) -> bool` using a non-tech blacklist (产品, 运营, HR, 销售, 财务, 法务, 行政, 市场, 品牌, 客服, 采购) — case-insensitive substring match
- [x] 4.3 Implement `assign_category(title, description) -> str` iterating the loaded categories in order, falling back to `tech_other`
- [x] 4.4 Implement `extract_tech_keywords(text, keywords) -> list[str]` (case-insensitive substring, dedup, lowercased canonical form)
- [x] 4.5 Write `tests/test_classifier.py`: parametrized cases for is_tech_role (tech vs non-tech titles), assign_category (specific-before-general), tech_other fallback, keyword extraction (dedup, empty result is `[]` not None)

## 5. Normalizer: schema enforcement + parsing_error flagging

- [x] 5.1 Implement `normalize_record(adapter, raw) -> tuple[dict_row, parsing_error: bool]` that calls `adapter.normalize(raw)`, runs `is_tech_role`, runs `assign_category`, runs `extract_tech_keywords`, and assembles the final SQLite row
- [x] 5.2 Capture exceptions inside `adapter.normalize` and missing required fields (`job_id`, `title` empty); set `parsing_error=True` and populate what's available from `raw_payload`
- [x] 5.3 Drop non-tech rows here so they never reach storage; emit a counter so the pipeline summary can report `dropped_non_tech`
- [x] 5.4 Write `tests/test_normalizer.py`: happy path, normalize raises (parsing_error=True, raw retained), missing title (parsing_error=True), non-tech row (returns sentinel that pipeline drops)

## 6. Storage: SQLite + raw JSONL double-write

- [x] 6.1 Implement `Storage.__init__(db_path)` that creates the `jobs` table and the three indexes (`company`, `category`, `crawled_at`) idempotently
- [x] 6.2 Implement `Storage.upsert_jobs(rows)` using `INSERT OR REPLACE`, JSON-encoding `tech_keywords`, `location`, `raw_payload`
- [x] 6.3 Implement `Storage.write_raw(company, raw_jobs, run_date)` that writes/overwrites `data/raw/<run_date>/<company>.jsonl`, one JSON object per line, including `source_url` and `payload`
- [x] 6.4 Ensure raw write happens even when normalize fails (raw is the source of truth)
- [x] 6.5 Write `tests/test_storage.py`: schema creation, upsert replaces existing row by `job_id`, `crawled_at` updates on re-upsert, raw JSONL round-trip, indexes exist via `PRAGMA index_list`

## 7. Pipeline orchestration

- [x] 7.1 Implement `load_companies_config(path)` and apply `enabled` and `rate_limit_qps` overrides on adapter instances
- [x] 7.2 At pipeline start, fetch and parse robots.txt for each enabled adapter's host; skip any disallowed adapter and log the reason; continue with the rest
- [x] 7.3 Run companies in parallel via `ThreadPoolExecutor(max_workers=10)`; inside a company, drive `list_jobs()` serially through its rate limiter
- [x] 7.4 For each company, accumulate raw payloads, normalize each, classify each, drop non-tech, collect parsing errors; on any exception during `list_jobs`, log company-level failure and move on (sibling companies must continue)
- [x] 7.5 After all workers finish: batch upsert all normalized rows; write each company's raw JSONL; print per-company summary (fetched, kept, dropped_non_tech, parsing_errors, duration, error_class_if_any)
- [x] 7.6 Exit code: 0 if at least one company finished without environmental errors (per-company errors are reported, not fatal); non-zero only on config or environment failures
- [x] 7.7 Write `tests/test_pipeline.py`: 3 mocked adapters where one raises mid-run — assert other two persist correctly, summary reports the failure, exit 0; assert non-tech rows do not appear in DB; assert raw JSONL written for all three

## 8. CLI

- [x] 8.1 In `cli.py`, expose a `main(argv=None)` that parses subcommand `crawl` and optional `--config <path>`, `--db <path>`, `--raw-dir <path>` overrides; defaults match the design (`config/companies.yaml`, `data/jobs.db`, `data/raw/`)
- [x] 8.2 Wire `__main__.py` to call `cli.main()`
- [x] 8.3 Print the per-company summary table at end of run; on KeyboardInterrupt, write what's been collected so far and exit cleanly
- [x] 8.4 Add an integration-style `tests/test_cli.py` that monkeypatches the registry to a single fake adapter and asserts `python -m job_market crawl` produces a populated DB and JSONL

## 9. Concrete adapters (10 companies)

For each company below: discover the public 校招 listing endpoint via DevTools; capture one or two pages of real JSON into `tests/fixtures/<company>_jobs_p1.json` (de-PII'd); implement `list_jobs` (paged) and `normalize` against that fixture; write `tests/adapters/test_<company>.py` covering pagination loop, field mapping, and edge-case rows.

- [x] 9.1 ByteDance adapter (`adapters/bytedance.py`) + fixture + tests
- [x] 9.2 Alibaba adapter + fixture + tests
- [x] 9.3 Tencent adapter + fixture + tests
- [x] 9.4 Meituan adapter + fixture + tests
- [x] 9.5 JD adapter + fixture + tests
- [x] 9.6 NetEase adapter + fixture + tests
- [x] 9.7 Xiaomi adapter + fixture + tests
- [x] 9.8 Pinduoduo adapter + fixture + tests
- [x] 9.9 Baidu adapter + fixture + tests
- [x] 9.10 Huawei adapter — first attempt JSON API; if no public API surfaces after reasonable inspection, implement Playwright fallback inside this module with `playwright` lazy-imported. Document the choice in a top-of-file comment. Fixture + tests.

## 10. Configuration content

- [ ] 10.1 Populate `config/companies.yaml` with all 10 companies, each `enabled: true`, `rate_limit_qps: 1.0`
- [ ] 10.2 Populate `config/categories.yaml` with the 13-category dictionary from the design doc, ordered specific-before-general (algorithm, ai, … , client, tech_other implicit)
- [ ] 10.3 Populate `config/tech_keywords.yaml` with ~200 entries across languages (python/java/go/rust/c++/...), frameworks (spring, django, react, vue, pytorch, tensorflow, ...), cloud/infra (kubernetes, docker, aws, aliyun, ...), databases (mysql, postgres, redis, mongodb, ...), AI (llm, transformer, langchain, ...)
- [ ] 10.4 Add a non-tech blacklist file or inline list in classifier.py covering: 产品经理, 运营, HR/人力, 销售, 财务, 法务, 行政, 市场, 品牌, 客服, 采购, 设计师 (non-tech variants only — keep "UI/UX设计" if user later wants design-tech roles)

## 11. Trends notebook

- [ ] 11.1 Create `notebooks/trends.ipynb` with a setup cell that opens `data/jobs.db` read-only via `sqlite3` and loads the table into a pandas DataFrame
- [ ] 11.2 Cell 1 — overall summary: total rows, distinct companies, count per company table
- [ ] 11.3 Cell 2 — category × company stacked bar chart
- [ ] 11.4 Cell 3 — top 30 tech-keyword frequency (explode the JSON column, value_counts)
- [ ] 11.5 Cell 4 — location distribution pie (北京/上海/深圳/杭州/广州/其他)
- [ ] 11.6 Cell 5 — education distribution by category
- [ ] 11.7 Cell 6 — top-N subcategories where present
- [ ] 11.8 Add empty-data guards in each chart cell so an empty `jobs.db` renders "no data" instead of crashing
- [ ] 11.9 Restart-and-run-all locally to confirm all 6 charts render

## 12. Verification and acceptance

- [ ] 12.1 `ruff check src tests` clean
- [ ] 12.2 `pytest -q` all green
- [ ] 12.3 Run `python -m job_market crawl` end-to-end against live sites; confirm wall-clock ≤ 10 min, `data/jobs.db` populated, `data/raw/<today>/` contains 10 JSONL files (or N where N companies were robots-allowed)
- [ ] 12.4 For each company adapter, confirm ≥ 95% of fixture rows parse without `parsing_error=True`
- [ ] 12.5 Run the trends notebook end-to-end and confirm the 6 charts answer the user's macro questions intelligibly
- [ ] 12.6 Capture a short run log in `docs/` (date, per-company counts, any disabled-by-robots companies) — this is the v1 "snapshot record"
