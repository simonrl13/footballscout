"""Text-free agent evals (M5a): golden questions graded with deterministic checks, no LLM judge yet.

Checks per case (only those the case asks for):
- outcome: an answer was released (injection cases may also be blocked: the claim never reaches the user)
- tools: the required tools were called (`tools`: all of them; `tools_any`: at least one; `tools_none`: none)
- quote: numbers the answer must contain, read from the tools at eval time (so they follow the data)
- names: the top result of a reference search must be named
- contains_all / contains_any / not_contains: phrases
- caveat: "Transfermarkt" appears when a market value is quoted; interval: "80%" appears with a forecast
- decline: the answer says the data/scope doesn't cover it

Every run uses the response cache (AGENT_CACHE semantics), so reruns of unchanged cases cost nothing. The CI subset is
saved as a recording (responses keyed by request hash + tool outputs + resolved expectations) and replayed in CI by
tests/test_evals_replay.py without an API key or a database.

Usage: uv run --env-file .env python -m scout.evals.run [--ci] [--max-usd 0.50]
"""
import argparse
import json
import re
import time
from pathlib import Path

from scout.agent import agent, tools
from scout.agent.numbers import numbers
from scout.data.manifest import ROOT, git_commit
from scout.text.linker import fold

HERE = Path(__file__).parent
GOLDEN = HERE / "golden.jsonl"
RECORDING = HERE / "recordings" / "ci.json"
REPORT = ROOT / "reports" / "m5a_evals.md"
DECLINE = ["not in", "isn't in", "is not in", "no data", "not available", "couldn't find", "could not find", "can't",
           "cannot", "don't have", "do not have", "not covered", "outside", "only help", "only cover", "not able",
           "unable", "no information", "not found", "doesn't include", "does not include", "no player found",
           "no players found", "no player named", "no results"]


def load_cases(ci_only: bool = False) -> list[dict]:
    cases = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [c for c in cases if c.get("ci")] if ci_only else cases


def _get(d, path: str):
    for k in path.split("."):
        d = d[k]
    return d


def resolve(case: dict, db) -> dict:
    """Expected numbers and names, read from the tools now."""
    return {"quote": [_get(tools.run_tool(db, q["tool"], q["args"]), q["path"]) for q in case.get("quote", [])],
            "names": [tools.run_tool(db, n["tool"], n["args"])["players"][n["top"] - 1]["name"] for n in case.get("names", [])]}


def _has_number(answer: str, value: float) -> bool:
    """The answer quotes `value` as given (38.4) or rounded to a whole number (38); signs may be words ("a fall of")."""
    targets = {round(abs(value), 1), float(round(abs(value)))}
    return any(abs(float(n.replace(",", "")) - t) < 1e-9 for n in numbers(answer) for t in targets)


def grade(case: dict, expected: dict, events: list[dict]) -> dict:
    final = events[-1]
    text = final.get("text", "")
    low, folded = text.lower(), fold(text)
    called = {e["name"] for e in events if e["type"] == "tool_call"}
    checks = {"outcome": final["type"] == "answer" or (case["category"] == "injection" and final["type"] == "blocked")}
    if case.get("tools"):
        checks["tools"] = set(case["tools"]) <= called
    if case.get("tools_any"):
        checks["tools"] = bool(set(case["tools_any"]) & called)
    if case.get("tools_none"):
        checks["tools"] = not called
    if expected["quote"]:
        checks["quote"] = all(_has_number(text, v) for v in expected["quote"])
    if expected["names"]:
        checks["names"] = all(fold(n) in folded for n in expected["names"])
    if case.get("contains_all"):
        checks["contains"] = all(p.lower() in low for p in case["contains_all"])
    if case.get("contains_any"):
        checks["contains"] = any(p.lower() in low for p in case["contains_any"])
    if case.get("not_contains"):
        checks["not_contains"] = not any(p.lower() in low for p in case["not_contains"])
    if case.get("caveat"):
        checks["caveat"] = "transfermarkt" in low
    if case.get("interval"):
        checks["interval"] = bool(re.search(r"80\s?%", text))
    if case.get("decline"):
        checks["decline"] = any(p in low.replace("’", "'") for p in DECLINE)
    return checks


class EvalTracer(agent.Tracer):
    """The real tracer (DB traces, spend cap, cache), also capturing what a recording needs."""

    def __init__(self):
        super().__init__()
        self.responses, self.new, self.violations = {}, {}, []

    def cache_get(self, key):
        r = super().cache_get(key)
        if r is not None:
            self.responses[key] = r
        return r

    def cache_put(self, key, response):
        super().cache_put(key, response)
        self.responses[key] = self.new[key] = response

    def violation(self, conversation_id, kind, detail, action):
        super().violation(conversation_id, kind, detail, action)
        self.violations.append({"numbers": detail["numbers"], "action": action})


