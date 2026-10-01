# Scout — audit and upgraded plan

Written 2026-09-29, revised the same day to follow [SPEC.md](SPEC.md) and the decisions in §0.1. **SPEC.md is the source of truth for the prediction problem; this file is the delivery plan.** Milestones run from Sep 29 to Nov 22 (7 weeks) on a budget of 12–15 h/week (84–105 h).

---

## 0.1 Decisions, round 2 (2026-09-29)

| Topic | Decision |
|---|---|
| v0 rebuild | Approved for M1. The M1 report gives usable snapshot counts under **both** target definitions (the SPEC's as-of target vs v0's 335–425 day window) for the README. |
| Club at t | Transfers-based, with the match rate reported per year. If any year is below 90%: fall back to the club of the player's last league appearance before the snapshot (August matches), then transfers, and report the match rate per year for **both** methods. Ask only if the fallback also fails. |
| Deploy | **Kept:** AWS Lightsail or a small EC2 instance running `docker compose`, **≤ US$15/month**. A 7th week (Nov 16–22) was added for it. Model routing and the thin UI stay deferred. |
| Dependencies | Approved: `mlflow`, `anthropic`, `mcp`, `voyageai`, `pre-commit` + gitleaks, CodeQL. Intervals in plain numpy (split conformal). Tracing in Postgres; Langfuse is a stretch goal after the project. |
| Embeddings | Voyage AI, cached in Postgres so each text is embedded once |
| LLM spend | US$2/day cap on public endpoints, enforced in code. **Before any bulk LLM job: estimate the cost and wait for approval.** |
| Eval thresholds | Placeholders until the first full eval run with a validated judge; then each is set just below the measured score and raised as quality improves |
| Hand labeling | About 4 h, approved. Labeling files are prepared so they're fast to fill in. |
| Repo | Goes public after M1: enable CodeQL then; a small sample of the CC0 data can go into CI |
| Guardian | Store only article IDs, URLs, dates, tags and extracted signals. **Article text is never persisted beyond 24 h** (a purge job plus a test that proves it). Text is fetched live when an answer or citation needs it, cached ≤ 24 h. ≤ 500 calls/day. LLM processing and stored embeddings **must each be switchable off** until the terms are confirmed. (Recorded in SPEC.md and SECURITY.md.) |
| Test discipline | `train.py` never prints test metrics. A separate script with an explicit flag evaluates test and appends date, commit and reason to `docs/TEST_LOG.md`. The README notes the test set was viewed 4 times in Phase 2, with no decisions based on it. |
| Reproducibility | Data manifest (download date + SHA-256) checked at load time; Python 3.12 locally and in Docker via uv + lockfile; one command runs load → features → train → evaluate. |
| DB security | Postgres bound to 127.0.0.1; password in a gitignored `.env` (plus `.env.example`); a loader role with write access and a read-only role for the API/agent; CSV columns allow-listed against the schema and built with `sql.Identifier`. |

---

## 0. Decisions (2026-09-29)

From [SPEC.md](SPEC.md). These replace the Phase 1–2 design in the code committed at `aa607c0` (now "v0").

| Topic | v0 (current code) | Decision (SPEC) |
|---|---|---|
| Prediction unit | Every valuation date | One player per **1 September snapshot**, 2013–2024 |
| Current value | Valuation on the snapshot date | Latest valuation on or before the snapshot |
| Target | First valuation in [t+335, t+425] | log(value as of the next 1 Sep / current value), each the latest valuation on or before its date; keep only snapshots with ≥ 1 new valuation between the two dates |
| Population | 14 leagues, all players | 7 leagues (GB1, ES1, L1, IT1, FR1, NL1, PO1, IDs confirmed in `competitions.csv`); club at the snapshot is in one of them; **≥ 450 league minutes in those leagues in the previous season**; players arriving from outside them excluded |
| Club at t | `player_valuations.current_club_id` | **Rebuilt from `transfers`** (as-of); current-state columns are never used |
| Features | age, value, 6m momentum, minutes 6/12m + trend, G+A/90, league, club ppg, position | age, position, league, log value, **12m value change**, previous-season minutes / appearances / G+A per 90, **share of team minutes**, **squad value as of t**, **club moves in last 12m** |
| Split | By date with purge; val 2023-24, test 2024-25 | Train snapshots 2013–2021, val 2022, **test 2023–2024**. Annual targets end exactly at the next snapshot, so no purge is needed. |
| Metrics | MAE, RMSE, direction | **MAE, directional accuracy, 80% interval coverage**, all also broken down by snapshot year (2019 overlaps the COVID dip). RMSE kept as secondary. |
| Success | — | Beat no-change and linear on test; 80% intervals cover **75–85%** of test cases |
| Data | Kaggle download, unversioned | CC0-1.0; collection stopped (valuations end 2026-06-12); record the download date + file hashes |
| Live demo | — | Predictions use data as of 2026-06-12 |
| Out of scope | — | Transfer fees, Brazil and other calendar-year leagues (v2), women's/youth football, live updates, betting, fine-tuning, a full frontend (thin UI only) |

