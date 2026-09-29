# Security

Status: **skeleton (M1)**. This file is completed in M6 and updated whenever the attack surface changes (a new endpoint, tool or data source).

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
| Lockfile, pip-audit, Dependabot, CodeQL (once the repo is public); new dependencies need approval + registry vetting | M1–M2 | LLM03, ASI04 |
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
To be filled in as controls land (M1: leakage tests, gitleaks planted-key check; M5: read-only role test, injection evals).

## Known limitations
To be filled in (M6).
