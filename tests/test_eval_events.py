import pandas as pd
import pytest

from scout.text.eval_events import move_eval, wilson

D = pd.Timestamp
T = D("2017-09-01")


def test_precision_and_recall_against_transfermarkt():
    transfers = pd.DataFrame([
        (1, D("2017-07-01"), "Tottenham", "Bayern Munich"),   # extracted (day date, 10 days off) -> match + recalled
        (1, D("2017-01-20"), "Bayern Munich", "Norwich"),     # loan in January: extracted as month "2017-01"
        (1, D("2016-08-01"), "Spurs U18", "Tottenham"),       # youth move: not in the recall denominator
        (2, D("2017-03-01"), "Ajax", "PSV"),                  # never extracted -> missed
        (2, D("2015-03-01"), "Ajax II", "Ajax"),              # outside the window
    ], columns=["player_id", "date", "from_club_name", "to_club_name"])
    signals = pd.DataFrame([
        (1, T, "transfer", D("2017-07-11"), "day"),
        (1, T, "loan", D("2017-01-01"), "month"),
        (1, T, "transfer", D("2017-04-15"), "day"),           # no recorded move within 31 days -> unmatched
        (1, T, "injury", D("2017-03-01"), "month"),           # not a move: ignored
    ], columns=["player_id", "t", "signal_type", "event_date", "date_precision"])
    py = pd.DataFrame({"player_id": [1, 2], "t": [T, T]})
    r = move_eval(signals, transfers, py)
    assert (r["extracted"], r["matched"]) == (3, 2) and r["precision"] == pytest.approx(2 / 3)
    assert (r["real"], r["recalled"]) == (3, 2) and r["recall"] == pytest.approx(2 / 3)


def test_wilson_interval():
    lo, hi = wilson(8, 10)
    assert 0.49 < lo < 0.5 and 0.94 < hi < 0.95


def test_players_without_any_recorded_transfer_are_not_scored():
    transfers = pd.DataFrame([(1, D("2017-07-01"), "A", "B")], columns=["player_id", "date", "from_club_name", "to_club_name"])
    signals = pd.DataFrame([(1, T, "transfer", D("2017-07-02"), "day"), (9, T, "transfer", D("2017-07-02"), "day")],
                           columns=["player_id", "t", "signal_type", "event_date", "date_precision"])
    r = move_eval(signals, transfers, pd.DataFrame({"player_id": [1, 9], "t": [T, T]}))
    assert (r["uncovered"], r["extracted"], r["matched"]) == (1, 1, 1)
