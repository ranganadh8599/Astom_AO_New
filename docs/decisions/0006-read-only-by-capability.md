# 0006 — Read-only guaranteed by capability, not by classification

**Status:** Accepted · **Date:** 2026-11 (POC)

## Context

The orchestrator must never create, change, delete or approve anything. Two ways to get
that:

1. **Classify intent** and refuse when the model says `mutation`.
2. **Only register read-only capabilities**, so even a permissive verdict has nothing to
   invoke.

Classification alone is not a guarantee: a model can mislabel, and a pattern list can be
bypassed or drift. Capability alone is not enough either — without a refusal, a mutation
request would be routed to a read-only tool and produce a confusing answer.

## Decision

Both, with the **structural guarantee being capability**.

- Only read-only agents and tools are registered on the gateway. That is the real control.
- `read_only_policy.py` holds **no detection logic at all** — no pattern list to bypass and none to
  drift out of date. It only composes the refusal message.
- The intent verdict comes from the gate and from the planner, and a `mutation` verdict ends
  the turn at either point:

  ```
  check_coverage → mutation → rejected
  plan_tasks     → mutation → rejected
  ```

Two checks because they are cheap and independent. The gate has seen the candidates; the
planner has seen the task list.

- **No human-in-the-loop path.** No interrupt, no approval queue, no resumable pending
  change. A refusal is final for the turn.

## Consequences

- A permissive `read` verdict still cannot do damage, because nothing writable is reachable.
- A false `mutation` costs a refusal, not an incident. The refusal names the reason:
  `I can't carry out that change. ... Why: <planner's reason>`.
- **Adding a writable capability invalidates this.** If a mutating tool is ever registered,
  a deterministic veto must go in front of execution — trusting the classifier alone is
  explicitly not sufficient. That warning is in the module docstring, where the next person
  editing it will see it.
- `READ_ONLY_MODE=false` disables the refusal for experiments; it does not make writes
  possible, because none are registered.

## Alternatives rejected

| Alternative | Why not |
|---|---|
classifier only | mislabels are unauditable and a pattern list always drifts |
capability only | mutation requests route to read-only tools and get confusing answers |
approval workflow | needs state, a UI and a resume path; out of scope for a read-only layer |

## Evidence

`src/orchestrator/routing/read_only_policy.py`, `src/orchestrator/graph/nodes.py` (`check_coverage`, `plan_tasks`),
`README.md#what-it-does-today`.
