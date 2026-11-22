"""Agent discovery and retrieval.

Two layers, deliberately separate:

* ``all_targets()`` — the cached full catalogue, used to report capabilities and to resolve
  a record by id at execution time.
* ``retrieve_for(query)`` — **retrieval**: ask the gateway to rank agents and MCP tools
  against the user's message, so the planner only ever sees a small, relevant set.

Ranking lives in the gateway (embeddings + tool search); the orchestrator never scores
candidates itself. When a search surface is unavailable — no ``agent_search_embedding_
model``, or a key without ``mcp_tool_search_enabled`` — that protocol falls back to
listing and says so, rather than silently pretending nothing matched.

Search failures are classified, because the right response differs:

* **not configured** (no embedding model, key without tool search) — a deployment choice.
  Remembered for ``search_unavailable_ttl_s`` so it is not re-probed every turn.
* **transient** (timeout, 429, 5xx) — retried, then listed for *this turn only*. It is
  never remembered: one blip must not turn semantic search off for a minute.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace

from orchestrator.config import Settings
from orchestrator.gateway import Target, GatewayError, LiteLLMGateway
from orchestrator.observability.trace_context import TraceContext
from orchestrator.routing.rank_fusion import reciprocal_rank_fusion


# What a search surface callable looks like: a ranked list, or ``None`` for "not configured".
SearchFn = Callable[..., Awaitable["list[Target] | None"]]
# Distinguishes "this query failed after retries" from "search is not configured" (None).
_SEARCH_FAILED = object()


@dataclass(frozen=True)
class RetrievalResult:
    """What retrieval produced, plus how it was produced."""

    records: list[Target]
    modes: dict[str, str] = field(default_factory=dict)

    @property
    def note(self) -> str:
        if not self.modes:
            return f"retrieve: {len(self.records)} target(s)"
        detail = ", ".join(f"{name}={mode}" for name, mode in sorted(self.modes.items()))
        return f"retrieve: {len(self.records)} target(s) via {detail}"


class TargetCatalog:
    """What this virtual key can reach. Nothing here is configured.

    Discovery is the source of truth: whatever A2A agents and MCP servers are
    registered on the gateway *are* the catalogue. Either side may be empty or
    unreachable without affecting the other — a gateway with only MCP tools, or a key
    without MCP permission, is a normal state, not an error.
    """

    def __init__(self, gateway: LiteLLMGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings
        self._agents: list[Target] = []
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()
        self._observed: dict[str, int] = {}
        self._unavailable: dict[str, str] = {}
        # A surface that reports "search not configured" is remembered for the cache TTL,
        # so a gateway without an embedding model is not re-probed on every turn.
        self._search_off: dict[str, float] = {}

    @property
    def observed(self) -> dict[str, int]:
        """Per-protocol target counts from the last successful discovery."""
        return dict(self._observed)

    @property
    def unavailable(self) -> dict[str, str]:
        """Per-protocol reason when a surface could not be read (empty when healthy)."""
        return dict(self._unavailable)

    # -- discovery --------------------------------------------------------
    async def all_targets(self, trace: TraceContext, *, force: bool = False) -> list[Target]:
        """Everything this virtual key can reach, across every protocol."""
        async with self._lock:
            if not force and self._is_fresh():
                return self._agents

            agents = await self._discover_agents(trace)
            mcp_tools = await self._discover_mcp(trace)
            models = self._model_targets()

            self._agents = agents + mcp_tools + models
            self._observed = {
                "a2a": len(agents),
                "mcp": len(mcp_tools),
                "model": len(models),
            }
            self._fetched_at = time.monotonic()
            return self._agents

    def _model_targets(self) -> list[Target]:
        """Configured LiteLLM models, exposed as routable targets.

        Allowlisted rather than discovered: ``/v1/models`` lists every registered model,
        so auto-including them would put hundreds of entries in a planner prompt. An
        entry here is an explicit decision that a model should be a target.
        """
        return [
            Target.from_model(model, description=description)
            for model, description in self._settings.model_target_descriptions.items()
        ]

    async def _discover_agents(self, trace: TraceContext) -> list[Target]:
        try:
            listed = await self._gateway.list_agents(trace)
        except GatewayError as exc:
            # No A2A surface on this gateway (or no permission) is not fatal: MCP may
            # still be usable, and the caller only cares about the union.
            self._unavailable["a2a"] = str(exc)
            return []
        self._unavailable.pop("a2a", None)
        hydrated = await asyncio.gather(
            *(self._hydrate(agent, trace) for agent in listed),
            return_exceptions=True,
        )
        return [item for item in hydrated if isinstance(item, Target)]

    async def _discover_mcp(self, trace: TraceContext) -> list[Target]:
        if not self._settings.mcp_enabled:
            return []
        try:
            tools = await self._gateway.list_mcp_tools(trace)
        except GatewayError as exc:
            self._unavailable["mcp"] = str(exc)
            return []
        self._unavailable.pop("mcp", None)
        return tools

    async def _hydrate(self, agent: Target, trace: TraceContext) -> Target:
        """Attach the curated card. A missing card is not fatal — the record still routes."""
        if agent.is_mcp or agent.card is not None or not agent.agent_id:
            return agent
        try:
            card = await self._gateway.get_agent_card(agent.agent_id, trace)
        except GatewayError:
            return agent
        return agent.with_card(card)

    def _is_fresh(self) -> bool:
        """Whether the cached catalogue may be reused.

        Deliberately no ``bool(self._agents)`` guard: an empty registry is a valid
        result and must be cached like any other. Without this, every turn re-fetches
        from a gateway that legitimately has nothing registered, forever.
        ``_fetched_at == 0`` means "never fetched", which the age check already covers.
        """
        if not self._fetched_at:
            return False
        age = time.monotonic() - self._fetched_at
        return age < self._settings.card_cache_ttl_s

    # -- retrieval --------------------------------------------------------
    async def retrieve_for(
        self,
        query: str,
        trace: TraceContext,
        *,
        limit: int | None = None,
        queries: Sequence[str] | None = None,
    ) -> RetrievalResult:
        """Targets relevant to this message, ranked by the gateway.

        ``queries`` are the search strings to use (see ``QueryBuilder``); each is searched
        separately and the rankings are merged by reciprocal rank fusion. Without it the
        single ``query`` is searched, exactly as before.

        Falls back per protocol: if search is unavailable for one surface it is listed
        instead, so a gateway with agent search configured and tool search off still
        routes both. Modes are reported so the answer can be honest about what the
        planner could see.

        Two different caps apply, deliberately:

        * ``retrieval_top_k`` asks *search* for a shortlist — ranking makes a small list
          safe.
        * ``candidate_max_targets`` bounds a *listing*, which has no ranking, so cutting
          it short can hide the right target entirely.
        """
        search_cap = limit if limit is not None else self._settings.retrieval_top_k
        listing_cap = limit if limit is not None else self._settings.candidate_max_targets
        search_queries = [q for q in (queries or [query]) if q and q.strip()] or [query]
        catalogue = await self.all_targets(trace)
        modes: dict[str, str] = {}

        a2a = await self._retrieve_protocol(
            "a2a", self._gateway.search_agents, search_queries, trace, search_cap, listing_cap,
            catalogue, modes,
        )
        mcp = await self._retrieve_protocol(
            "mcp", self._gateway.search_mcp_tools, search_queries, trace, search_cap,
            listing_cap, catalogue, modes,
        )
        models = self._retrieve_models(catalogue, modes)

        # Models join the fan-out. They are few and explicitly allowlisted, so they are
        # always presented rather than ranked — the gate decides relevance.
        found = _interleave(_interleave(a2a, mcp), models)
        self._absorb(found)
        final_cap = search_cap if limit is not None else max(search_cap, listing_cap)
        return RetrievalResult(
            records=found[:final_cap] if final_cap and final_cap > 0 else found,
            modes=modes,
        )

    def _retrieve_models(
        self, catalogue: list[Target], modes: dict[str, str]
    ) -> list[Target]:
        """Model targets always reach the gate.

        There is no search endpoint for "which model fits this query", and the list is an
        explicit allowlist rather than a discovered catalogue, so ranking it would only
        add a way to lose a target the operator deliberately exposed.
        """
        models = [record for record in catalogue if record.is_model]
        if models:
            modes["model"] = "listing"
        return models

    async def _retrieve_protocol(
        self,
        protocol: str,
        search: SearchFn,
        queries: Sequence[str],
        trace: TraceContext,
        search_cap: int,
        listing_cap: int,
        catalogue: list[Target],
        modes: dict[str, str],
    ) -> list[Target]:
        """Search one protocol, or list it when search cannot be used."""
        enabled = self._settings.a2a_enabled if protocol == "a2a" else self._settings.mcp_enabled
        if not enabled:
            return []
        if not self._settings.retrieval_enabled or self._search_is_off(protocol):
            return self._listed(catalogue, protocol, listing_cap, modes)

        outcomes = await asyncio.gather(
            *(self._search_one(search, query, trace, search_cap) for query in queries)
        )
        rankings = [o for o in outcomes if isinstance(o, list)]
        failed = sum(1 for o in outcomes if o is _SEARCH_FAILED)

        if rankings:
            # No numeric pre-filter: the gateway ranks, the coverage gate decides.
            # A score threshold here changed no outcome and hid valid targets.
            fused_cap = search_cap * min(len(queries), 2)
            fused = reciprocal_rank_fusion(rankings, limit=fused_cap)
            mode = "search" if fused else "search-empty"
            modes[protocol] = f"{mode}-partial" if failed else mode
            return fused

        if failed:
            # Transient: list for this turn, but do not mark search off.
            return self._listed(catalogue, protocol, listing_cap, modes, after_error=True)

        # Every query got "search is not configured".
        self._search_off[protocol] = time.monotonic()
        return self._listed(catalogue, protocol, listing_cap, modes)

    async def _search_one(
        self, search: SearchFn, query: str, trace: TraceContext, top_k: int
    ) -> list[Target] | None | object:
        """One query: a ranked list, ``None`` (not configured) or ``_SEARCH_FAILED``."""
        attempts = 1 + max(self._settings.search_retries, 0)
        for attempt in range(attempts):
            try:
                return await search(query, trace, top_k=top_k)
            except GatewayError:
                if attempt + 1 < attempts:
                    await asyncio.sleep(self._settings.search_retry_backoff_s * (attempt + 1))
        return _SEARCH_FAILED

    def _listed(
        self,
        catalogue: list[Target],
        protocol: str,
        cap: int,
        modes: dict[str, str],
        *,
        after_error: bool = False,
    ) -> list[Target]:
        """Unranked fallback, reporting when the cap actually hid something.

        ``listing-truncated`` is the signal that this protocol needs search: a target
        may exist and simply not be visible, which is a materially different situation
        from ``listing`` over a catalogue that fits.
        """
        matching = [
            record
            for record in catalogue
            if (record.is_mcp if protocol == "mcp" else record.protocol == "a2a")
        ]
        truncated = cap > 0 and len(matching) > cap
        mode = "listing-truncated" if truncated else "listing"
        modes[protocol] = f"{mode}-after-search-error" if after_error else mode
        return matching[:cap] if cap and cap > 0 else matching

    def _search_is_off(self, protocol: str) -> bool:
        """Whether a search surface recently reported itself unavailable.

        Uses its own TTL, not the catalogue's: this exists to avoid re-probing a broken
        surface on every turn, which is a different trade from how long a correct agent
        list may be reused.
        """
        marked = self._search_off.get(protocol)
        if marked is None:
            return False
        return (time.monotonic() - marked) < self._settings.search_unavailable_ttl_s

    def _absorb(self, records: list[Target]) -> None:
        """Merge retrieved records into the catalogue so ``find()`` resolves them.

        Search returns a slightly different shape than listing (prefixed names, no
        card), so a retrieved record replaces the cached one rather than sitting
        beside it. If a search result lacks the agent card that listing had, the cached
        card is kept: a thinner record must not erase what the planner and the gate use.
        """
        if not records:
            return
        by_id = {record.agent_id: record for record in self._agents}
        for record in records:
            cached = by_id.get(record.agent_id)
            if cached is not None and cached.card is not None and record.card is None:
                record = replace(
                    record,
                    card=cached.card,
                    skills=record.skills or cached.skills,
                    protocol_version=record.protocol_version or cached.protocol_version,
                    url=record.url or cached.url,
                )
            by_id[record.agent_id] = record
        self._agents = list(by_id.values())

    # -- lookup -----------------------------------------------------------
    def cached_targets(self, limit: int | None = None) -> list[Target]:
        """The cached catalogue, capped so one prompt stays bounded."""
        cap = limit if limit is not None else self._settings.candidate_max_targets
        return self._agents[:cap] if cap and cap > 0 else list(self._agents)

    def find(self, agent_id: str = "", agent_name: str = "") -> Target | None:
        for agent in self._agents:
            if agent_id and agent.agent_id == agent_id:
                return agent
            if agent_name and agent.agent_name == agent_name:
                return agent
        return None


def _interleave(a2a: list[Target], mcp: list[Target]) -> list[Target]:
    """Round-robin two ranked lists so neither protocol can starve the other.

    Concatenating would mean a large A2A registry hides every MCP tool once a cap
    applies; interleaving guarantees both surfaces are represented.
    """
    merged: list[Target] = []
    for index in range(max(len(a2a), len(mcp))):
        if index < len(a2a):
            merged.append(a2a[index])
        if index < len(mcp):
            merged.append(mcp[index])
    return merged
