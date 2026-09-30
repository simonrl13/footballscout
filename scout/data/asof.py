"""Point-in-time lookups shared by snapshot and feature construction."""
import numpy as np
import pandas as pd


def asof(ids: pd.Series, at: pd.Series, events: pd.DataFrame, by: str, cols: list[str], strict=True) -> pd.DataFrame:
    """For each (id, at): the last `events` row with the same id and date < at (<= at if not strict).
    Returns cols + the event's date, aligned to ids.index; NaN where there is none."""
    left = pd.DataFrame({by: ids.values, "_at": at.values, "_i": np.arange(len(ids))}).sort_values("_at", kind="stable")
    right = events[[by, "date", *cols]].sort_values("date", kind="stable")
    m = pd.merge_asof(left, right, left_on="_at", right_on="date", by=by, allow_exact_matches=not strict)
    return m.sort_values("_i")[[*cols, "date"]].set_index(ids.index)


def window_sum(ids: pd.Series, at: pd.Series, events: pd.DataFrame, by: str, cols: list[str], days: int) -> pd.DataFrame:
    """Sum of cols over events with the same id and date in [at - days, at)."""
    ev = events.sort_values([by, "date"], kind="stable")
    ev = ev[[by, "date"]].join(ev.groupby(by)[cols].cumsum())
    upto_now = asof(ids, at, ev, by, cols)[cols].fillna(0)
    upto_start = asof(ids, at - pd.Timedelta(days=days), ev, by, cols)[cols].fillna(0)
    return upto_now - upto_start