**v0 is kept as history.** `reports/evaluation.md` becomes the "per-valuation snapshot" baseline study for the README's "what didn't work / what changed" section. Parts of v0 carry over: the leakage-test pattern, the `_asof`/window helpers, the SHAP explainer, and the baselines.

**Data check for the club rebuild (2026-09-29, read-only):** at 2023-09-01, the club derived from transfers matches the club the player appeared for in the next 60 days for **95.1%** of active players (n = 5,487). Transfer rows are much sparser in early years (4.7k in 2013 vs 16.7k in 2023), so M1 must measure agreement **per snapshot year** before relying on it. If a year falls below 90%, use the fallback agreed in §0.1 (last August league appearance, then transfers) and report both methods per year; stop and ask only if the fallback also fails.

---

## 1. Audit (2026-09-29)

### 1.1 Status of the original phases

| Phase | Status | Evidence |
|---|---|---|
| 0 Scaffolding | Done | `docker-compose.yml`, `Dockerfile`, `scout/api/main.py` (`/health`), `pyproject.toml` + `uv.lock`; commit `d037266` |
| 1 Data and target | **Partial** | Committed `aa607c0`. `scout/data/target.py`, `tests/test_target.py`, `notebooks/01_eda.ipynb` and `db/schema.sql` are done for v0. `scout/data/load.py` has **never run** against Postgres. The target must be rebuilt to the SPEC. |
| 2 Features and model | Done for v0 | Committed `aa607c0`. `scout/ml/{features,train,model}.py`, `tests/test_{features,model}.py`, `reports/`; `models/lgbm.txt` (gitignored). Features and splits must be rebuilt to the SPEC. |
| 3 News RAG | Not started | `scout/news/` is empty |
| 4 Agent and API | Not started | Only `/health` exists |
| 5 Frontend | Not started | `frontend/.gitkeep` |

### 1.2 Correctness checks on v0 (run read-only)

| Check | Result |
|---|---|
| Target | Pass. An independent brute-force check of 4,431 snapshots found 0 mismatches; gaps are all within the window, with no zero values. |
| Leakage | Pass. The synthetic future-data test passes, and a real-data check of 120 snapshots × 11 features with all tables truncated at t found 0 differences. Soft spot: `position` is the player's current value. |
| Splits | Time-based with purge: pass. **Test discipline: partial.** `train.py` printed test metrics on every run (viewed about 4 times); no tuning was based on them. |
| Baselines | Pass. No-change, age-only and ridge are all reported (test MAE 0.469 / 0.413 / 0.402 vs LightGBM 0.394; direction 73.0%). |

### 1.3 Code health
15 tests pass; nothing covers the DB. Seeds are set and `uv.lock` is committed, but Python isn't pinned (the local `.venv` is 3.13, the Dockerfile uses 3.11). There's no single end-to-end command, no dataset manifest, no secrets in the tree or git history, and `pip-audit` found no known vulnerabilities.

### 1.4 Bugs and risks, ranked

