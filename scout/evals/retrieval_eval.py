"""Keyword vs vector vs hybrid retrieval on labelled questions (M8; pre-registered 2026-10-29, docs/RESEARCH_LOG.md).

Steps, in the pre-registered order:
  --tune     dev split (retrieval_dev.jsonl, string-match gold): RRF k, then rerank N, by within-player MRR
  --propose  string-match proposals + the pooled top 10 of every mode and scope for the eval questions (the
             original 36 in text.jsonl and the extension in retrieval_extra.jsonl, amendment 2026-10-29):
             a blind review file (docs/evals/retrieval_review.md); the candidates' origins (retrieval_candidates.json)
  --freeze   the owner's marks -> retrieval_gold.jsonl (origin + label per passage) and its SHA-256
  (none)     metrics on the 36 with the frozen gold -> reports/retrieval.md and MLflow

The question text is the query, verbatim, in every mode, with the same depth. Every mode runs in two scopes: within the
question's player (player_id set; primary) and corpus-wide. Voyage calls need VOYAGE_API_KEY.

Usage: uv run --env-file .env python -m scout.evals.retrieval_eval [--tune | --propose | --freeze]
"""
import argparse
import hashlib
import json
import math
import random
import re
import statistics
import time
import urllib.error

from scout.agent import tools
from scout.data.manifest import MANIFEST, ROOT, git_commit
from scout.evals.text_exp import mcnemar_p
from scout.text import retrieve
from scout.text.embed import MANIFEST as EMB_MANIFEST
from scout.text.fold import fold

EVALS = ROOT / "scout" / "evals"
QUESTIONS, EXTRA, DEV = EVALS / "text.jsonl", EVALS / "retrieval_extra.jsonl", EVALS / "retrieval_dev.jsonl"
CANDIDATES, GOLD, TUNED = EVALS / "retrieval_candidates.json", EVALS / "retrieval_gold.jsonl", EVALS / "retrieval_tuned.json"
REVIEW, REPORT = ROOT / "docs" / "evals" / "retrieval_review.md", ROOT / "reports" / "retrieval.md"
DEPTH, KS, SEED = 10, (1, 3, 5, 10), 20261029
K_GRID, N_GRID = (10, 30, 60), (10, 20, 30)
SCOPES = ("player", "corpus")
PRICE = {"embed_tokens": 0.02, "rerank_tokens": 0.02}  # US$ per million tokens (docs.voyageai.com/docs/pricing)
CONTRACT_WORDS = re.compile(r"\b(?:contract|extension|extended|signed|until|deal)\b", re.I)
PROVISIONAL = "**Provisional, pending label review**: the owner has not yet approved the gold labels."


