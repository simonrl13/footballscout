-- Scout demo database on Neon: the rate-limit table for the public API (scout/api/limits.py; same DDL and grants as
-- db/agent.sql, which a later demo re-import also runs). Run once in the Neon SQL Editor on neondb, after
-- neon_after_import.sql. No passwords; nothing to replace.
-- The table is created as scout_loader, like the other agent_* tables (neondb_owner takes the membership for this
-- transaction only). scout_reader gets nothing; scout_tracer gets SELECT, INSERT and DELETE (DELETE only to purge
-- rows older than 48 hours).
BEGIN;
GRANT scout_loader TO neondb_owner WITH INHERIT FALSE, SET TRUE;
SET LOCAL ROLE scout_loader;
CREATE TABLE IF NOT EXISTS agent_requests (
    created_at timestamptz NOT NULL DEFAULT now(),
    ip_hash    text NOT NULL,                     -- HMAC-SHA256(client IP, pepper); never the IP
    kind       text NOT NULL                      -- ask | tools
);
CREATE INDEX IF NOT EXISTS agent_requests_key ON agent_requests (ip_hash, kind, created_at);
REVOKE ALL ON agent_requests FROM scout_reader;
GRANT SELECT, INSERT, DELETE ON agent_requests TO scout_tracer;
RESET ROLE;
REVOKE scout_loader FROM neondb_owner;
COMMIT;
-- Then neon_verify.sql: 17 rows (step A6's 16 plus "scout_tracer DELETE on 1 table(s): agent_requests";
-- scout_tracer's INSERT and SELECT rows also list agent_requests; scout_reader's rows are unchanged).
