"""Database role checks. Run with the DB up: uv run --env-file .env pytest tests/test_db.py
Skipped when READER_DATABASE_URL is unset or the database is unreachable."""
import os

import psycopg
import pytest

URL = os.environ.get("READER_DATABASE_URL")


def _reachable() -> bool:
    if not URL:
        return False
    try:
        psycopg.connect(URL, connect_timeout=3).close()
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="READER_DATABASE_URL not set or database not reachable")


def test_reader_can_read_loaded_tables():
    with psycopg.connect(URL, connect_timeout=5) as conn:
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
    with psycopg.connect(URL, connect_timeout=5) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(stmt)
        conn.rollback()
