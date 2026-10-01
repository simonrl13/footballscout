"""Postgres storage for news metadata, the 24-hour text cache, the daily API budget and backfill progress.

Writes use the scout_loader role (LOADER_DATABASE_URL). ponytail: the M4 agent will need a narrow writer for the
text cache instead of the loader role; add a dedicated role then.
"""
import os
from datetime import timedelta

import psycopg
from psycopg.types.json import Jsonb

from scout.data.manifest import ROOT
from scout.news.guardian import DAILY_LIMIT

TEXT_TTL = timedelta(hours=24)


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["LOADER_DATABASE_URL"], connect_timeout=5)


def ensure_schema(conn) -> None:
    conn.execute((ROOT / "db" / "news.sql").read_text())  # static DDL, IF NOT EXISTS


def take_call(conn, limit: int = DAILY_LIMIT) -> bool:
    """Atomically reserve one Guardian API call for today; False once the daily limit is reached."""
    row = conn.execute(
        "INSERT INTO guardian_api_calls (day, calls) VALUES (current_date, 1) "
        "ON CONFLICT (day) DO UPDATE SET calls = guardian_api_calls.calls + 1 "
        "WHERE guardian_api_calls.calls < %s RETURNING calls", (limit,)).fetchone()
    conn.commit()
    return row is not None


def upsert_articles(conn, rows: list[dict]) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO news_articles (article_id, url, section_id, published_at, first_published_at, last_modified, wordcount, tags) "
            "VALUES (%(article_id)s, %(url)s, %(section_id)s, %(published_at)s, %(first_published_at)s, %(last_modified)s, "
            "%(wordcount)s, %(tags)s) ON CONFLICT (article_id) DO UPDATE SET url = EXCLUDED.url, "
            "last_modified = EXCLUDED.last_modified, wordcount = EXCLUDED.wordcount, tags = EXCLUDED.tags", [{**r, "tags": Jsonb(r["tags"])} for r in rows])
    conn.commit()
    return len(rows)


def cached_text(conn, article_id: str) -> str | None:
    """Cached body text if fetched within the last 24 h; older rows are treated as absent even before a purge."""
    row = conn.execute("SELECT body FROM news_text_cache WHERE article_id = %s AND fetched_at > now() - %s",
                       (article_id, TEXT_TTL)).fetchone()
    return row[0] if row else None


def get_text(conn, article_id: str, fetch) -> str:
    """Text for an answer/citation: from the 24-h cache, else fetched live via `fetch(article_id)` and cached."""
    text = cached_text(conn, article_id)
    if text is None:
        if not take_call(conn):
            raise RuntimeError("Guardian daily call limit reached")
        text = fetch(article_id)
        conn.execute("INSERT INTO news_text_cache (article_id, body, fetched_at) VALUES (%s, %s, now()) "
                     "ON CONFLICT (article_id) DO UPDATE SET body = EXCLUDED.body, fetched_at = now()", (article_id, text))
        conn.commit()
    return text


def purge_text_cache(conn) -> int:
    """Delete every cached article text older than 24 h. Run on a schedule and before each news job."""
    n = conn.execute("DELETE FROM news_text_cache WHERE fetched_at <= now() - %s", (TEXT_TTL,)).rowcount
    conn.commit()
    return n


if __name__ == "__main__":  # uv run --env-file .env python -m scout.news.store  -> purge now
    with connect() as c:
        ensure_schema(c)
        print(f"purged {purge_text_cache(c)} cached article texts older than 24 h")
