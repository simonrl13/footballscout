# Security

Status: **partial (M2)**. This file is completed in M6 and updated whenever the attack surface changes (a new endpoint, tool or data source).

## Reporting a vulnerability
Please don't open a public issue. Use GitHub's private vulnerability reporting on this repository ("Security" tab → "Report a vulnerability"). You should get a reply within 7 days.

## What is protected
- **API keys** (Anthropic, Voyage; GCP if approved) and database credentials: only in `.env` (gitignored) or the host's secret store.
- **The database:** player/valuation data (public CC0 source), public-text documents (Wikipedia revisions under CC BY-SA) and extracted signals, embeddings, traces.
- **Spend:** LLM and embedding usage (US$2/day cap on public endpoints; bulk jobs need manual approval).
- **Third-party content terms:** Wikipedia attribution/share-alike (see below).

## Secrets
- **Local Anthropic API key:**
  - Lives only in `.env`, which is gitignored and never read by Claude Code (`.claude/settings.json` deny rules).
  - Belongs to a **dedicated "scout" workspace with its own monthly spending limit**.
  - **Expires every 90 days and is rotated manually:** create a new key, update `.env`, revoke the old one.
- **Database passwords** (admin, `scout_loader`, `scout_reader`, `scout_mlflow`): generated random values in `.env`. The app never connects as admin.
- **`.env` hygiene:** after editing, run `uv run python -m scout.check_env`. It checks the syntax and prints only line numbers and the kind of problem, never names or values.
- **Planned for deploy and CI (M7):** identity federation instead of static keys. Short-lived tokens are issued from GitHub Actions OIDC or the AWS instance's identity, so no long-lived API key sits in CI secrets or on the server.

### Incident log
- **2026-10-01: Anthropic API key exposed in a session transcript.**
  - **What happened:** a `.env` line was missing its `=` (`ANTHROPIC_API_KEY<value>`). `uv run --env-file .env` could not parse it, and its warning printed the whole line, value included, into Claude Code's tool output. The parse failure also stopped every later variable from loading.
  - **Response:** the owner was asked to revoke the key and issue a new one (status: pending confirmation). `scout/check_env.py` was added so `.env` syntax can be checked without printing content.
  - **Not affected:** git (`.env` is gitignored; gitleaks found nothing), CI and the deployed services (none exist yet).

## Likely attackers and entry points
| Attacker | Entry point |
|---|---|
| Anonymous internet user | Public chat/API endpoints (M4+): prompt injection, abuse of spend, SQL-injection attempts through tool arguments |
| Malicious or compromised content | Wikipedia revisions (anyone can edit, incl. vandalism) and linked articles retrieved into the agent's or extractor's context (indirect prompt injection, poisoning) |
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
| Ruleset on `main` (no bypass, since M3): PRs required (squash only); no force-push/deletion; tests, audit, secrets and CodeQL must pass on an up-to-date branch; CodeQL high-severity alerts block merges | M2–M3 | LLM03 |
| MLflow in its own database with its own role (`scout_mlflow`), no access to project data | M2 | LLM06 |
| Pydantic validation and limits on every endpoint and tool | M4 | LLM06, ASI02 |
| Retrieved news treated as untrusted data; injection eval cases; attempts logged | M4–M5 | LLM01, ASI01, ASI06 |
| Numbers in answers must come from tool outputs (post-check, violations logged) | M4 | LLM09, ASI09 |
| Rate limits; US$2/day spend cap in code; max tool iterations and `max_tokens` | M4–M6 | LLM10, ASI08 |
| Read-only MCP tools | M5 | LLM06, ASI02 |
| Text pipeline gates: LLM extraction (`TEXT_LLM_ENABLED` + approved cost); Wikimedia API politeness (serial, < 5/s, `maxlag`, User-Agent) | M3 | LLM10 |
| Extraction prompt treats documents as untrusted data; outputs constrained by JSON schema; every signal needs a verbatim quote (and an in-window event date for Wikipedia) or it is dropped | M3 | LLM01, LLM04, LLM09 |

