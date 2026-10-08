"""The four read-only tools shared by the REST API and the agent (and later the MCP server).

Every input is a Pydantic model with limits; every query is parameterized (identifiers via psycopg.sql) and runs on
the read-only role (scout_reader) in a read-only transaction. Outputs are rounded to what an answer should quote, so
the agent copies numbers instead of computing them (the number check in scout/agent/numbers.py relies on this).
"""
import math
import os
from typing import Literal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from scout.text.linker import fold

DEMO_AS_OF = "2026-06-12"
LEAGUE_NAMES = {"GB1": "Premier League", "ES1": "LaLiga", "L1": "Bundesliga", "IT1": "Serie A", "FR1": "Ligue 1",
                "NL1": "Eredivisie", "PO1": "Liga Portugal"}
FEATURE_LABELS = {
    "age": "age (years)", "log_value_now": "current market value",
    "value_change_12m": "value change over the last 12 months", "prev_minutes": "league minutes last season",
    "prev_apps": "league appearances last season", "prev_ga_per90": "goals + assists per 90 last season",
    "share_team_minutes": "share of the club's league minutes last season", "log_squad_value": "club squad value",
    "club_moves_12m": "club moves in the last 12 months", "position": "position", "sub_position": "detailed position",
    "league": "league",
}
SOURCE = ("Market values are Transfermarkt crowd estimates, not transfer fees. Forecasts are model output "
          f"(LightGBM, 80% split-conformal interval) from data as of {DEMO_AS_OF}. The model was trained and validated "
          "on 1-September snapshots; this June snapshot is a demo.")
NOT_FOUND = f"not in the demo population (players in the 7 covered leagues as of {DEMO_AS_OF})"
COLUMNS = ["player_id", "name", "club", "league", "position", "sub_position", "age", "value_eur", "value_date", "as_of",
           "predicted_log_change", "interval_low_log", "interval_high_log", "factors"]
SORTS = {"predicted_change_desc": ("predicted_log_change", "DESC"), "predicted_change_asc": ("predicted_log_change", "ASC"),
         "value_desc": ("value_eur", "DESC"), "name": ("name", "ASC")}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlayerId(Strict):
    """One player from the demo population (players in the 7 covered leagues, data as of 2026-06-12)."""
    player_id: int = Field(ge=1, le=10**8, description="Transfermarkt player id, e.g. from search_players")


class Search(Strict):
    """Find players by name and/or filters. Returns at most `limit` players, each with a player_id."""
    name: str | None = Field(None, min_length=2, max_length=60, description="part of the player's name; accents optional")
    league: Literal["GB1", "ES1", "L1", "IT1", "FR1", "NL1", "PO1"] | None = Field(
        None, description="GB1 Premier League, ES1 LaLiga, L1 Bundesliga, IT1 Serie A, FR1 Ligue 1, NL1 Eredivisie, "
                          "PO1 Liga Portugal")
    position: Literal["Attack", "Midfield", "Defender", "Goalkeeper"] | None = None
    min_age: float | None = Field(None, ge=15, le=45)
    max_age: float | None = Field(None, ge=15, le=45)
    min_value_eur_m: float | None = Field(None, ge=0, le=500, description="minimum market value, EUR millions")
    max_value_eur_m: float | None = Field(None, ge=0, le=500, description="maximum market value, EUR millions")
    sort_by: Literal["predicted_change_desc", "predicted_change_asc", "value_desc", "name"] = "value_desc"
    limit: int = Field(10, ge=1, le=20)


class Compare(Strict):
    """Side-by-side profile and 12-month forecast for 2 to 5 players."""
    player_ids: list[int] = Field(min_length=2, max_length=5, description="Transfermarkt player ids")


def connect() -> psycopg.Connection:
    conn = psycopg.connect(os.environ["READER_DATABASE_URL"], connect_timeout=5, row_factory=dict_row)
    conn.read_only = True
    return conn


def _pct(log_change: float | None) -> float | None:
    return None if log_change is None else round(math.expm1(log_change) * 100, 1)


def _m(eur: float | None) -> float | None:
    return None if eur is None else round(eur / 1e6, 1)


def _profile(r: dict) -> dict:
    return {"player_id": r["player_id"], "name": r["name"], "club": r["club"],
            "league": LEAGUE_NAMES.get(r["league"], r["league"]), "position": r["position"],
            "detailed_position": r["sub_position"], "age": round(r["age"], 1), "market_value_eur_m": _m(r["value_eur"]),
            "valuation_date": str(r["value_date"]), "data_as_of": str(r["as_of"])}


