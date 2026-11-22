"""Generic A2A server for the example suite.

Serves one agent from ``a2a_suite.agents`` — the card at both well-known paths, and both
request shapes a gateway may forward:

  * JSON-RPC 2.0 ``message/send`` / ``message/stream``  (A2A 0.3 native)
  * ``{"message": {"role": "user", "parts": [...]}}``    (LiteLLM's simple proxy form)

Run one agent:

    python -m a2a_suite.server --agent bicycle-repair --port 9110

List them:

    python -m a2a_suite.server --list

The card's ``url`` must be reachable *from the gateway*. When the gateway runs in a
container and the agent on the host, pass ``--url http://host.docker.internal:9110`` (or set
``A2A_AGENT_URL``) — a card that advertises ``localhost`` produces the classic
"works locally, 500s in the gateway" failure.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from a2a_suite.catalog import AGENTS, by_id
from a2a_suite.spec import AgentSpec, answer


def load_spec(agent_id: str) -> AgentSpec:
    """Import ``a2a_suite.agents.<id>`` and return its ``SPEC``."""
    by_id(agent_id)  # validate with a helpful message before importing
    module = importlib.import_module(f"a2a_suite.agents.{agent_id.replace('-', '_')}")
    spec = getattr(module, "SPEC", None)
    if not isinstance(spec, AgentSpec):  # pragma: no cover - authoring mistake
        raise SystemExit(f"{module.__name__} does not export SPEC: AgentSpec")
    return spec


def card_url(spec: AgentSpec, override: str = "") -> str:
    """Where the card should say this agent lives."""
    explicit = (override or os.environ.get("A2A_AGENT_URL", "")).strip()
    return (explicit or f"http://localhost:{spec.port}").rstrip("/")


def _extract_text(payload: Any) -> str:
    """Pull the user's text out of any accepted request shape."""
    texts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "text" and isinstance(value, str):
                    texts.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return " ".join(texts).strip()


def _is_jsonrpc(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("jsonrpc") == "2.0"


def create_app(spec: AgentSpec, url: str = "") -> FastAPI:
    app = FastAPI(title=f"{spec.title} A2A agent", version="1.0.0")

    # Resolved per request, so a test monkeypatching the env is picked up.
    def current_card() -> dict[str, Any]:
        return spec.card(card_url(spec, url))

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "agent": spec.name,
            "port": spec.port,
            "skills": [skill.id for skill in spec.skills],
            "knowledge_version": spec.knowledge_version,
        }

    @app.get("/.well-known/agent-card.json")
    async def agent_card() -> dict[str, Any]:
        return current_card()

    @app.get("/.well-known/agent.json")
    async def agent_card_legacy() -> dict[str, Any]:
        return current_card()

    @app.get("/")
    async def describe() -> dict[str, Any]:
        return {
            "agent": spec.name,
            "card": "/.well-known/agent-card.json",
            "invoke": "POST /",
        }

    @app.post("/")
    async def handle(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                {"error": {"code": -32700, "message": "invalid JSON"}}, status_code=400
            )

        if _is_jsonrpc(payload):
            return _jsonrpc_response(payload)
        return _simple_response(payload)

    def _jsonrpc_response(payload: dict[str, Any]) -> JSONResponse:
        request_id = payload.get("id")
        method = str(payload.get("method") or "")

        if method not in ("message/send", "message/stream"):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"method not supported: {method}",
                    },
                }
            )

        reply = answer(spec, _extract_text(payload.get("params") or {}))
        message = {
            "kind": "message",
            "messageId": uuid.uuid4().hex,
            "role": "agent",
            "parts": [{"kind": "text", "text": reply}],
        }
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": message})

    def _simple_response(payload: Any) -> JSONResponse:
        reply = answer(spec, _extract_text(payload))
        return JSONResponse({"result": {"parts": [{"type": "text", "text": reply}]}})

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run one agent from the A2A example suite")
    parser.add_argument("--agent", help="agent id, for example bicycle-repair")
    parser.add_argument("--port", type=int, default=0, help="defaults to the catalog port")
    parser.add_argument(
        "--url",
        default="",
        help="URL the gateway will use to reach this agent (advertised in the card)",
    )
    parser.add_argument("--list", action="store_true", help="print every agent and exit")
    args = parser.parse_args(argv)

    if args.list:
        print(
            json.dumps(
                [
                    {"id": entry.id, "port": entry.port, "title": entry.title}
                    for entry in AGENTS
                ],
                indent=2,
            )
        )
        return

    if not args.agent:
        parser.error("--agent is required (or use --list)")

    spec = load_spec(args.agent)
    port = args.port or spec.port
    app = create_app(spec, args.url)

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
