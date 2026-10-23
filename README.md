# Scout — football player value forecasting + scouting agent

Forecasts how a player's Transfermarkt market value will change over the next 12 months, with SHAP explanations. A Claude tool-calling agent answers questions over the model's output (M4a); retrieval over Wikipedia revisions comes later.

> Values are Transfermarkt crowd-sourced estimates, **not transfer fees**.

- Problem definition: [docs/SPEC.md](docs/SPEC.md) · Plan and status: [docs/PLAN.md](docs/PLAN.md) · Security: [SECURITY.md](SECURITY.md)

## Status
- [x] **M1** — data pipeline rebuilt to the SPEC, point-in-time features with leakage tests, baselines, test-set gate, reproducibility, DB roles, security gates
- [x] **M2** — MLflow tracking, validation-only tuning pass, 80% prediction intervals (split-conformal), excluded-share report (a Guardian client was built in M2 and removed in M3; nothing was ever fetched)
- [ ] **M3 (in progress)** — *Stats feature pass (pre-registered): negative, B0 stays the baseline ([reports/m3_stats_pass.md](reports/m3_stats_pass.md)). Wikipedia revision fetch done (37,665 snapshot pairs, 8,179 players); `extract-v2` pilots: [first](reports/m3a_pilot.md) ($0.11, Haiku 4.5), [second](reports/m3a_pilot2.md) (Haiku 5.5, year rule `context-year`); full extraction done (24,260 documents, $2.77, [reports/m3a_extraction.md](reports/m3a_extraction.md)); pre-registered text-feature pass on validation: **negative, B0 stays** ([reports/m3a_text_pass.md](reports/m3a_text_pass.md)).* Public-text features. The Guardian was dropped (its terms prohibit AI use; nothing was stored). Sources evaluated read-only: Wikipedia revision history + Wikidata (LLM track) and GDELT (attention track); see [reports/m3_sources.md](reports/m3_sources.md). Source-agnostic linker, extraction with verbatim-quote checks, and point-in-time features are built and tested offline.
- [x] **M4a** — tools API + Claude agent (no text yet): 4 read-only tools, number check with retry/block, US$2/day spend cap, per-call traces. See [Agent](#agent-m4a-m4b).
- [x] **M5a** — MCP server (stdio, same 4 read-only tools) + 30-question text-free eval set with deterministic checks; CI replays a 13-case recorded subset without an API key. See [Evals and MCP (M5a)](#evals-and-mcp-m5a).
- [x] **M4b (text, no extraction)** — `search_text` over the demo players' Wikipedia pages (Postgres full-text search), every answer citing the exact revision with the CC BY-SA notice; agent on Claude Haiku 5.5; tracing dashboard and prompt caching (M6 pieces). See [Agent](#agent-m4a-m4b).
- [ ] LLM judge · rate limits (M6) · M7 — AWS deploy

## Problem (from the SPEC)
- **Unit:** one player on **1 September** each year, 2013–2024.
- **Population:**
  - The player's club on 1 Sep plays in the Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie or Liga Portugal.
  - The player had at least 450 league minutes in those leagues the previous season.
- **Target:** `log(value as of next 1 Sep / value as of 1 Sep)`, each the latest valuation on or before that date. Kept only if the player was revalued in between, so a zero means "revalued, unchanged".
- **Split:** train 2013–2021 · validation 2022 · test 2023–2024. Never random.

## Quick demo
One command after cloning (needs Docker and uv): `uv run python -m scout.local_demo`. See [docs/DEMO.md](docs/DEMO.md) for the demo data, what to try, and the walkthrough.

## Setup
Requires [uv](https://docs.astral.sh/uv/) and Docker Desktop. The Kaggle CSVs ([davidcariboo/player-scores](https://www.kaggle.com/datasets/davidcariboo/player-scores), CC0) go in `data/raw/`. They must match [data/manifest.json](data/manifest.json) (SHA-256), which is checked at load time.

```sh
uv sync                       # Python 3.12 + locked dependencies
cp .env.example .env          # then replace every change-me
uv run pre-commit install     # gitleaks secret scan on every commit
docker compose up -d db       # Postgres 16 + pgvector, bound to 127.0.0.1
```
On first start the database creates two roles (see [db/init/02-roles.sh](db/init/02-roles.sh)):
- `scout_loader` creates and loads the tables.
- `scout_reader` can only read them, and is the only role the API, agent and MCP server get for data.
- `scout_tracer` ([db/init/04-tracer.sh](db/init/04-tracer.sh)) can only read and append the agent's trace tables. On an existing volume, create it with `uv run python -m scout.agent.setup` (it also appends a random API token and `AGENT_MODEL` to `.env`, printing no values).

## Run
```sh
uv run --env-file .env python -m scout.pipeline          # manifest check → Postgres load → data report → features → train → validation
uv run python -m scout.pipeline --no-db                  # same, without the Postgres load
uv run --env-file .env python -m scout.ml.tune           # validation-only tuning pass (~8 min) → scout/ml/best_params.json
uv run --env-file .env python -m scout.ml.evaluate_test --confirm-test --reason "..."   # the ONLY path to the test set; logged
uv run --env-file .env python -m scout.ml.tracking       # MLflow UI on http://127.0.0.1:5000
uv run --env-file .env python -m scout.ml.feature_pass  # pre-registered stats feature pass (validation only)
uv run --env-file .env python -m scout.text.wikipedia   # Wikipedia revisions at each snapshot date (resumable, polite)
TEXT_LLM_ENABLED=true TEXT_LLM_MODEL=claude-haiku-4-5 uv run --env-file .env python -m scout.text.wiki_run --pilot 100
uv run --env-file .env python -m scout.text.labeling sample   # 100 links to hand-check → labeling/links_v1.csv
uv run python -m scout.text.labeling score               # precision with 95% CI after labelling
uv run --env-file .env python -m scout.agent.demo       # demo predictions as of 2026-06-12 → demo_players
uv run --env-file .env python -m scout.agent.agent "How will Harry Kane's value change?"   # agent in the terminal
uv run --env-file .env uvicorn scout.api.main:app --host 127.0.0.1   # API (Bearer SCOUT_API_TOKEN)
uv run --env-file .env pytest                            # all tests (DB tests skip without the DB)
```
Trained models go to `models/<run_id>/`, which is never overwritten; `models/LATEST` names the current run. Reports go to [reports/](reports/).

## Agent (M4a, M4b)
A Claude tool-calling agent over five read-only tools, also exposed as REST endpoints (all need `Authorization: Bearer $SCOUT_API_TOKEN`):

| Tool | Endpoint | Returns |
|---|---|---|
| `search_players` | `GET /players/search` | players by name (accents optional) and filters: league, position, age, value; sorted by forecast or value; ≤ 20 |
| `get_player` | `GET /players/{id}` | club, league, position, age, Transfermarkt value and its date |
| `predict_value_change` | `GET /players/{id}/forecast` | 12-month forecast (%), 80% interval, implied values, top 5 SHAP factors |
| `compare_players` | `POST /players/compare` | 2–5 players side by side |
| `search_text` | `GET /text/search` | up to 5 passages from players' English Wikipedia pages as of the demo date, each with its exact revision link, page history and license |
| (agent) | `POST /ask` | server-sent events: tool calls, then one checked answer |

- **Data:** the demo snapshot is **12 June 2026**, the last valuation date in the data, built with the same point-in-time code as training (`build_snapshots(..., as_of=...)`) and precomputed into `demo_players`. The model was trained on 1-September snapshots, so June forecasts are a demo, and every tool result says so.
- **Number check:** every number in an answer must appear in this turn's tool results, the question or the fixed facts in the system prompt (data date, horizon, interval level, league names). On a violation the agent gets one retry with feedback; if it fails again, the answer is blocked. Both cases are logged in `agent_violations`. The answer is therefore released only after the check: `/ask` streams progress events, not raw tokens. Since 2026-10-23 it also checks direction: a percentage stated as a rise when the tool result is a fall (or the reverse) takes the same retry-then-block path. The gap it closes was found by a test on 2026-10-23; a replay of every recorded dev and held-out answer found no released answer that had made the mistake.
- **Wikipedia text and citations:** each demo player's page as it stood on the demo date (2,616 of 2,649 players; revisions up to 11 June 2026) is split into 37,375 passages indexed with Postgres full-text search (free; embeddings only if evals show it isn't enough). Facts from a passage are labelled `[wiki n]`; the code, not the model, appends the sources: exact revision link (`oldid`), page history (authors) and the CC BY-SA 4.0 notice. A citation check retries, then blocks, answers that cite a ref no search returned or quote more than 300 characters. Passages are untrusted data; a planted-injection passage is an eval case.
- **Guardrails:** Pydantic models with limits (unknown fields rejected) for every tool and endpoint; parameterized SQL with `psycopg.sql` identifiers; read-only role and read-only transactions; max 6 model calls and 4,096 output tokens per call (thinking included); **US$0.50/day spend cap** (US$2 before the M7 deploy) across all agent calls, checked before each call.
- **Observability:** one `agent_calls` row per model call (tokens, cost, latency, requested tools, cache hits). `python -m scout.agent.dashboard` shows cost per day and per conversation, prompt-cache hit rate, p50/p95 latency and violations (views in `db/agent.sql`). `AGENT_CACHE=true` serves identical requests from `agent_cache` (development and evals). Production latency is reported cold vs warm ([reports/m7_latency.md](reports/m7_latency.md)): the first request after the demo has been idle takes about 19 s (the container starting; one sample, accepted rather than paying for an always-on instance); warm median 6.6 s (n = 5), model calls about 82% of it.
- **Prompt caching:** automatic caching on every request (tools, system prompt, history). On Haiku 5.5 the dev eval run read 158,833 tokens from the cache against 262 uncached input tokens.
- **Model:** `AGENT_MODEL` / `AGENT_EFFORT` from `.env`: `claude-haiku-5-5` at effort `medium` since 2026-10-12 (about 8x cheaper per question than Haiku 4.5 with the same dev-set result; see the research log).
- **Not yet:** rate limits (M6), an LLM judge, the held-out eval run.

## Evals and MCP (M5a)
- **MCP server** ([scout/mcp_server.py](scout/mcp_server.py)): the same five tools over stdio, annotated read-only, arguments validated against the same Pydantic limits before any query. Try it with `npx @modelcontextprotocol/inspector uv run --env-file .env python -m scout.mcp_server`.
- **Two sets.** Dev ([scout/evals/dev.jsonl](scout/evals/dev.jsonl)): the 30 M5a questions plus 7 Wikipedia questions, development only because their checks were changed after seeing answers (twice; see the research log). Held-out ([scout/evals/heldout.jsonl](scout/evals/heldout.jsonl)): questions written before they are run (10 by Claude, 10 by the owner via [docs/evals/my_questions.md](docs/evals/my_questions.md)); thresholds are set only on it, and each run is gated and logged in [docs/evals/HELDOUT_LOG.md](docs/evals/HELDOUT_LOG.md).
- **Dev set**: 37 questions in seven categories (lookup, forecast, comparison, search, unanswerable, injection, text), including a planted-injection Wikipedia passage and traps such as "Messi" (only Junior Messias is in the data) and a transfer-fee question the tools can't answer.
- **Checks are deterministic** (no LLM judge yet): numbers the answer must quote are read from the tools at eval time; the right player must be named; phrases present or absent; the Transfermarkt caveat and the 80% interval; declines for unanswerables.
- **Results with identical checks:** Haiku 5.5 37/37 ([reports/evals_dev.md](reports/evals_dev.md); live run $0.030, median 4.1 s per question); Haiku 4.5's M5a answers re-graded 30/30 ([reports/evals_dev_haiku45_regrade.md](reports/evals_dev_haiku45_regrade.md); live run $0.195, median 3.0 s). These are dev-set numbers, not threshold evidence.
- **CI:** [tests/test_evals_replay.py](tests/test_evals_replay.py) replays the 13-case CI subset through the real agent loop and graders from a recording, with no API key or database. Responses are keyed by request hash, so any change to the prompt, tool specs or tool outputs fails the replay until it is re-recorded (`python -m scout.evals.run --ci`).

## How the data is built (M1)
**Club on 1 September.** The SPEC's plan was to rebuild club membership from `transfers`. That table turned out to be incomplete before about 2021: in the 2013 check, 77% of players had no transfer row at all. The club is instead the **most recent** of three point-in-time records dated on or before the snapshot: the last league appearance, the last transfer, and the club recorded on the last valuation. Matched against the club each player actually played for in the next 60 days ([reports/m1_data.md](reports/m1_data.md)):

| Method | 2013 | 2016 | 2020 | 2022 | 2024 |
|---|---|---|---|---|---|
| Transfers only | 22% | 42% | 62% | 87% | 94% |
| Last August appearance, then transfers | 80% | 83% | 66% | 94% | 95% |
| **Most recent of appearance / transfer / valuation (used)** | **87%** | **91%** | **83%** | **98%** | **97%** |

The valuation's `current_club_id` is point-in-time, despite its name. It changes across 90% of 73,697 transfers, showing the old club before and the new club after. In 2020 the transfer window stayed open until October, so some "misses" are real moves made after 1 September.

**Why the as-of target, not v0's fixed window.** Revaluations bunch in particular months, so v0's rule ("first valuation 335–425 days later") finds a value for only 7,855 of 28,260 annual snapshots (28%). The SPEC's as-of rule finds 27,330 (96.7%).

**Features** ([scout/ml/features.py](scout/ml/features.py)):
- age, position, league, log value on 1 Sep, value change over the previous 12 months
- previous-season league minutes, appearances, goals + assists per 90, and share of the team's minutes
- squad value on 1 Sep (as-of valuations of players at the club)
- club moves in the last 12 months

**Leakage tests:**
- Synthetic: [tests/test_features.py](tests/test_features.py) adds valuations, transfers, appearances and games dated on or after the snapshot, and the snapshot and every feature must stay identical.
- Real data: [tests/test_leakage_real.py](tests/test_leakage_real.py) rebuilds 2014, 2020 and 2023 with every table truncated at 1 September, and the results must match the full build.

## Results (M2; the model is unchanged since)
**Settings** come from a validation-only tuning pass ([reports/m2_tuning.md](reports/m2_tuning.md)): 54 LightGBM configs and 5 ridge penalties, scored by rolling-origin CV (fit on 2013..y−1, score y, 2016–2021).
- Chosen LightGBM: L1 loss, 7 leaves, 600 trees. Chosen ridge: alpha 100, though the penalty barely matters.
- Tuning changed little: on 2022 both LightGBM versions score MAE 0.364.
- Every run is logged to MLflow with its commit and data manifest.

**Validation (2022)** · [reports/m2_results.md](reports/m2_results.md): LightGBM 0.364 vs linear 0.369 vs no change 0.424 (MAE). LightGBM minus linear: −0.0047, CI −0.0090 to −0.0004.

**Where LightGBM beats linear** (pooled CV folds + 2022): by a small but consistent margin, about −0.005 MAE.
- Every position and every value band.
- 6 of 7 years; 2019, the COVID year, is a tie.
- Clearest for ages 22–24 and 31+; a tie for ages 25–30.

**Test set, 2023–2024 (4,294 snapshots)**: the single M2 run, logged in [docs/TEST_LOG.md](docs/TEST_LOG.md), details in [reports/test_results.md](reports/test_results.md):

| Model | MAE | RMSE | Direction acc. |
|---|---|---|---|
| No change | 0.410 | 0.551 | n/a |
| Age-only | 0.367 | 0.496 | 69.3% |
| Linear (ridge) | 0.359 | 0.483 | 70.2% |
| LightGBM | 0.357 | 0.488 | 70.4% |

- **Beats "no change":** MAE −0.053 (CI −0.059 to −0.047).
- **Does not beat linear:** −0.0012, CI −0.0044 to +0.0020, which includes zero. Linear is marginally better in 2023, LightGBM in 2024.
- **The SPEC goal "beat both baselines" is not met.** It is met for "no change" but not for linear, at M1 or at M2. The validation-period edge (about 0.005) doesn't survive to 2023–24 at a significant level. With these features the signal is close to linear in log space. The M3 news features are the next test of whether non-linear signal exists. Nothing is tuned against these numbers.

**80% prediction intervals** (quantile LightGBM + split-conformal calibration, [scout/ml/intervals.py](scout/ml/intervals.py)):

| | Coverage | Mean width (log) |
|---|---|---|
| Backtest (fit ..y−2, calibrate y−1, score y), 2017–2022 | 67.5%–84.2% by year; 2017 is the only year below 75% | 1.00–1.26 |
| **Test 2023–2024** | **82.2%** (2023: 82.9%, 2024: 81.4%) | 1.17 |

The test coverage is inside the SPEC's 75–85% band. By segment it runs from 78.6% (ages 22–24) to 90.0% (over-31s, who are over-covered). `explain()` returns the interval with each prediction.

**M1 (history).** The untuned M1 model tied linear on test too: 0.3586 vs 0.3588 ([docs/TEST_LOG.md](docs/TEST_LOG.md)). M1 reports: [reports/m1_results.md](reports/m1_results.md), [reports/m1_data.md](reports/m1_data.md).

## Feature experiments after M2 (validation only, pre-registered)
Two pre-registered feature passes, each evaluated on validation only with the same protocol: rolling-origin CV fitting 2013..y−1 and scoring y (2016–2021) plus validation 2022, n = 16,458 pooled snapshots, fixed LightGBM settings, paired-bootstrap 95% CI of MAE(set) − MAE(B0). The test set was not used. **Both are negative: B0 (the 12 M1 features) stays the baseline.**

| Pass | Sets | Best difference vs B0 (95% CI) | Report |
|---|---|---|---|
| Stats (2026-10-01): position percentiles, availability, discipline, in-match injury records | P, A, D, I, ALL | P −0.0002 [−0.0006, +0.0002]; injury records and ALL are significantly worse | [reports/m3_stats_pass.md](reports/m3_stats_pass.md) |
| Wikipedia text (2026-10-12): contract (end date, years left, extensions, expiries) and moves (transfers, loans) extracted by an LLM from point-in-time Wikipedia revisions | B0+C, B0+C+M | B0+C+M −0.0001 [−0.0004, +0.0002]; B0+C −0.0000 [−0.0004, +0.0003] | [reports/m3a_text_pass.md](reports/m3a_text_pass.md) |

An exploratory check, run after the result and not used for any decision: scored only on the 5,081 snapshots where a contract end date is known, contract features change LightGBM's MAE by +0.0006 [−0.0001, +0.0013] ([reports/m3a_text_pass_exploratory.md](reports/m3a_text_pass_exploratory.md)).

**The Wikipedia extraction** ([reports/m3a_extraction.md](reports/m3a_extraction.md)): one document per labelled snapshot player-year (the text added to the player's page during the year before the snapshot), 24,260 documents, `claude-haiku-5-5` on the Batch API, **US$2.77**. Every event needs a verbatim quote and a day- or month-precise date inside the 12-month window, with its year written near the quote; contract end dates need their year in the quote itself.
- **Quality, against Transfermarkt's transfer table** (second pilot): extracted transfers/loans matched a recorded move within 31 days in **19 of 19** cases (95% CI 83–100%); **21 of 32 (66%)** recorded senior moves were extracted (recall is bounded by design).
- **Injuries are sparse:** 0.02–0.06 verified injuries per player-year in the pilots, 3–4% of snapshots in the full run, so they were reported but never used as a feature.
- **Contract end date known** (share of labelled snapshots):

  | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 |
  |---|---|---|---|---|---|---|---|---|---|
  | 13.7% | 18.6% | 22.6% | 25.3% | 28.4% | 30.4% | 31.2% | 31.7% | 33.5% | 35.3% |

## Test-set discipline
The test set is evaluated at most once per milestone, only by `scout/ml/evaluate_test.py`, and every run is logged with date, commit and reason. **Disclosure:** in the earlier v0 design (Phase 2), the v0 test metrics were printed on every training run and viewed 4 times. No feature, hyperparameter or model decision was based on them; the only change made after viewing was switching the age-only baseline from median to mean, because of a metric artifact visible in validation too. v0 was then replaced by the SPEC design, with new splits.

## What changed from v0
v0 (commit `aa607c0`, reports in [reports/v0/](reports/v0/)) used every valuation date as a snapshot, a 335–425-day target window, 14 leagues and a purged date split. It reached test MAE 0.394 vs 0.469 for no-change. The SPEC redesign moved to annual 1-September snapshots of established players, with club membership rebuilt point-in-time and no current-state columns. The numbers aren't directly comparable (a different population and target).

## Data caveats
- Transfermarkt values are crowd estimates, and collection stopped in July 2026 (valuations end 2026-06-12).
- `position` is each player's current position, applied to all years.
- Club reconstruction is 83–98% accurate by year (see above); 2013, 2014 and 2020 are the weakest.
- Survivorship: a target requires a revaluation within the year. Only 0.5–7.4% of candidates drop out for that reason, mostly in 2023–24 and among over-31s ([reports/m2_excluded.md](reports/m2_excluded.md)).
- **The population misses breakout prospects.** The ≥ 450-minute rule excludes 60% of under-22 candidates, and those who were revalued rose +0.54 in log value on average (vs +0.32 for the under-22s kept). The model says nothing about fringe youngsters, the players a scout often cares about most.
