"""Graph nodes, in execution order (wired together in ``graph/build.py``):

    validate_input -> retrieve_targets -> check_coverage -> plan_tasks
                   -> run_task (one per task, in parallel) -> compose_answer

One model decides routing. ``plan_tasks`` sends the user's message, the recent conversation
and the retrieved targets to the planner, and the planner returns both the intent
(``read`` or ``mutation``) and the task list. There is no local decomposition, no keyword
scoring and no argument extraction: if the planner cannot be reached the turn fails rather
than silently degrading to a guess.

``compose_answer`` is deterministic on purpose. It preserves attribution, cannot invent
facts, and passes a single result through untouched.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from langgraph.types import Send

from orchestrator.routing import read_only_policy, smalltalk
from orchestrator.routing.query_builder import QueryBuilder
from orchestrator.routing.target_catalog import TargetCatalog
from orchestrator.config import Settings
from orchestrator.gateway import InvocationResult, Target, GatewayError, LiteLLMGateway
from orchestrator.routing.coverage_gate import CoverageGate
from orchestrator.observability.trace_context import Lineage, TraceContext
from orchestrator.graph.state import RESET, OrchestratorState, TaskSpec

log = logging.getLogger(__name__)

MAX_QUERY_CHARS = 8000

_PLANNER_SYSTEM = """You are the routing planner for a read-only enterprise assistant.

You receive the user's latest message, the recent conversation, and the targets currently
registered on the gateway. A target is an A2A agent ([a2a]), a single MCP tool ([mcp]), or
an assistant model ([model]); you never choose a protocol, only the best target.

Do two things.

1. Classify the intent of the user's message:
   - "read": answering a question, looking something up, explaining, summarising,
     checking a status, or asking how something is done.
   - "mutation": asking you to create, change, update, delete, remove, cancel, approve,
     reject, assign, submit, schedule or otherwise modify anything.
   "How do I update my address?" is "read". "Update my address" is "mutation".

2. Break the message into the minimum set of independent tasks, assigning each task to
   the single best target. For an [mcp] target always include an "arguments" object that
   supplies every argument the tool needs, using values from the message or the
   conversation. For an [a2a] target omit "arguments".

Rules:
- Use only targets exactly as listed. Never invent one.
- Never exceed the stated maximum number of tasks.
- If nothing fits, return an empty task list.
- For "mutation" always return an empty task list.
- A "relevance" number may be shown per target. It is the gateway's cosine similarity
  between the request and the tool or agent text. Treat it as a hint, not proof: use it
  to break ties between plausible targets, never to justify a target that does not fit.

