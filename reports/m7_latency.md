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
request), then 5 warm requests 16 s apart, then the smoke set. The first 6 questions of the first run, in the same
order. Cost US$0.0057. The client clock had drifted to about 2.2 s behind Neon's, so admission and end-of-stream
are reported together (total minus the stages measured on one clock).

| Stage | Cold before | Cold after | Warm before (n = 9) | Warm after (n = 5) |
|---|---|---|---|---|
| Admission + check/end of stream | 10.12 | 17.10 | 0.60 (0.59–0.67) | 0.72 (0.70–0.93) |
| Before the first model call | 9.02 | **0.47** | 0.22 (0.20–0.24) | 0.25 (0.24–0.26) |
| Model calls (sum) | 4.08 (3 calls) | 3.61 (2 calls) | 3.38 (3.21–6.57) | 5.12 (4.61–7.14), 2–4 calls |
| Tools between model calls | 0.21 | 0.19 | 0.06 (0.06–0.13) | 0.11 (0.06–0.28) |
| **First event** | 20.33 | 18.91 | 1.89 (1.67–2.43) | 2.14 (1.77–3.07) |
| **Total** | **23.43** | **21.37** | **4.29 (4.13–7.44)** | **6.57 (5.64–8.29)** |

- **The first-`/ask` stall is gone:** before the first model call, 9.02 s → 0.47 s cold (and unchanged warm).
- **Bytecode compilation works:** in the production image at 1 CPU, importing the app (now including the Anthropic SDK
  and the agent) takes 3.86 s, against 7.43 s for the same imports in the previous image; 4,297 `.pyc` files ship.
- **But the cold total improved by only 2.1 s:** admission (instance start until the request is counted) grew from
  about 9 s to about 16 s. The traces can't say why. Imports are ruled out by the measurement above; the candidates are
  pulling the image for a revision that had never scaled from zero, Neon waking from suspension, and cold-start
  variance (one cold sample each). Cloud Run's startup log lines would separate them. Until then, cold starts are
  about 20 s and the docs say so.
- **Warm:** non-model time is unchanged (0.25 s before the first call, about 0.7 s around the edges); the higher
  warm median comes from the model: the same questions took more calls this time (2–4 against 2–3) and longer
  answers. Warm requests stay at or near the 6 s target (median 6.57 s, n = 5); the model calls dominate.
