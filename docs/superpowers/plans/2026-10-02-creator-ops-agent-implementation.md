# Creator Ops Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally runnable Chinese-language creator operations Web app that cleans fictional creator data, ranks candidates, generates English outreach, requires human approval, reviews content, logs model cost, and runs a repeatable 20-case evaluation in mock or DeepSeek mode.

**Architecture:** Use one FastAPI process with server-rendered Jinja pages, small JSON/form endpoints, SQLite persistence, and SQLite FTS5 retrieval. Deterministic Python handles validation and filtering; one `LLMClient` switches between stable mock responses and DeepSeek Chat Completions, validates every result with Pydantic, retries once, and records safe run metadata.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Jinja2, Pydantic, HTTPX, python-multipart, SQLite, pytest, HTML, CSS, vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-10-02-creator-ops-agent-design.md`

## Global Constraints

- The internal UI is Chinese; generated outreach email and collaboration brief are English.
- `LLM_PROVIDER=mock` is the safe default and must run without an API key.
- `LLM_PROVIDER=deepseek` uses `deepseek-flash` at `https://api.deepseek.com` with `DEEPSEEK_API_KEY` read only from the environment.
- The first version never sends real email, scrapes social platforms, stores real customer data, or performs an external action automatically.
- Use SQLite FTS5 for retrieval; do not add a vector database, task queue, cache server, React, or multi-agent framework.
- All model results must pass Pydantic validation; retry once, then record the failure without changing approval state or overwriting valid data.
- Uploaded CSV files must be `.csv`, at most 1 MiB, and validated row by row.
- All HTML output remains escaped by Jinja; do not mark user or model text as safe HTML.
- `./run.sh` initializes the environment and database, seeds fictional data, and starts the app.
- Every task follows red-green-refactor and ends with its listed focused test plus the accumulated suite.

## File Map

```text
creator-agent-demo/
├── app/
│   ├── __init__.py                 # Package marker
│   ├── config.py                   # Environment-backed settings and prices
│   ├── db.py                       # SQLite connection, migrations, seed entry point
│   ├── schema.sql                  # Tables and FTS5 schema
│   ├── models.py                   # Pydantic request/result models
│   ├── campaigns.py                # Campaign reads and updates
│   ├── creators.py                 # CSV parsing, validation, deduplication, filters
│   ├── matching.py                 # Eligibility rules and rule score
│   ├── retrieval.py                # FTS5 indexing and top-three retrieval
│   ├── llm.py                      # Mock/DeepSeek calls, validation, retry, run logs
│   ├── outreach.py                 # Draft generation and approval transition
│   ├── reviews.py                  # Delivery content review persistence
│   ├── evaluation.py               # Twenty-case repeatable evaluation
│   ├── main.py                     # FastAPI wiring and page/action routes
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── campaign.html
│   │   ├── creators.html
│   │   ├── matching.html
│   │   ├── workflow.html
│   │   └── logs.html
│   └── static/
│       ├── app.css
│       └── app.js
├── data/
│   ├── creators.csv                # Thirty fictional creator rows
│   ├── knowledge.json              # Product facts and collaboration rules
│   └── evaluation_cases.json       # Ten matching and ten review cases
├── docs/
│   ├── PROJECT_GUIDE_CN.md
│   ├── DEMO_SCRIPT_CN.md
│   ├── INTERVIEW_QA_CN.md
│   ├── GITHUB_AND_RESUME_CN.md
│   └── superpowers/...
├── tests/
│   ├── conftest.py
│   ├── test_bootstrap.py
│   ├── test_campaigns.py
│   ├── test_creators.py
│   ├── test_matching.py
│   ├── test_retrieval.py
│   ├── test_llm.py
│   ├── test_outreach.py
│   ├── test_reviews.py
│   └── test_evaluation.py
├── .env.example
├── .gitignore
├── requirements.txt
├── run.sh
└── README.md
```

---

### Task 1: Runnable App, Settings, and Database Bootstrap

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `run.sh`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/schema.sql`
- Create: `app/db.py`
- Create: `app/main.py`
- Create: `tests/conftest.py`
- Create: `tests/test_bootstrap.py`

**Interfaces:**
- Produces: `Settings.from_env() -> Settings`
- Produces: `connect(path: Path) -> sqlite3.Connection`
- Produces: `init_db(conn: sqlite3.Connection) -> None`
- Produces: FastAPI `app` and `GET /health`

- [ ] **Step 1: Write the failing bootstrap test**

```python
def test_health_and_schema(client, db):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "llm_provider": "mock"}
    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"campaigns", "creators", "matches", "drafts", "content_reviews", "knowledge_docs", "model_runs"} <= tables
