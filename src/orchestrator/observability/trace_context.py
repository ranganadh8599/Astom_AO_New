"""W3C trace context, plus the lineage IDs that survive every hop.

The trace id is **joined to LibreChat's**, not invented here. LibreChat derives its
Langfuse trace id as ``sha256(messageId)[:32]`` (see
``api/packages/api/src/langfuse/trace.ts``), and forwards the message id in a header. We
compute the same digest, so the orchestrator's spans land *inside* the trace LibreChat
already opened instead of forming a second, disconnected tree.

Granularity follows from that: **one trace per message**, grouped into **one Langfuse
session per conversation**. That is Langfuse's own model — a trace is one request, a
session is one conversation — and it is what LibreChat implements.

Every downstream call — planner, gate, each A2A agent, each MCP tool — carries the same
``traceparent`` so LiteLLM and Langfuse attach to one tree.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Mapping

TRACEPARENT_HEADER = "traceparent"
TRACESTATE_HEADER = "tracestate"
LITELLM_TRACE_HEADER = "x-litellm-trace-id"
PARENT_AGENT_HEADER = "x-orchestrator-parent-agent"
DEPTH_HEADER = "x-orchestrator-depth"
# Sent by LibreChat from {{LIBRECHAT_BODY_MESSAGEID}}. Its trace id is
# sha256(messageId)[:32], so this is the join key between the two systems.
LIBRECHAT_MESSAGE_ID_HEADER = "x-librechat-message-id"
SESSION_HEADER = "x-librechat-conversation-id"


def new_trace_id() -> str:
    return uuid.uuid4().hex  # 32 lowercase hex chars


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]  # 16 lowercase hex chars


def librechat_trace_id(message_id: str) -> str:
    """LibreChat's Langfuse trace id for a message: ``sha256(messageId)[:32]``.

    Duplicated deliberately rather than approximated: if this drifts from LibreChat's
    formula the two traces stop joining, and the failure is invisible (two trees, both
    looking fine). ``tests/observability/test_trace_join.py`` pins the exact formula.
    """
    return hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:32]


def conversation_trace_id(session_id: str, salt: str = "") -> str:
    """Fallback trace id derived from a conversation, when no message id is supplied.

    Used only when LibreChat is not in front of us (CLI, direct calls). Keeps the old
    behaviour available without making it the default.
    """
    digest = hashlib.sha256(f"{salt}|{session_id}".encode("utf-8")).hexdigest()[:32]
    return digest if digest.strip("0") else new_trace_id()


def _header(headers: Mapping[str, str], name: str) -> str:
    """Case-insensitive header lookup.

    ``Mapping.get`` is exact-match, and ``str.title()`` is not a correct
    case-insensitive key: ``x-librechat-message-id`` becomes
    ``X-Librechat-Message-Id``, which misses ``X-LibreChat-Message-Id``. ASGI lowercases
    its keys, but tests, batch jobs and proxies may not, so compare on lowercase.
    """
    direct = headers.get(name)
    if direct is not None:
        return direct.strip()
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return (value or "").strip()
    return ""


@dataclass(frozen=True)
class TraceContext:
    """Serializable trace state that crosses process boundaries."""

    trace_id: str
    span_id: str
    trace_flags: int = 1  # 0x01 = sampled
    trace_state: str = ""
    session_id: str = ""  # LibreChat conversation ID, used as the Langfuse session

    @classmethod
    def root(cls, session_id: str = "") -> "TraceContext":
        return cls(trace_id=new_trace_id(), span_id=new_span_id(), session_id=session_id)

    @classmethod
    def for_message(cls, message_id: str, session_id: str = "") -> "TraceContext":
        """Join LibreChat's trace for this message."""
        return cls(
            trace_id=librechat_trace_id(message_id),
            span_id=new_span_id(),
            session_id=session_id,
        )

    @classmethod
    def for_conversation(cls, session_id: str, *, salt: str = "") -> "TraceContext":
        """Fallback: one trace for the whole conversation, when no message id is known."""
        return cls(
            trace_id=conversation_trace_id(session_id, salt),
            span_id=new_span_id(),
            session_id=session_id,
        )

    @classmethod
    def from_headers(
        cls,
        headers: Mapping[str, str],
        session_id: str = "",
        *,
        salt: str = "",
        per_conversation: bool = True,
    ) -> "TraceContext":
        """Resolve trace context from an inbound request.

        Precedence, highest first:

        1. ``traceparent`` — a caller that already has W3C context.
        2. ``x-librechat-message-id`` — join the trace LibreChat opened for this message.
           This is the normal path when LibreChat is the front end.
        3. conversation-derived id — standalone use (CLI, direct calls).

        Session grouping is independent of all three: ``session_id`` is the
        conversation, so a per-message trace still appears inside one conversation.
        """
        session_id = _header(headers, SESSION_HEADER) or session_id

        raw = _header(headers, TRACEPARENT_HEADER)
        parts = raw.split("-")
        if len(parts) == 4 and len(parts[1]) == 32 and len(parts[2]) == 16:
            try:
                flags = int(parts[3], 16)
            except ValueError:
                flags = 1
            return cls(
                trace_id=parts[1].lower(),
                span_id=parts[2].lower(),
                trace_flags=flags,
                trace_state=_header(headers, TRACESTATE_HEADER),
                session_id=session_id,
            )

        message_id = _header(headers, LIBRECHAT_MESSAGE_ID_HEADER)
        if message_id:
            return cls.for_message(message_id, session_id)

        if per_conversation and session_id:
            return cls.for_conversation(session_id, salt=salt)
        return cls.root(session_id)

    def child(self) -> "TraceContext":
        """Derive a span for one step, keeping the same trace."""
        return TraceContext(
            trace_id=self.trace_id,
            span_id=new_span_id(),
            trace_flags=self.trace_flags,
            trace_state=self.trace_state,
            session_id=self.session_id,
        )

    def to_headers(self) -> dict[str, str]:
        headers = {
            TRACEPARENT_HEADER: f"00-{self.trace_id}-{self.span_id}-{self.trace_flags:02x}",
            # LiteLLM groups iteration/budget accounting by this header.
            LITELLM_TRACE_HEADER: self.trace_id,
        }
        if self.trace_state:
            headers[TRACESTATE_HEADER] = self.trace_state
        return headers


