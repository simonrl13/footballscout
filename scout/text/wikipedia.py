"""Wikipedia revision fetcher (M3a): the English Wikipedia page of each snapshot player, as it stood on each
snapshot date t and on the previous snapshot date (1 September a year earlier). Players are mapped via Wikidata's Transfermarkt player ID (P2446).

License and politeness (docs/SPEC.md): text is CC BY-SA 4.0 and is stored with the exact revision URL for
attribution; Wikidata is CC0. Requests are serial (1 at a time, < 5/s), carry a descriptive User-Agent with
contact, use maxlag, and back off after slow responses (Wikimedia robot policy).

Usage: uv run --env-file .env python -m scout.text.wikipedia [--limit N]     (resumable)
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd
from psycopg.types.json import Jsonb

from scout.text import store

UA = "ScoutResearchBot/0.1 (https://github.com/simonrl13/footballscout; scouting value research) python-urllib"
API = "https://en.wikipedia.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
PAUSE = 0.25  # seconds between requests (serial, well under 5 req/s)

DDL = """
ALTER TABLE text_documents ADD COLUMN IF NOT EXISTS body text;   -- stored for CC BY-SA sources only
CREATE TABLE IF NOT EXISTS wikidata_players (
    player_id    integer PRIMARY KEY,                 -- Transfermarkt id = our player_id
    qid          text NOT NULL,
    enwiki_title text,
    fetched_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS wiki_snapshot_revisions (
    player_id integer NOT NULL,
    as_of     date NOT NULL,                          -- a snapshot date t, or the previous 1 September
    doc_id    text REFERENCES text_documents (doc_id), -- NULL: no page/revision existed at as_of
    PRIMARY KEY (player_id, as_of)
);
"""


def _get(url: str, params: dict, accept="application/json", post: bool = False) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    if post:  # long SPARQL queries go in the body (Wikidata Query Service accepts form-encoded POST)
        req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), headers={
            "User-Agent": UA, "Accept": accept, "Content-Type": "application/x-www-form-urlencoded"})
    else:
        req = urllib.request.Request(full, headers={"User-Agent": UA, "Accept": accept, "Accept-Encoding": "identity"})
    for attempt in range(6):
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            raise
        took = time.monotonic() - t0
        if data.get("error", {}).get("code") == "maxlag":  # servers busy: wait and retry
            time.sleep(5 * (attempt + 1))
            continue
        time.sleep(5 if took > 1 else PAUSE)  # robot policy: slow response -> wait 5 s
        return data
    raise RuntimeError(f"giving up after retries: {full[:120]}")


# ---- wikitext -> plain text ---------------------------------------------------------------------------
_PATTERNS = [
    (re.compile(r"<!--.*?-->", re.S), ""),
    (re.compile(r"<ref[^>]*/>", re.I), ""),
    (re.compile(r"<ref[^>]*>.*?</ref>", re.I | re.S), ""),
    (re.compile(r"<(gallery|math|timeline|score|syntaxhighlight)[^>]*>.*?</\1>", re.I | re.S), ""),
]


def _strip_nested(text: str, open_: str, close: str) -> str:
    """Remove innermost-first nested blocks like {{...}} or {|...|}."""
    pattern = re.compile(re.escape(open_) + r"(?:(?!" + re.escape(open_) + r").)*?" + re.escape(close), re.S)
    prev = None
    while prev != text:
        prev, text = text, pattern.sub("", text)
    return text


def strip_wikitext(wt: str) -> str:
    for rx, rep in _PATTERNS:
        wt = rx.sub(rep, wt)
    wt = _strip_nested(wt, "{{", "}}")          # templates (infobox, citations, dates)
    wt = _strip_nested(wt, "{|", "|}")          # tables (career statistics)
    wt = re.sub(r"\[\[(?:File|Image|Category|Datei|Fichier):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", "", wt, flags=re.I)
    wt = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", wt)   # [[target|label]] -> label
    wt = re.sub(r"\[https?://[^\]]*\]", "", wt)               # [url label]: source labels, not prose
    wt = re.sub(r"'{2,}", "", wt)                                # bold/italic
    wt = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\1.", wt, flags=re.M)  # headings -> sentence
    wt = re.sub(r"<[^>]+>", "", wt)                              # remaining tags
    wt = re.sub(r"^[*#:;]+\s*", "", wt, flags=re.M)              # list markers
    wt = re.sub(r"[ \t]+", " ", wt)
    wt = re.sub(r"\n{3,}", "\n\n", wt)
    return wt.strip()


# ---- mapping and fetching -------------------------------------------------------------------------------
def load_mapping(conn, player_ids) -> int:
    """Wikidata items whose Transfermarkt player ID (P2446) is one of ours, with their enwiki title (chunked)."""
    rows = {}
    ids = sorted({int(p) for p in player_ids})
    for i in range(0, len(ids), 500):
        values = " ".join(f'"{p}"' for p in ids[i:i + 500])
        q = ("SELECT ?item ?tm ?article WHERE { VALUES ?tm { " + values + " } ?item wdt:P2446 ?tm . "
             "OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . } }")
        data = _get(SPARQL, {"query": q, "format": "json"}, accept="application/sparql-results+json", post=True)
        for b in data["results"]["bindings"]:
            title = b.get("article", {}).get("value")
            title = urllib.parse.unquote(title.rsplit("/wiki/", 1)[1]).replace("_", " ") if title else None
            pid = int(b["tm"]["value"])
            if pid not in rows or (rows[pid][1] is None and title):
                rows[pid] = (b["item"]["value"].rsplit("/", 1)[1], title)
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO wikidata_players (player_id, qid, enwiki_title) VALUES (%s, %s, %s) "
                        "ON CONFLICT (player_id) DO UPDATE SET qid = EXCLUDED.qid, enwiki_title = EXCLUDED.enwiki_title, "
                        "fetched_at = now()", [(p, q_, t) for p, (q_, t) in rows.items()])
    conn.commit()
    return len(rows)


def revision_at(title: str, as_of: pd.Timestamp) -> dict | None:
    """The revision in force at the start of `as_of` (latest revision with timestamp <= as_of 00:00 UTC)."""
    data = _get(API, {"action": "query", "prop": "revisions", "titles": title, "rvlimit": 1, "rvdir": "older",
                      "rvstart": as_of.strftime("%Y-%m-%dT00:00:00Z"), "rvprop": "ids|timestamp|content",
                      "rvslots": "main", "redirects": 1, "format": "json", "formatversion": 2, "maxlag": 5})
    pages = data.get("query", {}).get("pages", [])
    if not pages or "revisions" not in pages[0]:
        return None
    rev = pages[0]["revisions"][0]
    return {"revid": rev["revid"], "timestamp": rev["timestamp"], "title": pages[0]["title"],
            "wikitext": rev.get("slots", {}).get("main", {}).get("content", "")}


def snapshot_pairs(snapshot_years) -> pd.DataFrame:
    """(player_id, as_of) for every labelled snapshot player-year: as_of = t and the previous 1 September."""
    from scout.data.raw import read_raw
    from scout.data.snapshots import build_snapshots
    s = build_snapshots(read_raw(), years=snapshot_years)
    s = s[s.target.notna()][["player_id", "date"]]
    return pd.concat([s.rename(columns={"date": "as_of"}),
                      s.assign(as_of=s.date - pd.DateOffset(years=1))[["player_id", "as_of"]]]).drop_duplicates()


def wanted_pairs(conn, pairs: pd.DataFrame) -> pd.DataFrame:
    """Pairs still to fetch, for mapped players only."""
    mapped = pd.DataFrame(conn.execute("SELECT player_id, enwiki_title FROM wikidata_players WHERE enwiki_title IS NOT NULL").fetchall(),
                          columns=["player_id", "title"])
    done = pd.DataFrame(conn.execute("SELECT player_id, as_of FROM wiki_snapshot_revisions").fetchall(), columns=["player_id", "as_of"])
    pairs = pairs.merge(mapped, on="player_id")
    if len(done):
        done["as_of"] = pd.to_datetime(done.as_of)
        pairs = pairs.merge(done, on=["player_id", "as_of"], how="left", indicator=True)
        pairs = pairs[pairs._merge == "left_only"].drop(columns="_merge")
    return pairs.sort_values(["player_id", "as_of"]).reset_index(drop=True)


def fetch(conn, pairs: pd.DataFrame, log_every: int = 200) -> dict:
    stats = {"pairs": 0, "new_docs": 0, "no_revision": 0}
    known = {r[0] for r in conn.execute("SELECT doc_id FROM text_documents WHERE source = 'wikipedia'").fetchall()}
    t0 = time.time()
    for r in pairs.itertuples():
        rev = revision_at(r.title, r.as_of)
        doc_id = None
        if rev is None:
            stats["no_revision"] += 1
        else:
            doc_id = f"wikipedia:enwiki:rev:{rev['revid']}"
            if doc_id not in known:
                conn.execute(
                    "INSERT INTO text_documents (doc_id, source, url, available_at, meta, body) VALUES (%s, 'wikipedia', %s, %s, %s, %s) "
                    "ON CONFLICT (doc_id) DO NOTHING",
                    (doc_id, f"https://en.wikipedia.org/w/index.php?oldid={rev['revid']}", rev["timestamp"],
                     Jsonb({"title": rev["title"], "license": "CC BY-SA 4.0", "wikitext_chars": len(rev["wikitext"])}),
                     strip_wikitext(rev["wikitext"])))
                known.add(doc_id)
                stats["new_docs"] += 1
        conn.execute("INSERT INTO wiki_snapshot_revisions (player_id, as_of, doc_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                     (int(r.player_id), r.as_of.date(), doc_id))
        conn.commit()
        stats["pairs"] += 1
        if stats["pairs"] % log_every == 0:
            rate = stats["pairs"] / (time.time() - t0)
            print(f"{stats} | {rate:.2f} pairs/s | remaining ~{(len(pairs) - stats['pairs']) / rate / 3600:.1f} h", flush=True)
    return stats


def main() -> None:
    from scout.data.snapshots import YEARS
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    with store.connect() as conn:
        store.ensure_schema(conn)
        conn.execute(DDL)
        conn.commit()
        all_pairs = snapshot_pairs(YEARS)
        if conn.execute("SELECT count(*) FROM wikidata_players").fetchone()[0] == 0:
            print(f"wikidata mapping: {load_mapping(conn, all_pairs.player_id):,} players", flush=True)
        pairs = wanted_pairs(conn, all_pairs)
        print(f"pairs to fetch: {len(pairs):,}", flush=True)
        print(fetch(conn, pairs.head(args.limit) if args.limit else pairs), flush=True)


if __name__ == "__main__":
    main()
