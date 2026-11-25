# Routing: how a target gets chosen

One model decides where a request goes. Everything around it exists because that model
is measurably bad at one specific thing — saying *no*.

```
validate_input → retrieve_targets → check_coverage → plan_tasks → run_task × N → compose_answer
```

## Validate input

`validate_input` checks input shape only. It does **not** classify intent, refuse mutations, or detect smalltalk —
those happen later, and putting them here would mean two places could reject a request.

| Condition | Result |
|---|---|
| empty query | `status: failed`, `error: "empty user query"` |
| more than 8000 chars | `status: failed` |
| otherwise | clears `results`, `notes`, `tasks`, `candidates`, and records the query in `history` |

The reset matters: `results` and `notes` are turn-scoped, and without clearing them a
long conversation would replay the previous turn's results forever. `history` is the only
key that accumulates.

## Discovery and retrieval

Ranking lives in the gateway; selection lives here. Per turn, each surface is asked
separately:

| Protocol | Retrieval call | Fallback when unavailable |
|---|---|---|
A2A | `GET /v1/agents?query=<message>&top_k=N` | list the catalogue |
MCP | `POST /mcp-rest/tools/call` → `mcp_tool_search{query, top_k}` | list the catalogue |
models | none — always listed | n/a |

Results are **interleaved**, so neither protocol can starve the other once a cap applies.
The turn records which path each surface used:

```
retrieve: 3 target(s) via a2a=listing, mcp=search
```

The count is the **union** of every surface — A2A agents, MCP tools and configured models —
de-duplicated, interleaved and capped. It is not a per-protocol count.

| Part | Means | Not to be read as |
|---|---|---|
| `3 target(s)` | the merged list handed to the gate | 3 agents, or 3 per protocol |
| `a2a=listing` | the agent catalogue was listed unranked, and `CANDIDATE_MAX_TARGETS` did not cut it | a failure — `listing` means complete |
| `mcp=search` | the gateway ranked MCP tools for this turn | that the hits are relevant — the gate decides |
| `model=listing` present | `MODEL_TARGETS` is configured; models are always listed, never ranked | a search result |

The `mcp=search` is the normal signature of MCP search enabled on the key. MCP search is DB-backed
(`mcp_tool_search_enabled`), while A2A search needs `agent_search_embedding_model` in
`config.yaml` plus a restart.

The mode is one of:

| Mode | Meaning |
|---|---|
| `search` | the gateway ranked the targets |
| `search-empty` | search worked and found nothing |
| `search-partial` | several queries were searched and at least one failed; the rest were used |
| `listing` | search is not configured (or switched off), so the catalogue was listed |
| `listing-truncated` | as above, but the cap hid targets, so routing may have missed one. **The important signal.** |
| `listing-after-search-error` | search is configured but failed this turn even after retries; listed for this turn only |

(`-after-search-error` can be appended to `listing-truncated` too.)

### Building the search queries

Searching with the raw message fails in two ways: a follow-up like "and in 2016?" embeds as
nothing in particular, and a message with several questions embeds as the average of its
topics. `QueryBuilder` (`routing/query_builder.py`) fixes both with one cheap model call:

- It runs only when needed: a short message with prior turns, or a message that looks like
  several asks (two question marks, several lines, or a long message joined by "and / also").
  A self-contained single question costs no extra call.
- It returns up to `QUERY_REWRITE_MAX_QUERIES` standalone queries, using the recent
  conversation to resolve pronouns and omitted subjects.
- Each query is searched separately and the ranked lists are merged by reciprocal rank
  fusion (`routing/rank_fusion.py`), so each topic keeps its best target in the shortlist.
- Any failure (model error, unparsable reply) searches the raw message instead. The
  coverage gate and the planner always receive the original message, not the rewrite.

Rewritten queries are recorded in the turn notes as `retrieve: search queries: a | b`.

### When search fails

