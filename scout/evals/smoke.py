"""Production smoke evals: a small fixed set (smoke.jsonl, pre-registered in docs/PLAN.md) sent to the deployed API.

Not the held-out set, and no bypass: the public limits apply, so requests start at least 16 s apart (at most 4 a
minute) and the set is 5 questions (under the 20-a-day limit). The URL comes from an environment variable named by
--url-env and is never written to the repo. Expected numbers are read from the local demo database (the same export
the deployed one was loaded from) and graded with the eval checks in run.py. Writes a dated report under reports/.

Forecast check v2 (pre-registered 2026-10-22, docs/PLAN.md; replaces "predict_value_change was called"), for cases with
`forecast_provenance`: (a) the answer quotes the predicted change and both 80% interval bounds, each matching
predict_value_change for the player (computed here, from the local demo data; same matching rule as `quote`);
(b) a search_players or predict_value_change call in the stream, re-run here from its logged input, returns those
three values for the player. (b) is graded only if the deployed data date (/meta) equals the local one; otherwise the
case is NOT GRADED, never passed or failed.

Number matching in the smoke checks (`quote` and `forecast_numbers`; pre-registered 2026-10-23): a number quoted with
decimals must equal the value to one decimal; a whole number matches if it is within 0.5 of the value, inclusive
(20.5 -> 20 or 21; 20.4 -> 20 only). The held-out and dev evals keep run._has_number (Python round, half to even).

Usage: uv run --env-file .env python -m scout.evals.smoke --url-env SCOUT_DEMO_URL [--max-usd 0.05]
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from scout.agent import tools
from scout.agent.numbers import numbers
from scout.data.manifest import ROOT, git_commit
from scout.evals.run import grade, resolve

CASES = Path(__file__).with_name("smoke.jsonl")
SPACING_S = 16
FORECAST_CHECK = "v2 (pre-registered 2026-10-22)"
PROVENANCE_TOOLS = ("search_players", "predict_value_change")
WHOLE_NUMBER_TOLERANCE = 0.5  # smoke checks only (pre-registered 2026-10-23)


def smoke_has_number(answer: str, value: float) -> bool:
    """`value` quoted as given (one decimal), or as a whole number within 0.5 of it, inclusive. Signs are ignored, as in
    run._has_number (a sign may be written as a word: "a fall of 18.6%")."""
    target = abs(value)
    for token in numbers(answer):
        n = float(token.replace(",", ""))
        if "." in token:
            if abs(n - round(target, 1)) < 1e-9:
                return True
        elif abs(n - target) <= WHOLE_NUMBER_TOLERANCE + 1e-9:
            return True
    return False


def expected_forecast(db, player_id: int) -> tuple[float, float, float]:
    f = tools.run_tool(db, "predict_value_change", {"player_id": player_id})["forecast"]
    return f["predicted_change_pct"], f["interval_80_pct"]["low"], f["interval_80_pct"]["high"]


def _player_forecast(name: str, result: dict, player_id: int) -> tuple | None:
    """The player's (change, low, high) in a tool result, or None if the result doesn't carry them."""
    if name == "predict_value_change":
        f = result.get("forecast") if result.get("player_id") == player_id else None
        return (f["predicted_change_pct"], f["interval_80_pct"]["low"], f["interval_80_pct"]["high"]) if f else None
    for p in result.get("players", []):
        if p.get("player_id") == player_id and p.get("interval_80_pct"):
            return p.get("predicted_change_pct"), p["interval_80_pct"].get("low"), p["interval_80_pct"].get("high")
    return None


def forecast_check(case: dict, events: list[dict], db, served_as_of: str, local_as_of: str) -> dict:
    """Checks (a) forecast_numbers and (b) provenance. provenance is None (not graded) if the data dates differ."""
    pid = case["forecast_provenance"]["player_id"]
    expected = expected_forecast(db, pid)
    text = events[-1].get("body") or events[-1].get("text", "")
    out = {"forecast_numbers": all(smoke_has_number(text, v) for v in expected)}
    if served_as_of != local_as_of:
        out["provenance"] = None  # re-running tools against other data proves nothing
        return out
    found = False
    for e in events:
        if e["type"] != "tool_call" or e["name"] not in PROVENANCE_TOOLS:
            continue
        try:
            result = tools.run_tool(db, e["name"], e["input"])
        except Exception:  # invalid logged input: this call can't be the source
            continue
        got = _player_forecast(e["name"], result, pid)
        found = found or (got is not None and all(abs(g - x) < 1e-9 for g, x in zip(got, expected)))
    out["provenance"] = found
    return out


def grade_case(case: dict, events: list[dict], db, served_as_of: str, local_as_of: str) -> dict:
    """All checks for one smoke case: run.py's checks, `quote` re-graded with the smoke matching rule, then the
    forecast check v2 where the case asks for it."""
    expected = resolve(case, db)
    checks = grade(case, expected, events)
    if expected["quote"] and "quote" in checks:
        checks["quote"] = all(smoke_has_number(events[-1].get("text", ""), v) for v in expected["quote"])
    if case.get("forecast_provenance"):
        checks |= forecast_check(case, events, db, served_as_of, local_as_of)
    return checks


def verdict(checks: dict) -> str:
    """FAIL if any graded check failed (an ungraded one can't rescue it), else NOT GRADED if any wasn't graded."""
    if any(v is False for v in checks.values()):
        return "FAIL"
    return "NOT GRADED" if any(v is None for v in checks.values()) else "PASS"


def data_date(url: str) -> str:
    with urllib.request.urlopen(f"{url.rstrip('/')}/meta", timeout=60) as r:
        return json.load(r)["data_as_of"]


def ask(url: str, question: str) -> tuple[int, list[dict], float]:
    req = urllib.request.Request(f"{url.rstrip('/')}/ask", data=json.dumps({"question": question}).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    t0, events = time.time(), []
    try:
        with urllib.request.urlopen(req, timeout=130) as r:
            events = [json.loads(line[6:]) for line in r if line.startswith(b"data: ")]
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    return status, events, time.time() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url-env", required=True, help="name of the env var holding the deployed URL (never the URL)")
    ap.add_argument("--max-usd", type=float, default=0.05)
    args = ap.parse_args()
    url, cases = os.environ[args.url_env], [json.loads(x) for x in CASES.read_text(encoding="utf-8").splitlines() if x]
    rows, spent, last = [], 0.0, 0.0
    with tools.connect() as db:
        served, local = data_date(url), tools.data_as_of(db)
        print(f"data date: deployed {served}, local {local}", flush=True)
        for case in cases:
            if spent >= args.max_usd:
                raise SystemExit(f"stopped: spent {spent:.4f} >= {args.max_usd}")
            time.sleep(max(0.0, last + SPACING_S - time.time()))
            last = time.time()
            status, events, secs = ask(url, case["question"])
            if status != 200 or not events:
                raise SystemExit(f"{case['id']}: HTTP {status}; stopping (no retries against the public limits)")
            checks = grade_case(case, events, db, served, local)
            spent += events[-1].get("cost_usd") or 0.0
            rows.append({"case": case, "events": events, "checks": checks, "secs": secs})
            print(f"{case['id']}: {verdict(checks)} {events[-1]['type']} {secs:.1f}s", flush=True)
    write_report(rows, spent, served, local)


def write_report(rows: list[dict], spent: float, served: str, local: str) -> Path:
    """A dated report per run (earlier runs' reports are never overwritten)."""
    day, commit = time.strftime("%Y-%m-%d", time.gmtime()), git_commit()
    verdicts = [verdict(r["checks"]) for r in rows]
    lines = [f"# M7 production smoke evals ({day})", "",
             f"Commit {commit}; deployed demo (public mode, normal limits); set `scout/evals/smoke.jsonl`, "
             "pre-registered in docs/PLAN.md. Generated by `python -m scout.evals.smoke`.",
             f"Forecast check {FORECAST_CHECK}. Data date: deployed {served}, local {local}"
             + ("." if served == local else " (differ: provenance not graded)."), "",
             f"**{verdicts.count('PASS')}/{len(rows)} passed**"
             + (f", {verdicts.count('NOT GRADED')} not graded" if "NOT GRADED" in verdicts else "")
             + f", cost US${spent:.4f}.", "",
             "| Case | Category | Verdict | Outcome | Checks | Failed | Not graded | Time (s) | Tools |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r, v in zip(rows, verdicts):
        failed = [k for k, x in r["checks"].items() if x is False]
        ungraded = [k for k, x in r["checks"].items() if x is None]
        called = ", ".join(e["name"] for e in r["events"] if e["type"] == "tool_call") or "none"
        lines.append(f"| {r['case']['id']} | {r['case']['category']} | {v} | {r['events'][-1]['type']} | "
                     f"{len(r['checks'])} | {', '.join(failed) or '-'} | {', '.join(ungraded) or '-'} | {r['secs']:.1f} | {called} |")
    lines += ["", "## Answers", ""]
    for r in rows:
        text = r["events"][-1].get("text", "").replace("\n", "\n> ")
        lines += [f"### {r['case']['id']}", f"**Q:** {r['case']['question']}", "", f"> {text}", ""]
    path = ROOT / "reports" / f"m7_smoke_{day}_{commit}.md"
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    main()