def load(path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def words(q: str) -> list[str]:
    return re.findall(r"[^\W_]+", q)[:20]  # as search_text does


def string_match(case: dict, text: str) -> bool:
    """Pre-registered proposal rule: an accepted club alias (whole words, folded) and the year of the window; for
    contracts, the expiry year in a passage that mentions a contract."""
    t = fold(text)
    if case["type"] == "transfer":
        year = re.search(r"summer (\d{4})", case["question"]).group(1)
        return (re.search(rf"\b{year}\b", t) is not None
                and any(re.search(rf"\b{re.escape(fold(a))}\b", t) for a in case["accept"]))
    return re.search(rf"\b{case['truth']}\b", t) is not None and CONTRACT_WORDS.search(t) is not None


def passages(conn, where: str, params: tuple) -> list[dict]:
    return conn.execute("SELECT doc_id, passage_no, player_id, section, body FROM text_passages WHERE " + where
                        + " ORDER BY doc_id, passage_no", params).fetchall()  # `where` is a constant in this module


WAITED = [0.0]  # seconds the throttle slept; subtracted from latency


def throttle(pace: float = 21, cache_queries: bool = False) -> None:
    """Wraps retrieve.voyage for eval runs under Voyage's no-payment-method limits (3 requests, 10K tokens per
    minute): spaces calls, retries HTTP 429, and optionally reuses a query's embedding within the process (tune and
    propose only: ranks, not latency). The live path is unchanged."""
    real, last, cache = retrieve.voyage, [0.0], {}

    def call(path, payload):
        k = json.dumps(payload, sort_keys=True)
        if cache_queries and path == "embeddings" and k in cache:
            return {**cache[k], "usage": {"total_tokens": 0}}
        for attempt in range(10):
            wait = last[0] + pace - time.monotonic()
            if wait > 0:
                time.sleep(wait)
                WAITED[0] += wait
            last[0] = time.monotonic()
            try:
                out = real(path, payload)
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 9:
                    raise
                time.sleep(65)
                WAITED[0] += 65
        if path == "embeddings":
            cache[k] = out
        return out
    retrieve.voyage = call


def run_mode(conn, case: dict, mode: str, scope: str, k: int, n: int) -> tuple[list[tuple], float, dict]:
    """Top DEPTH passage keys, seconds (including Voyage calls, excluding throttle waits), and the Voyage tokens used."""
    before, waited = dict(retrieve.USAGE), WAITED[0]
    t = time.perf_counter()
    rows = retrieve.search(conn, case["question"], words(case["question"]),
                           case["player_id"] if scope == "player" else None, DEPTH, mode, k, n)
    secs = time.perf_counter() - t - (WAITED[0] - waited)
    conn.rollback()  # end the read-only transaction (and its SET LOCALs) after each query
    return [retrieve.key(r) for r in rows], secs, {u: retrieve.USAGE[u] - before[u] for u in before}


def rr(ranked: list[tuple], relevant: set) -> float:
    return next((1 / i for i, x in enumerate(ranked[:DEPTH], 1) if x in relevant), 0.0)


def hits(ranked: list[tuple], relevant: set, k: int) -> bool:
    return any(x in relevant for x in ranked[:k])


def random_baseline(n: int, g: int) -> dict:
    """Expected RR (cut at DEPTH) and hits@k for a random order of n candidates of which g are relevant, exactly."""
    total = math.comb(n, g)
    err = sum(math.comb(n - r, g - 1) / total / r for r in range(1, min(DEPTH, n - g + 1) + 1))
    return {"rr": err, **{f"hits@{k}": 1 - math.comb(n - g, min(k, n)) / math.comb(n, min(k, n)) for k in KS}}


def perm_p(diffs: list[float], draws: int = 100_000) -> float:
    """Paired sign-flip permutation test on the mean difference, two-sided, seeded."""
    rng, obs = random.Random(SEED), abs(sum(diffs))
    extreme = sum(abs(sum(d if rng.random() < 0.5 else -d for d in diffs)) >= obs - 1e-12 for _ in range(draws))
    return (extreme + 1) / (draws + 1)


def mrr_within_player(conn, cases: list[dict], gold: dict, mode: str, k: int, n: int) -> float:
    rrs = [rr(run_mode(conn, c, mode, "player", k, n)[0], gold[c["id"]]) for c in cases if gold[c["id"]]]
    return sum(rrs) / len(rrs)


def tune() -> None:
    """RRF k on hybrid, then rerank N on hybrid_rerank with that k; within-player MRR on the dev split; ties -> smaller."""
    cases = load(DEV)
    with tools.connect() as conn:
        gold = {c["id"]: {(p["doc_id"], p["passage_no"]) for p in passages(conn, "player_id = %s", (c["player_id"],))
                          if string_match(c, retrieve.chunk_text(p["section"], p["body"]))} for c in cases}
        scored = sum(bool(g) for g in gold.values())
        by_k = {k: mrr_within_player(conn, cases, gold, "hybrid", k, 0) for k in K_GRID}
        best_k = max(K_GRID, key=lambda k: (round(by_k[k], 9), -k))
        by_n = {n: mrr_within_player(conn, cases, gold, "hybrid_rerank", best_k, n) for n in N_GRID}
        best_n = max(N_GRID, key=lambda n: (round(by_n[n], 9), -n))
    out = {"dev_questions": len(cases), "with_gold": scored, "mrr_by_k": by_k, "rrf_k": best_k,
           "mrr_by_n": by_n, "rerank_n": best_n, "commit": git_commit(), "dev_sha256": sha256(DEV),
           "voyage_tokens": dict(retrieve.USAGE)}
    TUNED.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=1))


def tuned() -> tuple[int, int]:
    t = json.loads(TUNED.read_text(encoding="utf-8"))
    return t["rrf_k"], t["rerank_n"]


