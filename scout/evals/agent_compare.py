"""Exploratory agent eval, keyword vs hybrid_rerank, on local servers (M8; pre-registered 2026-11-07, docs/RESEARCH_LOG.md).

It cannot change the switching decision. Dev (37) and smoke (5) sets with the existing graders, one run per mode, the two
modes alternating question by question. Never touches the held-out set. Voyage calls are paced for the free-tier limits, and
time lost to that is excluded from the primary latency.

Usage: uv run --env-file .env python -m scout.evals.agent_compare --preflight   (servers only, no model or Voyage call)
       uv run --env-file .env python -m scout.evals.agent_compare               (the run; refuses a dirty tree)
"""
import argparse
import http.client
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from scout.agent import tools
from scout.data.manifest import MANIFEST, ROOT, git_commit
from scout.evals import retrieval_eval as re_
from scout.evals import run as dev_run
from scout.evals import smoke
from scout.text import retrieve

MODES = ("keyword", "hybrid_rerank")
PORTS = {"keyword": 8771, "hybrid_rerank": 8772}
SEED, PACE_S, MAX_USD = 20261107, 25, 0.45
TERMINAL = {"answer", "refused", "blocked"}
REPORT, RAW = ROOT / "reports" / "agent_eval_m8.md", ROOT / "reports" / "agent_eval_m8.json"


def stats_path(mode: str) -> Path:
    return Path(tempfile.gettempdir()) / f"scout_agent_compare_{mode}.json"


def serve(mode: str) -> None:
    """One server process: the normal app, private mode, no response cache; Voyage calls paced and counted."""
    import uvicorn
    os.environ.update(RETRIEVAL_MODE=mode, AGENT_CACHE="false", PUBLIC_DEMO="false")
    tokens = {"embeddings": 0, "rerank": 0}
    if mode != "keyword":
        re_.throttle(PACE_S)
        paced = retrieve.voyage

        def counted(path, payload):
            try:
                out = paced(path, payload)
                tokens[path] += out["usage"]["total_tokens"]
                return out
            finally:
                stats_path(mode).write_text(json.dumps({"waited": re_.WAITED[0], "calls": re_.CALLS[0], "tokens": tokens}))
        retrieve.voyage = counted
    uvicorn.run("scout.api.main:app", host="127.0.0.1", port=PORTS[mode], log_level="warning")


def server_stats(mode: str) -> dict:
    try:
        return json.loads(stats_path(mode).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"waited": 0.0, "calls": 0, "tokens": {"embeddings": 0, "rerank": 0}}


def start_servers() -> list[subprocess.Popen]:
    procs = []
    for mode in MODES:
        stats_path(mode).unlink(missing_ok=True)
        procs.append(subprocess.Popen([sys.executable, "-m", "scout.evals.agent_compare", "--serve", mode], cwd=ROOT))
    for mode in MODES:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORTS[mode]}/health", timeout=2).close()
                break
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        else:
            raise SystemExit(f"{mode} server did not start")
    return procs


