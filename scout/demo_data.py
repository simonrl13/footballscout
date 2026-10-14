"""Demo-only database: what the local and deployed demos need (~50 MB in Postgres), without raw data or full
Wikipedia revisions.

export: data/demo/scout_demo.tar.gz holding CSVs of
  - demo_players (forecasts as of 2026-06-12, precomputed),
  - text_passages (Wikipedia passages for search_text; the search index is rebuilt on import),
  - text_documents: only the revisions the passages cite, metadata only (url, date; no page text),
  - wikidata_players: the demo players' page titles,
  plus manifest.json (row counts, SHA-256 of each CSV, source commit) and NOTICE.txt (licenses).
import: creates the schema (db/text.sql, the Wikipedia DDL, db/agent.sql, the passages DDL) and loads the CSVs with the
  loader role. Checks every CSV against the manifest first; refuses to overwrite existing demo rows unless --replace.

Usage: uv run --env-file .env python -m scout.demo_data export
       uv run --env-file .env python -m scout.demo_data import [--file PATH] [--url-env LOADER_DATABASE_URL] [--replace]
"""
import argparse
import hashlib
import io
import json
import os
import tarfile
import time

import psycopg
from psycopg import sql

from scout.data.manifest import ROOT, git_commit

FILE = ROOT / "data" / "demo" / "scout_demo.tar.gz"
# table -> (columns, row filter); the order is the load order (foreign keys)
TABLES = {
    "demo_players": (["player_id", "name", "name_search", "as_of", "club", "league", "position", "sub_position", "age",
                      "value_eur", "value_date", "predicted_log_change", "interval_low_log", "interval_high_log",
                      "factors", "model_run_id"], "TRUE"),
    "wikidata_players": (["player_id", "qid", "enwiki_title"], "player_id IN (SELECT player_id FROM demo_players)"),
    "text_documents": (["doc_id", "source", "url", "available_at", "meta"],
                       "doc_id IN (SELECT DISTINCT doc_id FROM text_passages)"),
    "text_passages": (["doc_id", "passage_no", "player_id", "section", "body"], "TRUE"),
}
NOTICE = """Scout demo data: licenses and attribution

1. Transfermarkt-derived data (demo_players, wikidata_players): built from the Kaggle dataset "Football Data from
   Transfermarkt" (davidcariboo/player-scores), released under CC0 1.0 Universal (public domain dedication,
   https://creativecommons.org/publicdomain/zero/1.0/). Wikidata identifiers in wikidata_players are also CC0.
   The forecasts, intervals and factors in demo_players are output of the Scout model (https://github.com/simonrl13/footballscout).

2. Wikipedia text (text_passages): excerpts of English Wikipedia articles, licensed under the Creative Commons
   Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0, https://creativecommons.org/licenses/by-sa/4.0/).
   - Attribution: each passage's article title is text_documents.meta->>'title' and its exact source revision is
     text_documents.url (https://en.wikipedia.org/w/index.php?oldid=...); the authors are the contributors listed in
     each article's history (https://en.wikipedia.org/w/index.php?title=<title>&action=history).
   - Changes: wiki markup removed (templates, tables, references, links rendered as their text) and the text split into
     paragraph passages of at most 1,200 characters. No other changes.
   - ShareAlike: text_passages.csv, as an adaptation, is distributed under CC BY-SA 4.0. No warranties are given.
"""


def export(conn, path=FILE) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"exported_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "source_commit": git_commit(), "tables": {}}
    with tarfile.open(path, "w:gz") as tar:
        for table, (cols, where) in TABLES.items():
            q = sql.SQL("COPY (SELECT {} FROM {} WHERE " + where + ") TO STDOUT WITH (FORMAT csv, HEADER true)").format(
                sql.SQL(", ").join(map(sql.Identifier, cols)), sql.Identifier(table))
            buf = io.BytesIO()
            with conn.cursor().copy(q) as copy:
                for chunk in copy:
                    buf.write(chunk)
            data = buf.getvalue()
            rows = data.count(b"\n") - 1
            manifest["tables"][table] = {"rows": rows, "sha256": hashlib.sha256(data).hexdigest()}
            _add(tar, f"{table}.csv", data)
        _add(tar, "NOTICE.txt", NOTICE.encode())
        _add(tar, "manifest.json", json.dumps(manifest, indent=1).encode())
    return manifest


def _add(tar, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def read(path=FILE) -> tuple[dict, dict]:
    """(manifest, {table: csv bytes}); raises if a CSV doesn't match its manifest hash."""
    with tarfile.open(path, "r:gz") as tar:
        files = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    manifest = json.loads(files["manifest.json"])
    data = {}
    for table, meta in manifest["tables"].items():
        blob = files[f"{table}.csv"]
        if hashlib.sha256(blob).hexdigest() != meta["sha256"]:
            raise SystemExit(f"{path.name}: {table}.csv does not match its manifest hash")
        data[table] = blob
    return manifest, data


def import_(conn, path=FILE, replace: bool = False) -> dict:
    from scout.text.passages import DDL as PASSAGES_DDL
    from scout.text.wikipedia import DDL as WIKI_DDL
    manifest, data = read(path)
    for f in ("db/text.sql",):
        conn.execute((ROOT / f).read_text(encoding="utf-8"))
    conn.execute(WIKI_DDL)
    conn.execute((ROOT / "db" / "agent.sql").read_text(encoding="utf-8"))
    conn.execute(PASSAGES_DDL)
    if conn.execute("SELECT count(*) FROM demo_players").fetchone()[0] and not replace:
        raise SystemExit("demo_players already has rows; pass --replace to load the demo data over them")
    for table in reversed(list(TABLES)):
        conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
    for table, (cols, _) in TABLES.items():
        q = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true)").format(
            sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, cols)))
        with conn.cursor().copy(q) as copy:
            copy.write(data[table])
    conn.commit()
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["export", "import"])
    ap.add_argument("--file", default=str(FILE))
    ap.add_argument("--url-env", default="LOADER_DATABASE_URL", help="env var holding the loader role's URL (never a URL)")
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()
    from pathlib import Path
    with psycopg.connect(os.environ[args.url_env], connect_timeout=10) as conn:
        m = export(conn, Path(args.file)) if args.action == "export" else import_(conn, Path(args.file), args.replace)
    print(f"{args.action}: {args.file} ({', '.join(f'{t} {v['rows']:,}' for t, v in m['tables'].items())})")


if __name__ == "__main__":
    main()
