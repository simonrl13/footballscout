# Scout — football player value forecasting + scouting agent

Forecasts how a player's Transfermarkt market value will change over the next 12 months, with SHAP explanations. The model will be exposed through a Claude tool-calling agent with retrieval over Guardian football news (later milestones).

> Values are Transfermarkt crowd-sourced estimates, **not transfer fees**.

- Problem definition: [docs/SPEC.md](docs/SPEC.md) · Plan and status: [docs/PLAN.md](docs/PLAN.md) · Security: [SECURITY.md](SECURITY.md)

## Status
- [x] **M1** — data pipeline rebuilt to the SPEC, point-in-time features with leakage tests, baselines, test-set gate, reproducibility, DB roles, security gates
- [ ] M2 — MLflow, 80% prediction intervals, Guardian metadata backfill
- [ ] M3 — LLM-extracted news features · M4 — retrieval + agent · M5 — evals + MCP · M6 — ops · M7 — AWS deploy

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
- `scout_reader` can only read them, and is the only role the API (and later the agent and MCP server) gets.

## Run
```sh
uv run --env-file .env python -m scout.pipeline          # manifest check → Postgres load → data report → features → train → validation
uv run python -m scout.pipeline --no-db                  # same, without the Postgres load
uv run python -m scout.ml.evaluate_test --confirm-test --reason "..."   # the ONLY path to the test set; logged
uv run pytest                                            # unit + leakage tests (DB tests: uv run --env-file .env pytest)
```
Trained models go to `models/<run_id>/`, which is never overwritten; `models/LATEST` names the current run. Reports go to [reports/](reports/).

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

## Results (M1)
Validation, 2022 snapshots (2,406). Full tables in [reports/m1_results.md](reports/m1_results.md):

| Model | MAE (log change) | RMSE | Direction acc. |
|---|---|---|---|
| No change | 0.424 | 0.564 | n/a |
| Age-only | 0.375 | 0.498 | 69.5% |
| Linear (ridge) | 0.369 | 0.488 | 70.9% |
| **LightGBM** | **0.364** | **0.482** | **71.3%** |

LightGBM minus linear, MAE: −0.0049 (bootstrap 95% CI −0.0087 to −0.0008). The gain over the linear baseline is small but real; the gain over "no change" is large (−0.060).

In the expanding-window backtest (2016–2022), LightGBM has the lowest MAE in 5 of 7 years. 2018 is a near-tie with linear (0.376 vs 0.375), and it is **worse than age-only and linear for 2019**, the snapshots whose target lands in the COVID markdown. **Test set, 2023–2024 snapshots (4,294)**: the single M1 run, logged in [docs/TEST_LOG.md](docs/TEST_LOG.md), with details in [reports/test_results.md](reports/test_results.md):

| Model | MAE | RMSE | Direction acc. |
|---|---|---|---|
| No change | 0.410 | 0.551 | n/a |
| Age-only | 0.367 | 0.496 | 69.3% |
| Linear (ridge) | 0.359 | 0.483 | 70.1% |
| LightGBM | 0.359 | 0.482 | 70.4% |

- LightGBM **beats no-change** (MAE −0.052, CI −0.058 to −0.045).
- It **does not beat the linear baseline**: −0.0002, CI −0.0032 to +0.0030. Linear is better in 2023 and LightGBM in 2024.
- So the SPEC's success criterion is met for "no change" but **not yet for linear**. With these baseline features the relationships are close to linear in log space (age, value level, momentum, squad value). The planned news features (M3) are the test of whether non-linear signal exists.
- Nothing will be tuned against these test numbers.

## Test-set discipline
The test set is evaluated at most once per milestone, only by `scout/ml/evaluate_test.py`, and every run is logged with date, commit and reason. **Disclosure:** in the earlier v0 design (Phase 2), the v0 test metrics were printed on every training run and viewed 4 times. No feature, hyperparameter or model decision was based on them; the only change made after viewing was switching the age-only baseline from median to mean, because of a metric artifact visible in validation too. v0 was then replaced by the SPEC design, with new splits.

## What changed from v0
v0 (commit `aa607c0`, reports in [reports/v0/](reports/v0/)) used every valuation date as a snapshot, a 335–425-day target window, 14 leagues and a purged date split. It reached test MAE 0.394 vs 0.469 for no-change. The SPEC redesign moved to annual 1-September snapshots of established players, with club membership rebuilt point-in-time and no current-state columns. The numbers aren't directly comparable (a different population and target).

## Data caveats
- Transfermarkt values are crowd estimates, and collection stopped in July 2026 (valuations end 2026-06-12).
- `position` is each player's current position, applied to all years.
- Club reconstruction is 83–98% accurate by year (see above); 2013, 2014 and 2020 are the weakest.
- Survivorship: a target requires a revaluation within the year, so players who drop out of coverage are underrepresented.