| # | Severity | Finding | Fix (milestone) |
|---|---|---|---|
| 1 | ~~High~~ Resolved | Phase 1–2 work was uncommitted | Committed and pushed `aa607c0` |
| 2 | High | The Postgres path has never run (schema types and `COPY` unverified) | Docker is running now; run the load + DB smoke test (M1) |
| 3 | High | v0 target, population, features and split differ from the SPEC | Rebuild in M1 (§3) |
| 4 | Medium | Club rebuild from `transfers` is unvalidated for early years | Agreement per snapshot year; stop and ask if < ~90% (M1) |
| 5 | Medium | Test metrics are computed on every training run | `--final` gate + logged final runs (M1) |
| 6 | Medium | Selection bias: the target requires a revaluation and the population requires ≥ 450 minutes | Report the excluded share by year/age (M2) |
| 7 | Medium (security) | Postgres published on `0.0.0.0:5432` with password `scout` | Bind to `127.0.0.1`, generated password (M1) |
| 8 | Medium (security) | The app and loader connect as the Postgres superuser | Owner, loader and read-only agent roles (M1; test in M5) |
| 9 | Low (security) | `load.py` builds SQL identifiers with f-strings from CSV headers (`load.py:25`, `:36`) | `psycopg.sql.Identifier` + column allow-list (M1) |
| 10 | Low | Docker images unpinned, container runs as root, no `--frozen`, no `models/` in the image | Hardening (M2) |
| 11 | Low | The dataset is frozen (collection stopped), but its version isn't recorded | `data/manifest.json` with hashes + download date (M1) |

---

## 2. Gap analysis against the upgraded scope

Effort: S = up to 3 h, M = 3–8 h, L = more than 8 h.

| # | Item | Status | What must change | Effort | Depends on |
|---|---|---|---|---|---|
| 0 | **Rebuild to the SPEC** | Partial (v0) | Annual snapshots, new target, population, transfers-based club, new features, 2013–2021 / 2022 / 2023–24 split, errors by year | L | Club-rebuild validation |
| 1 | 80% intervals + coverage | Missing | Quantile LightGBM (q = 0.1/0.9) + split-conformal on the 2022 val set; coverage on test overall, by year and by segment; target 75–85% | M | Rebuild, test gate |
| 2 | MLflow | Missing | New dependency (ask); Postgres backend store; log params, metrics, manifest hash, git SHA, model | S–M | Manifest, DB |
| 3 | LLM news features | Missing | Guardian backfill, alias table, linker (skip ambiguous), 100 hand-checked links, Haiku structured outputs via Batch API, cache on `(article_id, prompt_version)`, point-in-time join, ablation, coverage. **Kept only if the ablation shows a gain.** | L | Guardian key, DB, `anthropic` SDK (ask), terms |
| 4 | Hybrid retrieval + reranker + citations | Missing | `tsvector` + pgvector with RRF, metadata filters, recency decay, measured reranker, `[n]` citations | M–L | Embedding provider, #3 |
| 5 | Number guardrail | Missing | Extract numbers from answers, normalize, match against that turn's tool outputs, log violations, regenerate once then flag | M | Agent |
| 6 | MCP server | Missing | Read-only `get_player`, `predict_value_change`, `search_players`, `search_news`, `compare_players`; MCP Inspector | S–M | Tools; `mcp` SDK (ask) |
| 7 | Eval suite + calibrated judge | Missing | 60-question golden set, recall@k, faithfulness, correctness, judge vs 50 of your labels | L | Agent, your labeling |
| 8 | CI | Missing | pytest, pip-audit, CodeQL, Dependabot; eval subset per PR on a fixture DB (CC0 data, so a small sample can be committed); nightly/manual full run | M | Repo settings, API key secret |
| 9 | Ops | Missing | Deploy, tracing to Postgres, cost/p95/cache dashboard, prompt caching, model routing | L | Host decision |
| 10 | Presentation | Partial | Architecture diagram; results table (baselines, news ablation, evals, coverage, security); "what didn't work" (v0 → SPEC is the first entry); data caveats | M | Everything |
| 11 | Thin UI | Missing | Chat + player page with SHAP chart and interval. **Deferred** (SPEC: thin UI only). | M | API |
| 12 | Security gates | Missing | `.claude/settings.json`, gitleaks pre-commit, CodeQL/pip-audit/Dependabot, branch protection, package vetting | M | Repo admin |
| 13 | AI-feature security | Missing | Read-only role, read-only MCP, rate limits + spend cap, injection evals, OWASP mapping (§5) | M | Agent, evals |
| 14 | SECURITY.md | Missing | Skeleton in M1, completed in M6 | S → M | — |

