"""Local demo helpers: .env generation from the example and the demo-data archive check (no Docker, no DB)."""
import io
import json
import tarfile

import pytest

from scout.check_env import problems
from scout.local_demo import fill_example, load_env

EXAMPLE = """# comment
POSTGRES_USER=scout_admin
POSTGRES_PASSWORD=change-me
SCOUT_LOADER_PASSWORD=change-me
SCOUT_READER_PASSWORD=change-me
LOADER_DATABASE_URL=postgresql://scout_loader:change-me@127.0.0.1:5432/scout
READER_DATABASE_URL=postgresql://scout_reader:change-me@127.0.0.1:5432/scout
SCOUT_API_TOKEN=change-me
ANTHROPIC_API_KEY=
AGENT_EFFORT=medium
"""


def test_generated_env_has_random_values_matched_to_role_urls(tmp_path):
    text = fill_example(EXAMPLE)
    assert "change-me" not in text and problems(text) == []
    p = tmp_path / ".env"
    p.write_text(text, encoding="utf-8")
    env = load_env(p)
    assert env["LOADER_DATABASE_URL"] == f"postgresql://scout_loader:{env['SCOUT_LOADER_PASSWORD']}@127.0.0.1:5432/scout"
    assert env["READER_DATABASE_URL"].startswith(f"postgresql://scout_reader:{env['SCOUT_READER_PASSWORD']}@")
    assert env["SCOUT_READER_PASSWORD"] != env["SCOUT_LOADER_PASSWORD"] and len(env["SCOUT_API_TOKEN"]) >= 40
    assert env["ANTHROPIC_API_KEY"] == "" and env["AGENT_EFFORT"] == "medium"
    assert fill_example(EXAMPLE) != text  # new values every time


def test_demo_archive_is_checked_against_its_manifest(tmp_path):
    from scout.demo_data import read

    def archive(csv: bytes, digest: str):
        path = tmp_path / "demo.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            for name, data in [("demo_players.csv", csv),
                               ("manifest.json", json.dumps({"tables": {"demo_players": {"rows": 1, "sha256": digest}}}).encode())]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return path

    import hashlib
    good = b"player_id\n1\n"
    manifest, data = read(archive(good, hashlib.sha256(good).hexdigest()))
    assert data["demo_players"] == good
    with pytest.raises(SystemExit, match="does not match"):
        read(archive(b"player_id\n2\n", hashlib.sha256(good).hexdigest()))
