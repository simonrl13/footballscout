"""Passage retrieval for search_text, one interface for every mode (M8, pre-registered 2026-10-29 in docs/RESEARCH_LOG.md).

RETRIEVAL_MODE (env, read per call; default keyword, the live demo's mode until the owner approves another):
- keyword: Postgres full-text search, the SQL search_text has always used.
- vector: cosine distance to the question embedded with Voyage (voyage-4-lite, 1024 dimensions, text_embeddings).
- hybrid: reciprocal rank fusion of the top FUSE_DEPTH keyword and vector results, score = sum of 1 / (k + rank).
- hybrid_rerank: the top RERANK_N fused results reranked by Voyage (rerank-2.5-lite).
Every mode returns rows with the same fields, so search_text's output contract doesn't change. Voyage is called over
REST with urllib (no SDK); the key comes from VOYAGE_API_KEY and is never logged. In vector modes the question text is
sent to Voyage (SECURITY.md).
"""
import json
import os
import urllib.request

MODES = ("keyword", "vector", "hybrid", "hybrid_rerank")
EMBED_MODEL, EMBED_DIM, RERANK_MODEL = "voyage-4-lite", 1024, "rerank-2.5-lite"
FUSE_DEPTH = 50  # results taken from each list before fusing
RRF_K, RERANK_N = 60, 20  # placeholders until the dev-split choice (pre-registered grid: k 10/30/60, N 10/20/30)
VOYAGE_URL = "https://api.voyageai.com/v1/"
USAGE = {"embed_tokens": 0, "rerank_tokens": 0}  # running totals for this process (eval cost per query)

KEYWORD_SQL = """
    SELECT p.player_id, dp.name, w.enwiki_title, p.section, p.body, d.url, d.available_at,
           ts_rank_cd(p.tsv, q) AS rank, p.doc_id, p.passage_no
    FROM text_passages p
    JOIN text_documents d USING (doc_id)
    JOIN wikidata_players w USING (player_id)
    JOIN demo_players dp USING (player_id),
         websearch_to_tsquery('english', %(q)s) q
    WHERE p.tsv @@ q AND (%(pid)s::int IS NULL OR p.player_id = %(pid)s::int)
    ORDER BY rank DESC, p.doc_id, p.passage_no
    LIMIT %(limit)s"""
# Two vector queries: one player's page is filtered first (MATERIALIZED) and ranked exactly; corpus-wide uses HNSW.
_VECTOR_COLS = """p.player_id, dp.name, w.enwiki_title, p.section, p.body, d.url, d.available_at, p.doc_id,
           p.passage_no, e.embedding <=> %(v)s::halfvec(1024) AS distance"""
_VECTOR_JOINS = """JOIN text_documents d ON d.doc_id = p.doc_id
    JOIN wikidata_players w ON w.player_id = p.player_id
    JOIN demo_players dp ON dp.player_id = p.player_id"""
VECTOR_PLAYER_SQL = f"""
    WITH page AS MATERIALIZED (SELECT * FROM text_passages WHERE player_id = %(pid)s::int)
    SELECT {_VECTOR_COLS}
    FROM page p
    JOIN text_embeddings e ON e.doc_id = p.doc_id AND e.chunk_id = p.passage_no AND e.model = %(model)s
    {_VECTOR_JOINS}
    ORDER BY distance, p.doc_id, p.passage_no
    LIMIT %(limit)s"""
VECTOR_ALL_SQL = f"""
    SELECT {_VECTOR_COLS}
    FROM text_embeddings e
    JOIN text_passages p ON p.doc_id = e.doc_id AND p.passage_no = e.chunk_id
    {_VECTOR_JOINS}
    WHERE e.model = %(model)s
    ORDER BY distance
    LIMIT %(limit)s"""


def mode() -> str:
    m = os.environ.get("RETRIEVAL_MODE", "keyword")
    if m not in MODES:
        raise ValueError(f"RETRIEVAL_MODE must be one of {', '.join(MODES)}")
    return m


def voyage(path: str, payload: dict) -> dict:
    req = urllib.request.Request(VOYAGE_URL + path, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def embed(texts: list[str], input_type: str) -> tuple[list[list[float]], int]:
    """Embeddings in input order, and the tokens Voyage counted."""
    out = voyage("embeddings", {"input": texts, "model": EMBED_MODEL, "input_type": input_type,
                                "output_dimension": EMBED_DIM})
    tokens = out["usage"]["total_tokens"]
    USAGE["embed_tokens"] += tokens
    return [d["embedding"] for d in sorted(out["data"], key=lambda d: d["index"])], tokens


def key(row: dict) -> tuple:
    return row["doc_id"], row["passage_no"]


def chunk_text(section: str | None, body: str) -> str:
    """What is embedded and reranked for a passage: its section name (as keyword search indexes it) and body."""
    return f"{section}\n{body}" if section else body


def rrf(rankings: list[list], k: int) -> list:
    """Reciprocal rank fusion: items ordered by sum of 1 / (k + rank) over the lists (rank from 1); ties keep the
    order of first appearance."""
    score, first = {}, {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            score[item] = score.get(item, 0.0) + 1.0 / (k + rank)
            first.setdefault(item, len(first))
    return sorted(score, key=lambda i: (-score[i], first[i]))


def keyword(conn, words: list[str], player_id: int | None, limit: int) -> list[dict]:
    return conn.execute(KEYWORD_SQL, {"q": " or ".join(words), "pid": player_id, "limit": limit}).fetchall()


def vector(conn, query: str, player_id: int | None, limit: int) -> list[dict]:
    [v], _ = embed([query], "query")
    params = {"v": str(v), "pid": player_id, "limit": limit, "model": EMBED_MODEL}
    if player_id is not None:
        return conn.execute(VECTOR_PLAYER_SQL, params).fetchall()
    # this transaction only: a candidate list >= FUSE_DEPTH (default 40), and keep scanning when the model filter
    # drops candidates (pgvector >= 0.8)
    conn.execute("SELECT set_config('hnsw.ef_search', '100', true), set_config('hnsw.iterative_scan', 'strict_order', true)")
    return conn.execute(VECTOR_ALL_SQL, params).fetchall()


def hybrid(conn, query: str, words: list[str], player_id: int | None, limit: int, k: int = RRF_K) -> list[dict]:
    lists = [keyword(conn, words, player_id, FUSE_DEPTH), vector(conn, query, player_id, FUSE_DEPTH)]
    rows = {key(r): r for rows in lists for r in rows}
    return [rows[i] for i in rrf([[key(r) for r in rows] for rows in lists], k)][:limit]


def rerank(query: str, rows: list[dict], limit: int) -> list[dict]:
    if not rows:
        return []
    out = voyage("rerank", {"query": query, "documents": [chunk_text(r["section"], r["body"]) for r in rows], "model": RERANK_MODEL,
                            "top_k": min(limit, len(rows))})
    USAGE["rerank_tokens"] += out["usage"]["total_tokens"]
    return [rows[d["index"]] for d in out["data"]]


def search(conn, query: str, words: list[str], player_id: int | None, limit: int, mode_: str | None = None,
           k: int = RRF_K, n: int = RERANK_N) -> list[dict]:
    """Passages for search_text: `query` is the text as asked (embedded in vector modes), `words` its plain words
    (keyword search)."""
    m = mode_ or mode()
    if m == "keyword":
        return keyword(conn, words, player_id, limit)
    if m == "vector":
        return vector(conn, query, player_id, limit)
    if m == "hybrid":
        return hybrid(conn, query, words, player_id, limit, k)
    return rerank(query, hybrid(conn, query, words, player_id, max(n, limit), k), limit)
