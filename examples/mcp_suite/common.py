"""Shared helpers for the MCP example suite.

Each server module declares plain, type-annotated functions and wraps them in ``Tool`` so
this module can register them on the MCP server object. The annotations are what produce the
tool's input schema, so keep them explicit — a ``**kwargs`` handler would advertise no
parameters and the orchestrator would reject every call for missing arguments.

Two SDK layouts exist in the wild, and the repo's own sample uses the first:

* ``mcp.server.mcpserver.MCPServer`` — ``run(host=, port=, stateless_http=, json_response=)``
* ``mcp.server.fastmcp.FastMCP`` — those options belong to the constructor

Both are supported here, so a server module never has to care which is installed.

Every tool is read-only: the orchestrator refuses mutations, so a write tool here would only
ever exercise the refusal path.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Callable

try:  # layout used by examples/mcp_field_ops
    from mcp.server.mcpserver import MCPServer as _Server

    _RUN_TAKES_TRANSPORT_OPTIONS = True
except ImportError:  # layout shipped by mcp>=1.9 (FastMCP)
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[assignment]

    _RUN_TAKES_TRANSPORT_OPTIONS = False

from mcp_suite.catalog import ServerEntry, by_id


@dataclass(frozen=True)
class Tool:
    """One advertised tool: the description the planner reads, and the handler."""

    description: str
    handler: Callable[..., str]


def build_server(server_id: str, tools: Iterable[Tool]) -> Any:
    entry = by_id(server_id)
    if _RUN_TAKES_TRANSPORT_OPTIONS:
        server = _Server(name=entry.name, version="1.0.0", instructions=entry.description)
    else:
        # The FastMCP settings object owns transport options, so they are set here.
        server = _Server(
            name=entry.name,
            instructions=entry.description,
            host="0.0.0.0",
            port=entry.port,
            stateless_http=True,
            json_response=True,
        )

    for tool in tools:
        # The function name becomes the tool name, so two servers can share a verb
        # without colliding.
        server.tool(description=tool.description)(tool.handler)
    return server


def run(server_id: str, server: Any, argv: list[str] | None = None) -> None:
    """Serve one MCP server over streamable HTTP, stateless with JSON responses."""
    entry: ServerEntry = by_id(server_id)
    parser = argparse.ArgumentParser(description=f"Run the {entry.title} example MCP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=entry.port)
    args = parser.parse_args(argv)

    if _RUN_TAKES_TRANSPORT_OPTIONS:
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            stateless_http=True,
            json_response=True,
        )
        return

    settings = getattr(server, "settings", None)
    if settings is not None:
        settings.host = args.host
        settings.port = args.port
    server.run(transport="streamable-http")
