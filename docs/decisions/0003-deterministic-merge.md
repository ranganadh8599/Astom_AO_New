# 0003 — Merge has no model

**Status:** Accepted · **Date:** 2026-11 (POC)

## Context

After fan-out, N results have to become one answer. The obvious implementation is a
summarising LLM call: "combine these into a coherent reply".

Two problems with that here:

1. **It can invent.** A summariser is a generation step, and the whole point of routing to
   a specific agent is that the answer came from that agent. A summariser can state
   something none of them said.
2. **It destroys attribution.** When two agents disagree — or one fails — a summary
   flattens the disagreement into prose. The user cannot tell which target supplied which
   fact, or that one of them failed.

## Decision

`compose_answer` (the merge step) is deterministic. No model call.

| Results | Output |
|---|---|
single, succeeded | the text **verbatim** — no heading, because a heading is noise, not information |
single, failed | `"<agent> could not answer: <error>"` |
many | `### <agent>` section per result; failures rendered `_Failed: <error>_` |

Turn status is `completed` if **any** result succeeded, so a partial failure is reported
honestly rather than failing the whole answer.

## Consequences

- **Cannot hallucinate.** The merge step has no generative capability.
- **Every fact is attributable**, which is what makes a multi-agent answer trustworthy.
- **No prose polish.** The output can read like stitched sections. Accepted: correctness
  over elegance, and the single-result path avoids the wrapper entirely for the common case.
- **Failures are visible.** A target that declined or errored appears in the answer rather
  than disappearing.
- **Cost is zero** and latency is unchanged.

## Alternatives rejected

| Alternative | Why not |
|---|---|
summarising LLM call | can invent facts and destroys attribution |
"pick the best result" | needs a judge model; same hallucination risk, plus a tie-break rule |
concatenate with no structure | attribution lost in multi-result turns |

## Evidence

`src/orchestrator/graph/nodes.py` (`_compose`),
`docs/architecture/routing.md#merge`.
