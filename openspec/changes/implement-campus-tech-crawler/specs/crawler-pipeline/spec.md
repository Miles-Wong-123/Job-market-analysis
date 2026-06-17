## ADDED Requirements

### Requirement: CLI entry point runs the full snapshot

The system SHALL expose `python -m job_market crawl` as the canonical entry point. Running this command SHALL load `config/companies.yaml`, instantiate every enabled adapter, run the full pipeline (robots check → fetch → normalize → classify → filter → store + raw dump), and print a per-company summary (rows fetched, rows kept, rows dropped non-tech, rows with parsing_error, run duration). The command SHALL exit 0 on success even if individual companies failed (those failures are reported in the summary), and exit non-zero only on configuration or environment errors that prevent any work.

#### Scenario: Successful end-to-end run
- **WHEN** the user runs `python -m job_market crawl` with all 10 adapters enabled and reachable
- **THEN** the command exits 0, `data/jobs.db` contains rows for the 10 companies, `data/raw/<today>/` contains 10 JSONL files, and stdout shows a one-row-per-company summary table

#### Scenario: One company fails, the rest succeed
- **WHEN** one adapter raises an unhandled exception during `list_jobs()`
- **THEN** the failing company's summary line shows the error class and message, the other 9 companies' rows are still persisted, the raw JSONL files for the 9 successful companies are still written, and the command exits 0

### Requirement: Parallel companies, serialized within a company

The pipeline SHALL run companies in parallel using a `ThreadPoolExecutor` capped at 10 workers. Within each company, requests SHALL be serialized through that company's `rate_limit_qps` budget. Global throughput across all hosts SHALL be capped at ≤ 10 QPS by the shared fetcher's per-host token buckets, independent of how many companies are active.

#### Scenario: Two companies run concurrently
- **WHEN** the pipeline starts with two enabled adapters whose hosts are different
- **THEN** the two adapters' first requests are dispatched within the same wall-clock second, and each adapter's subsequent requests respect its own `rate_limit_qps`

### Requirement: Company-level error isolation

A pipeline run SHALL isolate failures at the company boundary. If `list_jobs()` or any other top-level adapter call raises, the pipeline SHALL log the company, the exception type, and the message; close any partial outputs cleanly; and continue executing the remaining companies. Per-record errors are governed by the storage capability's parsing_error contract, not by this requirement.

#### Scenario: An adapter exception does not affect siblings
- **WHEN** the Tencent adapter raises `RuntimeError("schema changed")` mid-run
- **THEN** the pipeline records the failure for Tencent, does not retry it within the same run, and the ByteDance/Alibaba/etc. adapters complete normally

### Requirement: Configuration-driven adapter enablement

The pipeline SHALL read `config/companies.yaml` to determine which adapters are active and their per-adapter overrides (at minimum `enabled: bool` and `rate_limit_qps: float`). Adding a new company to the YAML SHALL be sufficient to include it in the next run, provided the corresponding `<company>.py` exists under `src/job_market/adapters/`.

#### Scenario: Disabling a company in config skips its adapter
- **WHEN** `config/companies.yaml` sets `huawei.enabled: false`
- **THEN** the pipeline does not instantiate the Huawei adapter, does not fetch its robots.txt, and the summary reports 9 companies instead of 10
