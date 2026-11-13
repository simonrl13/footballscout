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
            "outcome": final["type"], "cites": len(res["cited"]),
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
        "In B no tool returns a contract year, so any year the model writes from memory fails the number check: the "
        "answer is retried, then blocked and counted as declined. **The user-visible contract gap between A and B is "
        "therefore partly structural** (the guardrail, not only missing knowledge). The first drafts, graded before the "
        "check, show what the model would have said.", "", *side, "",
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


# --- Retrieval modes (pre-registered 2026-11-10, docs/RESEARCH_LOG.md): K = keyword vs H = hybrid_rerank, both with
# search_text, agent cache off, pair order per question drawn with MODES_SEED. Cannot change the M8 switching decision.
MODES = ("keyword", "hybrid_rerank")
MODES_SEED, PACE_S = 20261110, 25
MODES_REPORT, MODES_RAW = ROOT / "reports" / "text_exp_modes.md", ROOT / "reports" / "text_exp_modes.json"
MODES_REVIEW = ROOT / "docs" / "evals" / "text_modes_review.md"


def mode_order(case_id: str) -> tuple[str, str]:
    import random
    return MODES if random.Random(f"{MODES_SEED}:{case_id}").random() < 0.5 else MODES[::-1]


def blind_review(rows: list[dict], commit: str) -> tuple[str, dict]:
    """Every wrong or declined answer (released or draft), shuffled and without its mode. Returns the file and the key."""
    import random
    flagged = [r for r in rows if {r["label"], r["draft_label"]} & {"wrong", "declined"}]
    random.Random(MODES_SEED).shuffle(flagged)
    key, out = {}, ["# Text experiment (retrieval modes): answers to review, blind to mode", "",
                    f"Commit `{commit}`. Every answer labelled wrong or declined (released or draft), shuffled, with no mode "
                    "shown; the key is in reports/text_exp_modes.json (`review_key`): don't open it before the review is done. "
                    "Mark each automatic label right or wrong; for wrong transfer claims, also whether a cited passage supports "
                    "the club named.", ""]
    for n, r in enumerate(flagged, 1):
        rid = f"R{n:02d}"
        key[rid] = {"id": r["id"], "mode": r["mode"]}
        out += [f"## {rid}: {r['label']}" + (f", draft {r['draft_label']}" if r["draft_label"] != r["label"] else ""), "",
                f"**Q:** {r['question']}  ", f"**Truth:** {r['truth']}  ", "**Review:** [ ] label right  [ ] label wrong", "",
                "> " + (r["answer"] or "(no answer)").replace("\n", "\n> "), ""]
        if r["draft"] and r["draft"] != r["answer"]:
            out += ["First draft (rejected by the checks):", "", "> " + r["draft"].replace("\n", "\n> "), ""]
    return "\n".join(out) + "\n", key


