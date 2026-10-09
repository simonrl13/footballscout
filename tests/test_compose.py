"""The database container gets only the variables Postgres and db/init need, never app secrets."""
import re

from scout.data.manifest import ROOT

ALLOWED_DB_ENV = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "SCOUT_LOADER_PASSWORD", "SCOUT_READER_PASSWORD",
                  "SCOUT_MLFLOW_PASSWORD", "SCOUT_TRACER_PASSWORD"}


def test_db_service_gets_only_its_own_variables():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    db = compose.split("\n  db:\n", 1)[1].split("\n  api:\n", 1)[0]
    assert "env_file" not in db
    names = set(re.findall(r"^\s{6}([A-Z_]+):", db, re.M))
    assert names == ALLOWED_DB_ENV
    init_vars = {v for f in (ROOT / "db" / "init").glob("*.sh") for v in re.findall(r"\$\{?([A-Z_]+)", f.read_text())}
    assert init_vars <= ALLOWED_DB_ENV, init_vars - ALLOWED_DB_ENV  # every init script still gets what it reads
