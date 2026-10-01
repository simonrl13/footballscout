"""Text pass: read article text page by page (show-fields=bodyText, 200 articles per call), link player
mentions in memory, and store only the links (news_mentions). Text is not persisted.

Gated by NEWS_TEXT_PASS_ENABLED=true (bulk processing of article text needs the user's go-ahead) and by the
shared daily call budget. Resumable per month via news_textpass_progress.
Usage: uv run --env-file .env python -m scout.news.textpass --start 2012-09 --end 2026-06 [--max-calls 100]
"""
import argparse
import calendar
import os
from datetime import date

import pandas as pd

from scout.news import guardian, store
from scout.news.backfill import months
from scout.news.linker import LINKER_VERSION, build_index, link_articles

DDL = """CREATE TABLE IF NOT EXISTS news_textpass_progress (
    month date PRIMARY KEY, next_page integer NOT NULL DEFAULT 1, total_pages integer,
    done boolean NOT NULL DEFAULT false, updated_at timestamptz NOT NULL DEFAULT now())"""


def enabled() -> bool:
    return os.environ.get("NEWS_TEXT_PASS_ENABLED", "false").strip().lower() == "true"


def search_text_page(month_start: date, month_end: date, page: int) -> dict:
    return guardian._get("search", {"section": "football", "from-date": month_start.isoformat(),
                                    "to-date": month_end.isoformat(), "order-by": "oldest",
                                    "page-size": guardian.PAGE_SIZE, "page": page,
                                    "show-tags": "keyword,contributor",
                                    "show-fields": guardian.SEARCH_FIELDS + ",bodyText"})


def store_mentions(conn, mentions: pd.DataFrame) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO news_mentions (article_id, player_id, start_offset, end_offset, method, linker_version) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [(r.article_id, int(r.player_id), int(r.start), int(r.end), r.method, LINKER_VERSION) for r in mentions.itertuples()])
    conn.commit()
    return len(mentions)


def run(conn, raw: dict, idx, start: str, end: str, max_calls: int, search=search_text_page) -> dict:
    conn.execute(DDL)
    stats = {"calls": 0, "articles": 0, "mentions": 0, "skipped": {}, "stopped": None}
    for month in months(start, end):
        conn.execute("INSERT INTO news_textpass_progress (month) VALUES (%s) ON CONFLICT DO NOTHING", (month,))
        next_page, done = conn.execute("SELECT next_page, done FROM news_textpass_progress WHERE month = %s", (month,)).fetchone()
        conn.commit()
        while not done:
            if stats["calls"] >= max_calls or not store.take_call(conn):
                stats["stopped"] = "max_calls" if stats["calls"] >= max_calls else "daily_limit"
                return stats
            last_day = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
            resp = search(month, last_day, next_page)
            stats["calls"] += 1
            items = resp.get("results", [])
            store.upsert_articles(conn, [guardian.to_row(r) for r in items])  # metadata only
            arts = pd.DataFrame({"article_id": [r["id"] for r in items],
                                 "published_at": [pd.Timestamp(r["webPublicationDate"]).tz_localize(None) for r in items],
                                 "text": [r.get("fields", {}).get("bodyText") or None for r in items],
                                 "tags": [r.get("tags", []) for r in items]})
            if len(arts):
                m, skipped = link_articles(arts, raw, idx)
                stats["mentions"] += store_mentions(conn, m)
                for k, v in skipped.items():
                    stats["skipped"][k] = stats["skipped"].get(k, 0) + v
            stats["articles"] += len(items)
            pages = resp.get("pages", 0)
            del arts, items, resp  # text lives only for this page
            done = next_page >= pages
            next_page += 1
            conn.execute("UPDATE news_textpass_progress SET next_page = %s, total_pages = %s, done = %s, updated_at = now() "
                         "WHERE month = %s", (next_page, pages, done, month))
            conn.commit()
    return stats


def main() -> None:
    if not enabled():
        raise SystemExit("NEWS_TEXT_PASS_ENABLED is not true: bulk text processing needs the user's go-ahead")
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2012-09")
    ap.add_argument("--end", default="2026-06")
    ap.add_argument("--max-calls", type=int, default=guardian.DAILY_LIMIT)
    args = ap.parse_args()
    from scout.data.raw import read_raw
    raw = read_raw()
    clubs = pd.read_csv(store.ROOT / "data" / "raw" / "clubs.csv", usecols=["club_id", "name"])
    with store.connect() as conn:
        store.ensure_schema(conn)
        print(run(conn, raw, build_index(raw, clubs), args.start, args.end, args.max_calls))


if __name__ == "__main__":
    main()
