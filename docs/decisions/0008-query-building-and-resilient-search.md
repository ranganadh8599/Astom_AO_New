# 0008: Build standalone search queries, and classify search failures

**Status:** Accepted

## Context

Retrieval searched the gateway with the user's literal message, and treated every search
error the same way. Reviewing it against real conversations showed three problems:

1. **Follow-ups lose their subject.** "And in 2016?" has no topic of its own, so its
   embedding matches nothing in particular. The conversation history was available to the
   gate and the planner but not to retrieval, which runs first and decides what they see.
2. **Several questions average out.** One embedding of a two-topic message sits between the
   topics, so with a small `top_k` one topic can lose its best target.
3. **One blip disabled search.** Any `GatewayError` from a search surface marked search
   unavailable for `SEARCH_UNAVAILABLE_TTL_S` (60 s). A single timeout therefore pushed
   every turn in that minute onto an unranked listing, truncated at `CANDIDATE_MAX_TARGETS`,
   which can hide the right target entirely. That setting exists for "not configured", which
   is a different condition from "broken right now".

## Decision

- **`QueryBuilder`** turns the message plus recent turns into up to
  `QUERY_REWRITE_MAX_QUERIES` standalone queries with one cheap model call. It runs only
  when a deterministic check says the message needs it (a short message with history, or
  several asks), so a self-contained question costs nothing extra. Any failure returns the
  raw message.
- Each query is searched separately and the rankings are merged with **reciprocal rank
  fusion**, which needs no comparable scores (scores are relative to their own query).
- The coverage gate and the planner still receive the **original** message. The rewrite is
  only for search; a wrong rewrite can therefore cost recall but never change what the user
  is answered about.
- **Search failures are classified.** "Not configured" keeps the old behaviour (remembered
  for the TTL). A transient failure is retried `SEARCH_RETRIES` times, then listed for that
  turn only and never remembered. If only some queries fail, the others are used.
- A search record that lacks the agent card no longer overwrites the cached record that has
  it.

## Consequences

- One extra model call on turns that need it, on the gate model unless `QUERY_REWRITE_MODEL`
  is set. `QUERY_REWRITE_ENABLED=false` removes it.
- Notes show what was searched (`retrieve: search queries: a | b`) and which mode each
  surface used, including `search-partial` and `listing-after-search-error`.
- The benefit is **not yet measured on a live gateway**. `evals/run_retrieval_eval.py`
  exists to do that: run it with `--no-rewrite` and without, on questions that include
  follow-ups and two-topic messages, and keep this decision only if recall improves.

## Where

`src/orchestrator/routing/query_builder.py`, `rank_fusion.py`, `target_catalog.py`
(`_retrieve_protocol`, `_search_one`), `graph/nodes.py` (`retrieve_targets`), `evals/`.
