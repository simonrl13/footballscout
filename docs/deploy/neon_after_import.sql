-- Scout demo database on Neon: least privilege on the trace tables. Run once after the demo data import (and after
-- any re-import), as neondb_owner on neondb. No passwords. Then re-run neon_verify.sql.
-- - scout_reader (the tools) never reads traces; its default privileges gave it SELECT on the agent_* tables and
--   views, which hold tool inputs and answers. Revoke them.
-- - scout_tracer keeps what the API's Tracer does: SELECT + INSERT on agent_calls (spend cap, traces), INSERT on
--   agent_violations, and nothing on agent_cache (the response cache is off in production: AGENT_CACHE unset).
-- The tables belong to scout_loader, so neondb_owner holds its privileges (inherit only) for the revokes and drops
-- them again, as in neon_roles.sql.
BEGIN;
GRANT scout_loader TO neondb_owner WITH INHERIT TRUE, SET FALSE;
REVOKE ALL ON agent_calls, agent_violations, agent_cache, agent_daily, agent_conversations FROM scout_reader;
REVOKE SELECT ON agent_violations FROM scout_tracer;
REVOKE ALL ON agent_cache FROM scout_tracer;
REVOKE scout_loader FROM neondb_owner;
COMMIT;
