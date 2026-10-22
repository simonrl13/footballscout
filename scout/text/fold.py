"""Accent- and case-folding for name matching. Standard library only: the API imports it, and the API image has no
pandas (the linker, which needs pandas, re-exports it)."""
import unicodedata

# letters Unicode doesn't decompose into a base letter + accent ("Ødegaard" must match "odegaard")
_LETTERS = str.maketrans("øØđĐłŁıðÐ", "ooddllidd")


def fold(text: str) -> str:
    """Lowercase, strip accents, keep length (offsets in the folded text equal offsets in the original)."""
    out = []
    for ch in text.translate(_LETTERS):
        base = unicodedata.normalize("NFKD", ch)[0].lower()
        out.append(base if len(base) == 1 else ch)
    return "".join(out)
