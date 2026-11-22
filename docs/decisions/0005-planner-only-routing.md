# 0005 — Routing happens only in the planner

**Status:** Accepted · **Date:** 2026-11 (POC)

## Context

A model call per turn is the expensive, non-deterministic part. The tempting shortcut is a
local fallback: keyword match, "if the question mentions VPN, use the IT agent", a regex
for the obvious cases. It makes the system work when the planner is unreachable and costs
nothing.

The problem is what a fallback does to debugging. Two routing mechanisms means every wrong
answer raises "which one decided this?" — and the fallback is the one with no trace and no
reason string.

## Decision

`PLANNER_MODEL` is the **only** place routing happens. No keyword scoring, no local
decomposition, no argument extraction.

If the planner cannot be reached, the turn fails with a clear error rather than degrading
to a guess.

`Settings.validate()` refuses to start without `PLANNER_MODEL`, so the failure is at boot
rather than on the first question.

## Consequences

- **One place to look** when routing is wrong: the planner prompt and its reply, both
  visible in the trace.
- **The system is unavailable when the planner is.** Accepted for a routing layer — a wrong
  route is worse than an error, because a wrong route looks like an answer.
- **Deterministic parts stay deterministic.** Smalltalk is answered without a model call;
  the read-only refusal is checked at two points. Neither is a *routing* fallback.
- **Transient failures are retried, bounded**: 429 four times with 1/2/4/8s backoff;
  unparseable reply once with a corrective suffix. Anything else fails immediately, because
  retrying a misconfiguration only adds latency.
- The error names the cause, which is what makes "the planner is flaky" debuggable:

  ```
  planner did not return a usable decision (gateway error: POST /v1/chat/completions -> 429)
  ```

## Alternatives rejected

| Alternative | Why not |
|---|---|
keyword fallback | second routing path, untraced, invisible in failures |
"pick the only candidate if there is one" | hides retrieval bugs; the gate already handles it |
degrade to a generic message | masks a real outage as a product behaviour |
unbounded retry | a misconfiguration would hang the request |

## Evidence

`src/orchestrator/graph/nodes.py` (`plan`, `_call_planner`),
`docs/architecture/routing.md#planning`.