def _forecast(r: dict) -> dict:
    v, lo, hi = r["value_eur"], r["interval_low_log"], r["interval_high_log"]
    return {
        "horizon": "12 months",
        "predicted_change_pct": _pct(r["predicted_log_change"]),
        "interval_80_pct": None if lo is None else {"low": _pct(lo), "high": _pct(hi)},
        "implied_value_eur_m": {"predicted": _m(v * math.exp(r["predicted_log_change"])),
                                "low": None if lo is None else _m(v * math.exp(lo)),
                                "high": None if hi is None else _m(v * math.exp(hi))},
        "top_factors": [{"factor": FEATURE_LABELS.get(f["feature"], f["feature"]), "player_value": _readable(f),
                         "effect": "raises" if f["shap"] > 0 else "lowers", "shap_log": round(f["shap"], 3)}
                        for f in r["factors"]],
    }


def _readable(f: dict):
    """Factor values as an answer would quote them: log values back to EUR millions / %, league codes to names."""
    v = f["value"]
    if v is None or isinstance(v, str):
        return LEAGUE_NAMES.get(v, v)
    if f["feature"] in ("log_value_now", "log_squad_value"):
        return f"EUR {_m(math.exp(v))}m"
    if f["feature"] == "value_change_12m":
        return f"{_pct(v)}%"
    return round(v, 2)


def _rows(conn, where: sql.Composable, params: tuple, tail: sql.Composable = sql.SQL("")) -> list[dict]:
    q = sql.SQL("SELECT {} FROM demo_players WHERE {}{}").format(
        sql.SQL(", ").join(map(sql.Identifier, COLUMNS)), where, tail)
    return conn.execute(q, params).fetchall()


def get_player(conn, a: PlayerId) -> dict:
    rows = _rows(conn, sql.SQL("player_id = %s"), (a.player_id,))
    if not rows:
        return {"error": f"player_id {a.player_id} is {NOT_FOUND}"}
    return {**_profile(rows[0]), "source": SOURCE}


def predict_value_change(conn, a: PlayerId) -> dict:
    rows = _rows(conn, sql.SQL("player_id = %s"), (a.player_id,))
    if not rows:
        return {"error": f"player_id {a.player_id} is {NOT_FOUND}"}
    return {**_profile(rows[0]), "forecast": _forecast(rows[0]), "source": SOURCE}


def search_players(conn, a: Search) -> dict:
    where, params = [sql.SQL("TRUE")], []
    filters = [("name_search", "strpos", a.name and fold(a.name)), ("league", "=", a.league), ("position", "=", a.position),
               ("age", ">=", a.min_age), ("age", "<=", a.max_age),
               ("value_eur", ">=", None if a.min_value_eur_m is None else a.min_value_eur_m * 1e6),
               ("value_eur", "<=", None if a.max_value_eur_m is None else a.max_value_eur_m * 1e6)]
    for col, op, val in filters:
        if val is None:
            continue
        if op == "strpos":
            where.append(sql.SQL("strpos({}, %s) > 0").format(sql.Identifier(col)))
        else:
            where.append(sql.SQL("{} {} %s").format(sql.Identifier(col), sql.SQL(op)))  # op is a constant above
        params.append(val)
    col, direction = SORTS[a.sort_by]
    tail = sql.SQL(" ORDER BY {} {}, player_id LIMIT %s").format(sql.Identifier(col), sql.SQL(direction))
    rows = _rows(conn, sql.SQL(" AND ").join(where), (*params, a.limit), tail)
    return {"count": len(rows),
            "players": [{**_profile(r), "predicted_change_pct": _pct(r["predicted_log_change"]),
                         "interval_80_pct": {"low": _pct(r["interval_low_log"]), "high": _pct(r["interval_high_log"])}}
                        for r in rows],
            "source": SOURCE}


def compare_players(conn, a: Compare) -> dict:
    ids = list(dict.fromkeys(a.player_ids))
    rows = {r["player_id"]: r for r in _rows(conn, sql.SQL("player_id = ANY(%s)"), (ids,))}
    return {"players": [{**_profile(rows[p]), "forecast": _forecast(rows[p])} for p in ids if p in rows],
            "not_found": [p for p in ids if p not in rows], "source": SOURCE}


TOOLS = {"get_player": (get_player, PlayerId), "predict_value_change": (predict_value_change, PlayerId),
         "search_players": (search_players, Search), "compare_players": (compare_players, Compare)}


def tool_specs() -> list[dict]:
    """Tool definitions for the Claude API, generated from the Pydantic models."""
    return [{"name": name, "description": model.__doc__, "input_schema": model.model_json_schema()}
            for name, (_, model) in TOOLS.items()]


def run_tool(conn, name: str, args: dict) -> dict:
    """Validate and run one tool call. KeyError for an unknown tool, pydantic.ValidationError for bad input."""
    fn, model = TOOLS[name]
    return fn(conn, model.model_validate(args))
