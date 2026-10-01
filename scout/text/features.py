"""Point-in-time features from linked public-text documents, per snapshot (player_id, t). Source-agnostic.

A document counts only if it became public strictly before t (`available_at`: first publication, or the revision
timestamp). With exclude_edited_after_t=True it is also dropped when last_modified >= t (edit-sensitivity analysis).
Feature names carry a source prefix (e.g. "wiki"), so sources can be compared in ablations.
"""
import pandas as pd

from scout.text.extract import SIGNAL_TYPES

WINDOWS = (90, 365)


def feature_names(prefix: str) -> list[str]:
    return ([f"{prefix}_docs_{w}d" for w in WINDOWS] + [f"{prefix}_{s}_365d" for s in SIGNAL_TYPES]
            + [f"{prefix}_any_365d"])


def build_text_features(snaps: pd.DataFrame, documents: pd.DataFrame, mentions: pd.DataFrame,
                        signals: pd.DataFrame | None = None, prefix: str = "text",
                        exclude_edited_after_t: bool = False) -> pd.DataFrame:
    """snaps: player_id, date. documents: doc_id, available_at, last_modified (optional).
    mentions: doc_id, player_id. signals: doc_id, player_id, signal_type (optional, LLM output).
    Returns feature_names(prefix) aligned to snaps.index (0 where nothing qualifies)."""
    to_naive = lambda s: pd.to_datetime(s, utc=True).dt.tz_localize(None)
    d = documents.assign(first=to_naive(documents.available_at),
                         edited=to_naive(documents["last_modified"]) if "last_modified" in documents else pd.NaT)
    m = mentions[["doc_id", "player_id"]].drop_duplicates().merge(d[["doc_id", "first", "edited"]], on="doc_id")
    s = snaps[["player_id", "date"]].reset_index().rename(columns={"index": "_row"})
    j = s.merge(m, on="player_id", how="inner")
    j = j[j["first"] < j.date]  # strictly before the snapshot
    if exclude_edited_after_t:
        j = j[~(j.edited >= j.date)]
    age = (j.date - j["first"]).dt.days
    names = feature_names(prefix)
    out = pd.DataFrame(0, index=snaps.index, columns=names, dtype=float)
    for w in WINDOWS:
        counts = j[age <= w].groupby("_row").doc_id.nunique()
        out.loc[counts.index, f"{prefix}_docs_{w}d"] = counts.to_numpy()
    if signals is not None and len(signals):
        js = j[age <= 365].merge(signals[["doc_id", "player_id", "signal_type"]].drop_duplicates(), on=["doc_id", "player_id"])
        for st in SIGNAL_TYPES:
            c = js[js.signal_type == st].groupby("_row").doc_id.nunique()
            out.loc[c.index, f"{prefix}_{st}_365d"] = c.to_numpy()
    out[f"{prefix}_any_365d"] = (out[f"{prefix}_docs_365d"] > 0).astype(float)
    return out
