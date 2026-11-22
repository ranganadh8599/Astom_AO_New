"""Model preflight at boot.

A typo in `PLANNER_MODEL` or `GATE_MODEL` used to surface only as "the gate silently
stopped running" — because a 404 from the gateway was swallowed and the turn degraded to
planning. This check makes a wrong name fail at startup instead.

The design is deliberately asymmetric:

* a **rejected** model (404/403) is fatal — the name is wrong or the key may not use it,
  and no amount of retrying fixes that;
* a **transient** failure (timeout, 5xx, unreachable) is a warning — a gateway that is
  briefly down at boot must not fail the deploy;
* `/v1/models` is only a **hint** — a wildcard key may legitimately call models it does
  not advertise, so absence from the list is never treated as proof of a bad name.
"""

from __future__ import annotations

import json

import httpx
import pytest

from orchestrator.config import ConfigurationError, Settings
from orchestrator.gateway import LiteLLMGateway
from orchestrator.service import OrchestratorService

ADVERTISED = ["openai/gpt-4o-mini", "openai/gpt-4o"]


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


def _gateway(behaviour: str):
    """Build a transport that behaves like a gateway in a given state."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if behaviour == "unreachable":
            raise httpx.ConnectError("no route to host")
        if path == "/v1/models":
            if behaviour == "models-blocked":
                return httpx.Response(500, json={"error": "boom"})
            return httpx.Response(200, json={"data": [{"id": m} for m in ADVERTISED]})
        if path == "/v1/chat/completions":
            if behaviour == "models-blocked":
                # Model still works even when the listing endpoint does not.
                return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
            body = json.loads(request.content or b"{}")
            model = body.get("model")
            if model not in ADVERTISED:
                return httpx.Response(404, json={"error": {"message": "model does not exist"}})
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        return httpx.Response(404, json={"error": "unhandled"})

    return handler


# -- happy path ------------------------------------------------------------


async def test_valid_model_produces_no_warnings() -> None:
    service = _service(_gateway("healthy"))
    async with service:
        assert await service.preflight_models() == []


async def test_preflight_can_be_disabled() -> None:
    service = _service(_gateway("healthy"), model_preflight_enabled=False)
    async with service:
        assert await service.preflight_models() == []


# -- rejection is fatal ----------------------------------------------------


async def test_unknown_model_aborts_startup() -> None:
    service = _service(_gateway("healthy"), planner_model="openai/gpt-4o-minni")
    async with service:
        with pytest.raises(ConfigurationError, match="gateway rejected model"):
            await service.preflight_models()


async def test_bad_gate_model_aborts_startup() -> None:
    service = _service(
        _gateway("healthy"), gate_model="does-not-exist", coverage_gate_enabled=True
    )
    async with service:
        with pytest.raises(ConfigurationError, match="does-not-exist"):
            await service.preflight_models()


async def test_disabled_preflight_does_not_validate() -> None:
    service = _service(
        _gateway("healthy"),
        planner_model="openai/gpt-4o-minni",
        model_preflight_enabled=False,
    )
    async with service:
        assert await service.preflight_models() == []


# -- transient failures warn ----------------------------------------------


async def test_unreachable_gateway_warns_instead_of_failing() -> None:
    """A gateway restarting at boot must not fail the deploy."""
    service = _service(_gateway("unreachable"), request_timeout_s=1.0)
    async with service:
        warnings = await service.preflight_models()

    assert warnings
    assert any("could not verify" in w for w in warnings)


async def test_model_works_when_listing_is_broken() -> None:
    """/v1/models being down says nothing about whether the model works."""
    service = _service(_gateway("models-blocked"))
    async with service:
        warnings = await service.preflight_models()

    assert any("/v1/models unavailable" in w for w in warnings)
    # The probe itself succeeded, so no "could not verify" warning.
    assert not any("could not verify" in w for w in warnings)


# -- listing is a hint, never a gate -------------------------------------


def _wildcard_handler(request: httpx.Request) -> httpx.Response:
    """Gateway that serves an unlisted model, as a wildcard key legitimately can."""
    path = request.url.path
    if path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": m} for m in ADVERTISED]})
    if path == "/v1/chat/completions":
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    return httpx.Response(404, json={"error": "unhandled"})


async def test_unlisted_but_working_model_only_warns() -> None:
    service = _service(_wildcard_handler, planner_model="gpt-4o-mini")
    async with service:
        warnings = await service.preflight_models()

    assert any("not listed by /v1/models" in w for w in warnings)
    assert all("rejected" not in w for w in warnings)
