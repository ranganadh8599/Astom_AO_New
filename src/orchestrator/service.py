"""Service facade: one long-lived gateway, one compiled graph, one catalog."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from orchestrator.auth import UserContext
from orchestrator.routing.target_catalog import TargetCatalog
from orchestrator.config import ConfigurationError, Settings
from orchestrator.gateway import Target, GatewayError, LiteLLMGateway
from orchestrator.graph import build_graph, open_checkpointer
from orchestrator.observability.langfuse_tracer import Tracer, build_tracer, update as update_span
from orchestrator.observability.trace_context import Lineage, TraceContext

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelCheck:
    """Outcome of the background model check.

    Deliberately not an exception: a running process should not die because a model
    name is wrong. It should be *visible*, and `/health` is where a platform looks.
    """

    status: str = "pending"  # pending | ok | degraded | failed
    warnings: tuple[str, ...] = ()
    error: str = ""
    checked_at: float = 0.0

    @property
    def serves_traffic(self) -> bool:
        """Whether this instance should receive requests.

        Only a *rejected* model disqualifies it: that is a configuration fault which no
        retry fixes, so every turn would fail. ``degraded`` means the check could not
        reach the gateway — the gateway may be fine, so pulling this instance from
        rotation would turn one blip into a full outage.
        """
        return self.status != "failed"

    @property
    def healthy(self) -> bool:
        return self.status in ("ok", "pending")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "warnings": list(self.warnings),
            "error": self.error,
            "checked_at": self.checked_at,
        }


@dataclass
class RunResult:
    run_id: str
    answer: str
    status: str
    trace_id: str
    conversation_id: str = ""
    denied: bool = False
    tasks: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "answer": self.answer,
            "error": self.error,
            "trace_id": self.trace_id,
            "conversation_id": self.conversation_id,
            "denied": self.denied,
            "tasks": self.tasks,
            "results": self.results,
            "notes": self.notes,
        }


class OrchestratorService:
    def __init__(self, settings: Settings, *, gateway: LiteLLMGateway | None = None) -> None:
        self.settings = settings
        self._gateway = gateway
        self._catalog: TargetCatalog | None = None
        self._graph = None
        self._owns_gateway = gateway is None
        self._tracer: Tracer = build_tracer(settings)
        self._checkpoint_cm = None
        self._model_check = ModelCheck()
        # Replaced on __aenter__ with the real probe; a memory default keeps type
        # checkers and early callers honest.
        from orchestrator.graph.checkpointer import CheckpointerHealth

        self._memory_health: CheckpointerHealth = CheckpointerHealth(
            (settings.checkpoint_backend or "memory").lower()
        )

    async def __aenter__(self) -> "OrchestratorService":
        if self._gateway is None:
            self._gateway = await LiteLLMGateway(
                self.settings, tracer=self._tracer
            ).__aenter__()
        self._checkpoint_cm = open_checkpointer(self.settings)
        checkpointer, self._memory_health = await self._checkpoint_cm.__aenter__()
        self._catalog = TargetCatalog(self._gateway, self.settings)
        self._graph = build_graph(
            self.settings, self._gateway, self._catalog, checkpointer
        )
        # No gateway calls here on purpose: startup must not depend on the gateway
        # answering. Discovery happens on demand (first request) and the capability
        # report is produced by the background boot check.
        return self

    async def _probe_capabilities(self) -> None:
        """Report what the gateway has registered. Called from the background boot task.

        This is discovery, not configuration: whatever the key can see is what the
        orchestrator will route to. It runs after startup so a slow gateway cannot delay
        boot, and a gateway that is still warming up produces a warning, not a failure.
        """
        try:
            report = await self.capabilities(probe_search=False)
        except Exception as exc:  # pragma: no cover - gateway warming up
            log.warning("capability probe skipped: %s", exc)
            return

        found = ", ".join(
            f"{name}={details['count']}" for name, details in report["protocols"].items()
        ) or "none"
        log.info("gateway targets discovered: %s", found)
        for name, reason in report["unavailable"].items():
            log.info("protocol %s unavailable: %s", name, reason)

    async def run_boot_checks(self) -> "ModelCheck":
        """Everything that should be known shortly after startup, off the boot path.

        Ordered deliberately: discovery first (it is cheap and reports what exists),
        then the model check. Neither can abort the process.
        """
        await self._probe_capabilities()
        return await self.run_preflight()

    async def __aexit__(self, *exc_info: object) -> None:
        if self._checkpoint_cm is not None:
            await self._checkpoint_cm.__aexit__(*exc_info)
            self._checkpoint_cm = None
        if self._owns_gateway and self._gateway is not None:
            await self._gateway.__aexit__(*exc_info)
        self._tracer.flush()

    @property
    def gateway(self) -> LiteLLMGateway:
        if self._gateway is None:
            raise RuntimeError("OrchestratorService used outside its async context")
        return self._gateway

    @property
    def catalog(self) -> TargetCatalog:
        if self._catalog is None:
            raise RuntimeError("OrchestratorService used outside its async context")
        return self._catalog

    @property
    def tracer(self) -> Tracer:
        return self._tracer

    # -- model preflight --------------------------------------------------
    @property
    def model_check(self) -> "ModelCheck":
        """Result of the background model check. Safe to read at any time."""
        return self._model_check

    @property
    def memory_health(self) -> "CheckpointerHealth":
        """Connectivity probe for the checkpointer. ``/ready`` calls ``probe()``."""
        return self._memory_health

    async def run_preflight(self, trace: TraceContext | None = None) -> "ModelCheck":
        """Run the model check and record the outcome instead of raising.

        Used by the background task: a rejected model must not take down a running
        process, but it must be visible. The result is exposed on ``/health`` so a
        platform can decide whether to alert or roll back.
        """
        warnings: list[str] = []
        error = ""
        status = "ok"
        try:
            warnings = await self.preflight_models(trace)
            if warnings:
                status = "degraded"
        except ConfigurationError as exc:
            status = "failed"
            error = str(exc)
        except Exception as exc:  # pragma: no cover - defensive
            status = "degraded"
            warnings.append(f"model check failed unexpectedly: {exc}")

        self._model_check = ModelCheck(
            status=status,
            warnings=tuple(warnings),
            error=error,
            checked_at=time.time(),
        )
        return self._model_check

    async def preflight_models(
        self, trace: TraceContext | None = None
    ) -> list[str]:
        """Check the configured models against the gateway.

        Returns warnings, raises ``ConfigurationError`` when the gateway *rejects* a
        model — a 404/403 means the name is wrong or the key may not use it, which no
        amount of retrying will fix. Transport failures degrade to warnings: a gateway
        that is briefly down must not be reported as a configuration error.
        """
        if not self.settings.model_preflight_enabled:
            return []

        resolved = trace or TraceContext.root()
        warnings: list[str] = []

        advertised: list[str] = []
        try:
            advertised = await self.gateway.list_models(resolved)
        except GatewayError:
            warnings.append(
                "/v1/models unavailable; skipped the model-name cross-check"
            )

        requested = {
            self.settings.planner_model,
            self.settings.effective_gate_model,
        }
        for model in sorted(m for m in requested if m):
            verdict, detail = await self.gateway.probe_model(model, resolved)
            if verdict == "rejected":
                raise ConfigurationError(
                    f"gateway rejected model {model!r}: {detail}. "
                    "Set PLANNER_MODEL/GATE_MODEL to a model the key may call."
                )
            if verdict == "unavailable":
                warnings.append(
                    f"could not verify model {model!r} ({detail}); continuing"
                )
                continue
            if advertised and model not in advertised:
                # Permitted but unlisted: legitimate for wildcard keys, so only a hint.
                warnings.append(
                    f"model {model!r} answered but is not listed by /v1/models; "
                    "the key probably allows it by wildcard pattern"
                )

        return warnings

    async def capabilities(self, trace: TraceContext | None = None, *, probe_search: bool = True) -> dict[str, Any]:
        """What the gateway says is registered right now.

        This is the "identify what exists" step: no configuration is read, the gateway
        is the source of truth. Surfaces that cannot be read are reported with the
        reason instead of failing the call. ``search`` reports, per protocol, whether
        retrieval is live or whether that surface is being listed instead.

        ``probe_search=False`` skips the two live search calls, for startup logging
        where an extra round trip (and an unrelated trace) is not wanted.
        """
        resolved = trace or TraceContext.root()
        records = await self.catalog.all_targets(resolved)
        by_protocol: dict[str, list[str]] = {}
        for record in records:
            by_protocol.setdefault(record.protocol, []).append(record.agent_name)

        search: dict[str, str] = {}
        if probe_search and self.settings.retrieval_enabled:
            probe = "what can you help with"
            try:
                if self.settings.a2a_enabled:
                    ranked = await self.gateway.search_agents(probe, resolved, top_k=3)
                    search["a2a"] = "available" if ranked is not None else "not configured"
                if self.settings.mcp_enabled:
                    ranked = await self.gateway.search_mcp_tools(probe, resolved, top_k=3)
                    search["mcp"] = "available" if ranked is not None else "not configured"
            except GatewayError as exc:
                search["error"] = str(exc)

        return {
            "total": len(records),
            "protocols": {name: {"count": len(items), "targets": items}
                          for name, items in sorted(by_protocol.items())},
            "unavailable": self.catalog.unavailable,
            "search": search,
        }

    async def list_agents(self, trace: TraceContext | None = None) -> list[Target]:
        return await self.catalog.all_targets(trace or TraceContext.root())

    async def run(
        self,
        query: str,
        user: UserContext,
        *,
        session_id: str = "",
        inbound_headers: Mapping[str, str] | None = None,
        refresh_catalog: bool = False,
    ) -> RunResult:
        if self._graph is None:
            raise RuntimeError("OrchestratorService used outside its async context")

        # One trace for the whole conversation: the trace id is derived from the
        # conversation id, so every turn joins the same Langfuse trace and the same
        # W3C trace. An explicit inbound traceparent still wins.
        trace = TraceContext.from_headers(
            inbound_headers or {},
            session_id=session_id,
            per_conversation=self.settings.trace_per_conversation,
        )
        lineage = Lineage.root()
        run_id = uuid.uuid4().hex
        thread_id = session_id or run_id

        if refresh_catalog:
            await self.catalog.all_targets(trace, force=True)

        initial_state = {
            "run_id": run_id,
            "session_id": session_id,
            "user_query": query,
            "user": user.to_state(),
            "trace": {
                "trace_id": trace.trace_id,
                "span_id": trace.span_id,
                "trace_flags": trace.trace_flags,
                "trace_state": trace.trace_state,
                "session_id": session_id,
            },
            "lineage": lineage.describe(),
            "status": "running",
            "max_agents": self.settings.max_agents_per_request,
        }

        user_id = str(getattr(user, self.settings.langfuse_user_id_field, "") or user.oid or "")
        with self._tracer.turn(
            trace,
            name="orchestrator.turn",
            session_id=session_id,
            user_id=user_id,
            input={"message": query},
            metadata={"conversation_id": session_id, "run_id": run_id},
        ) as span:
            final_state = await self._graph.ainvoke(
                initial_state,
                config={"configurable": {"thread_id": thread_id}},
            )
            update_span(
                span,
                output={
                    "status": final_state.get("status"),
                    "answer": final_state.get("answer"),
                },
            )

        status = str(final_state.get("status") or "failed")
        return RunResult(
            run_id=run_id,
            answer=str(final_state.get("answer") or ""),
            status=status,
            trace_id=trace.trace_id,
            conversation_id=session_id,
            denied=status == "rejected",
            tasks=list(final_state.get("tasks") or []),
            results=list(final_state.get("results") or []),
            notes=list(final_state.get("notes") or []),
            error=str(final_state.get("error") or ""),
        )