**News-feature leakage risks:**
- **Article edits:** Guardian articles can be edited after publication. Use the first-publication date and record `lastModified`.
- **LLM hindsight:** the extractor knows how players' careers turned out. Extract only explicit statements, each with an evidence quote verified against the article text, and don't extract free-form sentiment.

---

## 3. Milestones

| Milestone | Dates | Est. h | Headline |
|---|---|---|---|
| M1 | Sep 29–Oct 11 | 20 | Rebuild the pipeline to the SPEC; club validation; test gate; reproducibility; DB roles; core security gates |
| M2 | Oct 12–18 | 16 | MLflow, 80% intervals + coverage, CodeQL (repo public), Docker hardening, Guardian metadata backfill |
| M3 | Oct 19–25 | 16 | Player linking, LLM news features (switchable, cost-approved), ablation |
| M4 | Oct 26–Nov 1 | 17 | Hybrid retrieval (Voyage, switchable), live-fetched citations, tools API, agent, number check |
| M5 | Nov 2–8 | 18.5 | Eval suite, calibrated judge, CI evals, MCP, injection tests |
| M6 | Nov 9–15 | 12.5 | Tracing, dashboard, prompt caching, spend cap, README, SECURITY.md |
| M7 | Nov 16–22 | 10 | AWS deploy (≤ US$15/month), production smoke evals, final README |
| **Total** | | **~110** | vs 84–105 h over 7 weeks (see §4) |

### M1: rebuild to the SPEC (Sep 29–Oct 11; Docker is already running)
- [x] `data/manifest.json` (download date + SHA-256 per CSV), checked at load time
- [x] Python 3.12 locally (`.python-version`) and in Docker; `uv sync --frozen`
- [x] Club at t: transfers alone 22–98% and the August fallback 66–96% both failed 90% → asked → **most recent of league appearance / transfer / valuation club** (83–98%; 2013, 2014 and 2020 below 90%, accepted and flagged). The valuation club was verified as point-in-time (changes across 90% of 73,697 transfers). See `reports/m1_data.md`.
- [x] Annual snapshots (1 Sep, 2013–2024): current value = latest valuation ≤ t; target = latest valuation ≤ next 1 Sep; keep only if ≥ 1 new valuation in between. Counts per year under the as-of target **and** the v0 335–425 window.
- [x] Population: club in the 7 leagues at t; ≥ 450 league minutes in those leagues in the previous season
- [x] Features: age, position, league, log value, 12m value change, previous-season minutes / apps / G+A per 90, share of team minutes, squad value as of t, club moves in last 12m
- [x] Leakage tests for every feature (append future rows → no change) + a real-data truncation test (skipped when the CSVs are absent)
- [x] Split 2013–2021 / 2022 / 2023–24; baselines no-change + linear (age-only as an extra reference); LightGBM; expanding-window backtest by year on 2016–2022 (never touches test)
- [x] `train.py` prints no test metrics; `scout/ml/evaluate_test.py --confirm-test --reason ...` appends to `docs/TEST_LOG.md`; one M1 test run (2026-09-30, commit `3a8c31e`: LightGBM beats no-change, ties linear)
- [x] One command: `uv run python -m scout.pipeline` (load → features → train → evaluate on val)
- [ ] (code done; **verification pending Docker**) Postgres bound to 127.0.0.1; `.env` / `.env.example`; roles `scout_loader` (write) and `scout_reader` (read-only, API/agent); `load.py` allow-lists CSV columns and uses `sql.Identifier`
- [x] `.claude/settings.json` deny rules; pre-commit + gitleaks; GitHub Actions (pytest, pip-audit, gitleaks); Dependabot; `SECURITY.md` skeleton with the Guardian rules
- [x] Trained models written to new versioned paths (`models/<run_id>/`); never overwrite `models/lgbm.txt` (v0)

