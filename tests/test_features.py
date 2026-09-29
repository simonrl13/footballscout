import numpy as np
import pandas as pd
import pytest

from scout.ml.features import FEATURES, build_features

T = pd.Timestamp("2020-01-01")


def d(days):
    return T + pd.Timedelta(days=days)


def raw_upto_t():
    """History for player 1 (club 10, GB1) strictly before T, plus the snapshot valuation at T."""
    wins = [(d(x), "GB1", "domestic_league", 10, 99, 2, 0) for x in (-300, -250, -200, -150)]
    draws = [(d(x), "GB1", "domestic_league", 99, 10, 1, 1) for x in (-100, -50)]
    return {
        "players": pd.DataFrame({"player_id": [1], "date_of_birth": [pd.Timestamp("2000-01-01")],
                                 "position": ["Attack"], "sub_position": ["Centre-Forward"]}),
        "valuations": pd.DataFrame(
            [(1, d(-400), 1_000_000, 10), (1, d(-200), 2_000_000, 10), (1, d(-100), 3_000_000, 10), (1, T, 4_000_000, 10)],
            columns=["player_id", "date", "market_value_in_eur", "current_club_id"]),
        "appearances": pd.DataFrame(
            [(1, d(-400), 90, 1, 0), (1, d(-200), 90, 1, 1), (1, d(-150), 90, 0, 0), (1, d(-100), 60, 0, 1), (1, d(-50), 90, 0, 0)],
            columns=["player_id", "date", "minutes_played", "goals", "assists"]),
        "games": pd.DataFrame(wins + draws, columns=["date", "competition_id", "competition_type", "home_club_id",
                                                     "away_club_id", "home_club_goals", "away_club_goals"]),
    }


def with_future(raw):
    """Add data dated on or after T that would change every feature if it leaked in."""
    r = {k: v.copy() for k, v in raw.items()}
    r["valuations"] = pd.concat([r["valuations"], pd.DataFrame(
        [(1, d(30), 90_000_000, 10)], columns=r["valuations"].columns)], ignore_index=True)
    r["appearances"] = pd.concat([r["appearances"], pd.DataFrame(
        [(1, d(x), 90, 3, 3) for x in (0, 1, 10, 100)], columns=r["appearances"].columns)], ignore_index=True)
    r["games"] = pd.concat([r["games"], pd.DataFrame(
        [(d(x), "ES1", "domestic_league", 10, 99, 0, 5) for x in (0, 1, 10, 100)], columns=r["games"].columns)],
        ignore_index=True)
    return r


SNAP = pd.DataFrame({"player_id": [1], "date": [T]})


def test_expected_values():
    f = build_features(SNAP, raw_upto_t()).iloc[0]
    assert f.age == pytest.approx(20.0, abs=0.01)
    assert f.log_value_now == pytest.approx(np.log(4_000_000))
    # momentum uses the last valuation on/before t-182 (t-200), not the more recent t-100 one
    assert f.value_momentum_6m == pytest.approx(np.log(2))
    # 12m window [t-365, t): -200, -150, -100, -50 -> 330 min; the t-400 appearance is excluded
    assert f.minutes_12m == 330
    assert f.minutes_6m == 240  # [t-182, t): -150, -100, -50
    assert f.minutes_trend == 240 - 90
    assert f.ga_per90_12m == pytest.approx(3 / 330 * 90)
    assert f.league == "GB1"
    assert f.club_ppg_12m == pytest.approx((4 * 3 + 2 * 1) / 6)
    assert (f.position, f.sub_position) == ("Attack", "Centre-Forward")


def test_no_leakage_from_data_on_or_after_snapshot_date():
    before = build_features(SNAP, raw_upto_t())
    after = build_features(SNAP, with_future(raw_upto_t()))
    pd.testing.assert_frame_equal(before[FEATURES], after[FEATURES])


def test_later_snapshot_does_see_that_data():
    # sanity check that the leakage test is meaningful: the future rows do change features at a later date
    f = build_features(pd.DataFrame({"player_id": [1], "date": [d(30)]}), with_future(raw_upto_t())).iloc[0]
    assert f.league == "ES1"
    assert f.minutes_6m > 240


def test_stale_league_becomes_unknown():
    raw = raw_upto_t()
    raw["valuations"].loc[len(raw["valuations"])] = (1, d(500), 4_000_000, 10)
    f = build_features(pd.DataFrame({"player_id": [1], "date": [d(500)]}), raw).iloc[0]
    assert f.league == "unknown"


def test_preserves_input_index_and_order():
    snaps = pd.DataFrame({"player_id": [1, 1], "date": [T, d(-200)]}, index=[7, 3])
    f = build_features(snaps, raw_upto_t())
    assert list(f.index) == [7, 3]
    assert f.loc[7, "log_value_now"] == pytest.approx(np.log(4_000_000))
    assert f.loc[3, "log_value_now"] == pytest.approx(np.log(2_000_000))
