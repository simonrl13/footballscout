"""Point-in-time features from extracted Wikipedia events (extract-v3), per snapshot (player_id, t). Pre-registered in
docs/RESEARCH_LOG.md (2026-10-12) before any evaluation.

Every row used comes from a document published strictly before t (`available_at < t`).
- Contract set C:
  - contract_years_left: (latest contract end date stated - t) in years, using the contract statements in ALL of the
    player's documents published before t (not only the 12-month window). A year-only end date is read as 30 June of
    that year (contracts end with the season), a month-only one as the month's last day. Negative values (an end date
    already passed) are kept: they say the latest known contract has run out. NaN when no statement exists.
  - contract_known: 1 if at least one statement exists, else 0 (the missing-value indicator).
  - contract_ext_12m, contract_exp_12m: verified contract-extension / contract-expiry events dated in [t - 1 year, t).
- Move set M: text_transfers_12m, text_loans_12m: verified transfer / loan events dated in [t - 1 year, t).
- Injuries: text_injuries_12m, reported only (about 0.02 per player-year in the second pilot), never a feature.
"""
import numpy as np
import pandas as pd

from scout.text.extract_wiki import PROMPT_VERSION

CONTRACT = ["contract_years_left", "contract_known", "contract_ext_12m", "contract_exp_12m"]
MOVES = ["text_transfers_12m", "text_loans_12m"]
REPORTED = ["text_injuries_12m"]
WINDOW_COUNTS = {"contract_ext_12m": "contract_extension", "contract_exp_12m": "contract_expiry",
                 "text_transfers_12m": "transfer", "text_loans_12m": "loan", "text_injuries_12m": "injury"}


def end_of(date: pd.Series, precision: pd.Series) -> pd.Series:
    """The day a stated contract ends: 30 June for a year, the month's last day for a month."""
    d = pd.to_datetime(date)
    return d.where(precision == "day", d + pd.offsets.MonthEnd(0)).where(
        precision != "year", pd.to_datetime(d.dt.year.astype("Int64").astype(str) + "-06-30", errors="coerce"))


def build_wiki_features(snaps: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    """snaps: player_id, date (t). signals: player_id, available_at (document publication), signal_type,
    event_date, date_precision. Returns CONTRACT + MOVES + REPORTED aligned to snaps.index."""
    names = CONTRACT + MOVES + REPORTED
    out = pd.DataFrame(0.0, index=snaps.index, columns=names)
    out["contract_years_left"] = np.nan
    s = snaps[["player_id", "date"]].reset_index().rename(columns={"index": "_row"})
    sig = signals.assign(available_at=pd.to_datetime(signals.available_at, utc=True).dt.tz_localize(None),
                         event_date=pd.to_datetime(signals.event_date))
    j = s.merge(sig, on="player_id", how="inner")
    j = j[j.available_at < j.date]  # point in time: only text published before the snapshot

    stated = j[j.signal_type == "contract_until"]
    if len(stated):
        latest = stated.assign(end=end_of(stated.event_date, stated.date_precision)).groupby("_row").end.max()
        rows = snaps.date.loc[latest.index]
        out.loc[latest.index, "contract_years_left"] = ((latest - rows).dt.days / 365.25).to_numpy()
        out.loc[latest.index, "contract_known"] = 1.0

    window = j[(j.event_date >= j.date - pd.DateOffset(years=1)) & (j.event_date < j.date)]
    for col, kind in WINDOW_COUNTS.items():
        c = window[window.signal_type == kind].groupby("_row").size()
        out.loc[c.index, col] = c.to_numpy(dtype=float)
    return out


def load_signals(conn, prompt_version: str = PROMPT_VERSION) -> pd.DataFrame:
    rows = conn.execute("SELECT s.player_id, d.available_at, s.signal_type, s.event_date, s.date_precision "
                        "FROM text_signals s JOIN text_documents d USING (doc_id) WHERE s.prompt_version = %s",
                        (prompt_version,)).fetchall()
    return pd.DataFrame(rows, columns=["player_id", "available_at", "signal_type", "event_date", "date_precision"])
