"""Agent loop with a fake Claude client and an in-memory tracer: no API calls, no database."""
import copy
from types import SimpleNamespace as NS

import pytest

from scout.agent import agent, tools
from scout.agent.numbers import unsupported

KANE = {"player_id": 132098, "name": "Harry Kane", "market_value_eur_m": 60.0,
        "forecast": {"predicted_change_pct": -38.4, "interval_80_pct": {"low": -57.4, "high": -7.6}}, "source": tools.SOURCE}
USAGE = {"input_tokens": 1000, "output_tokens": 100}


def tool_use(name, inp, id_="t1"):
    return {"content": [{"type": "tool_use", "id": id_, "name": name, "input": inp}], "stop_reason": "tool_use", "usage": USAGE}


def text(t):
    return {"content": [{"type": "text", "text": t}], "stop_reason": "end_turn", "usage": USAGE}


class FakeClient:
    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.messages = NS(create=self.create)

    def create(self, **req):
        self.requests.append(copy.deepcopy(req))  # the real client sends at call time
        reply = self.replies.pop(0)
        return NS(model_dump=lambda mode=None: reply)


class FakeTracer:
    def __init__(self, spent=0.0):
        self.spent, self.calls, self.violations, self.cache = spent, [], [], {}

    def spent_today(self):
        return self.spent + sum(c[4] for c in self.calls)

    def call(self, *args):
        self.calls.append(args[1:])

    def violation(self, cid, kind, detail, action):
        self.violations.append((kind, detail["numbers"], action))

    def cache_get(self, key):
        return self.cache.get(key)

    def cache_put(self, key, resp):
        self.cache[key] = resp


@pytest.fixture(autouse=True)
def stub_tools(monkeypatch):
    real = tools.run_tool

    def fake(db, name, args):
        if name == "predict_value_change":
            tools.PlayerId.model_validate(args)
            return KANE
        return real(db, name, args)  # validation errors still come from the real models
    monkeypatch.setattr(tools, "run_tool", fake)


def run(client, tracer=None, question="How will Harry Kane's value change?", **kw):
    tracer = tracer or FakeTracer()
    return list(agent.run(question, client, tracer, db=None, model="claude-haiku-4-5", use_cache=kw.get("use_cache", False))), tracer


def test_tool_loop_answers_with_supported_numbers_and_traces_every_call():
    client = FakeClient(tool_use("predict_value_change", {"player_id": 132098}),
                        text("The model forecasts a 38.4% fall (80% interval: -57.4% to -7.6%) from EUR 60.0m, a Transfermarkt estimate."))
    events, tracer = run(client)
    assert [e["type"] for e in events] == ["tool_call", "answer"]
    assert len(tracer.calls) == 2 and tracer.violations == []
    assert events[-1]["cost_usd"] == pytest.approx(2 * (1000 * 1 + 100 * 5) / 1e6)
    sent = client.requests[1]["messages"][-1]["content"][0]
    assert sent["type"] == "tool_result" and "38.4" in sent["content"] and not sent["is_error"]
    assert "not instructions" in client.requests[0]["system"]


def test_unsupported_number_gets_one_retry_then_passes():
    client = FakeClient(tool_use("predict_value_change", {"player_id": 132098}),
                        text("Kane should drop about 40% to EUR 36m."),
                        text("The model forecasts a 38.4% fall (80% interval -57.4% to -7.6%)."))
    events, tracer = run(client)
    assert events[-1]["type"] == "answer"
    assert tracer.violations == [("number_check", ["40", "36"], "retried")]
    assert "40, 36" in client.requests[2]["messages"][-1]["content"]


def test_repeated_violation_is_blocked_and_logged():
    client = FakeClient(tool_use("predict_value_change", {"player_id": 132098}), text("Drop of 40%."), text("Drop of 41%."))
    events, tracer = run(client)
    assert events[-1]["type"] == "blocked" and "41" not in events[-1]["text"]
    assert [v[2] for v in tracer.violations] == ["retried", "blocked"]


def test_spend_cap_refuses_before_calling_the_api():
    client = FakeClient()
    events, tracer = run(client, FakeTracer(spent=agent.DAILY_CAP_USD))
    assert events == [{"type": "refused", "conversation_id": events[0]["conversation_id"], "text": events[0]["text"]}]
    assert client.requests == [] and tracer.calls == []


def test_invalid_tool_input_is_returned_as_an_error_not_executed():
    client = FakeClient(tool_use("search_players", {"name": "x" * 500, "limit": 999}), text("Please ask with a shorter name."))
    events, _ = run(client)
    assert [e["type"] for e in events] == ["tool_call", "tool_error", "answer"]
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "ValidationError" in result["content"]


def test_cache_serves_identical_requests_without_api_calls():
    replies = [tool_use("predict_value_change", {"player_id": 132098}), text("The model forecasts a 38.4% fall.")]
    tracer = FakeTracer()
    run(FakeClient(*replies), tracer, use_cache=True)
    client = FakeClient()
    events, tracer = run(client, tracer, use_cache=True)
    assert events[-1]["type"] == "answer" and events[-1]["cost_usd"] == 0 and client.requests == []


def test_max_steps_ends_the_loop():
    client = FakeClient(*[tool_use("predict_value_change", {"player_id": 132098}, f"t{i}") for i in range(agent.MAX_STEPS)])
    events, _ = run(client)
    assert events[-1]["type"] == "refused" and len(client.requests) == agent.MAX_STEPS


def test_number_check():
    tool = '{"predicted_change_pct": -38.4, "market_value_eur_m": 60.0, "valuation_date": "2026-05-27", "interval_80_pct": 1}'
    assert unsupported("1. Kane: a 38.4% fall, about 38%, from EUR 60m (EUR 60,000,000) on 2026-05-27.", [tool]) == []
    assert unsupported("An 80% interval.", [tool]) == ["80"]          # numbers inside keys don't count
    assert unsupported("He is worth 61m and will fall 39.0%.", [tool]) == ["61", "39.0"]


def test_tool_specs_come_from_the_pydantic_models():
    specs = {s["name"]: s for s in tools.tool_specs()}
    assert set(specs) == {"get_player", "predict_value_change", "search_players", "compare_players"}
    assert specs["search_players"]["input_schema"]["properties"]["limit"]["maximum"] == 20
    assert specs["search_players"]["input_schema"]["additionalProperties"] is False


def test_fixed_facts_in_the_system_prompt_are_allowed():
    client = FakeClient(*[text("I only cover the Premier League, Ligue 1 and 5 other leagues, as of 2026-06-12.")] * 2)
    events, tracer = run(client, question="What's the weather in Lisbon?")
    assert events[-1]["type"] == "blocked"  # "5" is not stated anywhere
    client = FakeClient(text("I only cover player values in 7 leagues (e.g. Ligue 1), with data as of 2026-06-12."))
    events, tracer = run(client, question="What's the weather in Lisbon?")
    assert events[-1]["type"] == "answer" and tracer.violations == []


def test_whole_numbers_may_truncate_but_not_drift():
    tool = '{"age": 40.8, "predicted_change_pct": -29.7}'
    assert unsupported("He is 40 years old; a 29% or 30% fall.", [tool]) == []
    assert unsupported("He is 39 years old; a 28% fall.", [tool]) == ["39", "28"]
