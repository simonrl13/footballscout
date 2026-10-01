import pandas as pd

from scout.text.linker import build_index, find_name_spans, fold, link_articles

D = pd.Timestamp


def raw(rose_moves_on: str):
    """Two 'Danny Rose's: player 2 stays at Tottenham (10); player 3 moves to Watford (20) on `rose_moves_on`."""
    return {
        "players": pd.DataFrame({"player_id": [1, 2, 3, 4, 5],
                                 "name": ["Harry Kane", "Danny Rose", "Danny Rose", "Cris", "Old Timer"]}),
        "valuations": pd.DataFrame(
            [(1, D("2019-06-01"), 1e8, 10), (2, D("2019-06-01"), 1e7, 10), (3, D("2019-06-01"), 5e6, 10),
             (4, D("2019-06-01"), 1e6, 20), (5, D("2010-06-01"), 1e5, 10)],
            columns=["player_id", "date", "market_value_in_eur", "current_club_id"]),
        "transfers": pd.DataFrame([(3, D(rose_moves_on), 10, 20)], columns=["player_id", "date", "from_club_id", "to_club_id"]),
        "appearances": pd.DataFrame(columns=["game_id", "player_id", "player_club_id", "date", "competition_id",
                                             "minutes_played", "goals", "assists", "season"]).astype({"date": "datetime64[ns]", "player_id": "int64", "player_club_id": "int64"}),
        "games": pd.DataFrame({"competition_id": ["GB1"], "competition_type": ["domestic_league"]}),
    }


CLUBS = pd.DataFrame({"club_id": [10, 20], "name": ["Tottenham Hotspur Football Club", "Watford FC"]})
TEXT = "Harry Kane scored twice. Danny Rose was at Watford's training ground. Cris impressed. Old Timer watched."
WATFORD_TAG = [{"id": "football/watford", "type": "keyword", "webTitle": "Watford"}]


def articles(text=TEXT, tags=WATFORD_TAG, when="2019-08-10"):
    return pd.DataFrame({"article_id": ["a1"], "published_at": [D(when)], "text": [text], "tags": [tags]})


def test_fold_keeps_offsets():
    s = "Ödegaard and Müller"
    assert len(fold(s)) == len(s) and fold(s) == "odegaard and muller"


def test_spans_prefer_longest_full_name_and_require_capitalized_mononyms():
    idx = build_index(raw("2019-07-01"), CLUBS)
    keys = [k for _, _, k in find_name_spans(TEXT, idx)]
    assert keys == ["harry kane", "danny rose", "cris", "old timer"]
    assert [k for _, _, k in find_name_spans("the cris was lowercase", idx)] == []
    s, e, _ = find_name_spans(TEXT, idx)[0]
    assert TEXT[s:e] == "Harry Kane"


def test_links_unique_names_and_resolves_shared_names_by_club_at_article_date():
    r = raw("2019-07-01")  # player 3 moved to Watford BEFORE the article
    m, skipped = link_articles(articles(), r, build_index(r, CLUBS))
    got = dict(zip(m.key, zip(m.player_id, m.method)))
    assert got["harry kane"] == (1, "unique_name")
    assert got["danny rose"] == (3, "club")   # the Danny Rose at Watford on 2019-08-10
    assert got["cris"] == (4, "club")         # mononym, accepted only because Watford is in the article
    assert "old timer" not in got and skipped["inactive"] == 1


def test_future_transfer_cannot_resolve_an_ambiguous_name():
    r = raw("2019-08-20")  # player 3 moves to Watford AFTER the article
    m, skipped = link_articles(articles(), r, build_index(r, CLUBS))
    assert "danny rose" not in set(m.key)  # both Roses were at Tottenham on the article date -> skipped
    assert skipped["ambiguous"] >= 1


def test_mononym_without_club_context_is_skipped():
    r = raw("2019-07-01")
    m, skipped = link_articles(articles(text="Cris impressed.", tags=[]), r, build_index(r, CLUBS))
    assert m.empty and skipped["mononym_no_club"] == 1


def test_tags_only_mode_links_player_tags():
    r = raw("2019-07-01")
    tags = [{"id": "football/harry-kane", "type": "keyword", "webTitle": "Harry Kane"}]
    m, _ = link_articles(articles(text=None, tags=tags), r, build_index(r, CLUBS))
    assert list(zip(m.player_id, m.method)) == [(1, "unique_name_tag")]
