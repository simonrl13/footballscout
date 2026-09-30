"""One command, end to end: verify data -> load Postgres -> data report -> features + train -> validation report.

The test set is not evaluated here; that is scout/ml/evaluate_test.py (explicit flag, logged).

Usage: uv run --env-file .env python -m scout.pipeline [--no-db]
"""
import argparse

from scout.data import load, manifest, report
from scout.ml import train


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-db", action="store_true", help="skip the Postgres load (features read the CSVs directly)")
    args = ap.parse_args()
    manifest.verify()
    print("data/raw matches data/manifest.json")
    if not args.no_db:
        load.main()
    report.main()
    train.main()


if __name__ == "__main__":
    main()
