"""Leakage check on the real data: snapshots and features built from tables truncated at the snapshot
date must equal those built from the full tables. Skipped when data/raw is absent (e.g. in CI)."""
import pandas as pd
import pytest

from scout.data.manifest import RAW
from scout.data.snapshots import build_snapshots, snapshot_date
from scout.ml.features import FEATURES, build_features

pytestmark = pytest.mark.skipif(not (RAW / "appearances.csv").exists(), reason="raw CSVs not available")
YEARS = [2014, 2020, 2023]  # an early year, the COVID year, a test year


@pytest.fixture(scope="module")
def raw():
    from scout.data.raw import read_raw
    return read_raw()


def truncate(raw: dict, t: pd.Timestamp) -> dict:
    return {
        "players": raw["players"],
        "valuations": raw["valuations"][raw["valuations"].date <= t],
        "transfers": raw["transfers"][raw["transfers"].date <= t],
        "appearances": raw["appearances"][raw["appearances"].date < t],
        "games": raw["games"][raw["games"].date < t],
    }


@pytest.mark.parametrize("year", YEARS)
def test_truncated_data_gives_identical_snapshots_and_features(raw, year):
    full = build_snapshots(raw, years=[year], with_target=False)
    cut_raw = truncate(raw, snapshot_date(year))
    cut = build_snapshots(cut_raw, years=[year], with_target=False)
    cols = ["player_id", "club_id", "league", "value_now", "prev_league_minutes"]
    pd.testing.assert_frame_equal(full[cols], cut[cols])
    pd.testing.assert_frame_equal(build_features(full, raw)[FEATURES], build_features(cut, cut_raw)[FEATURES])
