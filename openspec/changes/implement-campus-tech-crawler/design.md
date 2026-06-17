## Context

The user wants a one-shot snapshot of public 校招 (campus-recruitment) tech jobs from 10 大厂 (ByteDance, Alibaba, Tencent, Meituan, JD, NetEase, Xiaomi, Pinduoduo, Baidu, Huawei) for macro trend analysis. Background, scope, and legal boundaries are fixed in `docs/superpowers/specs/2026-06-17-job-market-crawler-design.md` and the brainstorming session that preceded it. This document records the *how* — the architecture and the technical decisions that shape the implementation.

Greenfield repo: only `docs/`, `openspec/`, and a top-level `README.md` exist today. No existing Python code to integrate with.

Constraints:
- Strictly public endpoints, robots.txt-respected, ≤ 1 QPS per host, ≤ 10 QPS global, no PII, no login-walled content, no anti-bot evasion.
- One-shot snapshot now, but schema and storage must work unchanged when (later) re-run periodically.
- User is solo dev — operational complexity must stay low (no Postgres, no message queue, no orchestrator).

## Goals / Non-Goals

**Goals:**
- A `python -m job_market crawl` command that, in ≤ 10 minutes, fetches public 校招 listings from all 10 enabled companies, drops non-tech roles, and writes a queryable `data/jobs.db` plus per-company raw JSONL.
- An adapter-per-company architecture where adding/replacing a company is one new file + one config-line change, and any single company's failure is isolated.
- A two-stage classifier whose dictionaries (`config/categories.yaml`, `config/tech_keywords.yaml`) can iterate without code changes.
- A Jupyter notebook (`notebooks/trends.ipynb`) that, on rerun, produces 6 charts answering the user's macro questions deterministically from `jobs.db`.
- Test coverage that lets the user re-run normalize/classify against saved fixtures without hitting any network.

**Non-Goals:**
- Cross-snapshot trend analysis, salary fields, third-party aggregators, social-recruitment, non-tech roles, login-required pages — all explicitly excluded by the design doc.
- A production scheduler or web UI; the deliverable is a CLI + notebook.
- LLM-based classification — out of scope for v1 to keep snapshots reproducible.
- Distributing or republishing the scraped data; this is private research only.

## Decisions

### D1. Adapter pattern, one module per company

Each company gets its own file under `src/job_market/adapters/<company>.py` implementing `CampusAdapter` with `list_jobs()` and `normalize()`. The pipeline iterates over enabled adapters, isolating failures. Considered alternatives:
- **Single generic crawler with per-company config** — rejected: each site's pagination, response shape, and edge cases differ enough that config-driven crawling becomes a half-built DSL.
- **One Scrapy spider per company** — rejected: Scrapy's middleware/scheduler complexity is overkill for 10 small sources behind a 1-QPS budget; we want to own the rate limiter and error model.

### D2. JSON-API first, Playwright only as last resort

Most 大厂 校招 sites are SPAs whose listing data comes from a JSON XHR endpoint discoverable via DevTools. Adapters target that JSON directly. For sites whose endpoint can't be discovered or is heavily obfuscated (Huawei is the suspected case), the adapter may fall back to Playwright in a single isolated module — `playwright` is then a *lazy* import so users without it can still run all the other adapters. Rejected: Playwright-everywhere, because it would multiply the runtime, the install footprint, and the chance of breakage on every CI run.

### D3. SQLite + raw-JSON double-write

Normalized rows go to SQLite (`data/jobs.db`); the original API payload for every fetch goes to `data/raw/YYYY-MM-DD/<company>.jsonl`. Why both:
- SQLite gives us SQL over normalized fields for the notebook with zero ops cost.
- Raw JSONL means normalization is replayable when an adapter's mapping turns out to have a bug — we don't have to re-hit the network to fix history.
- Considered Parquet for raw — rejected: JSONL is append-only, line-grep-friendly, and matches the streaming nature of the fetch loop.

### D4. Two-stage classification, drop non-tech before storage

`is_tech_role(title, description)` runs first; non-tech rows are dropped *before* SQLite insert (they pollute analysis and never get re-examined). Survivors then run `assign_category()` against `categories.yaml` patterns; misses fall to `tech_other` and stay in the table. Why drop early instead of `category="non_tech"`:
- The user explicitly does not care about non-tech roles, and storing them grows the DB ~3-5× with rows we never query.
- `tech_other` is the *escape hatch for tech jobs we couldn't sub-categorize*, not for "maybe non-tech" — keeping the two states separate prevents the bucket from rotting into "stuff we haven't looked at yet".

### D5. Pattern-based classifier, dictionary in YAML, versioned

