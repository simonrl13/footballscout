-- News tables (M2+). NOT dropped by db/schema.sql. Created idempotently by scout.news.store.ensure_schema().
-- Guardian rules (docs/SPEC.md): persist only IDs, URLs, dates, tags and extracted signals; never article text
-- beyond 24 hours (news_text_cache is purged; reads ignore anything older).

CREATE TABLE IF NOT EXISTS news_articles (
    article_id         text PRIMARY KEY,          -- Guardian content id, e.g. football/2019/aug/10/...
    url                text NOT NULL,
    section_id         text,
    published_at       timestamptz NOT NULL,      -- webPublicationDate
    first_published_at timestamptz,               -- fields.firstPublicationDate (point-in-time joins use this)
    last_modified      timestamptz,               -- fields.lastModified (edits after a snapshot are detectable)
    tags               jsonb NOT NULL DEFAULT '[]',  -- [{id, type, webTitle}] keyword/contributor tags
    ingested_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS news_articles_published ON news_articles (published_at);
CREATE INDEX IF NOT EXISTS news_articles_tags ON news_articles USING gin (tags jsonb_path_ops);

-- Article text, fetched live when an answer or citation needs it. Rows older than 24 h are never returned and are
-- deleted by scout.news.store.purge_text_cache().
CREATE TABLE IF NOT EXISTS news_text_cache (
    article_id text PRIMARY KEY,
    body       text NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now()
);

-- Daily Guardian API call budget, shared by every process.
CREATE TABLE IF NOT EXISTS guardian_api_calls (
    day   date PRIMARY KEY,
    calls integer NOT NULL DEFAULT 0
);

-- Resumable backfill: one row per calendar month.
CREATE TABLE IF NOT EXISTS news_backfill_progress (
    month       date PRIMARY KEY,
    next_page   integer NOT NULL DEFAULT 1,
    total_pages integer,
    done        boolean NOT NULL DEFAULT false,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
