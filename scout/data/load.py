"""Load the raw Transfermarkt CSVs into Postgres as the scout_loader role.

Checks the CSVs against data/manifest.json first. Every CSV column must exist in the table created by
db/schema.sql (an allow-list read from the database); identifiers are built with psycopg.sql, never f-strings.

Usage: uv run --env-file .env python -m scout.data.load
"""
import csv
import os

import psycopg
from psycopg import sql

from scout.data.manifest import RAW, ROOT, verify

TABLES = ["competitions", "clubs", "players", "games", "appearances", "player_valuations", "transfers"]


def table_columns(cur, table: str) -> set[str]:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s",
                (table,))
    return {r[0] for r in cur.fetchall()}


def copy_csv(cur, table: str) -> None:
    path = RAW / f"{table}.csv"
    with open(path, encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    unknown = set(header) - table_columns(cur, table)
    if unknown:
        raise ValueError(f"{path.name}: columns not in the {table} schema: {sorted(unknown)}")
    cols = sql.SQL(", ").join(map(sql.Identifier, header))
    # FORCE_NULL: treat quoted empty strings as NULL too, not just unquoted ones
    stmt = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true, FORCE_NULL ({}))").format(
        sql.Identifier(table), cols, cols)
    with open(path, "rb") as f, cur.copy(stmt) as cp:
        while chunk := f.read(1 << 20):
            cp.write(chunk)


def main() -> None:
    verify(TABLES)
    with psycopg.connect(os.environ["LOADER_DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute((ROOT / "db" / "schema.sql").read_text())  # static DDL, no interpolation
        for t in TABLES:
            copy_csv(cur, t)
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(t)))
            print(f"{t}: {cur.fetchone()[0]:,} rows")


if __name__ == "__main__":
    main()
