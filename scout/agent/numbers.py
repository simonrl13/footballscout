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


# Direction of a quoted number (pre-registered 2026-10-23, docs/PLAN.md). Used by the production smoke matcher; the
# production number check adopts it separately (fix 2). A number's direction comes from an explicit sign, else from
# a direction word right before it ("a fall of 18.6%", skipping small words) or right after it ("an 18.6% drop",
# "18.6% lower") in the same clause. "up to" / "down to" are not directions; a negated direction ("not expected to
# fall") is ambiguous. Ambiguous or no direction: None (callers then match on magnitude only).
NEGATIVE = {"fall", "falls", "falling", "fell", "drop", "drops", "dropping", "dropped", "decline", "declines",
            "declining", "declined", "decrease", "decreases", "decreasing", "decreased", "down", "lower", "lose",
            "loses", "losing", "lost", "loss"}
POSITIVE = {"rise", "rises", "rising", "rose", "increase", "increases", "increasing", "increased", "gain", "gains",
            "gaining", "gained", "up", "grow", "grows", "growing", "grew", "growth", "higher"}
FILLERS = {"of", "by", "a", "an", "the", "about", "around", "roughly", "approximately", "nearly", "almost", "some", "just"}
NEGATIONS = {"not", "no", "never", "without", "hardly", "unlikely"}
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
CLAUSE_END = re.compile(r"[;:!?\n]|\.(?!\d)")
AFTER = re.compile(r"\s*(?:%|percent\b|per cent\b)?\s*([a-z]+)")
SIGNS = {"+": 1, "-": -1, "−": -1}


def _negated(words: list[str]) -> bool:
    return any(w in NEGATIONS or w.endswith("n't") for w in words)


def _word_direction(word: str) -> int | None:
    return -1 if word in NEGATIVE else 1 if word in POSITIVE else None


def directed_numbers(text: str) -> list[tuple[str, int | None]]:
    """Each number in `text` with its stated direction: +1, -1, or None (no direction, or an ambiguous one)."""
    low, out, prev_end = text.lower(), [], 0
    for m in NUMBER.finditer(low):
        s, e = m.span()
        clause = max((c.end() for c in CLAUSE_END.finditer(low, 0, s)), default=0)
        direction = None
        if s > 0 and low[s - 1] in SIGNS and (s == 1 or not low[s - 2].isalnum()):  # "-40.9", not "20-30" or dates
            direction = SIGNS[low[s - 1]]
        else:
            start = max(clause, prev_end)  # never read past the previous number
            words = WORD.findall(low[start:s])
            i = len(words) - 1
            while i >= 0:
                if words[i] == "to" and i > 0 and words[i - 1] in ("up", "down"):
                    i -= 2  # "up to 40.9%", "down to 40%": a bound, not a direction
                elif words[i] in FILLERS:
                    i -= 1
                else:
                    break
            if i >= 0 and _word_direction(words[i]) is not None:
                negated = _negated(WORD.findall(low[clause:start]) + words[:i])
                direction = None if negated else _word_direction(words[i])
            else:
                after = AFTER.match(low, e)
                if after and _word_direction(after.group(1)) is not None:
                    negated = _negated(WORD.findall(low[clause:s]))
                    direction = None if negated else _word_direction(after.group(1))
        out.append((m.group(), direction))
        prev_end = e
    return out


if __name__ == "__main__":
    tool = '{"predicted_change_pct": -38.4, "market_value_eur_m": 60.0, "valuation_date": "2026-05-27", "source": "80% interval"}'
    assert unsupported("1. Kane: the model forecasts a 38.4% fall (80% interval), from EUR 60m on 2026-05-27.", [tool]) == []
    assert unsupported("A fall of about 38% to EUR 60,000,000.", [tool]) == []
    assert unsupported("Kane will fall 40% to EUR 36.9m.", [tool]) == ["40", "36.9"]
    print("ok")
