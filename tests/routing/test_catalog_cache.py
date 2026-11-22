"""Catalogue caching.

Two regressions this pins, both found by counting gateway calls rather than reading code:

1. An **empty** registry was refetched on every turn. ``_is_fresh`` required
   ``bool(self._agents)``, so "no agents registered" was indistinguishable from
   "cache cold" and every turn paid for discovery forever.
2. The catalogue TTL and the "search surface unavailable" TTL were the **same number**.
   Lowering one to get fresher agent lists also made a broken search surface re-probe
   more often — extra gateway calls nobody asked for.
"""

from __future__ import annotations

import asyncio

import httpx

from orchestrator.routing.target_catalog import TargetCatalog
from orchestrator.config import Settings
from orchestrator.gateway import LiteLLMGateway
from orchestrator.observability.trace_context import TraceContext

AGENT = {
    "agent_id": "a1",
    "agent_name": "agent-1",
    "description": "test agent",
    "agent_card_params": {"name": "agent-1", "description": "test agent"},
}


class CountingGateway:
    """Counts discovery and search calls separately."""

    def __init__(self, agents: list[dict], *, search_available: bool = True) -> None:
        self.agents = agents
        self.search_available = search_available
        self.list_calls = 0
        self.search_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/agents":
            if request.url.params.get("query"):
                self.search_calls += 1
                if not self.search_available:
                    return httpx.Response(
                        400,
                        json={"detail": {"error": "agent_search_not_configured"}},
                    )
                return httpx.Response(200, json=self.agents)
            self.list_calls += 1
            return httpx.Response(200, json=self.agents)
        if path == "/v1/mcp/server":
            return httpx.Response(200, json={"data": []})
        if path.endswith("/.well-known/agent-card.json"):
            return httpx.Response(404)
        return httpx.Response(404)


def _catalog(counter: CountingGateway, **overrides) -> TargetCatalog:
    settings = Settings(
        litellm_base_url="http://gateway.test",
        litellm_api_key="sk-test",
        protocols=("a2a",),
        **overrides,
    )
    client = httpx.AsyncClient(
        base_url="http://gateway.test",
        transport=httpx.MockTransport(counter.handler),
    )
    return TargetCatalog(LiteLLMGateway(settings, client=client), settings)


async def test_empty_registry_is_cached_like_any_other_result() -> None:
    """A gateway with nothing registered must not be polled on every turn."""
    counter = CountingGateway([])
    catalog = _catalog(counter, card_cache_ttl_s=300, retrieval_enabled=False)
    trace = TraceContext.root()

    for _ in range(4):
        assert await catalog.all_targets(trace) == []

    assert counter.list_calls == 1


async def test_empty_registry_refetches_after_the_ttl() -> None:
    counter = CountingGateway([])
    catalog = _catalog(counter, card_cache_ttl_s=0.15, retrieval_enabled=False)
    trace = TraceContext.root()

    await catalog.all_targets(trace)
    await asyncio.sleep(0.25)
    await catalog.all_targets(trace)

    assert counter.list_calls == 2


async def test_populated_registry_still_caches() -> None:
    counter = CountingGateway([AGENT])
    catalog = _catalog(counter, card_cache_ttl_s=300, retrieval_enabled=False)
    trace = TraceContext.root()

    await catalog.all_targets(trace)
    await catalog.all_targets(trace)

    assert counter.list_calls == 1


async def test_search_unavailable_ttl_is_independent_of_the_catalogue_ttl() -> None:
    """Only the search probe retries; the catalogue stays cached."""
    counter = CountingGateway([AGENT], search_available=False)
    catalog = _catalog(
        counter,
        card_cache_ttl_s=300,
        search_unavailable_ttl_s=0.15,
        retrieval_enabled=True,
    )
    trace = TraceContext.root()

    await catalog.retrieve_for("first", trace)
    after_first = counter.search_calls
    await catalog.retrieve_for("second", trace)
    assert counter.search_calls == after_first, "should be skipped while marked unavailable"

    await asyncio.sleep(0.25)
    await catalog.retrieve_for("third", trace)
    assert counter.search_calls > after_first, "should re-probe after its own TTL"

    # The catalogue TTL (300s) means the agent listing was fetched once.
    assert counter.list_calls == 1
