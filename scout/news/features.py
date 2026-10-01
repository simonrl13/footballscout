"""Point-in-time news features per snapshot (player_id, t).

An article counts only if it was first published strictly before t (first_published_at, else published_at).
With exclude_edited_after_t=True it is also dropped when last_modified >= t, for the edit-sensitivity analysis.
"""
import numpy as np
import pandas as pd

from scout.news.extract import SIGNAL_TYPES

WINDOWS = (90, 365)
NEWS_FEATURES = ([f"news_articles_{w}d" for w in WINDOWS]
                 + [f"news_{s}_365d" for s in SIGNAL_TYPES] + ["news_any_365d"])


def build_news_features(snaps: pd.DataFrame, articles: pd.DataFrame, mentions: pd.DataFrame,
                        signals: pd.DataFrame | None = None, exclude_edited_after_t: bool = False) -> pd.DataFrame:
    """snaps: player_id, date. articles: article_id, published_at, first_published_at, last_modified.
    mentions: article_id, player_id. signals: article_id, player_id, signal_type (optional, LLM output).
    Returns NEWS_FEATURES aligned to snaps.index (0 where nothing qualifies)."""
    a = articles.assign(first=pd.to_datetime(articles.first_published_at.fillna(articles.published_at), utc=True)
                        .dt.tz_localize(None),
                        edited=pd.to_datetime(articles.last_modified, utc=True).dt.tz_localize(None))
    m = mentions[["article_id", "player_id"]].drop_duplicates().merge(a[["article_id", "first", "edited"]], on="article_id")
    s = snaps[["player_id", "date"]].reset_index().rename(columns={"index": "_row"})
    j = s.merge(m, on="player_id", how="inner")
    j = j[j["first"] < j.date]  # strictly before the snapshot
    if exclude_edited_after_t:
        j = j[~(j.edited >= j.date)]
    age = (j.date - j["first"]).dt.days
    out = pd.DataFrame(0, index=snaps.index, columns=NEWS_FEATURES, dtype=float)
    for w in WINDOWS:
        counts = j[age <= w].groupby("_row").article_id.nunique()
        out.loc[counts.index, f"news_articles_{w}d"] = counts.to_numpy()
    if signals is not None and len(signals):
        js = j[age <= 365].merge(signals[["article_id", "player_id", "signal_type"]].drop_duplicates(),
                                on=["article_id", "player_id"])
        for st in SIGNAL_TYPES:
            c = js[js.signal_type == st].groupby("_row").article_id.nunique()
            out.loc[c.index, f"news_{st}_365d"] = c.to_numpy()
    out["news_any_365d"] = (out["news_articles_365d"] > 0).astype(float)
    return out
