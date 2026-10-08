#!/bin/sh
# Agent trace writer: can read and append the agent_* tables only (grants in db/agent.sql), nothing else.
# Runs on first volume init; for an existing volume run it once via `python -m scout.agent.setup`.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v db="$POSTGRES_DB" -v pw="$SCOUT_TRACER_PASSWORD" <<'SQL'
CREATE ROLE scout_tracer LOGIN PASSWORD :'pw';
GRANT CONNECT ON DATABASE :"db" TO scout_tracer;
GRANT USAGE ON SCHEMA public TO scout_tracer;
SQL
