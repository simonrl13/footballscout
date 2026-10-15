"""Builds the text eval set (text.jsonl): questions whose answers Transfermarkt records, to measure whether search_text
(Wikipedia) improves the agent's answers. Separate from the dev and held-out sets; pre-registered in
docs/RESEARCH_LOG.md (2026-10-15).

- transfer: "Which club did X join in the summer YYYY transfer window?" for a demo player with exactly one senior
  move recorded in the transfers table between 1 July and 15 September of YYYY (2016-2025). Left out: youth/reserve
  teams, "Without Club"/"Retired"/unknown destinations, and moves to a club the player had left before (loan returns,
  which Transfermarkt dates 30 June or 1 July). Truth: the destination club.
- contract: "As of June 2026, until when does X's contract with CLUB run?" for a demo player whose Transfermarkt
  contract expiry (players.contract_expiration_date, same dump as the demo, 12 June 2026) is after 30 June 2026 and
  whose current club in that dump is the demo club. Truth: the expiry year.
- Bands by demo market value: high >= EUR 30m, mid EUR 5m-30m, low < EUR 5m. 6 questions per type and band (36),
  one question per player, fixed seed.

Usage: uv run --env-file .env python -m scout.evals.text_set   (writes scout/evals/text.jsonl)
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from scout.agent import tools
from scout.text.eval_events import YOUTH

OUT = Path(__file__).parent / "text.jsonl"
SEED = 20261015
PER_CELL = 6
BANDS = [("high", 30e6, None), ("mid", 5e6, 30e6), ("low", None, 5e6)]
RESERVE = re.compile(YOUTH.pattern[:-1] + r"|\s2$)", re.I)  # also reserve sides like "Whitecaps FC 2"
NOT_A_CLUB = ("Without Club", "Retired", "Unknown", "Career break", "Ban")
# Other names an answer may use for a destination club (Transfermarkt's short names differ from common ones).
# Written after sampling, before any run; each list is folded and matched as whole words.
ALIASES = {"Leipzig": ["RB Leipzig"], "Hannover 96": ["Hannover"], "Nott'm Forest": ["Nottingham Forest", "Forest"],
           "Valenciennes FC": ["Valenciennes"], "KVC Westerlo": ["Westerlo"], "SSV Ulm 1846": ["Ulm"],
           "Frankfurt": ["Eintracht Frankfurt"], "1.FC Nuremberg": ["Nuremberg", "Nurnberg"], "Club Tijuana": ["Tijuana"]}


def band(value_eur: float) -> str:
    return next(b for b, lo, hi in BANDS if (lo is None or value_eur >= lo) and (hi is None or value_eur < hi))


def transfer_candidates(demo: pd.DataFrame, transfers: pd.DataFrame) -> pd.DataFrame:
    t = transfers.assign(date=pd.to_datetime(transfers.transfer_date))
    t = t[~t.from_club_name.fillna("").str.contains(RESERVE) & ~t.to_club_name.fillna("").str.contains(RESERVE)]
    rows = []
    for year in range(2016, 2026):
        w = t[(t.date >= f"{year}-07-01") & (t.date <= f"{year}-09-15")]
        one = w.groupby("player_id").filter(lambda g: len(g) == 1)
        for r in one.itertuples():
            left_before = t[(t.player_id == r.player_id) & (t.date < r.date)].from_club_name
            if r.to_club_name in NOT_A_CLUB or not r.to_club_name or r.to_club_name in set(left_before):
                continue
            rows.append({"player_id": r.player_id, "year": year, "truth": r.to_club_name, "from_club": r.from_club_name})
    out = pd.DataFrame(rows)
    return out.merge(demo[["player_id", "name", "club", "value_eur"]], on="player_id")


def contract_candidates(demo: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    p = players.merge(demo[["player_id", "name", "club", "value_eur"]], on="player_id", suffixes=("_tm", ""))
    p = p[p.contract_expiration_date.notna() & (pd.to_datetime(p.contract_expiration_date) > "2026-06-30")
          & (p.current_club_name == p.club)]
    return p.assign(truth=pd.to_datetime(p.contract_expiration_date).dt.year)


def sample(df: pd.DataFrame, rng: np.random.Generator, taken: set) -> pd.DataFrame:
    df = df[~df.player_id.isin(taken)].assign(band=df.value_eur.map(band))
    picked = []
    for b, _, _ in BANDS:
        cell = df[df.band == b].drop_duplicates("player_id").sort_values("player_id")
        picked.append(cell.iloc[rng.choice(len(cell), PER_CELL, replace=False)])
    out = pd.concat(picked)
    taken.update(out.player_id)
    return out


def build(demo, transfers, players) -> list[dict]:
    rng, taken, cases = np.random.default_rng(SEED), set(), []
    for r in sample(transfer_candidates(demo, transfers), rng, taken).itertuples():
        cases.append({"id": f"tr-{r.player_id}-{r.year}", "type": "transfer", "band": r.band, "player_id": int(r.player_id),
                      "question": f"Which club did {r.name} join in the summer {r.year} transfer window?",
                      "truth": r.truth, "accept": [r.truth, *ALIASES.get(r.truth, [])], "from_club": r.from_club, "demo_club": r.club})
    for r in sample(contract_candidates(demo, players), rng, taken).itertuples():
        cases.append({"id": f"ct-{r.player_id}", "type": "contract", "band": r.band, "player_id": int(r.player_id),
                      "question": f"As of June 2026, until when does {r.name}'s contract with {r.club} run?",
                      "truth": int(r.truth), "tm_expiry": str(r.contract_expiration_date)})
    return cases


def main() -> None:
    with tools.connect() as db:
        demo = pd.DataFrame(db.execute("SELECT player_id, name, club, value_eur::float AS value_eur FROM demo_players").fetchall())
        transfers = pd.DataFrame(db.execute(
            "SELECT t.player_id, t.transfer_date, t.from_club_name, t.to_club_name FROM transfers t "
            "JOIN demo_players d USING (player_id)").fetchall())
        players = pd.DataFrame(db.execute(
            "SELECT p.player_id, p.contract_expiration_date, p.current_club_name FROM players p "
            "JOIN demo_players d USING (player_id)").fetchall())
    cases = build(demo, transfers, players)
    OUT.write_bytes("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases).encode())
    print(f"{len(cases)} cases -> {OUT}")


if __name__ == "__main__":
    main()