**Done when:** one command rebuilds everything from the raw CSVs; club match rates are reported per year; every feature has a leakage test; the test set has been evaluated exactly once and logged; CI is green.
**Risks:**
- **Early-year club rebuild accuracy:** measured first, with the fallback ready.
- **Small data:** about 2–3k snapshots per year; report bootstrap intervals on MAE differences.
- **COVID year:** the 2020 season started after 1 Sep for some leagues, so "league at t" can be one season stale for that year.

### M2: MLflow, intervals, hardening, news metadata backfill (Oct 12–18; done early, 2026-09-30)
- [x] MLflow in Postgres (own `mlflow` database + `scout_mlflow` role); every tune/train run logged with params, metrics, manifest, commit
- [x] **Improvement pass (validation only, time-boxed):** rolling-origin CV 2016–2021, 54 LightGBM configs + 5 ridge alphas, error breakdown by position / age / value band → `reports/m2_tuning.md`. LightGBM beats linear by ≈0.005 MAE in every segment on validation data.
- [x] Split-conformal 80% intervals (quantile LightGBM + CQR, numpy); backtest coverage 67.5–84.2% by year; `explain()` returns the interval
- [x] Excluded-share report → `reports/m2_excluded.md` (key finding: 60% of under-22 candidates excluded by the 450-minute rule)
- [x] Single M2 test run (commit `04008c3`): coverage **82.2%** ✓ (75–85%); LightGBM **ties linear** (−0.0012, CI includes 0) ✗ → "beat both baselines" not met; stated in README
- [x] Repo public; CodeQL (python + actions, 0 open alerts); ruleset on `main` (required checks + CodeQL high-severity gate; admin bypass for direct pushes)
- [x] Docker images pinned by digest; non-root API user (M1); Dependabot for docker/compose; Actions pinned by SHA
- [x] Guardian client (metadata only, ≤ 500 calls/day enforced in Postgres, 1 call/s), `news_*` tables, resumable backfill, 24 h text cache + purge + tests
- [ ] **Live backfill: waiting for `GUARDIAN_API_KEY`** (code and tests done; run `python -m scout.news.backfill`)

