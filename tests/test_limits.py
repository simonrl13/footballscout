"""Public-demo rate limits: client IP, hashing, 429s (no DB), and the counting against Postgres (skipped without it)."""
import contextlib
import logging
import os
import secrets

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
    assert seen[-1][1] == "ask"
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
    except (KeyError, psycopg.Error):
        pytest.skip("tracer database not available")


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
    except (KeyError, psycopg.Error):
        pytest.skip("database not available")
    with conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT 1 FROM agent_requests LIMIT 1")


def test_container_has_no_access_log():
    """uvicorn's access log would print client IPs (it trusts X-Forwarded-For from local proxies); Cloud Run logs requests."""
    from scout.data.manifest import ROOT
    assert '"--no-access-log"' in (ROOT / "Dockerfile").read_text(encoding="utf-8")