```

- [ ] **Step 2: Run the test and verify the package does not exist**

Run: `python3 -m pytest tests/test_bootstrap.py -v`

Expected: FAIL during import because `app.main` has not been created.

- [ ] **Step 3: Add dependencies and environment settings**

Create `requirements.txt` with FastAPI, Uvicorn, Jinja2, Pydantic, HTTPX, python-multipart, and pytest. Implement an immutable `Settings` dataclass with `db_path`, `llm_provider`, `deepseek_api_key`, `deepseek_base_url`, `deepseek_model`, `request_timeout_seconds`, `max_upload_bytes`, and current Flash input/output prices. `from_env()` defaults to a project-local `data/app.db`, mock mode, a 20-second timeout, and a 1 MiB upload limit.

```python
@dataclass(frozen=True)
class Settings:
    db_path: Path
    llm_provider: Literal["mock", "deepseek"] = "mock"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    request_timeout_seconds: float = 20.0
    max_upload_bytes: int = 1_048_576
    input_price_per_million: float = 0.30
    output_price_per_million: float = 1.20
```

- [ ] **Step 4: Add the schema and database helpers**

Create the seven tables from the spec with foreign keys enabled. Store JSON lists as TEXT. Add unique indexes on `(platform, normalized_handle)` and `(campaign_id, creator_id)`. Add `knowledge_docs_fts` as an FTS5 table linked by document id.

```python
def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
```

- [ ] **Step 5: Add the FastAPI lifecycle and health route**

Create `create_app(settings: Settings | None = None) -> FastAPI`. Initialize one connection per request through a dependency, and initialize the configured database at startup. Return the configured provider from `/health`.

- [ ] **Step 6: Add local bootstrap files**

`.gitignore` must exclude `.venv/`, `.env`, `*.db`, `__pycache__/`, `.pytest_cache/`, and macOS metadata. `.env.example` must contain only safe example names. `run.sh` creates `.venv` when absent, installs `requirements.txt`, initializes through app startup, and runs Uvicorn on `127.0.0.1:8000`.

- [ ] **Step 7: Run focused and accumulated tests**

Run: `python3 -m pytest tests/test_bootstrap.py -v`

Expected: PASS.

Run: `python3 -m pytest -q`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .gitignore .env.example run.sh app tests
git commit -m "feat: bootstrap creator ops app"
```

---

### Task 2: Demo Campaign and Editable Brief

**Files:**
- Create: `app/models.py`
- Create: `app/campaigns.py`
- Create: `app/templates/base.html`
- Create: `app/templates/campaign.html`
- Modify: `app/db.py`
- Modify: `app/main.py`
- Create: `tests/test_campaigns.py`

**Interfaces:**
- Produces: `CampaignInput` and `Campaign`
- Produces: `seed_demo_campaign(conn) -> int`
- Produces: `get_campaign(conn, campaign_id: int) -> Campaign`
- Produces: `update_campaign(conn, campaign_id: int, data: CampaignInput) -> Campaign`

- [ ] **Step 1: Write failing campaign tests**

```python
def test_demo_campaign_is_seeded_and_editable(client, db):
    row = db.execute("SELECT * FROM campaigns").fetchone()
    assert row["name"] == "LumaSip 美国创作者启动项目"
    response = client.post(
        f"/campaigns/{row['id']}",
        data={
            "brand": "LumaSip",
            "name": "LumaSip 秋季项目",
            "market": "US",
            "language": "English",
            "platforms": "TikTok,YouTube",
            "categories": "fitness,tech",
            "min_followers": "20000",
            "max_followers": "500000",
            "max_fee": "1200",
            "total_budget": "6000",
            "deadline": "2026-11-15",
            "deliverables": "1 short video; profile link for 7 days",
            "restrictions": "No medical claims; include #ad",
            "brief_text": "Launch a smart hydration bottle for active US consumers.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert db.execute("SELECT name FROM campaigns WHERE id = ?", (row["id"],)).fetchone()[0] == "LumaSip 秋季项目"
```

