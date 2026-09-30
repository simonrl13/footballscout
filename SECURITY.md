# Security

Status: **partial (M2)**. This file is completed in M6 and updated whenever the attack surface changes (a new endpoint, tool or data source).

## Reporting a vulnerability
Please don't open a public issue. Use GitHub's private vulnerability reporting on this repository ("Security" tab → "Report a vulnerability"). You should get a reply within 7 days.

## What is protected
- **API keys** (Anthropic, Voyage, Guardian) and database credentials: only in `.env` (gitignored) or the host's secret store.
- **The database:** player/valuation data (public CC0 source), news metadata and extracted signals, embeddings, traces.
- **Spend:** LLM and embedding usage (US$2/day cap on public endpoints; bulk jobs need manual approval).
- **Third-party content terms:** Guardian article text (see below).

## Likely attackers and entry points
| Attacker | Entry point |
|---|---|
| Anonymous internet user | Public chat/API endpoints (M4+): prompt injection, abuse of spend, SQL-injection attempts through tool arguments |
| Malicious or compromised content | News articles retrieved into the agent's context (indirect prompt injection) |
| Supply chain | Python packages, GitHub Actions, Docker base images |
| Local network | Postgres port (bound to 127.0.0.1 only) |

## Controls
| Control | Status | OWASP LLM / Agentic ID* |
|---|---|---|
| Secrets only in `.env`; gitleaks pre-commit + CI; no secrets in logs or prompts | M1 | LLM02, LLM07 |
| Postgres bound to 127.0.0.1; password from `.env` | M1 | — |
| DB roles: `scout_loader` (write) and `scout_reader` (read-only, used by the API, agent and MCP) | M1 (test in M5) | LLM06, ASI03 |
| Parameterized SQL; identifiers via `psycopg.sql.Identifier`; CSV columns allow-listed against the schema | M1 | LLM05, ASI02 |
| Lockfile, pip-audit, Dependabot (uv, Actions, Docker), CodeQL (python + actions); Actions pinned by commit SHA and Docker images by digest; new dependencies need approval + registry vetting | M1–M2 | LLM03, ASI04 |
| Ruleset on `main`: no force-push/deletion; tests, audit, secrets and CodeQL must pass; CodeQL high-severity alerts block merges (admins can bypass for direct pushes) | M2 | LLM03 |
| MLflow in its own database with its own role (`scout_mlflow`), no access to project data | M2 | LLM06 |
| Pydantic validation and limits on every endpoint and tool | M4 | LLM06, ASI02 |
| Retrieved news treated as untrusted data; injection eval cases; attempts logged | M4–M5 | LLM01, ASI01, ASI06 |
| Numbers in answers must come from tool outputs (post-check, violations logged) | M4 | LLM09, ASI09 |
| Rate limits; US$2/day spend cap in code; max tool iterations and `max_tokens` | M4–M6 | LLM10, ASI08 |
| Read-only MCP tools | M5 | LLM06, ASI02 |

\*IDs are tentative and are verified against the published OWASP lists before M6.

## Guardian content rules
- Persist only article IDs, URLs, dates, tags and extracted signals.
- Article text is never persisted beyond 24 hours; a purge job enforces this and a test proves it.
- Text is fetched live when an answer or citation needs it, cached for at most 24 hours.
- At most 500 API calls per day.
- LLM processing of article text (`NEWS_LLM_ENABLED`) and stored embeddings (`EMBEDDINGS_ENABLED`) can each be switched off, pending confirmation of the terms.

## What is tested and how
- **Secrets (M1):** gitleaks runs as a pre-commit hook and in CI over the full git history. Verified 2026-09-30 by staging a planted, randomly generated `ghp_…` token: the commit was blocked (rule `github-pat`). The file was then removed and never committed.
- **Dependencies (M1):** `pip-audit --strict` over the locked requirements (local run 2026-09-30: no known vulnerabilities) runs in CI on every push and PR. Dependabot covers `uv` and GitHub Actions weekly.
- **SQL (M1):** `load.py` rejects any CSV column not present in the table created by `db/schema.sql` and builds identifiers with `psycopg.sql.Identifier`; no SQL is built with f-strings.
- **DB roles (M1, runs when the DB is up):** `tests/test_db.py` checks that `scout_reader` can read but gets `InsufficientPrivilege` for INSERT, UPDATE, DELETE, CREATE and DROP.
- **Claude Code guardrails (M1):** `.claude/settings.json` denies reading or editing `.env` files and key files, and requires approval for package installs and network commands. This is a guardrail for the coding assistant, not a hard boundary: the deny list can't cover every shell command that could print a file.
- **Guardian rules (M2):** `tests/test_news.py`:
  - stored rows contain no article text, even when the API returns it;
  - text older than 24 h is never returned and is deleted by the purge;
  - the daily call budget can't be exceeded;
  - the backfill resumes without re-fetching.
- **CodeQL (M2):** first scan found 10 alerts (3 medium supply-chain: Actions pinned by tag; 7 code quality). All fixed; 0 open.
- M5 adds prompt-injection evals and agent-level read-only tests.

## Known limitations
- The owner can bypass the `main` ruleset for direct pushes, so its checks bind PRs (incl. Dependabot) and are not a hard gate on the owner's pushes.
- The 24-hour text cache is written with the loader role for now. M4 adds a narrow writer role before any public endpoint can trigger text fetches.
- `.claude/settings.json` guards the coding assistant, not the machine: shell commands outside its deny list could still read `.env`.
- The rest is completed in M6.