def get_meta(mode: str) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{PORTS[mode]}/meta",
                                 headers={"Authorization": f"Bearer {os.environ['SCOUT_API_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def ask(mode: str, question: str) -> tuple[list[dict], float, float]:
    """POST /ask until the stream ends: events, seconds, and seconds of that lost to Voyage waits and retries. A stream
    with no terminal event ends with an `error` event, which every grader fails."""
    req = urllib.request.Request(f"http://127.0.0.1:{PORTS[mode]}/ask", data=json.dumps({"question": question}).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {os.environ['SCOUT_API_TOKEN']}"}, method="POST")
    waited, t0, events = server_stats(mode)["waited"], time.perf_counter(), []
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            events = [json.loads(line[6:]) for line in r if line.startswith(b"data: ")]
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
        events.append({"type": "error", "text": "", "detail": type(e).__name__})
    secs = time.perf_counter() - t0
    if not events or events[-1]["type"] not in TERMINAL | {"error"}:
        events.append({"type": "error", "text": "", "detail": "stream ended without a terminal event"})
    return events, secs, server_stats(mode)["waited"] - waited


def order(case_id: str) -> tuple[str, str]:
    return MODES if random.Random(f"{SEED}:{case_id}").random() < 0.5 else MODES[::-1]


def grade_row(case: dict, set_name: str, mode: str, events: list[dict], secs, waited, db, data_date: str, tracer) -> dict:
    checks = (smoke.grade_case(case, events, db, data_date, data_date) if set_name == "smoke"
              else dev_run.grade(case, dev_run.resolve(case, db), events))
    db.rollback()  # end the read-only transaction (and its SET LOCALs)
    cid, final = events[-1].get("conversation_id"), events[-1]
    found = tracer.conn.execute("SELECT kind, action FROM agent_violations WHERE conversation_id = %s", (cid,)).fetchall() if cid else []
    cost = tracer.conn.execute("SELECT coalesce(sum(cost_usd), 0) FROM agent_calls WHERE conversation_id = %s", (cid,)).fetchone()[0] if cid else 0
    return {"case": case["id"], "set": set_name, "category": case["category"], "mode": mode, "verdict": smoke.verdict(checks),
            "failed": [k for k, v in checks.items() if v is False], "outcome": final["type"], "detail": final.get("detail"),
            "secs_raw": secs, "secs_net": None if secs is None else secs - waited, "cost_usd": float(cost),
            "violations": [{"kind": k, "action": a} for k, a in found],
            "tools": [e["name"] for e in events if e["type"] == "tool_call"], "answer": final.get("text", "")}


def summarize(rows: list[dict]) -> dict:
    """Per mode: pass counts by set and category, injection results, violations, outcomes, latency over /ask cases, cost."""
    out = {}
    for mode in MODES:
        rs = [r for r in rows if r["mode"] == mode]
        timed = [r for r in rs if r["secs_raw"] is not None]
        inj = [r for r in rs if r["category"] == "injection"]
        passed = lambda xs: sum(x["verdict"] == "PASS" for x in xs)  # noqa: E731
        out[mode] = {
            "dev": (passed([r for r in rs if r["set"] == "dev"]), sum(r["set"] == "dev" for r in rs)),
            "smoke": (passed([r for r in rs if r["set"] == "smoke"]), sum(r["set"] == "smoke" for r in rs)),
            "injection": (passed(inj), len(inj)),
            "by_category": {c: (passed([r for r in rs if r["category"] == c]), sum(r["category"] == c for r in rs))
                            for c in sorted({r["category"] for r in rs})},
            "violations": Counter((v["kind"], v["action"]) for r in rs for v in r["violations"]),
            "outcomes": Counter(r["outcome"] for r in rs),
            "latency_n": len(timed),
            "median_s": statistics.median(r["secs_net"] for r in timed) if timed else None,
            "p95_s": re_.p95([r["secs_net"] for r in timed]) if timed else None,
            "median_raw_s": statistics.median(r["secs_raw"] for r in timed) if timed else None,
            "p95_raw_s": re_.p95([r["secs_raw"] for r in timed]) if timed else None,
            "cost_usd": sum(r["cost_usd"] for r in rs), "not_graded": sum(r["verdict"] == "NOT GRADED" for r in rs),
        }
    return out


def changes(rows: list[dict]) -> tuple[list[str], list[str]]:
    """Cases that passed with keyword and not hybrid_rerank (drops), and the reverse (gains)."""
    v = {(r["case"], r["mode"]): r["verdict"] for r in rows}
    ids = list(dict.fromkeys(r["case"] for r in rows))
    both = [i for i in ids if (i, "keyword") in v and (i, "hybrid_rerank") in v]
    return ([i for i in both if v[i, "keyword"] == "PASS" and v[i, "hybrid_rerank"] != "PASS"],
            [i for i in both if v[i, "hybrid_rerank"] == "PASS" and v[i, "keyword"] != "PASS"])


def write_report(rows: list[dict], commit: str, model: str, voyage: dict, stopped: str | None) -> None:
    s, (drops, gains) = summarize(rows), changes(rows)
    a, b = s["keyword"], s["hybrid_rerank"]
    frac = lambda x: f"{x[0]}/{x[1]}"  # noqa: E731
    kinds = sorted(set(a["violations"]) | set(b["violations"]))
    lines = ["# Exploratory agent eval: keyword vs hybrid_rerank", "",
             "**Exploratory: it cannot change the switching decision.** Pre-registered 2026-11-07 (docs/RESEARCH_LOG.md). "
             "No held-out run. One run per mode, so differences of a case or two can be model variation.", "",
             f"Commit `{commit}`, model `{model}`, {time.strftime('%Y-%m-%d')}. Local servers against local Postgres, "
             "agent cache off, modes alternating per question. Generated by `python -m scout.evals.agent_compare`.", ""]
    if stopped:
        lines += [f"**Stopped early: {stopped}.**", ""]
    lines += ["| | keyword | hybrid_rerank |", "|---|---|---|",
              f"| Dev set passed | {frac(a['dev'])} | {frac(b['dev'])} |",
              f"| Smoke set passed | {frac(a['smoke'])} | {frac(b['smoke'])} |",
              f"| Injection cases resisted | {frac(a['injection'])} | {frac(b['injection'])} |"]
    lines += [f"| {kind} violations, {action} | {a['violations'][kind, action]} | {b['violations'][kind, action]} |" for kind, action in kinds]
    if not kinds:
        lines.append("| Number, direction and citation check violations | 0 | 0 |")
    lines += [f"| Outcome: {o} | {a['outcomes'][o]} | {b['outcomes'][o]} |" for o in sorted(set(a["outcomes"]) | set(b["outcomes"]))]
    lines += [f"| `/ask` median / p95, seconds (excluding Voyage waits and retries; n = {a['latency_n']}) | "
              f"{a['median_s']:.1f} / {a['p95_s']:.1f} | {b['median_s']:.1f} / {b['p95_s']:.1f} |",
              f"| `/ask` median / p95, seconds, unadjusted | {a['median_raw_s']:.1f} / {a['p95_raw_s']:.1f} | "
              f"{b['median_raw_s']:.1f} / {b['p95_raw_s']:.1f} |",
              f"| Anthropic cost, US$ | {a['cost_usd']:.4f} | {b['cost_usd']:.4f} |", "",
              "Latency is wall clock of `POST /ask` until the stream ends, measured locally: not the deployed demo's latency. "
              "`tx-planted-injection` ran in-process (planting patches the tool), so it counts for passes, not latency. The run "
              "used Voyage's free-tier limits.", "",
              f"Voyage, hybrid_rerank (server and grader): {voyage['calls']} calls, {voyage['embed_tokens']:,} embedding + "
              f"{voyage['rerank_tokens']:,} rerank tokens, US${voyage['cost_usd']:.4f} at list price.", "",
              f"**Passed with keyword, not with hybrid_rerank (drops):** {', '.join(drops) or 'none'}.  ",
              f"**Passed with hybrid_rerank, not with keyword (gains):** {', '.join(gains) or 'none'}.", "",
              "## By category", "", "| Category | keyword | hybrid_rerank |", "|---|---|---|"]
    lines += [f"| {c} | {frac(a['by_category'][c])} | {frac(b['by_category'].get(c, (0, 0)))} |" for c in a["by_category"]]
    lines += ["", "## Per case", "", "| Case | Set | Category | keyword | hybrid_rerank | keyword s | hybrid_rerank s (excl. waits) | Failed checks |",
              "|---|---|---|---|---|---|---|---|"]
    by = {(r["case"], r["mode"]): r for r in rows}
    fmt = lambda x: "–" if x is None else f"{x:.1f}"  # noqa: E731
    for case in dict.fromkeys(r["case"] for r in rows):
        k, h = by.get((case, "keyword")), by.get((case, "hybrid_rerank"))
        one = k or h
        failed = "; ".join(f"{r['mode']}: {', '.join(r['failed']) or r['outcome']}" for r in (k, h) if r and r["verdict"] == "FAIL")
        lines.append(f"| {case} | {one['set']} | {one['category']} | {k['verdict'] if k else '–'} | {h['verdict'] if h else '–'} | "
                     f"{fmt(k['secs_net']) if k else '–'} | {fmt(h['secs_net']) if h else '–'} | {failed or '–'} |")
    lines += ["", "## Failed answers", ""]
    for r in rows:
        if r["verdict"] == "FAIL":
            lines += [f"**{r['case']}, {r['mode']}** ({', '.join(r['failed']) or r['outcome']}):", "",
                      "> " + (r["answer"] or f"(no answer: {r['outcome']} {r['detail'] or ''})").replace("\n", "\n> "), ""]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[:40]), flush=True)


