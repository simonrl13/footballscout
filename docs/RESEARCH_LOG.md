# Research log

A running record of decisions, experiments and results, kept so the project can later be written up as a paper. Entries are appended, newest last. Numbers are copied from the reports and logs cited in each entry, never recomputed, and every number is labelled **train**, **validation**, **test**, or **descriptive** (all years, no model fitted). "Not recorded" means the number was never documented.

## Research question

Do LLM-extracted news signals (injury, transfer rumour, contract situation, manager change) add information beyond a strong structured baseline when forecasting 12-month changes in football players' Transfermarkt market values? And how do you build such features without look-ahead bias, both from the data (edited articles, current-state columns) and from the extracting model's own knowledge of how careers turned out?

Setting: annual 1-September snapshots, 2013–2024, of established players in seven European leagues (docs/SPEC.md). Baselines are "no change", age-only and ridge regression; the main model is LightGBM with SHAP explanations and split-conformal 80% intervals.

---

### 2026-09-29 — Replacing the v0 design with the SPEC design (Milestone M1)
- **Question:** Was the first design (v0) a sound basis for the study, or should the prediction problem be redefined before adding news features?
- **What we tried:** v0 used every valuation date as a snapshot, a target of the first valuation 335–425 days later, 14 leagues, all players, and a date split with purged training labels. It was audited against the new SPEC, which uses annual 1-September snapshots, an as-of target, 7 leagues, a ≥ 450 previous-season league minutes population, club membership rebuilt point-in-time, and a 2013–2021 / 2022 / 2023–2024 split.
- **Result:** v0 test (2024-25 season snapshots, 12,393): LightGBM MAE 0.394, direction 73.0%; no change 0.469; age-only 0.413; ridge 0.402. v0 validation LightGBM MAE 0.388. The audit found no leakage in v0:
  - independent recomputation of 4,431 targets: 0 mismatches;
  - 120 real snapshots × 11 features rebuilt from data truncated at t: 0 differences.
  
  But v0 relied on columns that are not point-in-time (league as the club's *current* league; contract expiry available only as a current value), and its unit (every valuation date) did not match the scouting question.
- **Decision:** v0 replaced by the SPEC design and kept as history. v0 numbers are not comparable with later ones (different population and target).
- **Evidence:** commit `aa607c0` (v0), `reports/v0/evaluation.md`, `reports/v0/results.md`; audit in `docs/PLAN.md` §1; SPEC in `docs/SPEC.md`; rebuild commit `3a8c31e`.
- **Paper relevance:** method (problem definition; why annual as-of snapshots).

### 2026-09-30 — Target definition: as-of rule vs fixed-window rule (Milestone M1)
- **Question:** Which target definition keeps the most usable snapshots without introducing bias?
- **What we tried:** SPEC as-of target, `log(latest valuation ≤ next 1 Sep / latest valuation ≤ 1 Sep)`, kept only if at least one new valuation falls in between (so a zero means "revalued, unchanged"). Compared with v0's rule (first valuation 335–425 days after t) on the same annual population.
- **Result (descriptive, 2013–2024):** population 28,260 snapshots. Usable under the as-of rule: 27,330 (96.7%). Usable under the 335–425-day window: 7,855 (27.8%). Revaluations bunch in particular months, so a fixed window misses most annual snapshots. Target (as-of, all years): mean −0.101, median −0.134, 14.1% exactly unchanged.
- **Decision:** as-of target (SPEC).
- **Evidence:** `reports/m1_data.md` ("Usable snapshots under both target definitions"); `scout/data/snapshots.py`; tests `tests/test_features.py::test_target_uses_latest_valuation_before_next_snapshot`, `::test_target_dropped_without_a_new_valuation`; commit `3a8c31e`.
- **Paper relevance:** method.

### 2026-09-30 — Reconstructing each player's club on 1 September (Milestone M1)
- **Question:** Can club membership at the snapshot date be rebuilt point-in-time, given that the dataset's club columns are current-state?
- **What we tried:** Three methods, each validated against the club the player actually played for in his next league game within 60 days (a validation-only check that looks after t; features never do):
  - `transfers`: last transfer on or before t (the SPEC's first choice);
  - `august_then_transfers`: last league appearance since 1 August, else transfers (the agreed fallback);
  - `latest_evidence`: the most recent of last league appearance, last transfer, and the club recorded on the last valuation, all on or before t.
  
  A separate check tested whether `player_valuations.current_club_id` is point-in-time or a current-state value.
- **Result (descriptive, match rate by year):**

  | Year | Players | transfers | august_then_transfers | latest_evidence |
  |---|---|---|---|---|
  | 2013 | 2,687 | 0.221 | 0.802 | 0.869 |
  | 2014 | 2,596 | 0.285 | 0.804 | 0.884 |
  | 2015 | 2,688 | 0.340 | 0.841 | 0.916 |
  | 2016 | 2,770 | 0.416 | 0.834 | 0.914 |
  | 2017 | 2,753 | 0.504 | 0.862 | 0.936 |
  | 2018 | 2,703 | 0.571 | 0.881 | 0.947 |
  | 2019 | 2,706 | 0.630 | 0.883 | 0.939 |
  | 2020 | 2,850 | 0.622 | 0.660 | 0.833 |
  | 2021 | 2,767 | 0.799 | 0.919 | 0.978 |
  | 2022 | 2,948 | 0.865 | 0.943 | 0.983 |
  | 2023 | 2,889 | 0.978 | 0.960 | 0.982 |
  | 2024 | 2,860 | 0.937 | 0.950 | 0.967 |

  The transfers table is incomplete before about 2021: in the 2013 check, 77% of players had no transfer row (README, "How the data is built").

  Point-in-time check on the valuation club (73,697 transfers, 2013–2024, with valuations within 365 days on both sides):
  - it changes across 89.6% of transfers;
  - the last valuation before shows the old club 78.2% of the time;
  - the first valuation after shows the new club 78.1% of the time;
  - 85.5% of players with a transfer have more than one valuation club.
  
  So it is point-in-time.

  Weak years: 2013 (0.869), 2014 (0.884) and 2020 (0.833). In 2020 the COVID-delayed transfer window stayed open until October, so some mismatches are real moves after 1 September. The match rate with those moves excluded: not recorded.
- **Decision:** `latest_evidence`. Both SPEC methods fell below 90% in early years, so the user was asked and chose this. The weak years are kept and flagged, not dropped.
- **Evidence:** `reports/m1_data.md`; `scout/data/snapshots.py::club_latest_evidence`, `club_match_rates`; `scout/data/report.py::valuation_club_check`; commit `3a8c31e`.
- **Paper relevance:** method + limitation (label noise in club-derived features and population membership, largest in 2013, 2014 and 2020).

### 2026-09-30 — M1 results: baselines vs LightGBM (Milestone M1)
- **Question:** With baseline features only, does LightGBM beat "no change" and a linear model?
- **What we tried:** No change, age-only (mean by age), ridge (alpha 1) and LightGBM (early-stopped on 2022, 226 trees). 12 features: age, position, sub-position, league, log value, 12-month value change, previous-season minutes / apps / goals+assists per 90, share of team minutes, as-of squad value, club moves in the last 12 months. Train on 2013–2021 (20,630 snapshots).
- **Result:**
  - **Validation (2022, n = 2,406), MAE:**
    - no change 0.424; age-only 0.375; ridge 0.369; LightGBM 0.364.
    - LightGBM minus ridge: −0.0049 (95% bootstrap CI −0.0087 to −0.0008).
    - LightGBM minus no change: −0.0598 (CI −0.0683 to −0.0506).
  - **Test (2023–2024, n = 4,294), single logged run, predictors refit on 2013–2022:**
    - MAE: no change 0.4103; ridge 0.3588; LightGBM 0.3586.
    - LightGBM minus ridge: −0.0002 (CI −0.0032 to +0.0030), a tie.
    - LightGBM minus no change: −0.0517 (CI −0.0582 to −0.0450).
    - LightGBM direction accuracy: 0.704.
- **Decision:** Report honestly: "no change" is beaten, the linear baseline is not. No tuning against the test numbers.
- **Evidence:**
  - Validation: `reports/m1_results.md` (run `20260930T133739Z`; generated at `8721f98-dirty`, code committed as `3a8c31e`).
  - Test: `docs/TEST_LOG.md` row 1 (commit `3a8c31e`); `reports/test_results.md` as of commit `c5a4e56`.
- **Paper relevance:** result (a strong linear baseline is hard to beat).

### 2026-09-30 — Test-set discipline (Milestones Phase 2 → M1)
- **Question:** How do we keep the test set untouched while iterating?
- **What we tried:** In the v0 design (Phase 2), `train.py` printed validation and test metrics together on every run.
- **Result:** The v0 test metrics were viewed 4 times. No feature, hyperparameter or model decision was based on them. The only change made after viewing was switching the age-only baseline from median to mean, because of a metric artifact (a zero prediction counts as a wrong direction) that was visible in validation too.
- **Decision:** From M1: `train.py` never builds the test years (asserted in code and in `tests/test_model.py::test_train_module_never_evaluates_the_test_set`). Only `scout/ml/evaluate_test.py --confirm-test --reason` touches them. It requires a clean git tree, and every run is appended to `docs/TEST_LOG.md` with date, commit and reason. At most one run per milestone. Two runs so far (M1, M2).
- **Evidence:** `docs/TEST_LOG.md`; README "Test-set discipline"; commits `3a8c31e`, `c5a4e56`.
- **Paper relevance:** method (reproducibility and evaluation hygiene).

### 2026-09-30 — The 2019 snapshots and the COVID-era market drop (Milestones M1–M2)
- **Question:** Does the 2019 snapshot year (target measured on 1 September 2020) behave differently?
- **What we tried:** Per-year description of the target, and per-year expanding-window backtests of all predictors.
- **Result:**
  - **Descriptive:** 2019 snapshots have mean target −0.241, median −0.223, and only 5.3% unchanged (other years 8.6–20.4%).
  - **Train-period backtest, M1 settings:** MAE for 2019 was LightGBM 0.374 vs age-only 0.362 and ridge 0.367. LightGBM was *worse* than the simple baselines only in that year.
  - **Train-period backtest, M2 tuned settings:** LightGBM 0.364, ridge 0.367, age-only 0.362.
  - **Tuning-pass CV breakdown:** LightGBM minus ridge for 2019 is −0.003 (95% CI −0.008 to +0.002), a tie.
- **Decision:** Keep 2019 in training; always report errors by year (SPEC).
- **Evidence:** `notebooks/01_eda.ipynb` (per-year table); `reports/m1_results.md` and `reports/m2_results.md` (backtest tables); `reports/m2_tuning.md` ("By year").
- **Paper relevance:** result + limitation (a market-wide shock that no player-level feature captures).

### 2026-09-30 — M2 improvement pass on validation data (Milestone M2)
- **Question:** Can a fair, time-boxed tuning pass on validation data only give LightGBM a clear edge over linear, and where would it come from?
- **What we tried:**
  - 54 LightGBM configurations: objective l2/l1/huber × leaves 7/15/31 × min child samples 50/200 × trees 150/300/600.
  - 5 ridge penalties: 0.1, 1, 10, 100, 1000.
  - Each scored by rolling-origin CV: fit on 2013..y−1, score y, for y = 2016–2021.
  - The best of each family compared once on 2022, plus an error breakdown by segment over the pooled CV folds and 2022.
- **Result:**
  - **Best LightGBM:** l1 loss, 7 leaves, 50 min child samples, 600 trees; mean CV MAE 0.357.
  - **Ridge:** mean CV MAE 0.363 at every alpha.
  - **Validation (2022), MAE:** tuned LightGBM 0.364, tuned ridge 0.369 (the untuned M1 LightGBM also scored 0.364). Difference −0.0047 (CI −0.0090 to −0.0004).
  - **By segment (pooled CV + 2022), LightGBM minus ridge:**
    - Attack −0.008; Defender −0.004; Goalkeeper −0.010; Midfield −0.004.
    - Ages 22–24: −0.010; 31+: −0.010; 25–27 and 28–30: tie; ≤ 21: tie.
    - Every value band favours LightGBM (−0.004 to −0.007).
    - Years 2016–2022: LightGBM better in 6, tie in 2019.
- **Decision:** Adopt the tuned settings (`scout/ml/best_params.json`). Record that tuning changed little: the edge over linear is consistent but small.
- **Evidence:** `reports/m2_tuning.md` (generated at `64a7937`); `scout/ml/tune.py`; MLflow experiment `scout-value-model`; commit `04a7766`.
- **Paper relevance:** result (a small, consistent non-linear edge within the training era).

### 2026-09-30 — M2 test run: LightGBM still ties linear (Milestone M2)
- **Question:** Does the tuned LightGBM beat both baselines on the untouched test set?
- **What we tried:** A single logged test run. Point predictors refit on 2013–2022 (23,036 snapshots) with the tuned settings.
- **Result (test, 2023–2024, n = 4,294):**
  - MAE: no change 0.4103; age-only 0.367; ridge 0.3586; LightGBM 0.3574.
  - LightGBM minus ridge: −0.0012 (95% CI −0.0044 to +0.0020), a tie.
  - LightGBM minus no change: −0.0529 (CI −0.0589 to −0.0473).
  - By year: 2023 ridge 0.353 vs LightGBM 0.354; 2024 ridge 0.365 vs LightGBM 0.361.
  - LightGBM direction accuracy: 0.704.
- **Decision:** **Negative result for the SPEC goal "beat both baselines":** met for "no change", not for linear, at M1 and at M2. The goal stays open, and M3's news features are the real test of whether non-linear or new signal exists. Nothing is tuned against these numbers.
- **Evidence:** `docs/TEST_LOG.md` row 2 (commit `04008c3`); `reports/test_results.md`.
- **Paper relevance:** negative result (the key baseline the news features must beat).

### 2026-09-30 — 80% prediction intervals (Milestone M2)
- **Question:** Can intervals with near-nominal coverage be produced, and do they hold across years and segments?
- **What we tried:** Quantile LightGBM (q10, q90) plus split-conformal calibration (CQR), in numpy. Coverage was estimated without the test years by repeating the procedure per year: fit on ..y−2, calibrate on y−1, score y. The served model is fit on 2013–2021 and calibrated on 2022 (margin +0.091 log units).
- **Result:**
  - **Backtest coverage (train/validation years):** 2017 0.675; 2018 0.842; 2019 0.753; 2020 0.818; 2021 0.822; 2022 0.758. 2017 is the only year below the SPEC's 75%. Pooled backtest coverage is lower for ≥ €20m players (0.741) and ages 22–24 (0.739).
  - **Test (2023–2024, n = 4,294):** coverage 0.822, mean width 1.171 log units. By year: 2023 0.829, 2024 0.814.
  - **Test by segment:** ages 22–24 0.786, 25–27 0.800, 28–30 0.792, 31+ 0.900 (over-covered), ≤ 21 0.857. Values < €1m 0.809, €1–5m 0.838, €5–20m 0.807, ≥ €20m 0.829.
- **Decision:** Keep CQR. The SPEC coverage goal (75–85%) is met on test. Keep reporting per year, since conformal guarantees assume exchangeable years.
- **Evidence:** `reports/m2_results.md` (80% prediction intervals), `reports/test_results.md`; `scout/ml/intervals.py`; `tests/test_intervals.py`.
- **Paper relevance:** method + result (distribution shift between years breaks conformal coverage in some years).

### 2026-09-30 — The population excludes breakout prospects (Milestone M2)
- **Question:** Who does the SPEC population (≥ 450 previous-season league minutes, revalued within the year) leave out, and does it matter?
- **What we tried:** Counted all candidates (any league minutes in the 7 leagues the previous season, club in those leagues on 1 September, valued) and split them into kept, excluded for < 450 minutes, and excluded for no revaluation.
- **Result (descriptive, 36,459 candidate snapshots, 2013–2024):**
  - The 450-minute rule excludes 60.0% of under-22 candidates.
  - Revalued under-22s excluded for < 450 minutes rose +0.544 on average (log), vs +0.319 for under-22s who were kept.
  - Exclusion for no revaluation is small (0.5–7.4% by year), highest in 2023–2024 and for over-31s (6.3%).
- **Decision:** The v1 population is unchanged. A separate prospects model for under-22s, with a lower minutes threshold and its own untouched test split, is added to SPEC "Future work".
- **Evidence:** `reports/m2_excluded.md`; `scout/data/excluded.py`.
- **Paper relevance:** limitation (the model cannot see breakout prospects, often a scout's main interest).

### 2026-09-30 — Data sources and terms (Milestones M1–M2)
- **Question:** Which data can be used, stored and published, and under what rules?
- **What we tried:** Checked the licence and state of the Transfermarkt dataset; set storage rules for Guardian Open Platform content before any ingestion.
- **Result:**
  - **Transfermarkt data:** Kaggle `davidcariboo/player-scores`, CC0-1.0. Collection stopped mid-July 2026 and valuations end 2026-06-12. The download of 2026-09-23 is pinned by SHA-256 in `data/manifest.json`.
  - **Guardian metadata:** only article IDs, URLs, publication / first-publication / last-modified dates, and tags are persisted.
  - **Guardian article text:** never persisted beyond 24 hours (purge job, and reads ignore older rows). Headlines count as article content, so they are not stored.
  - **Rate limit:** ≤ 500 API calls/day, enforced in Postgres.
  - **Switches:** LLM processing of text and stored embeddings are each switchable off until the terms are confirmed.
  - The M4 full-text fallback uses tags plus keywords from the URL slug.
- **Decision:** As above. LLM extraction waits for (a) a cost estimate and (b) the user's confirmation that the Guardian terms allow LLM processing of article text and storing embeddings.
- **Evidence:** `docs/SPEC.md` (Data sources), `SECURITY.md` (Guardian content rules), `db/news.sql`, `scout/news/`, `tests/test_news.py`.
- **Paper relevance:** limitation (reproducibility of the news corpus: others can rebuild it only via the API, not from shared text).

### 2026-09-30 — Planned look-ahead safeguards for news features (Milestone M3, planned)
- **Question:** How can news features avoid look-ahead bias beyond simple date filtering?
- **What we tried:** Identified two leakage paths during planning (not yet tested):
  - **Edited articles:** Guardian articles can be edited after publication, so a snapshot could see later text. Safeguard: join on first publication date (`first_published_at < t`), store `last_modified`, and measure sensitivity to excluding articles modified after t.
  - **Model hindsight:** the extracting LLM knows how real players' careers turned out and could leak that into "signals". Safeguards: extract only explicit statements; require an evidence quote per signal, verified verbatim against the article text; no free-form sentiment; and every news feature gets a leakage test that appends post-t articles and asserts the features at t don't change.
- **Result:** Not recorded (planned).
- **Decision:** Build both safeguards into M3 before any extraction run.
- **Evidence:** `docs/PLAN.md` (§2 news-feature leakage risks, M3 checklist); `db/news.sql` (`first_published_at`, `last_modified`).
- **Paper relevance:** method (the central methodological contribution if it holds up).

### 2026-09-30 — Linking player mentions point-in-time (Milestone M3)
- **Question:** How do we link names in news to `player_id`s without false links and without using information from after the article date?
- **What we tried:** A linker on case- and accent-folded text, built to keep character offsets:
  - **Matching:** full names, longest match first; single-name players only when capitalized *and* their club appears in the article.
  - **Candidates:** only players valued in the 730 days before the article.
  - **Shared names:** resolved only by each candidate's club *at the article date* (the same `latest_evidence` club method as the model). Anything still ambiguous is skipped and counted.
  - **Tag-only mode:** works on Guardian tags alone when text isn't available.
- **Result (descriptive, `players.csv`):** 50,149 players; 2,389 share a full name with another player; 5,839 surnames are shared; 1,757 players have a single-token name. Precision on real links: not recorded yet. It needs the 100 hand-labelled links (target ≥ 0.95).
- **Decision:** Adopt linker v1. `tests/test_linker.py` shows that a transfer dated *after* the article cannot resolve an ambiguous name.
- **Evidence:** `scout/news/linker.py`; `tests/test_linker.py`; profiling via `pandas` on `data/raw/players.csv` (normalized-name duplicates).
- **Paper relevance:** method (point-in-time entity linking).

### 2026-09-30 — Guarding LLM extraction against hindsight (Milestone M3)
- **Question:** How do we stop the extracting model from adding what it knows about players' later careers?
- **What we tried:** Prompt v1 (`extract-v1`):
  - only facts stated in the article; outside knowledge forbidden; the article is treated as untrusted data;
  - four signal types with fixed labels, and structured JSON output;
  - **evidence verification:** every signal must quote the article verbatim (whitespace-normalized). Unverifiable signals are dropped and counted, and only the quote's offsets are stored.
  
  News features count an article only if `first_published_at < t`, with an option to also drop articles edited at or after t, for a sensitivity analysis.
- **Result:** Unit tests only (no LLM run yet):
  - a hindsight-style quote ("Kane later joined Bayern Munich") and a paraphrase are dropped;
  - future-dated articles leave the features at t unchanged.
  
  Real drop rate: not recorded.
- **Decision:** No extraction run until the user approves (a) the cost estimate and (b) that the Guardian terms allow LLM processing.
- **Evidence:** `scout/news/extract.py`, `scout/news/features.py`; `tests/test_extract.py`, `tests/test_news_features.py`, `tests/test_labeling_textpass.py::test_run_batch_verifies_quotes_and_caches_by_prompt_version`.
- **Paper relevance:** method (the main look-ahead safeguard; the drop rate of unverified quotes is a candidate result).

---

## Paper notes

### Candidate contributions
- A point-in-time pipeline for player-value forecasting that avoids current-state columns, including club reconstruction from three dated sources with per-year validation.
- A leakage-safe way to turn news into features: first-publication joins, edit-date sensitivity, and verbatim evidence quotes against LLM hindsight.
- An honest baseline study: a strong linear model on log value is hard to beat. LightGBM's small validation edge does not carry to the test years, which is the bar news features must clear.
- Calibrated uncertainty (split-conformal) with per-year coverage under distribution shift, including the COVID year.
- A documented population blind spot (excluded prospects) and its size.

### Related work to check later
- Football market-value prediction from performance data (Transfermarkt-based studies).
- The "wisdom of the crowd" validity of Transfermarkt values vs actual transfer fees.
- Look-ahead and temporal leakage in financial and news-based forecasting; point-in-time data practices.
- LLMs as feature extractors from news for forecasting; knowledge-cutoff and hindsight contamination in LLM evaluations.
- Conformalized quantile regression (Romano et al., 2019) and conformal prediction under distribution shift.
- Entity linking of person names in sports news.

### Open questions
- Do news features close the gap to, or beat, the linear baseline on the untouched test years?
- How large is LLM hindsight leakage in practice? A candidate check: compare extraction with and without evidence verification, or on articles the model is likely to know vs obscure ones.
- How much does news coverage differ by league (English vs other leagues), and does any gain concentrate where coverage is dense?
- Would a separate prospects model (under-22s, lower minutes threshold) behave differently from the main population?
- Can the year-to-year shift in interval coverage be reduced (for example, calibrating on more than one year)?
