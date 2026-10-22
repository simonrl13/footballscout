"""Public-demo rate limits: client IP, hashing, 429s (no DB), and the counting against Postgres (skipped without it)."""
import contextlib
import logging
import os
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

from scout.agent import tools
from scout.api import limits, main

PEPPER = "test-pepper-not-a-secret"


def test_client_ip_is_the_entry_googles_front_end_appends():
    assert limits.client_ip({"x-forwarded-for": "6.6.6.6, 203.0.113.9"}, "10.0.0.1") == "203.0.113.9"
    assert limits.client_ip({"x-forwarded-for": "203.0.113.9"}, "10.0.0.1") == "203.0.113.9"
    assert limits.client_ip({}, "10.0.0.1") == "10.0.0.1"


def test_malformed_entries_share_one_fail_closed_bucket():
    for bad in ["not-an-ip", "1.2.3.4.5", "6.6.6.6, unknown", "2001:db8::1::2", "<script>"]:
        assert limits.client_ip({"x-forwarded-for": bad}, "10.0.0.1") == limits.MALFORMED, bad
    assert limits.client_ip({}, None) == limits.MALFORMED  # no header and no peer: same bucket
    assert limits.client_ip({"x-forwarded-for": "6.6.6.6, 203.0.113.9"}, None) != limits.MALFORMED


def test_ipv6_clients_are_keyed_by_their_64():
    a = limits.client_ip({"x-forwarded-for": "2001:db8:1:2:aaaa::1"}, None)
    assert a == "2001:db8:1:2::/64"
    assert limits.client_ip({"x-forwarded-for": "6.6.6.6, 2001:db8:1:2:ffff:ffff:ffff:ffff"}, None) == a  # same /64
    assert limits.client_ip({"x-forwarded-for": "2001:db8:1:3::1"}, None) != a  # next /64: another client
    assert limits.client_ip({"x-forwarded-for": "::ffff:203.0.113.9"}, None) == "203.0.113.9"  # IPv4-mapped


