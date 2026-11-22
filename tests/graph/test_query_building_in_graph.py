"""The query builder inside a real turn: what the gateway's search is actually asked."""

from __future__ import annotations

import json

from orchestrator.auth import UserContext
from orchestrator.gateway import LiteLLMGateway
from orchestrator.service import OrchestratorService
from tests.conftest import FakeGateway, make_settings


def _user() -> UserContext:
    return UserContext(oid="oid-1", name="Test User", roles=("AgentUser",))


async def _service(fake: FakeGateway, **overrides) -> OrchestratorService:
    settings = make_settings(**{"query_rewrite_enabled": True, **overrides})
    service = OrchestratorService(
        settings, gateway=LiteLLMGateway(settings, client=fake.client())
    )
    await service.__aenter__()
    return service


async def test_follow_up_is_searched_by_its_rewritten_query(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    service = await _service(fake_gateway)
    await service.run("how many annual leave days do I get?", _user(), session_id="c1")
    fake_gateway.agent_search_queries.clear()
    fake_gateway.rewrite_raw = json.dumps({"queries": ["annual leave days for contractors"]})

    await service.run("and for contractors?", _user(), session_id="c1")

    assert fake_gateway.agent_search_queries == ["annual leave days for contractors"]
    assert "how many annual leave days" in fake_gateway.rewrite_prompts[-1]


async def test_the_rewrite_is_visible_in_the_turn_notes(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    service = await _service(fake_gateway)
    await service.run("how many annual leave days do I get?", _user(), session_id="c2")
    fake_gateway.rewrite_raw = json.dumps({"queries": ["annual leave days for contractors"]})

    result = await service.run("and for contractors?", _user(), session_id="c2")

    assert any("search queries: annual leave days for contractors" in n for n in result.notes)


async def test_a_failing_rewrite_never_fails_the_turn(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    service = await _service(fake_gateway)
    await service.run("how many annual leave days do I get?", _user(), session_id="c3")
    fake_gateway.rewrite_fails = True

    result = await service.run("and for contractors?", _user(), session_id="c3")

    assert result.status != "failed"
    assert fake_gateway.agent_search_queries[-1] == "and for contractors?"


async def test_a_self_contained_question_costs_no_extra_model_call(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.agent_search_enabled = True
    service = await _service(fake_gateway)

    await service.run("how many annual leave days do I get?", _user(), session_id="c4")

    assert fake_gateway.rewrite_prompts == []


async def test_rewriting_can_be_switched_off(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    service = await _service(fake_gateway, query_rewrite_enabled=False)
    await service.run("how many annual leave days do I get?", _user(), session_id="c5")

    await service.run("and for contractors?", _user(), session_id="c5")

    assert fake_gateway.rewrite_prompts == []


async def test_earlier_declines_are_not_fed_to_the_rewriter(
    fake_gateway: FakeGateway,
) -> None:
    """A decline is not evidence about the next question.

    Measured in LibreChat: after several "Nothing in the registered catalogue covers that
    request." turns, the rewrite model answered ``{"queries": []}`` and the gate declined
    "what is a lahar?" — a question that routes correctly in a fresh conversation. Only
    the user's own turns may reach the retrieval prompt.
    """
    fake_gateway.agent_search_enabled = True
    fake_gateway.gate_no_match = True
    service = await _service(fake_gateway)
    for message in ("write me a haiku about winter", "what is the capital of Mongolia?"):
        await service.run(message, _user(), session_id="c6")
    fake_gateway.gate_no_match = False
    fake_gateway.rewrite_raw = json.dumps({"queries": ["lahar volcanic mudflow"]})

    await service.run("what is a lahar?", _user(), session_id="c6")

    prompt = fake_gateway.rewrite_prompts[-1]
    assert "haiku" in prompt and "Mongolia" in prompt, prompt
    assert "Nothing in the registered catalogue" not in prompt, prompt
    assert fake_gateway.gate_prompts[-1].count("Nothing in the registered catalogue") == 0


async def test_an_empty_rewrite_falls_back_to_the_message(fake_gateway: FakeGateway) -> None:
    """``{"queries": []}`` must degrade to the raw message, never to no search."""
    fake_gateway.agent_search_enabled = True
    service = await _service(fake_gateway)
    await service.run("how many annual leave days do I get?", _user(), session_id="c7")
    fake_gateway.rewrite_raw = json.dumps({"queries": []})

    result = await service.run("and for contractors?", _user(), session_id="c7")

    assert result.status != "failed"
    assert fake_gateway.agent_search_queries[-1] == "and for contractors?"