def modes_report(rows: list[dict], commit: str, model: str, voyage: dict, stopped: str | None) -> str:
    import statistics

    from scout.evals.retrieval_eval import p95
    df = pd.DataFrame(rows).assign(condition=lambda d: d["mode"])
    k, h = (df[df["mode"] == m].set_index("id") for m in MODES)
    both = k.index.intersection(h.index)

    def pairs(col, lab):  # (only keyword has the label, only hybrid_rerank has it), on paired questions
        a, b = k.loc[both, col] == lab, h.loc[both, col] == lab
        return int((a & ~b).sum()), int((b & ~a).sum())
    (ck, ch), (wk, wh) = pairs("label", "correct"), pairs("label", "wrong")
    lines = ["# Agent answers by retrieval mode: keyword vs hybrid_rerank (36 questions)", "",
             "Pre-registered 2026-11-10 (docs/RESEARCH_LOG.md); **it cannot change the M8 switching decision.** Same questions, "
             "labels and graders as the 2026-10-15 experiment (#41); both arms with search_text, agent cache off, one run per "
             f"arm. Commit `{commit}`, model `{model}`, {time.strftime('%Y-%m-%d')}, local Postgres. Generated by "
             "`python -m scout.evals.text_exp --modes`. Labels are automatic until the owner's blind review "
             "(docs/evals/text_modes_review.md). 95% Wilson intervals.", ""]
    if stopped:
        lines += [f"**Stopped early: {stopped}.**", ""]
    p = mcnemar_p(ck, ch)
    lines += ["## Released answers (primary)", "", *summary(df, "label"), "",
              f"**Correct answers, paired (n = {len(both)}):** only keyword correct {ck}, only hybrid_rerank correct {ch}, exact "
              f"two-sided McNemar p = {p:.3f}" + ("" if p < 0.05 else ": no difference detectable at this size (not \"equal\")") + ".  ",
              f"Wrong answers: only keyword wrong {wk}, only hybrid_rerank wrong {wh}, p = {mcnemar_p(wk, wh):.3f}.", "",
              "Power, stated in advance: 6 wins and 0 losses is the smallest split with p < 0.05; about 8 net wins are needed "
              "for 80% power.", "",
              "## First drafts (before the number/citation check)", "", *summary(df, "draft_label"), "",
              "## Claims supported by a cited source", "",
              "| Mode | Claims (correct + wrong) | Supported by a cited passage | Owner to judge |", "|---|---|---|---|"]
    claims = df[df.label != "declined"]
    lines += [f"| {m} | {len(g)} | {int(g.supported.eq(True).sum())} | {int(g.supported.isna().sum())} |" for m, g in claims.groupby("mode")]
    lines += ["", "## Latency and cost", "", "| Mode | Median / p95 s (excluding Voyage waits) | Median / p95 s, unadjusted | Anthropic US$ |",
              "|---|---|---|---|"]
    for m in MODES:
        g = df[df["mode"] == m]
        lines.append(f"| {m} | {statistics.median(g.secs_net):.1f} / {p95(list(g.secs_net)):.1f} | "
                     f"{statistics.median(g.seconds):.1f} / {p95(list(g.seconds)):.1f} | {g.cost_usd.sum():.4f} |")
    lines += ["", f"Voyage (hybrid_rerank): {voyage['calls']} calls, {voyage['embed_tokens']:,} embedding + "
              f"{voyage['rerank_tokens']:,} rerank tokens, US${voyage['cost_usd']:.4f} at list price. Latency is the in-process "
              "agent turn on a local machine against local Postgres, not the deployed demo's; free-tier Voyage limits.", "",
              "## Context, not tested", "",
              f"The 2026-10-15 run (#41, older code and cache): with search_text 24/36 correct, without it 4/36. Keyword here: "
              f"{int((k.label == 'correct').sum())}/{len(k)}.", "",
              "## Per question", "", "| Question | Truth | keyword | hybrid_rerank | keyword draft | hybrid_rerank draft | Technical retries |",
              "|---|---|---|---|---|---|---|"]
    for i in both:
        lines.append(f"| {k.question[i]} | {k.truth[i]} | {k.label[i]} | {h.label[i]} | {k.draft_label[i]} | {h.draft_label[i]} | "
                     f"{int(k.retried[i]) + int(h.retried[i])} |")
    return "\n".join(lines) + "\n"


