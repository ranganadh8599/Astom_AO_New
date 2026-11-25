"""Coverage gate: can *any* registered target answer this?

The planner is good at choosing between plausible options and bad at declining. Measured
on a 12-target registry, it rejected 2 of 7 irrelevant queries when asked to route
directly, and adding relevance scores to its prompt did not change that (still 2 of 7).
Asking a separate question first — "does anything here actually cover this?" — rejected
7 of 7 while keeping 9 of 10 valid queries routed correctly, and 10 of 10 once the
candidates carried their relevance scores.

The decision shape is borrowed from a sibling implementation in this workspace
(``multi-agent-orchestator/classifiers/open_ai_classifier.py``), which models "no match"
as a first-class outcome with a mandatory reason and a self-reported confidence, rather
than as an empty result list:

    accuracy     -> confidence   (the model's own 0-1 judgement)
    next_action  -> outcome      ("route" | "no_match")
    action       -> reason       (why, kept for audit)

Two deliberate differences from that implementation:

* confidence is *self-reported judgement*, never a cosine value. Embedding scores are not
  calibrated across registries and must not be presented as probabilities.
* a contradiction between ``can_answer`` and ``targets`` is recorded, not silently
  resolved. Their equivalent had ``next_action_input == "unkown"`` (a typo) compared
  against a correctly spelled constant elsewhere — the kind of bug that hides inside
  derived state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from orchestrator.gateway import Target, GatewayError, LiteLLMGateway
from orchestrator.observability.trace_context import Lineage, TraceContext
from orchestrator.routing.smalltalk import looks_like_request

OUTCOME_ROUTE = "route"
OUTCOME_NO_MATCH = "no_match"
# A greeting, thanks, or question about the assistant itself. Answered by the
# orchestrator directly: routing it to an agent would spend a call to produce nothing,
# and declining it ("nothing covers that") is wrong for "hi".
OUTCOME_SMALLTALK = "smalltalk"

GATE_SYSTEM = """You triage a read-only enterprise assistant's incoming message, then judge
whether any registered target can answer it.

1. Classify intent:
   - "read": answering a question, looking something up, explaining, summarising,
     checking a status, or asking how something is done.
   - "mutation": asking to create, change, update, delete, remove, cancel, approve,
     reject, assign, submit, schedule or otherwise modify anything.
   - "smalltalk": only social or meta messages — a greeting, thanks, acknowledgement, or
     a question about the assistant itself rather than about the business: "hi",
     "hello", "thanks, that helps", "good morning", "who are you?", "what can you do?".
   Smalltalk is never a request to produce something. "write me a poem", "translate
   this", "explain X", "summarise this paragraph" and "calculate 12% of 90" are all
   "read"; they are then judged on coverage like any other request (usually not covered).
   "How do I update my address?" is "read". "Update my address" is "mutation".
   "hi" and "what can you do?" are "smalltalk", not "read".

2. Judge coverage, not similarity. A target covers the message only if its description
   genuinely addresses that kind of request.

   Targets come in three kinds, marked in the list:
   - [a2a] an agent, described by what it knows or does
   - [mcp] a single tool, with its arguments
   - [model] an assistant model with its own domain

   A [model] target counts as coverage when the question falls inside the domain its
   description names. Its description lists what it handles; if the question is about
   something that list covers, it can answer.

   Be strict about these, which no listed target covers: general knowledge, arithmetic,
   translation, creative writing (poems, stories, jokes), summarising text the user
   supplies, chit-chat, and unrelated domains.

A "relevance" number may be supplied per target from embedding search. Treat it as a weak
hint only. Scores are not calibrated and a high score does not prove coverage; decide
from the descriptions.

Reply with JSON only, exactly:
{"intent": "read"|"mutation"|"smalltalk", "can_answer": true|false,
 "targets": ["<target name exactly as listed>", ...],
 "reason": "<one short sentence>", "confidence": <0.0-1.0>}

Rules:
- If nothing covers the message: can_answer=false and targets=[].
- A message may contain SEVERAL questions. Judge each one on its own, then combine:
  if at least one sub-question is covered, set can_answer=true and list the targets that
  cover the parts you can serve. Name the parts no target covers in `reason` instead of
  letting one uncovered part hide the rest. Only when NO part is covered is
  can_answer=false. Example: "what is a lahar, and what is the capital of Mongolia?" — a
  volcanology agent covers the lahar, nothing covers the capital city, so can_answer=true
  and reason "the capital of Mongolia is not covered".
- For "mutation" always return can_answer=false and targets=[].
- For "smalltalk" always return can_answer=false and targets=[]. The orchestrator
  answers those itself.
- List only targets that genuinely cover the message, most relevant first.
- confidence is your own judgement of this decision, not the supplied relevance number."""


@dataclass(frozen=True)
class CoverageVerdict:
    """The gate's verdict, kept as data so it can be traced and reported."""

    outcome: str = OUTCOME_ROUTE
    reason: str = ""
    confidence: float = 0.0
    # Targets the gate judged to cover the message, best first. ADVISORY ONLY.
    #
    # This used to be named `allowed` and was used to filter the candidate set, which
    # made a wrong verdict unrecoverable: retrieval's best match was deleted before the
    # planner saw it (measured: maintenance scored 0.63, the gate named the 0.39 tool, and
    # the planner received only that one). The field is a ranking — the prompt already
    # asks for "only targets that genuinely cover the message, most relevant first" — so
    # it is passed to the planner as a hint and never drops anything.
    named: tuple[str, ...] = ()
    intent: str = "read"
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_no_match(self) -> bool:
        return self.outcome == OUTCOME_NO_MATCH

    @property
    def is_smalltalk(self) -> bool:
        return self.outcome == OUTCOME_SMALLTALK