- [ ] **Step 2: Run the focused test**

Run: `python3 -m pytest tests/test_campaigns.py -v`

Expected: FAIL because the campaign service and route do not exist.

- [ ] **Step 3: Implement models and seed data**

Use Pydantic field constraints for follower counts, budgets, deadline, and non-empty names. Seed the fictional LumaSip campaign only when `campaigns` is empty. The product facts are a 14-day battery, hydration reminders, and IPX7 water resistance; the campaign forbids medical claims.

- [ ] **Step 4: Implement read/update functions and route**

Persist comma-separated form fields as normalized JSON arrays. Reject invalid dates and negative numeric values with a 422 response. Redirect back to the campaign page after a successful update.

- [ ] **Step 5: Add the base layout and campaign form**

`base.html` contains Chinese navigation, a visible `mock` or `deepseek` badge, and a main content block. `campaign.html` renders every required field, uses normal labels, and displays validation errors without losing entered values.

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/test_campaigns.py -v && python3 -m pytest -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app tests/test_campaigns.py
git commit -m "feat: add editable campaign brief"
```

---

### Task 3: Fictional Creator CSV Import, Validation, and Deduplication

**Files:**
- Create: `app/creators.py`
- Create: `app/templates/creators.html`
- Create: `data/creators.csv`
- Modify: `app/main.py`
- Create: `tests/test_creators.py`

**Interfaces:**
- Produces: `CreatorRow`, `ImportIssue`, and `ImportSummary`
- Produces: `parse_creator_csv(data: bytes, today: date) -> ImportSummary`
- Produces: `upsert_creators(conn, summary: ImportSummary) -> ImportSummary`
- Produces: `list_creators(conn, filters: CreatorFilters) -> list[sqlite3.Row]`

- [ ] **Step 1: Write failing parser and deduplication tests**

```python
def test_csv_reports_duplicate_missing_and_stale_rows(db):
    payload = b"""name,platform,handle,country,category,followers,engagement_rate,estimated_fee,currency,language,email,source,source_updated_at,notes
Maya Lee,TikTok,@mayamoves,US,fitness,85000,4.8,900,USD,English,maya@example.test,demo,2026-09-20,Strong video hooks
Maya New,TikTok,mayamoves,US,fitness,91000,5.0,950,USD,English,,demo,2026-09-25,Updated quote
No Handle,TikTok,,US,fitness,20000,3.2,400,USD,English,nobody@example.test,demo,2026-09-20,
Old Quote,YouTube,@oldquote,US,tech,40000,3.9,700,USD,English,old@example.test,demo,2025-01-01,
"""
    summary = parse_creator_csv(payload, date(2026, 10, 2))
    assert summary.valid_count == 2
    assert summary.duplicate_count == 1
    assert {issue.code for issue in summary.issues} == {"missing_handle", "stale_quote"}
    upsert_creators(db, summary)
    creator = db.execute("SELECT * FROM creators WHERE normalized_handle = 'mayamoves'").fetchone()
    assert creator["name"] == "Maya New"
    assert creator["email"] == "maya@example.test"
```

- [ ] **Step 2: Run the focused test**

Run: `python3 -m pytest tests/test_creators.py -v`

Expected: FAIL because `app.creators` does not exist.

- [ ] **Step 3: Implement strict CSV parsing**

Require the exact header names shown in the test. Normalize platform to title case and handle by trimming whitespace and a leading `@`, then lowering it. Parse followers as integer, rates and fees as decimals, and dates as ISO dates. Mark quotes older than 365 days as stale. A missing platform, handle, country, fee, or update date makes a row invalid.

- [ ] **Step 4: Implement deterministic duplicate merge**

Group by normalized platform and handle. Choose the row with the newest `source_updated_at` as primary. For each empty field on the primary row, copy the newest non-empty value from the group. Record one duplicate for each extra row. Use `INSERT ... ON CONFLICT(platform, normalized_handle) DO UPDATE` without replacing stored non-empty values with empty input.

- [ ] **Step 5: Create the thirty-row fictional dataset**

Use US, UK, and Canada creators on TikTok, YouTube, and Instagram across fitness, tech, lifestyle, beauty, gaming, and food. Include 12 plausible LumaSip candidates, one duplicated handle with a newer quote, one missing handle, one missing fee, one stale quote, and creators intentionally excluded by market, platform, follower count, or budget. Use the reserved `.test` email domain and fictional handles.

- [ ] **Step 6: Add upload and list routes**

Reject non-CSV filenames and bodies over 1 MiB before parsing. Show the import summary, issues with row numbers, filters, source, updated date, and data-quality badge. Never render raw CSV as HTML.

- [ ] **Step 7: Run tests**

Run: `python3 -m pytest tests/test_creators.py -v && python3 -m pytest -q`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add app/creators.py app/templates/creators.html app/main.py data/creators.csv tests/test_creators.py
git commit -m "feat: import and clean creator data"
```

