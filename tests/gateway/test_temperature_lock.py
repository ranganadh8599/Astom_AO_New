"""Models that reject the temperature we send.

OpenAI's reasoning models answer ``HTTP 400 UnsupportedParamsError: <model> doesn't
support temperature=0.0 while reasoning is active. Only temperature=1 is supported``.
That is a configuration detail of the model, not a fault in the caller, so the gateway
client should absorb it: one retry at the required value, then remember it.

What this pins:

1. The **first** call to such a model costs two requests; later calls cost one.
2. The error is recognised by its message — a 400 with any other text is still raised.
3. The value is read from the message, not assumed to be 1.0.
4. `probe_model` benefits too, so a reasoning planner reports ``ok`` at boot instead of
   ``unavailable``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from orchestrator.config import Settings
from orchestrator.gateway import LiteLLMGateway
from orchestrator.observability.trace_context import Lineage, TraceContext

LOCKED = "openai/gpt-5.6-luna"
FREE = "openai/gpt-4o-mini"


def _settings() -> Settings:
    return Settings(
        litellm_base_url="http://gateway.test",
        litellm_api_key="sk-test",
        planner_model=FREE,
        langfuse_tracing_enabled=False,
        protocols=("a2a",),
    )


def _gateway(handler) -> LiteLLMGateway:
    settings = _settings()
    client = httpx.AsyncClient(
        base_url="http://gateway.test", transport=httpx.MockTransport(handler)
    )
    return LiteLLMGateway(settings, client=client)


def _ok(content: str = "fine") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


def _temperature_error(model: str, limit: str = "1") -> httpx.Response:
    return httpx.Response(
        400,
        json={
            "error": {
                "message": (
                    f"litellm.UnsupportedParamsError: {model} doesn't support "
                    f"temperature=0.0 while reasoning is active. Only "
                    f"temperature={limit} is supported unless reasoning_effort resolves "
                    "to 'none'."
                ),
                "type": "invalid_request_error",
                "code": "400",
            }
        },
    )


def _family_temperature_error(limit: str = "1") -> httpx.Response:
    """The o-series wording: the family is named, not the model."""
    return httpx.Response(
        400,
        json={
            "error": {
                "message": (
                    "litellm.UnsupportedParamsError: O-series models don't support "
                    f"temperature=0.0. Only temperature={limit} is supported. To drop "
                    "unsupported openai params from the call, set `litellm.drop_params = True`"
                ),
                "type": "invalid_request_error",
                "code": "400",
            }
        },
    )


@pytest.mark.asyncio
async def test_first_call_retries_then_the_requirement_is_remembered() -> None:
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        temperature = json.loads(request.content)["temperature"]
        seen.append(temperature)
        return _temperature_error(LOCKED) if temperature != 1.0 else _ok()

    async with _gateway(handler) as gateway:
        first = await gateway.complete(
            LOCKED, [{"role": "user", "content": "hi"}],
            trace=TraceContext.root(), lineage=Lineage.root(),
        )
        second = await gateway.complete(
            LOCKED, [{"role": "user", "content": "again"}],
            trace=TraceContext.root(), lineage=Lineage.root(),
        )

    assert first == second == "fine"
    # Two attempts on the first call, one on the second.
    assert seen == [0.0, 1.0, 1.0]


@pytest.mark.asyncio
async def test_a_normal_model_still_gets_the_requested_temperature() -> None:
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["temperature"])
        return _ok()

    async with _gateway(handler) as gateway:
        await gateway.complete(
            FREE, [{"role": "user", "content": "hi"}],
            trace=TraceContext.root(), lineage=Lineage.root(), temperature=0.2,
        )

    assert seen == [0.2]


@pytest.mark.asyncio
async def test_the_value_comes_from_the_message_not_a_constant() -> None:
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        temperature = json.loads(request.content)["temperature"]
        seen.append(temperature)
        return _temperature_error(LOCKED, limit="0.7") if temperature != 0.7 else _ok()

    async with _gateway(handler) as gateway:
        await gateway.complete(
            LOCKED, [{"role": "user", "content": "hi"}],
            trace=TraceContext.root(), lineage=Lineage.root(),
        )

    assert seen == [0.0, 0.7]


@pytest.mark.asyncio
async def test_an_unrelated_400_is_not_retried() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(
            400,
            json={"error": {"message": "messages must not be empty", "code": "400"}},
        )

    async with _gateway(handler) as gateway:
        with pytest.raises(Exception):
            await gateway.complete(
                LOCKED, [{"role": "user", "content": "hi"}],
                trace=TraceContext.root(), lineage=Lineage.root(),
            )

    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_the_o_series_family_wording_is_also_recognised() -> None:
    """`O-series models don't support temperature=0.0` names the family, not the model."""
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        temperature = json.loads(request.content)["temperature"]
        seen.append(temperature)
        return _family_temperature_error() if temperature != 1.0 else _ok()

    async with _gateway(handler) as gateway:
        await gateway.complete(
            "openai/o3-mini", [{"role": "user", "content": "hi"}],
            trace=TraceContext.root(), lineage=Lineage.root(),
        )

    assert seen == [0.0, 1.0]


@pytest.mark.asyncio
async def test_probe_reports_ok_for_a_temperature_locked_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        temperature = json.loads(request.content)["temperature"]
        return _temperature_error(LOCKED) if temperature != 1.0 else _ok()

    async with _gateway(handler) as gateway:
        verdict, detail = await gateway.probe_model(LOCKED, TraceContext.root())

    assert verdict == "ok", detail
