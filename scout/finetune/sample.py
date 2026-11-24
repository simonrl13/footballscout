"""Draw the hand-labelling sets for the fine-tuning experiment (docs/FINETUNE_PLAN.md §3).

Units are the extract-v3 documents. Players are hashed into test / train / dev, so a page never lands in two sets.
Strata come from keywords in the document text, so the choice doesn't depend on any system's output. The 200 pilot
documents (extract-v2, used while writing the prompt) are excluded.

Usage:
  uv run --group finetune --env-file .env python -m scout.finetune.sample   # -> docs/evals/finetune_sample.csv (committed)
"""
import hashlib
import re

import pandas as pd

from scout.data.manifest import ROOT

SEED = 20261124
SAMPLE_FILE = ROOT / "docs" / "evals" / "finetune_sample.csv"
STRATA = {  # first match wins, rarest type first
    "injury": r"\b(?:injur|ruptur|ligament|surgery|sidelined|ruled out|fracture|strain)",
    "contract": r"\b(?:contract|extension|extended|until 20|free transfer|released|terminated)",
    "loan": r"\bloan",
    "transfer": r"\b(?:joined|signed for|moved to|transfer|fee\b)",
}
PER_STRATUM = {"test": 30, "train": 30, "dev": 6}  # 150 / 150 / 30 (approved 2026-11-24)


def split_of(player_id: int) -> str:
    """test 50% / train 40% / dev 10%, fixed by a hash of the player id."""
    h = int(hashlib.sha256(f"{SEED}:{player_id}".encode()).hexdigest(), 16) % 100
    return "test" if h < 50 else "train" if h < 90 else "dev"


def stratum_of(text: str) -> str:
    low = text.lower()
    return next((s for s, pat in STRATA.items() if re.search(pat, low)), "none")


def draw(docs: pd.DataFrame) -> pd.DataFrame:
    """docs: doc_id, player_id, text. Returns doc_id, player_id, split, stratum, one row per sampled document."""
    d = docs.assign(split=docs.player_id.map(split_of), stratum=docs.text.map(stratum_of)).sort_values("doc_id")
    parts = [g.sample(min(len(g), PER_STRATUM[sp]), random_state=SEED) for (sp, _), g in d.groupby(["split", "stratum"])]
    return pd.concat(parts)[["doc_id", "player_id", "split", "stratum"]].sort_values(["split", "stratum", "doc_id"]).reset_index(drop=True)


def load_docs(conn) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT d.doc_id, (d.meta->>'player_id')::bigint, d.body FROM text_extractions e JOIN text_documents d USING (doc_id) "
        "WHERE e.prompt_version = 'extract-v3' AND e.output IS NOT NULL "
        "AND d.doc_id NOT IN (SELECT doc_id FROM text_extractions WHERE prompt_version = 'extract-v2')").fetchall()
    return pd.DataFrame(rows, columns=["doc_id", "player_id", "text"])


def main() -> None:
    from scout.text import store
    if SAMPLE_FILE.exists():
        raise SystemExit(f"{SAMPLE_FILE.name} exists: the sets are locked once drawn")
    with store.connect() as conn:
        docs = load_docs(conn)
    out = draw(docs)
    out.to_csv(SAMPLE_FILE, index=False)
    print(f"{len(docs):,} candidate documents -> {SAMPLE_FILE}")
    print(out.groupby(["split", "stratum"]).size().unstack(fill_value=0))


if __name__ == "__main__":
    main()
