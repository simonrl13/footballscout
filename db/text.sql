-- Public-text tables, source-agnostic (M3). Created idempotently by scout.text.store.ensure_schema().
-- Sources are added per docs/SPEC.md (Wikipedia revisions, GDELT); each row carries its `source`.

-- 2026-10-01: the Guardian integration was removed (its terms prohibit AI-related use). Its tables were verified
-- empty (no article, text, link or API call was ever stored) and are dropped here.
DROP TABLE IF EXISTS news_signals, news_extractions, news_mentions, news_text_cache, news_backfill_progress,
    news_textpass_progress, guardian_api_calls, news_articles;

-- One row per document: a news item, or one encyclopedia revision. `available_at` is when the text became
-- public (first publication / revision timestamp); point-in-time joins use it.
CREATE TABLE IF NOT EXISTS text_documents (
    doc_id        text PRIMARY KEY,           -- e.g. "wikipedia:enwiki:rev:123456789"
    source        text NOT NULL,              -- wikipedia | gdelt | ...
    url           text NOT NULL,              -- link to the exact revision / article (attribution)
    available_at  timestamptz NOT NULL,
    last_modified timestamptz,
    meta          jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS text_documents_available ON text_documents (source, available_at);

-- Player mentions linked by scout.text.linker (offsets into the document text; -1 = linked from metadata).
CREATE TABLE IF NOT EXISTS text_mentions (
    doc_id         text NOT NULL REFERENCES text_documents (doc_id),
    player_id      integer NOT NULL,
    start_offset   integer NOT NULL,
    end_offset     integer NOT NULL,
    method         text NOT NULL,
    linker_version text NOT NULL,
    PRIMARY KEY (doc_id, player_id, start_offset, linker_version)
);
CREATE INDEX IF NOT EXISTS text_mentions_player ON text_mentions (player_id);

-- One row per (document, prompt version) processed by an LLM: the extraction cache key.
CREATE TABLE IF NOT EXISTS text_extractions (
    doc_id         text NOT NULL REFERENCES text_documents (doc_id),
    prompt_version text NOT NULL,
    model          text NOT NULL,
    status         text NOT NULL,             -- succeeded | errored | expired | canceled
    input_tokens   integer,
    output_tokens  integer,
    batch_id       text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_id, prompt_version)
);

-- Extracted signals; only the offsets of the verbatim-verified evidence quote are stored.
CREATE TABLE IF NOT EXISTS text_signals (
    doc_id         text NOT NULL,
    prompt_version text NOT NULL,
    player_id      integer NOT NULL,
    signal_type    text NOT NULL,             -- injury | transfer_rumour | contract | manager_change
    detail         text NOT NULL,
    evidence_start integer NOT NULL,
    evidence_end   integer NOT NULL,
    PRIMARY KEY (doc_id, prompt_version, player_id, signal_type, evidence_start),
    FOREIGN KEY (doc_id, prompt_version) REFERENCES text_extractions (doc_id, prompt_version)
);
