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
        return self.spent + sum(c[3] for c in self.calls)  # (step, model, usage, cost, ...)

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
    assert set(specs) == {"get_player", "predict_value_change", "search_players", "compare_players", "search_text"}
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


PASSAGE = {"player_id": 132098, "player": "Harry Kane", "section": "Bayern Munich", "text": "In 2025 Kane won the league.",
           "revision_date": "2026-06-01", "revision_url": "https://en.wikipedia.org/w/index.php?oldid=111",
           "page_history": "https://en.wikipedia.org/w/index.php?title=Harry+Kane&action=history", "license": "CC BY-SA 4.0"}


@pytest.fixture
def wiki(monkeypatch):
    def fake(db, name, args):
        tools.TextSearch.model_validate(args)
        return {"count": 2, "passages": [dict(PASSAGE), dict(PASSAGE, revision_url="https://en.wikipedia.org/w/index.php?oldid=222")]}
    monkeypatch.setattr(tools, "run_tool", fake)


def test_cited_passages_get_an_exact_revision_footer_with_the_license(wiki):
    client = FakeClient(tool_use("search_text", {"query": "league title", "player_id": 132098}),
                        text("Kane won the league in 2025 [wiki 2]."))
    events, _ = run(client)
    out = events[-1]
    assert out["type"] == "answer" and out["citations"] == 1
    # the only cited passage was search result 2; it is shown as [wiki 1] (owner's held-out note, 2026-10-13)
    assert out["text"].startswith("Kane won the league in 2025 [wiki 1].")
    assert "[wiki 1] Harry Kane's Wikipedia page, revision of 2026-06-01: https://en.wikipedia.org/w/index.php?oldid=222" in out["text"]
    assert "[wiki 2]" not in out["text"]
    assert "oldid=111" not in out["text"] and "CC BY-SA 4.0" in out["text"] and "action=history" in out["text"]
    result = client.requests[1]["messages"][-1]["content"][0]["content"]
    assert '"ref": "wiki 1"' in result and '"ref": "wiki 2"' in result


def test_invented_refs_and_long_quotes_are_retried_then_blocked(wiki):
    long_quote = '"' + "x" * 301 + '"'
    client = FakeClient(tool_use("search_text", {"query": "league"}), text("Kane won the league [wiki 3]."),
                        text(f"Kane: {long_quote} [wiki 1]."))
    events, tracer = run(client)
    assert events[-1]["type"] == "blocked"
    assert [(v[0], v[2]) for v in tracer.violations] == [("citation_check", "retried"), ("citation_check", "blocked")]
    assert "[wiki 3] does not exist" in client.requests[2]["messages"][-1]["content"]


def test_answers_without_wikipedia_get_no_footer():
    client = FakeClient(text("I only cover 7 leagues."))
    events, _ = run(client, question="Weather?")
    assert "Sources" not in events[-1]["text"] and events[-1]["citations"] == 0


def test_every_request_asks_for_prompt_caching_and_cache_tokens_are_priced():
    client = FakeClient(text("I only cover 7 leagues."))
    run(client, question="Weather?")
    assert client.requests[0]["cache_control"] == {"type": "ephemeral"}
    usage = {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 4000, "cache_creation_input_tokens": 0}
    assert agent.cost_usd("claude-haiku-4-5", usage) == pytest.approx((100 * 1 + 10 * 5 + 4000 * 0.1) / 1e6)


def test_thinking_blocks_are_passed_back_unmodified_even_when_empty():
    thinking = {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    first = tool_use("predict_value_change", {"player_id": 132098})
    first["content"].insert(0, thinking)
    client = FakeClient(first, text("The model forecasts a 38.4% fall (80% interval -57.4% to -7.6%)."))
    run(client)
    assert client.requests[1]["messages"][1]["content"][0] == thinking


def test_refusal_and_running_out_of_tokens_are_refused_not_answered():
    for stop in ("refusal", "max_tokens"):
        events, _ = run(FakeClient({"content": [], "stop_reason": stop, "usage": USAGE}))
        assert events[-1]["type"] == "refused"


def test_haiku_5_5_prices_and_its_long_prompt_card():
    small = {"input_tokens": 2000, "output_tokens": 500}
    assert agent.cost_usd("claude-haiku-5-5", small) == pytest.approx((2000 * 0.10 + 500 * 0.50) / 1e6)
    big = {"input_tokens": 90_000, "output_tokens": 100, "cache_read_input_tokens": 20_000}
    assert agent.cost_usd("claude-haiku-5-5", big) == pytest.approx((90_000 * 0.50 + 100 * 2.50 + 20_000 * 0.05) / 1e6)


def test_effort_comes_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_EFFORT", "medium")
    client = FakeClient(text("I only cover 7 leagues."))
    run(client, question="Weather?")
    assert client.requests[0]["output_config"] == {"effort": "medium"}


def test_refs_are_renumbered_in_order_of_first_appearance():
    citations = {1: "p1", 2: "p2", 3: "p3"}
    text, used = agent.renumber_refs("A [wiki 3]. B [wiki 1]. Again [wiki 3].", citations)
    assert text == "A [wiki 1]. B [wiki 2]. Again [wiki 1]." and used == {1: "p3", 2: "p1"}
    assert agent.renumber_refs("No refs.", citations) == ("No refs.", {})


def test_system_prompt_asks_for_the_data_date():
    assert "data as of 12 June 2026" in agent.SYSTEM
    assert not unsupported("Data as of 12 June 2026; valued on 2026-06-01.", [agent.SYSTEM, '"valuation_date": "2026-06-01"'])


def test_system_prompt_rules_for_medians_and_injected_figures():
    assert "central (median)" in agent.SYSTEM and "80% interval for the range" in agent.SYSTEM
    assert "without repeating that figure or claim" in agent.SYSTEM


def test_withheld_tools_are_neither_offered_nor_run():
    client = FakeClient(tool_use("search_text", {"query": "contract"}), text("I can't tell from the tools."))
    events = list(agent.run("q", client, FakeTracer(), db=None, model="claude-haiku-4-5", use_cache=False,
                            tools_off=frozenset({"search_text"})))
    assert all(t["name"] != "search_text" for r in client.requests for t in r["tools"])
    assert [e["type"] for e in events] == ["tool_call", "tool_error", "answer"]
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"]
