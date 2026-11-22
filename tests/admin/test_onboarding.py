"""Onboarding pipeline: pre-check the card, register, verify, smoke-test."""

from __future__ import annotations

import json

import httpx
import pytest

from orchestrator.admin.onboarding import (
    OnboardingError,
    build_register_payload,
    fetch_card,
    find_agent,
    register_agent,
    send_message,
    validate_card,
)

GOOD_CARD = {
    "name": "finance-invoice-auditor",
    "description": "Audits invoices and flags duplicate charges",
    "url": "http://reference-agent:9101/agents/finance",
    "version": "1.0.0",
    "protocolVersion": "0.3",
    "skills": [{"id": "audit", "name": "Invoice audit", "description": "detect duplicates"}],
}


# -- pre-check ------------------------------------------------------------
def test_good_card_has_no_problems() -> None:
    assert validate_card(GOOD_CARD, "http://reference-agent:9101/agents/finance") == []


def test_card_without_description_is_rejected() -> None:
    card = {**GOOD_CARD, "description": ""}
    assert any("description" in problem for problem in validate_card(card, GOOD_CARD["url"]))


def test_card_without_skills_is_rejected() -> None:
    card = {**GOOD_CARD, "skills": []}
    assert any("skills" in problem for problem in validate_card(card, GOOD_CARD["url"]))


def test_url_mismatch_is_flagged() -> None:
    problems = validate_card(GOOD_CARD, "http://localhost:9101/agents/finance")
    assert any("self-reports url" in problem for problem in problems)


def test_register_url_is_what_the_card_must_match() -> None:
    # Host fetches from localhost, gateway reaches the agent via host.docker.internal.
    card = {**GOOD_CARD, "url": "http://host.docker.internal:9101/agents/finance"}
    assert validate_card(
        card,
        "http://localhost:9101/agents/finance",
        register_url="http://host.docker.internal:9101/agents/finance",
    ) == []


def test_matching_register_url_but_stale_card_url_is_flagged() -> None:
    problems = validate_card(
        GOOD_CARD,  # card still says reference-agent
        "http://localhost:9101/agents/finance",
        register_url="http://host.docker.internal:9101/agents/finance",
    )
    assert any("self-reports url" in problem for problem in problems)


def test_skill_without_name_or_id_is_flagged() -> None:
    card = {**GOOD_CARD, "skills": [{"description": "nameless"}]}
    assert any("skill[0]" in problem for problem in validate_card(card, GOOD_CARD["url"]))


async def test_fetch_card_falls_back_to_second_well_known_path(monkeypatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("agent.json"):
            return httpx.Response(200, json=GOOD_CARD)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    card, source = await fetch_card("http://agent.test/agents/finance")

    assert card["name"] == "finance-invoice-auditor"
    assert source.endswith("/.well-known/agent.json")
    assert len(calls) == 2


async def test_fetch_card_raises_when_nothing_answers(monkeypatch) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    with pytest.raises(OnboardingError):
        await fetch_card("http://agent.test/nothing")


# -- register -------------------------------------------------------------
async def test_register_pins_protocol_version_and_sets_budget(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"agent_id": "abc"})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    await register_agent(
        "http://gw.test", "sk-admin",
        name="finance-invoice-auditor",
        url=GOOD_CARD["url"],
        protocol_version="0.3",
        card=GOOD_CARD,
    )

    assert captured["path"] == "/v1/agents"
    body = captured["body"]
    assert body["agent_name"] == "finance-invoice-auditor"
    assert body["agent_card_params"]["protocolVersion"] == "0.3"
    assert body["agent_card_params"]["skills"] == GOOD_CARD["skills"]
    assert body["litellm_params"]["require_trace_id_on_calls_by_agent"] is True
    assert body["litellm_params"]["max_iterations"] == 25


def test_default_protocol_version_is_the_current_spec() -> None:
    """1.0 is the newest A2A version LiteLLM serves, so it is the registration default.

    Measured on this stack: pinning 1.0 returns a 1.0 envelope and pinning 0.3 returns
    the legacy `kind` shape; the orchestrator parses both, so this is a forward-compat
    choice rather than a requirement.
    """
    payload = build_register_payload(name="a", url="http://a.test")

    assert payload["agent_card_params"]["protocolVersion"] == "1.0"


def test_legacy_protocol_can_still_be_pinned_explicitly() -> None:
    """Completion-bridge agents may only speak 0.3."""
    payload = build_register_payload(name="a", url="http://a.test", protocol_version="0.3")

    assert payload["agent_card_params"]["protocolVersion"] == "0.3"


async def test_register_surfaces_gateway_error(monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(400, text='{"error":"no connected db"}')
    )
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    with pytest.raises(OnboardingError) as excinfo:
        await register_agent("http://gw.test", "sk-admin", name="a", url="http://a.test")
    assert "400" in str(excinfo.value)


# -- verify / smoke -------------------------------------------------------
def test_find_agent_matches_name_or_id() -> None:
    agents = [{"agent_id": "abc", "agent_name": "finance-invoice-auditor"}]
    assert find_agent(agents, "finance-invoice-auditor") is not None
    assert find_agent(agents, "abc") is not None
    assert find_agent(agents, "nope") is None


async def test_smoke_message_carries_trace_id(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["trace"] = request.headers.get("x-litellm-trace-id")
        return httpx.Response(200, json={"result": {"parts": [{"text": "hi"}]}})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    status, _ = await send_message("http://gw.test", "sk-admin", "abc", "hello",
                                   trace_id="deadbeef")
    assert status == 200
    assert captured["path"] == "/a2a/abc"
    assert captured["trace"] == "deadbeef"
