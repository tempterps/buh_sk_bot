CREATE TABLE IF NOT EXISTS news_config (key TEXT PRIMARY KEY, value JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS news_sources (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT NOT NULL, priority SMALLINT NOT NULL CHECK(priority BETWEEN 1 AND 3), enabled BOOLEAN NOT NULL DEFAULT false,
 discovery_url TEXT NOT NULL, fallback_url TEXT, method TEXT NOT NULL CHECK(method IN ('rss','html')), topics TEXT[] NOT NULL DEFAULT '{}', last_success_at TIMESTAMPTZ,
 last_watermark TIMESTAMPTZ, etag TEXT, last_modified TEXT, last_error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS research_runs (
 id UUID PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ, status TEXT NOT NULL CHECK(status IN ('running','no_suitable_news','research_partial','research_failed','draft_created','budget_exhausted')),
 source_successes INTEGER NOT NULL DEFAULT 0, source_failures INTEGER NOT NULL DEFAULT 0, candidate_count INTEGER NOT NULL DEFAULT 0, error TEXT);
CREATE TABLE IF NOT EXISTS articles (
 id BIGSERIAL PRIMARY KEY, source_id TEXT NOT NULL REFERENCES news_sources(id), title TEXT NOT NULL, canonical_url TEXT NOT NULL, url_hash CHAR(64) NOT NULL UNIQUE,
 content_hash CHAR(64), published_at TIMESTAMPTZ, published_date_raw TEXT, categories TEXT[] NOT NULL DEFAULT '{}', summary TEXT, full_text TEXT, retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 processed_at TIMESTAMPTZ, retrieval_status TEXT NOT NULL DEFAULT 'discovered', UNIQUE(source_id, canonical_url));
CREATE TABLE IF NOT EXISTS topics (id BIGSERIAL PRIMARY KEY, topic_key TEXT NOT NULL UNIQUE, last_selected_at TIMESTAMPTZ, last_published_at TIMESTAMPTZ, summary TEXT);
CREATE TABLE IF NOT EXISTS drafts (
 id UUID PRIMARY KEY, article_id BIGINT REFERENCES articles(id), topic_id BIGINT REFERENCES topics(id), status TEXT NOT NULL CHECK(status IN ('pending','revision_requested','approved','rejected','expired','blocked')),
 current_version INTEGER NOT NULL DEFAULT 1, approval_expires_at TIMESTAMPTZ NOT NULL, revision_count INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS draft_versions (
 id BIGSERIAL PRIMARY KEY, draft_id UUID NOT NULL REFERENCES drafts(id) ON DELETE CASCADE, version INTEGER NOT NULL, content TEXT NOT NULL, content_hash CHAR(64) NOT NULL,
 evidence JSONB NOT NULL DEFAULT '{}'::jsonb, review JSONB NOT NULL DEFAULT '{}'::jsonb, review_passed BOOLEAN NOT NULL DEFAULT false, preview_message_id BIGINT, note_message_id BIGINT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(draft_id, version), UNIQUE(draft_id, content_hash));
CREATE TABLE IF NOT EXISTS approval_events (id BIGSERIAL PRIMARY KEY, draft_id UUID NOT NULL REFERENCES drafts(id), version INTEGER NOT NULL, event_type TEXT NOT NULL, actor_user_id BIGINT, actor_chat_id BIGINT, callback_ref TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), details JSONB NOT NULL DEFAULT '{}'::jsonb);
CREATE TABLE IF NOT EXISTS publication_outbox (id UUID PRIMARY KEY, draft_id UUID NOT NULL REFERENCES drafts(id), version INTEGER NOT NULL, content_hash CHAR(64) NOT NULL, status TEXT NOT NULL CHECK(status IN ('queued','claimed','previewed','sent','publication_unknown','cancelled')),
 claimed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(draft_id, version));
CREATE TABLE IF NOT EXISTS publications (id BIGSERIAL PRIMARY KEY, draft_id UUID NOT NULL, version INTEGER NOT NULL, content_hash CHAR(64) NOT NULL, channel_id TEXT NOT NULL, telegram_message_id BIGINT NOT NULL, published_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(draft_id, version), UNIQUE(channel_id, telegram_message_id));
CREATE TABLE IF NOT EXISTS model_usage_and_budget_reservations (id UUID PRIMARY KEY, run_id UUID REFERENCES research_runs(id), stage TEXT NOT NULL, model TEXT NOT NULL, month DATE NOT NULL,
 reserved_usd NUMERIC(12,6) NOT NULL, actual_usd NUMERIC(12,6), input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER, status TEXT NOT NULL CHECK(status IN ('reserved','reconciled','held','failed')), created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS articles_processed_idx ON articles(processed_at) WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS drafts_pending_idx ON drafts(status, approval_expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS one_news_research_run_idx ON research_runs ((1)) WHERE status='running';

