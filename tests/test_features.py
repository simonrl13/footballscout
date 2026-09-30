import numpy as np
import pandas as pd
import pytest

from scout.data.snapshots import build_snapshots
from scout.ml.features import FEATURES, build_features

Y = 2020
T = pd.Timestamp(f"{Y}-09-01")


def d(s):
    return pd.Timestamp(s)


def base_raw():
    """Season 2019 (the previous season for the 2020 snapshot) plus the summer before T.
    Club 10 and club 20 play in GB1; player 1 (club 10) is the snapshot player."""
    g_rows, a_rows = [], []
    gid = 0
    for i in range(10):  # club 10 and club 20 each play 10 league games in season 2019
        for club in (10, 20):
            gid += 1
            g_rows.append((gid, 2019, d("2019-09-10") + pd.Timedelta(days=20 * i), "GB1", "domestic_league", club, 99, 1, 0))
            if club == 10 and i < 5:  # player 1: 5 full games, 1 goal, 1 assist -> 450 minutes
                a_rows.append((gid, 1, 10, g_rows[-1][2], "GB1", 90, int(i == 0), int(i == 1), 2019))
    gid += 1
    g_rows.append((gid, 2020, d("2020-08-20"), "GB1", "domestic_league", 10, 20, 0, 0))  # new season before T
    games = pd.DataFrame(g_rows, columns=["game_id", "season", "date", "competition_id", "competition_type",
                                          "home_club_id", "away_club_id", "home_club_goals", "away_club_goals"])
    return {
        "players": pd.DataFrame({"player_id": [1, 2, 3], "name": ["A", "B", "C"],
                                 "date_of_birth": [d("2000-09-01"), d("1995-01-01"), d("1990-01-01")],
                                 "position": ["Midfield"] * 3, "sub_position": ["Central Midfield"] * 3}),
        "valuations": pd.DataFrame(
            [(1, d("2019-08-01"), 1_000_000, 10), (1, d("2020-06-01"), 2_000_000, 10),
             (2, d("2020-05-01"), 3_000_000, 10), (3, d("2020-05-01"), 5_000_000, 20)],
            columns=["player_id", "date", "market_value_in_eur", "current_club_id"]),
        "transfers": pd.DataFrame([(1, d("2019-10-01"), 5, 10)], columns=["player_id", "date", "from_club_id", "to_club_id"]),
        "appearances": pd.DataFrame(a_rows, columns=["game_id", "player_id", "player_club_id", "date", "competition_id",
                                                     "minutes_played", "goals", "assists", "season"]),
        "games": games,
    }


def with_future(raw):
    """Rows dated on/after T (matches) or after T (valuations, transfers) that would change the snapshot
    and every feature if they leaked in: player 1 moves to club 20, plays a lot, and is revalued at €50m."""
    r = {k: v.copy() for k, v in raw.items()}
    r["valuations"].loc[len(r["valuations"])] = (1, d("2020-10-01"), 50_000_000, 20)
    r["valuations"].loc[len(r["valuations"])] = (3, d("2020-09-02"), 90_000_000, 20)
    r["transfers"].loc[len(r["transfers"])] = (1, d("2020-09-02"), 10, 20)
    for i, when in enumerate([T, d("2020-09-15"), d("2020-10-15")]):
        gid = 1000 + i
        r["games"].loc[len(r["games"])] = (gid, 2020, when, "ES1", "domestic_league", 20, 10, 5, 0)
        r["appearances"].loc[len(r["appearances"])] = (gid, 1, 20, when, "ES1", 90, 3, 3, 2020)
    return r


def snaps_and_features(raw):
    s = build_snapshots(raw, years=[Y], with_target=False)
    return s, build_features(s, raw)


def test_expected_values():
    s, f = snaps_and_features(base_raw())
    assert list(s.player_id) == [1]  # players 2 and 3 have no previous-season minutes
    row, x = s.iloc[0], f.iloc[0]
    assert (row.club_id, row.league, row.value_now) == (10, "GB1", 2_000_000)
    assert x.age == pytest.approx(20.0, abs=0.01)
    assert x.log_value_now == pytest.approx(np.log(2_000_000))
    assert x.value_change_12m == pytest.approx(np.log(2))  # vs the latest valuation on/before t - 365 d
    assert (x.prev_minutes, x.prev_apps) == (450, 5)
    assert x.prev_ga_per90 == pytest.approx(2 / 450 * 90)
    assert x.share_team_minutes == pytest.approx(450 / (90 * 10))
    assert x.log_squad_value == pytest.approx(np.log(2_000_000 + 3_000_000))  # players 1 and 2 at club 10
    assert x.club_moves_12m == 1
    assert (x.position, x.league) == ("Midfield", "GB1")


def test_no_leakage_from_data_on_or_after_snapshot():
    s0, f0 = snaps_and_features(base_raw())
    s1, f1 = snaps_and_features(with_future(base_raw()))
    cols = ["player_id", "club_id", "league", "value_now", "prev_league_minutes"]
    pd.testing.assert_frame_equal(s0[cols], s1[cols])
    pd.testing.assert_frame_equal(f0[FEATURES], f1[FEATURES])


def test_future_rows_do_matter_for_a_later_snapshot():
    # sanity check that the leakage test is meaningful
    r = with_future(base_raw())
    s = build_snapshots(r, years=[Y], with_target=False)
    s = s.assign(date=d("2020-09-15"))  # same player, later as-of date: both transfers are inside 12 months
    s["club_id"] = 20.0
    f = build_features(s, r).iloc[0]
    assert f.club_moves_12m == 2
    assert f.log_squad_value > np.log(50_000_000)


def test_target_uses_latest_valuation_before_next_snapshot():
    r = base_raw()
    r["valuations"].loc[len(r["valuations"])] = (1, d("2021-03-01"), 3_000_000, 10)
    r["valuations"].loc[len(r["valuations"])] = (1, d("2021-08-01"), 4_000_000, 10)
    r["valuations"].loc[len(r["valuations"])] = (1, d("2021-09-02"), 99_000_000, 10)  # after the next 1 Sep: ignored
    s = build_snapshots(r, years=[Y])
    assert s.iloc[0].value_next == 4_000_000
    assert s.iloc[0].target == pytest.approx(np.log(4_000_000 / 2_000_000))


def test_target_dropped_without_a_new_valuation():
    s = build_snapshots(base_raw(), years=[Y])
    assert s.iloc[0].value_next == 2_000_000  # the as-of value exists, but it's the same old valuation
    assert np.isnan(s.iloc[0].target)
