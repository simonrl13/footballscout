"""One-off: create the scout_tracer role on an EXISTING Postgres volume (fresh volumes get it from
db/init/04-tracer.sh) and append the M4a settings to .env: tracer password and URL, a random API token and the
agent model (development default: the cheapest suitable one).
Nothing secret is printed. Then run `python -m scout.agent.demo` to create the tables and grants.

Usage: uv run python -m scout.agent.setup
"""
import secrets
import subprocess

from scout.data.manifest import ROOT


def main() -> None:
    pw = secrets.token_urlsafe(24)
    subprocess.run(["docker", "compose", "exec", "-T", "-e", f"SCOUT_TRACER_PASSWORD={pw}", "db",
                    "sh", "/docker-entrypoint-initdb.d/04-tracer.sh"], cwd=ROOT, check=True, capture_output=True)
    with open(ROOT / ".env", "a", encoding="utf-8") as f:  # append only; never read
        f.write(f"\n# --- added by M4a: agent traces (db/init/04-tracer.sh) and API token ---\n"
                f"SCOUT_TRACER_PASSWORD={pw}\n"
                f"TRACER_DATABASE_URL=postgresql://scout_tracer:{pw}@127.0.0.1:5432/scout\n"
                f"SCOUT_API_TOKEN={secrets.token_urlsafe(32)}\n"
                f"AGENT_MODEL=claude-haiku-4-5\n")
    print("created role 'scout_tracer'; appended 4 variables to .env (values not shown)")


if __name__ == "__main__":
    main()