def _score_line(agent: Target) -> str:
    if agent.search_score > 0:
        return f" | relevance: {agent.search_score:.2f}"
    return ""


def build_prompt(query: str, targets: Sequence[Target], history: str = "") -> str:
    if targets:
        listing = "\n".join(
            f"- {t.agent_name}: {t.description}{_score_line(t)}" for t in targets
        )
    else:
        listing = "(no targets matched retrieval)"
    return (
        f"User message:\n{query}\n\n"
        + (f"Recent conversation:\n{history}\n\n" if history else "")
        + f"Registered targets:\n{listing}"
    )


def parse_decision(raw: str) -> CoverageVerdict | None:
    """Turn a gate reply into a CoverageVerdict. Returns ``None`` when unusable."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, Mapping):
        return None

    raw_targets = data.get("targets")
    targets = tuple(
        str(item).strip() for item in (raw_targets or []) if str(item).strip()
    ) if isinstance(raw_targets, (list, tuple)) else ()

    can_answer = data.get("can_answer")
    if not isinstance(can_answer, bool):
        # No usable verdict. Returning None makes the caller continue to planning
        # rather than decline: a malformed gate reply must never lose a valid query.
        return None

    reason = str(data.get("reason") or "").strip()
    intent = str(data.get("intent") or "read").strip().lower()
    if intent not in ("read", "mutation", "smalltalk"):
        intent = "read"
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)

    notes: list[str] = []

    # Smalltalk is decided before coverage: "hi" has no target, but declining it is the
    # wrong outcome. Answered by the orchestrator, see graph/nodes.check_coverage.
    if intent == "smalltalk" and can_answer is False:
        if targets:
            notes.append("gate: smalltalk but targets listed; answering directly")
        return CoverageVerdict(
            outcome=OUTCOME_SMALLTALK,
            reason=reason,
            confidence=confidence,
            intent=intent,
            notes=tuple(notes),
        )

    if can_answer is False and targets:
        # Decline, but record that the reply contradicted itself.
        notes.append("gate: can_answer=false but targets listed; honouring no match")
        return CoverageVerdict(
            outcome=OUTCOME_NO_MATCH,
            reason=reason,
            confidence=confidence,
            intent=intent,
            notes=tuple(notes),
        )

    if can_answer is False:
        return CoverageVerdict(
            outcome=OUTCOME_NO_MATCH, reason=reason, confidence=confidence, intent=intent
        )

    if not targets:
        # Affirmative but unnamed: treat as "no narrowing" rather than as nothing,
        # because the answer said something can handle it.
        notes.append("gate: can_answer=true but no targets listed; no narrowing")
        return CoverageVerdict(outcome=OUTCOME_ROUTE, reason=reason, confidence=confidence,
                         intent=intent, notes=tuple(notes))

    return CoverageVerdict(
        outcome=OUTCOME_ROUTE,
        reason=reason,
        confidence=confidence,
        named=targets,
        intent=intent,
    )


class CoverageGate:
    """One LLM call that triages intent and answers only "is this covered?"."""

    def __init__(
        self, gateway: LiteLLMGateway, model: str, *, temperature: float = 0.0
    ) -> None:
        self._gateway = gateway
        self._model = model
        self._temperature = temperature

    async def assess(
        self,
        query: str,
        targets: Sequence[Target],
        *,
        trace: TraceContext,
        lineage: Lineage,
        history: str = "",
    ) -> CoverageVerdict | None:
        """Returns ``None`` when the gate could not be consulted (caller decides policy).

        Called even with an empty candidate list: intent still has to be triaged, or a
        mutation would be answered as a coverage miss.
        """

        try:
            reply = await self._gateway.complete(
                self._model,
                [
                    {"role": "system", "content": GATE_SYSTEM},
                    {"role": "user", "content": build_prompt(query, targets, history)},
                ],
                trace=trace,
                lineage=lineage,
                temperature=self._temperature,
                response_format_json=True,
            )
        except GatewayError:
            return None
        verdict = parse_decision(reply)
        if verdict is not None and verdict.is_smalltalk and looks_like_request(query):
            # The model labelled a content request as social ("write me a poem",
            # "write me a haiku", "translate this"). A deterministic check overrides the
            # label, so the outcome does not depend on prompt compliance: the turn becomes
            # a coverage miss, which the graph reports honestly, instead of a greeting that
            # silently drops what the user asked for.
            #
            # ``reason`` is intentionally dropped: the verdict's reason explains *why it
            # was smalltalk* ("the message is a greeting"), which contradicts a coverage
            # miss and read as nonsense in the answer. The caller supplies a neutral
            # reason, which is accurate whatever the message was.
            return CoverageVerdict(
                outcome=OUTCOME_NO_MATCH,
                reason="",
                confidence=verdict.confidence,
                intent="read",
                notes=(
                    "gate: labelled smalltalk, but the message is a request; treated as "
                    "no match",
                ),
            )
        return verdict
