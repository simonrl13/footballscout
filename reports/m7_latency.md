# M7 production latency: cold vs warm (2026-10-21)

The 6 s target (median latency per question, `THRESHOLDS` in `scout/evals/run.py`) was set on in-process held-out runs
(median 3.8 s, `reports/evals_heldout.md`). On Cloud Run one number hides two very different cases, so both are reported.

**Setup.** Deployed demo at commit `e486c33` (public mode, max 2 instances, min 0, 1 CPU, 512 MiB, startup CPU boost
already on), Neon Frankfurt, `claude-haiku-5-5` at medium effort. 10 sequential `/ask` questions (player forecasts,
values, one comparison, two list questions), starts 16 s apart (4 per minute, within the public limits), the first
after 27 minutes without traffic. Cost US$0.0080 in total. Times are seconds, measured on the client
(`first event`, `total`) and split with the Neon trace rows (`agent_requests`, `agent_calls`); the client clock was
about 0.1–0.2 s ahead of Neon's, so stage boundaries are ±0.2 s.

| Stage | Cold (request 1) | Warm (requests 2–10): median (min–max) |
|---|---|---|
| Admission: client → rate-limit row (container start, app import, tracer connect, limit queries) | 8.91 | ≈ 0 (clock skew) |
| Before the first model call (reader + tracer connects, spend check, first-use imports) | 9.02 | 0.22 (0.20–0.24) |
| Model calls (sum) | 4.08 (3 calls) | 3.38 (3.21–6.57), 2–3 calls |
| Tools between model calls | 0.21 | 0.06 (0.06–0.13) |
| Number/citation check and end of stream | 1.21 | 0.75 (0.72–0.78) |
| **First event** | 20.33 | 1.89 (1.67–2.43) |
| **Total** | **23.43** | **4.29 (4.13–7.44)** |

- Warm requests meet the 6 s target (7 of 9 under 6 s); the model calls are a median 80% of their time (78–88%).
- A cold request takes about 23 s. About 9 s go to starting the instance (3.6 s of it is importing the app, measured in
  the production image at 1 CPU; the rest includes Neon waking from suspension), and about 9 s more to the first
  `/ask` on a fresh instance, which imported the Anthropic SDK and the agent module on first use. The smoke-test
  question earlier the same day (a warm instance, but its first `/ask`) showed the same 9 s stall.
- The runtime user cannot write `__pycache__`, so every cold start compiled every module from source.

**Fixes (PR "M7 review fixes").** Bytecode compiled at build time (`UV_COMPILE_BYTECODE=1`), and the Anthropic SDK and
agent imported at app start instead of on the first `/ask`. Startup CPU boost was already on for the measurement
above, so no gain is credited to it. `min-instances=1` was not adopted: an always-on instance would cost more than the
project budget. The re-measurement after the fixes are deployed is added below with the same protocol.

## After the fixes (2026-10-22, commit `2159956`)
Owner's protocol: one cold request at 02:45 UTC after 32 minutes without traffic (the deploy's own check was the last
request), then 5 warm requests 16 s apart, then the smoke set. The first 6 questions of the first run, identical and in
the same order. Cost US$0.0057.

**Cold: about 21–23 s** with #51 (about 19 s after the slim image, below). Neon is ruled out; the extra time is
container startup before uvicorn is ready.
- The first-`/ask` stall is gone: before the first model call, 9.02 s → 0.47 s.
- Cloud Run's startup logs (owner, 2026-10-22), "Starting new instance" to the startup probe passing: 7.9, 8.3, 7.3 and
  8.4 s for the image before #51 (2 rollouts, 2 cold starts); 12.9 s (rollout, 02:12 UTC) and 15.4 s (the cold
  request, 02:45 UTC) for the #51 image. The probe passed at 02:45:17.1 and almost nothing remained between uvicorn
  being ready and the request being admitted, so Neon waking up is not the cause. About 2 s of the increase is the
  Anthropic SDK and agent import moved to startup, by design; the rest is open (see the investigation below).
- Total 21.37 s (first event 18.91 s); model calls 3.61 s (2 calls).

**Warm: median 6.6 s (n = 5), model calls a median 82% of the time (78–86%).** Non-model time is unchanged (before
the first model call 0.25 s; admission and end of stream about 0.7 s). No regression is claimed from 5 requests.

