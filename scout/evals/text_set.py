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

Retrieval dev split (--dev; pre-registered 2026-10-29): the same rules with seed 20261029, 4 questions per type and
band (24), players disjoint from text.jsonl. Used only to choose RRF k and rerank N (scout/evals/retrieval_eval.py).

Extension (--extend; amendment 2026-10-29, gold coverage): transfer questions from players disjoint from every set so
far, shuffled per band (seed 20261030) and taken round-robin high, mid, low, each kept as drawn, until 50 questions of
text.jsonl + the extension have a string-match gold passage (scout.evals.retrieval_eval.string_match); then the dev
split is topped up the same way (seed 20261031) until 24 dev questions have one.

Usage: uv run --env-file .env python -m scout.evals.text_set            (writes scout/evals/text.jsonl)
       uv run --env-file .env python -m scout.evals.text_set --dev      (writes scout/evals/retrieval_dev.jsonl)
       uv run --env-file .env python -m scout.evals.text_set --extend   (writes retrieval_extra.jsonl, appends to the dev split)
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from scout.agent import tools
from scout.text.eval_events import YOUTH

OUT = Path(__file__).parent / "text.jsonl"
DEV_OUT = Path(__file__).parent / "retrieval_dev.jsonl"
EXTRA_OUT = Path(__file__).parent / "retrieval_extra.jsonl"
SEED, DEV_SEED = 20261015, 20261029
PER_CELL, DEV_PER_CELL = 6, 4
EXTRA_SEED, TOPUP_SEED, EXTRA_TARGET, TOPUP_TARGET = 20261030, 20261031, 50, 24
CLUB_WORDS = {"fc", "cf", "sc", "afc", "sv", "ac", "as", "us", "cd", "ud", "sd", "rc", "ssc", "fk", "sk", "nk", "if",
              "ff", "bk", "vfb", "vfl", "tsg", "rb", "1.fc", "club", "calcio"}
BANDS = [("high", 30e6, None), ("mid", 5e6, 30e6), ("low", None, 5e6)]
RESERVE = re.compile(YOUTH.pattern[:-1] + r"|\s2$)", re.I)  # also reserve sides like "Whitecaps FC 2"
NOT_A_CLUB = ("Without Club", "Retired", "Unknown", "Career break", "Ban")
# Other names an answer may use for a destination club (Transfermarkt's short names differ from common ones).
# Written after sampling, before any run; each list is folded and matched as whole words.
ALIASES = {"Leipzig": ["RB Leipzig"], "Hannover 96": ["Hannover"], "Nott'm Forest": ["Nottingham Forest", "Forest"],
           "Valenciennes FC": ["Valenciennes"], "KVC Westerlo": ["Westerlo"], "SSV Ulm 1846": ["Ulm"],
           "Frankfurt": ["Eintracht Frankfurt"], "1.FC Nuremberg": ["Nuremberg", "Nurnberg"], "Club Tijuana": ["Tijuana"],
           # retrieval dev split (2026-10-29), written after sampling, before any run
           "CD Mirandés": ["Mirandés"], "Kalmar FF": ["Kalmar"], "Nordsjaelland": ["Nordsjælland", "FC Nordsjælland"]}


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


def sample(df: pd.DataFrame, rng: np.random.Generator, taken: set, per_cell: int = PER_CELL) -> pd.DataFrame:
    df = df[~df.player_id.isin(taken)].assign(band=df.value_eur.map(band))
    picked = []
    for b, _, _ in BANDS:
        cell = df[df.band == b].drop_duplicates("player_id").sort_values("player_id")
        picked.append(cell.iloc[rng.choice(len(cell), per_cell, replace=False)])
    out = pd.concat(picked)
    taken.update(out.player_id)
    return out


def build(demo, transfers, players, seed: int = SEED, per_cell: int = PER_CELL, taken: set | None = None) -> list[dict]:
    rng, taken, cases = np.random.default_rng(seed), set(taken or ()), []
    for r in sample(transfer_candidates(demo, transfers), rng, taken, per_cell).itertuples():
        cases.append({"id": f"tr-{r.player_id}-{r.year}", "type": "transfer", "band": r.band, "player_id": int(r.player_id),
                      "question": f"Which club did {r.name} join in the summer {r.year} transfer window?",
                      "truth": r.truth, "accept": [r.truth, *ALIASES.get(r.truth, [])], "from_club": r.from_club, "demo_club": r.club})
    for r in sample(contract_candidates(demo, players), rng, taken, per_cell).itertuples():
        cases.append({"id": f"ct-{r.player_id}", "type": "contract", "band": r.band, "player_id": int(r.player_id),
                      "question": f"As of June 2026, until when does {r.name}'s contract with {r.club} run?",
                      "truth": int(r.truth), "tm_expiry": str(r.contract_expiration_date)})
    return cases


