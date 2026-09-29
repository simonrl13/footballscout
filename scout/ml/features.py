"""Point-in-time features for valuation snapshots.

Every feature for a snapshot at date t uses only data dated strictly before t,
except the snapshot's own valuation (value and club at t), which is known at t.
"""
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

# Leagues with match data (games/appearances) from 2012-13 onward. The other domestic leagues in
# games.csv only start in 2024-25, so minutes/league/club features would be missing for them.
CORE_LEAGUES = ["GB1", "ES1", "IT1", "L1", "FR1", "NL1", "PO1", "BE1", "TR1", "RU1", "UKR1", "GR1", "SC1", "DK1"]
FIRST_SNAPSHOT = pd.Timestamp("2013-07-01")  # one full year after match data begins (2012-07)

NUMERIC = ["age", "log_value_now", "value_momentum_6m", "minutes_6m", "minutes_12m", "minutes_trend",
           "ga_per90_12m", "club_ppg_12m"]
CATEGORICAL = ["position", "sub_position", "league"]
FEATURES = NUMERIC + CATEGORICAL

LEAGUE_STALE_DAYS = 400  # club's last league game older than this -> league unknown (e.g. relegated out of coverage)
MIN_MINUTES_PER90 = 270
MIN_CLUB_GAMES = 5


def read_raw() -> dict[str, pd.DataFrame]:
    return {
        "valuations": pd.read_csv(RAW / "player_valuations.csv", parse_dates=["date"],
                                  usecols=["player_id", "date", "market_value_in_eur", "current_club_id"]),
        # position/sub_position are the player's current values; they rarely change over a career
        "players": pd.read_csv(RAW / "players.csv", parse_dates=["date_of_birth"],
                               usecols=["player_id", "date_of_birth", "position", "sub_position"]),
        "appearances": pd.read_csv(RAW / "appearances.csv", parse_dates=["date"],
                                   usecols=["player_id", "date", "minutes_played", "goals", "assists"]),
        "games": pd.read_csv(RAW / "games.csv", parse_dates=["date"],
                             usecols=["date", "competition_id", "competition_type", "home_club_id", "away_club_id",
                                      "home_club_goals", "away_club_goals"]),
    }


def _asof(ids: pd.Series, at: pd.Series, events: pd.DataFrame, by: str, cols: list[str], strict=True) -> pd.DataFrame:
    """For each (id, at): the last `events` row with the same id and date < at (<= at if not strict).
    Returns cols + event date, aligned to ids.index; NaN where there is none."""
    left = pd.DataFrame({by: ids.values, "_at": at.values, "_i": np.arange(len(ids))}).sort_values("_at", kind="stable")
    right = events[[by, "date", *cols]].sort_values("date", kind="stable")
    m = pd.merge_asof(left, right, left_on="_at", right_on="date", by=by, allow_exact_matches=not strict)
    return m.sort_values("_i")[[*cols, "date"]].set_index(ids.index)


def _window_sum(ids: pd.Series, at: pd.Series, events: pd.DataFrame, by: str, cols: list[str], days: int) -> pd.DataFrame:
    """Sum of cols over events with the same id and date in [at - days, at)."""
    ev = events.sort_values([by, "date"], kind="stable")
    ev = ev[[by, "date"]].join(ev.groupby(by)[cols].cumsum())
    upto_now = _asof(ids, at, ev, by, cols)[cols].fillna(0)
    upto_start = _asof(ids, at - pd.Timedelta(days=days), ev, by, cols)[cols].fillna(0)
    return upto_now - upto_start


def _club_league_games(games: pd.DataFrame) -> pd.DataFrame:
    g = games[games.competition_type == "domestic_league"]
    both = pd.concat([
        pd.DataFrame({"club_id": g.home_club_id, "date": g.date, "league": g.competition_id,
                      "gf": g.home_club_goals, "ga": g.away_club_goals}),
        pd.DataFrame({"club_id": g.away_club_id, "date": g.date, "league": g.competition_id,
                      "gf": g.away_club_goals, "ga": g.home_club_goals}),
    ], ignore_index=True)
    both["pts"] = np.select([both.gf > both.ga, both.gf == both.ga], [3, 1], 0)
    both["n"] = 1
    return both


def build_features(snaps: pd.DataFrame, raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """snaps: player_id, date - each must be an existing valuation. Returns FEATURES aligned to snaps.index."""
    v = raw["valuations"].assign(value=lambda d: d.market_value_in_eur.where(d.market_value_in_eur > 0))
    # left merges on unique keys keep snaps' row order, so the original index can be restored
    s = snaps[["player_id", "date"]].merge(v[["player_id", "date", "value", "current_club_id"]],
                                           on=["player_id", "date"], how="left")
    s = s.merge(raw["players"], on="player_id", how="left")
    s.index = snaps.index

    s["age"] = (s.date - s.date_of_birth).dt.days / 365.25
    s["log_value_now"] = np.log(s.value)
    past = _asof(s.player_id, s.date - pd.Timedelta(days=182), v, "player_id", ["value"], strict=False)
    s["value_momentum_6m"] = s.log_value_now - np.log(past.value)

    app = raw["appearances"].assign(ga=lambda d: d.goals + d.assists)
    w12 = _window_sum(s.player_id, s.date, app, "player_id", ["minutes_played", "ga"], 365)
    w6 = _window_sum(s.player_id, s.date, app, "player_id", ["minutes_played"], 182)
    s["minutes_12m"] = w12.minutes_played
    s["minutes_6m"] = w6.minutes_played
    s["minutes_trend"] = s.minutes_6m - (s.minutes_12m - s.minutes_6m)
    s["ga_per90_12m"] = (w12.ga / s.minutes_12m * 90).where(s.minutes_12m >= MIN_MINUTES_PER90)

    cg = _club_league_games(raw["games"])
    last = _asof(s.current_club_id, s.date, cg, "club_id", ["league"])
    s["league"] = last.league.where(s.date - last.date <= pd.Timedelta(days=LEAGUE_STALE_DAYS))
    club = _window_sum(s.current_club_id, s.date, cg, "club_id", ["pts", "n"], 365)
    s["club_ppg_12m"] = (club.pts / club.n).where(club.n >= MIN_CLUB_GAMES)

    out = s[FEATURES].copy()
    out[CATEGORICAL] = out[CATEGORICAL].fillna("unknown")
    return out


def in_scope(snaps: pd.DataFrame, feats: pd.DataFrame) -> pd.Series:
    """Snapshots the model is trained/evaluated on: core league at t, with a full year of match history."""
    return (snaps.date >= FIRST_SNAPSHOT) & feats.league.isin(CORE_LEAGUES)
