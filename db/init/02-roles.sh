#!/bin/sh
# Runs once, when the Postgres volume is first initialized (docker-entrypoint-initdb.d).
# scout_loader owns and (re)creates the data tables; scout_reader can only read them (API, agent, MCP).
# Passwords come from .env and are passed as psql variables, never interpolated into SQL by the shell.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v db="$POSTGRES_DB" -v loader_pw="$SCOUT_LOADER_PASSWORD" -v reader_pw="$SCOUT_READER_PASSWORD" <<'SQL'
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE ROLE scout_loader LOGIN PASSWORD :'loader_pw';
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO scout_loader;
GRANT USAGE, CREATE ON SCHEMA public TO scout_loader;

CREATE ROLE scout_reader LOGIN PASSWORD :'reader_pw';
GRANT CONNECT ON DATABASE :"db" TO scout_reader;
GRANT USAGE ON SCHEMA public TO scout_reader;
-- every table the loader creates is readable, and only readable, by scout_reader
ALTER DEFAULT PRIVILEGES FOR ROLE scout_loader IN SCHEMA public GRANT SELECT ON TABLES TO scout_reader;
SQL
