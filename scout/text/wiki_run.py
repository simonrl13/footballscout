"""Run extract-v2 over Wikipedia player-years: pilot (a random sample) or, once approved, the full set.

For each labelled snapshot (player, year) with a fetched revision at t: the document is the text new in the year
(revision at the previous 1 Sep -> revision at t), stored as a derived document linked to the exact Wikipedia diff.
One Message Batch, quotes and dates verified, results cached by (doc_id, prompt_version).

Usage:
  TEXT_LLM_ENABLED=true TEXT_LLM_MODEL=claude-haiku-4-5 uv run --env-file .env python -m scout.text.wiki_run --pilot 100
  ... --all --confirm-cost USD      (refuses unless the estimate is <= USD)
"""
import argparse
import os
import re
import time

import pandas as pd
from psycopg.types.json import Jsonb

from scout.data.manifest import ROOT, git_commit
from scout.text import extract, extract_wiki as xw, store

REPORT = ROOT / "reports" / "m3a_pilot.md"


def player_years(conn) -> pd.DataFrame:
    """Snapshot player-years with the revision at t fetched; previous-year revision if any."""
    rows = conn.execute("""
        SELECT t.player_id, t.as_of AS t, t.doc_id AS doc_t, p.doc_id AS doc_prev, w.enwiki_title
        FROM wiki_snapshot_revisions t
        JOIN wikidata_players w USING (player_id)
        LEFT JOIN wiki_snapshot_revisions p ON p.player_id = t.player_id AND p.as_of = (t.as_of - interval '1 year')::date
        WHERE t.doc_id IS NOT NULL AND extract(month FROM t.as_of) = 9 AND extract(day FROM t.as_of) = 1""").fetchall()
    df = pd.DataFrame(rows, columns=["player_id", "t", "doc_t", "doc_prev", "title"])
    df["t"] = pd.to_datetime(df.t)
    return df


def derived_docs(conn, py: pd.DataFrame) -> list[dict]:
    """Build (and store) the new-in-year document for each player-year."""
    ids = list(set(py.doc_t) | set(py.doc_prev.dropna()))
    bodies = dict(conn.execute("SELECT doc_id, body FROM text_documents WHERE doc_id = ANY(%s)", (ids,)).fetchall())
    meta = {r[0]: r[1] for r in conn.execute("SELECT doc_id, available_at FROM text_documents WHERE doc_id = ANY(%s)", (ids,)).fetchall()}
    out = []
    for r in py.itertuples():
        text = xw.new_text(bodies[r.doc_t] or "", bodies.get(r.doc_prev) if isinstance(r.doc_prev, str) else None)
        rev_t = r.doc_t.rsplit(":", 1)[1]
        rev_p = r.doc_prev.rsplit(":", 1)[1] if isinstance(r.doc_prev, str) else None
        doc_id = f"wikipedia:enwiki:diff:{rev_p or 'none'}:{rev_t}"
        url = (f"https://en.wikipedia.org/w/index.php?diff={rev_t}&oldid={rev_p}" if rev_p
               else f"https://en.wikipedia.org/w/index.php?oldid={rev_t}")
        conn.execute("INSERT INTO text_documents (doc_id, source, url, available_at, meta, body) VALUES (%s, 'wikipedia', %s, %s, %s, %s) "
                     "ON CONFLICT (doc_id) DO NOTHING",
                     (doc_id, url, meta[r.doc_t], Jsonb({"title": r.title, "player_id": int(r.player_id), "snapshot": str(r.t.date()),
                                                         "derived": "new-in-year", "license": "CC BY-SA 4.0"}), text))
        out.append({"doc_id": doc_id, "url": url, "text": text, "player_id": int(r.player_id), "title": r.title, "doc_t": r.doc_t,
                    "window": (r.t - pd.DateOffset(years=1), r.t)})
    conn.commit()
    return out


