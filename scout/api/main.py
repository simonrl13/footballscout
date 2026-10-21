"""Scout API: the five read-only tools as REST endpoints and the agent at POST /ask (server-sent events).

Access: with PUBLIC_DEMO=true (the deployed demo) there is no token and every endpoint except /health is rate-limited
per client IP (scout/api/limits.py); otherwise every endpoint except /health needs
`Authorization: Bearer <SCOUT_API_TOKEN>`. Inputs are validated by the same Pydantic models the agent's tools use.
Data access uses the read-only role; traces and rate-limit counts use scout_tracer.
"""
import json
import os
import secrets
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field

from scout.agent import tools
from scout.api import limits

app = FastAPI(title="Scout")
bearer = HTTPBearer(auto_error=False)


def authorized(cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
    expected = os.environ.get("SCOUT_API_TOKEN")
    if not expected or cred is None or not secrets.compare_digest(cred.credentials.encode(), expected.encode()):
        raise HTTPException(401, "missing or invalid token", headers={"WWW-Authenticate": "Bearer"})


def public() -> bool:
    return os.environ.get("PUBLIC_DEMO", "false").lower() == "true"


def access(kind: str):
    def check(request: Request, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
        if not public():
            return authorized(cred)
        key = limits.ip_hash(limits.client_ip(request.headers, request.client.host if request.client else None))
        with psycopg.connect(os.environ["TRACER_DATABASE_URL"], connect_timeout=5, autocommit=True) as conn:
            wait = limits.check(conn, key, kind)
        if wait is not None:
            raise HTTPException(429, "rate limit exceeded, please try again later", headers={"Retry-After": str(wait)})
    return Depends(check)


def db():
    with tools.connect() as conn:
        yield conn


Auth, AskAuth = access("tools"), access("ask")
DB = Annotated[psycopg.Connection, Depends(db)]
PlayerIdPath = Annotated[int, Path(ge=1, le=10**8)]


@app.get("/health")
def health():
    try:
        with psycopg.connect(os.environ["READER_DATABASE_URL"], connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        status = "ok"
    except Exception as e:
        status = f"error: {type(e).__name__}"
    return {"status": "ok", "db": status}


def _found(out: dict) -> dict:
    if "error" in out:
        raise HTTPException(404, out["error"])
    return out


@app.get("/players/search", dependencies=[Auth])
def search_players(a: Annotated[tools.Search, Query()], conn: DB):
    return tools.search_players(conn, a)


@app.get("/players/{player_id}", dependencies=[Auth])
def get_player(player_id: PlayerIdPath, conn: DB):
    return _found(tools.get_player(conn, tools.PlayerId(player_id=player_id)))


@app.get("/players/{player_id}/forecast", dependencies=[Auth])
def predict_value_change(player_id: PlayerIdPath, conn: DB):
    return _found(tools.predict_value_change(conn, tools.PlayerId(player_id=player_id)))


@app.get("/text/search", dependencies=[Auth])
def search_text(a: Annotated[tools.TextSearch, Query()], conn: DB):
    """Wikipedia passages (CC BY-SA 4.0) with their exact revision links."""
    return tools.search_text(conn, a)


@app.post("/players/compare", dependencies=[Auth])
def compare_players(a: tools.Compare, conn: DB):
    return tools.compare_players(conn, a)


class Ask(tools.Strict):
    question: str = Field(min_length=3, max_length=500)


@app.post("/ask", dependencies=[AskAuth])
def ask(a: Ask):
    """Server-sent events: tool_call / tool_error progress, then one answer | refused | blocked event."""
    import anthropic

    from scout.agent.agent import Tracer, run

    def events():
        tracer = Tracer()
        try:
            with tools.connect() as conn:
                for e in run(a.question, anthropic.Anthropic(), tracer, conn):
                    yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
        finally:
            tracer.conn.close()

    return StreamingResponse(events(), media_type="text/event-stream")
