import numpy as np
import pandas as pd

from scout.data.target import MAX_DAYS, MIN_DAYS, build_targets

T0 = pd.Timestamp("2020-01-01")


def vals(*rows):
    """rows: (player_id, days_after_T0, value)"""
    return pd.DataFrame(
        [(p, T0 + pd.Timedelta(days=d), v) for p, d, v in rows],
        columns=["player_id", "date", "market_value_in_eur"],
    )


def target_at(df, player_id=1, day=0):
    r = df[(df.player_id == player_id) & (df.date == T0 + pd.Timedelta(days=day))]
    return None if r.empty else r.iloc[0]


def test_computes_log_ratio():
    r = target_at(build_targets(vals((1, 0, 1_000_000), (1, 365, 2_000_000))))
    assert r.value_now == 1_000_000 and r.value_future == 2_000_000
    assert np.isclose(r.target, np.log(2))


def test_window_boundaries_inclusive():
    assert target_at(build_targets(vals((1, 0, 100), (1, MIN_DAYS, 200)))) is not None
    assert target_at(build_targets(vals((1, 0, 100), (1, MAX_DAYS, 200)))) is not None
    assert target_at(build_targets(vals((1, 0, 100), (1, MIN_DAYS - 1, 200)))) is None
    assert target_at(build_targets(vals((1, 0, 100), (1, MAX_DAYS + 1, 200)))) is None


def test_uses_first_valuation_in_window():
    r = target_at(build_targets(vals((1, 0, 100), (1, 200, 999), (1, 340, 150), (1, 400, 300))))
    assert r.value_future == 150
    assert r.future_date == T0 + pd.Timedelta(days=340)


def test_first_valuation_after_window_start_too_late_drops_snapshot():
    # a later valuation exists, but the first one on/after t+MIN_DAYS is beyond t+MAX_DAYS
    assert target_at(build_targets(vals((1, 0, 100), (1, 500, 200)))) is None


def test_never_uses_another_players_valuation():
    out = build_targets(vals((1, 0, 100), (2, 0, 50), (2, 365, 500)))
    assert target_at(out, player_id=1) is None
    assert target_at(out, player_id=2).value_future == 500


def test_zero_values_excluded():
    assert target_at(build_targets(vals((1, 0, 0), (1, 365, 200)))) is None
    # zero future value is skipped; the next valid one in the window is used
    r = target_at(build_targets(vals((1, 0, 100), (1, 350, 0), (1, 380, 300))))
    assert r.value_future == 300


def test_every_target_horizon_within_window_on_random_data():
    rng = np.random.default_rng(0)
    rows = [(p, int(d), int(rng.integers(1, 10**8))) for p in range(50) for d in np.unique(rng.integers(0, 3000, 20))]
    out = build_targets(vals(*rows))
    gap = (out.future_date - out.date).dt.days
    assert len(out) > 0
    assert gap.between(MIN_DAYS, MAX_DAYS).all()
    # value_now is exactly the valuation at the snapshot date
    src = vals(*rows).rename(columns={"market_value_in_eur": "v"})
    merged = out.merge(src, on=["player_id", "date"])
    assert (merged.v == merged.value_now).all() and len(merged) == len(out)
