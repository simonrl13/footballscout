# Extracted contract end dates vs Transfermarkt (as of 12 June 2026)

Transfermarkt: `players.contract_expiration_date` (Kaggle dump of 12 June 2026). Extracted: the latest contract end date stated in any Wikipedia document published before 12 June 2026 (extract-v3). The newest extracted document is from 2024-08-31: the June 2026 revisions were fetched for retrieval but never extracted. No API calls.

**Read this as a staleness measure, not an extraction-accuracy measure.** The extracted dates stop at August 2024 while Transfermarkt's are from June 2026, so most disagreements are contracts signed or extended in between. A fair accuracy check needs the June 2026 demo pages extracted (follow-up, about $0.30; not run).

| | Players |
|---|---|
| Demo players | 2649 |
| Transfermarkt expiry known | 2426 |
| Extracted end date known | 653 |
| Both (coverage of Transfermarkt's) | 587/2426 (24%, CI 23%–26%) |

| Extracted end date | n | Same year as Transfermarkt | Within 1 year |
|---|---|---|---|
| all | 587 | 107/587 (18%, CI 15%–22%) | 149/587 (25%, CI 22%–29%) |
| still in the future on 12 June 2026 | 262 | 107/262 (41%, CI 35%–47%) | 149/262 (57%, CI 51%–63%) |
| already past on 12 June 2026 (stale) | 325 | 0/325 (0%, CI 0%–1%) | 0/325 (0%, CI 0%–1%) |
