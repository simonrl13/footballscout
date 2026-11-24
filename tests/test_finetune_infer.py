"""Prompt and parse rules for the open model (no torch, no model, no network)."""
import json

from scout.finetune.infer import SYSTEM, messages, parse, user_turn
from scout.text import extract_wiki as xw

EV = {"type": "loan", "date": "2019-07", "injury_type": None, "duration_days": None, "contract_until": None,
      "evidence": "joined Leeds on loan"}


def test_prompt_is_claudes_plus_schema():
    assert SYSTEM.startswith(xw.SYSTEM) and json.dumps(xw.SCHEMA) in SYSTEM
    assert user_turn("A B", "text") == xw.build_request("d", "text", "A B", "m")["params"]["messages"][0]["content"]
    m = messages("A", "t", [{"title": "S", "text": "s", "events": [EV]}])
    assert [x["role"] for x in m] == ["system", "user", "assistant", "user"]
    assert json.loads(m[2]["content"]) == {"events": [EV]}


def test_parse_is_strict():
    good = json.dumps({"events": [EV]})
    assert parse(good, False) == {"events": [EV]}
    assert parse(f"```json\n{good}\n```\n", False) == {"events": [EV]}  # one enclosing fence is stripped
    assert parse(good, True) is None  # stopped at max_new_tokens
    assert parse("Here you go: " + good, False) is None  # no repair
    assert parse(json.dumps({"events": [EV | {"type": "rumour"}]}), False) is None  # fails SCHEMA
    assert parse(json.dumps({"events": [{"type": "loan"}]}), False) is None  # missing fields
