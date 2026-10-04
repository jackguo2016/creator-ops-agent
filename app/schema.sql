CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY,
    brand TEXT NOT NULL,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    language TEXT NOT NULL,
    platforms_json TEXT NOT NULL DEFAULT '[]',
    categories_json TEXT NOT NULL DEFAULT '[]',
    min_followers INTEGER NOT NULL DEFAULT 0 CHECK (min_followers >= 0),
    max_followers INTEGER NOT NULL DEFAULT 0 CHECK (max_followers >= min_followers),
    max_fee REAL NOT NULL DEFAULT 0 CHECK (max_fee >= 0),
    total_budget REAL NOT NULL DEFAULT 0 CHECK (total_budget >= 0),
    deadline TEXT NOT NULL,
    deliverables TEXT NOT NULL,
    restrictions TEXT NOT NULL,
    brief_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS creators (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    handle TEXT NOT NULL,
    normalized_handle TEXT NOT NULL,
    country TEXT NOT NULL,
    category TEXT NOT NULL,
    followers INTEGER NOT NULL CHECK (followers >= 0),
    engagement_rate REAL NOT NULL CHECK (engagement_rate >= 0),
    estimated_fee REAL NOT NULL CHECK (estimated_fee >= 0),
    currency TEXT NOT NULL,
    language TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    source_updated_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    data_quality_status TEXT NOT NULL DEFAULT 'valid',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_creators_platform_handle
ON creators(platform, normalized_handle);

CREATE INDEX IF NOT EXISTS idx_creators_filters
ON creators(country, platform, category);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    creator_id INTEGER NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
    eligible INTEGER NOT NULL DEFAULT 0,
    eligibility_reasons_json TEXT NOT NULL DEFAULT '[]',
    rule_score INTEGER,
    llm_score INTEGER,
    recommendation TEXT NOT NULL DEFAULT '',
    reasons_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    risks_json TEXT NOT NULL DEFAULT '[]',
    selected INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(campaign_id, creator_id)
);

CREATE INDEX IF NOT EXISTS idx_matches_campaign_state
ON matches(campaign_id, eligible, selected);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    creator_id INTEGER NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
    draft_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    brief TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_drafts_campaign_status
ON drafts(campaign_id, status);

CREATE TABLE IF NOT EXISTS content_reviews (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    submission_content TEXT NOT NULL,
    submission_link TEXT,
    planned_publish_at TEXT,
    result_json TEXT NOT NULL,
    human_status TEXT NOT NULL DEFAULT 'pending',
    status TEXT NOT NULL DEFAULT 'success',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_content_reviews_campaign
ON content_reviews(campaign_id, created_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_docs (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    body TEXT NOT NULL,
    source_label TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_docs_fts USING fts5(
    doc_id UNINDEXED,
    title,
    body,
    source_label UNINDEXED
);

CREATE TABLE IF NOT EXISTS model_runs (
    id INTEGER PRIMARY KEY,
    purpose TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    mode TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    elapsed_ms REAL NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_model_runs_status_created
ON model_runs(status, created_at DESC);

PRAGMA optimize;
