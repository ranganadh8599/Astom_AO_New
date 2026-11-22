"""Trace and lineage propagation: the reason traces don't break at service boundaries."""

from __future__ import annotations

from orchestrator.observability.trace_context import (
    Lineage,
    TraceContext,
    call_headers,
    conversation_trace_id,
)


def test_root_generates_w3c_ids() -> None:
    trace = TraceContext.root(session_id="conv-1")
    assert len(trace.trace_id) == 32
    assert len(trace.span_id) == 16
    header = trace.to_headers()["traceparent"]
    assert header == f"00-{trace.trace_id}-{trace.span_id}-01"


def test_conversation_trace_id_is_stable_and_distinct() -> None:
    assert conversation_trace_id("conv-1") == conversation_trace_id("conv-1")
    assert conversation_trace_id("conv-1") != conversation_trace_id("conv-2")
    assert len(conversation_trace_id("conv-1")) == 32


def test_missing_traceparent_joins_the_conversation_trace() -> None:
    trace = TraceContext.from_headers({}, session_id="conv-9")
    assert trace.trace_id == conversation_trace_id("conv-9")
    assert trace.session_id == "conv-9"


def test_conversation_tracing_can_be_disabled() -> None:
    trace = TraceContext.from_headers(
        {}, session_id="conv-9", per_conversation=False
    )
    assert trace.trace_id != conversation_trace_id("conv-9")


def test_inbound_traceparent_is_reused_span_changes() -> None:
    inbound = {"traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"}
    trace = TraceContext.from_headers(inbound)
    assert trace.trace_id == "1" * 32

    child = trace.child()
    assert child.trace_id == trace.trace_id
    assert child.span_id != trace.span_id


def test_malformed_traceparent_starts_a_new_trace() -> None:
    trace = TraceContext.from_headers({"traceparent": "garbage"})
    assert len(trace.trace_id) == 32


def test_lineage_records_parent_chain() -> None:
    root = Lineage.root()
    hop1 = root.for_agent("hr-policy-agent")
    hop2 = hop1.for_agent("sub-agent")

    assert hop1.depth == 1
    assert hop2.depth == 2
    assert hop2.parent_agent == "hr-policy-agent"
    assert hop2.chain == ("hr-policy-agent", "sub-agent")
    assert hop2.top_level_turn_id == root.top_level_turn_id


def test_call_headers_never_include_credentials() -> None:
    headers = call_headers(TraceContext.root(), Lineage.root().for_agent("a"))
    lowered = {name.lower() for name in headers}
    for forbidden in ("authorization", "cookie", "x-api-key", "proxy-authorization"):
        assert forbidden not in lowered
    assert headers["x-litellm-trace-id"]
    assert headers["x-orchestrator-depth"] == "1"
