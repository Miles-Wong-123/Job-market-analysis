## ADDED Requirements

### Requirement: Two-stage role classification

The system SHALL classify each fetched job in two stages. Stage 1, `is_tech_role(title, description) -> bool`, SHALL return `False` for any role whose title or description matches an explicit non-tech pattern (产品经理, 运营, HR, 销售, 财务, 法务, 行政, 市场, 品牌, 客服, 采购, and other non-technical role keywords). Stage 1 returning `False` MUST cause the job to be dropped before SQLite insert — non-tech rows SHALL NOT be persisted. Stage 2, `assign_category(title, description) -> str`, SHALL run only for jobs that passed Stage 1 and SHALL produce a category from the closed enum `algorithm | ai | backend | frontend | mobile | client | embedded | hardware | data | infra | security | qa | tech_other`. The fallback `tech_other` SHALL be used only when no category pattern matches; jobs labelled `tech_other` are persisted, not dropped.

#### Scenario: Non-tech role is dropped before storage
- **WHEN** the classifier sees a job titled "产品经理 - 校招"
- **THEN** `is_tech_role` returns `False`, the row is not written to the `jobs` table, and a counter increments tracking how many non-tech rows were filtered

#### Scenario: Tech role with no specific match falls to tech_other
- **WHEN** the classifier sees a tech role whose title and description match no entry in `categories.yaml`
- **THEN** `is_tech_role` returns `True`, `assign_category` returns `"tech_other"`, and the row is persisted

### Requirement: Category dictionary loaded from versioned YAML

The classifier SHALL load category patterns from `config/categories.yaml`, where each top-level key is a category name and its `patterns` list contains case-insensitive substrings to match against `title + description`. The match order SHALL follow the file order, with first-match-wins semantics so that more-specific categories listed earlier (e.g., `algorithm`) take precedence over more-general ones listed later (e.g., `backend`). Editing this file SHALL NOT require code changes.

#### Scenario: Specific category wins over a more general one
- **WHEN** `categories.yaml` lists `algorithm` before `backend`, and a job's title is "推荐算法工程师" (which matches both "推荐" → algorithm and "工程师" patterns under backend)
- **THEN** the assigned category is `algorithm`

#### Scenario: Pattern match is case-insensitive
- **WHEN** a job title contains the substring "Java工程师" while `categories.yaml` lists the pattern `java工程师` under `backend`
- **THEN** the row is categorized as `backend`

### Requirement: Tech keyword extraction from versioned dictionary

The system SHALL load a list of approximately 200 technical keywords (programming languages, frameworks, cloud platforms, databases, AI frameworks) from `config/tech_keywords.yaml`. For each persisted job, the system SHALL scan the concatenation of `title`, `description`, and `requirements` and produce a deduplicated list of matched keywords stored as JSON in the `tech_keywords` column. Matching SHALL be case-insensitive. The output list MAY be empty.

#### Scenario: Multiple keywords are extracted, deduplicated, and stored as JSON
- **WHEN** a job description contains "我们使用 Python、Pytorch 和 PyTorch 进行深度学习" and `tech_keywords.yaml` lists `python` and `pytorch`
- **THEN** the persisted row's `tech_keywords` column contains the JSON array `["python", "pytorch"]` (deduplicated, case-normalized)

#### Scenario: No matches yields an empty array, not NULL
- **WHEN** a job's text contains none of the keywords in the dictionary
- **THEN** the persisted row's `tech_keywords` column is the JSON array `[]`
