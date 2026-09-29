"""Load Transfermarkt CSVs from data/raw/ into Postgres and build the target table.

Usage: uv run --env-file .env python -m scout.data.load
"""
import io
import os
from pathlib import Path

import pandas as pd
import psycopg

from scout.data.target import build_targets

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
TABLES = ["competitions", "clubs", "players", "games", "appearances", "player_valuations", "transfers"]


def copy_csv(cur, table: str) -> None:
    path = RAW / f"{table}.csv"
    with open(path, "rb") as f:
        cols = f.readline().decode("utf-8").strip().replace('"', "")
        f.seek(0)
        # FORCE_NULL: treat quoted empty strings as NULL too, not just unquoted ones
        sql = f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true, FORCE_NULL ({cols}))"
        with cur.copy(sql) as cp:
            while chunk := f.read(1 << 20):
                cp.write(chunk)


def main() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute((ROOT / "db" / "schema.sql").read_text())
        for t in TABLES:
            copy_csv(cur, t)
            cur.execute(f"SELECT count(*) FROM {t}")
            print(f"{t}: {cur.fetchone()[0]:,} rows")

        cur.execute("SELECT player_id, date, market_value_in_eur FROM player_valuations")
        vals = pd.DataFrame(cur.fetchall(), columns=["player_id", "date", "market_value_in_eur"])
        targets = build_targets(vals)
        buf = io.StringIO()
        targets.to_csv(buf, index=False, header=False, date_format="%Y-%m-%d")
        with cur.copy("COPY valuation_targets FROM STDIN WITH (FORMAT csv)") as cp:
            cp.write(buf.getvalue())
        print(f"valuation_targets: {len(targets):,} rows ({len(targets) / len(vals):.1%} of snapshots)")


if __name__ == "__main__":
    main()
