"""Search failures are classified: "not configured" is remembered, "broken" is not.

Before this, any error from a search surface switched search off for a minute and the
turn fell back to a truncated listing. A single timeout therefore degraded every request
in that window. These tests pin the corrected behaviour, plus multi-query search.
"""

from __future__ import annotations

from orchestrator.gateway import LiteLLMGateway
from orchestrator.observability.trace_context import TraceContext
from orchestrator.routing.target_catalog import TargetCatalog
from tests.conftest import FakeGateway, make_settings


def _catalog(fake: FakeGateway, **overrides) -> TargetCatalog:
    settings = make_settings(**overrides)
    return TargetCatalog(LiteLLMGateway(settings, client=fake.client()), settings)


def _agent_searches(fake: FakeGateway) -> list[str]:
    return list(fake.agent_search_queries)


# -- transient failures ------------------------------------------------------


async def test_one_transient_error_is_retried_and_search_still_wins(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.agent_search_enabled = True
    fake_gateway.agent_search_errors = 1
    catalog = _catalog(fake_gateway, search_retries=1)

    result = await catalog.retrieve_for("leave policy", TraceContext.root())

    assert result.modes["a2a"] == "search"
    assert len(_agent_searches(fake_gateway)) == 2  # the failure, then the retry


async def test_persistent_errors_list_this_turn_but_do_not_switch_search_off(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.agent_search_enabled = True
    fake_gateway.agent_search_errors = 2  # first turn: initial try + one retry both fail
    catalog = _catalog(fake_gateway, search_retries=1)

    first = await catalog.retrieve_for("leave policy", TraceContext.root())
    second = await catalog.retrieve_for("leave policy", TraceContext.root())

    assert first.modes["a2a"] == "listing-after-search-error"
    assert first.records, "the turn still gets targets"
    # Search is tried again on the very next turn instead of staying off for 60 s.
    assert second.modes["a2a"] == "search"


async def test_no_retries_configured_means_one_attempt(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    fake_gateway.agent_search_errors = 1
    catalog = _catalog(fake_gateway, search_retries=0)

    result = await catalog.retrieve_for("leave policy", TraceContext.root())

    assert result.modes["a2a"] == "listing-after-search-error"
    assert len(_agent_searches(fake_gateway)) == 1


async def test_not_configured_is_still_remembered(fake_gateway: FakeGateway) -> None:
    catalog = _catalog(fake_gateway)  # agent search not configured on the fake gateway

    await catalog.retrieve_for("first", TraceContext.root())
    await catalog.retrieve_for("second", TraceContext.root())

    assert len(_agent_searches(fake_gateway)) == 1  # probed once, not every turn


# -- several queries ----------------------------------------------------------


async def test_each_query_is_searched_and_results_are_merged(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    fake_gateway.rank_by_overlap = True
    catalog = _catalog(fake_gateway, retrieval_top_k=1)

    result = await catalog.retrieve_for(
        "leave and vpn", TraceContext.root(), queries=["leave policy", "vpn access"]
    )

    assert sorted(_agent_searches(fake_gateway)) == ["leave policy", "vpn access"]
    names = {t.agent_name for t in result.records}
    # top_k=1 per query, so a single merged query would have kept only one of these.
    assert {"hr-policy-agent", "it-support-agent"} <= names
    assert result.modes["a2a"] == "search"


async def test_one_failed_query_does_not_discard_the_others(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    fake_gateway.agent_search_errors = 1  # exactly one of the two searches fails
    catalog = _catalog(fake_gateway, search_retries=0)

    result = await catalog.retrieve_for(
        "leave and vpn", TraceContext.root(), queries=["leave policy", "vpn access"]
    )

    assert result.modes["a2a"] == "search-partial"
    assert result.records


async def test_a_single_query_behaves_exactly_as_before(fake_gateway: FakeGateway) -> None:
    fake_gateway.agent_search_enabled = True
    catalog = _catalog(fake_gateway)

    plain = await catalog.retrieve_for("leave policy", TraceContext.root())
    explicit = await catalog.retrieve_for(
        "leave policy", TraceContext.root(), queries=["leave policy"]
    )

    assert [t.agent_id for t in plain.records] == [t.agent_id for t in explicit.records]


# -- cached cards survive search ------------------------------------------------


async def test_search_does_not_erase_the_cached_card(fake_gateway: FakeGateway) -> None:
    from orchestrator.gateway import Target

    fake_gateway.agent_search_enabled = True
    catalog = _catalog(fake_gateway)
    listed = await catalog.all_targets(TraceContext.root())
    hr = next(t for t in listed if t.agent_id == "hr-1")
    assert hr.card is not None

    thin = Target(agent_id="hr-1", agent_name="hr-policy-agent", description="x", search_score=0.5)
    catalog._absorb([thin])

    kept = catalog.find(agent_id="hr-1")
    assert kept is not None and kept.card is not None and kept.search_score == 0.5
