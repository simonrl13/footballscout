import os

import pandas as pd
import psycopg
import pytest

from scout.news import store
from scout.news.labeling import COLUMNS, sample_links, score, wilson
from scout.news.linker import build_index
from scout.news.textpass import run

D = pd.Timestamp


def links(n_unique=80, n_club=30, n_tag=10):
    rows = [{"article_url": f"https://g/{i}", "published_date": "2019-08-10", "matched_name": "x", "player_id": i,
             "player_name": "x", "club_at_date": "c", "method": m, "transfermarkt_url": "t"}
            for i, m in enumerate(["unique_name"] * n_unique + ["club"] * n_club + ["unique_name_tag"] * n_tag)]
    return pd.DataFrame(rows)


def test_sample_is_stratified_and_has_blank_label_columns():
    s = sample_links(links())
    assert len(s) == 100 and list(s.columns) == COLUMNS
    assert set(s.method) == {"unique_name", "club", "unique_name_tag"}
    assert (s.correct == "").all() and s.sample_id.tolist() == list(range(1, 101))


def test_score_and_wilson():
    lab = pd.DataFrame({"method": ["a"] * 10 + ["b"] * 10, "correct": ["y"] * 10 + ["y"] * 8 + ["n", ""]})
    t = score(lab)
    assert t.loc["all", "labeled"] == 19 and t.loc["all", "correct"] == 18
    assert t.loc["a", "precision"] == 1.0
    lo, hi = wilson(18, 19)
    assert lo < 18 / 19 < hi <= 1


# ---- text pass (DB) -------------------------------------------------------------------------------
def _raw():
    return {
        "players": pd.DataFrame({"player_id": [1, 2], "name": ["Harry Kane", "Son Heung-min"]}),
        "valuations": pd.DataFrame([(1, D("1989-06-01"), 1e6, 10), (2, D("1989-06-01"), 1e6, 10)],
                                   columns=["player_id", "date", "market_value_in_eur", "current_club_id"]),
        "transfers": pd.DataFrame({"player_id": pd.Series([], dtype="int64"), "date": pd.Series([], dtype="datetime64[ns]"),
                                   "from_club_id": pd.Series([], dtype="int64"), "to_club_id": pd.Series([], dtype="int64")}),
        "appearances": pd.DataFrame({"player_id": pd.Series([], dtype="int64"), "player_club_id": pd.Series([], dtype="int64"),
                                     "date": pd.Series([], dtype="datetime64[ns]"), "competition_id": pd.Series([], dtype=str)}),
        "games": pd.DataFrame({"competition_id": ["GB1"], "competition_type": ["domestic_league"]}),
    }


@pytest.fixture
def conn():
    url = os.environ.get("LOADER_DATABASE_URL")
    try:
        c = psycopg.connect(url, connect_timeout=5) if url else None
    except psycopg.OperationalError:
        c = None
    if c is None:
        pytest.skip("LOADER_DATABASE_URL not set or database not reachable")
    store.ensure_schema(c)
    c.commit()
    calls_before = c.execute("SELECT coalesce((SELECT calls FROM guardian_api_calls WHERE day = current_date), 0)").fetchone()[0]
    cache_before = c.execute("SELECT count(*) FROM news_text_cache").fetchone()[0]
    yield c, cache_before
    c.rollback()
    c.execute("DELETE FROM news_mentions WHERE article_id LIKE 'test/%'")
    c.execute("DELETE FROM news_articles WHERE article_id LIKE 'test/%'")
    c.execute("DELETE FROM news_textpass_progress WHERE month < '1991-01-01'")
    c.execute("UPDATE guardian_api_calls SET calls = %s WHERE day = current_date", (calls_before,))
    c.commit()
    c.close()


def fake_search(start, end, page):
    item = {"id": f"test/tp/{page}", "webUrl": f"https://g/test/{page}", "sectionId": "football",
            "webPublicationDate": "1990-01-15T10:00:00Z",
            "fields": {"firstPublicationDate": "1990-01-15T10:00:00Z", "lastModified": "1990-01-15T10:00:00Z",
                       "wordcount": "40", "bodyText": f"SECRET BODY {page}: Harry Kane scored again."},
            "tags": []}
    return {"pages": 2, "results": [item]}


