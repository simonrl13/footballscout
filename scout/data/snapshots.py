"""Annual 1-September snapshots, population and target (docs/SPEC.md).

Everything that defines a snapshot's population uses only data dated on or before t
(match data strictly before t). Only the target looks forward, to the next 1 September.
"""
import numpy as np
import pandas as pd

from scout.data.asof import asof

LEAGUES = ["GB1", "ES1", "L1", "IT1", "FR1", "NL1", "PO1"]
YEARS = list(range(2013, 2025))  # 2024 is the last snapshot whose target lies inside the data
MIN_PREV_MINUTES = 450
LEAGUE_STALE_DAYS = 400  # club's last league game older than this -> league unknown
V0_WINDOW = (335, 425)   # v0 target window, only used for the comparison counts


def snapshot_date(year: int) -> pd.Timestamp:
    return pd.Timestamp(f"{year}-09-01")


def league_games(games: pd.DataFrame) -> pd.DataFrame:
    """One row per (club, domestic league game)."""
    g = games[games.competition_type == "domestic_league"]
    both = pd.concat([
        pd.DataFrame({"club_id": g.home_club_id, "date": g.date, "season": g.season, "league": g.competition_id,
                      "gf": g.home_club_goals, "ga": g.away_club_goals, "game_id": g.game_id}),
        pd.DataFrame({"club_id": g.away_club_id, "date": g.date, "season": g.season, "league": g.competition_id,
                      "gf": g.away_club_goals, "ga": g.home_club_goals, "game_id": g.game_id}),
    ], ignore_index=True)
    return both


def club_from_transfers(ids: pd.Series, at: pd.Series, transfers: pd.DataFrame) -> pd.Series:
    """Club at `at`: destination of the player's last transfer dated on or before `at`."""
    return asof(ids, at, transfers, "player_id", ["to_club_id"], strict=False).to_club_id


def club_from_august_apps(ids: pd.Series, at: pd.Series, apps: pd.DataFrame, league_ids) -> pd.Series:
    """Club of the player's last domestic-league appearance in [1 Aug, at); NaN if none."""
    a = apps[apps.competition_id.isin(league_ids)]
    last = asof(ids, at, a, "player_id", ["player_club_id"])
    return last.player_club_id.where(last.date >= at.apply(lambda d: pd.Timestamp(d.year, 8, 1)))


def club_latest_evidence(ids: pd.Series, at: pd.Series, raw: dict) -> pd.Series:
    """Club at `at` from the most recent of three point-in-time sources: last domestic-league appearance
    before `at`, last transfer on or before `at`, and the club recorded on the last valuation on or before `at`.
    (Chosen 2026-09-29: transfers alone are incomplete before ~2021; see reports/m1_data.md.)"""
    domestic = raw["games"].loc[raw["games"].competition_type == "domestic_league", "competition_id"].unique()
    apps = raw["appearances"][raw["appearances"].competition_id.isin(domestic)]
    sources = [  # order breaks date ties: an appearance beats a transfer beats a valuation
        asof(ids, at, apps, "player_id", ["player_club_id"]).set_axis(["club", "date"], axis=1),
        asof(ids, at, raw["transfers"], "player_id", ["to_club_id"], strict=False).set_axis(["club", "date"], axis=1),
        asof(ids, at, raw["valuations"], "player_id", ["current_club_id"], strict=False).set_axis(["club", "date"], axis=1),
    ]
    # NaT views as the smallest int64, so a missing source never wins argmax
    dates = np.column_stack([s.date.to_numpy("datetime64[ns]").view("int64") for s in sources])
    clubs = np.column_stack([s.club.to_numpy(dtype=float) for s in sources])
    best = dates.argmax(axis=1)
    club = clubs[np.arange(len(best)), best]
    club[(dates == np.iinfo(np.int64).min).all(axis=1)] = np.nan
    return pd.Series(club, index=ids.index)


