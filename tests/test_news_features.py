import pandas as pd
import pytest

from scout.news.features import NEWS_FEATURES, build_news_features

T = pd.Timestamp("2020-09-01")


def articles(*rows):
    """rows: (article_id, first_published, last_modified)"""
    return pd.DataFrame([(a, f"{f}T10:00:00Z", f"{f}T10:00:00Z", f"{m}T10:00:00Z") for a, f, m in rows],
                        columns=["article_id", "published_at", "first_published_at", "last_modified"])


BASE = articles(("a1", "2020-08-15", "2020-08-15"),   # 17 days before t
                ("a2", "2020-03-01", "2020-03-01"),   # within 365 d, outside 90 d
                ("a3", "2019-06-01", "2019-06-01"))   # older than 365 d
MENTIONS = pd.DataFrame({"article_id": ["a1", "a2", "a3", "a1"], "player_id": [1, 1, 1, 2]})
SIGNALS = pd.DataFrame({"article_id": ["a1", "a2"], "player_id": [1, 1], "signal_type": ["injury", "transfer_rumour"]})
SNAP = pd.DataFrame({"player_id": [1, 2, 3], "date": [T, T, T]})


def test_expected_counts():
    f = build_news_features(SNAP, BASE, MENTIONS, SIGNALS)
    assert list(f.columns) == NEWS_FEATURES
    assert (f.loc[0, "news_articles_90d"], f.loc[0, "news_articles_365d"]) == (1, 2)
    assert (f.loc[0, "news_injury_365d"], f.loc[0, "news_transfer_rumour_365d"], f.loc[0, "news_contract_365d"]) == (1, 1, 0)
    assert f.loc[1, "news_articles_365d"] == 1 and f.loc[1, "news_injury_365d"] == 0  # signal belongs to player 1 only
    assert f.loc[2].sum() == 0  # no mentions -> zeros


def test_no_leakage_from_articles_published_on_or_after_t():
    future = pd.concat([BASE, articles(("f1", "2020-09-01", "2020-09-01"), ("f2", "2021-01-10", "2021-01-10"))])
    mentions = pd.concat([MENTIONS, pd.DataFrame({"article_id": ["f1", "f2", "f2"], "player_id": [1, 1, 3]})])
    signals = pd.concat([SIGNALS, pd.DataFrame({"article_id": ["f1", "f2"], "player_id": [1, 3],
                                                "signal_type": ["contract", "injury"]})])
    pd.testing.assert_frame_equal(build_news_features(SNAP, BASE, MENTIONS, SIGNALS),
                                  build_news_features(SNAP, future, mentions, signals))


def test_first_publication_date_is_used_not_the_edit_date():
    # first published before t, but republished/edited after t: still known at t
    a = articles(("e1", "2020-08-20", "2020-10-05"))
    f = build_news_features(SNAP.head(1), a, pd.DataFrame({"article_id": ["e1"], "player_id": [1]}))
    assert f.loc[0, "news_articles_90d"] == 1


def test_edit_sensitivity_option_drops_articles_edited_after_t():
    a = articles(("e1", "2020-08-20", "2020-10-05"), ("e2", "2020-08-21", "2020-08-25"))
    m = pd.DataFrame({"article_id": ["e1", "e2"], "player_id": [1, 1]})
    f = build_news_features(SNAP.head(1), a, m, exclude_edited_after_t=True)
    assert f.loc[0, "news_articles_90d"] == 1  # only e2 survives


@pytest.mark.parametrize("col", ["first_published_at"])
def test_missing_first_publication_falls_back_to_published_at(col):
    a = articles(("x", "2020-08-01", "2020-08-01")).assign(**{col: None})
    f = build_news_features(SNAP.head(1), a, pd.DataFrame({"article_id": ["x"], "player_id": [1]}))
    assert f.loc[0, "news_articles_90d"] == 1