\*IDs are tentative and are verified against the published OWASP lists before M6.

## Public-text source rules
- No Guardian content: the integration was removed on 2026-10-01 (its terms prohibit AI-related use). A database check confirmed that nothing from it was ever stored.
- **Wikipedia fetching:** Action API only, serial requests (< 5/s), `maxlag=5`, a 5 s wait after any response slower than 1 s, User-Agent `ScoutResearchBot/0.1 (https://github.com/simonrl13/footballscout; …)`; Wikidata SPARQL via POST in chunks of 500 IDs.
- **Wikipedia (CC BY-SA 4.0):**
  - Every excerpt shown links to the exact revision and carries the license notice and a page-history link.
  - Excerpts are short (≤ 300 characters, or a ≤ 2-sentence summary).
  - Revision text is stored with its URL.
- **Wikidata:** CC0.
- **GDELT:** cite and link gdeltproject.org wherever its data is used. Metadata only; third-party articles are linked, never copied.
- LLM processing (`TEXT_LLM_ENABLED`) and stored embeddings (`EMBEDDINGS_ENABLED`) stay switchable, and each bulk run needs an approved cost estimate.

## What is tested and how
- **Secrets (M1):** gitleaks runs as a pre-commit hook and in CI over the full git history. Verified 2026-09-30 by staging a planted, randomly generated `ghp_…` token: the commit was blocked (rule `github-pat`). The file was then removed and never committed.
- **Dependencies (M1):** `pip-audit --strict` over the locked requirements (local run 2026-09-30: no known vulnerabilities) runs in CI on every push and PR. Dependabot covers `uv` and GitHub Actions weekly.
- **SQL (M1):** `load.py` rejects any CSV column not present in the table created by `db/schema.sql` and builds identifiers with `psycopg.sql.Identifier`; no SQL is built with f-strings.
- **DB roles (M1, runs when the DB is up):** `tests/test_db.py` checks that `scout_reader` can read but gets `InsufficientPrivilege` for INSERT, UPDATE, DELETE, CREATE and DROP.
- **Claude Code guardrails (M1):** `.claude/settings.json` denies reading or editing `.env` files and key files, and requires approval for package installs and network commands. This is a guardrail for the coding assistant, not a hard boundary: the deny list can't cover every shell command that could print a file.
- **Guardian removal (M3):** `tests/test_labeling_extract.py::test_old_guardian_tables_are_gone`. The M2 Guardian tests were removed with the integration.
- **CodeQL (M2):** first scan found 10 alerts (3 medium supply-chain: Actions pinned by tag; 7 code quality). All fixed; 0 open.
- **Wikipedia (M3a):**
  - `tests/test_wikipedia.py`: markup is stripped and the User-Agent carries contact info.
  - `tests/test_extract_wiki.py`: events are dropped if the quote isn't verbatim, the date is year-only, outside the window, or not written in the quote's sentence; rumours are not a type.
  - `tests/test_wiki_run.py`: end-to-end with a fake Batch client.
- **Text pipeline (M3):**
  - `tests/test_labeling_extract.py`: the extraction runner verifies quotes and caches by prompt version.
  - `tests/test_extract.py`: invented or paraphrased quotes are dropped, and the switch and model come from env.
  - `tests/test_text_features.py`: documents available on or after t change nothing.
- M5 adds prompt-injection evals and agent-level read-only tests.

## Known limitations
- Text documents are written with the loader role. The API and agent will only read them (`scout_reader`).
- `.claude/settings.json` guards the coding assistant, not the machine: shell commands outside its deny list could still read `.env`. Tools that load `.env` (e.g. `uv --env-file`) may echo malformed lines in warnings (see the incident log).
- The rest is completed in M6.
