"""Register an A2A agent on the LiteLLM gateway, safely and repeatably.

This is the pipeline we settled on:

    1. pre-check   fetch the agent's own card, reject it if the orchestrator could not
                   reason over it (no description / no skills / URL mismatch)
    2. register    POST /v1/agents with the admin key
    3. verify      GET /v1/agents and confirm it is visible
    4. smoke       send one harmless message through the gateway

Steps 1 and 4 are read-mostly; only step 2 needs the admin key. The orchestrator itself
never runs this — it holds a scoped virtual key, not the admin one.

Usage
-----
    python -m orchestrator.admin.onboarding check   --url http://localhost:9101/agents/finance
    python -m orchestrator.admin.onboarding register --name finance-invoice-auditor \
        --url http://reference-agent:9101/agents/finance --protocol-version 0.3
    python -m orchestrator.admin.onboarding verify  --name finance-invoice-auditor
    python -m orchestrator.admin.onboarding smoke   --name finance-invoice-auditor --text "hello"

Set LITELLM_ADMIN_KEY (or pass --admin-key) for register/verify/smoke.

CLI-ONLY KEY
------------
``LITELLM_ADMIN_KEY`` is read by this module alone. The orchestrator runtime
(``orchestrator.api.app``, ``service``, ``gateway``) never reads it: every call it makes
authenticates with ``LITELLM_API_KEY``, a key scoped to ``llm_api_routes``. Keeping the
admin key out of the service's environment means an orchestrator compromise cannot mint
keys, edit teams, or register agents.

Because of that, the variable is optional in ``.env``. Export it for the onboarding run
(``$env:LITELLM_ADMIN_KEY = "sk-..."``) or pass ``--admin-key`` per invocation.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any, Mapping

import httpx

from orchestrator.config import Settings

CARD_CANDIDATES = (
    "/.well-known/agent-card.json",
    "/.well-known/agent.json",
    "/.well-known/agent-card/v1.0/agent-card.json",
)


class OnboardingError(RuntimeError):
    pass


def _client(base_url: str, key: str, timeout: float = 30.0) -> httpx.AsyncClient:
    headers = {"accept": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    return httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)


def _snippet(text: str, limit: int = 400) -> str:
    return " ".join(text.split())[:limit]


# -- step 1: pre-check ----------------------------------------------------
async def fetch_card(agent_url: str, *, timeout: float = 20.0) -> tuple[dict[str, Any], str]:
    """Fetch the agent's own card. Returns the card and the URL that answered."""
    base = agent_url.rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as http:
        last_error = ""
        for suffix in CARD_CANDIDATES:
            url = f"{base}{suffix}"
            try:
                response = await http.get(url, headers={"accept": "application/json"})
            except httpx.HTTPError as exc:
                last_error = f"{url}: {exc}"
                continue
            if response.status_code == 404:
                continue
            if response.status_code >= 400:
                last_error = f"{url}: HTTP {response.status_code}"
                continue
            try:
                return response.json(), url
            except json.JSONDecodeError:
                last_error = f"{url}: not JSON"
        raise OnboardingError(
            f"no agent card found at {base} (tried {', '.join(CARD_CANDIDATES)}). "
            f"Last error: {last_error or 'none'}"
        )


def validate_card(
    card: Mapping[str, Any], submitted_url: str, *, register_url: str = ""
) -> list[str]:
    """Return the reasons this card is not good enough to register.

    ``submitted_url`` is where you fetched the card; ``register_url`` is the URL the
    gateway will use. They differ when the gateway runs in a container and the agent runs
    on the host (``localhost`` vs ``host.docker.internal``). The card must report the
    *register* URL, because the gateway may follow the card's own URL.
    """
    problems: list[str] = []
    if not card.get("name"):
        problems.append("card has no 'name'")
    if not card.get("description"):
        problems.append("card has no 'description' — the orchestrator cannot route to it")
    skills = card.get("skills") or []
    if not skills:
        problems.append("card has no 'skills' — the planner has nothing to match on")
    else:
        for index, skill in enumerate(skills):
            if not (skill.get("name") or skill.get("id")):
                problems.append(f"skill[{index}] has neither id nor name")

    expected = (register_url or submitted_url).rstrip("/")
    card_url = str(card.get("url") or "").rstrip("/")
    if card_url and expected and card_url != expected:
        # Not fatal, but it is the exact failure mode that breaks behind private networks.
        problems.append(
            f"card self-reports url={card_url!r} but you will register {expected!r} "
            "(the gateway may follow the card's URL)"
        )
    return problems


