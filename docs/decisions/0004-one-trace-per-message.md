# 0004 — One trace per message, one session per conversation

**Status:** Accepted · **Date:** 2026-11 (POC)

## Context

The orchestrator runs in front of LibreChat. LibreChat already creates a Langfuse trace per
user message and an LLM generation inside it. If the orchestrator creates its own trace, a
single question produces **two disconnected trees**: the routing decision in one, the model
call in the other.

The naive fix — make the orchestrator reuse a conversation-scoped trace — is worse, because
then the conversation is one enormous trace and "what happened in this request" is
unanswerable.

## Decision

Join LibreChat's trace. LibreChat derives its trace id as `sha256(messageId)[:32]`
(`api/packages/api/src/langfuse/trace.ts`) and forwards the message id in a header; the
orchestrator computes the same digest.

```python
trace_id = sha256(message_id)[:32]   # identical to LibreChat's formula
```

Resolution order, highest precedence first:

| Source | Used when |
|---|---|
`traceparent` | caller already has W3C context |
`X-LibreChat-Message-Id` | LibreChat is the front end — **the normal path** |
conversation-derived | standalone use: CLI, direct calls |

Session grouping is **independent**: `session_id = conversationId`.

## Consequences

- Orchestrator spans (`gate`, `plan`, `execute`, …) appear next to LibreChat's LLM call in
  one trace. Verified: message id `librechat-msg-7f3a9c21` produced trace `b4417be3…` in
  both systems.
- "Whole conversation" is still answerable, via the session, not the trace. That matches
  Langfuse's own model: trace = one request, session = one conversation.
- `TRACE_PER_CONVERSATION=true` remains available for **standalone** deployments. With
  LibreChat in front it is effectively inert because the header outranks it — which is why
  leaving it `true` here is safe rather than confusing.
- The formula is a **contract with LibreChat's source**. If that changes, trace joining
  breaks silently. The verification step is: send one message with a known id and look for
  the digest in both systems.

## Alternatives rejected

| Alternative | Why not |
|---|---|
orchestrator makes its own trace | two trees per question |
one trace per conversation | conversation becomes one trace; per-request analysis impossible |
custom correlation header only | works internally, invisible to LibreChat's own trace |

## Evidence

`src/orchestrator/observability/trace_context.py` (`TraceContext.from_headers`, `librechat_trace_id`),
`docs/architecture/tracing.md`.
