"""Retrieval: the gateway ranks, the orchestrator routes.

Two surfaces, two independent fallbacks. These tests pin the contract that matters:
search is used when available, listing is used when it is not, and the answer says
which one happened so a routing miss is never silently reported as "nothing exists".
"""

from __future__ import annotations

import json

from orchestrator.auth import UserContext
from orchestrator.routing.target_catalog import TargetCatalog, _interleave
from orchestrator.gateway import LiteLLMGateway
from orchestrator.service import OrchestratorService
from orchestrator.observability.trace_context import TraceContext
from tests.conftest import (
    FakeGateway,
    make_settings,
    search_calls,
    tool_calls,
)


def _user() -> UserContext:
    return UserContext(oid="oid-1", name="Test User", roles=("AgentUser",))


async def _service(fake_gateway: FakeGateway, **overrides) -> OrchestratorService:
    settings = make_settings(**overrides)
    gateway = LiteLLMGateway(settings, client=fake_gateway.client())
    service = OrchestratorService(settings, gateway=gateway)
    await service.__aenter__()
    return service


async def _catalog(fake_gateway: FakeGateway, **overrides) -> TargetCatalog:
    settings = make_settings(**overrides)
    gateway = LiteLLMGateway(settings, client=fake_gateway.client())
    return TargetCatalog(gateway, settings)


# -- search path -----------------------------------------------------------


async def test_mcp_search_is_used_when_enabled(fake_gateway: FakeGateway) -> None:
    fake_gateway.mcp_tool_search_enabled = True
    catalog = await _catalog(fake_gateway, protocols=("a2a", "mcp"))

    result = await catalog.retrieve_for("order status", TraceContext.root())

    assert result.modes["mcp"] == "search"
    assert search_calls(fake_gateway), "expected an mcp_tool_search call"
    # The stripped name keeps the record resolvable at execution time.
    mcp = [r for r in result.records if r.is_mcp]
    assert mcp[0].tool_name == "get_order_status"
    assert mcp[0].agent_id == "mcp:orders:get_order_status"
    assert catalog.find(agent_id=mcp[0].agent_id) is not None


async def test_search_results_keep_their_schema(fake_gateway: FakeGateway) -> None:
    """mcp_tool_search returns the schema, so required-argument checks still work."""
    fake_gateway.mcp_tool_search_enabled = True
    catalog = await _catalog(fake_gateway, protocols=("mcp",))

    result = await catalog.retrieve_for("order status", TraceContext.root())
    mcp = [r for r in result.records if r.is_mcp][0]

    assert mcp.required_arguments == ("order_id",)
    assert mcp.missing_arguments({}) == ("order_id",)


