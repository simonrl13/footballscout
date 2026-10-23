"""Smoke forecast check v2 (pre-registered 2026-10-22): numbers + provenance instead of a tool path.
Unit tests only: tools are faked, no database, no /ask calls."""
import json

import pytest

from scout.agent import tools
from scout.evals import smoke
from scout.evals.run import _has_number

WIRTZ, OTHER = 598577, 132098
FORECAST = {"predicted_change_pct": -18.6, "interval_80_pct": {"low": -40.9, "high": 20.5}}
CASE = json.loads(smoke.CASES.read_text(encoding="utf-8").splitlines()[0])
GOOD = ("The model forecasts a median change of -18.6% over the next 12 months. The 80% interval runs from -40.9% to "
        "+20.5%.")


@pytest.fixture(autouse=True)
def fake_tools(monkeypatch):
    """predict_value_change and search_players over two players; invalid input raises like the real validation."""
    def run_tool(db, name, args):
        if name == "predict_value_change":
            pid = args["player_id"]
            f = FORECAST if pid == WIRTZ else {"predicted_change_pct": -38.4, "interval_80_pct": {"low": -57.4, "high": -7.6}}
            return {"player_id": pid, "forecast": f}
        if name == "search_players":
            if "name" not in args:
                raise ValueError("invalid input")
            hits = [{"player_id": WIRTZ, **FORECAST}] if "wirtz" in args["name"].lower() else [
                {"player_id": OTHER, "predicted_change_pct": -38.4, "interval_80_pct": {"low": -57.4, "high": -7.6}}]
            return {"count": len(hits), "players": hits}
        return {"error": "not a provenance tool"}
    monkeypatch.setattr(tools, "run_tool", run_tool)


def events(*calls, body=GOOD):
    return [{"type": "tool_call", "name": n, "input": i} for n, i in calls] + [
        {"type": "answer", "text": body, "body": body, "cost_usd": 0.0006, "notice": "AI"}]


def full(evts, served="2026-06-12", local="2026-06-12"):
    """All checks for the case, exactly as smoke.main computes them."""
    checks = smoke.grade_case(CASE, evts, None, served, local)
    return checks, smoke.verdict(checks)


def test_the_case_no_longer_requires_a_tool_path():
    assert "tools" not in CASE and CASE["forecast_provenance"] == {"player_id": WIRTZ}
    assert CASE["quote"] and CASE["interval"]  # (c): quote and interval unchanged


def test_pass_via_search_players():
    checks, v = full(events(("search_players", {"name": "Florian Wirtz", "limit": 5})))
    assert v == "PASS" and checks["forecast_numbers"] and checks["provenance"]
    assert set(checks) == {"outcome", "quote", "interval", "forecast_numbers", "provenance"}


def test_pass_via_predict_value_change():
    checks, v = full(events(("search_players", {"name": "Wirtz"}), ("predict_value_change", {"player_id": WIRTZ})))
    assert v == "PASS" and checks["provenance"]
    checks, v = full(events(("predict_value_change", {"player_id": WIRTZ})))
    assert v == "PASS"


def test_fail_when_the_numbers_dont_match():
    for body in [GOOD.replace("+20.5%", "+25.0%"), GOOD.replace("-40.9%", "-41.9%"),
                 "The model forecasts a change of -18.6% over the next 12 months, with an 80% interval."]:
        checks, v = full(events(("search_players", {"name": "Florian Wirtz"}), body=body))
        assert v == "FAIL" and checks["forecast_numbers"] is False, body


def test_fail_when_no_qualifying_tool_call_appears():
    for calls in [(), (("search_text", {"query": "Wirtz"}),), (("compare_players", {"player_ids": [WIRTZ, OTHER]}),),
                  (("search_players", {"name": "Harry Kane"}),),  # a search that doesn't return the player
                  (("predict_value_change", {"player_id": OTHER}),),  # another player's forecast
                  (("search_players", {"limit": 5}),)]:  # invalid logged input: can't be the source
        checks, v = full(events(*calls))
        assert v == "FAIL" and checks["provenance"] is False and checks["forecast_numbers"], calls


def test_whole_numbers_within_half_a_point_match_inclusive():
    assert smoke.smoke_has_number("about 20%", 20.5) and smoke.smoke_has_number("about 21%", 20.5)
    assert smoke.smoke_has_number("a fall of 40%", -40.5) and smoke.smoke_has_number("a fall of 41%", -40.5)
    assert smoke.smoke_has_number("about 20%", 20.4) and not smoke.smoke_has_number("about 21%", 20.4)
    assert smoke.smoke_has_number("-19%", -18.6) and not smoke.smoke_has_number("-18%", -18.6)  # 0.6 away
    # numbers with decimals must match to one decimal; no tolerance for them
    assert smoke.smoke_has_number("+20.5%", 20.5) and not smoke.smoke_has_number("+20.4%", 20.5)
    assert not smoke.smoke_has_number("-18.5%", -18.6)


def test_the_held_out_rule_is_unchanged():
    """run._has_number (dev and held-out evals) still rounds half to even: 20.5 -> 20 only."""
    assert _has_number("about 20%", 20.5) and not _has_number("about 21%", 20.5)
    assert _has_number("a fall of 40%", -40.5) and not _has_number("a fall of 41%", -40.5)


