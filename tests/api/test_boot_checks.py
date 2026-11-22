"""Deferred model check.

Booting must not depend on the gateway answering. Previously `__aenter__` awaited both
the capability probe and the model check, so a dead gateway delayed startup by seconds
and a wrong model name aborted it entirely.

Now the checks run as a background task after startup, and the outcome lands on
`/health` as `models.status`:

    pending -> ok | degraded | failed

`pending` is deliberately not an error: a liveness probe must not fail on something that
resolves a second later.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from orchestrator.config import Settings
from orchestrator.gateway import LiteLLMGateway
from orchestrator.service import ModelCheck, OrchestratorService

ADVERTISED = ["openai/gpt-4o-mini"]


def _settings(**overrides) -> Settings:
    base = {
        "litellm_base_url": "http://gateway.test",
        "litellm_api_key": "sk-test",
        "planner_model": "openai/gpt-4o-mini",
        "langfuse_tracing_enabled": False,
        "protocols": ("a2a",),
    }
    base.update(overrides)
    return Settings(**base)


def _service(handler, **overrides) -> OrchestratorService:
    settings = _settings(**overrides)
    client = httpx.AsyncClient(
        base_url="http://gateway.test", transport=httpx.MockTransport(handler)
    )
    return OrchestratorService(settings, gateway=LiteLLMGateway(settings, client=client))


def _handler(behaviour: str):
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if behaviour == "unreachable":
            raise httpx.ConnectError("no route")
        if path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": m} for m in ADVERTISED]})
        if path == "/v1/chat/completions":
            model = json.loads(request.content or b"{}").get("model")
            if model not in ADVERTISED:
                return httpx.Response(404, json={"error": {"message": "no such model"}})
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        if path == "/v1/agents":
            return httpx.Response(200, json=[])
        if path == "/v1/mcp/server":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404, json={"error": "unhandled"})

    return handle


# -- ModelCheck shape ------------------------------------------------------


def test_fresh_check_starts_pending_and_is_not_unhealthy() -> None:
    check = ModelCheck()

    assert check.status == "pending"
    assert check.healthy is True


def test_serialised_shape() -> None:
    payload = ModelCheck(status="failed", error="boom").to_dict()

    assert payload == {"status": "failed", "warnings": [], "error": "boom", "checked_at": 0.0}


# -- run_preflight records instead of raising -----------------------------


async def test_good_config_settles_ok() -> None:
    service = _service(_handler("healthy"))
    async with service:
        check = await service.run_boot_checks()

    assert check.status == "ok"
    assert check.error == ""


async def test_rejected_model_is_recorded_not_raised() -> None:
    """The process must survive; the failure belongs on /health."""
    service = _service(_handler("healthy"), planner_model="openai/gpt-4o-minni")
    async with service:
        check = await service.run_preflight()

    assert check.status == "failed"
    assert "rejected model" in check.error
    assert check.healthy is False


async def test_transient_failure_is_degraded_not_failed() -> None:
    """An unreachable gateway is not a configuration error."""
    service = _service(_handler("unreachable"), request_timeout_s=1.0)
    async with service:
        check = await service.run_preflight()

    assert check.status == "degraded"
    assert check.error == ""
    assert any("could not verify" in w for w in check.warnings)


async def test_disabled_preflight_settles_ok_immediately() -> None:
    service = _service(_handler("unreachable"), model_preflight_enabled=False)
    async with service:
        check = await service.run_preflight()

    assert check.status == "ok"


# -- startup must not wait on the gateway ---------------------------------


async def test_entering_the_service_makes_no_gateway_calls() -> None:
    """Startup is now gateway-independent: discovery moved to the background task."""
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"data": []})

    service = _service(handle)
    async with service:
        assert seen == [], f"startup touched the gateway: {seen}"
        await service.run_boot_checks()
        assert seen, "the background task is what performs discovery"


async def test_boot_checks_never_raise_on_a_dead_gateway() -> None:
    service = _service(_handler("unreachable"), request_timeout_s=1.0)
    async with service:
        check = await service.run_boot_checks()
    assert check.status == "degraded"
