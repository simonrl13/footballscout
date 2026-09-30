#!/bin/sh
# MLflow tracking store: its own database and owner role, separate from the project data.
# Runs on first volume init; for an existing volume run it once via `python -m scout.ml.setup_mlflow`.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v pw="$SCOUT_MLFLOW_PASSWORD" <<'SQL'
CREATE ROLE scout_mlflow LOGIN PASSWORD :'pw';
CREATE DATABASE mlflow OWNER scout_mlflow;
REVOKE ALL ON DATABASE mlflow FROM PUBLIC;
SQL
