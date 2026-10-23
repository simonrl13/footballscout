"""Direction check (fix 2, 2026-10-23): percentages whose stated direction contradicts the tool results."""
import json

from scout.agent.numbers import contradictions, unsupported

WIRTZ = json.dumps({"player_id": 598577, "forecast": {"predicted_change_pct": -18.6,
                                                      "interval_80_pct": {"low": -40.9, "high": 20.5}}})
QUESTION = "What does the model forecast for Florian Wirtz?"


def check(answer, *sources):
    return contradictions(answer, [QUESTION, *(sources or (WIRTZ,))])


def test_a_stated_direction_against_the_tool_value_is_caught():
    assert check("The model forecasts a rise of 18.6%.") == ["18.6"]
    assert check("The model forecasts +18.6% over 12 months.") == ["18.6"]
    assert check("The model forecasts an 18.6% increase.") == ["18.6"]
    # the number check alone lets all three through: the magnitude is in the tool result
    assert unsupported("The model forecasts a rise of 18.6%.", [QUESTION, WIRTZ]) == []


def test_a_contradiction_on_an_interval_bound_is_caught():
    assert check("The 80% interval runs from -40.9% to -20.5%.") == ["20.5"]
    assert check("The 80% interval runs from a rise of 40.9% to a rise of 20.5%.") == ["40.9"]
    assert check("The 80% interval runs from -41% to +21%.") == []  # whole numbers, right directions


def test_agreeing_ambiguous_and_undirected_percentages_pass():
    for answer in ["The model forecasts a fall of 18.6%.", "The model forecasts -18.6%, from -40.9% to +20.5%.",
                   "The model forecasts an 18.6% drop.", "The model forecasts a change of 18.6%.",
                   "His value is not expected to fall by 18.6%.", "a fall of up to 40.9%"]:
        assert check(answer) == [], answer


def test_same_magnitude_with_both_signs_passes_documented_limitation():
    # Known limitation: if the tool results hold 18.6 and -18.6 (two players, or a value and a change), a stated
    # direction can't be attributed to one of them, so it passes. Only clear contradictions are flagged.
    other = json.dumps({"player_id": 1, "forecast": {"predicted_change_pct": 18.6}})
    assert check("The model forecasts a rise of 18.6%.", WIRTZ, other) == []
    assert check("The model forecasts a fall of 18.6%.", WIRTZ, other) == []


def test_only_percentages_and_only_tool_numbers_with_a_known_sign():
    assert check("His value could rise 18.6 places.") == []  # not a percentage: out of scope
    # numbers from the question or from text (e.g. a Wikipedia passage inside a tool result) have no known sign
    passage = json.dumps({"passages": [{"text": "His value fell 12% in 2024."}]})
    assert contradictions("Wikipedia says his value rose 12%.", ["Did his value rise 12%?", passage]) == []
    assert contradictions("The model forecasts a rise of 7%.", ["Will it rise 7%?"]) == []
    assert check("The model forecasts a rise of 99%.") == []  # no matching value: unsupported() handles it


def test_list_markers_and_ranges_are_not_misread():
    assert check("1. Florian Wirtz: a fall of 18.6%\n2. Someone else") == []
    assert check("Players aged 20-30 often see a fall of 18.6%.") == []
