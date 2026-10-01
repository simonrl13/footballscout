# M3 source evaluation: Wikipedia/Wikidata and GDELT (2026-10-01)

Read-only evaluation after dropping the Guardian. Methods: license and policy pages, plus small samples:
- 1 Wikidata SPARQL query;
- 258 Wikipedia API requests;
- 4 GDELT 15-minute GKG files.

No LLM or embedding calls were made. **"Measured"** = from these samples; **"estimate"** = derived, with the assumptions stated.

## Summary

| | Wikipedia revisions + Wikidata | GDELT GKG |
|---|---|---|
| Track | LLM extraction (injury, transfer, contract, manager signals with dates) | No LLM: mention counts, tone, themes |
| License | Text CC BY-SA 4.0 (+ GFDL); Wikidata CC0. No AI/ML restriction in the Terms of Use | "Unlimited and unrestricted use … academic, commercial, or governmental"; citation + link required |
| Coverage of our snapshot players | **99.9%** mapped via P2446 and have an enwiki page; page existed at t in **100%** of a 200-player sample | Name match in 1.78% of all GKG records (one deadline-week hour); ambiguity 2.0%; **only 39.8% of matched records have sports context** |
| Years | 2013–2024 (all) | GKG 2.0 starts Feb 2015, so a full 365-day window exists only for snapshots 2016–2024 |
| Volume / time | about 63–71k API requests serial, about 12–20 h (estimate) | BigQuery: about 0.2–0.65 TB per full pass (estimate), within the 1 TiB/month free tier. Raw files: about 3.3 TB download, about 7–8 days |
| Money | LLM (Haiku 4.5, Batch): **about $24, range $15–45** (estimate) | BigQuery: about $0–4 (estimate; needs a dry run); new external service (GCP) |
| Main risk | Diffs mix old rewritten text with new events, so event dates are needed; Wikipedia lags real events | Name-only matching precision; needs a sports-context filter and a labelled precision check |

**Recommendation if only one: Wikipedia.** It is the track that answers the research question (LLM-extracted signals), covers all 12 snapshot years and all 7 leagues, has clear license terms, and doubles as citable text for the M4 agent (links to exact revisions). GDELT is a cheaper "attention" baseline, but its matching precision is unproven and it adds a GCP dependency.

---

## A. Wikipedia revision history + Wikidata

### License and attribution
- **Wikipedia text:** CC BY-SA 4.0 (text before 15 June 2009 also GFDL). Reuse requires:
  - a hyperlink or URL to the page(s) reused;
  - credit to the authors (the page history satisfies this);
  - a licence notice;
  - modifications must be indicated, and adaptations licensed CC BY-SA. [Reusing Wikipedia content](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content)
