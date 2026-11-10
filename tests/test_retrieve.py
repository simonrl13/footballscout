"""Retrieval modes (scout/text/retrieve.py), RRF, idempotent embedding ingestion, and keyword parity with the code
before RETRIEVAL_MODE existed (tests/fixtures/keyword_search_text.json, recorded at 72cef97)."""
import json
import math
from pathlib import Path

import pytest

from scout.agent import tools
from scout.agent.agent import sources_footer
from scout.text import embed, retrieve, store

FIXTURE = Path(__file__).parent / "fixtures" / "keyword_search_text.json"


def test_rrf_sums_reciprocal_ranks_and_breaks_ties_by_first_appearance():
    assert retrieve.rrf([["a", "b", "c"], ["c", "b"]], k=60) == ["c", "b", "a"]  # c: 1/63+1/61 > b: 2/62 > a: 1/61
    assert retrieve.rrf([["a"], ["b"]], k=1) == ["a", "b"]  # equal scores: order of first appearance
    assert retrieve.rrf([["x", "y"]], k=10) == ["x", "y"] and retrieve.rrf([[], []], k=10) == []
    # small k rewards a top rank in one list over middling ranks in both
    assert retrieve.rrf([["a", "q", "r", "m"], ["z", "s", "t", "m"]], k=1)[0] == "a"  # 1/2 > 2/5
    assert retrieve.rrf([["a", "q", "r", "m"], ["z", "s", "t", "m"]], k=1000)[0] == "m"