Same 5 questions, before (2026-10-21, image before #51) and after (calls from the `agent_calls` trace rows):

| # | Before: model calls, tools, total | After: model calls, tools, total |
|---|---|---|
| 2 | 2, search_players, 4.18 s | 4, search_players + predict_value_change (plus one number-check retry), 8.29 s |
| 3 | 2, search_players, 4.13 s | 3, search_players + predict_value_change, 5.92 s |
| 4 | 2, search_players, 7.44 s | 2, search_players, 6.57 s |
| 5 | 3, search_players + predict_value_change, 5.29 s | 2, search_players, 5.64 s |
| 6 | 3, search_players × 2 + compare_players, 6.71 s | 3, search_players × 2 + compare_players, 6.86 s |

12 model calls and 8 tool calls before, 14 and 9 after: the model chose different paths on two questions and one
answer was retried by the number check. This is model variation on identical questions, not a code change (the
agent and prompt did not change in #51).

**Startup investigation (2026-10-22, read-only, local rebuilds of both commits at 1 CPU / 512 MiB):**
- Image size: 484.0 → 569.4 MB uncompressed (Docker's figure), 111.0 → 129.4 MB gzipped. Filesystem content differs only
  in `/app/.venv`: +54.1 MB, all `.pyc` (4,297 files; 18.4 MB gzipped, i.e. the whole compressed increase).
- The `.pyc` files are used: on a read-only filesystem, importing the app loads 2,529 modules from bytecode with none
  stale; 102 are still compiled from source at every start (88 standard-library modules, which the slim base ships
  without bytecode, and 14 of ours, installed editable).
- Locally the #51 image starts faster (container start to the first `/health`: 2.7–3.0 s against 3.4–4.2 s, 3 runs
  each), so the Cloud Run increase isn't reproduced once the image is local; the leading hypothesis is fetching and
  unpacking the larger image on a new instance. Not proven.
- Only 2,447 of the 4,297 compiled files (6.7 of 18.4 MB gzipped) are imported at startup. The image also carries the
  uv binary (56 MB, 22.1 MB gzipped), unused at runtime except to launch uvicorn, and pandas + numpy (135 MB, 40.2 MB
  gzipped, about 0.44 s of import at 1 CPU), loaded only because `scout.agent.tools` imports `fold` from
  `scout/text/linker.py`, which imports pandas.

## Startup fixes (2026-10-22, PR "M7 slim image")
Three changes, ranked by the investigation above: pandas and numpy out of the image (`fold()` moved to the stdlib-only
`scout/text/fold.py`, pandas moved to the local group), uv only at build time (mounted, not copied; uvicorn starts from
the venv; the project installed non-editable), and bytecode for exactly what startup imports (a build step starts the
server once as root and calls `/health`; replaces `UV_COMPILE_BYTECODE`). Local rebuilds of each commit, measured the
same way on the same machine:

| | Before #51 (`e486c33`) | #51 (`2159956`) | This PR |
|---|---|---|---|
| Image, uncompressed (Docker's figure) | 484.0 MB | 569.4 MB | **299.3 MB** |
| Image, gzipped (`docker save \| gzip -1`) | 111.0 MB | 129.4 MB | **65.7 MB** |
| Filesystem content (`du`) | 332.3 MB | 386.5 MB | **192.6 MB** |
| Local start to first `/health` (1 CPU, 512 MiB; 3 runs) | 3.66, 4.69, 3.86 s | 2.82, 4.17, 2.82 s | **2.19, 1.95, 2.49 s** |
| Modules compiled from source at start (`python -v`, runtime user, read-only filesystem) | 765 | 115 | **0** |

- On a read-only filesystem as the runtime user, startup loads 2,371 modules from bytecode and compiles none; the
  container runs read-only.

## On Cloud Run after the slim image (2026-10-22, commit `b4fb275`)
**Startup logs** (owner, "Starting new instance" → startup probe passed):

| Image | Rollout | Cold start |
|---|---|---|
| Before #51 | 7.3–8.4 s (4 starts: 2 rollouts, 2 cold) | |
| #51 | 12.9 s (02:12 UTC) | 15.4 s (02:45 UTC) |
| #53, slim | 9.6 s (18:44 UTC) | 12.7 s (19:16 UTC) |

**One cold `/ask`** at 19:16:00 UTC after 32 idle minutes (the Kane question used for every cold run; US$0.0006).
The client and Neon clocks disagreed by about a second, so admission and end of stream are given together:

| Stage (s) | Before #51 | #51 | #53, slim |
|---|---|---|---|
| Admission + end of stream (instance start, admission, checks, last bytes) | 10.12 | 17.10 | 15.37 |
| Before the first model call | 9.02 | 0.47 | 0.47 |
| **Non-model, non-tool time (sum of the two)** | **19.14** | **17.57** | **15.84** |
| Model calls | 4.08 (3) | 3.61 (2) | 3.10 (2) |
| Tools | 0.21 | 0.19 | 0.19 |
| First event | 20.33 | 18.91 | 17.00 |
| **Total** | **23.43** | **21.37** | **19.13** |

- The smaller image helped modestly: about 3 s off startup in the logs (12.9–15.4 s → 9.6–12.7 s) and 1.7 s off the
  non-model time of the cold `/ask`, while the image halved (129.4 → 65.7 MB gzipped).
- Startup is still slower than before #51 (7.3–8.4 s) because #51 moved the Anthropic SDK and agent import from the
  first `/ask` into startup. Before #51 that import cost about 9 s inside the first request; the non-model time of a
  cold `/ask` has fallen at each step (19.1 → 17.6 → 15.8 s), so the import was moved rather than added. On Cloud
  Run's CPU it takes much longer than the 2.1 s measured locally. Likely, not proven: one sample per image.
- **Decision (owner, 2026-10-22): stop optimizing.** A cold request takes about 19 s; users are warned (README text next
  to the link, and the planned demo page). No `min-instances`. No further latency work.