def run_case(case: dict, client, tracer: EvalTracer, db, model: str) -> dict:
    tracer.responses, tracer.new, tracer.violations, outputs = {}, {}, [], []
    real_run_tool = tools.run_tool

    def recording_run_tool(conn, name, args):
        out = real_run_tool(conn, name, args)
        outputs.append({"name": name, "input": args, "output": json.loads(json.dumps(out, default=str))})
        return out
    tools.run_tool = recording_run_tool
    try:
        t0 = time.perf_counter()
        events = list(agent.run(case["question"], client, tracer, db, model=model, use_cache=True))
        seconds = time.perf_counter() - t0
    finally:
        tools.run_tool = real_run_tool
    return {"events": events, "seconds": seconds, "responses": tracer.responses, "new": tracer.new,
            "tool_outputs": outputs, "violations": tracer.violations}


def cost_of(responses: dict, model: str) -> float:
    return sum(agent.cost_usd(model, r["usage"]) for r in responses.values())


def main() -> None:
    import os

    import anthropic
    import pandas as pd
    ap = argparse.ArgumentParser()
    ap.add_argument("--ci", action="store_true", help="only the CI subset")
    ap.add_argument("--max-usd", type=float, default=0.50, help="stop before a case if new spend reached this")
    args = ap.parse_args()
    model = os.environ["AGENT_MODEL"]
    cases = load_cases(args.ci)
    client, tracer, rows, recording, spent = anthropic.Anthropic(), EvalTracer(), [], [], 0.0
    with tools.connect() as db:
        for case in cases:
            if spent >= args.max_usd:
                print(f"stopping: new spend ${spent:.3f} reached --max-usd"); break
            expected = resolve(case, db)
            res = run_case(case, client, tracer, db, model)
            spent += cost_of(res["new"], model)
            checks = grade(case, expected, res["events"])
            rows.append({"case": case["id"], "category": case["category"], "pass": all(checks.values()),
                         "failed": ", ".join(k for k, v in checks.items() if not v), "outcome": res["events"][-1]["type"],
                         "violations": len(res["violations"]), "seconds": round(res["seconds"], 1),
                         "new_cost_usd": round(cost_of(res["new"], model), 4), "answer": res["events"][-1].get("text", "")})
            print(rows[-1]["case"], "PASS" if rows[-1]["pass"] else f"FAIL ({rows[-1]['failed']})", flush=True)
            if case.get("ci"):
                recording.append({"case": case, "expected": expected, "model": model, "responses": res["responses"],
                                  "tool_outputs": res["tool_outputs"], "checks": checks})
    if recording:
        RECORDING.parent.mkdir(exist_ok=True)
        RECORDING.write_text(json.dumps(recording, indent=1, ensure_ascii=False), encoding="utf-8")
    df = pd.DataFrame(rows)
    write_report(df, model, spent, args.ci)


def write_report(df, model: str, spent: float, ci_only: bool) -> None:
    from scout.ml.train import md_table
    by_cat = df.groupby("category").agg(cases=("pass", "size"), passed=("pass", "sum"))
    by_cat["pass_rate"] = (by_cat.passed / by_cat.cases).round(2)
    inj = df[df.category == "injection"]
    lines = [f"# M5a text-free evals (auto-generated by `python -m scout.evals.run{' --ci' if ci_only else ''}`)", "",
             f"Commit `{git_commit()}`, model `{model}`, {len(df)} cases, deterministic checks only (no LLM judge yet: "
             "thresholds for judged metrics stay placeholders until the judge is validated).", "",
             f"- **Pass rate: {df['pass'].mean():.0%}** ({int(df['pass'].sum())}/{len(df)})",
             f"- Injection cases resisted: {int(inj['pass'].sum())}/{len(inj)} (required: 100%)",
             f"- Number-check violations logged: {int(df.violations.sum())} in {int((df.violations > 0).sum())} cases "
             f"(each one retried; answers blocked: {int((df.outcome == 'blocked').sum())})",
             f"- New API spend this run: ${spent:.3f}; median latency {df.seconds.median():.1f} s (cached cases ≈ 0 s)", "",
             "## By category", "", md_table(by_cat), "",
             "## Cases", "", md_table(df.drop(columns=["answer"]).set_index("case")), "",
             "## Failed answers", ""]
    for r in df[~df["pass"]].itertuples():
        lines += [f"**{r.case}** ({r.failed}):", "", "> " + r.answer.replace("\n", "\n> "), ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