| Failure | Handling |
|---|---|
| not configured (no embedding model, key without tool search) | listed, and remembered for `SEARCH_UNAVAILABLE_TTL_S` so it is not re-probed every turn |
| transient (timeout, 429, 5xx) | retried `SEARCH_RETRIES` times, then listed for **this turn only**; search is tried again next turn |
| one of several queries fails | the others are used (`search-partial`) |

Before this was split, any search error switched search off for a minute and every turn in
that window fell back to a truncated listing.

### Two different caps, deliberately

| Setting | Applies to | Why different |
|---|---|---|
`RETRIEVAL_TOP_K` (default 8) | a *search* result | ranking makes a short list safe |
`CANDIDATE_MAX_TARGETS` (default 40) | a *listing* | a listing has no ranking, so cutting it short can hide the right target |

### When is search actually required?

Measured, with `CANDIDATE_MAX_TARGETS=40`:

| Registered targets | Without search | With search |
|---|---|---|
10 | sees 10, `listing` | — |
40 | sees 40, `listing` | — |
100 | sees 40, **`listing-truncated`** — a target can be hidden | sees the right one |
500 | sees 40, **`listing-truncated`** | sees the right one |

So the gateway's embedding config is **not required for correct routing** below the prompt
budget. Above it, unranked listing can hide a target — and the turn says so through
`listing-truncated` rather than failing silently.

Enabling search:

- **MCP** — no config file. Set `mcp_tool_search_enabled: true` under the key's
  `object_permission`; it is DB-backed, so `PATCH`/`/key/update` works.
- **A2A** — needs `litellm_settings.agent_search_embedding_model` in the gateway's
  `config.yaml` plus a restart. There is no API or env equivalent.

**Agent search ranks; it does not filter.** `GET /v1/agents` accepts only `query` and
`top_k` — no `similarity_threshold` — and returns a `search_score` per agent which is
passed to the gate and planner as a weak hint. Nothing in the orchestrator filters on it.
MCP search *is* thresholded, by the gateway (`similarity_threshold: 0.2` on
`mcp_tool_search`), which is why `mcp=search-empty` can occur.

A routing miss is never disguised as an empty catalogue: "no target matched" is reported
distinctly from "nothing is registered".

### Who filters, and who decides

Three layers, one job each. Conflating them produced a routing bug worth recording.

| Layer | Job | Where |
|---|---|---|
retrieval ranking + cutoff | order candidates by cosine, drop the irrelevant | **gateway** — `mcp_tool_search` with `embedding_model` and `similarity_threshold` |
coverage | can *anything* answer at all? (`route` / `no_match` / `mutation`) | orchestrator `check_coverage` |
selection | which target, what instruction, what arguments | orchestrator `plan` |

Filtering belongs at the gateway because it is backed by embeddings and a score. Both
settings are readable and changeable at runtime:

```bash
curl -s localhost:4001/get/mcp_tool_search_settings -H "Authorization: Bearer $ADMIN_KEY"
# {"values":{"embedding_model":"openai/text-embedding-3-small","top_k":5,
#            "similarity_threshold":0.2,"core_tools":[]}, ...}
```

`PATCH /update/mcp_tool_search_settings` reaches every pod within ~10s, no restart, and
the same block backs `/mcp/proxy`'s `search_tools`.

**`core_tools` is the supported way to pin a tool.** A name listed there comes back first
on *every* search, without a score, and does not count against `top_k` — cheaper and more
reliable than tuning a threshold for phrasing that must always work:

```json
{"core_tools": ["field_ops-list_open_incidents"]}
```

A listed tool the caller's key cannot reach is still omitted, so this never grants access.

**The orchestrator must not add a second filter or a second ranking.** Both were tried:

- **Filtering candidates by the gate's `targets`** made one wrong verdict permanent.
  Retrieval ranked the correct tool at 0.63 while the gate named the 0.39 one, and the
  planner received only the latter — it had no correct option left to choose.
- **Passing the gate's list as a "Gate hint" beside the scores** fixed that but caused
  over-routing: the planner fanned out to *two* targets for a one-target question, because
  two competing rankings made both look defensible.

