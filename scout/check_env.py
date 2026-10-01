"""Check .env syntax WITHOUT printing any of its content (names or values).

A malformed line (e.g. a missing "=") makes `uv run --env-file` print the whole offending line, secret included, in
its warning. Run this first after editing .env: it reports only line numbers and the kind of problem.

Usage: uv run python -m scout.check_env [path]
"""
import re
import sys
from pathlib import Path

LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*(\s+#.*)?$")


def problems(text: str) -> list[tuple[int, str]]:
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            out.append((n, "missing '=' between name and value"))
        elif line != raw.rstrip("\r\n") and raw[:1].isspace():
            out.append((n, "leading whitespace"))
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s+=|^[A-Za-z_][A-Za-z0-9_]*=\s", line):
            out.append((n, "space around '='"))
        elif not LINE.match(line):
            out.append((n, "unexpected characters (quotes or spaces in the value?)"))
    return out


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    found = problems(path.read_text(encoding="utf-8"))
    for n, what in found:
        print(f"{path.name} line {n}: {what}")
    print(f"{path.name}: {'OK' if not found else f'{len(found)} problem(s)'}")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
