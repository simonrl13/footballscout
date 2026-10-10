"""MCP server (stdio) exposing the same four read-only tools as the REST API and the agent (scout/agent/tools.py).

Arguments are validated against the tools' Pydantic models (limits, enums) before any query; queries run on the
read-only role in read-only transactions. Unknown arguments are dropped by the MCP SDK before they reach the tool.

Run:       uv run --env-file .env python -m scout.mcp_server
Inspector: npx @modelcontextprotocol/inspector uv run --env-file .env python -m scout.mcp_server
"""
import inspect
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from scout.agent import tools

server = MCPServer("scout", instructions=(
    "Football player market values (Transfermarkt crowd estimates, not transfer fees) and a model's 12-month value "
    f"forecast with an 80% interval, for players in 7 European leagues, data as of {tools.DEMO_AS_OF}. "
    "Find players with search_players before using a player_id."))
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _handler(name: str, fn, model):
    """A flat-argument handler whose signature mirrors the Pydantic model, so the MCP schema carries its limits."""
    def handler(**kwargs) -> dict:
        args = model.model_validate(kwargs)  # validate before touching the database
        with tools.connect() as conn:
            return fn(conn, args)
    P = inspect.Parameter
    handler.__signature__ = inspect.Signature(
        [P(n, P.KEYWORD_ONLY, default=P.empty if f.is_required() else f.default, annotation=Annotated[f.annotation, f])
         for n, f in model.model_fields.items()], return_annotation=dict)
    handler.__name__, handler.__doc__ = name, model.__doc__
    return handler


for _name, (_fn, _model) in tools.TOOLS.items():
    server.tool(annotations=READ_ONLY)(_handler(_name, _fn, _model))


if __name__ == "__main__":
    server.run("stdio")
