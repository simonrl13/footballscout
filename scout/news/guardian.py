"""Guardian Open Platform client (football section). Metadata only: no article text is requested here.

Rules (docs/SPEC.md): key from GUARDIAN_API_KEY; at most DAILY_LIMIT calls per day across all processes
(counted in Postgres, see scout.news.store.take_call); at most one call per second.
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date

API = "https://content.guardianapis.com"
DAILY_LIMIT = 500
PAGE_SIZE = 200  # the API maximum
# Dates only: never bodyText/body in the search call. Text is fetched per article, on demand (fetch_text).
SEARCH_FIELDS = "firstPublicationDate,lastModified,wordcount"  # wordcount is a number, not content
_clock = {"last_call": 0.0}  # monotonic time of the previous request (1 call/s)


def _get(path: str, params: dict) -> dict:
    key = os.environ.get("GUARDIAN_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GUARDIAN_API_KEY is not set in the environment (.env)")
    wait = 1.0 - (time.monotonic() - _clock["last_call"])
    if wait > 0:
        time.sleep(wait)
    url = f"{API}/{path}?" + urllib.parse.urlencode({**params, "api-key": key})
    req = urllib.request.Request(url, headers={"User-Agent": "scout-portfolio (github.com/simonrl13/footballscout)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)
    finally:
        _clock["last_call"] = time.monotonic()
    resp = payload.get("response", {})
    if resp.get("status") != "ok":
        raise RuntimeError(f"Guardian API error: {resp.get('message', 'unknown')}")  # message never contains the key
    return resp


def search_page(month_start: date, month_end: date, page: int) -> dict:
    """One page of football-section content published in [month_start, month_end], oldest first."""
    return _get("search", {"section": "football", "from-date": month_start.isoformat(),
                           "to-date": month_end.isoformat(), "order-by": "oldest", "page-size": PAGE_SIZE,
                           "page": page, "show-tags": "keyword,contributor", "show-fields": SEARCH_FIELDS})


def fetch_text(article_id: str) -> str:
    """Live body text for one article (for answers/citations). Callers cache it for at most 24 h."""
    resp = _get(urllib.parse.quote(article_id, safe="/"), {"show-fields": "bodyText"})
    return resp.get("content", {}).get("fields", {}).get("bodyText", "")


def to_row(item: dict) -> dict:
    """Keep only what the storage rules allow: id, URL, section, dates, tags."""
    fields = item.get("fields", {})
    return {
        "article_id": item["id"],
        "url": item["webUrl"],
        "section_id": item.get("sectionId"),
        "published_at": item["webPublicationDate"],
        "first_published_at": fields.get("firstPublicationDate"),
        "last_modified": fields.get("lastModified"),
        "wordcount": int(fields["wordcount"]) if str(fields.get("wordcount", "")).isdigit() else None,
        "tags": [{"id": t["id"], "type": t.get("type"), "webTitle": t.get("webTitle")} for t in item.get("tags", [])],
    }
