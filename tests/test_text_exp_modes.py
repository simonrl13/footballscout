"""text_exp --modes: the pair order is fixed by the seed, the review file never shows a mode, and the report renders."""
from scout.evals import text_exp


def row(i, mode, label, draft=None):
    return {"id": f"q{i}", "mode": mode, "type": "transfer", "band": "b", "question": f"Q{i}?", "truth": "Club",
            "label": label, "draft_label": draft or label, "answer": f"answer {i} {label}", "draft": f"answer {i} {label}",
            "outcome": "answer", "cites": 1, "supported": True if label == "correct" else None, "tools": [], "seconds": 4.0,
            "secs_net": 3.5, "cost_usd": 0.001, "retried": 0}


ROWS = [row(i, m, lab) for i in range(6) for m, lab in (("keyword", "correct" if i < 3 else "declined"),
                                                        ("hybrid_rerank", "correct" if i < 4 else "wrong"))]


def test_pair_order_is_seeded_and_covers_both_modes():
    orders = {text_exp.mode_order(f"q{i}") for i in range(40)}
    assert orders == {text_exp.MODES, text_exp.MODES[::-1]}
    assert text_exp.mode_order("q7") == text_exp.mode_order("q7")


def test_review_is_blind_and_complete():
    text, key = text_exp.blind_review(ROWS, "abc1234")
    body = text.split("\n", 4)[-1]  # after the header, which explains where the key is
    assert "keyword" not in body and "hybrid" not in body
    flagged = [r for r in ROWS if r["label"] in ("wrong", "declined")]
    assert len(key) == len(flagged) and {(v["id"], v["mode"]) for v in key.values()} == {(r["id"], r["mode"]) for r in flagged}


def test_report_has_the_paired_test():
    voyage = {"calls": 1, "embed_tokens": 10, "rerank_tokens": 100, "cost_usd": 0.0001}
    out = text_exp.modes_report(ROWS, "abc1234", "m", voyage, None)
    assert "only keyword correct 0, only hybrid_rerank correct 1" in out and "no difference detectable" in out
