-- Passage embeddings for vector and hybrid retrieval (M8, scout/text/retrieve.py). Static DDL, idempotent; applied by
-- scout/text/embed.py with the loader role. The extension is created by the admin role (db/init/01-extensions.sql
-- locally; docs/deploy/neon_embeddings.sql on Neon); here it is only checked.
CREATE EXTENSION IF NOT EXISTS vector;

-- One row per (passage, model). Chunks are the text_passages rows (scout/text/passages.py), so keyword and vector
-- search rank the same units; chunk_text is exactly the text that was embedded (section, newline, body).
CREATE TABLE IF NOT EXISTS text_embeddings (
    doc_id        text NOT NULL,
    chunk_id      integer NOT NULL,
    model         text NOT NULL,
    model_version text NOT NULL,
    dim           integer NOT NULL CHECK (dim = 1024),
    chunk_text    text NOT NULL,
    text_sha256   text NOT NULL,
    embedding     halfvec(1024) NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_id, chunk_id, model)
    -- no foreign key to text_passages: passages.py rebuilds that table with TRUNCATE. embed.py deletes rows whose
    -- passage is gone and re-embeds rows whose text changed (text_sha256), and queries join text_passages.
);

-- HNSW, not IVFFlat: no training step on loaded data (IVFFlat's lists must be built after loading and re-tuned as the
-- table changes) and a better recall/speed trade-off; the slower build is minutes at 37k rows. Used for corpus-wide
-- queries; queries for one player filter on text_passages_player first and compute exact distances.
CREATE INDEX IF NOT EXISTS text_embeddings_hnsw ON text_embeddings USING hnsw (embedding halfvec_cosine_ops);

GRANT SELECT ON text_embeddings TO scout_reader;
