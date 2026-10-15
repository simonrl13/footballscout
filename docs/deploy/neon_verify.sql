-- Scout demo database on Neon: what each scout_* role can do. Read-only; run in the Neon SQL Editor on neondb.
-- Expected after neon_roles.sql (before the demo data import):
--   scout_loader  attributes LOGIN, database CONNECT, schema public USAGE + CREATE
--   scout_reader  attributes LOGIN, database CONNECT, schema public USAGE,
--                 default privilege "SELECT on tables created by scout_loader in public"
--   scout_tracer  attributes LOGIN, database CONNECT, schema public USAGE
--   no "member" rows for neondb_owner except "admin" (from CREATE ROLE; no inherit, no set)
-- After the import, also: scout_reader SELECT on every table; scout_tracer SELECT + INSERT on the agent_* tables.
-- (TEMP on the database comes from Postgres' default grant to PUBLIC, not from these scripts.)
WITH r(rolname) AS (VALUES ('scout_loader'), ('scout_reader'), ('scout_tracer'))
SELECT r.rolname AS role, 'attributes' AS kind,
       concat_ws(', ', CASE WHEN p.rolcanlogin THEN 'LOGIN' END, CASE WHEN p.rolsuper THEN 'SUPERUSER' END,
                 CASE WHEN p.rolcreaterole THEN 'CREATEROLE' END, CASE WHEN p.rolcreatedb THEN 'CREATEDB' END,
                 CASE WHEN p.rolbypassrls THEN 'BYPASSRLS' END, CASE WHEN p.rolreplication THEN 'REPLICATION' END) AS detail
FROM r JOIN pg_roles p USING (rolname)
UNION ALL
SELECT r.rolname, 'database ' || current_database(),
       concat_ws(', ', CASE WHEN has_database_privilege(r.rolname, current_database(), 'CONNECT') THEN 'CONNECT' END,
                 CASE WHEN has_database_privilege(r.rolname, current_database(), 'CREATE') THEN 'CREATE' END,
                 CASE WHEN has_database_privilege(r.rolname, current_database(), 'TEMP') THEN 'TEMP' END)
FROM r
UNION ALL
SELECT r.rolname, 'schema public',
       concat_ws(', ', CASE WHEN has_schema_privilege(r.rolname, 'public', 'USAGE') THEN 'USAGE' END,
                 CASE WHEN has_schema_privilege(r.rolname, 'public', 'CREATE') THEN 'CREATE' END)
FROM r
UNION ALL
SELECT pg_get_userbyid(a.member), 'member of ' || pg_get_userbyid(a.roleid),
       concat_ws(', ', CASE WHEN a.admin_option THEN 'admin' END, CASE WHEN a.inherit_option THEN 'inherit' END,
                 CASE WHEN a.set_option THEN 'set' END) || ' (granted by ' || pg_get_userbyid(a.grantor) || ')'
FROM pg_auth_members a
WHERE pg_get_userbyid(a.roleid) LIKE 'scout\_%' OR pg_get_userbyid(a.member) LIKE 'scout\_%'
UNION ALL
SELECT pg_get_userbyid(e.grantee), 'default privilege',
       e.privilege_type || ' on ' || CASE d.defaclobjtype WHEN 'r' THEN 'tables' WHEN 'S' THEN 'sequences'
           WHEN 'f' THEN 'functions' ELSE d.defaclobjtype::text END
       || ' created by ' || pg_get_userbyid(d.defaclrole) || coalesce(' in ' || d.defaclnamespace::regnamespace::text, '')
FROM pg_default_acl d, aclexplode(d.defaclacl) e
WHERE pg_get_userbyid(d.defaclrole) LIKE 'scout\_%' OR pg_get_userbyid(e.grantee) LIKE 'scout\_%'
UNION ALL
SELECT g.grantee, 'tables', g.privilege_type || ' on ' || count(*) || ' table(s): '
       || string_agg(g.table_name, ', ' ORDER BY g.table_name)
FROM information_schema.role_table_grants g
WHERE g.grantee LIKE 'scout\_%' AND g.table_schema = 'public'
GROUP BY g.grantee, g.privilege_type
ORDER BY 1, 2;
