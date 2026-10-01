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
- Public text (features + RAG), chosen 2026-10-01 after the Guardian was dropped
  (its terms prohibit AI-related use). Evaluation: `reports/m3_sources.md`.
  - **Wikipedia revision history + Wikidata** (LLM extraction track). Players are
    mapped through Wikidata's Transfermarkt player ID (P2446) to their English
    Wikipedia page. Features use the revision in force on each snapshot date (and
    the one 365 days earlier), so text written after t is never read.
    - Licenses: Wikipedia text CC BY-SA 4.0 (and GFDL); Wikidata CC0.
    - Access: MediaWiki Action API, serial requests (1 at a time, < 5/s),
      `maxlag`, and a User-Agent naming the tool and contact
      (`ScoutResearchBot/… (https://github.com/simonrl13/footballscout; …)`).
    - Storage: revision text may be stored (the license allows it), always with
      its revision URL so attribution can be shown.
- **Attribution and display rules** (agent answers, API responses, UI, reports):
  - Never show long passages. Show a short summary (at most two sentences) or a
    verbatim quote of at most 300 characters, marked as summarized or quoted.
  - **Wikipedia:** link to the *specific revision*
    (`https://en.wikipedia.org/w/index.php?oldid=<revid>`), name the page, and
    add "Text from Wikipedia, CC BY-SA 4.0" with links to the license and to
    the page history (authors). If the text is changed, say so. Excerpts shown
    to users stay under CC BY-SA.
  - **Wikidata:** no attribution required (CC0); credit it as a courtesy.
- Extraction schema (`extract-v2`): injuries (type, date, duration if stated),
  contract extensions and expiry, loans and transfers. No transfer rumours.
- Any LLM-extracted event must carry its own date and an evidence quote that
  appears verbatim in the source text, and only events dated in the 12 months
  before the snapshot count. Otherwise it is dropped. The extracting model may know
  later outcomes, and this check is the guard.
- LLM processing and stored embeddings stay switchable (`TEXT_LLM_ENABLED`,
  `EMBEDDINGS_ENABLED`). Every bulk run needs a cost estimate approved first.
- Caveat: Transfermarkt values are crowd-sourced estimates, not transfer fees.

## Baseline features (as of the snapshot date)
- Age, position, league, current log value
- Value change over the previous 12 months
- Minutes, appearances, goals + assists per 90 in the previous season
- Share of the team's minutes played
- Club strength proxy: total squad value at the snapshot
- Club moves in the previous 12 months

## Planned additions
- M3a: a stats feature pass first (pre-registered in docs/RESEARCH_LOG.md):
  position percentiles, availability proxy, discipline, in-match injury records.
  The best set on validation becomes the new baseline.
- M3a: LLM-extracted Wikipedia signals (injuries, contracts, loans and transfers,
  each with an event date), joined point-in-time and kept only if an ablation
  against the new baseline shows they help (2013–2024).

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
- **GDELT news attention (out of scope for v1, 2026-10-01).** Per-player mention
  counts, tone and themes from the GDELT Global Knowledge Graph (`DATE < t`).
  License: unrestricted use with a citation and link to https://www.gdeltproject.org/.
  Needs a sports-context filter (39.8% of name matches in a sample had sports
  context) and BigQuery (new Google Cloud account). Windows from 2016 only.
  Evaluation: `reports/m3_sources.md`.
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
chosen leagues; noise in crowd-sourced values; Wikipedia edits lag real events
and mix new events with rewritten older text (event dates needed).
