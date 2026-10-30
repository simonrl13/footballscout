"""Embeds the text_passages rows with Voyage for vector and hybrid retrieval (M8; scout/text/retrieve.py).

Idempotent and resumable: a passage is embedded only if it has no row for the model or its text changed
(text_sha256); rows whose passage is gone are deleted; each batch is committed. Uses the loader role. Embeddings are
derived data: the recipe (chunking, model, dimension, corpus hash) and every run's tokens and cost go to
data/embeddings_manifest.json.

Usage: uv run --env-file .env python -m scout.text.embed --count            (characters and passages to embed; no API)
       uv run --env-file .env python -m scout.text.embed --max-usd 0.20     (needs VOYAGE_API_KEY; owner's OK first)
"""
import argparse
import hashlib
import json
import time
import urllib.error

from scout.data.manifest import ROOT, git_commit
from scout.text import retrieve, store
from scout.text.passages import MAX_CHARS

MANIFEST = ROOT / "data" / "embeddings_manifest.json"
PRICE_PER_MTOK = 0.02  # voyage-4-lite, US$ per million tokens (docs.voyageai.com/docs/pricing, 2026-10-29)
BATCH = 128


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def pending(conn, model: str) -> tuple[list[tuple], int]:
    """(doc_id, chunk_id, chunk_text, sha) for passages to (re-)embed, and the number of passages in all."""
    have = dict(((d, c), h) for d, c, h in conn.execute(
        "SELECT doc_id, chunk_id, text_sha256 FROM text_embeddings WHERE model = %s", (model,)).fetchall())
    rows = conn.execute("SELECT doc_id, passage_no, section, body FROM text_passages ORDER BY doc_id, passage_no").fetchall()
    todo = []
    for d, c, section, body in rows:
        text = retrieve.chunk_text(section, body)
        if have.get((d, c)) != sha(text):
            todo.append((d, c, text, sha(text)))
    return todo, len(rows)


def corpus_hash(conn) -> str:
    h = hashlib.sha256()
    for d, c, section, body in conn.execute(
            "SELECT doc_id, passage_no, section, body FROM text_passages ORDER BY doc_id, passage_no"):
        h.update(f"{d}\t{c}\t{sha(retrieve.chunk_text(section, body))}\n".encode())
    return h.hexdigest()


def with_backoff(embed_fn, texts: list[str], tries: int = 10):
    """Retries rate limits (HTTP 429) during bulk ingestion only; the live query path fails fast instead."""
    for attempt in range(tries):
        try:
            return embed_fn(texts, "document")
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                raise
            wait = float(e.headers.get("Retry-After") or 65)  # Voyage limits are per minute
            print(f"rate limited (429), waiting {wait:.0f} s", flush=True)
        except (TimeoutError, urllib.error.URLError) as e:  # network hiccup; HTTPError is caught above
            if attempt == tries - 1:
                raise
            wait = 65
            print(f"network error ({type(e).__name__}), waiting {wait} s", flush=True)
            time.sleep(wait)


def batches(todo: list[tuple], size: int, max_chars: int | None = None):
    """Consecutive groups of at most `size` passages and (if given) `max_chars` characters; a longer passage goes alone."""
    batch, chars = [], 0
    for item in todo:
        if batch and (len(batch) == size or (max_chars and chars + len(item[2]) > max_chars)):
            yield batch
            batch, chars = [], 0
        batch.append(item)
        chars += len(item[2])
    if batch:
        yield batch