@dataclass(frozen=True)
class Lineage:
    """Who spawned whom.

    Mirrors the Copilot Chat subagent convention: every subagent invocation knows its own
    ID, the tool call / model call that caused it, and the root turn it belongs to.
    """

    top_level_turn_id: str
    parent_tool_call_id: str = ""
    parent_model_call_id: str = ""
    parent_agent: str = ""
    depth: int = 0
    chain: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def root(cls) -> "Lineage":
        return cls(top_level_turn_id=new_span_id(), chain=())

    def for_agent(self, agent_name: str) -> "Lineage":
        return Lineage(
            top_level_turn_id=self.top_level_turn_id,
            parent_agent=self.chain[-1] if self.chain else self.parent_agent,
            depth=self.depth + 1,
            chain=(*self.chain, agent_name),
        )

    def to_headers(self) -> dict[str, str]:
        headers = {DEPTH_HEADER: str(self.depth)}
        if self.parent_agent:
            headers[PARENT_AGENT_HEADER] = self.parent_agent
        return headers

    def describe(self) -> dict[str, object]:
        return {
            "top_level_turn_id": self.top_level_turn_id,
            "parent_agent": self.parent_agent,
            "depth": self.depth,
            "chain": list(self.chain),
        }


def call_headers(trace: TraceContext, lineage: Lineage) -> dict[str, str]:
    """Headers sent on every call to the gateway.

    Credential-shaped headers are never derived here, so a caller cannot smuggle
    ``Authorization``/``Cookie`` values upstream through the orchestrator.
    """
    headers = trace.to_headers()
    headers.update(lineage.to_headers())
    return headers