### M3: news features (Oct 19–25; started 2026-09-30 on branch `m3/news-features`)
- [x] Alias index (players.csv names, club-name keys); linker v1 (full names, capitalized mononyms only with club context, active players only, ambiguity resolved by club at article date; skips counted); tag-only mode
- [ ] **Labeling file 1:** generator and scorer done (`scout/news/labeling.py`). No article text in the file: URL, matched name, candidate player, club at date, Transfermarkt link. *Needs mentions (backfill + text pass), then your ~1.5 h of labelling.*
- [x] Extraction v1 code (`extract-v1` prompt, JSON schema, Batch API runner, verbatim-quote verification, offsets only, cache on `(article_id, prompt_version)`, model from `NEWS_LLM_MODEL`); tested with a fake client
- [ ] **Extraction run: blocked** on (a) the cost estimate (needs article counts + word counts from the backfill), (b) your OK, and (c) your confirmation that the Guardian terms allow LLM processing. Also: confirm Haiku 4.5 structured-output support with one Models API call at that point.
- [x] Point-in-time news features (`first_published_at < t`; optional edit-sensitivity filter) + leakage tests
- [ ] Ablation (val, then the milestone's single test run) + coverage by league: after mentions/signals exist

**Done when:** the ablation and coverage tables are in the report; a re-run hits the cache; with the switch off, the pipeline runs without news features.

### M4: retrieval and agent (Oct 26–Nov 1)
- [ ] Voyage embeddings behind an `EMBEDDINGS_ENABLED` switch, cached in Postgres by content hash; if disabled or the terms disallow it, retrieval falls back to metadata + full-text over titles/tags
- [ ] Hybrid retrieval (RRF), metadata filters, recency decay; Haiku reranker kept only if recall@5 improves
- [ ] Citations: text fetched live from the Guardian API when needed, cached ≤ 24 h
- [ ] FastAPI tools with Pydantic validation; `scout_reader` role; predictions as of 2026-06-12
- [ ] Streaming agent; `[model]` / `[news n]` labels; Transfermarkt caveat; news treated as untrusted data
- [ ] Number check + violation log; US$2/day spend cap enforced in code (checked before each call)

**Done when:** streaming chat answers all 4 tool types with citations; a planted wrong number is caught in a unit test; the spend cap blocks calls in a test.

### M5: evals, CI evals, MCP (Nov 2–8)
- [ ] 60-question golden set incl. unanswerables, a planted injection article and injection in the user question
- [ ] **Labeling file 2:** 50 answers as a CSV/markdown sheet with question, answer, tool outputs and cited sources, plus blank `faithful` / `correct` / `note` columns
- [ ] LLM judge → agreement + κ against your labels; **cost estimate → approval → full run**; thresholds set just below the measured scores
- [ ] CI eval subset (about 12 questions) on a CC0 fixture DB; full suite nightly/manual
- [ ] MCP server (stdio), read-only, 5 tools; MCP Inspector
- [ ] Test that `scout_reader` can't write or run DDL; injection attempts logged

### M6: operations and presentation (Nov 9–15)
- [ ] Tracing to Postgres (model, tokens in/out/cached, latency, cost, tools, violations)
- [ ] Dashboard: cost per query, p95 latency, cache hit rate
- [ ] Prompt caching on tools + system prompt (verify cache reads)
- [ ] Rate limits on public endpoints
- [ ] README: architecture diagram, results table (baselines, news ablation, evals, coverage, security), "what didn't work" (v0 first), data caveats
- [ ] SECURITY.md complete with OWASP mapping and test evidence

### M7: deploy (Nov 16–22)
- [ ] AWS Lightsail or small EC2, `docker compose`, TLS reverse proxy, secrets from env; ≤ US$15/month (budget alarm)
- [ ] Production smoke evals against the deployed URL; spend cap verified live
- [ ] Final README pass with the live URL; buffer for M1–M6 slippage

---

## 4. Budget and what to cut

About 110 h over 7 weeks against 84–105 h. **Already cut:** the thin UI and model routing (deferred), Langfuse (a stretch goal after the project), a 60-question golden set, and no sentiment extraction. If we slip further, cut in this order:
1. The reranker (−2 h; report hybrid-only recall)
2. MLflow reduced to local file-store autolog (−1.5 h)
3. News features for Premier League clubs only (−2 h)

The evals, security work and deploy are protected.

---

## 5. OWASP mapping (tentative; verify IDs in M1)

| Control | OWASP LLM Top 10 (2025) | OWASP Agentic Top 10 |
|---|---|---|
| News wrapped as untrusted data; injection evals; attempts logged | LLM01 Prompt Injection | ASI01 Agent Goal Hijack |
| Read-only DB role and tools; parameterized SQL; input schemas | LLM06 Excessive Agency | ASI02 Tool Misuse, ASI03 Identity & Privilege Abuse |
| Number check; citations; Transfermarkt caveat; faithfulness eval | LLM09 Misinformation | ASI09 Human-Agent Trust Exploitation |
| Rate limits; spend cap; max tool iterations; `max_tokens` | LLM10 Unbounded Consumption | ASI08 Cascading Failures |
| Lockfiles; pip-audit; Dependabot; package vetting | LLM03 Supply Chain | ASI04 Agentic Supply Chain |
| Guardian-only ingestion; provenance; planted-article test | LLM04 Data and Model Poisoning, LLM08 Vector and Embedding Weaknesses | ASI06 Memory & Context Poisoning |
| No secrets in prompts or logs; redaction | LLM02 Sensitive Information Disclosure, LLM07 System Prompt Leakage | — |
| Output rendered as escaped text; never executed | LLM05 Improper Output Handling | ASI05 Unexpected Code Execution (N/A) |

---

## 6. Open questions

All questions from the first draft were answered on 2026-09-29 (see §0.1). Still pending on your side: whether the Guardian terms allow LLM processing and stored embeddings. M3–M4 are built so either can be switched off.