Reply with JSON only, in exactly this shape:
{"intent": "read" | "mutation", "reason": "<one short sentence>", "tasks": [{"agent": "<target name exactly as listed>", "instruction": "<self-contained instruction>", "arguments": {}}]}"""


def _trace_from_state(state: OrchestratorState) -> TraceContext:
    raw = state.get("trace") or {}
    return TraceContext(
        trace_id=str(raw.get("trace_id") or TraceContext.root().trace_id),
        span_id=str(raw.get("span_id") or ""),
        trace_flags=int(raw.get("trace_flags") or 1),
        trace_state=str(raw.get("trace_state") or ""),
        session_id=str(raw.get("session_id") or state.get("session_id") or ""),
    )


def _lineage_from_state(state: OrchestratorState) -> Lineage:
    raw = state.get("lineage") or {}
    chain = raw.get("chain") or []
    return Lineage(
        top_level_turn_id=str(raw.get("top_level_turn_id") or ""),
        parent_agent=str(raw.get("parent_agent") or ""),
        depth=int(raw.get("depth") or 0),
        chain=tuple(str(item) for item in chain),
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object out of a model reply, tolerating code fences and prose.

    Pure string handling: strip surrounding fences, else take the outermost braces.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


class OrchestratorNodes:
    def __init__(
        self,
        *,
        settings: Settings,
        gateway: LiteLLMGateway,
        catalog: TargetCatalog,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._catalog = catalog
        self._gate = CoverageGate(gateway, settings.effective_gate_model)
        self._query_builder = (
            QueryBuilder(
                gateway,
                settings.effective_rewrite_model,
                max_queries=settings.query_rewrite_max_queries,
            )
            if settings.can_rewrite_queries
            else None
        )

    # -- validate_input ------------------------------------------------
    async def validate_input(self, state: OrchestratorState) -> dict[str, Any]:
        """Input gate. Shape and limits only.

        Intent is decided by the planner, so this node cannot itself refuse a mutation;
        it clears the per-turn keys and rejects empty or oversized input.
        """
        query = (state.get("user_query") or "").strip()
        reset: dict[str, Any] = {
            "results": [RESET],
            "notes": [RESET],
            "tasks": [],
            "candidates": [],
            "coverage": {},
            "answer": "",
            "error": "",
        }

        if not query:
            return {
                **reset,
                "status": "failed",
                "error": "empty user query",
                "notes": [RESET, "input: empty query"],
            }

        if len(query) > MAX_QUERY_CHARS:
            return {
                **reset,
                "status": "failed",
                "error": f"query exceeds {MAX_QUERY_CHARS} characters",
                "notes": [RESET, "input: query too long"],
                "history": [{"role": "user", "content": query}],
            }

        return {
            **reset,
            "status": "running",
            "user_query": query,
            "notes": [RESET, f"input: accepted {len(query)} chars"],
            "history": [{"role": "user", "content": query}],
        }

    # -- retrieve_targets ----------------------------------------------
    async def retrieve_targets(self, state: OrchestratorState) -> dict[str, Any]:
        if state.get("status") in ("failed", "rejected"):
            return {}
        trace = _trace_from_state(state)

        # A leading greeting is stripped before retrieval so "hi, what is the leave
        # policy?" is treated as the question it is. Smalltalk on its own never reaches
        # here — `validate_input` answers it.
        query = smalltalk.strip_leading_greeting(state.get("user_query", ""))
        notes: list[str] = []
        if query != state.get("user_query", ""):
            state["user_query"] = query
            notes.append(f"retrieve: stripped leading greeting")

        # Follow-ups are made standalone and multi-question messages are split, so search
        # sees what the user means rather than the literal text (see QueryBuilder).
        search_queries: tuple[str, ...] = (query,)
        if self._query_builder is not None:
            built = await self._query_builder.build(
                query,
                history=self._history_block(state, user_only=True),
                trace=trace,
                lineage=_lineage_from_state(state),
            )
            if built.queries:
                search_queries = built.queries
            if built.note:
                notes.append(f"retrieve: {built.note}")
            if built.rewritten:
                notes.append("retrieve: search queries: " + " | ".join(built.queries))

        try:
            result = await self._catalog.retrieve_for(query, trace, queries=search_queries)
        except GatewayError as exc:
            return {"status": "failed", "error": f"agent discovery failed: {exc}"}

        candidates = [
            {
                "agent_id": agent.agent_id,
                "agent_name": agent.agent_name,
                "description": agent.description,
                "protocol": agent.protocol,
                "server_id": agent.server_id,
                "tool_name": agent.tool_name,
            }
            for agent in result.records
        ]

        if not candidates:
            # Retrieval genuinely found nothing. That is only a failure if the catalogue
            # itself is empty; an empty search over a populated registry is a routing
            # miss the planner should explain, not a crash.
            #
            # No `failed` status here even when the catalogue is empty: `check_coverage` runs
            # next and can still answer smalltalk. Failing first would turn "hi" into
            # "no agents available", which is both wrong and confusing.
            catalogue = self._catalog.cached_targets()
            notes.append(result.note)
            if not catalogue:
                notes.append("retrieve: catalogue is empty")
            return {"candidates": [], "notes": notes}

        return {"candidates": candidates, "notes": [*notes, result.note]}

    # -- check_coverage ------------------------------------------------
    async def check_coverage(self, state: OrchestratorState) -> dict[str, Any]:
        """Ask the coverage gate whether any candidate can answer this.

        A ``no_match`` verdict ends the turn with an explanation and no routing — that
        is the outcome the planner cannot reliably produce on its own. If the gate
        cannot be consulted, the turn continues: the planner still declines, and a
        degraded gate must not become an outage.
        """
        if state.get("status") != "running":
            return {}

        candidates = state.get("candidates") or []

        # Greetings, thanks and "what can you do?" never need a model call or a target.
        # Answered here so they cost nothing and never surface as "nothing covers that".
        # Runs before the gate: this is deterministic and cannot misroute.
        if self._settings.smalltalk_enabled:
            user = state.get("user") or {}
            small = smalltalk.detect(
                state.get("user_query", ""),
                capabilities_reply=self._settings.smalltalk_capabilities_reply,
                # Personalised when the name is usable; an email or opaque id greets
                # neutrally rather than by identifier.
                user_name=str(user.get("name") or ""),
            )
            if small is not None:
                message = small.reply
                return {
                    "status": "completed",
                    "answer": message,
                    "tasks": [],
                    "coverage": {"outcome": "smalltalk", "reason": small.kind},
                    "notes": [f"coverage: smalltalk ({small.kind})"],
                    "history": [{"role": "assistant", "content": message}],
                }

        # "hi, what is our leave policy?" is a question with a greeting glued on. The
        # greeting is noise for retrieval, the gate and the planner, which otherwise
        # judge the whole sentence as smalltalk and find no coverage.
        query = smalltalk.strip_leading_greeting(state.get("user_query", ""))
        if query != state.get("user_query", ""):
            state["user_query"] = query
            return {
                "notes": [f"retrieve: stripped greeting -> {query[:60]!r}"],
            }

        if not (self._settings.coverage_gate_enabled and self._settings.can_gate_with_model):
            return {"coverage": {"outcome": "skipped", "reason": "gate disabled"}}

        targets = [
            record
            for record in (self._catalog.find(agent_id=item["agent_id"]) for item in candidates)
            if record is not None
        ]
        verdict = await self._gate.assess(
            state.get("user_query", ""),
            targets,
            trace=_trace_from_state(state),
            lineage=_lineage_from_state(state),
            history=self._history_block(state, user_only=True),
        )

        if verdict is None:
            return {
                "coverage": {"outcome": "unavailable", "reason": "gate call failed"},
                "notes": ["coverage: gate unavailable, continuing to plan"],
            }

        # A mutation verdict must produce the read-only refusal, not a coverage message.
        # Deciding this here keeps the refusal independent of whether any target exists.
        if self._settings.read_only_mode and read_only_policy.is_mutation(verdict.intent):
            message = read_only_policy.denial_message(self._settings, verdict.reason)
            return {
                "status": "rejected",
                "answer": message,
                "tasks": [],
                "coverage": {
                    "outcome": "mutation",
                    "reason": verdict.reason,
                    "confidence": verdict.confidence,
                },
                "notes": [f"coverage: refused ({verdict.reason or 'mutation intent'})"],
                "history": [{"role": "assistant", "content": message}],
            }

        notes = list(verdict.notes)

        if verdict.is_smalltalk:
            # `looks_like_request` is enforced in the gate, which turns such a verdict into
            # a coverage miss before it gets here. This is the remaining social case.
            user = state.get("user") or {}
            small = smalltalk.neutral_reply(
                user_name=str(user.get("name") or ""),
                capabilities_reply=self._settings.smalltalk_capabilities_reply,
            )
            return {
                "status": "completed",
                "answer": small.reply,
                "tasks": [],
                "coverage": {
                    "outcome": "smalltalk",
                    "reason": verdict.reason,
                    "confidence": verdict.confidence,
                },
                "notes": [*notes, "coverage: smalltalk (gate)"],
                "history": [{"role": "assistant", "content": small.reply}],
            }
        if verdict.is_no_match:
            # Without a reason, do not invent one: "Why:" followed by a restatement of the
            # first line reads like a malfunction.
            reason = verdict.reason
            message = "Nothing in the registered catalogue covers that request."
            if reason:
                message += f"\n\nWhy: {reason}"
            notes.append(f"coverage: no match ({reason or 'no reason given'})")
            return {
                "status": "completed",
                "answer": message,
                "tasks": [],
                "coverage": {
                    "outcome": verdict.outcome,
                    "reason": verdict.reason,
                    "confidence": verdict.confidence,
                },
                "notes": notes,
                "history": [{"role": "assistant", "content": message}],
            }

        if verdict.named:
            # Advisory ordering only — nothing is dropped. See CoverageVerdict.named.
            named = [item["agent_name"] for item in candidates if item["agent_name"] in verdict.named]
            unknown = [name for name in verdict.named if name not in {c["agent_name"] for c in candidates}]
            if unknown:
                notes.append(f"coverage: named unknown target(s) {unknown}; ignored")
            notes.append(
                f"coverage: route ({len(named)} of {len(targets)} named, "
                f"confidence {verdict.confidence:.2f}; all {len(candidates)} kept)"
            )
        else:
            notes.append("coverage: route (gate named nothing; all candidates kept)")

        return {
            "candidates": candidates,
            "coverage": {
                "outcome": verdict.outcome,
                "reason": verdict.reason,
                "confidence": verdict.confidence,
                # Carried into the planner prompt as an advisory hint, never a filter.
                "named": list(verdict.named),
            },
            "notes": notes,
        }

    # -- plan_tasks ----------------------------------------------------
    async def plan_tasks(self, state: OrchestratorState) -> dict[str, Any]:
        """Ask the planner for intent and tasks. Always a model call."""
        # "completed" here means the gate already resolved the turn (no match), so there
        # is nothing left to route and a second assistant message would be recorded.
        if state.get("status") != "running":
            return {}

        if not self._settings.can_plan_with_model:
            return {
                "status": "failed",
                "error": (
                    "PLANNER_MODEL is not configured: the orchestrator routes only through "
                    "the planner model and has no local fallback"
                ),
            }

        candidates = state.get("candidates") or []
        if not candidates:
            message = (
                "Nothing in the registered catalogue matched that request closely enough "
                "to route it."
            )
            return {
                "tasks": [],
                "status": "completed",
                "answer": message,
                "notes": ["plan: no candidates from retrieval"],
                "history": [{"role": "assistant", "content": message}],
            }

        targets = [
            record
            for record in (self._catalog.find(agent_id=item["agent_id"]) for item in candidates)
            if record is not None
        ]
        limit = min(
            state.get("max_agents") or self._settings.max_agents_per_request,
            self._settings.max_agents_per_request,
        )

        decision, why = await self._call_planner(state, targets, limit)
        if decision is None:
            # `why` distinguishes a transport fault from a formatting fault. They used to
            # share one message, which made a gateway blip indistinguishable from a model
            # that answered in the wrong shape.
            return {
                "status": "failed",
                "error": f"planner did not return a usable decision ({why})",
            }

        intent = str(decision.get("intent") or "").strip().lower()
        reason = str(decision.get("reason") or "").strip()

        if self._settings.read_only_mode and read_only_policy.is_mutation(intent):
            message = read_only_policy.denial_message(self._settings, reason)
            return {
                "status": "rejected",
                "answer": message,
                "tasks": [],
                "notes": [f"plan: refused ({reason or 'mutation intent'})"],
                "history": [{"role": "assistant", "content": message}],
            }

        tasks = self._coerce_tasks(decision.get("tasks") or [], targets, limit)
        note = f"plan: {len(tasks)} task(s) via {self._settings.planner_model}"
        if not tasks:
            message = "No registered agent or MCP tool can handle this request."
            return {
                "tasks": [],
                "notes": [note],
                "status": "completed",
                "answer": message,
                "history": [{"role": "assistant", "content": message}],
            }
        return {"tasks": tasks, "notes": [note]}

    async def _call_planner(
        self,
        state: OrchestratorState,
        targets: list[Target],
        limit: int,
    ) -> tuple[dict[str, Any] | None, str]:
        """Ask the planner. Returns ``(decision, reason)``; ``reason`` is empty on success.

        The reason is carried out so the turn can say *why* it failed — a gateway 4xx and
        a model answering in the wrong JSON shape need different fixes, and one shared
        message hid that.
        """
        history = self._history_block(state)
        # One ranked list, best first — the gateway's ordering (cosine similarity, already
        # cut at `similarity_threshold`). Deliberately *not* re-ordered or annotated with a
        # second opinion: adding a "gate hint" line here measurably caused the planner to
        # fan out to two targets for a one-target question, because two competing rankings
        # made both look defensible. LiteLLM's own design is a single ordered list.
        listing = "\n".join(
            target.summary() + (f" | relevance: {target.search_score:.2f}"
                                if target.search_score > 0 else "")
            for target in targets
        )
        prompt = (
            f"User message:\n{state.get('user_query', '')}\n\n"
            + (f"Recent conversation:\n{history}\n\n" if history else "")
            + f"Registered targets:\n{listing}\n\n"
            f"Maximum tasks: {limit}"
        )

        # Two distinct transient failures, both bounded:
        #   * a *rate limit* (429) — observed upstream on this gateway; the same call
        #     succeeds moments later. Backoff is 1/2/4/8s so a normal provider window
        #     (~20s) is survivable without failing the turn.
        #   * an unusable reply — models occasionally emit prose around the JSON or a
        #     truncated object
        # Anything else (4xx caused by configuration, 5xx) fails immediately: retrying it
        # only adds latency to a turn that cannot succeed.
        attempt_prompt = prompt
        attempts = 0
        rate_limit_retries = 0
        format_retries = 0
        max_rate_limit_retries = 4

        while attempts < 1 + max_rate_limit_retries + 1:
            attempts += 1
            try:
                reply = await self._gateway.complete(
                    self._settings.planner_model,
                    [
                        {"role": "system", "content": _PLANNER_SYSTEM},
                        {"role": "user", "content": attempt_prompt},
                    ],
                    trace=_trace_from_state(state),
                    lineage=_lineage_from_state(state),
                    temperature=self._settings.planner_temperature,
                    response_format_json=True,
                )
            except GatewayError as exc:
                if exc.status == 429 and rate_limit_retries < max_rate_limit_retries:
                    rate_limit_retries += 1
                    delay = 2.0 ** (rate_limit_retries - 1)  # 1, 2, 4, 8
                    log.warning(
                        "planner rate limited (429); retrying in %.0fs (attempt %d/%d)",
                        delay,
                        rate_limit_retries,
                        max_rate_limit_retries,
                    )
                    await asyncio.sleep(delay)
                    continue
                log.warning("planner call failed: %s", exc)
                return None, f"gateway error: {exc}"

            decision = _parse_json_object(reply)
            if decision:
                return decision, ""

            if format_retries < 1:
                format_retries += 1
                log.warning(
                    "planner reply was not usable JSON (%d chars); retrying once",
                    len(reply or ""),
                )
                attempt_prompt = (
                    prompt
                    + "\n\nYour previous reply could not be parsed. Reply with the JSON "
                    "object only — no prose, no code fences."
                )
                continue

            return None, (
                "replies could not be parsed as JSON; last reply started with "
                f"{(reply or '')[:80]!r}"
            )

        return None, "planner unavailable after retries"

    def _history_block(self, state: OrchestratorState, *, user_only: bool = False) -> str:
        """Prior turns only — the current message is already in the prompt.

        ``user_only`` drops assistant turns. Retrieval and the coverage gate reason about
        *what the user asked*; feeding them earlier assistant answers actively harms it.
        Measured: after a few "Nothing in the registered catalogue covers that request."
        turns, the query builder answered ``{"queries": []}`` and the gate declined
        "what is a lahar?" — a question that routes correctly in a fresh conversation. A
        decline is not evidence about the next question, so it must not be in the prompt.
        """
        history = list(state.get("history") or [])
        query = (state.get("user_query") or "").strip()
        if history and history[-1].get("role") == "user" and history[-1].get("content") == query:
            history = history[:-1]
        if user_only:
            history = [item for item in history if item.get("role") == "user"]
        limit = max(self._settings.history_max_turns, 1) * 2
        lines = [
            f"{item.get('role', 'user')}: {item.get('content', '')}"
            for item in history[-limit:]
            if item.get("content")
        ]
        return "\n".join(lines)

    def _coerce_tasks(
        self,
        raw_tasks: Any,
        targets: list[Target],
        limit: int,
    ) -> list[TaskSpec]:
        if not isinstance(raw_tasks, list):
            return []
        by_name = {target.agent_name: target for target in targets}
        by_id = {target.agent_id: target for target in targets}

        tasks: list[TaskSpec] = []
        for item in raw_tasks:
            if not isinstance(item, dict):
                continue
            name = str(item.get("agent") or "")
            instruction = str(item.get("instruction") or "").strip()
            target = by_name.get(name) or by_id.get(name)
            if target is None or not instruction:
                continue
            arguments = item.get("arguments")
            tasks.append(
                self._task(
                    target,
                    instruction,
                    dict(arguments) if isinstance(arguments, dict) else {},
                )
            )
            if len(tasks) >= limit:
                break
        return tasks

    @staticmethod
    def _task(target: Target, instruction: str, arguments: dict[str, Any]) -> TaskSpec:
        task: TaskSpec = {
            "task_id": uuid.uuid4().hex[:12],
            "agent_id": target.agent_id,
            "agent_name": target.agent_name,
            "protocol": target.protocol,
            "instruction": instruction,
        }
        if target.is_mcp:
            task["server_id"] = target.server_id
            task["tool_name"] = target.tool_name
            task["arguments"] = arguments
        return task

    # -- fan-out ----------------------------------------------------------
    def fan_out_tasks(self, state: OrchestratorState) -> list[Send] | str:
        if state.get("status") in ("failed", "rejected") or not state.get("tasks"):
            return "compose_answer"
        return [
            Send(
                "run_task",
                {
                    "task": task,
                    "user_query": state.get("user_query", ""),
                    "trace": state.get("trace") or {},
                    "lineage": state.get("lineage") or {},
                    "session_id": state.get("session_id", ""),
                },
            )
            for task in state["tasks"]
        ]

    # -- run_task ------------------------------------------------------
    async def run_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task: TaskSpec = payload["task"]
        trace = _trace_from_state(payload)  # type: ignore[arg-type]
        lineage = _lineage_from_state(payload)  # type: ignore[arg-type]

        target = self._catalog.find(agent_id=task["agent_id"])
        if target is None:
            target = Target(
                agent_id=task["agent_id"],
                agent_name=task["agent_name"],
                protocol=task.get("protocol", "a2a"),
                server_id=task.get("server_id", ""),
                tool_name=task.get("tool_name", ""),
            )

        arguments = task.get("arguments") or {}

        # The planner supplies arguments; validating them against the tool's own schema
        # keeps a knowingly incomplete call from leaving the orchestrator.
        if target.is_mcp:
            missing = target.missing_arguments(arguments)
            if missing:
                result = InvocationResult(
                    agent_id=target.agent_id,
                    agent_name=target.agent_name,
                    instruction=task["instruction"],
                    ok=False,
                    error=(
                        "planner did not supply required argument(s): "
                        + ", ".join(missing)
                    ),
                    protocol="mcp",
                    tool_name=target.tool_name,
                )
                return {"results": [result.to_state()]}

        result = await self._gateway.invoke(
            target,
            task["instruction"],
            trace=trace,
            lineage=lineage,
            arguments=arguments,
        )
        return {"results": [result.to_state()]}

    # -- compose_answer ------------------------------------------------
    async def compose_answer(self, state: OrchestratorState) -> dict[str, Any]:
        status = state.get("status")
        if status in ("failed", "rejected"):
            return {}

        results = [InvocationResult(**item) for item in state.get("results") or []]
        if not results:
            # The turn was resolved *before* execution — `check_coverage` (smalltalk, no match) or
            # `plan_tasks` (no candidates, no tasks) already wrote the assistant message into
            # history. Appending it again here recorded every such turn twice, which then
            # padded the planner prompt with duplicate noise on subsequent turns.
            return {}

        answer = self._compose(results)

        status = "completed" if any(item.ok for item in results) else "failed"
        error = "" if status == "completed" else "all targets failed"
        return {
            "answer": answer,
            "status": status,
            "error": error,
            "history": [{"role": "assistant", "content": answer}],
        }

    @staticmethod
    def _compose(results: list[InvocationResult]) -> str:
        """Deterministic merge: attribute every fact to its source, invent nothing."""
        if not results:
            return "No target produced a result."

        if len(results) == 1:
            # A single result needs no wrapper: the heading is noise, not information.
            result = results[0]
            if result.ok:
                return result.text
            return f"{result.agent_name} could not answer: {result.error or 'unknown error'}"

        sections: list[str] = []
        for result in results:
            header = f"### {result.agent_name}"
            if result.ok:
                sections.append(f"{header}\n{result.text}")
            else:
                sections.append(f"{header}\n_Failed: {result.error or 'unknown error'}_")
        return "\n\n".join(sections)