---

### Task 4: Eligibility Rules and Transparent Rule Scoring

**Files:**
- Create: `app/matching.py`
- Create: `app/templates/matching.html`
- Modify: `app/main.py`
- Create: `tests/test_matching.py`

**Interfaces:**
- Consumes: `Campaign`, creator database rows
- Produces: `EligibilityResult(eligible: bool, reasons: list[str])`
- Produces: `RuleMatch(creator_id: int, score: int, notes: list[str])`
- Produces: `check_eligibility(campaign: Campaign, creator: Mapping[str, Any]) -> EligibilityResult`
- Produces: `score_creator(campaign: Campaign, creator: Mapping[str, Any]) -> RuleMatch`
- Produces: `refresh_rule_matches(conn, campaign_id: int) -> list[RuleMatch]`

- [ ] **Step 1: Write failing eligibility and score tests**

```python
def test_hard_requirements_exclude_over_budget_creator(campaign, creator):
    creator["estimated_fee"] = 1500
    result = check_eligibility(campaign, creator)
    assert result.eligible is False
    assert "报价超过单人预算" in result.reasons

def test_category_mismatch_lowers_score_without_excluding(campaign, creator):
    matched = score_creator(campaign, {**creator, "category": "food"})
    aligned = score_creator(campaign, {**creator, "category": "fitness"})
    assert matched.score < aligned.score
    assert "类别非优先" in matched.notes
```

- [ ] **Step 2: Run the focused test**

Run: `python3 -m pytest tests/test_matching.py -v`

Expected: FAIL because matching functions do not exist.

- [ ] **Step 3: Implement eligibility**

Reject a creator when market, platform, follower range, budget, or required field validity fails. Return every failure reason instead of stopping at the first.

- [ ] **Step 4: Implement the public 100-point score**

Use fixed weights: market 20, platform 15, preferred category 20, follower fit 15, engagement 15, and budget headroom 15. Eligible creators always receive market and platform points. Scale follower fit by distance from the midpoint, engagement from 0 to 6 percent, and budget headroom from 0 to the campaign maximum. Clamp the final integer score to 0 through 100.

- [ ] **Step 5: Persist and render rule matches**

Rebuild current campaign matches transactionally. Store ineligible reasons but do not pass those rows to later model ranking. The page shows the scoring weights, eligible candidates, excluded candidates, reasons, and a “运行 AI 解释排序” action.

- [ ] **Step 6: Run tests and commit**

Run: `python3 -m pytest tests/test_matching.py -v && python3 -m pytest -q`

Expected: all tests pass.

```bash
git add app/matching.py app/templates/matching.html app/main.py tests/test_matching.py
git commit -m "feat: add transparent creator matching rules"
```

---

### Task 5: Explainable FTS5 Retrieval

**Files:**
- Create: `app/retrieval.py`
- Create: `data/knowledge.json`
- Modify: `app/db.py`
- Create: `tests/test_retrieval.py`

**Interfaces:**
- Produces: `KnowledgeHit(id: int, title: str, source_label: str, text: str, rank: float)`
- Produces: `seed_knowledge(conn, path: Path) -> int`
- Produces: `search_knowledge(conn, query: str, limit: int = 3) -> list[KnowledgeHit]`

- [ ] **Step 1: Write the failing retrieval test**

```python
def test_retrieval_returns_product_and_disclosure_sources(db):
    seed_knowledge(db, Path("data/knowledge.json"))
    hits = search_knowledge(db, "hydration bottle medical claims #ad", limit=3)
    assert len(hits) == 3
    labels = {hit.source_label for hit in hits}
    assert "LumaSip 产品事实" in labels
    assert "美国创作者披露规范" in labels
```

