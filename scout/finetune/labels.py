"""Hand-labelling files for the fine-tuning experiment (guide: docs/evals/finetune_labelling.md).

  uv run --group finetune --env-file .env python -m scout.finetune.labels render test   # -> labeling/finetune/test.md + test.csv
  uv run --group finetune --env-file .env python -m scout.finetune.labels check test    # validate the filled CSV

The files hold Wikipedia text (CC BY-SA 4.0) and stay out of git (labeling/finetune/ is gitignored).
"""
import argparse

import pandas as pd

from scout.data.manifest import ROOT
from scout.finetune.sample import SAMPLE_FILE
from scout.text.extract import MAX_QUOTE_CHARS, _norm
from scout.text.extract_wiki import EVENT_TYPES, locate, parse_date

DIR = ROOT / "labeling" / "finetune"
COLUMNS = ["doc_id", "row", "type", "date", "contract_until", "injury_type", "duration_days", "evidence", "note"]


def doc_texts(conn, doc_ids: list[str]) -> pd.DataFrame:
    rows = conn.execute("SELECT doc_id, url, meta->>'title', meta->>'snapshot', body FROM text_documents WHERE doc_id = ANY(%s)",
                        (doc_ids,)).fetchall()
    return pd.DataFrame(rows, columns=["doc_id", "url", "title", "snapshot", "text"]).set_index("doc_id").loc[doc_ids].reset_index()


def render(docs: pd.DataFrame) -> str:
    """Numbered lines per document: what the labeller reads (the same text the systems get)."""
    out = []
    for i, d in enumerate(docs.itertuples(), 1):
        out += [f"## {i}. {d.title}", "", f"- doc_id: `{d.doc_id}`", f"- snapshot: {d.snapshot}", f"- diff: {d.url}", ""]
        out += [f"    {n:>3}  {line}" for n, line in enumerate(d.text.split("\n"), 1)] + [""]
    return "\n".join(out)


def template(docs: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{c: "" for c in COLUMNS} | {"doc_id": d, "row": 1} for d in docs.doc_id])[COLUMNS]


def check(labels: pd.DataFrame, texts: dict[str, str]) -> list[str]:
    """Problems in a filled sheet; empty when it is valid."""
    errs = []
    missing = set(texts) - set(labels.doc_id)
    if missing:
        errs.append(f"{len(missing)} documents have no row (a document with no events gets type 'none')")
    for i, r in labels.fillna("").astype(str).iterrows():
        at = f"line {i + 2} ({r.doc_id}, row {r.row})"
        t = r.type.strip()
        if r.doc_id not in texts:
            errs.append(f"{at}: doc_id not in the set")
            continue
        if t == "none":
            if (labels.doc_id == r.doc_id).sum() > 1:
                errs.append(f"{at}: 'none' alongside other rows")
            continue
        if t not in EVENT_TYPES:
            errs.append(f"{at}: type {t!r} not in {EVENT_TYPES + ['none']}")
        if r.date.strip() and parse_date(r.date) is None:  # empty = the text gives no date (guide rule 3)
            errs.append(f"{at}: date {r.date!r} is not YYYY-MM-DD, YYYY-MM or YYYY")
        if r.contract_until.strip() and parse_date(r.contract_until) is None:
            errs.append(f"{at}: contract_until {r.contract_until!r} is not a date")
        if r.duration_days.strip() and not r.duration_days.strip().isdigit():
            errs.append(f"{at}: duration_days must be a whole number")
        if len(_norm(r.evidence)) > MAX_QUOTE_CHARS or locate(texts[r.doc_id], r.evidence) is None:
            errs.append(f"{at}: evidence is not a verbatim fragment of at most {MAX_QUOTE_CHARS} characters")
    return errs


def main() -> None:
    from scout.text import store
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["render", "check"])
    ap.add_argument("split", choices=["test", "train", "dev"])
    a = ap.parse_args()
    ids = pd.read_csv(SAMPLE_FILE).query("split == @a.split").doc_id.tolist()
    with store.connect() as conn:
        docs = doc_texts(conn, ids)
    sheet = DIR / f"{a.split}.csv"
    if a.action == "render":
        DIR.mkdir(parents=True, exist_ok=True)
        (DIR / f"{a.split}.md").write_text(render(docs), encoding="utf-8")
        if sheet.exists():
            raise SystemExit(f"{sheet} exists: not overwriting labels (documents re-rendered)")
        template(docs).to_csv(sheet, index=False)
        print(f"{len(docs)} documents -> {DIR}")
    else:
        errs = check(pd.read_csv(sheet, dtype=str, keep_default_na=False), dict(zip(docs.doc_id, docs.text)))
        print("\n".join(errs) or f"{sheet.name}: valid")
        raise SystemExit(1 if errs else 0)


if __name__ == "__main__":
    main()
