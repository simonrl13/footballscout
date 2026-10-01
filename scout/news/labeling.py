"""Hand-check file for player links: sample 100 links, label them in a spreadsheet, then score precision.

The CSV holds URLs, names and dates only (no article text): open each URL and check the named player.
Usage:
  uv run --env-file .env python -m scout.news.labeling sample   # -> labeling/links_v1.csv
  uv run python -m scout.news.labeling score                    # after filling the `correct` column (y/n)
"""
import argparse
import math
from pathlib import Path

import pandas as pd

from scout.data.manifest import ROOT

FILE = ROOT / "labeling" / "links_v1.csv"
COLUMNS = ["sample_id", "article_url", "published_date", "matched_name", "player_id", "player_name",
           "club_at_date", "method", "transfermarkt_url", "correct", "note"]


def sample_links(links: pd.DataFrame, n: int = 100, seed: int = 0) -> pd.DataFrame:
    """Stratified by link method (proportional, at least 5 per method when available)."""
    shares = links.method.value_counts(normalize=True)
    quotas = {m: max(5, round(n * s)) for m, s in shares.items()}
    parts = [g.sample(min(len(g), quotas[m]), random_state=seed) for m, g in links.groupby("method")]
    out = pd.concat(parts).sample(frac=1, random_state=seed).head(n).reset_index(drop=True)
    out.insert(0, "sample_id", range(1, len(out) + 1))
    return out.assign(correct="", note="")[COLUMNS]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def score(labeled: pd.DataFrame) -> pd.DataFrame:
    lab = labeled[labeled.correct.astype(str).str.strip().str.lower().isin(["y", "n"])]
    ok = lab.correct.str.strip().str.lower().eq("y")
    rows = []
    for name, mask in [("all", ok.index == ok.index)] + [(m, (lab.method == m).to_numpy()) for m in sorted(lab.method.unique())]:
        k, n = int(ok[mask].sum()), int(mask.sum())
        lo, hi = wilson(k, n)
        rows.append({"group": name, "labeled": n, "correct": k, "precision": k / n if n else float("nan"),
                     "95% CI low": lo, "95% CI high": hi})
    return pd.DataFrame(rows).set_index("group")


def _links_from_db() -> pd.DataFrame:
    from scout.data.raw import read_raw
    from scout.data.snapshots import club_at
    from scout.news import store
    from scout.news.linker import LINKER_VERSION
    with store.connect() as c:
        df = pd.DataFrame(c.execute(
            "SELECT m.article_id, a.url, a.published_at, m.player_id, m.method FROM news_mentions m "
            "JOIN news_articles a USING (article_id) WHERE m.linker_version = %s", (LINKER_VERSION,)).fetchall(),
            columns=["article_id", "article_url", "published_at", "player_id", "method"])
    raw = read_raw()
    when = pd.to_datetime(df.published_at, utc=True).dt.tz_localize(None)
    players = pd.read_csv(ROOT / "data" / "raw" / "players.csv", usecols=["player_id", "name", "url"]).set_index("player_id")
    clubs = pd.read_csv(ROOT / "data" / "raw" / "clubs.csv", usecols=["club_id", "name"]).set_index("club_id").name
    return df.assign(published_date=when.dt.date, matched_name=df.player_id.map(players.name),
                     player_name=df.player_id.map(players.name), transfermarkt_url=df.player_id.map(players.url),
                     club_at_date=club_at(df.player_id, when, raw).map(clubs))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["sample", "score"])
    args = ap.parse_args()
    if args.action == "sample":
        FILE.parent.mkdir(exist_ok=True)
        if FILE.exists():
            raise SystemExit(f"{FILE} exists; never overwrite labels")
        sample_links(_links_from_db()).to_csv(FILE, index=False)
        print(f"wrote {FILE}: fill `correct` with y/n (and `note` if useful), then run `score`")
    else:
        print(score(pd.read_csv(FILE, dtype=str).assign(method=lambda d: d.method)).round(3).to_string())


if __name__ == "__main__":
    main()
