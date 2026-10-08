"""Tools and roles against the real database (skipped when it isn't reachable or the demo table isn't built)."""
import os

import psycopg
import pytest

from scout.agent import tools


def _ready() -> bool:
    try:
        with tools.connect() as c:
            return c.execute("SELECT count(*) AS n FROM demo_players").fetchone()["n"] > 0
    except (KeyError, psycopg.Error):
        return False


pytestmark = pytest.mark.skipif(not _ready(), reason="database or demo_players not available")


def test_search_is_accent_insensitive_and_bounded():
    with tools.connect() as c:
        out = tools.search_players(c, tools.Search(name="mbappe", limit=5))
        assert any(p["name"].startswith("Kylian Mbapp") for p in out["players"])
        assert tools.search_players(c, tools.Search(name="%_", limit=3))["count"] == 0  # no wildcard injection
        assert tools.search_players(c, tools.Search(limit=20))["count"] == 20


def test_tools_run_in_a_read_only_transaction():
    with tools.connect() as c:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            c.execute("UPDATE demo_players SET name = 'x' WHERE player_id = 1")


def test_unknown_player_is_an_error_not_an_exception():
    with tools.connect() as c:
        assert "error" in tools.predict_value_change(c, tools.PlayerId(player_id=99_999_999))


@pytest.mark.skipif(not os.environ.get("TRACER_DATABASE_URL"), reason="TRACER_DATABASE_URL not set")
def test_tracer_role_cannot_touch_project_data():
    with psycopg.connect(os.environ["TRACER_DATABASE_URL"], connect_timeout=5) as c:
        for stmt in ["SELECT 1 FROM players LIMIT 1", "SELECT 1 FROM demo_players LIMIT 1", "DELETE FROM agent_calls",
                     "UPDATE agent_calls SET cost_usd = 0", "CREATE TABLE t_tracer_probe (x int)"]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(stmt)
            c.rollback()