def test_textpass_stores_mentions_but_never_text_and_resumes(conn):
    c, cache_before = conn
    raw = _raw()
    idx = build_index(raw, pd.DataFrame({"club_id": [10], "name": ["Tottenham Hotspur"]}))
    first = run(c, raw, idx, "1990-01", "1990-01", max_calls=1, search=fake_search)
    assert first["calls"] == 1 and first["mentions"] == 1 and first["stopped"] == "max_calls"
    second = run(c, raw, idx, "1990-01", "1990-01", max_calls=5, search=fake_search)
    assert second["calls"] == 1  # resumed at page 2, then done
    m = c.execute("SELECT article_id, player_id, method FROM news_mentions WHERE article_id LIKE 'test/tp/%' ORDER BY 1").fetchall()
    assert m == [("test/tp/1", 1, "unique_name"), ("test/tp/2", 1, "unique_name")]
    assert c.execute("SELECT count(*) FROM news_text_cache").fetchone()[0] == cache_before  # nothing cached
    dump = c.execute("SELECT row_to_json(a)::text FROM news_articles a WHERE article_id LIKE 'test/tp/%'").fetchall()
    assert dump and not any("SECRET BODY" in r[0] for r in dump)


# ---- extraction batch runner with a fake client (no API calls) --------------------------------------
from types import SimpleNamespace as NS  # noqa: E402

from scout.news import extract  # noqa: E402


class FakeBatches:
    def __init__(self, replies):
        self.replies, self.created = replies, []

    def create(self, requests):
        self.created.append(requests)
        return NS(id="batch_test")

    def retrieve(self, _id):
        return NS(processing_status="ended")

    def results(self, _id):
        for cid, text in self.replies.items():
            msg = NS(content=[NS(type="text", text=text)], usage=NS(input_tokens=500, output_tokens=40))
            yield NS(custom_id=cid, result=NS(type="succeeded", message=msg))


def test_run_batch_verifies_quotes_and_caches_by_prompt_version(conn):
    c, _ = conn
    c.execute("INSERT INTO news_articles (article_id, url, published_at) VALUES ('test/x1', 'u', '1990-01-01') ON CONFLICT DO NOTHING")
    c.commit()
    text = "Harry Kane limped off with a hamstring injury."
    reply = ('{"players": [{"player_id": 1, "signals": ['
             '{"type": "injury", "detail": "injured", "evidence": "limped off with a hamstring injury"},'
             '{"type": "transfer_rumour", "detail": "linked_with_move", "evidence": "Kane joined Bayern"}]}]}')
    cid = extract.build_request("test/x1", text, [(1, "Harry Kane")], "m")["custom_id"]
    client = NS(messages=NS(batches=FakeBatches({cid: reply})))
    todo = [{"article_id": "test/x1", "text": text, "players": [(1, "Harry Kane")]}]
    try:
        s = extract.run_batch(c, client, todo, model="m", sleep=lambda _: None)
        assert s == {"submitted": 1, "succeeded": 1, "signals": 1, "dropped_unverified": 1}
        row = c.execute("SELECT signal_type, evidence_start, evidence_end FROM news_signals WHERE article_id = 'test/x1'").fetchone()
        assert row[0] == "injury" and text[row[1]:row[2]] == "limped off with a hamstring injury"
        assert extract.run_batch(c, client, todo, model="m", sleep=lambda _: None) == {"submitted": 0}  # cached
        assert len(client.messages.batches.created) == 1
    finally:
        c.rollback()
        c.execute("DELETE FROM news_signals WHERE article_id = 'test/x1'")
        c.execute("DELETE FROM news_extractions WHERE article_id = 'test/x1'")
        c.execute("DELETE FROM news_articles WHERE article_id = 'test/x1'")
        c.commit()
