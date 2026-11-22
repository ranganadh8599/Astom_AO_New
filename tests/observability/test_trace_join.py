"""Trace join with LibreChat.

The whole point of this module: the orchestrator's spans must land inside the trace
LibreChat already opened, not in a second tree beside it.

LibreChat derives its Langfuse trace id in
``api/packages/api/src/langfuse/trace.ts``:

    export function traceIdForMessage(messageId: string): string {
      return createHash('sha256').update(messageId, 'utf8').digest('hex').slice(0, 32);
    }

If `librechat_trace_id` ever drifts from that formula the two traces stop joining, and
nothing fails — you just get two trees that each look healthy. So the formula is pinned
against an independent digest rather than against itself.
"""

from __future__ import annotations

import hashlib

import pytest

from orchestrator.observability.trace_context import (
    LIBRECHAT_MESSAGE_ID_HEADER,
    SESSION_HEADER,
    TraceContext,
    conversation_trace_id,
    librechat_trace_id,
)


def _librechat_reference(message_id: str) -> str:
    """Independent reimplementation of LibreChat's formula, as a cross-check."""
    return hashlib.sha256(message_id.encode("utf8")).hexdigest()[:32]


# -- the formula -----------------------------------------------------------


@pytest.mark.parametrize(
    "message_id",
    [
        "8f4d3e2a-1b6c-4f5e-9a7b-2c3d4e5f6a7b",
        "abc123",
        "00000000-0000-0000-0000-000000000000",
        "message with spaces and unicode ✔",
        "",
    ],
)
def test_trace_id_matches_librechat_formula(message_id: str) -> None:
    assert librechat_trace_id(message_id) == _librechat_reference(message_id)


def test_trace_id_is_32_hex_chars() -> None:
    trace_id = librechat_trace_id("any-message-id")

    assert len(trace_id) == 32
    assert all(c in "0123456789abcdef" for c in trace_id)


def test_different_messages_get_different_traces() -> None:
    assert librechat_trace_id("m1") != librechat_trace_id("m2")


def test_same_message_is_stable() -> None:
    """Retries and internal replays must not fork the trace."""
    assert librechat_trace_id("m1") == librechat_trace_id("m1")


# -- resolution precedence -------------------------------------------------


def test_message_id_joins_librechats_trace() -> None:
    ctx = TraceContext.from_headers({LIBRECHAT_MESSAGE_ID_HEADER: "msg-1"}, session_id="conv-1")

    assert ctx.trace_id == librechat_trace_id("msg-1")
    assert ctx.session_id == "conv-1", "session still groups the conversation"


def test_inbound_traceparent_wins_over_message_id() -> None:
    """An upstream that already has W3C context is authoritative."""
    traceparent = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    ctx = TraceContext.from_headers(
        {"traceparent": traceparent, LIBRECHAT_MESSAGE_ID_HEADER: "msg-1"}
    )

    assert ctx.trace_id == "a" * 32
    assert ctx.span_id == "b" * 16


def test_conversation_fallback_when_no_message_id() -> None:
    """Standalone use (CLI, direct calls) keeps the old behaviour available."""
    ctx = TraceContext.from_headers({}, session_id="conv-9")

    assert ctx.trace_id == conversation_trace_id("conv-9")


def test_conversation_id_header_sets_the_session() -> None:
    ctx = TraceContext.from_headers(
        {LIBRECHAT_MESSAGE_ID_HEADER: "msg-1", SESSION_HEADER: "conv-from-header"}
    )

    assert ctx.trace_id == librechat_trace_id("msg-1")
    assert ctx.session_id == "conv-from-header"


def test_explicit_session_argument_still_wins_over_nothing() -> None:
    ctx = TraceContext.from_headers({}, session_id="from-body")

    assert ctx.session_id == "from-body"


def test_header_lookup_is_case_insensitive() -> None:
    """ASGI lowercases, but other callers (tests, proxy) may not."""
    ctx = TraceContext.from_headers({"X-LibreChat-Message-Id": "msg-1"})

    assert ctx.trace_id == librechat_trace_id("msg-1")


# -- per-message granularity, per-conversation grouping --------------------


def test_two_turns_in_one_conversation_are_two_traces_one_session() -> None:
    """Langfuse's model: a trace is a request, a session is a conversation."""
    first = TraceContext.from_headers(
        {LIBRECHAT_MESSAGE_ID_HEADER: "m1", SESSION_HEADER: "c1"}
    )
    second = TraceContext.from_headers(
        {LIBRECHAT_MESSAGE_ID_HEADER: "m2", SESSION_HEADER: "c1"}
    )

    assert first.trace_id != second.trace_id
    assert first.session_id == second.session_id == "c1"


def test_child_spans_keep_the_joined_trace() -> None:
    ctx = TraceContext.from_headers({LIBRECHAT_MESSAGE_ID_HEADER: "m1"})
    child = ctx.child()

    assert child.trace_id == librechat_trace_id("m1")
    assert child.span_id != ctx.span_id


def test_headers_sent_downstream_carry_the_joined_id() -> None:
    ctx = TraceContext.from_headers({LIBRECHAT_MESSAGE_ID_HEADER: "m1"})
    headers = ctx.to_headers()

    assert librechat_trace_id("m1") in headers["traceparent"]
    assert headers["x-litellm-trace-id"] == librechat_trace_id("m1")
