"""Resumable backfill of Guardian football metadata (IDs, URLs, dates, tags), month by month, oldest first.

Stops cleanly at the daily call limit (or --max-calls) and resumes from news_backfill_progress on the next run.
Usage: uv run --env-file .env python -m scout.news.backfill --start 2013-06 --end 2026-06 [--max-calls 50]
"""
import argparse
import calendar
from datetime import date

from scout.news import guardian, store


def months(start: str, end: str) -> list[date]:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def backfill(conn, start: str, end: str, max_calls: int, search=guardian.search_page) -> dict:
    stats = {"calls": 0, "articles": 0, "months_done": 0, "stopped": None}
    for month in months(start, end):
        conn.execute("INSERT INTO news_backfill_progress (month) VALUES (%s) ON CONFLICT DO NOTHING", (month,))
        next_page, done = conn.execute("SELECT next_page, done FROM news_backfill_progress WHERE month = %s",
                                       (month,)).fetchone()
        conn.commit()
        while not done:
            if stats["calls"] >= max_calls:
                stats["stopped"] = "max_calls"
                return stats
            if not store.take_call(conn):
                stats["stopped"] = "daily_limit"
                return stats
            last_day = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
            resp = search(month, last_day, next_page)
            stats["calls"] += 1
            stats["articles"] += store.upsert_articles(conn, [guardian.to_row(r) for r in resp.get("results", [])])
            pages = resp.get("pages", 0)
            done = next_page >= pages
            next_page += 1
            conn.execute("UPDATE news_backfill_progress SET next_page = %s, total_pages = %s, done = %s, updated_at = now() "
                         "WHERE month = %s", (next_page, pages, done, month))
            conn.commit()
        stats["months_done"] += 1
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2012-06")
    ap.add_argument("--end", default="2026-06")
    ap.add_argument("--max-calls", type=int, default=guardian.DAILY_LIMIT)
    args = ap.parse_args()
    with store.connect() as conn:
        store.ensure_schema(conn)
        store.purge_text_cache(conn)
        print(backfill(conn, args.start, args.end, args.max_calls))


if __name__ == "__main__":
    main()
