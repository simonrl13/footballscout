"""Metric and gold-proposal helpers of scout/evals/retrieval_eval.py (no database, no API)."""
import itertools

import pytest

from scout.evals import retrieval_eval as re_


def test_rr_and_hits_use_the_first_relevant_passage_in_the_top_10():
    ranked = [("d", i) for i in range(12)]
    assert re_.rr(ranked, {("d", 2), ("d", 5)}) == pytest.approx(1 / 3)
    assert re_.rr(ranked, {("d", 11)}) == 0.0  # beyond the depth
    assert re_.hits(ranked, {("d", 2)}, 3) and not re_.hits(ranked, {("d", 2)}, 2)


@pytest.mark.parametrize("n,g", [(1, 1), (4, 1), (6, 2), (12, 3), (13, 1)])
def test_random_baseline_matches_brute_force(n, g):
    perms = list(itertools.permutations(range(n))) if n <= 6 else None
    exact = re_.random_baseline(n, g)
    if perms:  # relevant items are 0..g-1
        rrs = [next((1 / i for i, x in enumerate(p[:10], 1) if x < g), 0.0) for p in perms]
        assert exact["rr"] == pytest.approx(sum(rrs) / len(rrs))
        for k in re_.KS:
            assert exact[f"hits@{k}"] == pytest.approx(sum(any(x < g for x in p[:k]) for p in perms) / len(perms))
    else:  # large n: hits@k = 1 - C(n-g, k)/C(n, k); with g = 1, hits@k = k/n
        if g == 1:
            assert exact["hits@5"] == pytest.approx(5 / n) and exact["rr"] == pytest.approx(sum(1 / r for r in range(1, 11)) / n)


def test_permutation_test_is_seeded_and_sensible():
    assert re_.perm_p([0.0] * 10) == 1.0
    strong = re_.perm_p([0.5] * 12, draws=20_000)
    assert strong < 0.001 and strong == re_.perm_p([0.5] * 12, draws=20_000)
    assert re_.perm_p([0.5, -0.5] * 6, draws=20_000) > 0.5


def test_string_match_proposal_rule():
    tr = {"type": "transfer", "question": "Which club did X join in the summer 2018 transfer window?",
          "accept": ["Leipzig", "RB Leipzig"]}
    assert re_.string_match(tr, "In June 2018 he signed for RB Leipzig.")
    assert re_.string_match(tr, "Leipzig signed him for the 2018–19 season.")
    assert not re_.string_match(tr, "He joined Leipzig in 2019.")  # wrong year
    assert not re_.string_match(tr, "In 2018 he joined Lipsia.")
    ct = {"type": "contract", "question": "...", "truth": 2029}
    assert re_.string_match(ct, "He signed a new contract until 2029.")
    assert not re_.string_match(ct, "He scored 2029 goals.") and not re_.string_match(ct, "A contract until 2028.")


def test_paired_counts_wins_and_losses_on_hits_at_1():
    gold = {"a": {"player": {1}}, "b": {"player": {1}}, "c": {"player": {1}}, "z": {"player": set()}}
    row = lambda m, i, h, rr: {"mode": m, "id": i, "scope": "player", "hits@1": h, "rr": rr}  # noqa: E731
    rows = [row("keyword", "a", False, 0.5), row("vector", "a", True, 1.0),
            row("keyword", "b", True, 1.0), row("vector", "b", True, 1.0),
            row("keyword", "c", True, 1.0), row("vector", "c", False, 0.25),
            row("keyword", "z", False, 0.0), row("vector", "z", True, 1.0)]  # z has no gold: not counted
    t = re_.paired(rows, gold, "vector", "player")
    assert (t["wins"], t["losses"]) == (1, 1) and t["mcnemar_p"] == 1.0
    assert t["mrr_diff"] == pytest.approx((0.5 + 0 - 0.75) / 3)


def test_mcnemar_needs_six_net_wins_without_losses():
    """The pre-registered rule's arithmetic: 6-0 is the smallest clean win with p < 0.05; 8-1 and 10-2 too."""
    assert re_.mcnemar_p(5, 0) > 0.05 and re_.mcnemar_p(6, 0) < 0.05
    assert re_.mcnemar_p(7, 1) > 0.05 and re_.mcnemar_p(8, 1) < 0.05
    assert re_.mcnemar_p(9, 2) > 0.05 and re_.mcnemar_p(10, 2) < 0.05


def test_throttle_retries_429_and_reuses_query_embeddings(monkeypatch):
    import urllib.error

    from scout.text import retrieve
    calls = []

    def fake(path, payload):
        calls.append(path)
        if len(calls) == 1:
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        return {"data": [{"index": 0, "embedding": [0.0]}], "usage": {"total_tokens": 5}}
    monkeypatch.setattr(retrieve, "voyage", fake)
    monkeypatch.setattr(re_.time, "sleep", lambda s: None)
    re_.throttle(pace=0, cache_queries=True)
    p = {"input": ["q"], "model": "m"}
    assert retrieve.voyage("embeddings", p)["usage"]["total_tokens"] == 5  # retried after the 429
    assert retrieve.voyage("embeddings", p)["usage"]["total_tokens"] == 0  # cached: no call, no tokens
    retrieve.voyage("rerank", {"query": "q"})
    assert calls == ["embeddings", "embeddings", "rerank"]
