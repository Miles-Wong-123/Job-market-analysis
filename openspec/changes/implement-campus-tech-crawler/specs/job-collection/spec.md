## ADDED Requirements

### Requirement: Adapter contract for company-specific job sources

The system SHALL define an abstract `CampusAdapter` base class with two methods — `list_jobs(fetcher) -> Iterator[RawJob]` and `normalize(raw: RawJob) -> NormalizedJob` — and class attributes `company: str` and `rate_limit_qps: float`. Every concrete company source MUST be a subclass of `CampusAdapter` placed in `src/job_market/adapters/<company>.py`. Each adapter SHALL be self-contained: it owns pagination logic, query parameters, and field mapping for its company. Category assignment, tech-keyword extraction, and the `parsing_error` flag are NOT computed inside adapters — they are post-processed by the normalizer/classifier layers.

#### Scenario: Adding a new company requires only one adapter file
- **WHEN** a developer drops a new file `src/job_market/adapters/foo.py` defining `class FooAdapter(CampusAdapter)` and registers `foo` in `config/companies.yaml`
- **THEN** the pipeline picks it up on next run with no other code changes, and a failure inside `FooAdapter` does not affect the other companies' runs

#### Scenario: Adapter normalize output conforms to the shared dataclass
- **WHEN** an adapter's `normalize(raw)` returns a value
- **THEN** the value is an instance of `NormalizedJob` carrying `job_id`, `company`, `title`, `description`, `requirements`, `location`, `education`, `job_type`, `department`, `posted_at`, `source_url`, and `raw_payload`, with `job_id` formatted as `<company>:<原始ID>`

### Requirement: Concrete adapters for the ten target 大厂

The system SHALL ship concrete adapter implementations for ByteDance, Alibaba, Tencent, Meituan, JD, NetEase, Xiaomi, Pinduoduo, Baidu, and Huawei. Each adapter SHALL fetch from the company's official 校招 site only (no third-party aggregators) and target only public, non-login-walled endpoints. Adapters MAY fall back to a Playwright-driven flow only when no JSON endpoint can be discovered after reasonable investigation; Playwright SHALL be a lazy import so adapters that don't need it remain runnable without it.

#### Scenario: Each company adapter targets its official 校招 domain
- **WHEN** the pipeline starts an adapter for company X
- **THEN** all outbound HTTP requests for that adapter go to X's official 校招 host(s), and no requests target login-protected URLs or third-party aggregators

#### Scenario: Playwright is not required for JSON-API adapters
- **WHEN** a user installs the project without the optional `playwright` extra and runs the pipeline with all JSON-API adapters enabled
- **THEN** the pipeline runs to completion without raising `ImportError`, because Playwright is imported lazily only inside adapters that need it

### Requirement: Unified HTTP fetcher with per-host rate limiting and retries

The system SHALL provide a `Fetcher` that all adapters use for HTTP. The fetcher SHALL enforce a per-host token-bucket rate limit (default 1 QPS, configurable per adapter) and a global concurrency cap of ≤ 10 QPS across all hosts. The fetcher SHALL retry 5xx responses and network errors with exponential backoff at 1s, 2s, and 4s for at most 3 attempts; 4xx responses SHALL NOT be retried. The fetcher SHALL send a transparent `User-Agent` containing both a real browser UA string and a project identifier; it SHALL NOT spoof identity or otherwise circumvent anti-bot mechanisms.

#### Scenario: Per-host rate limit holds under bursts
- **WHEN** an adapter issues 5 requests in rapid succession to the same host with `rate_limit_qps=1.0`
- **THEN** the fetcher spaces the requests so that no host sees more than 1 request per second, while requests to other hosts proceed independently

#### Scenario: Transient 5xx triggers exponential backoff
- **WHEN** a host returns HTTP 503 on the first two attempts and 200 on the third
- **THEN** the fetcher waits 1s before retry 1, 2s before retry 2, and ultimately returns the 200 response; total attempts do not exceed 3

#### Scenario: 4xx is not retried
- **WHEN** a host returns HTTP 404
- **THEN** the fetcher returns the 404 response immediately without retry

### Requirement: robots.txt compliance at startup

The system SHALL fetch and parse the `robots.txt` for each enabled adapter's target host(s) at pipeline startup using the project's User-Agent. Any adapter whose listing endpoint is disallowed by `robots.txt` SHALL be skipped for that run, and the skip SHALL be recorded in the run log with the company name and the disallowing rule. The pipeline SHALL continue with the remaining allowed adapters.

#### Scenario: Disallowed adapter is skipped without aborting the run
- **WHEN** company X's `robots.txt` disallows the path the adapter would hit
- **THEN** that adapter is skipped, a log line records the reason, and the other companies' adapters still run to completion
