import pandas as pd
import pytest

from scout.data.snapshots import build_snapshots
from scout.ml.features import build_features
from scout.ml.stats_features import ALL_STATS, build_stats_features
from test_features import Y, base_raw, d


def stats_raw():
    """base_raw + match-day squads, substitution events and cards for player 1 (club 10, season 2019).
    Club 10's league games are ids 1, 3, 5, ..., 19 (10 games). Player 1 is in the squad for its games 1-5 and 7."""
    r = base_raw()
    club10 = r["games"][(r["games"].home_club_id == 10) & (r["games"].season == 2019)].sort_values("date").game_id.tolist()
    r["lineups"] = pd.DataFrame({"game_id": [club10[i] for i in (0, 1, 2, 3, 4, 6)], "player_id": 1, "club_id": 10})
    # other clubs' squads exist for every game, so all games count as covered by lineup data
    r["lineups"] = pd.concat([r["lineups"], pd.DataFrame({"game_id": r["games"].game_id, "player_id": 99, "club_id": 99})])
    r["events"] = pd.DataFrame({"game_id": [club10[3]], "player_id": [1], "description": ["1. Substitution, Injury"]})
    r["appearances"] = r["appearances"].assign(yellow_cards=[1, 1, 0, 0, 0], red_cards=0)
    return r


def with_future_stats(r):
    """Season-2019 data dated AFTER the snapshot (COVID-style late game) + a 2020-season game: none may count."""
    r = {k: v.copy() for k, v in r.items()}
    late = 5000
    r["games"].loc[len(r["games"])] = (late, 2019, d("2020-09-05"), "GB1", "domestic_league", 10, 99, 0, 3)
    r["appearances"].loc[len(r["appearances"])] = (late, 1, 10, d("2020-09-05"), "GB1", 90, 0, 0, 2019, 0, 1)
    r["lineups"] = pd.concat([r["lineups"], pd.DataFrame({"game_id": [late], "player_id": [99], "club_id": [99]})])
    r["events"] = pd.concat([r["events"], pd.DataFrame({"game_id": [late], "player_id": [1], "description": ["Injury"]})])
    return r


def stats(r):
    s = build_snapshots(r, years=[Y], with_target=False)
    return build_stats_features(s, build_features(s, r), r)


def test_expected_values():
    x = stats(stats_raw()).iloc[0]
    assert x.cards_per90 == pytest.approx(2 / 450 * 90)
    assert x.missed_share == pytest.approx(4 / 10)   # missed games 6, 8, 9, 10 of the club's 10
    assert x.longest_absence == 3                    # games 8-10
    assert x.pct_injury_subs == 1.0 and x.pct_ga90_pos == 1.0 and x.pct_minshare_pos == 1.0


def test_no_leakage_from_data_dated_on_or_after_snapshot():
    pd.testing.assert_frame_equal(stats(stats_raw())[ALL_STATS], stats(with_future_stats(stats_raw()))[ALL_STATS])


def test_no_lineup_data_gives_missing_availability():
    r = stats_raw()
    r["lineups"] = r["lineups"].iloc[0:0]
    x = stats(r).iloc[0]
    assert pd.isna(x.missed_share) and pd.isna(x.longest_absence)