def short_form(name: str) -> str | None:
    """The club name without club-type words ("Kalmar FF" -> "Kalmar"), if a word of 4+ letters remains."""
    kept = [w for w in name.split() if w.lower() not in CLUB_WORDS]
    short = " ".join(kept)
    return short if short != name and any(len(w) >= 4 for w in kept) else None


def transfer_case(r) -> dict:
    accept = [r.truth, *ALIASES.get(r.truth, [])]
    if (short := short_form(r.truth)) and short not in accept:
        accept.append(short)
    return {"id": f"tr-{r.player_id}-{r.year}", "type": "transfer", "band": r.band, "player_id": int(r.player_id),
            "question": f"Which club did {r.name} join in the summer {r.year} transfer window?",
            "truth": r.truth, "accept": accept, "from_club": r.from_club, "demo_club": r.club}


def extend(demo, transfers, taken: set, seed: int, have: int, target: int, has_gold) -> list[dict]:
    """Transfer questions drawn in a fixed order (one per player, earliest eligible window; shuffled per band,
    round-robin high, mid, low), each kept, until `have` questions with string-match gold reach `target`."""
    c = transfer_candidates(demo, transfers)
    c = c[~c.player_id.isin(taken)].sort_values(["player_id", "year"]).drop_duplicates("player_id")
    c = c.assign(band=c.value_eur.map(band))
    rng = np.random.default_rng(seed)
    queues = [list(g.sort_values("player_id").iloc[rng.permutation(len(g))].itertuples())
              for b, _, _ in BANDS for g in [c[c.band == b]]]
    order = [q[i] for i in range(max(map(len, queues))) for q in queues if i < len(q)]
    out = []
    for r in order:
        if have >= target:
            break
        case = transfer_case(r)
        out.append(case)
        taken.add(case["player_id"])
        have += has_gold(case)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true", help="the retrieval dev split, players disjoint from text.jsonl")
    ap.add_argument("--extend", action="store_true", help="extended eval set and dev top-up (amendment 2026-10-29)")
    a = ap.parse_args()
    dev = a.dev
    with tools.connect() as db:
        demo = pd.DataFrame(db.execute("SELECT player_id, name, club, value_eur::float AS value_eur FROM demo_players").fetchall())
        transfers = pd.DataFrame(db.execute(
            "SELECT t.player_id, t.transfer_date, t.from_club_name, t.to_club_name FROM transfers t "
            "JOIN demo_players d USING (player_id)").fetchall())
        players = pd.DataFrame(db.execute(
            "SELECT p.player_id, p.contract_expiration_date, p.current_club_name FROM players p "
            "JOIN demo_players d USING (player_id)").fetchall())
        if a.extend:
            return write_extension(db, demo, transfers)
    if dev:
        reported = {json.loads(x)["player_id"] for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()}
        cases, out = build(demo, transfers, players, DEV_SEED, DEV_PER_CELL, reported), DEV_OUT
    else:
        cases, out = build(demo, transfers, players), OUT
    out.write_bytes("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases).encode())
    print(f"{len(cases)} cases -> {out}")


def read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def write_extension(db, demo, transfers) -> None:
    from scout.evals.retrieval_eval import passages, string_match
    from scout.text.retrieve import chunk_text

    def has_gold(case: dict) -> bool:
        return any(string_match(case, chunk_text(p["section"], p["body"]))
                   for p in passages(db, "player_id = %s", (case["player_id"],)))
    reported, dev = read(OUT), read(DEV_OUT)
    if EXTRA_OUT.exists() or any(c.get("topup") for c in dev):
        raise SystemExit("the extension exists already: it is built once")
    taken = {c["player_id"] for c in reported + dev}
    extra = extend(demo, transfers, taken, EXTRA_SEED, sum(map(has_gold, reported)), EXTRA_TARGET, has_gold)
    topup = [{**c, "topup": True} for c in extend(demo, transfers, taken, TOPUP_SEED, sum(map(has_gold, dev)), TOPUP_TARGET, has_gold)]
    EXTRA_OUT.write_bytes("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in extra).encode())
    DEV_OUT.write_bytes("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in dev + topup).encode())
    print(f"extension: {len(extra)} questions ({sum(map(has_gold, extra))} with gold) -> {EXTRA_OUT}")
    print(f"dev top-up: {len(topup)} questions ({sum(map(has_gold, topup))} with gold); dev now {len(dev) + len(topup)}")


if __name__ == "__main__":
    main()
