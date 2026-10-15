"""Does search_text (Wikipedia retrieval) improve the agent's answers? Pre-registered in docs/RESEARCH_LOG.md
(2026-10-15) before any run.

Every question in text.jsonl (built by scout/evals/text_set.py) runs in two conditions with the same model, prompt and
settings: A, the agent as deployed; B, the same agent with search_text withheld (it may answer from its own knowledge
or decline). Labels, automatic (the owner reviews every wrong and declined label, see docs/evals/text_review.md):
- correct: the answer names the truth (a club alias as whole words / the contract's expiry year)
- declined: no answer was released (refused, blocked), or the truth is missing and the answer says it can't tell
- wrong (hallucinated): the truth is missing and the answer does not decline
Graded twice: the released answer (primary) and the first draft, i.e. the answer before the number/citation check
rejected it (secondary: what the model knows, which the guardrail may hide).
Supported: a claim (correct or wrong) is supported when the answer cites a passage containing the truth (correct) or
the year it states (contract); wrong transfer claims are left to the owner's review.

--contracts (no API calls): Transfermarkt's contract expiry (dump of 12 June 2026) against the latest contract end
date extracted from Wikipedia (extract-v3, documents published before 12 June 2026) for the demo players.

Usage: uv run --env-file .env python -m scout.evals.text_exp --max-usd 0.20   (clean tree; responses cached)
       uv run --env-file .env python -m scout.evals.text_exp --contracts
"""
import argparse
import json
import math
import re
import time

import pandas as pd

from scout.agent import tools
from scout.data.manifest import ROOT, git_commit
from scout.evals.run import EvalTracer, cost_of, run_case
from scout.text.eval_events import wilson
from scout.text.linker import fold

SET = ROOT / "scout" / "evals" / "text.jsonl"
REPORT = ROOT / "reports" / "text_retrieval.md"
REVIEW = ROOT / "docs" / "evals" / "text_review.md"
CONTRACTS = ROOT / "reports" / "text_contracts.md"
CONDITIONS = {"A": frozenset(), "B": frozenset({"search_text"})}
AS_OF = pd.Timestamp("2026-06-12")
DECLINE = re.compile(
    r"\b(?:don't|do not|doesn't|does not|can't|cannot|couldn't|could not|unable|not able|no (?:information|data|"
    r"record|records|details|mention)|not (?:available|in (?:the|my) (?:data|tools)|covered|included|listed|"
    r"mentioned|found)|isn't (?:available|in|covered|included|listed)|only (?:have|cover|covers|includes?))\b", re.I)
YEAR = re.compile(r"\b20(?:2[7-9]|3\d)\b")  # contract years after June 2026 (the truth is never 2026)


def body(text: str) -> str:
    """The answer without the sources footer, with typographic apostrophes made plain."""
    return text.split("\n\nSources (Wikipedia")[0].replace("’", "'")


def has_truth(case: dict, text: str) -> bool:
    if case["type"] == "contract":
        return re.search(rf"\b{case['truth']}\b", text) is not None
    return any(re.search(rf"\b{re.escape(fold(a))}\b", fold(text)) for a in case["accept"])


def label(case: dict, text: str | None) -> str:
    if not text:
        return "declined"
    b = body(text)
    if has_truth(case, b):
        return "correct"
    return "declined" if DECLINE.search(b) else "wrong"


def supported(case: dict, text: str, cited: dict) -> bool | None:
    """True/False for a claim checked against the passages the answer cites; None when only the owner can tell."""
    passages = " ".join(p["text"] for p in cited.values())
    if not cited:
        return False
    if has_truth(case, body(text)):
        return has_truth(case, passages)
    if case["type"] == "contract":
        return any(y in passages for y in YEAR.findall(body(text)))
    return None