- [ ] **Step 2: Run the focused test**

Run: `python3 -m pytest tests/test_retrieval.py -v`

Expected: FAIL because retrieval does not exist.

- [ ] **Step 3: Add six compact knowledge documents**

Create documents for LumaSip product facts, US creator disclosure, outreach tone, content delivery checklist, prohibited medical claims, and campaign reporting fields. Product facts must state 14-day battery, hydration reminders, and IPX7 water resistance. Content rules must require `#ad`, a visible product in the first five seconds, a profile link for seven days, and no health-treatment claims.

- [ ] **Step 4: Implement FTS5 indexing and safe queries**

Insert or replace each JSON document and mirror it in `knowledge_docs_fts`. Convert the query into quoted alphanumeric tokens joined with `OR`; if tokenization produces no term, return an empty list. Use `bm25()` order and always cap results at three for model context.

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m pytest tests/test_retrieval.py -v && python3 -m pytest -q`

Expected: all tests pass.

```bash
git add app/retrieval.py app/db.py data/knowledge.json tests/test_retrieval.py
git commit -m "feat: add explainable knowledge retrieval"
```

---

### Task 6: Mock and DeepSeek Structured Model Calls with Safe Logging

**Files:**
- Create: `app/llm.py`
- Modify: `app/models.py`
- Create: `tests/test_llm.py`

**Interfaces:**
- Produces: `MatchExplanation`, `OutreachDraftResult`, and `ContentReviewResult`
- Produces: `LLMClient(settings: Settings, conn: sqlite3.Connection, transport: httpx.BaseTransport | None = None)`
- Produces: `LLMClient.rank_creator(...) -> MatchExplanation`
- Produces: `LLMClient.generate_outreach(...) -> OutreachDraftResult`
- Produces: `LLMClient.review_content(...) -> ContentReviewResult`

- [ ] **Step 1: Write failing mock, validation, retry, and cost tests**

```python
def test_mock_match_is_deterministic_and_logged(db, settings):
    client = LLMClient(settings, db)
    first = client.rank_creator(CAMPAIGN, CREATOR, KNOWLEDGE)
    second = client.rank_creator(CAMPAIGN, CREATOR, KNOWLEDGE)
    assert first == second
    assert 0 <= first.score <= 100
    assert db.execute("SELECT COUNT(*) FROM model_runs").fetchone()[0] == 2

def test_deepseek_retries_one_invalid_json_response(db, deepseek_settings):
    transport = SequenceTransport([
        httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}], "usage": {}}),
        httpx.Response(200, json=VALID_MATCH_RESPONSE),
    ])
    result = LLMClient(deepseek_settings, db, transport).rank_creator(CAMPAIGN, CREATOR, KNOWLEDGE)
    assert result.score == 88
    assert transport.calls == 2
```

- [ ] **Step 2: Run the focused test**

Run: `python3 -m pytest tests/test_llm.py -v`

Expected: FAIL because the model client does not exist.

- [ ] **Step 3: Define strict output models**

Forbid extra fields. Require scores from 0 to 100, non-empty English subject/body for outreach, lists of short strings for evidence and risks, and source labels copied from supplied knowledge hits.

- [ ] **Step 4: Implement stable mock behavior**

Derive mock match scores from the rule score and category alignment. Generate English outreach containing the creator name, LumaSip, deliverables, disclosure, and a request to confirm availability and quote. Review content using deterministic checks for `#ad`, product mention, forbidden medical terms, link mention, and timing metadata. The mock path must return the same result for the same input.

- [ ] **Step 5: Implement DeepSeek Chat Completions**

POST to `/chat/completions` with model `deepseek-flash`, `stream: false`, and `response_format: {"type": "json_object"}`. Set system prompts that demand only the documented JSON shape and prohibit unsupported facts. Include at most three retrieved passages with source labels. Retry once on HTTP errors, JSON decoding errors, or Pydantic validation errors.

- [ ] **Step 6: Log safe metadata and cost**

Use the response `usage.prompt_tokens` and `usage.completion_tokens`. Compute `(input_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price)`. Log success or an error class plus a short sanitized message. Never log authorization headers, API keys, full prompts, or full generated bodies.

