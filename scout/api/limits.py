"""Per-client-IP rate limits for the public demo (PUBLIC_DEMO=true), counted in Postgres by scout_tracer.

The client IP is the last X-Forwarded-For entry: the one Google's front end appends in front of Cloud Run (verified on
the run.app URL, 2026-10-21). Entries a client sends itself come before it and are ignored. This holds only while the
service is reached directly: behind a load balancer or a custom-domain proxy the last entry is that proxy, and every
client would share one counter. IPv6 clients are keyed by their /64 (one subscriber's usual allocation), IPv4 by address;
an entry that isn't an IP address goes to one shared bucket (MALFORMED), so garbage can't mint fresh keys.
Check-and-count is atomic per (kind, key): a transaction-scoped advisory lock serializes concurrent requests from one
client, so a burst can't overshoot a limit. Only HMAC-SHA256(IP, RATE_LIMIT_PEPPER) is stored, never the IP;
rows older than 48 hours are deleted. Neither the IP nor the pepper is logged.
"""
import hashlib
import hmac
import ipaddress
import os

# approved 2026-10-14 (docs/PLAN.md, M7); ask_raw (2026-10-22): every /ask request, counted before validation, so
# floods of invalid bodies are bounded while a typo doesn't cost one of the 20 daily questions
LIMITS = {"ask": {"minute": 5, "day": 20}, "ask_raw": {"minute": 20}, "tools": {"minute": 60}}
MALFORMED = "malformed"

COUNT = """
SELECT count(*) FILTER (WHERE created_at > now() - interval '1 minute') AS minute,
       count(*) FILTER (WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') AS day,
       ceil(extract(epoch FROM date_trunc('day', now() AT TIME ZONE 'UTC') + interval '1 day'
                               - (now() AT TIME ZONE 'UTC')))::int AS to_midnight
FROM agent_requests WHERE ip_hash = %s AND kind = %s AND created_at > now() - interval '25 hours'"""


def client_ip(headers, peer: str | None) -> str:
    """The rate-limit key's source: an IPv4 address, an IPv6 /64, or MALFORMED (one shared bucket, fail closed)."""
    raw = headers.get("x-forwarded-for", "").rsplit(",", 1)[-1].strip() or peer or ""
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return MALFORMED
    if ip.version == 6 and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)


def ip_hash(ip: str) -> str:
    return hmac.new(os.environ["RATE_LIMIT_PEPPER"].encode(), ip.encode(), hashlib.sha256).hexdigest()


def check(conn, key: str, kind: str) -> int | None:
    """Seconds to wait if this request is over a limit (not recorded), else None (recorded)."""
    conn.execute("DELETE FROM agent_requests WHERE created_at < now() - interval '48 hours'")
    limits = LIMITS[kind]
    with conn.transaction():  # the lock is held until commit, so count + insert is one step per (kind, key)
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{kind}:{key}",))
        minute, day, to_midnight = conn.execute(COUNT, (key, kind)).fetchone()
        if minute >= limits["minute"]:
            return 60
        if day >= limits.get("day", float("inf")):
            return to_midnight
        conn.execute("INSERT INTO agent_requests (ip_hash, kind) VALUES (%s, %s)", (key, kind))
    return None
