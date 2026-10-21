"""Per-client-IP rate limits for the public demo (PUBLIC_DEMO=true), counted in Postgres by scout_tracer.

The client IP is the last X-Forwarded-For entry: the one Google's front end appends in front of Cloud Run (verified on
the run.app URL, 2026-10-21). Entries a client sends itself come before it and are ignored. This holds only while the
service is reached directly: behind a load balancer or a custom-domain proxy the last entry is that proxy, and every
client would share one counter. IPv6 clients are keyed by their /64 (one subscriber's usual allocation), IPv4 by address. Only HMAC-SHA256(IP, RATE_LIMIT_PEPPER) is stored, never the IP;
rows older than 48 hours are deleted. Neither the IP nor the pepper is logged.
"""
import hashlib
import hmac
import ipaddress
import os

LIMITS = {"ask": {"minute": 5, "day": 20}, "tools": {"minute": 60}}  # approved 2026-10-14 (docs/PLAN.md, M7)

COUNT = """
SELECT count(*) FILTER (WHERE created_at > now() - interval '1 minute') AS minute,
       count(*) FILTER (WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') AS day,
       ceil(extract(epoch FROM date_trunc('day', now() AT TIME ZONE 'UTC') + interval '1 day'
                               - (now() AT TIME ZONE 'UTC')))::int AS to_midnight
FROM agent_requests WHERE ip_hash = %s AND kind = %s AND created_at > now() - interval '25 hours'"""


def client_ip(headers, peer: str | None) -> str:
    """The rate-limit key's source: an IPv4 address, an IPv6 /64, or the raw string if it doesn't parse."""
    raw = headers.get("x-forwarded-for", "").rsplit(",", 1)[-1].strip() or peer or "unknown"
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return raw
    if ip.version == 6 and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)


def ip_hash(ip: str) -> str:
    return hmac.new(os.environ["RATE_LIMIT_PEPPER"].encode(), ip.encode(), hashlib.sha256).hexdigest()


def check(conn, key: str, kind: str) -> int | None:
    """Seconds to wait if this request is over a limit (not recorded), else None (recorded)."""
    conn.execute("DELETE FROM agent_requests WHERE created_at < now() - interval '48 hours'")
    minute, day, to_midnight = conn.execute(COUNT, (key, kind)).fetchone()
    limits = LIMITS[kind]
    if minute >= limits["minute"]:
        return 60
    if day >= limits.get("day", float("inf")):
        return to_midnight
    # ponytail: count-then-insert can let a burst from one IP overshoot by a few under concurrency; fine for a demo
    conn.execute("INSERT INTO agent_requests (ip_hash, kind) VALUES (%s, %s)", (key, kind))
    return None
