"""A minimal but real A2A agent.

Serves its own agent card at the well-known path, and answers two request shapes so it
works whichever way the gateway forwards to it:

  * JSON-RPC 2.0 ``message/send``  (A2A 0.3 / 1.x native)
  * ``{"message": {"role": "user", "parts": [...]}}``  (LiteLLM's simple proxy form)

Run it with:
    python -m uvicorn ronaldo_agent.server:app --host 0.0.0.0 --port 9103
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .knowledge import KNOWLEDGE_CUTOFF, answer

CARD_PATH = Path(__file__).with_name("card.json")


def load_card(url_override: str = "") -> dict[str, Any]:
    card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    override = (url_override or os.environ.get("RONALDO_AGENT_URL", "")).strip()
    if override:
        card["url"] = override.rstrip("/")
        if isinstance(card.get("provider"), dict):
            card["provider"]["url"] = card["url"]
    return card


def _extract_text(payload: Any) -> str:
    """Pull the user's text out of any of the accepted request shapes."""
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


def _parts(text: str, *, kind_key: str) -> list[dict[str, str]]:
    return [{kind_key: "text", "text": text}]


def _is_jsonrpc(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("jsonrpc") == "2.0"


def create_app() -> FastAPI:
    app = FastAPI(title="Ronaldo A2A Agent", version="1.0.0")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "knowledge_cutoff": KNOWLEDGE_CUTOFF}

    @app.get("/.well-known/agent-card.json")
    async def agent_card() -> dict[str, Any]:
        return load_card()

    @app.get("/.well-known/agent.json")
    async def agent_card_legacy() -> dict[str, Any]:
        return load_card()

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
                    "error": {"code": -32601, "message": f"method not supported: {method}"},
                }
            )

        text = _extract_text(payload.get("params") or {})
        reply = answer(text)
        message = {
            "kind": "message",
            "messageId": uuid.uuid4().hex,
            "role": "agent",
            "parts": _parts(reply, kind_key="kind"),
        }
        if method == "message/stream":
            # Single-event stream: enough for clients that expect SSE framing.
            return JSONResponse(
                {"jsonrpc": "2.0", "id": request_id, "result": message}
            )
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": message})

    def _simple_response(payload: Any) -> JSONResponse:
        text = _extract_text(payload)
        reply = answer(text)
        return JSONResponse({"result": {"parts": _parts(reply, kind_key="type")}})

    return app


app = create_app()