- **Wikidata (structured data):** CC0, no attribution required. [Wikidata:Licensing](https://www.wikidata.org/wiki/Wikidata:Licensing)
- **Terms of Use:** no restriction on AI or ML processing. They prohibit "placing an undue burden on an API" and automated use that is "abusive or disruptive". [Terms of Use](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use)

### API policy
- **User-Agent** must identify the tool and give contact info, e.g. `ScoutResearchBot/0.1 (https://github.com/simonrl13/footballscout; …)`. [User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy)
- **Action API, unauthenticated:** "keep the concurrency of your requests to 1 at a time, and below 5 requests per second overall". If a request takes more than 1 s, wait 5 s. [Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy)
- **Etiquette:** send requests in series, use `maxlag`, use gzip, and cache results. [API:Etiquette](https://www.mediawiki.org/wiki/API:Etiquette)
- **Our sample:** 258 serial requests at 0.41 s mean latency, plus a 0.25 s pause between requests, with `maxlag=5`, so well inside the limits.

### Coverage (measured)
- **Mapping:** Wikidata items with P2446 (Transfermarkt player ID): 220,584, of which 153,340 have an English Wikipedia page.
- **Our population:** 8,190 distinct players in the 27,330 labelled snapshots. 99.9% are mapped, 99.9% have an enwiki page, and 2 map to more than one Wikidata item.
- **By year:** 99.7% (2013) to 100% in every other year. **By league:** 100% everywhere except Liga Portugal (99.6% with a page).
- **Page age:** in a random sample of 200 players (631 snapshots), the page existed at t in 100% of snapshots, and existed at t − 365 days in 94.3–100% by year.

### Signal quality (measured, 20 random players, diff of revision at t − 365 → revision at t)
- **Size:** median 2,984 characters of added wikitext per year (one page unchanged; one page without a revision at t − 365).
- **Keyword hits:** transfer terms in 65% of diffs, contract terms in 40%, injury terms in 20%.
- **Real dated events do appear.** "On 13 January 2017, Upamecano joined RB Leipzig…"; "On 7 September 2020, Sánchez further extended his contract until 2025"; "In June 2023, Huijsen renewed his contract with Juventus until 2027".
- **Noise:** diffs often contain **older text that was rewritten or reformatted**. Kyle Walker's 2013 diff includes 2009 events; Bamford's 2021 diff includes a 2013 injury. Infobox and citation markup also produce false keyword hits.
- **Consequences for the design:**
  1. Strip markup and citations first.
  2. The LLM must return the **event date** stated in the text, and only events dated in (t − 365, t] count.
  3. Quote verification stays.
- **No leakage risk:** the revision in force at t contains only text written by t. The real limitations are lag (events added late) and recall.

### Volume, time and cost (estimates)
- **Requests:** one revision lookup per (player, date) for t and t − 365, about 35.5k (27,330 + 8,190 first years), plus one parse or diff per snapshot, about 27–35k. That's about 63–71k serial requests, about 12–20 h in the background.
- **Bulk alternative:** full-history dumps are far larger, so the API is appropriate at this volume.
- **LLM cost:** mean added text in the sample was about 7,960 characters with markup. Assuming about 50% is removed by stripping markup, that's about 1,000 tokens per document. `estimate_cost(27,330 docs, 714 words, 1 player, claude-haiku-4-5)` gives **about $24 on the Batch API** (37.3M input, 2.2M output tokens). The range is $15–45 depending on real text size.
- **Pilot first:** 100 documents, under $1, to measure the real size, quote-verification drop rate and precision.

---

## B. GDELT Global Knowledge Graph (GKG 2.x)

### License and citation
- "Unlimited and unrestricted use for any academic, commercial, or governmental use of any kind without fee". Any use or redistribution "must include a citation to the GDELT Project and a link to this website" (https://www.gdeltproject.org/). [About GDELT](https://www.gdeltproject.org/about.html)
- GDELT provides metadata (persons, themes, tone, URL), not article text. Source articles stay third-party content, so we would link to them, never copy text.

### Access route and cost
- **Raw files (measured, 2019-08-08 12:00–13:00):** about 8.5 MB zipped / 26.9 MB unzipped per 15-minute file, about 1.7 s per download. 2015–2026 is about 385k files and **about 3.3 TB zipped, about 7–8 days** of downloading (estimate, at 2019 volume).
- **BigQuery** (`gdelt-bq.gdeltv2.gkg_partitioned`, partitioned by day; 3.6 TB at 353M records in an early GDELT post, and much larger now):
  - Price: $6.25 per TiB scanned, first 1 TiB per month free. [BigQuery pricing](https://cloud.google.com/bigquery/pricing)
  - The columns we need, measured as a share of a GKG row's bytes: DATE 0.1%, URL 0.9%, V1Persons 0.4%, V1.5Tone 0.8% (2.2% together), plus V1Themes 4.3%.
  - At about 0.9 TB of raw GKG per year (2019 rate, about 10 TB for 2015–2026), one full pass scans about **0.2–0.65 TB**: about $0–4.
  - Estimate only; a dry run gives the exact bytes. Partitions on `_PARTITIONTIME` can limit each query to the needed days. [Partitioned GDELT tables](https://blog.gdeltproject.org/announcing-partitioned-gdelt-bigquery-tables/), [GKG 2.0 sample queries](https://blog.gdeltproject.org/google-bigquery-gkg-2-0-sample-queries/)
- **Recommendation for this track:** BigQuery, which needs a GCP project and billing account: **a new external service, so it needs your approval**.

### Coverage and name matching (measured, 4 files = 9,039 records)
- **Names:** 28,119 person mentions, 14,367 distinct names. Our full-name index (players valued in the 2 years before the date) matched **161 records (1.78%)**: 247 distinct players, 442 mentions. 2.0% of matched mentions are names shared by more than one active player.
- **Precision problem:** only **39.8%** of matched records had a sports URL or theme. Frequent matches include real footballers (Cristiano Ronaldo, Paulo Dybala, Romelu Lukaku, Lionel Messi) but also likely namesakes (e.g. "andre anderson", 35 mentions). GDELT stores names lowercase, without context.
- **Required before use:**
  - a sports-context filter (URL/source/themes, or a club name in the organizations field);
  - our club-at-date rule for shared names;
  - a hand-labelled precision check of 100 matched records (target ≥ 0.95, as for the linker).
- **Years:** GKG 2.0 begins in February 2015, so a full 365-day window exists only for snapshots from 2016. Any comparison must therefore use 2016–2024 snapshots for all arms.

### Point-in-time feature design (proposed)
- A record is available at its GKG `DATE`, the 15-minute window when GDELT processed it. GKG rows are not revised afterwards, so a record counts for snapshot t only if `DATE < t`.
- **Per (player, t):** matched record counts for [t − 90 d, t) and [t − 365 d, t); mean tone and share of negative-tone records over 365 d; counts of a few theme families (e.g. injury/health, crime/legal, transfer/economy) over 365 d; and the trend (count over 90 d vs the previous 275 d).
- **Tests:** the same leakage pattern as the other features (append future records → features at t unchanged), plus a linker test that a namesake without sports context is not counted.

---

## Revised M3 and effort

| Track | Steps | Effort (h) | Needs your approval |
|---|---|---|---|
| **M3a Wikipedia** | Wikidata mapping table · revision fetcher (serial, compliant User-Agent) · plain text (markup stripped) and new-text-per-year · prompt v2 (adds event date, keeps verbatim quotes) · pilot on 100 docs · full extraction · point-in-time features + leakage tests · ablation on validation · labelled precision on 100 signals | 16–20 (+1.5 your labelling) | the fetch (about 12–20 h background, free); pilot (< $1); full run (about $15–45, after the pilot) |
| **M3b GDELT** | GCP/BigQuery setup + dry run · extraction query for our names (partitioned) · linking with sports filter + club-at-date · 100-record precision labelling · point-in-time features (counts, tone, themes) + leakage tests · ablation | 12–15 (+1 your labelling) | GCP account (new service); query cost after the dry run (expected $0–4) |
| **Comparison** | baseline vs +GDELT vs +Wikipedia vs both. All arms on 2016–2024 snapshots (GDELT window); Wikipedia alone also on 2013–2024. Validation only during development; one logged test run at the end | 3–4 | — |
