import pandas as pd

from scout.text.extract_wiki import EVENT_TYPES, SCHEMA, build_request, new_text, verify_events

PREV = "Kane is an English footballer. He joined Tottenham in 2004."
NOW = (PREV + " On 13 January 2017, Kane signed a new contract with Tottenham until 2022.\n"
       "In March 2017 he suffered an ankle injury that kept him out for six weeks. "
       "He was linked with a move to Real Madrid. In the 2012–13 season he was loaned to Norwich.")
W0, W1 = pd.Timestamp("2016-09-01"), pd.Timestamp("2017-09-01")


def ev(type_, date, evidence, **kw):
    return {"type": type_, "date": date, "evidence": evidence, "injury_type": kw.get("it"), "duration_days": kw.get("dd")}


def test_new_text_keeps_only_sentences_added_during_the_year():
    t = new_text(NOW, PREV)
    assert "signed a new contract" in t and "ankle injury" in t
    assert "joined Tottenham in 2004" not in t


def test_dated_verbatim_events_inside_the_window_are_kept():
    text = new_text(NOW, PREV)
    out = {"events": [
        ev("contract_extension", "2017-01-13", "On 13 January 2017, Kane signed a new contract with Tottenham until 2022"),
        ev("injury", "2017-03", "In March 2017 he suffered an ankle injury that kept him out for six weeks", it="ankle", dd=42),
    ]}
    kept, dropped = verify_events(text, out, W0, W1)
    assert [k["signal_type"] for k in kept] == ["contract_extension", "injury"]
    assert kept[1]["precision"] == "month" and kept[1]["duration_days"] == 42
    s, e = kept[0]["evidence_start"], kept[0]["evidence_end"]
    assert text[s:e].startswith("On 13 January 2017") and sum(dropped.values()) == 0


def test_events_are_dropped_for_each_failed_check():
    text = new_text(NOW, PREV)
    out = {"events": [
        ev("transfer", "2018-07-01", "Kane joined Bayern Munich"),                                        # not in text
        ev("loan", "2012", "In the 2012–13 season he was loaned to Norwich"),                             # year-only
        ev("loan", "2012-08", "In the 2012–13 season he was loaned to Norwich"),                          # outside window
        ev("injury", "2017-05-02", "he suffered an ankle injury that kept him out for six weeks"),        # ok window, but...
        ev("contract_expiry", "2017-06-30", "He was linked with a move to Real Madrid"),                  # year not in text
        ev("transfer_rumour", "2017-05", "He was linked with a move to Real Madrid"),                     # dropped type
    ]}
    kept, dropped = verify_events(text, out, W0, W1)
    assert dropped["no_quote"] == 1 and dropped["year_only"] == 1 and dropped["outside_window"] == 1
    assert dropped["date_not_in_text"] == 1 and dropped["bad_type"] == 1
    assert len(kept) == 1  # the injury quote has "March 2017" right before it, so its year is supported


def test_schema_has_no_rumours_and_request_is_guarded():
    assert "transfer_rumour" not in EVENT_TYPES
    assert SCHEMA["properties"]["events"]["items"]["properties"]["type"]["enum"] == EVENT_TYPES
    r = build_request("wikipedia:enwiki:diff:1:2", "text", "Harry Kane", "claude-haiku-4-5")
    sys = r["params"]["system"]
    assert "outside knowledge" in sys and "untrusted data" in sys and "rumours" in sys
