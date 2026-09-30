"""One-off: create the MLflow database/role on an EXISTING Postgres volume (fresh volumes get it from
db/init/03-mlflow.sh). Generates a password, runs the init script inside the container, and appends
SCOUT_MLFLOW_PASSWORD and MLFLOW_TRACKING_URI to .env. Nothing secret is printed.

Usage: uv run python -m scout.ml.setup_mlflow
"""
import secrets
import subprocess

from scout.data.manifest import ROOT


def main() -> None:
    pw = secrets.token_urlsafe(24)
    subprocess.run(["docker", "compose", "exec", "-T", "-e", f"SCOUT_MLFLOW_PASSWORD={pw}", "db",
                    "sh", "/docker-entrypoint-initdb.d/03-mlflow.sh"], cwd=ROOT, check=True, capture_output=True)
    with open(ROOT / ".env", "a", encoding="utf-8") as f:  # append only; never read
        f.write(f"\n# --- added by M2: MLflow tracking store (db/init/03-mlflow.sh) ---\n"
                f"SCOUT_MLFLOW_PASSWORD={pw}\n"
                f"MLFLOW_TRACKING_URI=postgresql+psycopg://scout_mlflow:{pw}@127.0.0.1:5432/mlflow\n")
    print("created database 'mlflow' and role 'scout_mlflow'; appended 2 variables to .env (values not shown)")


if __name__ == "__main__":
    main()
