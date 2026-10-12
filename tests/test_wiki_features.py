import numpy as np
import pandas as pd
import pytest

from scout.text.wiki_features import CONTRACT, MOVES, build_wiki_features

T = pd.Timestamp("2020-09-01")
SNAPS = pd.DataFrame({"player_id": [1, 2], "date": [T, T]})


def sig(rows):
    return pd.DataFrame(rows, columns=["player_id", "available_at", "signal_type", "event_date", "date_precision"])


BASE = sig([
    # 2018 page: "signed until June 2021" (an old statement, outside any 12-month window, still known at t)
    (1, "2018-08-10T12:00:00Z", "contract_until", "2021-06-01", "month"),
    # 2020 page: extended until 2023 (year only -> 30 June 2023), plus a loan and an injury in the window
    (1, "2020-08-20T12:00:00Z", "contract_until", "2023-01-01", "year"),
    (1, "2020-08-20T12:00:00Z", "contract_extension", "2020-02-14", "day"),
    (1, "2020-08-20T12:00:00Z", "loan", "2020-01-31", "day"),
    (1, "2020-08-20T12:00:00Z", "injury", "2019-11-01", "month"),
    # an event before the window does not count in the 12-month counts
    (1, "2020-08-20T12:00:00Z", "transfer", "2019-07-01", "day"),
])


def test_expected_values_and_missing_indicator():
    f = build_wiki_features(SNAPS, BASE)
    a, b = f.iloc[0], f.iloc[1]
    assert a.contract_years_left == pytest.approx((pd.Timestamp("2023-06-30") - T).days / 365.25)  # latest end date
    assert a.contract_known == 1 and a.contract_ext_12m == 1 and a.text_loans_12m == 1 and a.text_transfers_12m == 0
    assert a.text_injuries_12m == 1
    assert np.isnan(b.contract_years_left) and b.contract_known == 0  # player 2: nothing stated -> missing


def test_no_statement_or_event_published_on_or_after_the_snapshot_is_used():
    future = sig([
        (1, "2020-09-01T00:00:00Z", "contract_until", "2026-06-01", "month"),  # published exactly at t
        (1, "2020-10-05T09:00:00Z", "contract_until", "2027-06-01", "month"),  # after t
        (1, "2020-10-05T09:00:00Z", "contract_extension", "2020-08-30", "day"),  # dated in the window, published after t
        (1, "2020-10-05T09:00:00Z", "transfer", "2020-08-15", "day"),
        (2, "2021-02-01T09:00:00Z", "contract_until", "2024-06-01", "month"),
    ])
    pd.testing.assert_frame_equal(build_wiki_features(SNAPS, BASE), build_wiki_features(SNAPS, pd.concat([BASE, future])))


def test_the_same_future_rows_do_count_for_a_later_snapshot():
    later = pd.DataFrame({"player_id": [1], "date": [pd.Timestamp("2021-09-01")]})
    future = sig([(1, "2020-10-05T09:00:00Z", "contract_until", "2027-06-01", "month")])
    f = build_wiki_features(later, pd.concat([BASE, future]))
    assert f.contract_years_left.iloc[0] == pytest.approx((pd.Timestamp("2027-06-30") - pd.Timestamp("2021-09-01")).days / 365.25)


def test_feature_sets():
    assert CONTRACT == ["contract_years_left", "contract_known", "contract_ext_12m", "contract_exp_12m"]
    assert MOVES == ["text_transfers_12m", "text_loans_12m"]
