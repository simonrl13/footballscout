"""Number check: every number in an answer must come from a tool result in the same turn (or the user's question).

A number in the answer is supported if some source number, shown with the same number of decimals, equals it
(so 38.4 supports "38.4" and "38"; a whole number may also truncate: 40.8 supports "40"), or the same holds for the
source × 10^6 ("EUR 60.0m" supports "60,000,000").
Signs are ignored: "a fall of 38.4%" quotes -38.4.
"""
import re

# 1,234,567.8 | 1234.5 | 12 ; not glued to letters/underscores on the left (keys like interval_80_pct)
NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")
LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.M)


def numbers(text: str) -> list[str]:
    return NUMBER.findall(text)


def unsupported(answer: str, sources: list[str]) -> list[str]:
    """Numbers in `answer` that no source text supports (list markers like '1. ' are not claims)."""
    allowed = {float(n.replace(",", "")) for s in sources for n in numbers(s)}
    allowed |= {a * 1e6 for a in allowed}
    # ponytail: rounding makes small integers easy to support ("under 19" passes via age 18.8); an eval with an
    # LLM judge catches derived claims, add per-claim attribution if that proves too loose.
    out = []
    for n in numbers(LIST_MARKER.sub("", answer)):
        x = float(n.replace(",", ""))
        decimals = len(n.split(".")[1]) if "." in n else 0
        # whole numbers may also truncate: "40 years old" from an age of 40.8 (evals, 2026-10-09)
        if not any(round(a, decimals) == x or (decimals == 0 and int(a) == x) for a in allowed):
            out.append(n)
    return out


if __name__ == "__main__":
    tool = '{"predicted_change_pct": -38.4, "market_value_eur_m": 60.0, "valuation_date": "2026-05-27", "source": "80% interval"}'
    assert unsupported("1. Kane: the model forecasts a 38.4% fall (80% interval), from EUR 60m on 2026-05-27.", [tool]) == []
    assert unsupported("A fall of about 38% to EUR 60,000,000.", [tool]) == []
    assert unsupported("Kane will fall 40% to EUR 36.9m.", [tool]) == ["40", "36.9"]
    print("ok")
