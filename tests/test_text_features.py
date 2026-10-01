import pandas as pd

from scout.text.features import build_text_features, feature_names

T = pd.Timestamp("2020-09-01")


def articles(*rows):
    """rows: (doc_id, available, last_modified)"""
    return pd.DataFrame([(a, f"{f}T10:00:00Z", f"{m}T10:00:00Z") for a, f, m in rows],
                        columns=["doc_id", "available_at", "last_modified"])


BASE = articles(("a1", "2020-08-15", "2020-08-15"),   # 17 days before t
                ("a2", "2020-03-01", "2020-03-01"),   # within 365 d, outside 90 d
                ("a3", "2019-06-01", "2019-06-01"))   # older than 365 d
MENTIONS = pd.DataFrame({"doc_id": ["a1", "a2", "a3", "a1"], "player_id": [1, 1, 1, 2]})
SIGNALS = pd.DataFrame({"doc_id": ["a1", "a2"], "player_id": [1, 1], "signal_type": ["injury", "transfer_rumour"]})
SNAP = pd.DataFrame({"player_id": [1, 2, 3], "date": [T, T, T]})


def test_expected_counts():
    f = build_text_features(SNAP, BASE, MENTIONS, SIGNALS)
    assert list(f.columns) == feature_names("text")
    assert (f.loc[0, "text_docs_90d"], f.loc[0, "text_docs_365d"]) == (1, 2)
    assert (f.loc[0, "text_injury_365d"], f.loc[0, "text_transfer_rumour_365d"], f.loc[0, "text_contract_365d"]) == (1, 1, 0)
    assert f.loc[1, "text_docs_365d"] == 1 and f.loc[1, "text_injury_365d"] == 0  # signal belongs to player 1 only
    assert f.loc[2].sum() == 0  # no mentions -> zeros


def test_no_leakage_from_articles_published_on_or_after_t():
    future = pd.concat([BASE, articles(("f1", "2020-09-01", "2020-09-01"), ("f2", "2021-01-10", "2021-01-10"))])
    mentions = pd.concat([MENTIONS, pd.DataFrame({"doc_id": ["f1", "f2", "f2"], "player_id": [1, 1, 3]})])
    signals = pd.concat([SIGNALS, pd.DataFrame({"doc_id": ["f1", "f2"], "player_id": [1, 3],
                                                "signal_type": ["contract", "injury"]})])
    pd.testing.assert_frame_equal(build_text_features(SNAP, BASE, MENTIONS, SIGNALS),
                                  build_text_features(SNAP, future, mentions, signals))


def test_availability_date_is_used_not_the_edit_date():
    # public before t, but edited after t: still known at t
    a = articles(("e1", "2020-08-20", "2020-10-05"))
    f = build_text_features(SNAP.head(1), a, pd.DataFrame({"doc_id": ["e1"], "player_id": [1]}))
    assert f.loc[0, "text_docs_90d"] == 1


def test_edit_sensitivity_option_drops_articles_edited_after_t():
    a = articles(("e1", "2020-08-20", "2020-10-05"), ("e2", "2020-08-21", "2020-08-25"))
    m = pd.DataFrame({"doc_id": ["e1", "e2"], "player_id": [1, 1]})
    f = build_text_features(SNAP.head(1), a, m, exclude_edited_after_t=True)
    assert f.loc[0, "text_docs_90d"] == 1  # only e2 survives


def test_prefix_names_features_per_source():
    f = build_text_features(SNAP.head(1), BASE, MENTIONS, prefix="wiki")
    assert list(f.columns) == feature_names("wiki") and f.loc[0, "wiki_docs_365d"] == 2
