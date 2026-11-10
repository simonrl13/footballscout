"""Summaries of the exploratory agent eval (scout/evals/agent_compare.py): no servers, model or database."""
from scout.evals import agent_compare as ac


def _row(case, mode, verdict, secs=10.0, waited=0.0, category="text", set_="dev", violations=()):
    return {"case": case, "mode": mode, "verdict": verdict, "category": category, "set": set_, "outcome": "answer",
            "secs_raw": secs, "secs_net": None if secs is None else secs - waited, "cost_usd": 0.001, "failed": [],
            "violations": [{"kind": k, "action": a} for k, a in violations], "tools": [], "answer": "", "detail": None}


def test_counts_drops_gains_and_latency_excludes_waits():
    rows = [_row("a", "keyword", "PASS"), _row("a", "hybrid_rerank", "FAIL", secs=60, waited=50),
            _row("b", "keyword", "FAIL"), _row("b", "hybrid_rerank", "PASS", secs=60, waited=50),
            _row("c", "keyword", "PASS", secs=None, category="injection"),
            _row("c", "hybrid_rerank", "PASS", secs=None, category="injection", violations=[("number_check", "retried")]),
            _row("s", "keyword", "NOT GRADED", set_="smoke"), _row("s", "hybrid_rerank", "PASS", set_="smoke", secs=60, waited=50)]
    s = ac.summarize(rows)
    assert s["keyword"]["dev"] == (2, 3) and s["hybrid_rerank"]["dev"] == (2, 3)
    assert s["keyword"]["smoke"] == (0, 1) and s["hybrid_rerank"]["smoke"] == (1, 1) and s["keyword"]["not_graded"] == 1
    assert s["hybrid_rerank"]["injection"] == (1, 1) and s["hybrid_rerank"]["violations"]["number_check", "retried"] == 1
    assert s["hybrid_rerank"]["latency_n"] == 3 and s["hybrid_rerank"]["median_s"] == 10 and s["hybrid_rerank"]["median_raw_s"] == 60
    assert ac.changes(rows) == (["a"], ["b", "s"])


def test_order_is_seeded_and_only_ever_the_two_modes():
    orders = {ac.order(f"case-{i}") for i in range(40)}
    assert orders == {("keyword", "hybrid_rerank"), ("hybrid_rerank", "keyword")}
    assert ac.order("case-1") == ac.order("case-1")
