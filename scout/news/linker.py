"""Link player mentions in Guardian articles to player_ids: name + club + date, skipping ambiguous mentions.

Point-in-time: a candidate must have a valuation in the LOOKBACK_DAYS before the article, and a shared name is
resolved only by the candidate's club *at the article date* (scout.data.snapshots.club_at). Nothing after the
article date is used. Works on article text (live-fetched, never stored) or on Guardian tags alone.
"""
import re
import unicodedata
from dataclasses import dataclass

import numpy as np
import pandas as pd

from scout.data.snapshots import club_at

LINKER_VERSION = "v1"
LOOKBACK_DAYS = 730
MAX_NAME_TOKENS = 4
CLUB_AFFIXES = {"fc", "afc", "cf", "sc", "ac", "as", "ssc", "us", "sv", "vfb", "vfl", "tsg", "fk", "cd", "rcd", "sd", "ud",
                "rc", "ogc", "losc", "stade", "football", "club", "de", "la", "calcio", "1", "1899", "1846", "1904", "1909"}
_WORD = re.compile(r"[a-z0-9]+(?:['\-][a-z0-9]+)*")


def fold(text: str) -> str:
    """Lowercase, strip accents, keep length (offsets in the folded text equal offsets in the original)."""
    out = []
    for ch in text:
        base = unicodedata.normalize("NFKD", ch)[0].lower()
        out.append(base if len(base) == 1 else ch)
    return "".join(out)


def norm_name(s: str) -> str:
    return " ".join(_WORD.findall(fold(str(s))))


def club_keys(name: str) -> set[str]:
    """Matching keys for a club name: the full normalized name and the name without common affixes."""
    toks = norm_name(name).split()
    core = [t for t in toks if t not in CLUB_AFFIXES]
    return {k for k in {" ".join(toks), " ".join(core)} if k}


@dataclass
class Index:
    names: dict            # normalized full name -> list of player_ids
    mononyms: set          # normalized single-token names that belong to a player
    club_by_key: dict      # club key -> club_id (keys shared by several clubs are dropped)
    valued: pd.DataFrame   # player_id, date: valuation dates (for "active at the article date")


def build_index(raw: dict, clubs: pd.DataFrame) -> Index:
    p = raw["players"][["player_id", "name"]].dropna()
    p = p.assign(key=p.name.map(norm_name))
    names = p.groupby("key").player_id.apply(list).to_dict()
    mononyms = {k for k in names if " " not in k and len(k) >= 3}
    keys = [(k, cid) for cid, n in zip(clubs.club_id, clubs.name) for k in club_keys(n)]
    kdf = pd.DataFrame(keys, columns=["key", "club_id"]).drop_duplicates()
    unique = kdf.groupby("key").club_id.nunique() == 1
    club_by_key = kdf[kdf.key.isin(unique[unique].index)].set_index("key").club_id.to_dict()
    return Index(names, mononyms, club_by_key, raw["valuations"][["player_id", "date"]])


def find_name_spans(text: str, idx: Index) -> list[tuple[int, int, str]]:
    """(start, end, key) for every full-name match (longest first, non-overlapping), plus capitalized mononyms."""
    folded = fold(text)
    words = [(m.start(), m.end(), m.group()) for m in _WORD.finditer(folded)]
    spans, i = [], 0
    while i < len(words):
        hit = None
        for n in range(min(MAX_NAME_TOKENS, len(words) - i), 0, -1):
            key = " ".join(w for _, _, w in words[i:i + n])
            if key in idx.names and (n > 1 or (key in idx.mononyms and text[words[i][0]].isupper())):
                hit = (words[i][0], words[i + n - 1][1], key, n)
                break
        if hit:
            spans.append(hit[:3])
            i += hit[3]
        else:
            i += 1
    return spans


def article_clubs(text: str | None, tags: list[dict], idx: Index) -> set:
    """Clubs named in the article: Guardian keyword tags (title or slug) plus club names in the text."""
    found = set()
    for t in tags:
        for raw_name in (t.get("webTitle") or "", (t.get("id") or "").split("/")[-1].replace("-", " ")):
            for k in club_keys(raw_name):
                if k in idx.club_by_key:
                    found.add(idx.club_by_key[k])
    if text:
        folded = " " + norm_name(text) + " "
        found |= {cid for k, cid in idx.club_by_key.items() if len(k) >= 4 and f" {k} " in folded}
    return found


def link_articles(articles: pd.DataFrame, raw: dict, idx: Index) -> tuple[pd.DataFrame, dict]:
    """articles: article_id, published_at (tz-naive date), text (str or None), tags (list[dict]).
    Returns mentions (article_id, player_id, start, end, key, method) and counts of skipped mentions."""
    rows, skipped = [], {"ambiguous": 0, "inactive": 0, "mononym_no_club": 0}
    cand = []  # (article row, span, candidate ids)
    for a in articles.itertuples(index=False):
        sources = [(s, e, k) for s, e, k in find_name_spans(a.text, idx)] if a.text else []
        tag_names = [norm_name(t.get("webTitle") or "") for t in a.tags if (t.get("type") == "keyword")]
        sources += [(-1, -1, k) for k in tag_names if k in idx.names and " " in k]  # player tags, if any
        for s, e, k in sources:
            cand.append((a.article_id, pd.Timestamp(a.published_at), s, e, k, idx.names[k],
                         article_clubs(a.text, a.tags, idx)))
    if not cand:
        return pd.DataFrame(columns=["article_id", "player_id", "start", "end", "key", "method"]), skipped

    # every (candidate player, article date) pair, resolved point-in-time in one vectorized pass
    pairs = pd.DataFrame([(i, pid, c[1]) for i, c in enumerate(cand) for pid in c[5]], columns=["cand", "player_id", "when"])
    pairs["when"] = pairs["when"].astype("datetime64[ns]")
    v = idx.valued.astype({"date": "datetime64[ns]"}).sort_values("date")
    last = pd.merge_asof(pairs.sort_values("when").reset_index(), v.rename(columns={"date": "vdate"}), left_on="when",
                         right_on="vdate", by="player_id", direction="backward").set_index("index").sort_index()
    pairs["active"] = (pairs["when"] - last.vdate).dt.days.le(LOOKBACK_DAYS).to_numpy()
    pairs["club"] = club_at(pairs.player_id, pairs["when"], raw).to_numpy()

    for i, c in enumerate(cand):
        article_id, _, s, e, key, _, clubs = c
        p = pairs[(pairs.cand == i) & pairs.active]
        if p.empty:
            skipped["inactive"] += 1
            continue
        on_club = p[p.club.isin(clubs)]
        mononym = " " not in key
        if len(p) == 1 and not mononym:
            pid, method = p.player_id.iloc[0], "unique_name"
        elif len(on_club) == 1:
            pid, method = on_club.player_id.iloc[0], "club"
        else:
            skipped["mononym_no_club" if mononym and on_club.empty else "ambiguous"] += 1
            continue
        rows.append((article_id, int(pid), s, e, key, method + ("" if s >= 0 else "_tag")))
    out = pd.DataFrame(rows, columns=["article_id", "player_id", "start", "end", "key", "method"])
    return out.drop_duplicates(["article_id", "player_id", "start"]), skipped
