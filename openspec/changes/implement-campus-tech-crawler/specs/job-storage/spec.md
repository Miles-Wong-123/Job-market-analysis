## ADDED Requirements

### Requirement: SQLite jobs table with normalized schema

The system SHALL persist normalized tech jobs to a SQLite database at `data/jobs.db` in a table named `jobs` with the following columns: `job_id` (TEXT PRIMARY KEY, formatted `<company>:<原始ID>`), `company` (TEXT), `title` (TEXT), `category` (TEXT), `subcategory` (TEXT, nullable), `description` (TEXT), `requirements` (TEXT), `tech_keywords` (JSON-encoded TEXT), `location` (JSON-encoded TEXT), `education` (TEXT, nullable), `job_type` (TEXT, value in `校招` | `实习`), `department` (TEXT, nullable), `posted_at` (DATE, nullable), `crawled_at` (DATETIME, set on insert), `source_url` (TEXT), `raw_payload` (JSON-encoded TEXT), `parsing_error` (BOOLEAN). The system SHALL create indexes on `company`, `category`, and `crawled_at`.

#### Scenario: Schema is created on first run
- **WHEN** the pipeline starts and `data/jobs.db` does not exist
- **THEN** the system creates the file, the `jobs` table with all columns above, and the three indexes, all in a single setup transaction

#### Scenario: Re-running the pipeline updates rows in place
- **WHEN** the pipeline runs a second time and a job's `job_id` already exists in the table
- **THEN** the row is replaced via `INSERT OR REPLACE`, with `crawled_at` updated to the new run's timestamp

### Requirement: Raw payload double-write to dated JSONL

For every batch of fetches, the system SHALL also write each adapter's raw API responses (one record per job) to `data/raw/YYYY-MM-DD/<company>.jsonl`, where `YYYY-MM-DD` is the run's date. Each line SHALL be a JSON object containing at minimum `source_url` and the original `payload`. The directory SHALL be created if missing. This raw output SHALL be written even when normalization fails, so the snapshot can be re-normalized without re-hitting the network.

#### Scenario: Raw JSONL is written even when normalization fails
- **WHEN** an adapter fetches a job whose `normalize()` raises an exception
- **THEN** the corresponding raw response is still appended to `data/raw/<date>/<company>.jsonl` and the row is persisted with `parsing_error=True` and the available fields populated from `raw_payload`

#### Scenario: Re-running on the same day overwrites that day's raw file
- **WHEN** the pipeline is run twice on the same date for the same company
- **THEN** `data/raw/<date>/<company>.jsonl` reflects the latest run's responses (the file is rewritten, not appended across runs)

### Requirement: Per-record parsing error isolation

The system SHALL set `parsing_error=True` on any row where `normalize()` raised an exception OR where any of the required fields (`job_id`, `title`) are missing or empty after normalization. Such rows SHALL still be persisted with `raw_payload` intact so the user can repair normalization later. A single failing row SHALL NOT abort the company's batch.

#### Scenario: Missing required field flags but does not drop the row
- **WHEN** an adapter's normalize returns a `NormalizedJob` whose `title` is empty
- **THEN** the row is persisted with `parsing_error=True`, `raw_payload` populated, and the company's remaining records continue processing
