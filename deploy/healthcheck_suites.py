"""Container healthcheck for the example suites (one image, two protocols).

Docker passes no arguments here: the probe reads ``SUITE_KIND`` (``a2a`` or ``mcp``) and
``PORT`` from the environment that compose sets per service.

Why not one probe for both:

* An **A2A agent** serves its card at ``/.well-known/agent-card.json`` and answers 200.
  That is exactly the readiness question — the app is up and serving the thing the gateway
  will fetch.
* An **MCP server** speaks the *streamable* HTTP transport at ``/mcp``. A GET returns 200
  and then holds the connection open, so any client that waits for a body times out; and a
  POST without a JSON-RPC body answers 400 by design. The honest question is "is it
  accepting TCP connections", which cannot hang or produce a false negative.

Exit codes follow the HEALTHCHECK contract: 0 healthy, 1 unhealthy. A misconfigured
service (unknown kind, no port) is unhealthy rather than quietly passing.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request

CARD_PATH = "/.well-known/agent-card.json"
TIMEOUT_S = 4.0


def _port() -> int:
    raw = (os.environ.get("PORT") or "").strip()
    if not raw.isdigit():
        print(f"PORT is not set or not a number: {raw!r}", file=sys.stderr)
        raise SystemExit(1)
    return int(raw)


def _one_shot(port: int) -> int:
    """A2A: one-shot probes; the card must parse, so a half-started app cannot pass."""
    url = f"http://127.0.0.1:{port}{CARD_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:
            if response.status != 200:
                print(f"{url} -> HTTP {response.status}", file=sys.stderr)
                return 1
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"{url} -> {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if not payload.get("name") or not payload.get("skills"):
        print(f"{url} -> card is not registrable: {sorted(payload)}", file=sys.stderr)
        return 1
    return 0


def _streamable(port: int) -> int:
    """MCP: TCP connect only (see the module docstring for why)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT_S):
            return 0
    except OSError as exc:
        print(f"tcp 127.0.0.1:{port} -> {exc}", file=sys.stderr)
        return 1


def main() -> int:
    kind = (os.environ.get("SUITE_KIND") or "").strip().lower()
    port = _port()
    if kind == "a2a":
        return _one_shot(port)
    if kind == "mcp":
        return _streamable(port)
    print(f"SUITE_KIND must be 'a2a' or 'mcp', got {kind!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
