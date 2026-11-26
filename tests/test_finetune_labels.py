"""Sampling and label-sheet checks for the fine-tuning experiment (no DB, no network)."""
import pandas as pd

from scout.finetune.labels import check, template
from scout.finetune.sample import draw, split_of, stratum_of


def test_strata_first_match_and_word_starts():
    assert stratum_of("He was injured on loan.") == "injury"
    assert stratum_of("He signed a new contract and joined.") == "contract"
    assert stratum_of("He went on loan.") == "loan"
    assert stratum_of("The fee was undisclosed.") == "transfer"
    assert stratum_of("He felt restrained by coffee.") == "none"  # no 'fee', 'strain' or 'loan' inside words


def test_draw_keeps_players_in_one_split_and_is_deterministic():
    docs = pd.DataFrame({"doc_id": [f"d{i}" for i in range(400)], "player_id": [i // 4 for i in range(400)],
                         "text": ["loan", "injury", "contract", "plain text"] * 100})
    a, b = draw(docs), draw(docs)
    pd.testing.assert_frame_equal(a, b)
    assert a.groupby("player_id").split.nunique().max() == 1
    assert (a.split == a.player_id.map(split_of)).all()
    assert a.groupby(["split", "stratum"]).size().max() <= 30


def test_check_rejects_non_verbatim_and_bad_fields():
    texts = {"d1": "He joined Leeds on 3 July 2019.", "d2": "Nothing here."}
    ok = pd.DataFrame([{"doc_id": "d1", "row": "1", "type": "transfer", "date": "2019-07-03", "contract_until": "",
                        "injury_type": "", "duration_days": "", "evidence": "He joined Leeds on 3 July 2019", "note": ""},
                       {"doc_id": "d2", "row": "1", "type": "none", "date": "", "contract_until": "",
                        "injury_type": "", "duration_days": "", "evidence": "", "note": ""}])
    assert check(ok, texts) == []
    bad = ok.copy()
    bad.loc[0, ["evidence", "date", "type"]] = ["He joined Leeds in July", "July 2019", "move"]
    assert check(ok.assign(date=""), texts) == []  # no date stated is a valid label
    errs = check(bad, texts)
    assert len(errs) == 3
    assert any("documents have no row" in e for e in check(ok.iloc[:1], texts))
    assert list(template(pd.DataFrame({"doc_id": ["d1"]})).columns)[:2] == ["doc_id", "row"]