def surname(name: str) -> str:
    return fold(name).split()[-1]


def propose() -> None:
    """Union of string-match proposals and the pooled top DEPTH of every mode and scope, per question; the review file
    shows them shuffled (seeded) with no mode or method."""
    k, n = tuned()
    cases, out, review = eval_cases(), {}, []
    with tools.connect() as conn:
        for c in cases:
            own = passages(conn, "player_id = %s", (c["player_id"],))
            byk = {(p["doc_id"], p["passage_no"]): p for p in own}
            origin = {key: {"string_match"} for key, p in byk.items()
                      if string_match(c, retrieve.chunk_text(p["section"], p["body"]))}
            name = conn.execute("SELECT name FROM demo_players WHERE player_id = %s", (c["player_id"],)).fetchone()["name"]
            for mode in retrieve.MODES:
                for scope in SCOPES:
                    for key in run_mode(conn, c, mode, scope, k, n)[0]:
                        if key not in byk:  # another player's page: pooled only if it names this player
                            [p] = passages(conn, "doc_id = %s AND passage_no = %s", key)
                            if surname(name) not in fold(p["body"]):
                                continue
                            byk[key] = p
                        origin.setdefault(key, set()).add(f"pool:{mode}:{scope}")
            keys = sorted(origin)
            random.Random(f"{SEED}:{c['id']}").shuffle(keys)
            out[c["id"]] = [{"cand": f"{c['id']}#{i + 1}", "doc_id": d, "passage_no": no, "player_id": byk[(d, no)]["player_id"],
                             "origin": sorted(origin[(d, no)])} for i, (d, no) in enumerate(keys)]
            truth = c["truth"] if c["type"] == "contract" else " / ".join(c["accept"])
            review += [f"## {c['id']}", "", f"**Q:** {c['question']}  ", f"**Truth (Transfermarkt):** {truth}", ""]
            for i, key in enumerate(keys):
                p = byk[key]
                other = "" if p["player_id"] == c["player_id"] else " (another player's page)"
                text = retrieve.chunk_text(p["section"], p["body"]).replace("\n", " | ")
                review.append(f"- [ ] **{c['id']}#{i + 1}**{other}: {text}")
            review.append("")
    CANDIDATES.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    head = ["# Retrieval gold: candidates to review (blind)", "",
            "Mark `[x]` on every passage that states the answer for this player: the club joined in that summer window, or "
            "the contract's expiry year. Leave the rest `[ ]`. The candidates are shuffled; which mode or rule proposed "
            "each one is not shown (it is in `scout/evals/retrieval_candidates.json`; please don't open it before marking).",
            f"Candidates: {sum(len(v) for v in out.values())} for {len(cases)} questions.", ""]
    REVIEW.write_text("\n".join(head + review) + "\n", encoding="utf-8", newline="\n")
    print(f"{sum(len(v) for v in out.values())} candidates for {len(cases)} questions -> {REVIEW}")


MARK = re.compile(r"^- \[([ xX])\] \*\*([^*]+)\*\*", re.M)


def freeze() -> None:
    """The owner's [x] marks -> one gold row per candidate, with its origin; prints the file's SHA-256."""
    marks = {cand: m for m, cand in MARK.findall(REVIEW.read_text(encoding="utf-8"))}
    cands = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    rows = [{"question": qid, "doc_id": c["doc_id"], "passage_no": c["passage_no"], "player_id": c["player_id"],
             "origin": c["origin"], "relevant": marks[c["cand"]] in "xX"} for qid, cs in cands.items() for c in cs]
    GOLD.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")
    print(f"{len(rows)} labels, {sum(r['relevant'] for r in rows)} relevant; sha256 {sha256(GOLD)}")


def gold_sets(cases: list[dict]) -> dict:
    """Relevant passage keys per question and scope: within the player = on the question's player's page."""
    g = {c["id"]: {"player": set(), "corpus": set()} for c in cases}
    pid = {c["id"]: c["player_id"] for c in cases}
    for x in load(GOLD):
        if x["relevant"]:
            g[x["question"]]["corpus"].add((x["doc_id"], x["passage_no"]))
            if x["player_id"] == pid[x["question"]]:
                g[x["question"]]["player"].add((x["doc_id"], x["passage_no"]))
    return g


