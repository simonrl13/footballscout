import os
from types import SimpleNamespace as NS

import pandas as pd
import psycopg
import pytest

from scout.text import extract, store
from scout.text.labeling import COLUMNS, sample_links, score, wilson


def links(n_unique=80, n_club=30, n_tag=10):
    rows = [{"doc_url": f"https://example.org/{i}", "available_date": "2019-08-10", "matched_name": "x", "player_id": i,
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


# ---- extraction batch runner with a fake client (no API calls) --------------------------------------
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
    yield c
    c.rollback()
    c.execute("DELETE FROM text_signals WHERE doc_id LIKE 'test/%'")
    c.execute("DELETE FROM text_extractions WHERE doc_id LIKE 'test/%'")
    c.execute("DELETE FROM text_documents WHERE doc_id LIKE 'test/%'")
    c.commit()
    c.close()


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
    conn.execute("INSERT INTO text_documents (doc_id, source, url, available_at) "
                 "VALUES ('test/x1', 'test', 'https://example.org/x1', '1990-01-01')")
    conn.commit()
    text = "Harry Kane limped off with a hamstring injury."
    reply = ('{"players": [{"player_id": 1, "signals": ['
             '{"type": "injury", "detail": "injured", "evidence": "limped off with a hamstring injury"},'
             '{"type": "transfer_rumour", "detail": "linked_with_move", "evidence": "Kane joined Bayern"}]}]}')
    cid = extract.build_request("test/x1", text, [(1, "Harry Kane")], "m")["custom_id"]
    client = NS(messages=NS(batches=FakeBatches({cid: reply})))
    todo = [{"doc_id": "test/x1", "text": text, "players": [(1, "Harry Kane")]}]
    s = extract.run_batch(conn, client, todo, model="m", sleep=lambda _: None)
    assert s == {"submitted": 1, "succeeded": 1, "signals": 1, "dropped_unverified": 1}
    row = conn.execute("SELECT signal_type, evidence_start, evidence_end FROM text_signals WHERE doc_id = 'test/x1'").fetchone()
    assert row[0] == "injury" and text[row[1]:row[2]] == "limped off with a hamstring injury"
    assert extract.run_batch(conn, client, todo, model="m", sleep=lambda _: None) == {"submitted": 0}  # cached
    assert len(client.messages.batches.created) == 1


def test_old_guardian_tables_are_gone(conn):
    left = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                        "AND (table_name LIKE 'news%%' OR table_name LIKE 'guardian%%')").fetchall()
    assert left == []
