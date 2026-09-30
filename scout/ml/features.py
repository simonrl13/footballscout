"""Baseline features for 1-September snapshots (docs/SPEC.md).

For a snapshot at t: valuations and transfers count if dated on or before t; match data
(appearances, games) only if dated strictly before t. Nothing else about the future is read.
"""
import numpy as np
import pandas as pd

from scout.data.asof import asof, window_sum
from scout.data.snapshots import LEAGUES, club_at, league_games

NUMERIC = ["age", "log_value_now", "value_change_12m", "prev_minutes", "prev_apps", "prev_ga_per90",
           "share_team_minutes", "log_squad_value", "club_moves_12m"]
CATEGORICAL = ["position", "sub_position", "league"]
FEATURES = NUMERIC + CATEGORICAL
ACTIVE_DAYS = 365  # a player counts towards squad value if valued within this many days before t


def _prev_season(snaps: pd.DataFrame, raw: dict) -> pd.DataFrame:
    """Previous-season league stats (LEAGUES only) per snapshot row."""
    apps, lg = raw["appearances"], league_games(raw["games"])
    rows = []
    for (y, t), s in snaps.groupby(["year", "date"]):
        a = apps[apps.competition_id.isin(LEAGUES) & (apps.season == y - 1) & (apps.date < t)
                 & apps.player_id.isin(s.player_id)]
        per_club = a.groupby(["player_id", "player_club_id"]).minutes_played.sum().rename("club_minutes").reset_index()
        primary = per_club.sort_values("club_minutes").groupby("player_id").tail(1)  # club with the most minutes
        games = lg[lg.league.isin(LEAGUES) & (lg.season == y - 1) & (lg.date < t)].groupby("club_id").size()
        primary = primary.assign(team_games=primary.player_club_id.map(games))
        tot = a.groupby("player_id").agg(prev_minutes=("minutes_played", "sum"), prev_apps=("game_id", "nunique"),
                                         goals=("goals", "sum"), assists=("assists", "sum"))
        tot = tot.join(primary.set_index("player_id")[["club_minutes", "team_games"]])
        rows.append(s[["player_id"]].join(tot, on="player_id"))
    out = pd.concat(rows).reindex(snaps.index)
    out["prev_ga_per90"] = ((out.goals + out.assists) / out.prev_minutes * 90).where(out.prev_minutes > 0)
    # ponytail: share uses the primary club only; a mid-season mover's share is understated
    out["share_team_minutes"] = out.club_minutes / (90 * out.team_games)
    return out[["prev_minutes", "prev_apps", "prev_ga_per90", "share_team_minutes"]].fillna(
        {"prev_minutes": 0, "prev_apps": 0})


def _squad_value(snaps: pd.DataFrame, raw: dict) -> pd.Series:
    """Sum of as-of values of the players at the snapshot club, among players valued in the last ACTIVE_DAYS."""
    v = raw["valuations"][raw["valuations"].market_value_in_eur > 0]
    out = pd.Series(np.nan, index=snaps.index)
    for t, s in snaps.groupby("date"):
        recent = v[(v.date <= t) & (v.date > t - pd.Timedelta(days=ACTIVE_DAYS))]
        ids = pd.Series(recent.player_id.unique())
        at = pd.Series(t, index=ids.index)
        squad = pd.DataFrame({
            "club_id": club_at(ids, at, raw).to_numpy(),
            "value": asof(ids, at, v, "player_id", ["market_value_in_eur"], strict=False).market_value_in_eur.to_numpy(),
        }).groupby("club_id").value.sum()
        out.loc[s.index] = s.club_id.map(squad)
    return out


def build_features(snaps: pd.DataFrame, raw: dict) -> pd.DataFrame:
    """snaps: build_snapshots() rows (player_id, year, date, club_id, league, value_now). Returns FEATURES
    aligned to snaps.index."""
    v = raw["valuations"][raw["valuations"].market_value_in_eur > 0]
    f = snaps[["player_id", "league"]].join(
        snaps[["player_id"]].merge(raw["players"], on="player_id", how="left").set_index(snaps.index)
        [["date_of_birth", "position", "sub_position"]])
    f["age"] = (snaps.date - f.date_of_birth).dt.days / 365.25
    f["log_value_now"] = np.log(snaps.value_now)
    year_ago = asof(snaps.player_id, snaps.date - pd.Timedelta(days=365), v, "player_id", ["market_value_in_eur"],
                    strict=False).market_value_in_eur
    f["value_change_12m"] = f.log_value_now - np.log(year_ago)
    f = f.join(_prev_season(snaps, raw))
    f["log_squad_value"] = np.log(_squad_value(snaps, raw))
    # transfers dated in (t - 365 d, t]
    moves = raw["transfers"].assign(n=1)
    f["club_moves_12m"] = window_sum(snaps.player_id, snaps.date + pd.Timedelta(days=1), moves, "player_id", ["n"], 365).n
    out = f[FEATURES].copy()
    out[CATEGORICAL] = out[CATEGORICAL].fillna("unknown")
    return out