def p95(xs: list[float]) -> float:
    return statistics.quantiles(xs, n=20, method="inclusive")[18]


def summarize(rows: list[dict], gold: dict, sizes: dict) -> dict:
    """Metrics per (mode, scope) over questions with a relevant passage in that scope; latency over all queries."""
    out = {}
    for mode, scope in {(r["mode"], r["scope"]) for r in rows}:
        rs = [r for r in rows if (r["mode"], r["scope"]) == (mode, scope)]
        scored = [r for r in rs if gold[r["id"]][scope]]
        cost = sum(sum(r["usage"][u] * PRICE[u] for u in PRICE) for r in rs) / 1e6 / len(rs)
        out[mode, scope] = {"n": len(scored), "mrr": sum(r["rr"] for r in scored) / len(scored),
                            **{f"hits@{k}": sum(r[f"hits@{k}"] for r in scored) / len(scored) for k in KS},
                            "median_ms": statistics.median(r["secs"] for r in rs) * 1000,
                            "p95_ms": p95([r["secs"] for r in rs]) * 1000, "cost_usd": cost}
    for scope in SCOPES:
        base = [random_baseline(sizes[c][scope], len(gold[c][scope])) for c in gold if gold[c][scope]]
        out["random", scope] = {"n": len(base), "mrr": sum(b["rr"] for b in base) / len(base),
                                **{f"hits@{k}": sum(b[f"hits@{k}"] for b in base) / len(base) for k in KS}}
    return out


def paired(rows: list[dict], gold: dict, mode: str, scope: str) -> dict:
    """mode vs keyword on the same questions: hits@1 wins/losses (exact McNemar) and the MRR difference (sign-flip
    permutation test)."""
    by = {(r["mode"], r["id"]): r for r in rows if r["scope"] == scope}
    ids = [i for i in gold if gold[i][scope]]
    wins = sum(by[mode, i]["hits@1"] and not by["keyword", i]["hits@1"] for i in ids)
    losses = sum(by["keyword", i]["hits@1"] and not by[mode, i]["hits@1"] for i in ids)
    diffs = [by[mode, i]["rr"] - by["keyword", i]["rr"] for i in ids]
    return {"wins": wins, "losses": losses, "mcnemar_p": mcnemar_p(wins, losses),
            "mrr_diff": sum(diffs) / len(diffs), "perm_p": perm_p(diffs)}


def eval_cases() -> list[dict]:
    """The original 36 and the extension (amendment 2026-10-29), in that order."""
    return load(QUESTIONS) + [{**c, "extension": True} for c in load(EXTRA)]


SETS = {"extended": lambda c: True, "original": lambda c: not c.get("extension")}  # the rule applies to "extended"


def evaluate(labels_approved: bool) -> None:
    k, n = tuned()
    cases = eval_cases()
    gold, rows = gold_sets(cases), []
    with tools.connect() as conn:
        corpus = conn.execute("SELECT count(*) AS n FROM text_passages").fetchone()["n"]
        per_player = [r["n"] for r in conn.execute("SELECT count(*) AS n FROM text_passages GROUP BY player_id")]
        sizes = {c["id"]: {"player": len(passages(conn, "player_id = %s", (c["player_id"],))), "corpus": corpus}
                 for c in cases}
        conn.rollback()
        for mode in retrieve.MODES:
            for scope in SCOPES:
                for c in cases:
                    ranked, secs, usage = run_mode(conn, c, mode, scope, k, n)
                    rel = gold[c["id"]][scope]
                    rows.append({"id": c["id"], "mode": mode, "scope": scope, "secs": secs, "usage": usage,
                                 "rank": next((i for i, x in enumerate(ranked, 1) if x in rel), None),
                                 "rr": rr(ranked, rel), **{f"hits@{q}": hits(ranked, rel, q) for q in KS}})
                print(mode, scope, "done", flush=True)
    results = {}
    for name, keep in SETS.items():
        ids = {c["id"] for c in cases if keep(c)}
        sub, g = [r for r in rows if r["id"] in ids], {i: gold[i] for i in ids}
        results[name] = (summarize(sub, g, sizes), {(m, s): paired(sub, g, m, s) for m in retrieve.MODES[1:] for s in SCOPES})
    write_report(cases, rows, gold, sizes, per_player, results, k, n, labels_approved)
    log_mlflow(results, k, n, labels_approved)


