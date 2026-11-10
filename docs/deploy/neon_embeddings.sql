-- M8 (DRAFT, not run): passage embeddings on Neon. Run only after the owner's OK on the storage estimate (measured
-- locally with pg_total_relation_size: 219 MB at halfvec(1024), 111.5 MB at halfvec(512); see reports/retrieval.md).
-- In the Neon SQL Editor as neondb_owner. Then load the rows with the loader role and rerun neon_verify.sql.
-- The block after SET ROLE must stay identical to db/embeddings.sql (tests/test_retrieve.py checks it).

CREATE EXTENSION IF NOT EXISTS vector;
SELECT extversion FROM pg_extension WHERE extname = 'vector';  -- must be >= 0.8.0 (hnsw.iterative_scan)

SET ROLE scout_loader;
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
RESET ROLE;
