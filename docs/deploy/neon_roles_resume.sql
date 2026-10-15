-- One-off: finishes neon_roles.sql after statements 1-7 succeeded and statement 8 (ALTER DEFAULT PRIVILEGES) failed
-- with "permission denied to change default privileges". No passwords; run as neondb_owner on neondb.
-- Cause: on Postgres 16 a role may change another role's default privileges only if it has that role's privileges.
-- neondb_owner created scout_loader, which on PG 16 gives it ADMIN OPTION only (no INHERIT, no SET), so it can grant
-- itself the membership but doesn't hold it. Grant it (inherit only), set the default privileges, revoke it: the
-- default privileges stay in place without the membership, and nothing else needs it (the import logs in as
-- scout_loader). The REVOKE removes only this grant; the ADMIN OPTION from CREATE ROLE stays.
BEGIN;
GRANT scout_loader TO neondb_owner WITH INHERIT TRUE, SET FALSE;
ALTER DEFAULT PRIVILEGES FOR ROLE scout_loader IN SCHEMA public GRANT SELECT ON TABLES TO scout_reader;
REVOKE scout_loader FROM neondb_owner;
COMMIT;
-- Then run neon_verify.sql.
