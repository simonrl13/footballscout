"""Grading of the retrieval experiment (scout/evals/text_exp.py) and the set builder's filters: no API, no database."""
import pandas as pd

from scout.evals import text_exp as x
from scout.evals.text_set import RESERVE, band, transfer_candidates

TR = {"type": "transfer", "truth": "1.FC Nuremberg", "accept": ["1.FC Nuremberg", "Nuremberg", "Nurnberg"]}
CT = {"type": "contract", "truth": 2029}
FOOTER = "\n\nSources (Wikipedia, public text, not model output):\n[wiki 1] ... revision of 2026-06-01 ... 2027"


def test_labels_correct_wrong_declined():
    assert x.label(TR, "He joined 1. FC Nürnberg in July 2021.") == "correct"  # accents folded, whole words
    assert x.label(TR, "He joined Hertha BSC.") == "wrong"
    assert x.label(TR, "I don’t have transfer history in my tools.") == "declined"
    assert x.label(TR, None) == "declined"  # blocked or refused: nothing released
    assert x.label(CT, "His contract runs until June 2029 [wiki 1]." + FOOTER) == "correct"
    assert x.label(CT, "His deal runs until 2028 (data as of 12 June 2026)." + FOOTER) == "wrong"  # footer years ignored
    assert x.label(CT, "The tools don't include contract dates.") == "declined"
    assert x.label({**TR, "accept": ["Nice"]}, "He joined Venice.") == "wrong"  # no partial-word matches


def test_supported_needs_a_cited_passage_with_the_claim():
    cited = {1: {"text": "In 2025 he signed a new contract until 2029."}}
    assert x.supported(CT, "Until 2029 [wiki 1].", cited) is True
    assert x.supported(CT, "Until 2031 [wiki 1].", cited) is False
    assert x.supported(CT, "Until 2029.", {}) is False
    assert x.supported(TR, "He joined Hertha [wiki 1].", cited) is None  # owner judges wrong transfer claims


def test_mcnemar():
    assert x.mcnemar_p(0, 0) == 1.0
    assert round(x.mcnemar_p(8, 0), 4) == 0.0078
    assert x.mcnemar_p(3, 3) == 1.0


def test_set_filters():
    assert band(30e6) == "high" and band(5e6) == "mid" and band(4.9e6) == "low"
    assert all(RESERVE.search(n) for n in ["Whitecaps FC 2", "Atalanta U19", "Barcelona B"])
    assert not any(RESERVE.search(n) for n in ["Hannover 96", "1.FC Nuremberg"])
    demo = pd.DataFrame({"player_id": [1, 2, 3], "name": ["A", "B", "C"], "club": ["Z"] * 3, "value_eur": [1e6] * 3})
    t = pd.DataFrame({"player_id": [1, 2, 2, 3, 3], "from_club_name": ["X", "Y", "Z", "P", "Q"],
                      "to_club_name": ["Z", "Z", "Y", "Q", "R"],
                      "transfer_date": ["2019-07-10", "2018-07-10", "2019-07-10", "2019-07-10", "2019-08-01"]})
    c = transfer_candidates(demo, t)
    # 1: one move, kept; 2: back to a club he left before (loan return), dropped; 3: two moves in the window, dropped
    assert sorted(c[["player_id", "year", "truth"]].values.tolist()) == [[1, 2019, "Z"], [2, 2018, "Z"]]