- [ ] **Step 7: Run tests and commit**

Run: `python3 -m pytest tests/test_llm.py -v && python3 -m pytest -q`

Expected: all tests pass.

```bash
git add app/llm.py app/models.py tests/test_llm.py
git commit -m "feat: integrate mock and DeepSeek model calls"
```

---

### Task 7: AI Ranking, Outreach Drafts, and Human Approval

**Files:**
- Create: `app/outreach.py`
- Create: `app/templates/workflow.html`
- Modify: `app/matching.py`
- Modify: `app/main.py`
- Create: `tests/test_outreach.py`

**Interfaces:**
- Consumes: eligible `matches`, `LLMClient`, and `search_knowledge`
- Produces: `rank_eligible_matches(conn, campaign_id: int, llm: LLMClient) -> int`
- Produces: `create_outreach_draft(conn, campaign_id: int, creator_id: int, llm: LLMClient) -> int`
- Produces: `approve_draft(conn, draft_id: int) -> None`

- [ ] **Step 1: Write failing ranking and approval tests**

```python
def test_only_eligible_creators_are_ranked(db, mock_llm, seeded_campaign):
    refresh_rule_matches(db, seeded_campaign)
    count = rank_eligible_matches(db, seeded_campaign, mock_llm)
    eligible = db.execute("SELECT COUNT(*) FROM matches WHERE eligible = 1").fetchone()[0]
    ranked = db.execute("SELECT COUNT(*) FROM matches WHERE llm_score IS NOT NULL").fetchone()[0]
    assert count == eligible == ranked

def test_draft_requires_explicit_approval(db, mock_llm, selected_match):
    draft_id = create_outreach_draft(db, selected_match.campaign_id, selected_match.creator_id, mock_llm)
    assert db.execute("SELECT status FROM drafts WHERE id = ?", (draft_id,)).fetchone()[0] == "pending"
    approve_draft(db, draft_id)
    row = db.execute("SELECT status, approved_at FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row["status"] == "approved"
    assert row["approved_at"] is not None
```

- [ ] **Step 2: Run the focused test**

Run: `python3 -m pytest tests/test_outreach.py -v`

Expected: FAIL because ranking and outreach services do not exist.

- [ ] **Step 3: Implement AI ranking**

Retrieve relevant knowledge from the campaign brief, call the model once per eligible creator, and update only `llm_score`, explanation, evidence, and risks. If a call fails, preserve the rule result and store the safe error through `model_runs`.

- [ ] **Step 4: Implement draft creation and approval transition**

Only creators marked `selected = 1` can receive a draft. Save generated email and brief as `pending`. `approve_draft` accepts only pending drafts, changes the state to approved, and stamps UTC time. No route or service sends email.

- [ ] **Step 5: Render the matching and workflow pages**

Show separate rule and AI scores, source evidence, risks, a selection action, English subject/body in editable text areas, the current approval state, and a confirmation form that explicitly says it does not send email.

- [ ] **Step 6: Run tests and commit**

Run: `python3 -m pytest tests/test_outreach.py -v && python3 -m pytest -q`

Expected: all tests pass.

```bash
git add app/outreach.py app/matching.py app/main.py app/templates tests/test_outreach.py
git commit -m "feat: add AI ranking and approved outreach workflow"
```

---

### Task 8: Delivery Content Review

**Files:**
- Create: `app/reviews.py`
- Modify: `app/templates/workflow.html`
- Modify: `app/main.py`
- Create: `tests/test_reviews.py`

**Interfaces:**
- Produces: `ReviewSubmission(content: str, link: str | None, planned_publish_at: datetime | None)`
- Produces: `create_content_review(conn, campaign_id: int, submission: ReviewSubmission, llm: LLMClient) -> int`
- Produces: `get_content_review(conn, review_id: int) -> sqlite3.Row`

- [ ] **Step 1: Write the failing content-review test**

```python
def test_review_flags_missing_disclosure_and_medical_claim(db, mock_llm, seeded_campaign):
    review_id = create_content_review(
        db,
        seeded_campaign,
        ReviewSubmission(
            content="LumaSip cures dehydration. Link in profile.",
            link="https://example.test/lumasip",
            planned_publish_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        ),
        mock_llm,
    )
    result = json.loads(get_content_review(db, review_id)["result_json"])
    assert "missing_disclosure" in result["issue_labels"]
    assert "medical_claim" in result["issue_labels"]
```