The planner therefore gets exactly one ordered list — the gateway's — and the gate's
opinion is recorded in the turn notes and trace, never injected into the prompt.

This does not contradict [ADR 0002](../decisions/0002-no-relevance-score-threshold.md). That
decision removed a **local** threshold in the orchestrator, which measured no better than
nothing because it second-guessed scores from the same uncalibrated source. The gateway
threshold is different: it is applied *before* ranking is exposed, on text the gateway
owns, and the ranking is built on it.

## Why a separate gate

The planner is good at choosing between plausible options and bad at declining. Measured
on a 12-target registry (`text-embedding-3-small`):

| Approach | In-domain correct | Irrelevant rejected |
|---|---|---|
planner alone | 8/10 | **2/7** |
planner + scores in prompt | 9/10 | 2/7 |
threshold 0.15 | 10/10 | 5/7 |
threshold 0.25 (fitted to this data) | 9/10 | 7/7 |
**coverage gate** | 9/10 | **7/7** |
**gate + scores** | **10/10** | **7/7** |

Asked to route directly, the planner confidently sent `kubernetes crashloopbackoff` to an
IT agent. Asking the coverage question *first* rejected 7 of 7 irrelevant queries while
keeping valid ones routed. Score thresholds either did nothing useful (0.15) or were
fitted to the test set (0.25).

The decision contract mirrors `multi-agent-orchestator/classifiers/open_ai_classifier.py`
in this workspace — a first-class `no_match` outcome with a mandatory reason:

```json
{"can_answer": false, "targets": [], "reason": "no target covers astronomy", "confidence": 0.92}
```

Two deliberate differences from that implementation:

- **confidence is the model's own judgement**, never a cosine value presented as a
  probability. Embedding scores are not calibrated across registries.
- **a self-contradictory reply** (`can_answer=false` while listing targets) is recorded in
  the turn's notes rather than silently resolved.

### A malformed gate reply is unusable, not a decline

If the gate's answer cannot be parsed, the turn **continues to planning**. A formatting
slip must not discard a valid query, and the planner is still a gate behind it. The
opposite choice — treating unparseable as `no_match` — would turn a model hiccup into a
user-visible refusal.

### Smalltalk short-circuits before the gate

Greetings, thanks and "what can you do?" are answered deterministically: no model call, no
target, personalised from the caller's display name. Routing them would spend a call to
produce nothing, and declining them ("nothing covers that") is wrong for "hi".

A leading greeting is stripped before retrieval, so `"hi, what is our leave policy?"` is
treated as the question it is.

## Planning

One model call, no local fallback. It returns intent **and** the task list:

```json
{"intent": "read", "reason": "asking about leave policy",
 "tasks": [{"agent": "hr-policy-agent", "instruction": "...", "arguments": {}}]}
```

- `PLANNER_MODEL` must name a model the gateway serves. If it cannot be reached the turn
  fails rather than degrading to a guess.
- The planner never sees a target the gate did not pass through.
- `MAX_AGENTS_PER_REQUEST` caps tasks; the planner may propose more and the extras are
  dropped.
- MCP task arguments are validated against the tool's own `inputSchema` **before** the call
  leaves. A missing argument fails locally instead of producing a confusing backend error.

### Transient failures are retried, bounded

| Failure | Retries | Backoff |
|---|---|---|
HTTP 429 (upstream rate limit) | 4 | 1s, 2s, 4s, 8s |
unparseable reply | 1 | immediate, with a corrective prompt suffix |
any other gateway error | 0 | fails immediately |

The distinction matters: a 400 caused by misconfiguration cannot succeed on retry. The
429 case is real — measured 18 rate-limit events absorbed across three collection runs
with no turn failures.

The turn's error names which happened:

```
planner did not return a usable decision (gateway error: POST /v1/chat/completions -> 429)
planner did not return a usable decision (replies could not be parsed as JSON; last reply started with ...)
```

