import numpy as np
import pandas as pd

# Valuations come roughly every ~6 months, so a strict 365-day start keeps only ~35% of snapshots.
# [335, 425] keeps ~62% while staying centred on a 12-month horizon.
MIN_DAYS = 335
MAX_DAYS = 425


def build_targets(valuations: pd.DataFrame) -> pd.DataFrame:
    """One row per valuation snapshot that has a future valuation in [t+MIN_DAYS, t+MAX_DAYS].

    Input columns: player_id, date, market_value_in_eur.
    value_future is the FIRST valuation of the same player on or after t+MIN_DAYS;
    the snapshot is dropped if that valuation is later than t+MAX_DAYS or doesn't exist.
    Zero values are dropped (log undefined).
    """
    v = valuations.loc[valuations.market_value_in_eur > 0, ["player_id", "date", "market_value_in_eur"]]
    v = v.assign(date=pd.to_datetime(v.date))

    left = v.assign(search_from=v.date + pd.Timedelta(days=MIN_DAYS)).sort_values("search_from")
    right = v.rename(columns={"date": "future_date", "market_value_in_eur": "value_future"}).sort_values("future_date")
    m = pd.merge_asof(left, right, left_on="search_from", right_on="future_date", by="player_id", direction="forward")
    m = m[m.future_date <= m.date + pd.Timedelta(days=MAX_DAYS)]

    out = m.rename(columns={"market_value_in_eur": "value_now"})[
        ["player_id", "date", "value_now", "future_date", "value_future"]
    ].astype({"value_future": "int64"})
    out["target"] = np.log(out.value_future / out.value_now)
    return out.sort_values(["player_id", "date"]).reset_index(drop=True)
