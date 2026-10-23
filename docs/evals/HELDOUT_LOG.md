# Held-out eval runs

Appended by `python -m scout.evals.run --set heldout --confirm-heldout --reason "..."`. The held-out set is used only
to set thresholds; graders are not changed in response to its answers (a fix found there goes into the dev set and
the next held-out questions).

| Date | Commit | Model | Cases | Pass rate | Reason |
|---|---|---|---|---|---|
| 2026-10-13 14:56 | `be92cd3` | `claude-haiku-5-5` | 20 | 95% automatic (5 cases await the owner's review) | first held-out run: 20 questions (10 Claude, 10 owner) written before running; thresholds proposed from it |
| 2026-10-23 | `be92cd3` code, check from PR "number-check direction" | — (no model calls) | 20 | not a run: replay of the recorded 2026-10-13 answers from the response cache; 0 of 20 released answers flagged by the new direction check | fix 2 validation (owner, 2026-10-23); no tuning, thresholds untouched |
