"""Postgres access for the public-text tables (db/text.sql), written with the scout_loader role."""
import os

import psycopg

from scout.data.manifest import ROOT


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["LOADER_DATABASE_URL"], connect_timeout=5)


def ensure_schema(conn) -> None:
    conn.execute((ROOT / "db" / "text.sql").read_text())  # static DDL, idempotent
