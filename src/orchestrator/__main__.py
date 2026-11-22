"""Serve the orchestrator: ``python -m orchestrator``.

Why this module exists
----------------------
``uvicorn.run()`` does not read the asyncio event-loop policy. On Windows it hard-codes
``ProactorEventLoop`` (``uvicorn/loops/asyncio.py``: ``if sys.platform == "win32" and not
use_subprocess: return asyncio.ProactorEventLoop``), and ``psycopg`` refuses to run async
on Proactor:

    psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async
    mode.

So ``CHECKPOINT_BACKEND=postgres`` cannot boot through the plain ``uvicorn`` CLI on
Windows, even with ``asyncio.set_event_loop_policy`` set beforehand — the policy is
bypassed. This entry point supplies the loop explicitly instead:

    asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)

On every other platform the factory is left unset, so the interpreter default is used and
Linux/container behaviour is unchanged.

``--reload`` is deliberately absent: uvicorn implements it with a subprocess, which
returns to the Proactor loop and re-breaks psycopg. Use the ``uvicorn`` CLI for reload
with ``CHECKPOINT_BACKEND=memory``.

``asyncio.Runner`` is used instead of ``asyncio.run(..., loop_factory=...)`` because the
latter only gained ``loop_factory`` in Python 3.12, while this package supports 3.11.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

import uvicorn


def loop_factory() -> Any:
    """The event loop class uvicorn should use, or ``None`` for the default.

    ``SelectorEventLoop`` is required on Windows only because of psycopg's async
    limitation. It is not used elsewhere so the platform default stays in charge.
    """
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator",
        description="Run the A2A orchestrator API server",
    )
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="bind port (default: 8000)")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        help="uvicorn log level (default: info)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = uvicorn.Config(
        "orchestrator.api.app:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )
    server = uvicorn.Server(config)

    factory = loop_factory()
    if factory is not None:
        # Provenance for the one case that is not the platform default.
        print(f"event loop: {factory.__name__}", flush=True)

    # asyncio.Runner speaks loop_factory on 3.11+; asyncio.run only from 3.12.
    with asyncio.Runner(loop_factory=factory) as runner:
        try:
            runner.run(server.serve())
        except KeyboardInterrupt:  # pragma: no cover - interactive only
            return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