- [ ] **Step 2: Run the focused test**

Run: `python3 -m pytest tests/test_reviews.py -v`

Expected: FAIL because review services do not exist.

- [ ] **Step 3: Implement review persistence and model call**

Require non-empty content with a 20,000-character maximum. Retrieve product and compliance documents, run the model review, and save supplied metadata plus structured JSON. A failed model call returns an error page and does not create a successful review row.

- [ ] **Step 4: Render readable review results**

Show passed checks, missing requirements, issue labels, risks, revision suggestions, and source labels as separate lists. Keep the original content escaped in a plain text block.

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m pytest tests/test_reviews.py -v && python3 -m pytest -q`

Expected: all tests pass.

```bash
git add app/reviews.py app/main.py app/templates/workflow.html tests/test_reviews.py
git commit -m "feat: review creator delivery content"
```

---

### Task 9: Repeatable Evaluation, Dashboard, and Model Logs

**Files:**
- Create: `app/evaluation.py`
- Create: `data/evaluation_cases.json`
- Create: `app/templates/dashboard.html`
- Create: `app/templates/logs.html`
- Modify: `app/main.py`
- Create: `tests/test_evaluation.py`

**Interfaces:**
- Produces: `EvaluationReport(match_hit_rate: float, issue_recall: float, schema_success_rate: float, average_latency_ms: float, estimated_cost_usd: float)`
- Produces: `run_evaluation(conn, llm: LLMClient, cases_path: Path) -> EvaluationReport`
- Produces: `dashboard_metrics(conn, campaign_id: int) -> dict[str, int | float]`

- [ ] **Step 1: Write the failing evaluation test**

```python
def test_mock_evaluation_is_repeatable_and_complete(db, mock_llm):
    first = run_evaluation(db, mock_llm, Path("data/evaluation_cases.json"))
    second = run_evaluation(db, mock_llm, Path("data/evaluation_cases.json"))
    assert first.match_hit_rate == second.match_hit_rate
    assert first.issue_recall == second.issue_recall
    assert first.schema_success_rate == second.schema_success_rate
    assert first.total_match_cases == 10
    assert first.total_review_cases == 10
    assert 0 <= first.match_hit_rate <= 1
    assert 0 <= first.issue_recall <= 1
    assert first.schema_success_rate == 1
