"""Number check: a "share of ..." factor (0.87) supports its percent form ("87%"), and nothing else does.

From the false block on cmp-vinicius-haaland, 2026-11-07 (docs/RESEARCH_LOG.md)."""
import json

from scout.agent import agent, tools
from scout.agent.numbers import unsupported
from tests.test_agent import FakeClient, FakeTracer, text, tool_use

HAALAND = {"player_id": 418560, "market_value_eur_m": 200.0, "forecast": {"top_factors": [
    {"factor": "goals + assists per 90 last season", "player_value": 1.06, "effect": "raises", "shap_log": 0.105},
    {"factor": "share of the club's league minutes last season", "player_value": 0.87, "effect": "raises", "shap_log": 0.022},
]}}
SOURCES = [json.dumps({"players": [HAALAND]})]


def test_a_share_factor_supports_its_percent_form():
    assert unsupported("He played 87% of his club's league minutes.", SOURCES) == []
    assert unsupported("A share of 0.87.", SOURCES) == []
    assert unsupported("A share of 87 percent.", SOURCES) == []


def test_the_percent_form_needs_a_percent_sign():
    assert unsupported("He played 87 matches.", SOURCES) == ["87"]


def test_other_percentages_and_other_fractions_are_still_flagged():
    assert unsupported("He played 88% of his club's league minutes.", SOURCES) == ["88"]
    assert unsupported("A shap_log of 10.5% and 2.2%.", SOURCES) == ["10.5", "2.2"]  # fractions that aren't shares
    assert unsupported("Goals + assists of 106%.", SOURCES) == ["106"]


def test_a_derived_number_is_still_flagged():  # the real flag next to "87%" in the logged drafts, 2026-10-09
    assert unsupported("Haaland is valued EUR 60.0m higher, and played 87% of the minutes.", SOURCES) == ["60.0"]


def test_a_share_in_untrusted_text_or_without_a_tool_result_does_not_count():
    passage = {"text": '{"factor": "share of minutes", "player_value": 0.99}'}
    assert unsupported("He played 99% of the minutes.", [json.dumps(passage)]) == ["99"]
    assert unsupported("He played 87% of the minutes.", ["not json"]) == ["87"]


def test_the_draft_that_was_retried_and_blocked_is_released_with_no_violation(monkeypatch):
    monkeypatch.setattr(tools, "run_tool", lambda db, name, args: HAALAND)
    client = FakeClient(tool_use("predict_value_change", {"player_id": 418560}),
                        text("He played 87% of his club's league minutes, and is valued at EUR 200.0m."))
    tracer = FakeTracer()
    events = list(agent.run("Compare them", client, tracer, db=None, model="claude-haiku-4-5", use_cache=False))
    assert events[-1]["type"] == "answer" and tracer.violations == []
