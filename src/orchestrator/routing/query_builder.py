"""From the user's message to the queries that go to the gateway's search.

Searching with the raw message has two failure modes:

* **Follow-ups lose their subject.** "And in 2016?" embeds as nothing in particular.
  The recent conversation says what it is about.
* **Several questions average out.** One embedding of "Ronaldo's Ballon d'Or count and
  open incidents at the Pune site" sits between two topics and can rank neither agent
  first. One query per question does not.

``QueryBuilder`` fixes both with one cheap model call, made only when the message looks
like it needs it. Anything that goes wrong (model error, unparsable reply) returns the
original message, so retrieval is never worse than before this step existed.

The queries are **keyword phrases, not the user's sentence**. Measured on the 40-target
example catalogue, the gateway's embedding search is phrasing-sensitive: "what were
E-1042's deductions?" returned *zero* candidates while "E-1042 payroll deductions" ranked
the right tool first, and "any rooms free on 2026-12-03?" missed the hotel tool that
"hotel room availability 2026-12-03" found at rank 1. So the prompt asks for compact
phrases and the trigger fires on any reference-like token (``SKU-4471``, ``BA2490``,
``2026-12-03``), not only on follow-ups and multi-ask messages.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from orchestrator.gateway import GatewayError, LiteLLMGateway
from orchestrator.observability.trace_context import Lineage, TraceContext

QUERY_BUILDER_SYSTEM = """You turn a user's message into search queries for a registry of \
agents and tools. You do not answer the message.

The registry is searched by embedding similarity against short descriptions, so a
conversational sentence matches poorly. Write each query as a compact keyword phrase —
domain nouns, the action, and any identifier — with question scaffolding removed.

Rules:
- Use the recent conversation to replace pronouns and fill in an omitted subject ("and in
  2016?" after a question about a player's goals becomes "player goals 2016").
- Keep identifiers, codes and dates EXACTLY as written: SKU-4471, BA2490, E-1042,
  LAB-2026-0418, 2026-12-03.
- Drop filler: "what were", "is", "do we have", "can you tell me", "please".
- Infer the *kind of record* an identifier names when that is what makes it searchable
  (a flight number, a ticket, a parcel, a payslip). Never invent facts, values or answers.
- One query per distinct topic, at most {max_queries}.

Examples:
  "is BA2490 delayed?"             -> {{"queries": ["flight BA2490 status delay"]}}
  "what were E-1042's deductions?" -> {{"queries": ["E-1042 payroll deductions"]}}
  "any rooms free on 2026-12-03?"  -> {{"queries": ["hotel room availability 2026-12-03"]}}
  "how do I check chain wear?"     -> {{"queries": ["bicycle chain wear check"]}}

Reply with JSON only: {{"queries": ["...", "..."]}}

Always return at least one query. Do not decide whether a target exists — that is a later
step's job. Even for a message you suspect is unanswerable, return the search phrase that
would find a target if one existed."""

# An empty ``queries`` list means the model declined to search (measured: after a run of
# "nothing covers that" turns it answered ``{"queries": []}``). Falling back to the raw
# message is the safe reading: no rewrite is worse than no search.

# A message this short, with prior turns available, is probably a follow-up.
FOLLOW_UP_MAX_WORDS = 14
# A long message is only worth splitting if it also looks like several asks.
MULTI_ASK_MIN_WORDS = 20
_JOINERS = re.compile(r"\b(and|also|plus|then|as well as|additionally)\b", re.IGNORECASE)
# A reference-like token: a code with both letters and digits (SKU-4471, BA2490, E-1042,
# LAB-2026-0418) or an ISO date. Measured: the gateway's embedding search returns nothing
# at all for "what were E-1042's deductions?" but ranks the right tool first for
# "E-1042 payroll deductions", so an identifier-bearing message is always worth rewriting.
_REFERENCE_RE = re.compile(
    r"\b(?=[A-Za-z0-9-]{4,}\b)(?=[A-Za-z0-9-]*[A-Za-z])(?=[A-Za-z0-9-]*\d)[A-Za-z0-9-]+\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
)
MAX_QUERY_CHARS = 300


@dataclass(frozen=True)
class BuiltQueries:
    queries: tuple[str, ...]
    rewritten: bool
    note: str = ""


def needs_rewrite(message: str, *, has_history: bool) -> bool:
    """Cheap, deterministic check for whether the model call is worth making."""
    text = message.strip()
    words = len(text.split())
    if _REFERENCE_RE.search(text):
        return True
    if has_history and words <= FOLLOW_UP_MAX_WORDS:
        return True
    if text.count("?") >= 2:
        return True
    if len([line for line in text.splitlines() if line.strip()]) >= 2:
        return True
    return words >= MULTI_ASK_MIN_WORDS and bool(_JOINERS.search(text))


class QueryBuilder:
    def __init__(self, gateway: LiteLLMGateway, model: str, *, max_queries: int = 3) -> None:
        self._gateway = gateway
        self._model = model
        self._max_queries = max(max_queries, 1)

    async def build(
        self,
        message: str,
        *,
        history: str,
        trace: TraceContext,
        lineage: Lineage,
    ) -> BuiltQueries:
        original = (message or "").strip()
        if not original:
            return BuiltQueries((), False)
        if not needs_rewrite(original, has_history=bool(history.strip())):
            return BuiltQueries((original,), False)

        prompt = (
            (f"Recent conversation:\n{history}\n\n" if history.strip() else "")
            + f"User message:\n{original}"
        )
        try:
            reply = await self._gateway.complete(
                self._model,
                [
                    {
                        "role": "system",
                        "content": QUERY_BUILDER_SYSTEM.format(max_queries=self._max_queries),
                    },
                    {"role": "user", "content": prompt},
                ],
                trace=trace,
                lineage=lineage,
                temperature=0.0,
                response_format_json=True,
            )
        except GatewayError:
            return BuiltQueries((original,), False, "query rewrite unavailable, using the message as is")

        queries = parse_queries(reply, self._max_queries)
        if not queries:
            return BuiltQueries((original,), False, "query rewrite unusable, using the message as is")
        return BuiltQueries(queries, queries != (original,))


def parse_queries(raw: str, limit: int) -> tuple[str, ...]:
    """Pull the query list out of a model reply, tolerating code fences and prose."""
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data: object
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return ()
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return ()
    if not isinstance(data, Mapping):
        return ()
    items = data.get("queries")
    if not isinstance(items, list):
        return ()
    seen: set[str] = set()
    queries: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        query = " ".join(item.split())[:MAX_QUERY_CHARS]
        key = query.lower()
        if query and key not in seen:
            seen.add(key)
            queries.append(query)
        if len(queries) >= limit:
            break
    return tuple(queries)