```

- [ ] **Step 2: Run the focused test**

Run: `python3 -m pytest tests/test_evaluation.py -v`

Expected: FAIL because evaluation does not exist.

- [ ] **Step 3: Create exactly twenty fictional cases**

Matching cases cover: ideal US fitness TikTok, ideal US tech YouTube, budget exclusion, follower ceiling, wrong market, wrong platform, category mismatch, high-engagement alternative, stale data exclusion, and mixed fitness-tech campaign. Each stores a compact campaign, candidate list, and one or more expected handles in the top five.

Review cases expect these label sets: missing disclosure; medical claim; missing product mention; missing link; late publish time; missing disclosure plus medical claim; valid delivery with no labels; unsupported battery claim; missing visible-product requirement; and valid delivery with every required element.

- [ ] **Step 4: Implement metrics**

For matching, count a case as a hit when any expected handle appears in the top five after rule and mock/real model ranking. For review, calculate micro label recall as found expected labels divided by all expected labels. Count validated results for schema success, average recorded elapsed milliseconds, and sum estimated USD cost.

- [ ] **Step 5: Add dashboard and log pages**

Dashboard cards show total creators, eligible candidates, pending drafts, reviews with risks, recent model errors, and estimated cost. Logs show provider, model, purpose, status, tokens, elapsed time, and cost without prompts or secrets. The evaluation action clearly labels mock versus DeepSeek results.

- [ ] **Step 6: Run tests and commit**

Run: `python3 -m pytest tests/test_evaluation.py -v && python3 -m pytest -q`

Expected: all tests pass.

```bash
git add app/evaluation.py app/main.py app/templates data/evaluation_cases.json tests/test_evaluation.py
git commit -m "feat: add evaluation dashboard and model logs"
```

---

### Task 10: Responsive Presentation Layer and Final Documentation

**Files:**
- Create: `app/static/app.css`
- Create: `app/static/app.js`
- Modify: all `app/templates/*.html`
- Create: `README.md`
- Create: `docs/PROJECT_GUIDE_CN.md`
- Create: `docs/DEMO_SCRIPT_CN.md`
- Create: `docs/INTERVIEW_QA_CN.md`
- Create: `docs/GITHUB_AND_RESUME_CN.md`
- Modify: `tests/test_bootstrap.py`

**Interfaces:**
- Consumes: every implemented route and workflow
- Produces: finished local demo and candidate-facing learning materials

- [ ] **Step 1: Add a failing navigation smoke test**

```python
@pytest.mark.parametrize(
    "path, marker",
    [
        ("/", "项目总览"),
        ("/campaigns/1", "项目 Brief"),
        ("/creators", "创作者库"),
        ("/campaigns/1/matches", "智能匹配"),
        ("/campaigns/1/workflow", "沟通与交付"),
        ("/logs", "日志与评测"),
    ],
)
def test_demo_pages_render(client, path, marker):
    response = client.get(path)
    assert response.status_code == 200
    assert marker in response.text
```

- [ ] **Step 2: Run the smoke test**

Run: `python3 -m pytest tests/test_bootstrap.py::test_demo_pages_render -v`

Expected: FAIL for any missing route, template, or marker.

- [ ] **Step 3: Finish visual styling**

Use a restrained neutral palette with one lime accent inspired by the supplied recruitment sheet without copying its logo. Implement a fixed-width readable content column, responsive navigation, data cards, filter controls, status badges, tables that scroll on narrow screens, visible focus states, and `prefers-reduced-motion`. JavaScript is limited to confirmation prompts, file-name display, and small progressive enhancements; every core action remains a normal form submission.

- [ ] **Step 4: Write the README**

Document prerequisites, `./run.sh`, test command, mock mode, DeepSeek account/key setup, `.env` fields, price caveat, safe demo data, project structure, and a troubleshooting table for missing key, insufficient balance, timeout, invalid JSON, and occupied port.

- [ ] **Step 5: Write the project guide**

Explain the business problem, why hard filters precede the model, schema and data flow, why SQLite FTS5 is sufficient for this corpus, how human approval prevents unintended actions, how token cost is calculated, what the twenty cases prove, limitations, and the prioritized production upgrade path.

- [ ] **Step 6: Write the interview materials**

`DEMO_SCRIPT_CN.md` provides a timed five-minute path: 30-second context, 45-second data import, 60-second matching, 60-second outreach and approval, 45-second content review, 45-second logs/evaluation, and 60-second design trade-offs.

`INTERVIEW_QA_CN.md` answers at least: why this is more than an API wrapper; why not multi-agent; why FTS5 rather than vectors; how hallucinations are controlled; how failures are handled; how cost is measured; what changes for production; and how AI coding tools were verified.

`GITHUB_AND_RESUME_CN.md` includes a repository description, screenshot checklist, suggested pinned-repository text, and three truthful resume bullets that use only measured project results.

- [ ] **Step 7: Run the complete verification**

Run: `python3 -m pytest -q`

Expected: all tests pass.

Run: `LLM_PROVIDER=mock ./run.sh`

Expected: Uvicorn starts on `http://127.0.0.1:8000`; all six pages load and the end-to-end mock workflow completes.

- [ ] **Step 8: Commit**

```bash
git add app README.md docs tests/test_bootstrap.py
git commit -m "docs: finish creator ops demo and interview guide"
```

---

## Final Verification Checklist

- [ ] Run `python3 -m pytest -q` and record the exact pass count.
- [ ] Start with `LLM_PROVIDER=mock ./run.sh` from a clean database.
- [ ] Import `data/creators.csv` and verify duplicate, missing, and stale counts.
- [ ] Run deterministic matching and mock AI ranking.
- [ ] Generate one English email, confirm it remains pending, then approve it.
- [ ] Review one invalid and one valid delivery.
- [ ] Run all 20 evaluation cases twice and confirm identical mock metrics.
- [ ] Inspect every page at desktop and narrow viewport widths.
- [ ] Confirm `.env`, API keys, prompts, and real personal information are absent from Git status and model logs.
- [ ] Confirm README commands work in a fresh virtual environment.