def test_rounded_answers_pass_the_whole_case():
    for upper in ["+20%", "+21%"]:  # the 20.5 bound written either way
        whole = f"The model forecasts a change of -19% over the next 12 months; the 80% interval runs from -41% to {upper}."
        checks, v = full(events(("predict_value_change", {"player_id": WIRTZ}), body=whole))
        assert v == "PASS" and checks["quote"] and checks["forecast_numbers"], upper
    for wrong in ["+22%", "-18.5%"]:
        body = "The model forecasts a change of -19%; the 80% interval runs from -41% to +20%.".replace(
            "+20%" if wrong == "+22%" else "-19%", wrong)
        assert full(events(("predict_value_change", {"player_id": WIRTZ}), body=body))[1] == "FAIL", wrong


def test_signs_may_be_written_as_words():
    words = ("The model forecasts a fall of 18.6% over the next 12 months; the 80% interval runs from a fall of 40.9% "
             "to a rise of 20.5%.")
    checks, v = full(events(("search_players", {"name": "Florian Wirtz"}), body=words))
    assert v == "PASS" and checks["forecast_numbers"]


def test_data_date_mismatch_refuses_to_grade_provenance():
    checks, v = full(events(("search_players", {"name": "Florian Wirtz"})), served="2026-06-12", local="2026-07-01")
    assert checks["provenance"] is None and v == "NOT GRADED"  # never passed on data it can't re-run against
    checks, v = full(events(), served="2026-06-12", local="2026-07-01")
    assert checks["provenance"] is None and v == "NOT GRADED"  # nor failed
    wrong = GOOD.replace("+20.5%", "+25.0%")
    checks, v = full(events(("search_players", {"name": "Florian Wirtz"}), body=wrong), "2026-06-12", "2026-07-01")
    assert checks["provenance"] is None and v == "FAIL"  # (a) failed: the case fails whatever (b) would say


def test_report_states_the_check_version_dates_and_ungraded_cases(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    monkeypatch.setattr(smoke, "git_commit", lambda: "abc1234")
    (tmp_path / "reports").mkdir()
    evts = events(("search_players", {"name": "Florian Wirtz"}))
    checks, _ = full(evts, "2026-06-12", "2026-07-01")
    path = smoke.write_report([{"case": CASE, "events": evts, "checks": checks, "secs": 4.2}], 0.0006,
                              "2026-06-12", "2026-07-01")
    report = path.read_text(encoding="utf-8")
    assert path.name.endswith("_abc1234.md")
    rules = report.splitlines()[3]
    for rule in ["forecast check v2", "smoke whole-number tolerance", "direction rule"]:  # every rule in effect
        assert rule in rules, rule
    assert "deployed 2026-06-12, local 2026-07-01 (differ: provenance not graded)" in report
    assert "**0/1 passed**, 1 not graded" in report and "| NOT GRADED |" in report and "| provenance |" in report


def test_a_wrong_sign_fails_under_the_smoke_rule():
    assert not smoke.smoke_has_number("+40%", -40.5)
    assert not smoke.smoke_has_number("a rise of 41%", -40.5)
    assert not smoke.smoke_has_number("a fall of 20%", 20.5)


def test_directions_that_agree_match():
    assert smoke.smoke_has_number("The model forecasts a fall of 18.6%.", -18.6)
    assert smoke.smoke_has_number("The model forecasts -19% over 12 months.", -18.6)
    assert smoke.smoke_has_number("The model forecasts an 18.6% drop.", -18.6)
    assert smoke.smoke_has_number("His value could end 18.6% lower.", -18.6)
    assert smoke.smoke_has_number("from a fall of 40.9% to a rise of 20.5%", -40.9)
    assert smoke.smoke_has_number("from a fall of 40.9% to a rise of 20.5%", 20.5)


def test_up_to_and_down_to_are_not_directions():
    # "a fall of up to 40.9%" reads as negative: "up to" is skipped and "fall" gives the direction
    assert smoke.smoke_has_number("a fall of up to 40.9%", -40.9)
    assert not smoke.smoke_has_number("a fall of up to 40.9%", 40.9)
    assert smoke.smoke_has_number("it could go down to 40%", 40.5) and smoke.smoke_has_number("down to 40%", -40.5)


def test_a_negated_direction_matches_on_magnitude():
    for value in (-18.6, 18.6):
        assert smoke.smoke_has_number("His value is not expected to fall by 18.6%.", value)
        assert smoke.smoke_has_number("It isn't an 18.6% drop.", value)


def test_no_sign_and_no_direction_word_matches_on_magnitude():
    for value in (-18.6, 18.6):
        assert smoke.smoke_has_number("The model forecasts 18.6% over 12 months.", value)


def test_direction_reading_does_not_misfire():
    from scout.agent.numbers import directed_numbers
    assert directed_numbers("a 12-month forecast, ages 20-30, data as of 2026-06-12") == [
        ("12", None), ("20", None), ("30", None), ("2026", None), ("06", None), ("12", None)]
    assert directed_numbers("a rise of 5% and 18.6%") == [("5", 1), ("18.6", None)]  # a direction doesn't carry over
    assert directed_numbers("It fell. 18.6% is the forecast.") == [("18.6", None)]  # nor across sentences
    assert directed_numbers("-40.9% to +20.5%") == [("40.9", -1), ("20.5", 1)]