def run_batch(conn, client, docs: list[dict], model: str, sleep=time.sleep) -> dict:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    done = {r[0] for r in conn.execute("SELECT doc_id FROM text_extractions WHERE prompt_version = %s", (xw.PROMPT_VERSION,)).fetchall()}
    docs = [d for d in docs if d["doc_id"] not in done and d["text"].strip()]
    stats = {"submitted": len(docs), "succeeded": 0, "input_tokens": 0, "output_tokens": 0, "raw_events": 0, "kept": 0,
             "dropped": {}, "kept_by_type": {}}
    if not docs:
        return stats
    reqs = {xw.build_request(d["doc_id"], d["text"], d["title"], model)["custom_id"]: d for d in docs}
    batch = client.messages.batches.create(requests=[
        Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**xw.build_request(d["doc_id"], d["text"], d["title"], model)["params"]))
        for cid, d in reqs.items()])
    while client.messages.batches.retrieve(batch.id).processing_status != "ended":
        sleep(30)
    for res in client.messages.batches.results(batch.id):
        d = reqs[res.custom_id]
        status, usage, kept, out = res.result.type, None, [], None
        if status == "succeeded":
            msg = res.result.message
            usage = msg.usage
            out = xw.parse_output(next((b.text for b in msg.content if b.type == "text"), '{"events": []}'))
            kept, dropped = xw.verify_events(d["text"], out, *d["window"])
            stats["succeeded"] += 1
            stats["raw_events"] += len(out.get("events", []))
            for k, v in dropped.items():
                stats["dropped"][k] = stats["dropped"].get(k, 0) + v
            stats["input_tokens"] += usage.input_tokens
            stats["output_tokens"] += usage.output_tokens
        conn.execute("INSERT INTO text_extractions (doc_id, prompt_version, model, status, input_tokens, output_tokens, batch_id, output) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (d["doc_id"], xw.PROMPT_VERSION, model, status, getattr(usage, "input_tokens", None),
                      getattr(usage, "output_tokens", None), batch.id, Jsonb(out) if out is not None else None))
        for k in kept:
            conn.execute("INSERT INTO text_signals (doc_id, prompt_version, player_id, signal_type, detail, evidence_start, evidence_end, "
                         "event_date, date_precision, attributes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                         (d["doc_id"], xw.PROMPT_VERSION, d["player_id"], k["signal_type"], k["signal_type"], k["evidence_start"],
                          k["evidence_end"], k["event_date"], k["precision"],
                          Jsonb({"injury_type": k["injury_type"], "duration_days": k["duration_days"]})))
            stats["kept_by_type"][k["signal_type"]] = stats["kept_by_type"].get(k["signal_type"], 0) + 1
        stats["kept"] += len(kept)
    conn.commit()
    stats["batch_id"] = batch.id
    return stats


def main() -> None:
    import anthropic
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", type=int)
    g.add_argument("--all", action="store_true")
    ap.add_argument("--confirm-cost", type=float, default=None, help="max USD for --all (from the pilot estimate)")
    args = ap.parse_args()
    if not extract.enabled():
        raise SystemExit("TEXT_LLM_ENABLED is not true")
    model = extract.model_name()
    with store.connect() as conn:
        store.ensure_schema(conn)
        labelled = labelled_player_years()
        py = player_years(conn).merge(labelled, on=["player_id", "t"])  # previous-year revisions are context, not documents
        if args.pilot:
            py = py.sample(min(args.pilot * 2, len(py)), random_state=20261001)  # oversample: empty diffs are skipped
        built = derived_docs(conn, py)
        docs = [d for d in built if d["text"].strip()]
        n_full = None
        if args.pilot:
            mapped = {r[0] for r in conn.execute("SELECT player_id FROM wikidata_players WHERE enwiki_title IS NOT NULL")}
            n_full = round(labelled.player_id.isin(mapped).sum() * len(docs) / len(built))  # all labelled player-years × non-empty share
            docs = docs[:args.pilot]
        else:
            est = estimate_full(conn, len(docs), model)
            if args.confirm_cost is None or est > args.confirm_cost:
                raise SystemExit(f"full run estimate ${est:.2f} for {len(docs):,} docs; pass --confirm-cost >= estimate after approval")
        stats = run_batch(conn, anthropic.Anthropic(), docs, model)
        write_report(conn, stats, docs, model, n_full, pilot=bool(args.pilot))
        print({k: v for k, v in stats.items() if k != "dropped"}, stats.get("dropped"))


