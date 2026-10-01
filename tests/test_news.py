"""Guardian storage rules. Unit tests always run; DB tests need LOADER_DATABASE_URL and a running Postgres
(uv run --env-file .env pytest tests/test_news.py). DB tests clean up their rows and give back API budget."""
import os
from datetime import date

import psycopg
import pytest

from scout.news import guardian, store
from scout.news.backfill import backfill

SAMPLE = {  # shape of a Guardian /search result, including fields we must NOT store
    "id": "football/2019/aug/10/test-article", "type": "article", "sectionId": "football",
    "webTitle": "Headline text", "webUrl": "https://www.theguardian.com/football/2019/aug/10/test-article",
    "webPublicationDate": "2019-08-10T12:00:00Z",
    "fields": {"firstPublicationDate": "2019-08-10T11:00:00Z", "lastModified": "2019-08-11T09:00:00Z", "wordcount": "812",
               "bodyText": "FULL ARTICLE TEXT", "body": "<p>FULL ARTICLE TEXT</p>"},
    "tags": [{"id": "football/arsenal", "type": "keyword", "webTitle": "Arsenal", "apiUrl": "x"}],
}


def test_to_row_keeps_only_ids_urls_dates_tags():
    row = guardian.to_row(SAMPLE)
    assert set(row) == {"article_id", "url", "section_id", "published_at", "first_published_at", "last_modified", "wordcount", "tags"}
    assert row["wordcount"] == 812
    assert "FULL ARTICLE TEXT" not in repr(row) and "Headline text" not in repr(row)
    assert row["tags"] == [{"id": "football/arsenal", "type": "keyword", "webTitle": "Arsenal"}]


def test_search_never_requests_article_text():
    assert "body" not in guardian.SEARCH_FIELDS.lower()


def test_missing_key_fails_without_calling(monkeypatch):
    monkeypatch.delenv("GUARDIAN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GUARDIAN_API_KEY"):
        guardian.search_page(date(2019, 8, 1), date(2019, 8, 31), 1)


def _db():
    url = os.environ.get("LOADER_DATABASE_URL")
    if not url:
        return None
    try:
        return psycopg.connect(url, connect_timeout=5)
    except psycopg.OperationalError:
        return None


@pytest.fixture
def conn():
    c = _db()
    if c is None:
        pytest.skip("LOADER_DATABASE_URL not set or database not reachable")
    store.ensure_schema(c)
    c.commit()
    calls_before = c.execute("SELECT coalesce((SELECT calls FROM guardian_api_calls WHERE day = current_date), 0)").fetchone()[0]
    yield c
    c.rollback()
    c.execute("DELETE FROM news_text_cache WHERE article_id LIKE 'test/%'")
    c.execute("DELETE FROM news_articles WHERE article_id LIKE 'test/%'")
    c.execute("DELETE FROM news_backfill_progress WHERE month < '1991-01-01'")
    c.execute("UPDATE guardian_api_calls SET calls = %s WHERE day = current_date", (calls_before,))  # give budget back
    c.commit()
    c.close()


def test_text_older_than_24h_is_never_returned_and_is_purged(conn):
    conn.execute("INSERT INTO news_text_cache VALUES ('test/old', 'old text', now() - interval '25 hours'), "
                 "('test/new', 'new text', now() - interval '1 hour')")
    conn.commit()
    assert store.cached_text(conn, "test/old") is None  # invisible even before the purge runs
    assert store.cached_text(conn, "test/new") == "new text"
    store.purge_text_cache(conn)
    left = {r[0] for r in conn.execute("SELECT article_id FROM news_text_cache WHERE article_id LIKE 'test/%'")}
    assert left == {"test/new"}
    old_rows = conn.execute("SELECT count(*) FROM news_text_cache WHERE fetched_at <= now() - interval '24 hours'").fetchone()[0]
    assert old_rows == 0


def test_get_text_refetches_stale_text(conn):
    conn.execute("INSERT INTO news_text_cache VALUES ('test/stale', 'stale', now() - interval '30 hours')")
    conn.commit()
    assert store.get_text(conn, "test/stale", fetch=lambda _id: "fresh") == "fresh"
    assert store.get_text(conn, "test/stale", fetch=lambda _id: pytest.fail("should hit the cache")) == "fresh"


def test_daily_call_budget_is_enforced(conn):
    used = conn.execute("SELECT coalesce((SELECT calls FROM guardian_api_calls WHERE day = current_date), 0)").fetchone()[0]
    assert store.take_call(conn, limit=used + 2) and store.take_call(conn, limit=used + 2)
    assert not store.take_call(conn, limit=used + 2)


def test_backfill_is_resumable_and_stores_no_text(conn):
    def fake_search(start, end, page):
        item = {**SAMPLE, "id": f"test/{start:%Y-%m}/p{page}"}
        return {"pages": 3, "results": [item]}

    first = backfill(conn, "1990-01", "1990-01", max_calls=2, search=fake_search)
    assert first == {"calls": 2, "articles": 2, "months_done": 0, "stopped": "max_calls"}
    second = backfill(conn, "1990-01", "1990-01", max_calls=5, search=fake_search)
    assert second["calls"] == 1 and second["months_done"] == 1  # resumed at page 3, then done
    ids = {r[0] for r in conn.execute("SELECT article_id FROM news_articles WHERE article_id LIKE 'test/1990-01/%'")}
    assert ids == {"test/1990-01/p1", "test/1990-01/p2", "test/1990-01/p3"}
    cols = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'news_articles'")}
    assert not cols & {"body", "body_text", "title", "text"}
