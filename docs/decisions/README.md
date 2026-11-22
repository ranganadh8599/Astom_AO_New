# Architecture decisions

Short records of decisions that were **measured**, not just preferred. Each one exists
because the obvious alternative was tried and either failed or changed nothing — so
re-litigating it should start from the evidence.

Format: context → decision → consequences. Numbers are the setup that produced them.

| # | Decision | Status |
|---|---|---|
[0001](0001-coverage-gate-before-planning.md) | Ask a coverage question before planning | Accepted |
[0002](0002-no-relevance-score-threshold.md) | No relevance-score threshold | Accepted |
[0003](0003-deterministic-merge.md) | Merge has no model | Accepted |
[0004](0004-one-trace-per-message.md) | One trace per message, one session per conversation | Accepted |
[0005](0005-planner-only-routing.md) | Routing happens only in the planner — no heuristic fallback | Accepted |
[0006](0006-read-only-by-capability.md) | Read-only guaranteed by capability, not by classification | Accepted |
[0007](0007-postgres-pooling.md) | Pooled Postgres connections, probed on readiness | Accepted |
[0008](0008-query-building-and-resilient-search.md) | Build standalone search queries; classify search failures | Accepted |

## Amending one

Don't edit an accepted decision to say something different — add a new ADR that supersedes
it and link both ways. The value of these records is that they show what was believed at
the time, with the evidence available then.
