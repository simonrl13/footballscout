"""SHA-256 manifest of the raw Kaggle CSVs, so every run is tied to one exact dataset version.

Usage: uv run python -m scout.data.manifest --record 2026-09-23   # (re)write after a new download
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "data" / "manifest.json"
FILES = ["players", "player_valuations", "appearances", "games", "clubs", "competitions", "transfers"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def verify(files=FILES) -> None:
    """Raise if any raw CSV is missing or differs from the recorded hash."""
    recorded = json.loads(MANIFEST.read_text())["files"]
    bad = [f for f in files if not (RAW / f"{f}.csv").exists() or sha256(RAW / f"{f}.csv") != recorded[f]]
    if bad:
        raise RuntimeError(f"data/raw does not match data/manifest.json: {bad}. "
                           "Re-download the dataset version in the manifest, or re-record it deliberately.")


def record(download_date: str) -> None:
    MANIFEST.write_text(json.dumps({
        "source": "https://www.kaggle.com/datasets/davidcariboo/player-scores (CC0-1.0)",
        "download_date": download_date,
        "files": {f: sha256(RAW / f"{f}.csv") for f in FILES},
    }, indent=2) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", metavar="DOWNLOAD_DATE", help="write the manifest for the current data/raw files")
    args = ap.parse_args()
    record(args.record) if args.record else verify()
    print("recorded" if args.record else "data/raw matches data/manifest.json")
