# Scouting Value Predictor — Spec

## Problem
Predict how a football player's market value will change over the next 12 months,
with an uncertainty range and an explanation, so a scout can spot players likely
to rise or fall in value.

## Prediction unit and target
- Unit: one player at one snapshot date.
- Snapshot dates: 1 September each year (after the summer window).
- Current value: the latest valuation on or before the snapshot date.
- Target: log(value as of the next 1 September / current value), where each
  value is the latest valuation on or before that date.
- Keep only snapshots with at least one new valuation between the two dates,
  so a zero change means "revalued, unchanged", not "never updated".

## Population
- Players whose club at the snapshot plays in: Premier League, La Liga,
  Bundesliga, Serie A, Ligue 1, Eredivisie, Liga Portugal (confirm the
  competition IDs in the competitions table).
- At least 450 league minutes in those leagues in the previous season.
- Players arriving from outside these leagues are excluded in v1.

## Data sources
- transfermarkt-datasets by dcaribou (Kaggle: "Football Data from Transfermarkt"),
  CC0-1.0 license. Collection stopped mid-July 2026; valuations end 12 June 2026.
  Record the download date and file hash for reproducibility.
- News (features + RAG): The Guardian Open Platform API, under these rules:
  - Persist only article IDs, URLs, dates, tags and extracted signals.
  - Headlines are article content: never stored (the 24-hour rule applies). Text search
    without article text uses tags plus keywords from the URL slug.
  - Never persist article text beyond 24 hours: a purge job, plus a test that
    proves it.
  - Fetch text live when an answer or citation needs it; cache it for at most
    24 hours.
  - Stay within 500 API calls per day.
  - LLM processing of article text and stored embeddings can each be switched
    off (`NEWS_LLM_ENABLED`, `EMBEDDINGS_ENABLED`) until the Guardian terms are
    confirmed to allow them.
- Caveat: Transfermarkt values are crowd-sourced estimates, not transfer fees.

## Baseline features (as of the snapshot date)
- Age, position, league, current log value
- Value change over the previous 12 months
- Minutes, appearances, goals + assists per 90 in the previous season
- Share of the team's minutes played
- Club strength proxy: total squad value at the snapshot
- Club moves in the previous 12 months

## Planned additions
- M3: LLM-extracted news features (injury, rumor, contract, manager change),
  joined point-in-time, kept only if an ablation shows they help.

## Leakage rules
- No feature may use data dated after the snapshot.
- Never use "current state" columns directly (current club, contract expiry,
  highest-ever value, club market value, international caps). Rebuild club
  membership from the transfers table and squad value from as-of valuations.

## Splits and evaluation
- Snapshots 2013–2024 (2024 is the last with a target inside the data).
- Train: 2013–2021. Validation: 2022. Test: 2023–2024, evaluated once per milestone.
- Report errors by snapshot year; the 2019 snapshot's target overlaps the
  2020 COVID-era market dip.
- Baselines: "no change" and linear regression.
- Metrics: MAE on the log change, directional accuracy, 80% interval coverage.
- Success: beat both baselines on the test set; 80% intervals cover 75–85%
  of test cases.
- Live demo predictions use data as of 12 June 2026, the last valuation date.

## Future work (v2)
- **Prospects model (candidate experiment).** The v1 population's 450-minute rule
  excludes 60% of under-22 candidates, and those players rise most when revalued
  (+0.54 log on average vs +0.32 for under-22s kept; `reports/m2_excluded.md`).
  A separate model for under-22s with a lower minutes threshold, and its own
  untouched test split, would test whether breakout prospects are predictable.
  The v1 population stays as defined above.
- A focused experiment with **StatsBomb open data**: for the competitions and
  seasons it covers, test whether detailed event data (passes, pressures,
  duels) improves predictions for defenders and midfielders, whose value is
  least explained by goals and assists.
- Design: match the StatsBomb players to our `player_id`s and build per-90
  event features over the same "previous season" window. Compare the model
  with and without them on the same snapshots, with errors by position and
  season.
- Openly licensed data only, used under StatsBomb's open-data user agreement.
  No scraping. Follow StatsBomb's attribution requirements (credit StatsBomb
  as the data source and show their logo wherever results based on the data
  are published). Coverage is limited to specific competitions and seasons,
  so report results only for what is covered.

## Out of scope
Transfer fees, Brazilian and other calendar-year leagues (v2 candidate),
women's and youth football, live data updates, betting use, model
fine-tuning, a full frontend (thin UI only).

## Risks
Data collection has stopped (no newer data); coverage gaps outside the
chosen leagues; sparse news for non-English leagues; noise in crowd-sourced
values.