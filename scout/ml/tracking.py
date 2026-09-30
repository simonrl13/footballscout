"""MLflow tracking: every training/tuning run is logged with its commit and data manifest.

Tracking store: MLFLOW_TRACKING_URI (Postgres in .env); falls back to a local SQLite file so runs are never lost.
"""
import json
import os
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
import mlflow  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = "scout-value-model"


@contextmanager
def start_run(run_name: str, tags: dict | None = None):
    from scout.data.manifest import MANIFEST
    from scout.ml.train import git_commit

    uri = os.environ.get("MLFLOW_TRACKING_URI") or f"sqlite:///{(ROOT / 'mlruns' / 'mlflow.db').as_posix()}"
    (ROOT / "mlruns").mkdir(exist_ok=True)
    mlflow.set_tracking_uri(uri)
    if mlflow.get_experiment_by_name(EXPERIMENT) is None:
        mlflow.create_experiment(EXPERIMENT, artifact_location=(ROOT / "mlartifacts").resolve().as_uri())
    mlflow.set_experiment(EXPERIMENT)
    manifest = json.loads(MANIFEST.read_text())
    with mlflow.start_run(run_name=run_name, tags={"commit": git_commit(),
                                                   "data_download_date": manifest["download_date"], **(tags or {})}) as run:
        mlflow.log_dict(manifest, "data_manifest.json")
        yield run


if __name__ == "__main__":  # uv run --env-file .env python -m scout.ml.tracking  -> MLflow UI on http://127.0.0.1:5000
    import subprocess
    import sys

    uri = os.environ.get("MLFLOW_TRACKING_URI") or f"sqlite:///{(ROOT / 'mlruns' / 'mlflow.db').as_posix()}"
    subprocess.run([sys.executable, "-m", "mlflow", "ui", "--backend-store-uri", uri, "--host", "127.0.0.1",
                    "--port", "5000"], check=False)
