"""One command for a local demo: Postgres in Docker, the demo-only data, and the API on http://127.0.0.1:8000.

Usage: uv run python -m scout.local_demo [--data data/demo/scout_demo.tar.gz] [--no-api]

1. .env: if missing, created from .env.example with random passwords and API token (values are never printed);
   existing .env files are only syntax-checked (scout.check_env), never changed.
2. Postgres: `docker compose up -d db`, then waits until healthy (roles are created on the first start).
3. Data: if the demo tables are empty, loads the demo data file (scout.demo_data import). A fresh clone gets the file
   from the repository's GitHub release (see docs/DEMO.md).
4. API: starts uvicorn on 127.0.0.1:8000 and prints what to try. The agent (POST /ask) needs ANTHROPIC_API_KEY in .env;
   the five tools work without it.
"""
import argparse
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

from scout.check_env import problems
from scout.data.manifest import ROOT
from scout.demo_data import FILE

ENV, EXAMPLE = ROOT / ".env", ROOT / ".env.example"
ROLE_URL = re.compile(r"(scout_[a-z]+):change-me@")


def fill_example(text: str) -> str:
    """.env.example with every change-me replaced: one random value per NAME=change-me line, and database URLs given
    the password of their role (scout_reader -> SCOUT_READER_PASSWORD)."""
    values = {}
    for line in text.splitlines():
        name, _, value = line.partition("=")
        if value.strip() == "change-me":
            values[name.strip()] = secrets.token_urlsafe(32 if name.strip() == "SCOUT_API_TOKEN" else 24)
    out = []
    for line in text.splitlines():
        name, _, value = line.partition("=")
        if name.strip() in values:
            line = f"{name.strip()}={values[name.strip()]}"
        else:
            line = ROLE_URL.sub(lambda m: f"{m.group(1)}:{values[m.group(1).upper() + '_PASSWORD']}@", line)
        out.append(line)
    return "\n".join(out) + "\n"


def load_env(path: Path) -> dict:
    """NAME=value pairs (comments and blank lines skipped); used only to pass the settings to subprocesses."""
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            env[name.strip()] = value.split(" #")[0].strip()
    return env


def main() -> None:
    import os

    import psycopg
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(FILE))
    ap.add_argument("--no-api", action="store_true", help="prepare the database only")
    args = ap.parse_args()
    if not ENV.exists():
        ENV.write_text(fill_example(EXAMPLE.read_text(encoding="utf-8")), encoding="utf-8")
        print("created .env from .env.example with random passwords and API token (values not shown)")
    found = problems(ENV.read_text(encoding="utf-8"))
    if found:
        raise SystemExit(f".env has {len(found)} syntax problem(s); run `uv run python -m scout.check_env`")
    env = {**os.environ, **load_env(ENV)}

    subprocess.run(["docker", "compose", "up", "-d", "db"], cwd=ROOT, check=True)
    for _ in range(90):
        status = subprocess.run(["docker", "compose", "ps", "--format", "{{.Status}}", "db"], cwd=ROOT,
                                capture_output=True, text=True).stdout
        if "healthy" in status:
            break
        time.sleep(2)
    else:
        raise SystemExit("Postgres did not become healthy; check `docker compose logs db`")
    time.sleep(2)  # first start: the init scripts create the roles right after the health check turns green

    with psycopg.connect(env["LOADER_DATABASE_URL"], connect_timeout=10) as conn:
        has = conn.execute("SELECT to_regclass('demo_players') IS NOT NULL").fetchone()[0]
        rows = conn.execute("SELECT count(*) FROM demo_players").fetchone()[0] if has else 0
        if not rows:
            data = Path(args.data)
            if not data.exists():
                raise SystemExit(f"no demo data yet: download scout_demo.tar.gz from the GitHub release into {data} "
                                 "(see docs/DEMO.md), then run this again")
            from scout.demo_data import import_
            m = import_(conn, data)
            print("loaded demo data: " + ", ".join(f"{t} {v['rows']:,}" for t, v in m["tables"].items()))
        else:
            print(f"demo data already loaded ({rows:,} players)")
    if args.no_api:
        return
    print("\nAPI on http://127.0.0.1:8000 (Ctrl+C to stop). Every endpoint except /health needs the bearer token "
          "SCOUT_API_TOKEN from your .env, e.g.\n"
          "  curl -H \"Authorization: Bearer <token>\" \"http://127.0.0.1:8000/players/search?name=saka\"\n"
          "MCP (stdio):  npx @modelcontextprotocol/inspector uv run --env-file .env python -m scout.mcp_server\n"
          "Agent:        uv run --env-file .env python -m scout.agent.agent \"How will Bukayo Saka's value change?\" "
          "(needs ANTHROPIC_API_KEY)\n")
    subprocess.run([sys.executable, "-m", "uvicorn", "scout.api.main:app", "--host", "127.0.0.1", "--port", "8000"],
                   cwd=ROOT, env=env)


if __name__ == "__main__":
    main()
