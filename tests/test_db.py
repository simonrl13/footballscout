"""Database role checks. Run with the DB up: uv run --env-file .env pytest tests/test_db.py
Skipped when READER_DATABASE_URL is unset or the database is unreachable."""
import os

import psycopg
import pytest

URL = os.environ.get("READER_DATABASE_URL")


def _connect(url):
    try:
        conn = psycopg.connect(url, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("database not reachable")  # raises, so conn is always bound below
    return conn


pytestmark = pytest.mark.skipif(not URL, reason="READER_DATABASE_URL not set")


def test_reader_can_read_loaded_tables():
    with _connect(URL) as conn:
        n = conn.execute("SELECT count(*) FROM player_valuations").fetchone()[0]
    assert n > 0


@pytest.mark.parametrize("stmt", [
    "INSERT INTO competitions (competition_id) VALUES ('X')",
    "UPDATE players SET name = 'x' WHERE player_id = 10",
    "DELETE FROM transfers",
    "CREATE TABLE t_reader_probe (x int)",
    "DROP TABLE games",
])
def test_reader_cannot_write_or_change_schema(stmt):
    with _connect(URL) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(stmt)
        conn.rollback()