def labelled_player_years() -> pd.DataFrame:
    """(player_id, t) for every labelled snapshot (the model's population with a target)."""
    from scout.data.raw import read_raw
    from scout.data.snapshots import YEARS, build_snapshots
    s = build_snapshots(read_raw(), years=YEARS)
    return s.loc[s.target.notna(), ["player_id", "date"]].rename(columns={"date": "t"})


def estimate_full(conn, n_docs: int, model: str) -> float:
    r = conn.execute("SELECT avg(input_tokens), avg(output_tokens) FROM text_extractions WHERE prompt_version = %s AND status = 'succeeded'",
                     (xw.PROMPT_VERSION,)).fetchone()
    if r[0] is None:
        raise SystemExit("no pilot measurements yet; run --pilot first")
    return xw.estimate_cost(int(r[0] * n_docs), int(r[1] * n_docs), model)


def write_report(conn, stats, docs, model, n_player_years, pilot: bool) -> None:
    from scout.ml.train import md_table
    by_id = {d["doc_id"]: d for d in docs}
    rows = conn.execute("SELECT doc_id, signal_type, event_date, date_precision, attributes, evidence_start, evidence_end FROM text_signals "
                        "WHERE prompt_version = %s AND doc_id = ANY(%s) ORDER BY doc_id", (xw.PROMPT_VERSION, list(by_id))).fetchall()
    cost = xw.estimate_cost(stats["input_tokens"], stats["output_tokens"], model)
    n = max(1, stats["succeeded"])
    lines = [f"# M3a Wikipedia extraction {'pilot' if pilot else 'run'} (auto-generated by `python -m scout.text.wiki_run`)", "",
             f"Commit `{git_commit()}`, model `{model}`, prompt `{xw.PROMPT_VERSION}`, batch `{stats.get('batch_id')}`. "
             "Text from Wikipedia (CC BY-SA 4.0); each example links to the exact diff it came from.", "",
             f"- Documents: {stats['submitted']} submitted, {stats['succeeded']} succeeded",
             f"- Tokens: {stats['input_tokens']:,} in / {stats['output_tokens']:,} out "
             f"(mean {stats['input_tokens'] / n:,.0f} / {stats['output_tokens'] / n:,.0f} per doc); cost **${cost:.2f}** (Batch API)",
             f"- Events returned: {stats['raw_events']}; kept after verification: **{stats['kept']}**",
             f"- Dropped by reason: {stats['dropped']}",
             f"- Kept by type: {stats['kept_by_type']}", ""]
    if pilot and stats["succeeded"]:
        full = xw.estimate_cost(int(stats["input_tokens"] / n * n_player_years), int(stats["output_tokens"] / n * n_player_years), model)
        lines += [f"**Full-run estimate:** ~{n_player_years:,} non-empty documents (all labelled player-years with an English "
                  f"Wikipedia page × the non-empty share in this sample) × measured mean tokens = **${full:.2f}** on the Batch API.", "",
                  "**Sample bias:** the pilot samples only player-years already fetched (the fetcher runs in player-id order, so "
                  "mostly lower ids, i.e. players who joined Transfermarkt earlier and are older on average).", ""]
    ex = []
    for i in pd.Series(range(len(rows))).sample(min(10, len(rows)), random_state=20261001).sort_values():
        doc_id, typ, date, prec, attrs, s, e = rows[i]
        d = by_id[doc_id]
        quote = d["text"][s:e].replace("|", "/")
        ex.append({"player": d["title"], "snapshot": str(d["window"][1].date()), "type": typ, "date": f"{date} ({prec})",
                   "injury/duration": f"{(attrs or {}).get('injury_type') or ''} {(attrs or {}).get('duration_days') or ''}".strip(),
                   "quote (≤300 chars)": quote[:300], "source": f"[diff]({d['url']})"})
    if ex:
        lines += [f"## 10 random kept events (of {len(rows)}) for spot-checking", "", md_table(pd.DataFrame(ex).set_index("player")), ""]
    drops = year_rule_drops(conn, by_id)
    if drops:
        df = pd.DataFrame(drops)
        lines += ["## Events dropped by the same-sentence year rule", "",
                  "Would an alternative rule recover them? `paragraph`: the year appears earlier in the same paragraph of the "
                  "full revision at t. `heading`: the nearest preceding section heading names the year (a season heading "
                  "`2016–17` counts for 2016 and 2017). For review only: the rule is unchanged.", "",
                  f"- {len(df)} dropped; `paragraph` would recover {int(df.paragraph.sum())}, `heading` {int(df.heading.sum())}, "
                  f"either {int((df.paragraph | df.heading).sum())}", "",
                  md_table(df.set_index("player")), ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT}")