async def test_agent_search_is_used_when_configured(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    catalog = await _catalog(fake_gateway, retrieval_top_k=2)

    result = await catalog.retrieve_for("leave policy", TraceContext.root())

    assert result.modes["a2a"] == "search"
    assert len([r for r in result.records if r.protocol == "a2a"]) <= 2


async def test_agent_search_returns_everything_the_gateway_ranked(
    fake_gateway: FakeGateway,
) -> None:
    """No numeric pre-filter: ranking is the gateway's, coverage is the gate's."""
    fake_gateway.agent_search_enabled = True
    catalog = await _catalog(fake_gateway, protocols=("a2a",))

    result = await catalog.retrieve_for("leave policy", TraceContext.root())

    assert result.modes["a2a"] == "search"
    assert len([r for r in result.records if r.protocol == "a2a"]) == 3
    assert all(r.search_score > 0 for r in result.records)


# -- fallback path ---------------------------------------------------------


async def test_unconfigured_search_falls_back_to_listing(fake_gateway: FakeGateway) -> None:
    """No embedding model and no tool search is a deployment choice, not an outage."""
    catalog = await _catalog(fake_gateway, protocols=("a2a", "mcp"))

    result = await catalog.retrieve_for("anything", TraceContext.root())

    assert result.modes == {"a2a": "listing", "mcp": "listing"}
    assert {r.protocol for r in result.records} == {"a2a", "mcp"}
    assert "listing" in result.note


async def test_unavailable_search_is_not_reprobed_every_turn(
    fake_gateway: FakeGateway,
) -> None:
    catalog = await _catalog(fake_gateway, protocols=("mcp",))

    await catalog.retrieve_for("first", TraceContext.root())
    after_first = len(search_calls(fake_gateway))
    await catalog.retrieve_for("second", TraceContext.root())

    assert len(search_calls(fake_gateway)) == after_first


async def test_empty_search_result_over_a_populated_catalogue_is_reported_honestly(
    fake_gateway: FakeGateway,
) -> None:
    """A routing miss must not be reported as 'nothing is registered'."""
    fake_gateway.mcp_tool_search_enabled = True
    service = await _service(fake_gateway, protocols=("mcp",))

    result = await service.run("xyzzyspoonqwerty", _user())

    assert result.status == "completed"
    answer = result.answer.lower()
    # Either the gate's coverage wording or the planner's lookup wording is acceptable;
    # claiming the registry itself is empty is not.
    assert "matched" in answer or "covers" in answer
    assert "no agents or mcp tools available" not in answer


# -- protocol fairness -----------------------------------------------------


def test_interleave_prevents_one_protocol_from_starving_the_other() -> None:
    from orchestrator.gateway.models import Target

    a2a = [Target(agent_id=f"a{i}", agent_name=f"a{i}") for i in range(5)]
    mcp = [
        Target(agent_id=f"m{i}", agent_name=f"m{i}", protocol="mcp", tool_name=f"t{i}")
        for i in range(2)
    ]

    merged = _interleave(a2a, mcp)

    assert [r.agent_id for r in merged[:4]] == ["a0", "m0", "a1", "m1"]
    assert len(merged) == 7


async def test_listing_uses_the_prompt_budget_not_the_search_cap(
    fake_gateway: FakeGateway,
) -> None:
    """Unranked listing must not be squeezed to `retrieval_top_k`.

    Advice: retrieval asks search for a shortlist; listing has no ranking, so cutting it
    short can hide the right target.
    """
    catalog = await _catalog(
        fake_gateway, protocols=("a2a", "mcp"), retrieval_top_k=2, candidate_max_targets=40
    )
    result = await catalog.retrieve_for("anything", TraceContext.root())

    assert len(result.records) == 4
    assert {r.protocol for r in result.records} == {"a2a", "mcp"}


async def test_explicit_limit_caps_the_combined_list_keeping_both_protocols(
    fake_gateway: FakeGateway,
) -> None:
    catalog = await _catalog(fake_gateway, protocols=("a2a", "mcp"))
    result = await catalog.retrieve_for("anything", TraceContext.root(), limit=2)

    assert len(result.records) == 2
    assert {r.protocol for r in result.records} == {"a2a", "mcp"}


async def test_truncated_listing_is_flagged(fake_gateway: FakeGateway) -> None:
    """A hidden target must be visible in the note, not silently dropped."""
    catalog = await _catalog(fake_gateway, protocols=("a2a",), candidate_max_targets=2)
    result = await catalog.retrieve_for("anything", TraceContext.root())

    assert result.modes["a2a"] == "listing-truncated"
    assert "listing-truncated" in result.note


async def test_listing_that_fits_is_not_flagged_as_truncated(fake_gateway: FakeGateway) -> None:
    catalog = await _catalog(fake_gateway, protocols=("a2a",), candidate_max_targets=40)
    result = await catalog.retrieve_for("anything", TraceContext.root())

    assert result.modes["a2a"] == "listing"


# -- end to end ------------------------------------------------------------


async def test_mcp_search_result_is_executed_end_to_end(fake_gateway: FakeGateway) -> None:
    fake_gateway.mcp_tool_search_enabled = True
    service = await _service(fake_gateway, protocols=("a2a", "mcp"))

    result = await service.run("what is the status of my order?", _user())

    assert result.status == "completed"
    assert "shipped" in result.answer
    calls = tool_calls(fake_gateway)
    assert calls
    body = json.loads(calls[0].content)
    assert body["server_id"] == "orders"
    assert body["name"] == "get_order_status"


async def test_capabilities_reports_search_state(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway, protocols=("a2a", "mcp"))
    report = await service.capabilities()

    assert report["search"]["a2a"] == "not configured"
    assert report["search"]["mcp"] == "not configured"

    fake_gateway.mcp_tool_search_enabled = True
    fake_gateway.agent_search_enabled = True
    report = await service.capabilities()
    assert report["search"]["mcp"] == "available"
    assert report["search"]["a2a"] == "available"
