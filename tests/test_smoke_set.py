"""The production smoke set stays small, separate from the other eval sets, and gradeable."""
import json

from scout.evals import smoke
from scout.evals.run import SETS


def _cases(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def test_smoke_set_fits_the_public_limits_and_is_separate():
    cases = _cases(smoke.CASES)
    assert len(cases) == 5 and len({c["id"] for c in cases}) == 5
    assert smoke.SPACING_S >= 15  # at most 4 questions a minute (limit 5); 5 a run (limit 20 a day)
    others = {c["question"] for path in SETS.values() for c in _cases(path)}
    assert not others & {c["question"] for c in cases}
    assert {"forecast", "injection", "unanswerable", "text"} <= {c["category"] for c in cases}