# -- step 2: register -----------------------------------------------------
def build_register_payload(
    *,
    name: str,
    url: str,
    protocol_version: str = "1.0",
    description: str = "",
    card: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The exact body sent to ``POST /v1/agents``.

    Protocol version is pinned deliberately: legacy callers without a version header
    otherwise get the older wire format, which changes the response shape the
    orchestrator parses.

    ``1.0`` is the current A2A spec and is the default here because it is the newest
    version LiteLLM serves. Measured against this stack: pinning 1.0 returns a 1.0
    envelope (``result.message.parts[]``) and pinning 0.3 returns the legacy
    ``kind``-discriminated shape, and the orchestrator reads both (it walks for ``text``
    rather than depending on ``kind``). Chain completion-bridge agents may only speak
    ``0.3``; pass that explicitly if so.
    """
    card_params: dict[str, Any] = {
        "name": name,
        "url": url,
        "version": str((card or {}).get("version") or "1.0.0"),
        "protocolVersion": protocol_version,
    }
    if card:
        for field in ("description", "skills", "capabilities", "provider", "defaultInputModes",
                      "defaultOutputModes", "iconUrl", "documentationUrl"):
            if card.get(field):
                card_params[field] = card[field]
    if description and "description" not in card_params:
        card_params["description"] = description

    return {
        "agent_name": name,
        "agent_card_params": card_params,
        "litellm_params": {
            # Enables per-session iteration/budget accounting keyed by x-litellm-trace-id.
            "require_trace_id_on_calls_by_agent": True,
            "max_iterations": 25,
            "max_budget_per_session": 5.00,
        },
    }


def build_smoke_request(
    agent_id: str,
    text: str,
    *,
    strategy: str = "simple",
    trace_id: str = "",
) -> dict[str, Any]:
    """The exact request sent when smoke-testing an agent."""
    trace_id = trace_id or uuid.uuid4().hex
    headers = {"x-litellm-trace-id": trace_id}
    if strategy == "chat":
        return {
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": headers,
            "body": {"model": f"a2a/{agent_id}",
                     "messages": [{"role": "user", "content": text}]},
            "trace_id": trace_id,
        }
    if strategy == "jsonrpc":
        return {
            "method": "POST",
            "path": f"/a2a/{agent_id}",
            "headers": headers,
            "body": {
                "jsonrpc": "2.0",
                "id": uuid.uuid4().hex,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": uuid.uuid4().hex,
                        "role": "user",
                        "parts": [{"kind": "text", "text": text}],
                    }
                },
            },
            "trace_id": trace_id,
        }
    return {
        "method": "POST",
        "path": f"/a2a/{agent_id}",
        "headers": headers,
        "body": {"message": {"role": "user", "parts": [{"type": "text", "text": text}]}},
        "trace_id": trace_id,
    }


async def register_agent(
    gateway_url: str,
    admin_key: str,
    *,
    name: str,
    url: str,
    protocol_version: str = "1.0",
    description: str = "",
    card: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """POST /v1/agents."""
    payload = build_register_payload(
        name=name, url=url, protocol_version=protocol_version,
        description=description, card=card,
    )

    async with _client(gateway_url, admin_key) as http:
        response = await http.post("/v1/agents", json=payload)
        if response.status_code == 409:
            raise OnboardingError(f"agent {name!r} is already registered")
        if response.status_code >= 400:
            raise OnboardingError(
                f"POST /v1/agents -> {response.status_code}: {_snippet(response.text)}"
            )
        return response.json() if response.content else {}


# -- step 3: verify -------------------------------------------------------
async def list_agents(gateway_url: str, key: str) -> list[dict[str, Any]]:
    async with _client(gateway_url, key) as http:
        response = await http.get("/v1/agents")
        if response.status_code >= 400:
            raise OnboardingError(
                f"GET /v1/agents -> {response.status_code}: {_snippet(response.text)}"
            )
        data = response.json()
    if isinstance(data, dict):
        data = data.get("data") or data.get("agents") or []
    return [item for item in data if isinstance(item, dict)]


def find_agent(agents: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for agent in agents:
        if agent.get("agent_name") == name or agent.get("agent_id") == name:
            return agent
    return None


# -- step 4: smoke --------------------------------------------------------
async def send_message(
    gateway_url: str,
    key: str,
    agent_id: str,
    text: str,
    *,
    strategy: str = "simple",
    trace_id: str = "",
) -> tuple[int, str]:
    spec = build_smoke_request(agent_id, text, strategy=strategy, trace_id=trace_id)
    async with _client(gateway_url, key) as http:
        response = await http.post(spec["path"], json=spec["body"], headers=spec["headers"])
        return response.status_code, response.text


# -- CLI ------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_env()
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--gateway", default=settings.litellm_base_url)
    common.add_argument("--admin-key", default="")
    common.add_argument("--json", action="store_true", help="machine-readable output")

    parser = argparse.ArgumentParser(prog="orchestrator.admin.onboarding", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", parents=[common], help="pre-check an agent's card")
    p_check.add_argument("--url", required=True, help="where YOU fetch the card from")
    p_check.add_argument(
        "--register-url", default="",
        help="URL the gateway will use (container-reachable); defaults to --url",
    )

    p_reg = sub.add_parser("register", parents=[common], help="register an agent on the gateway")
    p_reg.add_argument("--name", required=True)
    p_reg.add_argument("--url", required=True, help="where YOU fetch the card from")
    p_reg.add_argument(
        "--register-url", default="",
        help="URL the gateway will use (container-reachable); defaults to --url",
    )
    p_reg.add_argument("--protocol-version", default="0.3")
    p_reg.add_argument("--description", default="")
    p_reg.add_argument("--skip-precheck", action="store_true")

    p_ver = sub.add_parser("verify", parents=[common], help="confirm an agent is visible to a key")
    p_ver.add_argument("--name", required=True)
    p_ver.add_argument("--key", default="", help="key to check with; defaults to admin key")

    p_smoke = sub.add_parser("smoke", parents=[common], help="send one message through the gateway")
    p_smoke.add_argument("--name", required=True)
    p_smoke.add_argument("--text", default="hello, what can you do?")
    p_smoke.add_argument("--strategy", default=settings.invocation_strategy)

    args = parser.parse_args(argv)

    import asyncio

    async def run() -> int:
        if args.command == "check":
            card, source = await fetch_card(args.url)
            problems = validate_card(card, args.url, register_url=args.register_url)
            print(json.dumps({"source": source, "card": card, "problems": problems},
                             indent=2 if args.json else 0))
            if problems:
                print("\nWARN: " + "\nWARN: ".join(problems), file=sys.stderr)
            return 0

        admin = args.admin_key or settings.litellm_admin_key
        if not admin:
            print("LITELLM_ADMIN_KEY or --admin-key is required", file=sys.stderr)
            return 2

        if args.command == "register":
            card = None
            register_url = (args.register_url or args.url).rstrip("/")
            if not args.skip_precheck:
                card, source = await fetch_card(args.url)
                problems = validate_card(card, args.url, register_url=args.register_url)
                if problems:
                    print("Pre-check failed; refusing to register:", file=sys.stderr)
                    for problem in problems:
                        print(f"  - {problem}", file=sys.stderr)
                    print("\nRe-run with --skip-precheck to override.", file=sys.stderr)
                    return 1
                print(f"pre-check ok (card from {source})", file=sys.stderr)

            result = await register_agent(
                args.gateway, admin,
                name=args.name, url=register_url,
                protocol_version=args.protocol_version,
                description=args.description, card=card,
            )
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "verify":
            agents = await list_agents(args.gateway, args.key or admin)
            match = find_agent(agents, args.name)
            if not match:
                print(f"{args.name!r} not visible. Visible: "
                      f"{[a.get('agent_name') for a in agents]}", file=sys.stderr)
                return 1
            print(json.dumps({"agent_id": match.get("agent_id"),
                              "agent_name": match.get("agent_name")}, indent=2))
            return 0

        if args.command == "smoke":
            agents = await list_agents(args.gateway, args.key or admin)
            match = find_agent(agents, args.name)
            if not match:
                print(f"{args.name!r} not registered", file=sys.stderr)
                return 1
            trace_id = uuid.uuid4().hex

            status, body = await send_message(
                args.gateway, args.key or admin, str(match["agent_id"]), args.text,
                strategy=args.strategy, trace_id=trace_id,
            )
            print(json.dumps({"status": status, "trace_id": trace_id,
                              "body": _snippet(body, 1200)}, indent=2))
            return 0 if status < 400 else 1

        return 2

    try:
        return asyncio.run(run())
    except OnboardingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
