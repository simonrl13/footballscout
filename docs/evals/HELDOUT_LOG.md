# Held-out eval runs

Appended by `python -m scout.evals.run --set heldout --confirm-heldout --reason "..."`. The held-out set is used only
to set thresholds; graders are not changed in response to its answers (a fix found there goes into the dev set and
the next held-out questions).

| Date | Commit | Model | Cases | Pass rate | Reason |
|---|---|---|---|---|---|