def test_mode_comes_from_env_and_defaults_to_keyword(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_MODE", raising=False)
    assert retrieve.mode() == "keyword"
    for m in retrieve.MODES:
        monkeypatch.setenv("RETRIEVAL_MODE", m)
        assert retrieve.mode() == m
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25")
    with pytest.raises(ValueError):
        retrieve.mode()


def _row(i: int) -> dict:
    return {"doc_id": "d", "passage_no": i, "section": None, "body": f"passage {i}"}


@pytest.fixture
def fake_lists(monkeypatch):
    """keyword returns passages 1, 2, 3; vector returns 3, 4; rerank (Voyage) reverses its input."""
    calls = []
    monkeypatch.setattr(retrieve, "keyword", lambda conn, words, pid, limit: [_row(i) for i in (1, 2, 3)][:limit])
    monkeypatch.setattr(retrieve, "vector", lambda conn, query, pid, limit: [_row(i) for i in (3, 4)][:limit])

    def voyage(path, payload):
        calls.append((path, payload))
        n = len(payload["documents"])
        return {"data": [{"index": i} for i in reversed(range(n))][:payload["top_k"]], "usage": {"total_tokens": 7}}
    monkeypatch.setattr(retrieve, "voyage", voyage)
    return calls


def test_each_mode_through_one_interface(fake_lists):
    nos = lambda rows: [r["passage_no"] for r in rows]  # noqa: E731
    assert nos(retrieve.search(None, "q", ["q"], None, 5, "keyword")) == [1, 2, 3]
    assert nos(retrieve.search(None, "q", ["q"], None, 5, "vector")) == [3, 4]
    assert nos(retrieve.search(None, "q", ["q"], None, 5, "hybrid", k=60)) == [3, 1, 2, 4]  # 3 is in both lists
    assert nos(retrieve.search(None, "q", ["q"], None, 2, "hybrid", k=60)) == [3, 1]
    assert nos(retrieve.search(None, "q", ["q"], None, 2, "hybrid_rerank", k=60, n=3)) == [2, 1]  # reverse of 3, 1, 2
    path, payload = fake_lists[-1]
    assert path == "rerank" and payload["model"] == retrieve.RERANK_MODEL and len(payload["documents"]) == 3


def test_search_text_output_contract_is_the_same_in_every_mode(monkeypatch):
    import datetime
    row = {"player_id": 1, "name": "A", "enwiki_title": "A_(footballer)", "section": "Career", "body": "He joined X.",
           "url": "https://en.wikipedia.org/w/index.php?oldid=1", "available_at": datetime.datetime(2026, 6, 1),
           "doc_id": "d", "passage_no": 0}
    outs = []
    for m in retrieve.MODES:
        monkeypatch.setenv("RETRIEVAL_MODE", m)
        monkeypatch.setattr(retrieve, "search", lambda conn, q, w, pid, limit, mode_=None, **kw: [row])
        outs.append(tools.search_text(None, tools.TextSearch(query="joined X")))
    assert all(o == outs[0] for o in outs) and outs[0]["passages"][0]["revision_url"].endswith("oldid=1")


def _db_ready() -> bool:
    try:
        with tools.connect() as c:
            return c.execute("SELECT count(*) AS n FROM text_passages").fetchone()["n"] > 0
    except Exception:
        return False


db = pytest.mark.skipif(not _db_ready(), reason="database or text_passages not available")


@db
def test_keyword_mode_is_byte_identical_to_before(monkeypatch):
    """search_text output and the citation footer for 192 recorded inputs (the eval questions in both scopes, the CI
    recordings, every search_text call in the local traces, operator/injection strings) are unchanged."""
    monkeypatch.setenv("RETRIEVAL_MODE", "keyword")
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 190
    with tools.connect() as c:
        for case in cases:
            out = tools.run_tool(c, "search_text", case["input"])
            assert json.dumps(out, ensure_ascii=False) == case["output"], case["input"]
            cites = {i + 1: p for i, p in enumerate(out["passages"])}
            assert sources_footer(" ".join(f"[wiki {n}]" for n in cites), cites) == case["footer"]


FAKE = "test-fake-model"


def fake_embed(texts, input_type):
    """Deterministic unit vectors: a passage's vector depends only on its text."""
    out = []
    for t in texts:
        seed = int(embed.sha(t)[:8], 16) % 10007 + 1
        v = [math.sin(seed * (i + 1)) for i in range(retrieve.EMBED_DIM)]
        norm = math.sqrt(sum(x * x for x in v))
        out.append([x / norm for x in v])
    return out, 3 * len(texts)


@db
def test_ingestion_is_idempotent_and_reembeds_only_changed_text(monkeypatch):
    with store.connect() as conn:
        try:
            first = embed.ingest(conn, fake_embed, model=FAKE, version="test", limit=5)
            assert first["embedded"] == 5 and first["tokens"] == 15
            n = lambda: conn.execute("SELECT count(*) FROM text_embeddings WHERE model = %s", (FAKE,)).fetchone()[0]  # noqa: E731
            assert n() == 5
            # a second run over the same 5 embeds nothing new among them and never duplicates rows
            todo, _ = embed.pending(conn, FAKE)
            assert not {(d, c) for d, c, _, _ in todo} & {
                (d, c) for d, c in conn.execute("SELECT doc_id, chunk_id FROM text_embeddings WHERE model = %s", (FAKE,))}
            embed.ingest(conn, fake_embed, model=FAKE, version="test", limit=0)
            assert n() == 5
            # changed text (simulated by a stale hash) is re-embedded in place
            conn.execute("UPDATE text_embeddings SET text_sha256 = 'stale' WHERE model = %s AND ctid IN "
                         "(SELECT ctid FROM text_embeddings WHERE model = %s ORDER BY doc_id, chunk_id LIMIT 1)", (FAKE, FAKE))
            conn.commit()
            todo, _ = embed.pending(conn, FAKE)
            stale = todo[0]  # the first passage overall, so the first one ingest takes
            again = embed.ingest(conn, fake_embed, model=FAKE, version="test", limit=1)
            assert again["embedded"] == 1 and n() == 5
            assert conn.execute("SELECT text_sha256 FROM text_embeddings WHERE model = %s AND doc_id = %s AND chunk_id = %s",
                                (FAKE, stale[0], stale[1])).fetchone()[0] == stale[3]

            # vector mode over these rows: the passage whose own vector is the query ranks first, in both scopes
            monkeypatch.setattr(retrieve, "EMBED_MODEL", FAKE)
            d, c, text = conn.execute("SELECT doc_id, chunk_id, chunk_text FROM text_embeddings WHERE model = %s "
                                      "ORDER BY doc_id, chunk_id LIMIT 1", (FAKE,)).fetchone()
            pid = conn.execute("SELECT player_id FROM text_passages WHERE doc_id = %s AND passage_no = %s", (d, c)).fetchone()[0]
            monkeypatch.setattr(retrieve, "embed", lambda texts, kind: fake_embed([text], kind))
            with tools.connect() as reader:
                for scope in (pid, None):
                    top = retrieve.search(reader, "q", ["q"], scope, 3, "vector")[0]
                    assert (top["doc_id"], top["passage_no"]) == (d, c)
        finally:
            conn.rollback()
            conn.execute("DELETE FROM text_embeddings WHERE model = %s", (FAKE,))
            conn.commit()


def test_neon_migration_matches_the_local_ddl():
    root = Path(__file__).parents[1]
    local = (root / "db" / "embeddings.sql").read_text(encoding="utf-8")
    neon = (root / "docs" / "deploy" / "neon_embeddings.sql").read_text(encoding="utf-8")
    block = local[local.index("CREATE TABLE"):]
    assert block in neon and neon.index("SET ROLE scout_loader;") < neon.index(block)


def test_batches_respect_count_and_character_budgets():
    todo = [("d", i, "x" * n, "h") for i, n in enumerate([5, 5, 5, 20, 5])]
    sizes = lambda b: [len(x) for x in b]  # noqa: E731
    assert sizes(embed.batches(todo, 2)) == [2, 2, 1]
    assert sizes(embed.batches(todo, 10, max_chars=12)) == [2, 1, 1, 1]  # the 20-character passage goes alone
    assert [x for b in embed.batches(todo, 3, max_chars=12) for x in b] == todo