def ingest(conn, embed_fn=retrieve.embed, model: str = retrieve.EMBED_MODEL, version: str = "", max_usd: float = 0.20,
           limit: int | None = None, batch_size: int = BATCH, pace: float = 0, max_chars: int | None = None) -> dict:
    """Embeds what `pending` returns (the first `limit` if given), deletes orphaned rows; returns counts and tokens."""
    conn.execute((ROOT / "db" / "embeddings.sql").read_text())  # static DDL, idempotent
    gone = conn.execute("""DELETE FROM text_embeddings e WHERE e.model = %s AND NOT EXISTS
                           (SELECT 1 FROM text_passages p WHERE p.doc_id = e.doc_id AND p.passage_no = e.chunk_id)""",
                        (model,)).rowcount
    conn.commit()
    todo, total = pending(conn, model)
    todo = todo[:limit] if limit is not None else todo
    tokens, done = 0, 0
    for n, batch in enumerate(batches(todo, batch_size, max_chars)):
        if tokens * PRICE_PER_MTOK / 1e6 >= max_usd:
            raise SystemExit(f"stopping: {tokens:,} tokens reached --max-usd {max_usd} (rerun resumes)")
        if n and pace:
            time.sleep(pace)  # stays under per-minute limits (no payment method: 3 requests, 10K tokens per minute)
        vectors, used = with_backoff(embed_fn, [t for _, _, t, _ in batch])
        tokens += used
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO text_embeddings (doc_id, chunk_id, model, model_version, dim, chunk_text, text_sha256, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::halfvec(1024))
                ON CONFLICT (doc_id, chunk_id, model) DO UPDATE SET model_version = EXCLUDED.model_version,
                    chunk_text = EXCLUDED.chunk_text, text_sha256 = EXCLUDED.text_sha256,
                    embedding = EXCLUDED.embedding, created_at = now()""",
                [(d, c, model, version, retrieve.EMBED_DIM, t, h, str(v)) for (d, c, t, h), v in zip(batch, vectors)])
        conn.commit()
        done += len(batch)
        print(f"{done:,}/{len(todo):,} embedded, {tokens:,} tokens", flush=True)
    return {"passages": total, "embedded": len(todo), "deleted": gone, "tokens": tokens}


def write_manifest(conn, run: dict) -> None:
    old = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"runs": []}
    account = old.get("voyage_account", {})  # set by the owner in the manifest; every run records it
    rows = conn.execute("SELECT count(*) FROM text_embeddings WHERE model = %s", (retrieve.EMBED_MODEL,)).fetchone()[0]
    doc = {
        "what": "Voyage embeddings of the text_passages rows (derived data; table text_embeddings)",
        "chunking": {"source": "scout/text/passages.py", "unit": "paragraph, long ones cut at sentence ends",
                     "max_chars": MAX_CHARS, "min_chars": 40,
                     "embedded_text": "section name, newline, passage body (scout.text.retrieve.chunk_text)"},
        "model": retrieve.EMBED_MODEL, "dimension": retrieve.EMBED_DIM, "storage": "halfvec(1024)",
        "input_type": "document (queries: query)", "price_usd_per_mtok": PRICE_PER_MTOK,
        "corpus_sha256": corpus_hash(conn), "rows": rows, "voyage_account": account,
        "runs": old["runs"] + [{**run, "date": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "commit": git_commit(),
                                "voyage_training_opt_out": account.get("training_opt_out"),
                                "cost_usd_list_price": round(run["tokens"] * PRICE_PER_MTOK / 1e6, 4)}],
    }
    MANIFEST.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", action="store_true", help="what would be embedded (characters), no API call")
    ap.add_argument("--max-usd", type=float, default=0.20)
    ap.add_argument("--batch", type=int, default=BATCH, help="passages per request")
    ap.add_argument("--max-chars", type=int, help="characters per request (token limits)")
    ap.add_argument("--pace", type=float, default=0, help="seconds between requests")
    args = ap.parse_args()
    with store.connect() as conn:
        if args.count:
            conn.execute((ROOT / "db" / "embeddings.sql").read_text())
            todo, total = pending(conn, retrieve.EMBED_MODEL)
            conn.rollback()
            chars = sum(len(t) for _, _, t, _ in todo)
            print(f"{len(todo):,} of {total:,} passages to embed, {chars:,} characters")
            return
        run = ingest(conn, version=f"API, embedded {time.strftime('%Y-%m-%d', time.gmtime())}", max_usd=args.max_usd,
                     batch_size=args.batch, pace=args.pace,
                     max_chars=args.max_chars)
        write_manifest(conn, run)
    print(f"done: {run}; cost at list price US${run['tokens'] * PRICE_PER_MTOK / 1e6:.4f}")


if __name__ == "__main__":
    main()
