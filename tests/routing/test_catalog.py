"""Discovery without a network: caching, protocol union, capability reporting."""

from __future__ import annotations

from orchestrator.routing.target_catalog import TargetCatalog
from orchestrator.config import Settings
from orchestrator.observability.trace_context import TraceContext
from tests.conftest import make_settings


async def test_cards_hydrate_skills(gateway, settings) -> None:
    catalog = TargetCatalog(gateway, settings)
    agents = await catalog.all_targets(TraceContext.root())
    assert len(agents) == 3
    assert all(agent.skills for agent in agents), "cards should hydrate skills"


async def test_targets_are_capped_but_not_reordered(gateway) -> None:
    """No relevance ranking: the planner sees a bounded, stable list."""
    catalog = TargetCatalog(gateway, make_settings(candidate_max_targets=2))
    agents = await catalog.all_targets(TraceContext.root())

    targets = catalog.cached_targets()
    assert len(targets) == 2
    assert [t.agent_name for t in targets] == [a.agent_name for a in agents[:2]]


async def test_catalog_is_cached(gateway, fake_gateway) -> None:
    catalog = TargetCatalog(gateway, make_settings())
    trace = TraceContext.root()
    await catalog.all_targets(trace)
    calls_after_first = len(fake_gateway.requests)
    await catalog.all_targets(trace)
    assert len(fake_gateway.requests) == calls_after_first


async def test_missing_card_does_not_drop_the_agent(gateway) -> None:
    catalog = TargetCatalog(gateway, make_settings())
    agents = await catalog.all_targets(TraceContext.root())
    assert {agent.agent_name for agent in agents} == {
        "hr-policy-agent",
        "finance-agent",
        "it-support-agent",
    }


async def test_mcp_tools_join_the_same_catalog(fake_gateway) -> None:
    from orchestrator.gateway import LiteLLMGateway

    settings = make_settings(protocols=("a2a", "mcp"))
    gateway = LiteLLMGateway(settings, client=fake_gateway.client())
    catalog = TargetCatalog(gateway, settings)
    agents = await catalog.all_targets(TraceContext.root())

    assert {agent.protocol for agent in agents} == {"a2a", "mcp"}
    mcp = [agent for agent in agents if agent.protocol == "mcp"]
    assert mcp[0].tool_name == "get_order_status"
    assert mcp[0].server_id == "orders"
    assert mcp[0].argument_names == ("order_id",)

    # MCP tools have no A2A card: they must not be hydrated as agents.
    assert mcp[0].card is None
    assert mcp[0].skills == ()


async def test_mcp_discovery_is_skipped_when_the_protocol_is_off(fake_gateway) -> None:
    from orchestrator.gateway import LiteLLMGateway

    settings = make_settings(protocols=("a2a",))
    gateway = LiteLLMGateway(settings, client=fake_gateway.client())
    catalog = TargetCatalog(gateway, settings)
    await catalog.all_targets(TraceContext.root())
    assert not [
        request
        for request in fake_gateway.requests
        if request.url.path.startswith("/mcp-rest/") or request.url.path == "/v1/mcp/server"
    ]


async def test_forbidden_mcp_surface_does_not_break_a2a_discovery(fake_gateway) -> None:
    """A key without MCP permission is a normal deployment, not an outage."""
    from orchestrator.gateway import LiteLLMGateway

    fake_gateway.mcp_discovery_status = 403
    settings = make_settings(protocols=("a2a", "mcp"))
    gateway = LiteLLMGateway(settings, client=fake_gateway.client())
    catalog = TargetCatalog(gateway, settings)

    agents = await catalog.all_targets(TraceContext.root())

    assert {agent.protocol for agent in agents} == {"a2a"}
    assert "mcp" in catalog.unavailable
    assert "403" in catalog.unavailable["mcp"]


async def test_discovery_is_automatic_with_default_settings(fake_gateway) -> None:
    """No protocol list, no server list: whatever the gateway has is the catalogue."""
    from orchestrator.gateway import LiteLLMGateway

    settings = Settings(litellm_base_url="http://gateway.test", litellm_api_key="sk-test")
    gateway = LiteLLMGateway(settings, client=fake_gateway.client())
    catalog = TargetCatalog(gateway, settings)

    agents = await catalog.all_targets(TraceContext.root())

    assert {agent.protocol for agent in agents} == {"a2a", "mcp"}
    assert catalog.observed == {"a2a": 3, "mcp": 1, "model": 0}
