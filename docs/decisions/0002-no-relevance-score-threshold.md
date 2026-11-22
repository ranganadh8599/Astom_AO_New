# 0002 — No relevance-score threshold

**Status:** Accepted (removes `AGENT_SEARCH_THRESHOLD`) · **Date:** 2026-11 (POC)

## Context

Agent search returns a `search_score` per agent. A numeric threshold in front of the
planner looks like cheap protection: drop candidates below 0.15 and the planner sees less
noise.

It was implemented and then measured:

```
outcome differences between threshold 0.0 and 0.10: 0   (9 queries)
LLM calls at 0.0:   gate=9 plan=3
LLM calls at 0.10:  gate=9 plan=4
```

Same routing decisions, effectively the same call count. And it could **hide a valid
target**: at 12 agents a valid query scored `0.209` while `kubernetes crashloopbackoff`
scored `0.215` — so no threshold separates the classes. Fitting to this data (0.25) gets
7/7 on irrelevant queries but 9/10 on valid ones, which is a model of the test set, not of
the problem.

## Decision

Remove the threshold. Coverage is decided in exactly **one** place: the gate
([0001](0001-coverage-gate-before-planning.md)). Prompt size is controlled by a visible
count, `CANDIDATE_MAX_TARGETS`.

## Consequences

- **A count that is wrong fails loudly** (`listing-truncated` in the turn's notes); a score
  threshold silently drops targets.
- **Fewer knobs.** No `AGENT_SEARCH_THRESHOLD` to tune per deployment, and no false sense
  of tuning.
- Scores are still passed to the gate and planner as a **weak hint**, clearly labelled as
  one in both prompts: "scoring is not calibrated and a high score does not guarantee
  fitness."

Measured comparison, same 12-target registry:

| Approach | In-domain correct | Irrelevant rejected |
|---|---|---|
threshold 0.15 | 10/10 | 5/7 |
threshold 0.25 (fitted) | 9/10 | 7/7 |
**gate** | 9/10 | **7/7** |
**gate + scores** | **10/10** | **7/7** |

The last row is why scores stay as a hint: they help the gate slightly. They do not
replace it and they are not a filter.

## Alternatives rejected

| Alternative | Why not |
|---|---|
threshold 0.15 | rejects only 5/7; keeps the failure mode |
threshold 0.25 | fitted to the measurement; will not generalise |
per-protocol thresholds | more knobs, same uncalibrated score |
"always search, never list" | unranked listing is correct below the prompt budget and needs no gateway config |

## Scope note: this is not the gateway's `similarity_threshold`

This ADR removes a threshold **inside the orchestrator**, applied to scores the
orchestrator had already received. The LiteLLM gateway's `mcp_tool_search.similarity_threshold`
is a different thing and stays: it cuts the catalog *before* ranking is exposed, on text
the gateway embeds itself. The orchestrator uses that ranking as its single ordered list
and adds nothing on top — see
[routing.md](../architecture/routing.md#who-filters-and-who-decides).

## Evidence

`src/orchestrator/routing/target_catalog.py` (`_retrieve_protocol`, `_listed`),
`docs/architecture/routing.md#when-is-search-actually-required`.