Categories and tech keywords live in `config/*.yaml`, not in code. The classifier loads them once per run and matches case-insensitively over `title + description`. Why patterns over an LLM:
- Snapshots must be **reproducible**: re-running the same snapshot yesterday and today should give the same labels, which is hard to guarantee with a model that can drift between calls.
- Easier to debug a missed match — grep the YAML, add a word, rerun normalize against fixtures.
- LLM is slated as Future Work for subcategory extraction where dictionaries hit a wall.

Match precedence: most-specific category first. The YAML is ordered, and the matcher iterates top-to-bottom with first-match-wins (`algorithm` before `backend`, etc.). Documented in the spec; the order is part of the contract.

### D6. Concurrency model: thread pool across companies, serial within company

`ThreadPoolExecutor(max_workers=10)` runs one worker per company. Inside a company, the adapter loops pages serially under that company's `rate_limit_qps` (default 1.0). Why threads not asyncio:
- httpx supports both, but the bulk of work is I/O-bound waiting on remote endpoints; threads are fine and the code stays linear (no `await` everywhere, easier to read inside adapters).
- Total throughput cap of 10 QPS is enforced by per-host token buckets in the shared `Fetcher`, *not* by the executor — so even if some company's adapter parallelizes detail-page fetches in the future, the global bucket still bounds the rate.

### D7. Error isolation contract

Three failure layers:
1. **Per-request**: 5xx and network errors retry with exponential backoff (1s/2s/4s), max 3 attempts; 4xx never retries.
2. **Per-record**: a `normalize()` exception or a missing required field (`job_id`, `title`) sets `parsing_error=True`, keeps the row with raw payload intact, and continues.
3. **Per-company**: an adapter's `list_jobs()` raising kills only that company's run; the pipeline logs and moves on.

This three-layer model means a single bad row doesn't kill a company, a single bad company doesn't kill a snapshot, and the user can always diagnose because raw payloads survive.

### D8. robots.txt enforced at startup, not at request time

We fetch each company's `robots.txt` once on pipeline start, parse with `urllib.robotparser`, and refuse to enable any adapter whose target endpoint is disallowed for our UA. A clear log line (`[skipped] <company>: robots.txt disallows /...`) tells the user which companies were skipped. This is cheaper than per-request checks and makes the legal posture explicit.

### D9. Python ≥ 3.11, dataclasses for the contracts, pydantic only if needed

The adapter contract (`RawJob`, `NormalizedJob`) uses stdlib `@dataclass`. Pydantic adds validation we don't need at the adapter boundary — adapters already know their payload shape. We will pull pydantic in only if normalization/storage finds repeated boilerplate worth replacing.

## Risks / Trade-offs

- **API schema drift** → mitigated by raw-JSONL replay; whenever a company's `parsing_error` rate spikes, fix the normalizer and re-run against saved raw payloads.
- **Anti-bot countermeasures** (Cloudflare-style challenges) → not bypassed. If a company's public listing endpoint requires JS execution, that adapter falls to Playwright. If even Playwright is challenged, the adapter is disabled and reported, *not* worked around — it would cross the legal posture commitments.
- **Classification accuracy ceiling** → first-pass dictionary will miss specifics. `tech_other` is the safety valve and the iteration prompt; user reviews `tech_other` rows in the notebook and adds patterns to `categories.yaml`.
- **Huawei adapter complexity** → uncertainty around whether their public 校招 listing has a discoverable API. Built behind the same `CampusAdapter` interface; if Playwright fails too, it's disabled and the change still ships with 9/10 companies.
- **One-shot vs periodic** → `crawled_at` and SQLite primary-key design (`<company>:<id>`) already support periodic re-runs with `INSERT OR REPLACE` semantics. The notebook for v1 assumes a single snapshot but won't break if multiple snapshots accumulate.
- **Raw JSONL disk growth** → bounded by snapshot size (≈10 companies × ~2k jobs × ~5KB ≈ 100MB per snapshot). Acceptable for one-shot; if periodic mode is enabled later, add date-based pruning.

## Migration Plan

Greenfield project — no migration. To "deploy":
1. `pip install -e .[dev]`
2. (Optional, only if Huawei adapter falls back) `playwright install chromium`
3. `python -m job_market crawl` — produces `data/jobs.db` and `data/raw/<date>/`
4. `jupyter lab notebooks/trends.ipynb` → Run All

Rollback: delete `data/jobs.db` and re-run; raw JSONL is the source of truth.

## Open Questions

- **Huawei**: does their public 校招 listing actually need Playwright, or is there a JSON endpoint hidden behind one of the static pages? Resolve during adapter implementation; if no API surfaces in 30 min of inspection, fall to Playwright.
- **Subcategory extraction**: how aggressively to attempt rule-based subcategory ("推荐系统", "分布式存储", "大模型")? V1 fills `subcategory` only when a clear pattern matches and leaves it `NULL` otherwise; LLM-based extraction is Future Work.
- **Rate limit defaults per host**: 1 QPS is conservative. May relax to 2 QPS once we observe response times in practice; not changed for v1.
