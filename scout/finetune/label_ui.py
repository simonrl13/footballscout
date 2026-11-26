"""Local browser UI for the hand labels (guide: docs/evals/finetune_labelling.md).

  uv run --group finetune --env-file .env python -m scout.finetune.label_ui test    # or: dev

Serves on 127.0.0.1 only and opens the browser. It reads the documents from text_documents (the same text the
systems get) and the sheet labeling/finetune/<split>.csv. It never reads extractions or model output and never
suggests labels. Every change rewrites the sheet atomically (temp file + rename) with labels.COLUMNS, so
`labels check` and the scorer read it unchanged. A timestamped .bak copy is taken on start.
"""
import argparse
import os
import re
import shutil
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from scout.finetune.labels import COLUMNS, DIR, check, doc_texts
from scout.finetune.sample import SAMPLE_FILE

PAGE = Path(__file__).with_name("label_ui.html")
FIELDS = [c for c in COLUMNS if c not in ("doc_id", "row")]


def read_sheet(path: Path) -> dict[str, list[dict]]:
    """doc_id -> rows (dicts of FIELDS, all strings), in file order."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    out: dict[str, list[dict]] = {}
    for r in df.to_dict("records"):
        out.setdefault(r["doc_id"], []).append({f: r.get(f, "") for f in FIELDS})
    return out


def write_sheet(path: Path, order: list[str], rows: dict[str, list[dict]]) -> None:
    """Rewrite the whole sheet atomically: documents in `order` (others kept after them), rows renumbered 1..n.
    A document with no rows keeps one blank row, as in the template, so it stays visibly unlabelled."""
    recs = []
    for d in order + [d for d in rows if d not in order]:
        for i, r in enumerate(rows.get(d) or [{}], 1):
            recs.append({"doc_id": d, "row": str(i), **{f: str(r.get(f, "") or "") for f in FIELDS}})
    tmp = path.with_name(path.name + ".tmp")
    pd.DataFrame(recs, columns=COLUMNS).to_csv(tmp, index=False)
    os.replace(tmp, path)  # atomic on the same filesystem: the sheet is either the old or the new version


def backup(path: Path) -> Path:
    bak = path.with_name(f"{path.stem}.{datetime.now():%Y%m%d-%H%M%S}.bak")
    shutil.copy2(path, bak)
    return bak


def is_labelled(rows: list[dict]) -> bool:
    return any(r.get("type", "").strip() for r in rows)


def doc_problems(doc_id: str, rows: list[dict], text: str) -> list[str]:
    """The existing check() on one document's rows; an unlabelled document has none yet."""
    if not is_labelled(rows):
        return []
    df = pd.DataFrame([{"doc_id": doc_id, "row": str(i), **r} for i, r in enumerate(rows, 1)], columns=COLUMNS).fillna("")
    return [re.sub(r"^line \d+ \(.*?, row (\d+)\): ", r"event \1: ", e) for e in check(df, {doc_id: text})]


class Row(BaseModel):
    type: str = Field("", max_length=40)
    date: str = Field("", max_length=20)
    contract_until: str = Field("", max_length=20)
    injury_type: str = Field("", max_length=100)
    duration_days: str = Field("", max_length=10)
    evidence: str = Field("", max_length=2000)  # check() enforces the 300-character rule
    note: str = Field("", max_length=1000)


class DocRows(BaseModel):
    rows: list[Row] = Field(max_length=50)


def create_app(docs: pd.DataFrame, sheet: Path) -> FastAPI:
    """docs: doc_id, url, title, snapshot, text (from labels.doc_texts)."""
    order = docs.doc_id.tolist()
    texts = dict(zip(docs.doc_id, docs.text))
    rows = read_sheet(sheet)
    lock = threading.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(request: Request, call_next):  # DNS-rebinding guard: only our own host names
        host = request.headers.get("host", "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            return HTMLResponse("forbidden", status_code=403)
        return await call_next(request)

    def state(d: str) -> dict:
        return {"rows": rows.get(d, []), "problems": doc_problems(d, rows.get(d, []), texts[d]),
                "labelled": is_labelled(rows.get(d, []))}

    def progress() -> dict:
        done = [d for d in order if is_labelled(rows.get(d, []))]
        flagged = [i for i, d in enumerate(order) if doc_problems(d, rows.get(d, []), texts[d])]
        first = next((i for i, d in enumerate(order) if not is_labelled(rows.get(d, []))), 0)
        return {"done": len(done), "total": len(order), "first_unlabelled": first, "with_problems": flagged}

    @app.get("/", response_class=HTMLResponse)
    def page():
        return PAGE.read_text(encoding="utf-8")

    @app.get("/api/docs")
    def all_docs():
        return {"split": sheet.stem, "docs": [{"doc_id": r.doc_id, "title": r.title, "snapshot": r.snapshot, "url": r.url,
                                              "text": r.text} for r in docs.itertuples()], **progress()}

    @app.get("/api/doc/{i}")
    def get_doc(i: int):
        if not 0 <= i < len(order):
            raise HTTPException(404)
        return state(order[i])

    @app.put("/api/doc/{i}")
    def put_doc(i: int, body: DocRows):
        if not 0 <= i < len(order):
            raise HTTPException(404)
        d = order[i]
        with lock:
            rows[d] = [r.model_dump() for r in body.rows]
            write_sheet(sheet, order, rows)
        return state(d) | {"progress": progress()}

    return app


def main() -> None:
    import uvicorn
    from scout.text import store
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["test", "dev", "train"])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    sheet = DIR / f"{a.split}.csv"
    if not sheet.exists():
        raise SystemExit(f"{sheet} missing: run `python -m scout.finetune.labels render {a.split}` first")
    ids = pd.read_csv(SAMPLE_FILE).query("split == @a.split").doc_id.tolist()
    cache = DIR / f"{a.split}.docs.json"  # gitignored like the sheet; later sessions don't need Postgres
    if cache.exists():
        docs = pd.read_json(cache, orient="records", dtype=False)
        if docs.doc_id.tolist() != ids:
            raise SystemExit(f"{cache} doesn't match the sampled {a.split} set: delete it and rerun with Postgres up")
    else:
        with store.connect() as conn:
            docs = doc_texts(conn, ids)
        docs.to_json(cache, orient="records", force_ascii=False, indent=0)
    print(f"backup: {backup(sheet)}")
    url = f"http://127.0.0.1:{a.port}/"
    print(f"labelling {a.split} at {url} (Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(1.0, webbrowser.open, (url,)).start()
    uvicorn.run(create_app(docs, sheet), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