def run_modes(max_usd: float, voyage_max_usd: float) -> None:
    import os

    import anthropic

    from scout.evals import retrieval_eval as re_
    from scout.text import retrieve
    commit = git_commit()
    if commit.endswith("-dirty"):
        raise SystemExit("commit first: the experiment is tied to a clean commit")
    model = os.environ["AGENT_MODEL"]
    cases = [json.loads(line) for line in SET.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(cases) == 36
    re_.throttle(PACE_S)
    client, tracer, rows, stopped = anthropic.Anthropic(), EvalTracer(), [], None
    start = tracer.spent_today()
    with tools.connect() as db:
        for case in cases:
            for mode in mode_order(case["id"]):
                spent, vspent = tracer.spent_today() - start, re_.usage_cost(retrieve.USAGE)
                if spent >= max_usd or vspent >= voyage_max_usd:
                    stopped = f"cap reached (Anthropic US${spent:.4f}, Voyage US${vspent:.4f})"
                    break
                os.environ["RETRIEVAL_MODE"] = mode
                retried = 0
                while True:
                    waited = re_.WAITED[0]
                    try:
                        res = run_case(case, client, tracer, db, model, use_cache=False)
                        break
                    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:  # technical error: once
                        db.rollback()
                        if retried or (isinstance(e, anthropic.APIStatusError) and e.status_code < 500):
                            raise
                        retried = 1
                db.rollback()  # end the read-only transaction (and hybrid's SET LOCALs)
                cid = res["events"][-1].get("conversation_id")
                cost = tracer.conn.execute("SELECT coalesce(sum(cost_usd), 0) FROM agent_calls WHERE conversation_id = %s",
                                           (cid,)).fetchone()[0] if cid else 0
                rows.append({"id": case["id"], "mode": mode, "type": case["type"], "band": case["band"], "question": case["question"],
                             "truth": case["truth"], **grade(case, res), "seconds": res["seconds"],
                             "secs_net": res["seconds"] - (re_.WAITED[0] - waited), "cost_usd": float(cost), "retried": retried})
                print(case["id"], mode, rows[-1]["label"], f"${tracer.spent_today() - start:.4f}", flush=True)
            if stopped:
                break
    voyage = {"calls": re_.CALLS[0], "embed_tokens": retrieve.USAGE["embed_tokens"], "rerank_tokens": retrieve.USAGE["rerank_tokens"],
              "cost_usd": re_.usage_cost(retrieve.USAGE)}
    review, key = blind_review(rows, commit)
    MODES_RAW.write_text(json.dumps({"commit": commit, "model": model, "voyage": voyage, "stopped": stopped, "review_key": key,
                                     "rows": rows}, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    MODES_REVIEW.write_text(review, encoding="utf-8", newline="\n")
    MODES_REPORT.write_text(modes_report(rows, commit, model, voyage, stopped), encoding="utf-8", newline="\n")
    with re_.USAGE_LOG.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"step": "text_exp_modes", "date": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "commit": commit,
                            "calls": voyage["calls"], "embed_tokens": voyage["embed_tokens"], "rerank_tokens": voyage["rerank_tokens"],
                            "cost_usd_list_price": round(voyage["cost_usd"], 6)}) + "\n")
    import mlflow

    from scout.ml.tracking import start_run
    with start_run("text_exp retrieval modes", tags={"kind": "text_exp_modes", "code_commit": commit,
                                                    "note": "cannot change the M8 switching decision; labels automatic until owner review"}):
        mlflow.log_params({"model": model, "modes": ",".join(MODES), "seed": MODES_SEED, "rrf_k": re_.tuned()[0], "rerank_n": re_.tuned()[1]})
        for m in MODES:
            g = [r for r in rows if r["mode"] == m]
            mlflow.log_metrics({f"{m}_{lab}": sum(r["label"] == lab for r in g) for lab in ("correct", "wrong", "declined")})
        mlflow.log_artifact(str(MODES_REPORT))
        mlflow.log_artifact(str(MODES_RAW))
    print(MODES_REPORT.read_text(encoding="utf-8")[:2500])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", action="store_true", help="compare extracted contract ends with Transfermarkt (no API)")
    ap.add_argument("--modes", action="store_true", help="keyword vs hybrid_rerank (pre-registered 2026-11-10)")
    ap.add_argument("--max-usd", type=float, default=0.20)
    ap.add_argument("--voyage-max-usd", type=float, default=0.01)
    args = ap.parse_args()
    if args.contracts:
        contracts()
    elif args.modes:
        run_modes(args.max_usd, args.voyage_max_usd)
    else:
        run(args.max_usd)


if __name__ == "__main__":
    main()
