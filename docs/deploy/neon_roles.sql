-- Scout demo database on Neon: the same three roles as local Postgres (db/init/02-roles.sh, 04-tracer.sh).
-- Run once in the Neon SQL Editor as the project owner, on the default database (neondb).
-- Replace the three <...> placeholders with passwords you generate on your own machine, e.g.
--   python -c "import secrets; print(secrets.token_urlsafe(24))"
-- Never paste them into a chat, a commit or an issue. Store the resulting connection strings only in your local .env
-- (loader) and in GCP Secret Manager (reader, tracer).

CREATE ROLE scout_loader LOGIN PASSWORD '<loader password>';
CREATE ROLE scout_reader LOGIN PASSWORD '<reader password>';
CREATE ROLE scout_tracer LOGIN PASSWORD '<tracer password>';

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE neondb TO scout_loader, scout_reader, scout_tracer;
GRANT USAGE, CREATE ON SCHEMA public TO scout_loader;
GRANT USAGE ON SCHEMA public TO scout_reader, scout_tracer;

-- every table the loader creates is readable, and only readable, by scout_reader;
-- scout_tracer gets SELECT/INSERT on the agent_* tables only, from db/agent.sql when the demo data is imported
ALTER DEFAULT PRIVILEGES FOR ROLE scout_loader IN SCHEMA public GRANT SELECT ON TABLES TO scout_reader;