CLUB_METHODS = {
    "transfers": lambda ids, at, raw: club_from_transfers(ids, at, raw["transfers"]),
    "august_then_transfers": lambda ids, at, raw: club_from_august_apps(
        ids, at, raw["appearances"],
        raw["games"].loc[raw["games"].competition_type == "domestic_league", "competition_id"].unique(),
    ).fillna(club_from_transfers(ids, at, raw["transfers"])),
    "latest_evidence": club_latest_evidence,
}
CLUB_METHOD = "latest_evidence"


def club_at(ids, at, raw, method: str = CLUB_METHOD) -> pd.Series:
    return CLUB_METHODS[method](ids, at, raw)


def club_match_rates(raw: dict, years=YEARS) -> pd.DataFrame:
    """Validation only (looks after t): share of players whose reconstructed club at 1 Sep equals the club they
    played their next league game for within 60 days, per year and method."""
    apps = raw["appearances"]
    rows = []
    for y in years:
        t = snapshot_date(y)
        nxt = apps[apps.competition_id.isin(LEAGUES) & (apps.date >= t) & (apps.date < t + pd.Timedelta(days=60))]
        truth = nxt.sort_values("date").groupby("player_id").player_club_id.first()
        ids = pd.Series(truth.index, index=truth.index)
        at = pd.Series(t, index=truth.index)
        row = {"year": y, "players": len(truth)}
        for m in CLUB_METHODS:
            row[m] = (club_at(ids, at, raw, m) == truth).mean()
        rows.append(row)
    return pd.DataFrame(rows).set_index("year")


def build_snapshots(raw: dict, years=YEARS, club_method: str = CLUB_METHOD, with_target: bool = True,
                    min_prev_minutes: int = MIN_PREV_MINUTES) -> pd.DataFrame:
    """Population snapshots (one row per player and year) with current value and, optionally, the target.

    Population: >= MIN_PREV_MINUTES league minutes in LEAGUES in the previous season, club at t in LEAGUES,
    and a positive valuation on or before t.
    """
    v = raw["valuations"][raw["valuations"].market_value_in_eur > 0].rename(columns={"market_value_in_eur": "value"})
    apps, lg = raw["appearances"], league_games(raw["games"])
    out = []
    for y in years:
        t = snapshot_date(y)
        prev = apps[apps.competition_id.isin(LEAGUES) & (apps.season == y - 1) & (apps.date < t)]
        mins = prev.groupby("player_id").minutes_played.sum()
        s = pd.DataFrame({"player_id": mins.index[mins >= min_prev_minutes]})
        s["year"], s["date"] = y, t
        at = pd.Series(t, index=s.index)
        s["club_id"] = club_at(s.player_id, at, raw, club_method)
        last = asof(s.club_id.fillna(-1).astype("int64"), at, lg, "club_id", ["league"])
        s["league"] = last.league.where(t - last.date <= pd.Timedelta(days=LEAGUE_STALE_DAYS))
        now = asof(s.player_id, at, v, "player_id", ["value"], strict=False)
        s["value_now"], s["value_now_date"] = now.value, now.date
        s["prev_league_minutes"] = s.player_id.map(mins)
        s = s[s.league.isin(LEAGUES) & s.value_now.notna()]

        if with_target:
            t_next = snapshot_date(y + 1)
            nxt = asof(s.player_id, pd.Series(t_next, index=s.index), v, "player_id", ["value"], strict=False)
            s["value_next"], s["value_next_date"] = nxt.value, nxt.date
            s["target"] = np.log(s.value_next / s.value_now).where(s.value_next_date > t)  # >= 1 new valuation in (t, t_next]
            # v0 comparison: first valuation in [t+335, t+425]
            after = v.assign(date=v.date - pd.Timedelta(days=V0_WINDOW[0]))  # shift so "first on/after t+335" is an asof
            first = pd.merge_asof(
                pd.DataFrame({"player_id": s.player_id.values, "_at": t, "_i": np.arange(len(s))}),
                after.sort_values("date"), left_on="_at", right_on="date", by="player_id", direction="forward")
            s["v0_target_ok"] = (first.sort_values("_i").date <= t + pd.Timedelta(days=V0_WINDOW[1] - V0_WINDOW[0])).to_numpy()
        out.append(s)
    return pd.concat(out, ignore_index=True)
