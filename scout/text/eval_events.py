"""Ground truth for extracted moves: Transfermarkt's transfers table (permanent moves, loans and loan returns).

- Precision: share of extracted transfer/loan events with a recorded move of the same player within TOLERANCE of the
  event date (a month-precision date covers its whole month).
- Recall: share of recorded moves inside a processed player-year's window [t - 1 year, t) that some extracted
  transfer/loan event of that player-year matches. Youth/reserve-team moves (U19, Yth., B, II ...) are left out:
  Wikipedia rarely mentions them.
Recall is bounded by the design: a document holds only text added to the page during the year.

Both are scored only for players with at least one recorded transfer: the table has no transfers at all for many
players (mostly earlier careers), and counting their extracted moves as false would measure coverage, not extraction.
"""
import math
import re

import pandas as pd

MOVES = ("transfer", "loan")
TOLERANCE = pd.Timedelta(days=31)
YOUTH = re.compile(r"(?:\bU\d{2}\b|\bYth\b|\bYouth\b|\bII\b|\bB$|\bJuniors?\b|\bReserves?\b)", re.I)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return math.nan, math.nan
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _span(date, precision: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    d = pd.Timestamp(date)
    end = d + pd.offsets.MonthEnd(0) if precision == "month" else d
    return d - TOLERANCE, end + TOLERANCE


def move_eval(signals: pd.DataFrame, transfers: pd.DataFrame, player_years: pd.DataFrame) -> dict:
    """signals: kept events (player_id, t, signal_type, event_date, date_precision) of the processed player-years;
    transfers: player_id, date, from_club_name, to_club_name; player_years: player_id, t (every processed document)."""
    covered = set(transfers.player_id)
    all_moves = signals[signals.signal_type.isin(MOVES)]
    moves = all_moves[all_moves.player_id.isin(covered)]
    by_player = {p: g.date for p, g in transfers.groupby("player_id")}
    matched = 0
    for m in moves.itertuples():
        lo, hi = _span(m.event_date, m.date_precision)
        dates = by_player.get(m.player_id)
        matched += dates is not None and bool(((lo <= dates) & (dates <= hi)).any())
    senior = transfers[~transfers.from_club_name.fillna("").str.contains(YOUTH)
                       & ~transfers.to_club_name.fillna("").str.contains(YOUTH)]
    real = senior.merge(player_years, on="player_id")
    real = real[(real.date >= real.t - pd.DateOffset(years=1)) & (real.date < real.t)]
    spans = {}
    for m in moves.itertuples():
        spans.setdefault((m.player_id, m.t), []).append(_span(m.event_date, m.date_precision))
    recalled = sum(any(lo <= r.date <= hi for lo, hi in spans.get((r.player_id, r.t), [])) for r in real.itertuples())
    return {"uncovered": len(all_moves) - len(moves), "extracted": len(moves), "matched": int(matched), "precision": matched / len(moves) if len(moves) else math.nan,
            "precision_ci": wilson(int(matched), len(moves)), "real": len(real), "recalled": int(recalled),
            "recall": recalled / len(real) if len(real) else math.nan, "recall_ci": wilson(int(recalled), len(real))}