def log_mlflow(rows: list[dict], commit: str, model: str) -> None:
    import mlflow

    from scout.ml.tracking import start_run
    s = summarize(rows)
    tags = {"kind": "agent_eval_exploratory", "code_commit": commit, "data_manifest_sha256": re_.sha256(MANIFEST),
            "embeddings_manifest_sha256": re_.sha256(re_.EMB_MANIFEST), "note": "exploratory: cannot change the switching decision"}
    with start_run("agent eval (M8, exploratory)", tags=tags):
        mlflow.log_params({"model": model, "modes": ",".join(MODES), "seed": SEED, "rrf_k": re_.tuned()[0], "rerank_n": re_.tuned()[1]})
        for mode, m in s.items():
            mlflow.log_metrics({f"{mode}_dev_passed": m["dev"][0], f"{mode}_smoke_passed": m["smoke"][0],
                                f"{mode}_injection_passed": m["injection"][0], f"{mode}_median_s": m["median_s"],
                                f"{mode}_p95_s": m["p95_s"], f"{mode}_cost_usd": m["cost_usd"],
                                f"{mode}_violations": sum(m["violations"].values())})
        mlflow.log_artifact(str(REPORT))
        mlflow.log_artifact(str(RAW))


def main() -> None:
    import anthropic
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", choices=MODES)
    ap.add_argument("--preflight", action="store_true")
    a = ap.parse_args()
    if a.serve:
        return serve(a.serve)
    commit = git_commit()
    if not a.preflight and commit.endswith("-dirty"):
        raise SystemExit("commit first: the run must start from a clean tree")
    cases = [("dev", c) for c in dev_run.load_cases("dev")] + [("smoke", json.loads(x)) for x in smoke.CASES.read_text(encoding="utf-8").splitlines() if x]
    assert len(cases) == 42 and all(s != "heldout" for s, _ in cases)
    procs = start_servers()
    try:
        meta = {m: get_meta(m)["data_as_of"] for m in MODES}
        print("servers up; data date:", meta, "cases:", len(cases), "planted:", [c["id"] for _, c in cases if c.get("plant")], flush=True)
        if a.preflight:
            return
        re_.throttle(PACE_S)  # the grader's own search_text calls in hybrid_rerank mode
        model, client, tracer, rows, stopped = os.environ["AGENT_MODEL"], anthropic.Anthropic(), dev_run.EvalTracer(), [], None
        start = tracer.spent_today()
        with tools.connect() as db:
            date = tools.data_as_of(db)
            db.rollback()
            for set_name, case in cases:
                for mode in order(case["id"]):
                    if tracer.spent_today() - start >= MAX_USD:
                        stopped = f"new Anthropic spend reached US${MAX_USD}"
                        break
                    os.environ["RETRIEVAL_MODE"] = mode
                    if case.get("plant"):
                        events, secs, waited = dev_run.run_case(case, client, tracer, db, model, use_cache=False)["events"], None, 0.0
                        db.rollback()
                    else:
                        events, secs, waited = ask(mode, case["question"])
                    rows.append(grade_row(case, set_name, mode, events, secs, waited, db, date, tracer))
                    print(case["id"], mode, rows[-1]["verdict"], rows[-1]["outcome"], flush=True)
                if stopped:
                    break
        stats = server_stats("hybrid_rerank")
        voyage = {"calls": stats["calls"] + re_.CALLS[0], "embed_tokens": stats["tokens"]["embeddings"] + retrieve.USAGE["embed_tokens"],
                  "rerank_tokens": stats["tokens"]["rerank"] + retrieve.USAGE["rerank_tokens"]}
        voyage["cost_usd"] = re_.usage_cost({"embed_tokens": voyage["embed_tokens"], "rerank_tokens": voyage["rerank_tokens"]})
        RAW.write_text(json.dumps({"commit": commit, "model": model, "voyage": voyage, "stopped": stopped, "rows": rows}, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8", newline="\n")
        with re_.USAGE_LOG.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"step": "agent_eval", "date": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "commit": commit,
                                "calls": voyage["calls"], "embed_tokens": voyage["embed_tokens"], "rerank_tokens": voyage["rerank_tokens"],
                                "cost_usd_list_price": round(voyage["cost_usd"], 6)}) + "\n")
        write_report(rows, commit, model, voyage, stopped)
        log_mlflow(rows, commit, model)
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
