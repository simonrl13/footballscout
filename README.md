# Scout — football player value forecasting + scouting agent

Forecasts how a player's Transfermarkt market value will change over the next 12 months, with SHAP explanations. A Claude tool-calling agent answers questions over the model's output (M4a); retrieval over Wikipedia revisions comes later.

> Values are Transfermarkt crowd-sourced estimates, **not transfer fees**.

- Problem definition: [docs/SPEC.md](docs/SPEC.md) · Plan and status: [docs/PLAN.md](docs/PLAN.md) · Security: [SECURITY.md](SECURITY.md)

## Status
- [x] **M1** — data pipeline rebuilt to the SPEC, point-in-time features with leakage tests, baselines, test-set gate, reproducibility, DB roles, security gates
- [x] **M2** — MLflow tracking, validation-only tuning pass, 80% prediction intervals (split-conformal), excluded-share report (a Guardian client was built in M2 and removed in M3; nothing was ever fetched)
- [ ] **M3 (in progress)** — *Stats feature pass (pre-registered): negative, B0 stays the baseline ([reports/m3_stats_pass.md](reports/m3_stats_pass.md)). Wikipedia revision fetch running; `extract-v2` pilot done ($0.11, [reports/m3a_pilot.md](reports/m3a_pilot.md)); full extraction waits for budget.* Public-text features. The Guardian was dropped (its terms prohibit AI use; nothing was stored). Sources evaluated read-only: Wikipedia revision history + Wikidata (LLM track) and GDELT (attention track); see [reports/m3_sources.md](reports/m3_sources.md). Source-agnostic linker, extraction with verbatim-quote checks, and point-in-time features are built and tested offline.
- [x] **M4a** — tools API + Claude agent (no text yet): 4 read-only tools, number check with retry/block, US$2/day spend cap, per-call traces. See [Agent (M4a)](#agent-m4a).
- [ ] M5a — MCP server + text-free evals · Wikipedia retrieval and citations · M4b/M5b — text in the agent · M6 — ops · M7 — AWS deploy

## Problem (from the SPEC)
- **Unit:** one player on **1 September** each year, 2013–2024.
- **Population:**
  - The player's club on 1 Sep plays in the Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie or Liga Portugal.
  - The player had at least 450 league minutes in those leagues the previous season.
- **Target:** `log(value as of next 1 Sep / value as of 1 Sep)`, each the latest valuation on or before that date. Kept only if the player was revalued in between, so a zero means "revalued, unchanged".
- **Split:** train 2013–2021 · validation 2022 · test 2023–2024. Never random.

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
- `scout_reader` can only read them, and is the only role the API, agent (and later the MCP server) get for data.
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

## Agent (M4a)
A Claude tool-calling agent over four read-only tools, also exposed as REST endpoints (all need `Authorization: Bearer $SCOUT_API_TOKEN`):

| Tool | Endpoint | Returns |
|---|---|---|
| `search_players` | `GET /players/search` | players by name (accents optional) and filters: league, position, age, value; sorted by forecast or value; ≤ 20 |
| `get_player` | `GET /players/{id}` | club, league, position, age, Transfermarkt value and its date |
| `predict_value_change` | `GET /players/{id}/forecast` | 12-month forecast (%), 80% interval, implied values, top 5 SHAP factors |
| `compare_players` | `POST /players/compare` | 2–5 players side by side |
| (agent) | `POST /ask` | server-sent events: tool calls, then one checked answer |

- **Data:** the demo snapshot is **12 June 2026**, the last valuation date in the data, built with the same point-in-time code as training (`build_snapshots(..., at=...)`) and precomputed into `demo_players`. The model was trained on 1-September snapshots, so June forecasts are a demo, and every tool result says so.
- **Number check:** every number in an answer must appear in this turn's tool results, the question or the fixed facts in the system prompt (data date, horizon, interval level, league names). On a violation the agent gets one retry with feedback; if it fails again, the answer is blocked. Both cases are logged in `agent_violations`. The answer is therefore released only after the check: `/ask` streams progress events, not raw tokens.
- **Guardrails:** Pydantic models with limits (unknown fields rejected) for every tool and endpoint; parameterized SQL with `psycopg.sql` identifiers; read-only role and read-only transactions; max 6 model calls and 1,024 output tokens per call; **US$2/day spend cap** across all agent calls, checked before each call.
- **Observability:** one `agent_calls` row per model call (tokens, cost, latency, requested tools, cache hit). `AGENT_CACHE=true` serves identical requests from `agent_cache` (development and evals).
- **Model:** `AGENT_MODEL` from `.env` (development: `claude-haiku-4-5`). Development spend so far: about US$0.05.
- **Not yet:** Wikipedia text and citations (after M5a), rate limits (M6), MCP (M5a).

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

## Results (M2, current)
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
