"""Stats feature pass (M3a, pre-registered in docs/RESEARCH_LOG.md): position percentiles, availability proxy,
discipline, in-match injury records. All from the previous season's league games in LEAGUES, dated before t.

Sets: P = position percentiles, A = availability (proxy, not "injuries"), D = discipline, I = injury records.
"""
import numpy as np
import pandas as pd

from scout.data.snapshots import LEAGUES, league_games

SETS = {
    "P": ["pct_ga90_pos", "pct_minshare_pos"],
    "A": ["missed_share", "longest_absence"],
    "D": ["cards_per90"],
    "I": ["pct_injury_subs"],
}
ALL_STATS = [c for cols in SETS.values() for c in cols]


def _longest_run(missed: np.ndarray) -> int:
    best = run = 0
    for m in missed:
        run = run + 1 if m else 0
        best = max(best, run)
    return best


def build_stats_features(snaps: pd.DataFrame, base: pd.DataFrame, raw: dict) -> pd.DataFrame:
    """snaps: build_snapshots() rows (player_id, year, date, league). base: build_features() output (needs
    position, prev_ga_per90, share_team_minutes, prev_minutes). Percentiles are within the rows passed in, so pass
    the year's whole population. Returns ALL_STATS aligned to snaps.index."""
    out = pd.DataFrame(index=snaps.index, columns=ALL_STATS, dtype=float)
    key = pd.DataFrame({"year": snaps.year, "position": base.position, "league": snaps.league})

    # P: percentile rank within year x position x league
    out["pct_ga90_pos"] = base.prev_ga_per90.groupby([key.year, key.position, key.league]).rank(pct=True)
    out["pct_minshare_pos"] = base.share_team_minutes.groupby([key.year, key.position, key.league]).rank(pct=True)

    apps, lg = raw["appearances"], league_games(raw["games"])
    lineup_games = set(raw["lineups"].game_id.unique())
    inj = raw["events"][raw["events"].description.fillna("").str.contains("Injury")]
    for (y, t), s in snaps.groupby(["year", "date"]):
        a = apps[apps.competition_id.isin(LEAGUES) & (apps.season == y - 1) & (apps.date < t) & apps.player_id.isin(s.player_id)]
        # D: cards per 90
        cards = a.groupby("player_id")[["yellow_cards", "red_cards"]].sum().sum(axis=1)
        mins = a.groupby("player_id").minutes_played.sum()
        out.loc[s.index, "cards_per90"] = (s.player_id.map(cards) / s.player_id.map(mins) * 90).to_numpy()

        # I: injury-coded substitutions (player taken off), league games of Y-1 before t
        games_y = lg[lg.league.isin(LEAGUES) & (lg.season == y - 1) & (lg.date < t)]
        n_inj = inj[inj.game_id.isin(games_y.game_id)].groupby("player_id").game_id.nunique()
        out.loc[s.index, "_inj"] = s.player_id.map(n_inj).fillna(0).to_numpy()

        # A: availability on the primary club (most league minutes in Y-1)
        primary = a.groupby(["player_id", "player_club_id"]).minutes_played.sum().reset_index() \
                   .sort_values("minutes_played").groupby("player_id").tail(1).set_index("player_id").player_club_id
        club_games = games_y[games_y.game_id.isin(lineup_games)].sort_values("date")
        listed = raw["lineups"][raw["lineups"].game_id.isin(club_games.game_id)]
        listed = set(zip(listed.game_id, listed.player_id, listed.club_id))
        by_club = {c: g.game_id.to_numpy() for c, g in club_games.groupby("club_id")}
        miss, longest = [], []
        for pid in s.player_id:
            club = primary.get(pid)
            games = by_club.get(club) if club is not None else None
            if games is None or len(games) == 0:
                miss.append(np.nan), longest.append(np.nan)
                continue
            in_squad = np.array([(g, pid, club) in listed for g in games])
            if not in_squad.any():
                miss.append(np.nan), longest.append(np.nan)
                continue
            window = ~in_squad[in_squad.argmax():]  # from the first squad listing for this club to the club's last game
            miss.append(window.mean()), longest.append(_longest_run(window))
        out.loc[s.index, "missed_share"] = miss
        out.loc[s.index, "longest_absence"] = longest

    out["pct_injury_subs"] = out["_inj"].groupby([key.year, key.league]).rank(pct=True)
    return out[ALL_STATS]
