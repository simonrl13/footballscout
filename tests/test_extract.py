import pytest

from scout.text import extract

TEXT = "Kane limped off with a hamstring injury.\n\nTottenham have   extended Son's contract until 2026."


def test_verified_quotes_keep_offsets_into_original_text():
    out = {"players": [
        {"player_id": 1, "signals": [{"type": "injury", "detail": "injured", "evidence": "Kane limped off with a hamstring injury"}]},
        {"player_id": 2, "signals": [{"type": "contract", "detail": "contract_extended",
                                      "evidence": "Tottenham have extended Son's contract"}]},  # whitespace differs
    ]}
    rows = extract.verify_signals(TEXT, out, {1, 2})
    assert len(rows) == 2
    for r, quote in zip(rows, ["Kane limped off with a hamstring injury", "Tottenham have   extended Son's contract"]):
        assert TEXT[r["evidence_start"]:r["evidence_end"]] == quote
    assert all("evidence" not in r for r in rows)  # the quote text itself is never returned for storage


def test_hindsight_or_paraphrase_is_dropped():
    out = {"players": [{"player_id": 1, "signals": [
        {"type": "transfer_rumour", "detail": "linked_with_move", "evidence": "Kane later joined Bayern Munich"},  # not in text
        {"type": "injury", "detail": "injured", "evidence": "Kane was hurt"},                                      # paraphrase
    ]}]}
    assert extract.verify_signals(TEXT, out, {1}) == []


def test_unlisted_players_and_invalid_labels_are_dropped():
    out = {"players": [
        {"player_id": 99, "signals": [{"type": "injury", "detail": "injured", "evidence": "Kane limped off"}]},
        {"player_id": 1, "signals": [{"type": "sentiment", "detail": "injured", "evidence": "Kane limped off"}]},
    ]}
    assert extract.verify_signals(TEXT, out, {1}) == []


def test_request_uses_configured_model_and_schema():
    r = extract.build_request("football/2019/aug/10/kane-injury", TEXT, [(1, "Harry Kane")], "claude-haiku-4-5")
    assert r["params"]["model"] == "claude-haiku-4-5"
    assert r["params"]["output_config"]["format"]["schema"] is extract.SCHEMA
    assert "outside knowledge" in r["params"]["system"] and "untrusted data" in r["params"]["system"]
    assert set(r["custom_id"]) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def test_switch_and_model_come_from_env(monkeypatch):
    monkeypatch.delenv("TEXT_LLM_ENABLED", raising=False)
    monkeypatch.delenv("TEXT_LLM_MODEL", raising=False)
    assert not extract.enabled()
    with pytest.raises(RuntimeError):
        extract.model_name()
    monkeypatch.setenv("TEXT_LLM_ENABLED", "true")
    monkeypatch.setenv("TEXT_LLM_MODEL", "claude-haiku-4-5")
    assert extract.enabled() and extract.model_name() == "claude-haiku-4-5"


def test_cost_estimate_applies_batch_discount():
    e = extract.estimate_cost(1000, mean_words=800, mean_players=3, model="claude-haiku-4-5")
    assert e["usd_batch"] == pytest.approx(e["usd_standard"] * 0.5, abs=0.01)
    assert e["input_tokens"] == int(1000 * (350 + 800 * 1.4 + 45))