def decision(summary: dict, tests: dict, mode: str) -> list[str]:
    """The pre-registered switching rule, parts (1)-(3); part (4) needs the agent eval."""
    t, s, kw = tests[mode, "player"], summary[mode, "player"], summary["keyword", "player"]
    return [f"(1) hits@1 within the player: {t['wins']} wins, {t['losses']} losses, McNemar p = {t['mcnemar_p']:.3f}: "
            + ("met" if t["wins"] > t["losses"] and t["mcnemar_p"] < 0.05 else "not met"),
            f"(2) MRR within the player {s['mrr']:.3f} vs keyword {kw['mrr']:.3f}: " + ("met" if s["mrr"] > kw["mrr"] else "not met"),
            f"(3) p95 latency {s['p95_ms']:.0f} ms vs keyword {kw['p95_ms']:.0f} ms (limit +500): "
            + ("met" if s["p95_ms"] <= kw["p95_ms"] + 500 else "not met")]


def tables(summary: dict, tests: dict, scope: str) -> list[str]:
    lines = ["| Mode | n | MRR | hits@1 | hits@3 | hits@5 | hits@10 | median ms | p95 ms | US$ per query |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for mode in (*retrieve.MODES, "random"):
        m = summary[mode, scope]
        lat = "– | – | –" if mode == "random" else f"{m['median_ms']:.0f} | {m['p95_ms']:.0f} | {m['cost_usd']:.6f}"
        lines.append(f"| {mode} | {m['n']} | {m['mrr']:.3f} | " + " | ".join(f"{m[f'hits@{x}']:.2f}" for x in KS)
                     + f" | {lat} |")
    lines += ["", "| vs keyword | hits@1 wins | losses | McNemar p | MRR difference | permutation p |",
              "|---|---|---|---|---|---|"]
    for mode in retrieve.MODES[1:]:
        t = tests[mode, scope]
        lines.append(f"| {mode} | {t['wins']} | {t['losses']} | {t['mcnemar_p']:.3f} | {t['mrr_diff']:+.3f} | "
                     f"{t['perm_p']:.3f} |")
    return lines + [""]


def write_report(cases, rows, gold, sizes, per_player, results, k, n, labels_approved) -> None:
    q = statistics.quantiles(per_player, n=10, method="inclusive")
    mine = sorted(sizes[c["id"]]["player"] for c in cases)
    n_ext = sum(bool(c.get("extension")) for c in cases)
    lines = ["# Retrieval: keyword vs vector vs hybrid", ""]
    if not labels_approved:
        lines += [PROVISIONAL, ""]
    lines += [f"Commit `{git_commit()}`, {time.strftime('%Y-%m-%d')}. Pre-registration: docs/RESEARCH_LOG.md (2026-10-29, "
              f"and its amendment). Questions: the original 36 (`scout/evals/text.jsonl`) and the extended set (+{n_ext} "
              f"transfer questions, `scout/evals/retrieval_extra.jsonl`; {len(cases)} in all). Query = the question "
              f"verbatim; top {DEPTH}. Gold: `scout/evals/retrieval_gold.jsonl` (sha256 `{sha256(GOLD)[:12]}`). "
              f"RRF k = {k}, rerank N = {n} (chosen on the dev split: `scout/evals/retrieval_tuned.json`). Embeddings "
              "voyage-4-lite (1024 dimensions), rerank rerank-2.5-lite. Latency: wall clock against local Postgres, "
              "Voyage calls included. Generated by `python -m scout.evals.retrieval_eval`.", "",
              f"Passages per player (all {len(per_player):,} players): p10 {q[0]:.0f}, median "
              f"{statistics.median(per_player):.0f}, p90 {q[8]:.0f}, max {max(per_player)}. The questions' players: median "
              f"{statistics.median(mine):.0f}, min {mine[0]}, max {mine[-1]}. Random = the exact expectation of a random "
              "order of each question's candidates. n = questions with a relevant passage in that scope.", ""]
    for name, title in [("extended", f"Extended set ({len(cases)} questions; the switching rule applies here)"),
                        ("original", "Original 36")]:
        summary, tests = results[name]
        lines += [f"## {title}", ""]
        for scope, sub in [("player", "Within the question's player (primary)"), ("corpus", "Corpus-wide")]:
            lines += [f"### {sub}", "", *tables(summary, tests, scope)]
    summary, tests = results["extended"]
    lines += ["## Switching rule (pre-registered, extended set), parts 1–3", ""]
    lines += [f"- **{mode}:** " + "; ".join(decision(summary, tests, mode)) for mode in retrieve.MODES[1:]]
    contracts = [c for c in cases if c["type"] == "contract"]
    missing = [c["id"] for c in contracts if not gold[c["id"]]["player"]]
    other = [c["id"] for c in cases if c["type"] != "contract" and not gold[c["id"]]["player"]]
    lines += ["", "## Coverage finding (not retrieval misses)", "",
              f"Contract questions whose answer (the June 2026 expiry year) no passage on the player's page states: "
              f"**{len(missing)} of {len(contracts)}** ({', '.join(missing) or 'none'}). They are left out of hits@k and MRR. "
              f"Transfer questions with no relevant passage on the page: {len(other)} ({', '.join(other) or 'none'}).", "",
              "## Per question: rank of the first relevant passage in the top 10 (– none)", "",
              "| Question | Set | Page passages | Relevant (page / corpus) | "
              + " | ".join(f"{m} ({s})" for s in SCOPES for m in retrieve.MODES) + " |",
              "|---|---|---|---|" + "---|" * (len(SCOPES) * len(retrieve.MODES))]
    by = {(r["id"], r["mode"], r["scope"]): r for r in rows}
    for c in cases:
        g = gold[c["id"]]
        cells = [str(by[c["id"], m, s]["rank"] or "–") for s in SCOPES for m in retrieve.MODES]
        lines.append(f"| {c['id']} | {'extension' if c.get('extension') else 'original'} | {sizes[c['id']]['player']} | "
                     f"{len(g['player'])} / {len(g['corpus'])} | " + " | ".join(cells) + " |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[:60]))


def log_mlflow(results, k, n, labels_approved) -> None:
    import mlflow

    from scout.ml.tracking import start_run
    tags = {"kind": "retrieval_eval", "data_manifest_sha256": sha256(MANIFEST),
            "embeddings_manifest_sha256": sha256(EMB_MANIFEST), "gold_sha256": sha256(GOLD),
            "labels": "approved" if labels_approved else "provisional, pending label review"}
    with start_run("retrieval eval (M8)", tags=tags):
        mlflow.log_params({"rrf_k": k, "rerank_n": n, "depth": DEPTH, "embed_model": retrieve.EMBED_MODEL,
                           "rerank_model": retrieve.RERANK_MODEL,
                           "questions": "scout/evals/text.jsonl + scout/evals/retrieval_extra.jsonl"})
        for name, (summary, tests) in results.items():
            for (mode, scope), m in summary.items():
                mlflow.log_metrics({f"{name}_{mode}_{scope}_{x.replace('@', '_at_')}": v for x, v in m.items() if x != "n"})
            for (mode, scope), t in tests.items():
                mlflow.log_metrics({f"{name}_{mode}_{scope}_mcnemar_p": t["mcnemar_p"],
                                    f"{name}_{mode}_{scope}_perm_p": t["perm_p"]})
        mlflow.log_artifact(str(REPORT))


def main() -> None:
    ap = argparse.ArgumentParser()
    step = ap.add_mutually_exclusive_group()
    step.add_argument("--tune", action="store_true")
    step.add_argument("--propose", action="store_true")
    step.add_argument("--freeze", action="store_true")
    ap.add_argument("--labels-approved", action="store_true", help="only once the owner has approved the gold labels")
    ap.add_argument("--pace", type=float, default=21, help="seconds between Voyage calls (0 with standard limits)")
    a = ap.parse_args()
    if not a.freeze:
        throttle(a.pace, cache_queries=a.tune or a.propose)
    tune() if a.tune else propose() if a.propose else freeze() if a.freeze else evaluate(a.labels_approved)


if __name__ == "__main__":
    main()
