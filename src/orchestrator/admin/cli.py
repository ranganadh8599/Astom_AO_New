"""Ask the orchestrator one question from the terminal.

    python -m orchestrator.admin.cli "what is our leave policy for 2026?"

With AUTH_MODE=dev a token is minted locally; with AUTH_MODE=entra pass --token.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from orchestrator.auth import DevValidator, NullAuthenticator, build_authenticator
from orchestrator.config import ConfigurationError, Settings, validate_environment
from orchestrator.service import OrchestratorService


async def _run(message: str, *, token: str, session_id: str) -> int:
    settings = Settings.from_env()

    # Same checks as the API, so the CLI cannot run with settings that would fail the
    # server. Warnings go to stderr to keep stdout parseable JSON.
    try:
        for warning in validate_environment():
            print(f"config: {warning}", file=sys.stderr)
        for warning in settings.validate():
            print(f"config: {warning}", file=sys.stderr)
    except ConfigurationError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2

    authenticator = build_authenticator(settings)

    if token:
        user = authenticator.validate(token)
    elif isinstance(authenticator, DevValidator):
        user = authenticator.validate(authenticator.issue())
    elif isinstance(authenticator, NullAuthenticator):
        user = authenticator.validate("")
    else:
        print("AUTH_MODE=entra requires --token", file=sys.stderr)
        return 2

    async with OrchestratorService(settings) as service:
        # CLI is short-lived: run the check inline so its output is available before
        # the result is printed, but never let a bad model block the actual query.
        check = await service.run_preflight()
        for warning in check.warnings:
            print(f"preflight: {warning}", file=sys.stderr)
        if check.status == "failed":
            print(f"preflight: {check.error}", file=sys.stderr)

        result = await service.run(message, user, session_id=session_id)

    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.status == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one query through the orchestrator")
    parser.add_argument("message", help="the user question")
    parser.add_argument("--token", default="", help="bearer token (required for AUTH_MODE=entra)")
    parser.add_argument("--session-id", default="", help="conversation ID to group traces")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.message, token=args.token, session_id=args.session_id))


if __name__ == "__main__":
    raise SystemExit(main())
