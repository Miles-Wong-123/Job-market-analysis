## ADDED Requirements

### Requirement: Trends notebook reads exclusively from jobs.db

The system SHALL ship `notebooks/trends.ipynb` that reads `data/jobs.db` and produces analysis charts entirely from that database. The notebook SHALL NOT make any network requests, SHALL NOT mutate the database, and SHALL run from a clean restart-and-run-all without manual intervention provided `data/jobs.db` exists.

#### Scenario: Notebook runs offline against a populated DB
- **WHEN** the user runs `Restart Kernel and Run All` on `notebooks/trends.ipynb` with `data/jobs.db` already populated by a prior crawl
- **THEN** every cell executes without error, no network call is made, and the notebook ends with all six charts rendered

### Requirement: Six fixed analytical views

The notebook SHALL produce, in order, the following six views:

1. **Overall summary**: total rows, companies covered, breakdown of count per company.
2. **Category × company stacked bar**: x-axis companies, y-axis row counts stacked by `category`.
3. **Top 30 tech-keyword frequency**: bar chart of the 30 most frequent values across all rows' `tech_keywords` JSON arrays.
4. **Location distribution pie**: rows grouped into 北京 / 上海 / 深圳 / 杭州 / 广州 / 其他.
5. **Education distribution by category**: stacked or grouped bar of 本科 / 硕士 / 博士 / 不限 within each category.
6. **Top-N subcategories**: ranked list/bar of the most-populated `subcategory` values where present.

Each view SHALL use the schema column names from the storage capability without renaming them in the notebook.

#### Scenario: All six views are produced and ordered
- **WHEN** the user runs the notebook against a non-empty `data/jobs.db`
- **THEN** the rendered notebook contains six chart cells in the order listed above, each labelled with its title

### Requirement: Notebook tolerates empty or partial data

The notebook SHALL handle edge cases without raising: an empty `jobs` table SHALL produce a clear "no data" message in each view rather than a stack trace; a category with zero rows SHALL be omitted from charts rather than rendered as a zero-height bar; a row with `tech_keywords = []` SHALL be excluded from the keyword-frequency view but counted in the others.

#### Scenario: Empty database renders informative placeholders
- **WHEN** the user runs the notebook against a `data/jobs.db` whose `jobs` table is empty
- **THEN** each view cell prints "no data" (or equivalent text) and the notebook completes with exit status 0