def test_ip_hash_is_keyed_and_reveals_neither_ip_nor_pepper(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PEPPER", PEPPER)
    h = limits.ip_hash("203.0.113.9")
    assert h == limits.ip_hash("203.0.113.9") and len(h) == 64
    assert "203.0.113.9" not in h and PEPPER not in h
    monkeypatch.setenv("RATE_LIMIT_PEPPER", "other")
    assert limits.ip_hash("203.0.113.9") != h


@pytest.fixture
def public(monkeypatch):
    """Public mode with the tracer connection and the counter replaced; records what the counter was asked."""
    class Seen(list):
        wait = None
    seen = Seen()
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    monkeypatch.setenv("RATE_LIMIT_PEPPER", PEPPER)
    monkeypatch.setenv("TRACER_DATABASE_URL", "postgresql://unused")
    monkeypatch.delenv("SCOUT_API_TOKEN", raising=False)
    monkeypatch.setattr(main.psycopg, "connect", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(limits, "check", lambda conn, key, kind: seen.append((key, kind)) or seen.wait)
    monkeypatch.setattr(tools, "get_player", lambda conn, a: {"player_id": a.player_id})
    main.app.dependency_overrides[main.db] = lambda: None
    yield TestClient(main.app), seen
    main.app.dependency_overrides.clear()


def test_public_mode_needs_no_token_and_counts_by_hashed_ip(public):
    client, seen = public
    assert client.get("/players/7", headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.9"}).status_code == 200
    assert seen == [(limits.ip_hash("203.0.113.9"), "tools")]


def test_spoofed_forwarded_for_entries_dont_change_the_key(public):
    client, seen = public
    for fake in ["1.1.1.1", "2.2.2.2, 3.3.3.3"]:
        client.get("/players/7", headers={"X-Forwarded-For": f"{fake}, 203.0.113.9"})
    assert len({key for key, _ in seen}) == 1


def test_over_the_limit_is_429_with_retry_after(public):
    client, seen = public
    seen.wait = 42
    r = client.get("/players/7")
    assert r.status_code == 429 and r.headers["Retry-After"] == "42"
    assert client.post("/ask", json={"question": "Who is Kane?"}).status_code == 429
    assert seen[-1][1] == "ask_raw"  # stopped by the pre-validation bucket
    n = len(seen)
    assert client.get("/health").status_code == 200 and len(seen) == n  # /health is never counted or limited


def test_pepper_and_ip_never_reach_logs_or_responses(public, caplog):
    client, _ = public
    with caplog.at_level(logging.DEBUG):
        r = client.get("/players/7", headers={"X-Forwarded-For": "203.0.113.9"})
    assert PEPPER not in caplog.text + r.text and "203.0.113.9" not in caplog.text + r.text


def test_public_mode_without_a_pepper_fails_closed(public, monkeypatch):
    client, _ = public
    monkeypatch.delenv("RATE_LIMIT_PEPPER")
    with pytest.raises(KeyError):
        client.get("/players/7")


def _tracer():
    try:
        return psycopg.connect(os.environ["TRACER_DATABASE_URL"], connect_timeout=3, autocommit=True)
    except (KeyError, psycopg.Error) as e:
        raise pytest.skip.Exception("tracer database not available") from e


@pytest.fixture
def tracer():
    conn, key = _tracer(), "test-" + secrets.token_hex(8)
    yield conn, key
    conn.execute("DELETE FROM agent_requests WHERE ip_hash = %s", (key,))
    conn.close()


def test_minute_limit_counts_accepted_requests_only(tracer):
    conn, key = tracer
    assert [limits.check(conn, key, "ask") for _ in range(5)] == [None] * 5
    assert limits.check(conn, key, "ask") == 60
    assert conn.execute("SELECT count(*) FROM agent_requests WHERE ip_hash = %s", (key,)).fetchone()[0] == 5
    assert limits.check(conn, key, "tools") is None  # separate counters per kind


def test_day_limit_waits_until_utc_midnight(tracer):
    conn, key = tracer
    conn.execute("INSERT INTO agent_requests (created_at, ip_hash, kind) SELECT date_trunc('day', now() AT TIME ZONE "
                 "'UTC') AT TIME ZONE 'UTC', %s, 'ask' FROM generate_series(1, 20)", (key,))
    wait = limits.check(conn, key, "ask")
    assert wait is not None and 0 < wait <= 86_400


def test_rows_older_than_48_hours_are_purged(tracer):
    conn, key = tracer
    conn.execute("INSERT INTO agent_requests (created_at, ip_hash, kind) VALUES (now() - interval '49 hours', %s, 'ask')",
                 (key,))
    limits.check(conn, key + "-other", "tools")
    conn.execute("DELETE FROM agent_requests WHERE ip_hash = %s", (key + "-other",))
    assert conn.execute("SELECT count(*) FROM agent_requests WHERE ip_hash = %s", (key,)).fetchone()[0] == 0


def test_reader_cannot_see_the_request_log():
    try:
        conn = tools.connect()
    except (KeyError, psycopg.Error) as e:
        raise pytest.skip.Exception("database not available") from e
    with conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT 1 FROM agent_requests LIMIT 1")


def test_container_has_no_access_log():
    """uvicorn's access log would print client IPs (it trusts X-Forwarded-For from local proxies); Cloud Run logs requests."""
    from scout.data.manifest import ROOT
    assert '"--no-access-log"' in (ROOT / "Dockerfile").read_text(encoding="utf-8")


def _fail(*a, **k):
    raise AssertionError("must not be called")


def test_public_health_touches_neither_the_database_nor_anthropic(public, monkeypatch):
    import anthropic
    client, seen = public
    monkeypatch.setattr(main.psycopg, "connect", _fail)
    monkeypatch.setattr(tools, "connect", _fail)
    monkeypatch.setattr(anthropic, "Anthropic", _fail)
    assert client.get("/health").json() == {"status": "ok"} and not seen


def test_security_headers_and_security_txt(public):
    client, _ = public
    r = client.get("/players/7")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Content-Security-Policy"] == main.CSP and "frame-ancestors 'none'" in main.CSP
    assert client.get("/docs").headers["Content-Security-Policy"] == main.DOCS_CSP != main.CSP
    txt = client.get("/.well-known/security.txt")
    assert txt.headers["content-type"].startswith("text/plain") and "Expires: " in txt.text and "Contact: " in txt.text
    assert client.get("/redoc").status_code == 404


def stub_agent(monkeypatch):
    """The agent with no model, no tracer and no reader: one tool_call event, then an answer."""
    import anthropic

    from scout.agent import agent

    class FakeConn:
        def close(self):
            pass

    class FakeTracer:
        conn = FakeConn()

    def fake_run(question, client, tracer, db):
        yield {"type": "tool_call", "name": "x", "input": {}}
        yield {"type": "answer", "text": "Hi"}
    monkeypatch.setattr(anthropic, "Anthropic", lambda: None)
    monkeypatch.setattr(agent, "Tracer", FakeTracer)
    monkeypatch.setattr(agent, "run", fake_run)
    monkeypatch.setattr(tools, "connect", contextlib.nullcontext)


def test_ask_answers_carry_the_ai_notice(public, monkeypatch):
    client, seen = public
    stub_agent(monkeypatch)
    body = client.post("/ask", json={"question": "Who is Kane?"}).text
    assert body.count(main.AI_NOTICE) == 1 and '"type": "answer"' in body
    key = limits.ip_hash(limits.MALFORMED)  # TestClient's peer "testclient" isn't an IP address
    assert seen == [(key, "ask_raw"), (key, "ask")]  # a valid question: the loose bucket, then the real limits


def test_invalid_questions_count_only_against_the_loose_bucket(public):
    client, seen = public
    for body in [{"question": "x"}, {"question": "y" * 501}, {"query": "Kane"}, None]:
        assert client.post("/ask", json=body).status_code == 422
    assert [kind for _, kind in seen] == ["ask_raw"] * 4
    seen.wait = 60  # the loose bucket full: a flood of invalid bodies gets 429, not 422
    assert client.post("/ask", json={"question": "x"}).status_code == 429


def test_concurrent_checks_never_overshoot(tracer):
    """12 simultaneous checks for one key, each on its own connection: exactly 5 pass (the advisory lock)."""
    _, key = tracer
    conns = [_tracer() for _ in range(12)]
    start = threading.Barrier(12)

    def one(conn):
        start.wait()
        return limits.check(conn, key, "ask")
    try:
        with ThreadPoolExecutor(12) as pool:
            results = list(pool.map(one, conns))
    finally:
        for c in conns:
            c.close()
    assert results.count(None) == 5 and results.count(60) == 7


@pytest.fixture
def public_db(monkeypatch):
    """Public mode against the real tracer database (the limits are real), with the agent stubbed (no model)."""
    conn = _tracer()
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    monkeypatch.setenv("RATE_LIMIT_PEPPER", PEPPER)
    stub_agent(monkeypatch)
    ip = f"198.51.100.{secrets.randbelow(250) + 1}"
    yield TestClient(main.app), {"X-Forwarded-For": f"6.6.6.6, {ip}"}, conn, limits.ip_hash(ip)
    conn.execute("DELETE FROM agent_requests WHERE ip_hash = %s", (limits.ip_hash(ip),))
    conn.close()


def test_burst_of_ask_requests_lets_at_most_5_through(public_db):
    client, headers, _, _ = public_db
    start = threading.Barrier(12)

    def one(_):
        start.wait()
        return client.post("/ask", json={"question": "Who is Kane?"}, headers=headers).status_code
    with ThreadPoolExecutor(12) as pool:
        codes = list(pool.map(one, range(12)))
    assert codes.count(200) == 5 and codes.count(429) == 7


def test_flood_of_invalid_asks_is_bounded_and_spares_the_daily_quota(public_db):
    client, headers, conn, key = public_db
    codes = [client.post("/ask", json={"question": "x"}, headers=headers).status_code for _ in range(21)]
    assert codes == [422] * 20 + [429]
    rows = dict(conn.execute("SELECT kind, count(*) FROM agent_requests WHERE ip_hash = %s GROUP BY kind", (key,)).fetchall())
    assert rows == {"ask_raw": 20}  # nothing against the 5/min and 20/day question limits