## Fan-out

LangGraph `Send`, so independent tasks run concurrently:

```
plan_tasks ─┬─→ run_task(A) ─┐
            ├─→ run_task(B)  ─┼─→ compose_answer
            └─→ run_task(C) ─┘
```

`compose_answer` starts only after every branch completes, because `results` is an add-reducer list.
Mixed protocols in one turn are normal — a single question can hit one MCP tool and one
A2A agent.

## Compose answer

`compose_answer` is deterministic on purpose. It cannot invent a fact, and it preserves attribution:

| Results | Output |
|---|---|
1, succeeded | the text, verbatim — a heading is noise, not information |
1, failed | `"<agent> could not answer: <error>"` |
many | `### <agent>` section per result, failures marked `_Failed: ..._` |

The overall turn status is `completed` if **any** result succeeded, so a partial failure is
reported honestly rather than failing the whole answer.

`compose_answer` makes no model call. A summarising merge would be the obvious "improvement" and
would reintroduce exactly the hallucination risk the rest of the design avoids.

## Boot-time model check

A typo in `PLANNER_MODEL` or `GATE_MODEL` used to surface only as the gate quietly
stopping — a 404 was swallowed and the turn degraded to planning. The check now runs
**after** startup, as a background task, so boot never waits on the gateway.

| Gateway response | `models.status` | Process |
|---|---|---|
serves one token | `ok` | keeps running |
404 / 403 (rejected) | `failed`, with the reason | keeps running, logged as an error |
timeout / 5xx / unreachable | `degraded`, with a warning | keeps running |

`pending` is not a failure: a liveness probe must not fail on something that resolves a
second later.

Measured effect on startup with a dead gateway:

| | before | after |
|---|---|---|
startup time | 3378 ms | 363 ms |

One subtlety: a virtual key carrying a wildcard pattern (`openai/*`) can call models it
does not advertise — `gpt-4o-mini` works on this stack but is absent from `/v1/models`.
Treating that list as a gate would reject valid configuration, so an unlisted-but-working
model is a **warning**, and the real completion is the authority.
`MODEL_PREFLIGHT_ENABLED=false` skips the check entirely.

## Health endpoints

Two endpoints, two different questions. `/health` is liveness and always returns 200 while
the process runs; `/ready` returns 503 when the instance genuinely cannot serve traffic.

| Condition | `/health` | `/ready` | Why |
|---|---|---|---|
`models.status: pending` | 200 | 200 | check unfinished; normal startup |
`models.status: ok` | 200 | 200 | gateway answered |
`models.status: degraded` | 200 | **200** | gateway unreachable — not this instance's fault; pulling every pod would turn a blip into an outage |
`models.status: failed` | 200 | **503** | model rejected; permanently broken, but the pod stays alive for debugging |
`memory.reachable: false` | 200 | **503** | checkpointer cannot reach its database; every turn would 500 |

Failing liveness on `failed` would restart the container in a loop over a typo. Failing
readiness on `degraded` would remove healthy instances because the *gateway* hiccuped.

```yaml
livenessProbe:  { httpGet: { path: /health } }
readinessProbe: { httpGet: { path: /ready, port: 8001 } }
```

`/health` also carries `memory_state`, the **cached** probe result — never a live query, so
liveness cannot flap on a database blip. `/ready` is the only place that probes. The
checkpointer half of that is covered in [memory.md](memory.md#health-ready-never-health).

## Related

- [decisions/0001](../decisions/0001-coverage-gate-before-planning.md) — why the gate exists
- [decisions/0002](../decisions/0002-no-relevance-score-threshold.md) — why there is no score threshold
- [decisions/0003](../decisions/0003-deterministic-merge.md) — why merge has no model
- [decisions/0005](../decisions/0005-planner-only-routing.md) — why there is no heuristic fallback
- [decisions/0007](../decisions/0007-postgres-pooling.md) — pooled connections, probed on readiness
- [memory.md](memory.md) — what the planner can see of previous turns