def heading_years(line: str) -> set[str]:
    """Years a heading names; a season '2016–17' names 2016 and 2017."""
    years = set(re.findall(r"\b\d{4}\b", line))
    for y, yy in re.findall(r"\b(\d{4})[–-](\d{2})\b", line):
        years |= {y, str(int(y) + 1)}
    return years


def is_heading(line: str) -> bool:
    """strip_wikitext turns '== Heading ==' into a short one-sentence line ending in '.'."""
    return 0 < len(line) <= 60 and line.endswith(".") and ". " not in line and len(line.split()) <= 8


def year_context(body: str, sentence: str, year: str) -> tuple[bool, bool]:
    """In the full revision text: (year earlier in the sentence's paragraph, year named by the nearest preceding heading)."""
    at = body.find(sentence)
    if at < 0:
        return False, False
    para_start = body.rfind("\n\n", 0, at) + 1
    above = body[:body.rfind("\n", 0, at) + 1].split("\n")  # whole lines above the sentence's own line
    heading = next((ln.strip() for ln in reversed(above) if is_heading(ln.strip())), "")
    return year in body[para_start:at], year in heading_years(heading)


def year_rule_drops(conn, by_id: dict) -> list[dict]:
    """Re-verify the stored raw outputs event by event; describe the events dropped by the same-sentence year rule."""
    outs = conn.execute("SELECT doc_id, output FROM text_extractions WHERE prompt_version = %s AND doc_id = ANY(%s) "
                        "AND output IS NOT NULL", (xw.PROMPT_VERSION, list(by_id))).fetchall()
    bodies = dict(conn.execute("SELECT doc_id, body FROM text_documents WHERE doc_id = ANY(%s)",
                               ([by_id[o[0]]["doc_t"] for o in outs],)).fetchall())
    rows = []
    for doc_id, out in outs:
        d = by_id[doc_id]
        for e in out.get("events", []):
            if not xw.verify_events(d["text"], {"events": [e]}, *d["window"])[1]["date_not_in_text"]:
                continue
            start, end = xw.locate(d["text"], e["evidence"])
            sentence = d["text"][d["text"].rfind("\n", 0, start) + 1:]
            sentence = sentence.split("\n", 1)[0]
            para, head = year_context(bodies.get(d["doc_t"]) or "", sentence, e["date"][:4])
            rows.append({"player": d["title"], "snapshot": str(d["window"][1].date()), "type": e["type"],
                         "claimed date": e["date"], "paragraph": para, "heading": head,
                         "sentence (≤300 chars)": sentence[:300].replace("|", "/"), "source": f"[diff]({d['url']})"})
    return rows


if __name__ == "__main__":
    main()
