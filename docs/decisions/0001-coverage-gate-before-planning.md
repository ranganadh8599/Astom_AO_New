# 0001 — Ask a coverage question before planning

**Status:** Accepted · **Date:** 2026-11 (POC)

## Context

One model call could do both jobs: decide whether anything can answer, and choose which
target. That is fewer calls and less code. The question was whether it was also *correct*.

Measured on a 12-target registry (`text-embedding-3-small`), asking the planner to route
directly:

| Approach | In-domain correct | Irrelevant rejected |
|---|---|---|
planner alone | 8/10 | **2/7** |
planner + relevance scores in the prompt | 9/10 | 2/7 |

It confidently routed `kubernetes crashloopbackoff` to an IT agent. Adding scores to the
prompt did not help — the failure is not about information, it is that a router asked
"which of these?" will pick one.

Asking a separate question first — *"does anything here actually cover this?"* — rejected
**7 of 7** irrelevant queries while keeping 9 of 10 valid ones routed.

## Decision

A dedicated `check_coverage` node runs before `plan_tasks` and returns one of four outcomes:

```json
{"intent":"read"|"mutation"|"smalltalk", "can_answer": true|false,
 "targets": ["<name>"], "reason": "<one sentence>", "confidence": 0.0}
```

`no_match` is a first-class outcome with a **mandatory reason**, not an empty result list.

## Consequences

- **One extra LLM call per turn.** Accepted: it converts a confidently-wrong answer into
  an explanation.
- **A malformed gate reply is unusable, not a decline.** The turn continues to planning,
  because a formatting slip must not discard a valid query and the planner is still a gate
  behind it.
- **Confidence is the model's own judgement**, never a cosine score presented as a
  probability. Embedding scores are not calibrated across registries.
- **Self-contradictory replies are recorded, not resolved.** `can_answer=false` with
  targets listed lands in the turn's notes rather than being silently "fixed".
- Prompt size is bounded by `CANDIDATE_MAX_TARGETS` (a visible count) rather than a
  similarity threshold (see [0002](0002-no-relevance-score-threshold.md)).

## Alternatives rejected

| Alternative | Why not |
|---|---|
planner alone | 2/7 rejection — worse than useless, because a wrong route looks authoritative |
planner + scores | still 2/7 |
two-model ensemble | doubles cost for no measured gain over one dedicated question |
local classifier | needs training data and drifts; the gate needs no maintenance |

## Evidence

`src/orchestrator/routing/coverage_gate.py`, `docs/architecture/routing.md#why-a-separate-gate`.
`COVERAGE_GATE_ENABLED=false` (formerly `RELEVANCE_GATE_ENABLED`, still accepted) reverts to planner-only, for comparison.
