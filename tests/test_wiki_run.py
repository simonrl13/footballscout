"""End-to-end extract-v2 flow with a fake Batch client (no API calls). Needs the DB (LOADER_DATABASE_URL)."""
import os
from types import SimpleNamespace as NS

import pandas as pd
import psycopg
import pytest

from scout.text import extract_wiki as xw, store
from scout.text.wikipedia import DDL
from scout.text.wiki_run import derived_docs, run_batch

PID = 990000001  # a player id that cannot collide with Transfermarkt ids in the test window


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
    c.execute(DDL)
    c.commit()
    yield c
    c.rollback()
    c.execute("DELETE FROM text_signals WHERE doc_id LIKE 'wikipedia:enwiki:%:t%'")
    c.execute("DELETE FROM text_extractions WHERE doc_id LIKE 'wikipedia:enwiki:%:t%'")
    c.execute("DELETE FROM wiki_snapshot_revisions WHERE player_id = %s", (PID,))
    c.execute("DELETE FROM text_documents WHERE doc_id LIKE 'wikipedia:enwiki:%:t%'")
    c.commit()
    c.close()


class FakeBatches:
    def __init__(self, reply):
        self.reply = reply

    def create(self, requests):
        self.ids = [r["custom_id"] for r in requests]
        return NS(id="batch_fake")

    def retrieve(self, _id):
        return NS(processing_status="ended")

    def results(self, _id):
        for cid in self.ids:
            msg = NS(content=[NS(type="text", text=self.reply)], usage=NS(input_tokens=800, output_tokens=60))
            yield NS(custom_id=cid, result=NS(type="succeeded", message=msg))


def test_new_in_year_document_extraction_and_verification(conn):
    prev = "Test Player is a footballer. He joined Test FC in 2010."
    now = prev + "\nOn 13 January 2017, Test Player signed a new contract with Test FC until 2020."
    for rev, body, ts in [("t1", prev, "2016-08-01"), ("t2", now, "2017-08-20")]:
        conn.execute("INSERT INTO text_documents (doc_id, source, url, available_at, body) VALUES (%s, 'wikipedia', 'u', %s, %s)",
                     (f"wikipedia:enwiki:rev:{rev}", ts, body))
    py = pd.DataFrame({"player_id": [PID], "t": [pd.Timestamp("2017-09-01")], "doc_t": ["wikipedia:enwiki:rev:t2"],
                       "doc_prev": ["wikipedia:enwiki:rev:t1"], "title": ["Test Player"]})
    docs = derived_docs(conn, py)
    assert docs[0]["text"] == "On 13 January 2017, Test Player signed a new contract with Test FC until 2020."
    assert docs[0]["url"].endswith("diff=t2&oldid=t1")
    reply = ('{"events": [{"type": "contract_extension", "date": "2017-01-13", "injury_type": null, "duration_days": null, '
             '"evidence": "On 13 January 2017, Test Player signed a new contract with Test FC until 2020"},'
             '{"type": "transfer", "date": "2019-07-01", "injury_type": null, "duration_days": null, "evidence": "He joined Test FC"}]}')
    stats = run_batch(conn, NS(messages=NS(batches=FakeBatches(reply))), docs, "m", sleep=lambda _: None)
    assert stats["kept"] == 1 and stats["dropped"]["no_quote"] == 1 and stats["input_tokens"] == 800
    row = conn.execute("SELECT signal_type, event_date, date_precision FROM text_signals WHERE doc_id = %s", (docs[0]["doc_id"],)).fetchone()
    assert row[0] == "contract_extension" and str(row[1]) == "2017-01-13" and row[2] == "day"
    assert run_batch(conn, NS(messages=NS(batches=FakeBatches(reply))), docs, "m")["submitted"] == 0  # cached
    assert conn.execute("SELECT output FROM text_extractions WHERE doc_id = %s", (docs[0]["doc_id"],)).fetchone()[0]["events"]


def test_year_context_finds_paragraph_and_season_heading_years():
    from scout.text.wiki_run import heading_years, year_context
    assert heading_years("2016–17 season.") == {"2016", "2017"}
    body = "Club career.\n\n2016–17 season.\nIn 2016 he moved to Test FC. In January, he injured his knee.\n\nLater years.\nIn March, he left."
    assert year_context(body, "In January, he injured his knee.", "2016") == (True, True)
    assert year_context(body, "In January, he injured his knee.", "2017") == (False, True)
    assert year_context(body, "In March, he left.", "2017") == (False, False)