def mcnemar_p(b: int, c: int) -> float:
    """Exact two-sided McNemar test on the discordant pairs (b: only A right, c: only B right)."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def grade(case: dict, res: dict) -> dict:
    final = res["events"][-1]
    text = final.get("text") if final["type"] == "answer" else None
    draft = res["violations"][0]["answer"] if res["violations"] else text
    lab = label(case, text)
    return {"label": lab, "draft_label": label(case, draft), "answer": text or final.get("text", ""), "draft": draft,
            "outcome": final["type"], "cites": len(res["cited"]), "checked": bool(res["violations"]),
            "supported": supported(case, text, res["cited"]) if lab != "declined" else None,
            "tools": [o["name"] for o in res["tool_outputs"]], "seconds": round(res["seconds"], 1)}


def cell(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({k / n:.0%}, CI {lo:.0%}–{hi:.0%})" if n else "–"


def summary(df: pd.DataFrame, col: str) -> list[str]:
    lines = ["| Condition | Group | n | Correct | Wrong (hallucinated) | Declined |", "|---|---|---|---|---|---|"]
    for cond, g in df.groupby("condition"):
        for name, sub in [("all", g), *[(f"{t} / {b}", s) for (t, b), s in g.groupby(["type", "band"])],
                          *[(b, s) for b, s in g.groupby("band")]]:
            n = len(sub)
            lines.append(f"| {cond} | {name} | {n} | " + " | ".join(cell(int((sub[col] == x).sum()), n)
                                                                    for x in ("correct", "wrong", "declined")) + " |")
    return lines


def write_report(df: pd.DataFrame, model: str, commit: str, spent: float) -> None:
    a, b = (df[df.condition == c].set_index("id") for c in ("A", "B"))

    def pairs(lab):  # (only A has the label, only B has it)
        return int(((a.label == lab) & (b.label != lab)).sum()), int(((b.label == lab) & (a.label != lab)).sum())
    (only_a, only_b), (wrong_a, wrong_b) = pairs("correct"), pairs("wrong")
    claims = df[df.label != "declined"]
    sup = [f"| {c} | {len(g)} | {int(g.supported.eq(True).sum())} | {int(g.supported.isna().sum())} |"
           for c, g in claims.groupby("condition")]
    ct = df[df.type == "contract"]
    side = ["| Condition | Level | Correct | Wrong (hallucinated) | Declined |", "|---|---|---|---|---|"]
    for cond, g in ct.groupby("condition"):
        for level, col in [("released (user-visible)", "label"), ("first draft", "draft_label")]:
            side.append(f"| {cond} | {level} | " + " | ".join(cell(int((g[col] == x).sum()), len(g))
                                                             for x in ("correct", "wrong", "declined")) + " |")
    lines = [
        "# Does Wikipedia retrieval improve the agent's answers?", "",
        f"Commit `{commit}`, model `{model}`, {time.strftime('%Y-%m-%d')}; new API spend ${spent:.3f}. Pre-registration and "
        "decision rule: docs/RESEARCH_LOG.md (2026-10-15). A: the agent with search_text; B: the same agent without it. "
        "Labels are automatic (owner review of wrong/declined labels: docs/evals/text_review.md). 95% Wilson intervals.", "",
        "## Released answers (primary)", "", *summary(df, "label"), "",
        f"Paired comparison of correct answers: only A correct {only_a}, only B correct {only_b}, exact McNemar "
        f"p = {mcnemar_p(only_a, only_b):.3f}. Wrong answers: only A wrong {wrong_a}, only B wrong {wrong_b}, "
        f"p = {mcnemar_p(wrong_a, wrong_b):.3f}.", "",
        "## Contract questions: released answers next to first drafts", "",
        "In B no tool returns a contract year, so a year written from memory would fail the number check (retried, "
        "then blocked and counted as declined), and the system prompt already tells the model to copy every number from "
        "a tool. **The user-visible contract gap between A and B is therefore partly structural.** The first drafts, "
        "graded before the check, show what the model would have said. In this run "
        f"{int((ct.condition.eq('B') & ct.checked).sum())} of {int(ct.condition.eq('B').sum())} B contract answers reached "
        "the number check: the model declined before writing a year, so the structural part comes from the prompt's "
        "tools-only rules rather than the check itself.", "", *side, "",
        "Sensitivity (pre-registered): transfer questions whose destination is not the player's demo club (get_player "
        "shows the current club in both conditions):", "", *summary(df[df.type.eq("transfer") & ~df.club_gives_it], "label"), "",
        "## First drafts (before the number/citation check)", "", *summary(df, "draft_label"), "",
        "## Claims supported by a cited source", "",
        "| Condition | Claims (correct + wrong) | Supported by a cited passage | Owner to judge |", "|---|---|---|---|", *sup, "",
        "B cannot cite (search_text is withheld), so its claims are unsupported by construction.", "",
        "## Limitations", "",
        "- The system prompt is identical in both conditions, so in B it still describes search_text (\"search_text "
        "returns passages from players' Wikipedia pages...\") although the tool is withheld. The model may decline more "
        "readily in B, expecting a tool it doesn't have.",
        "- Transfermarkt is the ground truth and can itself be wrong; the Wikipedia revisions are those in force on 12 June "
        "2026 and may miss a recent move or extension.",
        "- 36 questions (6 per type and band per condition): only large differences are detectable; per-band rows are "
        "descriptive.",
        "- Labels are automatic until the owner's review of every wrong and declined label.", "",
        "## Per question", "", "| Question | Truth | Band | A | B | A draft | B draft |", "|---|---|---|---|---|---|---|"]
    for i, r in a.iterrows():
        lines.append(f"| {r.question} | {r.truth} | {r.band} | {r.label} | {b.label[i]} | {r.draft_label} | {b.draft_label[i]} |")
    REPORT.write_bytes(("\n".join(lines) + "\n").encode())
    review = ["# Text experiment: answers to review", "",
              f"Commit `{commit}`. Every answer labelled wrong or declined (released or draft). Mark each automatic label "
              "right or wrong; for wrong transfer claims, also whether a cited passage supports the club named.", ""]
    flagged = df.label.isin(["wrong", "declined"]) | df.draft_label.isin(["wrong", "declined"])
    for _, r in df[flagged].sort_values(["id", "condition"]).iterrows():
        review += [f"## {r.id} ({r.condition}): {r.label}" + (f", draft {r.draft_label}" if r.draft_label != r.label else ""),
                   "", f"**Q:** {r.question}  ", f"**Truth:** {r.truth}  ", "**Review:** [ ] label right  [ ] label wrong", "",
                   "> " + (r.answer or "(no answer)").replace("\n", "\n> "), ""]
        if r.draft and r.draft != r.answer:
            review += ["First draft (rejected by the checks):", "", "> " + r.draft.replace("\n", "\n> "), ""]
    REVIEW.write_bytes(("\n".join(review) + "\n").encode())


def run(max_usd: float) -> None:
    import os

    import anthropic
    commit = git_commit()
    if commit.endswith("-dirty"):
        raise SystemExit("commit first: the experiment is tied to a clean commit")
    model = os.environ["AGENT_MODEL"]
    cases = [json.loads(line) for line in SET.read_text(encoding="utf-8").splitlines() if line.strip()]
    client, tracer, rows, spent = anthropic.Anthropic(), EvalTracer(), [], 0.0
    with tools.connect() as db:
        for case in cases:
            for cond, off in CONDITIONS.items():
                if spent >= max_usd:
                    raise SystemExit(f"stopping: new spend ${spent:.3f} reached --max-usd (cached reruns are free)")
                res = run_case(case, client, tracer, db, model, tools_off=off)
                spent += cost_of(res["new"], model)
                rows.append({"id": case["id"], "condition": cond, "type": case["type"], "band": case["band"],
                             "question": case["question"], "truth": case["truth"],
                             "club_gives_it": case["type"] == "transfer" and has_truth(case, case["demo_club"]), **grade(case, res)})
                print(case["id"], cond, rows[-1]["label"], f"${spent:.3f}", flush=True)
    write_report(pd.DataFrame(rows), model, commit, spent)


def contracts() -> None:
    from scout.text.wiki_features import end_of, load_signals
    with tools.connect() as db:
        tm = pd.DataFrame(db.execute(
            "SELECT p.player_id, p.contract_expiration_date AS tm, d.value_eur::float AS value_eur FROM players p "
            "JOIN demo_players d USING (player_id)").fetchall())
        sig = load_signals(db)
    sig = sig[(sig.signal_type == "contract_until")
              & (pd.to_datetime(sig.available_at, utc=True).dt.tz_localize(None) < AS_OF)]
    ext = (sig.assign(end=end_of(pd.to_datetime(sig.event_date), sig.date_precision))
           .groupby("player_id").agg(end=("end", "max"), published=("available_at", "max")))
    df = tm.join(ext, on="player_id")
    df["tm"] = pd.to_datetime(df.tm)
    both = df[df.tm.notna() & df.end.notna()]
    agree = both.tm.dt.year == both.end.dt.year
    live = both.end >= AS_OF
    lines = ["# Extracted contract end dates vs Transfermarkt (as of 12 June 2026)", "",
             "Transfermarkt: `players.contract_expiration_date` (Kaggle dump of 12 June 2026). Extracted: the latest "
             "contract end date stated in any Wikipedia document published before 12 June 2026 (extract-v3). The newest "
             f"extracted document is from {pd.to_datetime(sig.available_at).max():%Y-%m-%d}: the June 2026 revisions "
             "were fetched for retrieval but never extracted. No API calls.", "",
             "**Read this as a staleness measure, not an extraction-accuracy measure.** The extracted dates stop at August "
             "2024 while Transfermarkt's are from June 2026, so most disagreements are contracts signed or extended in "
             "between. A fair accuracy check needs the June 2026 demo pages extracted (follow-up, about $0.30; not run).", "",
             "| | Players |", "|---|---|",
             f"| Demo players | {len(df)} |", f"| Transfermarkt expiry known | {int(df.tm.notna().sum())} |",
             f"| Extracted end date known | {int(df.end.notna().sum())} |",
             f"| Both (coverage of Transfermarkt's) | {cell(len(both), int(df.tm.notna().sum()))} |", "",
             "| Extracted end date | n | Same year as Transfermarkt | Within 1 year |", "|---|---|---|---|"]
    for name, m in [("all", pd.Series(True, index=both.index)), ("still in the future on 12 June 2026", live),
                    ("already past on 12 June 2026 (stale)", ~live)]:
        n = int(m.sum())
        near = int(((both.tm.dt.year - both.end.dt.year).abs() <= 1)[m].sum())
        lines.append(f"| {name} | {n} | {cell(int(agree[m].sum()), n)} | {cell(near, n)} |")
    CONTRACTS.write_bytes(("\n".join(lines) + "\n").encode())
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", action="store_true", help="compare extracted contract ends with Transfermarkt (no API)")
    ap.add_argument("--max-usd", type=float, default=0.20)
    args = ap.parse_args()
    contracts() if args.contracts else run(args.max_usd)


if __name__ == "__main__":
    main()
