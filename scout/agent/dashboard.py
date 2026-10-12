"""Tracing dashboard: cost, tokens, prompt-cache hit rate, latency and guardrail violations per day, plus the most
expensive recent conversations. Views live in db/agent.sql; reading uses the read-only role.

Usage: uv run --env-file .env python -m scout.agent.dashboard [--days 14]
       uv run --env-file .env python -m scout.agent.dashboard --install     (loader: create/refresh the views)
"""
import argparse
import os

import pandas as pd
import psycopg

from scout.data.manifest import ROOT


def main() -> None:
    from scout.ml.train import md_table
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--install", action="store_true")
    args = ap.parse_args()
    if args.install:
        with psycopg.connect(os.environ["LOADER_DATABASE_URL"]) as conn:
            conn.execute((ROOT / "db" / "agent.sql").read_text(encoding="utf-8"))
        print("views agent_daily and agent_conversations installed")
        return
    with psycopg.connect(os.environ["READER_DATABASE_URL"], connect_timeout=5) as conn:
        conn.read_only = True
        daily = _q(conn, "SELECT * FROM agent_daily WHERE day > current_date - %s ORDER BY day DESC", (args.days,))
        top = _q(conn, "SELECT * FROM agent_conversations WHERE started_at > now() - make_interval(days => %s) "
                                     "ORDER BY cost_usd DESC LIMIT 10", (args.days,))
        kinds = _q(conn, "SELECT kind, action, count(*) AS n FROM agent_violations "
                                       "WHERE created_at > now() - make_interval(days => %s) GROUP BY 1, 2 ORDER BY 1, 2", (args.days,))
    print(f"# Agent dashboard (last {args.days} days)\n\n## By day\n\n{md_table(daily.set_index('day')) if len(daily) else 'no calls'}\n")
    print(f"## Violations\n\n{md_table(kinds.set_index('kind')) if len(kinds) else 'none'}\n")
    print(f"## Most expensive conversations\n\n{md_table(top.set_index('conversation_id')) if len(top) else 'none'}")


def _q(conn, sql: str, params: tuple) -> pd.DataFrame:
    cur = conn.execute(sql, params)
    return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


if __name__ == "__main__":
    main()
