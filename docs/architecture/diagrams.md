# Diagrams

One page, one picture per configuration. Every diagram is derived from the code paths
described in [routing.md](routing.md), [memory.md](memory.md), [tracing.md](tracing.md) and
[authorization.md](authorization.md); read those for the why, this page for the shape.

Nothing here is rendered by the application — Mermaid blocks render on GitHub and in VS Code's
Markdown preview (current versions; otherwise install "Markdown Preview Mermaid Support").

## Which diagram do I need?

| Question | Diagram |
|---|---|
| What happens to one user message? | [The turn](#the-turn) |
| What does a healthy default deployment look like? | [Config A · search everywhere](#config-a--search-everywhere) |
| Why is A2A `listing` while MCP is `search`? | [Config B · A2A unranked](#config-b--a2a-unranked) |
| When does the whole catalogue get listed? | [Config C · listing only](#config-c--listing-only) |
| What is `listing-truncated`? | [Config E · catalogue larger than the cap](#config-e--catalogue-larger-than-the-cap) |
| Which auth mode does what? | [Identity modes](#identity-modes) |
| Why do my traces split in two? | [Trace resolution](#trace-resolution) |
| Which setting bounds what? | [Cap map](#cap-map) |
| Where does conversation state live? | [Memory backends](#memory-backends) |
| Which calls need the admin key? | [Gateway access layers](#gateway-access-layers) |
| Are models routable targets? | [Model targets](#model-targets) |
| What breaks when the gateway is down? | [Boot and readiness](#boot-and-readiness) |

## The turn

Every request — `/v1/orchestrate`, or `/v1/chat/completions` for LibreChat — runs the same
graph.

```mermaid
flowchart TD
    IN["message + conversation_id"] --> V["validate_input<br/>shape + 8000 char limit<br/>clears results, notes, tasks"]
    V -->|"empty or too long"| F["status: failed"]
    V --> R["retrieve_targets<br/>query builder + gateway ranking"]
    R --> SM{"smalltalk?<br/>SMALLTALK_ENABLED"}
    SM -->|"greeting, thanks, what can you do"| A0["deterministic reply<br/>no model call, no target"]
    SM -->|no| G{"check_coverage<br/>can anything answer?<br/>read or write?"}
    G -->|"no_match"| A1["decline with the reason"]
    G -->|"mutation and READ_ONLY_MODE=true"| A2["read-only refusal"]
    G -->|"reply unparsable"| P["plan_tasks<br/>malformed gate reply is not a decline"]
    G -->|"read"| P
    P -->|"planner unreachable or unparseable"| F
    P --> FN["fan_out: one Send per task<br/>capped at MAX_AGENTS_PER_REQUEST"]
    FN --> T1["run_task · A2A agent"]
    FN --> T2["run_task · MCP tool"]
    FN --> T3["run_task · model target"]
    T1 --> C["compose_answer<br/>deterministic, no model call"]
    T2 --> C
    T3 --> C
    C --> OUT["answer + tasks + results + notes"]
    A0 --> OUT
    A1 --> OUT
    A2 --> OUT
    F --> OUT
```

`compose_answer` waits for every branch because `results` is an add-reducer list. Status is
`completed` if **any** result succeeded, so a partial failure is reported rather than hidden.

## Retrieval: how modes are chosen

Decided per protocol, per turn — never globally.

```mermaid
flowchart TD
    START["retrieve_targets"] --> ENA{"protocol enabled?<br/>PROTOCOLS / MCP_ENABLED"}
    ENA -->|no| EMPTY["contributes no targets<br/>mode not reported"]
    ENA -->|yes| ON{"RETRIEVAL_ENABLED<br/>and not marked off?"}
    ON -->|no| LIST
    ON -->|yes| QB["query builder<br/>only when the message needs it"]
    QB --> SR["search each query<br/>top_k = RETRIEVAL_TOP_K"]
    SR --> ANY{"any ranked list?"}
    ANY -->|yes| OK["mode: search<br/>+ -partial if a query failed"]
    ANY -->|"all not configured"| OFF["mark search off<br/>SEARCH_UNAVAILABLE_TTL_S"] --> LIST
    ANY -->|"all failed after retries"| ERRL["mode: listing-after-search-error"] --> LIST
    LIST{"catalogue larger than<br/>CANDIDATE_MAX_TARGETS?"}
    LIST -->|no| L1["mode: listing<br/>complete, safe"]
    LIST -->|yes| L2["mode: listing-truncated<br/>a target may be hidden"]
```

`MODEL_TARGETS` bypasses this entirely: models are always listed, never searched, because
there is no relevance endpoint for "which model fits".

## Config A · search everywhere

Both surfaces ranked. The normal production shape when the gateway is fully configured.

```mermaid
flowchart LR
    M["user message"] --> A["A2A search<br/>GET /v1/agents?query=<br/>top_k=8"]
    M --> T["MCP search<br/>mcp_tool_search<br/>top_k=8, threshold 0.2"]
    M --> MD["model targets<br/>always listed"]
    A --> I["interleave"]
    T --> I
    MD --> I
    I --> CAP["cap 40<br/>max search_cap, listing_cap"]
    CAP --> G["coverage gate"]
    G --> P["planner"]
```

Turn note: `retrieve: 3 target(s) via a2a=search, mcp=search, model=listing`

## Config B · A2A unranked

MCP search is DB-backed (`mcp_tool_search_enabled` on the key); A2A search needs
`agent_search_embedding_model` in the gateway's `config.yaml` **plus a restart**. Mixed
modes are normal, not a fault.

```mermaid
flowchart LR
    M["user message"] --> A["A2A listing<br/>GET /v1/agents<br/>cap 40"]
    M --> T["MCP search<br/>ranked, top_k=8"]
    A --> I["interleave"]
    T --> I
    I --> G["coverage gate"]
```

Turn note: `retrieve: 3 target(s) via a2a=listing, mcp=search`

`listing` (not `listing-truncated`) proves the agent catalogue fit under the cap, so
unranked listing is safe here.

## Config C · listing only

`RETRIEVAL_ENABLED=false`, or every surface reported "not configured", or each protocol
disabled. The fallback path.

```mermaid
flowchart LR
    M["user message"] --> C["catalogue from<br/>all_targets()<br/>CARD_CACHE_TTL_S=300"]
    C --> A["A2A targets<br/>first 40"]
    C --> T["MCP tools<br/>first 40"]
    C --> MD["model targets<br/>all"]
    A --> I["interleave"]
    T --> I
    MD --> I
    I --> G["coverage gate"]
```

Turn note: `retrieve: N target(s) via a2a=listing, mcp=listing`

Listing is **unranked**, so order is arbitrary — this is why the cap is 40 and not 8.

## Config D · search fails this turn

Transient failure (timeout, 429, 5xx) after `SEARCH_RETRIES`; search is retried next turn,
not switched off.

```mermaid
sequenceDiagram
    participant O as orchestrator
    participant G as gateway
    O->>G: search (attempt 1)
    G-->>O: 503
    O->>O: sleep SEARCH_RETRY_BACKOFF_S
    O->>G: search (attempt 2)
    G-->>O: 503
    O->>O: mark listing-after-search-error for this turn only
    O->>G: GET /v1/agents (listing)
    G-->>O: full catalogue
    Note over O: next turn probes search again
```

Contrast with "not configured" (no embedding model, key without tool search): that marks
the surface off for `SEARCH_UNAVAILABLE_TTL_S` so it is not re-probed every turn. Before
this split existed, one transient error disabled search for a minute and every turn in that
window fell back to a truncated listing.

## Config E · catalogue larger than the cap

`CANDIDATE_MAX_TARGETS=40` with 100+ registered targets and no search. The turn says so
instead of failing silently.

```mermaid
flowchart LR
    C["catalogue: 100 targets"] --> CAP["take first 40"]
    CAP --> G["coverage gate"]
    G --> P["planner"]
    P --> R["route may be wrong:<br/>the right target was #73"]
    CAP -.->|"note"| N["listing-truncated"]
```

Measured: 10 or 40 targets → `listing`, correct. 100 or 500 → `listing-truncated`, and the
correct target is found only once search is enabled. Treat the mode as an actionable signal,
not a warning to ignore.

## Cap map

What each limit applies to. They are not interchangeable.

```mermaid
flowchart TD
    Q["turn"] --> R["retrieval"]
    R -->|"per search call"| K1["RETRIEVAL_TOP_K = 8"]
    R -->|"fusion of rewritten queries"| K2["top_k x min(queries, 2)"]
    R -->|"listing, and final union cap"| K3["CANDIDATE_MAX_TARGETS = 40"]
    R --> G["coverage gate"]
    G --> P["planner"]
    P -->|"tasks created"| K4["MAX_AGENTS_PER_REQUEST = 4"]
    K4 --> F["fan-out: all tasks run concurrently"]
    F -->|"per task"| K5["REQUEST_TIMEOUT_S = 60"]
    P -->|"history given to the planner"| K6["HISTORY_MAX_TURNS = 6"]
```

There is **no concurrency limiter**: `MAX_AGENTS_PER_REQUEST` bounds how many branches
exist, not how many run at once. Lowering it reduces load and breadth together.

## Identity modes

Four `AUTH_MODE` values, one `UserContext` shape. Only `entra` and `dev` enforce a role.

```mermaid
flowchart TD
    REQ["Authorization: Bearer ..."] --> MODE{"AUTH_MODE"}
    MODE -->|dev| DEV["HS256 local JWT<br/>issuer + audience pinned"]
    MODE -->|entra| ENT["tenant JWKS<br/>issuer + audience pinned<br/>ENTRA_REQUIRED_ROLE optional"]
    MODE -->|shared_key| SK["constant-time key compare<br/>+ unsigned user header"]
    MODE -->|none| NUL["constant anonymous"]
    DEV --> CTX["UserContext<br/>oid, name, email, roles, tenant_id"]
    ENT --> CTX
    SK --> CTX
    NUL --> CTX
    CTX --> ROUTES["every route, via one dependency"]
```

| Mode | Proves | Gap |
|---|---|---|
`dev` | the token is self-signed by this process | not for anything shared |
`entra` | signature, issuer, audience, expiry | behind LibreChat SSO it validates **LibreChat's** audience, so any LibreChat token opens the orchestrator (OBO gap) |
`shared_key` | the caller holds the key | identity is an unsigned header — a key holder can impersonate any user |
`none` | nothing | localhost only |

Every mode produces the same `UserContext`, so switching modes changes only which validator
is constructed.

## Authorization layers

Three questions, three places. Only layers 1 and 3 are implemented.

```mermaid
flowchart TD
    U["alice / bob / carol"] --> LC["LibreChat"]
    LC -->|"ORCH_SHARED_KEY or Entra token<br/>+ user headers"| L3["Layer 3 · identity<br/>AUTH_MODE validator"]
    L3 --> ORCH["orchestrator<br/>read-only"]
    ORCH --> L2["Layer 2 · entitlement<br/>may this user reach this agent?<br/>NOT IMPLEMENTED"]
    L2 -.->|"one shared key for all users"| GW["LiteLLM gateway"]
    ORCH -->|"LITELLM_API_KEY<br/>allowed_routes = llm_api_routes"| L1["Layer 1 · route + resource<br/>key ∩ team"]
    L1 --> OK["agents, MCP tools, models"]
    L1 -->|"/key, /team, /model, /get, /update"| D403["403 by design"]
    ADMIN["operator CLI only"] -->|"LITELLM_ADMIN_KEY"| GW
```

## Trace resolution

`traceparent` wins outright, which is why a static one breaks the join. LibreChat's path is
the message id, not W3C.

```mermaid
flowchart TD
    IN["inbound request"] --> TP{"traceparent valid?<br/>00-32hex-16hex-flags"}
    TP -->|yes| USE1["use it<br/>LibreChat id ignored"]
    TP -->|no| MID{"x-librechat-message-id?"}
    MID -->|yes| USE2["trace_id = sha256(messageId)[:32]<br/>same id LibreChat used"]
    MID -->|no| CONV{"session id and<br/>TRACE_PER_CONVERSATION?"}
    CONV -->|yes| USE3["conversation-derived id"]
    CONV -->|no| USE4["new root id per turn"]
    USE1 --> OUT["traceparent + x-litellm-trace-id<br/>on every gateway call"]
    USE2 --> OUT
    USE3 --> OUT
    USE4 --> OUT
    OUT --> LF["Langfuse<br/>session = conversation"]
```

| Send from LibreChat | Result |
|---|---|
`X-LibreChat-Message-Id` only | one trace, joined |
`traceparent` derived from the same digest | one trace |
`traceparent` with any other id | **two disconnected trees** |
neither, `TRACE_PER_CONVERSATION=true` | two trees |
neither, `TRACE_PER_CONVERSATION=false` | new root each turn |

Langfuse is the sink, not the carrier: it is told the id via `trace_context`, and it is not
involved in propagation. With `LANGFUSE_*` blank the tracer is a no-op and `traceparent`
still goes out, so gateway logs stay correlated.

## Memory backends

`CHECKPOINT_BACKEND` decides where conversation state lives. History survives a turn either
way; only Postgres survives a restart.

```mermaid
flowchart LR
    subgraph MEM["CHECKPOINT_BACKEND=memory"]
        R1["restart"] --> L1["history lost<br/>new thread per conversation"]
    end
    subgraph PG["CHECKPOINT_BACKEND=postgres"]
        DSN["POSTGRES_DSN<br/>path segment = database"] --> T["checkpoint tables<br/>auto-created, POSTGRES_AUTO_CREATE"]
        T --> R2["restart"]
        R2 --> L2["history kept"]
    end
    READY["/ready"] -->|"probes the pool live"| PG
    HEALTH["/health"] -->|"cached result only"| MEM
```

On Windows, `python -m orchestrator` supplies the event loop psycopg needs; the plain
`uvicorn` CLI hard-codes one it refuses.

## Gateway access layers

Two independent gates on one call, checked in this order.

```mermaid
flowchart TD
    CALL["orchestrator gateway call"] --> R{"route class allowed?<br/>allowed_routes"}
    R -->|"no: /key, /team, /model, /get, /update"| D["403 not allowed to call this route"]
    R -->|yes| T{"team permits the resource?"}
    T -->|no| X["denied<br/>Key requests ... not allowed by team"]
    T -->|yes| K{"key permits it too?"}
    K -->|no| X2["denied<br/>access_denied / Access denied to agent"]
    K -->|yes| OK["200"]
```

Effective access is **key ∩ team**, and the team must be granted first. `agents: []` is
ambiguous — measured as denied on new keys and unrestricted on the orchestrator's own key —
so grant agent ids explicitly if agent access matters.

## Model targets

`MODEL_TARGETS` is empty by default; when set, models become routable targets beside agents
and tools.

```mermaid
flowchart LR
    subgraph OFF["MODEL_TARGETS empty"]
        O1["targets = agents + MCP tools"]
    end
    subgraph ON["MODEL_TARGETS=mai|facts only"]
        O2["targets = agents + MCP tools + mai"]
        O2 --> G["gate and planner may choose mai"]
        G --> INV["POST /v1/chat/completions"]
        INV --> REF{"reply matches REFUSAL_MARKERS?"}
        REF -->|yes| FAIL["task marked failed<br/>refusal reported, not passed through"]
        REF -->|no| ANS["answer"]
    end
```

Refusal detection applies to model targets only — never to A2A agents or MCP tools.

## Boot and readiness

The model check runs **after** startup, so a slow or wrong model name cannot delay boot.

```mermaid
stateDiagram-v2
    [*] --> pending: process started
    pending --> ok: gateway serves one token
    pending --> degraded: timeout, 5xx, unreachable
    pending --> failed: 404 or 403 rejected
    ok --> [*]
    degraded --> [*]
    failed --> [*]
```

| State | `/health` | `/ready` | Why |
|---|---|---|---|
`pending` | 200 | 200 | check unfinished; normal startup |
`ok` | 200 | 200 | gateway answered |
`degraded` | 200 | **200** | the gateway hiccuped, not this pod — pulling every pod would turn a blip into an outage |
`failed` | 200 | **503** | permanently broken config, but the pod stays alive for debugging |
memory unreachable | 200 | **503** | every turn would 500 |

`/health` reports the **cached** memory probe; only `/ready` probes live, so liveness cannot
flap on a database blip.

## Feature toggles

| Setting | `true` (default) | `false` |
|---|---|---|
`RETRIEVAL_ENABLED` | gateway ranks agents and tools | list the catalogue — debugging only |
`QUERY_REWRITE_ENABLED` | follow-ups and multi-question messages become standalone queries, merged by rank fusion | search the raw message |
`COVERAGE_GATE_ENABLED` | one call asks "can anything answer?" — measured 7/7 rejection of irrelevant queries | planner decides alone — measured 2/7 |
`SMALLTALK_ENABLED` | greetings answered deterministically, no model call | greetings go through the gate and may be declined |
`READ_ONLY_MODE` | mutating intents refused with an explanation | mutation verdict ignored — no approval flow exists |
`MODEL_PREFLIGHT_ENABLED` | background model check reported on `/health` | skip the check |
`LANGFUSE_TRACING_ENABLED` | spans exported; blank keys make the tracer a no-op | untraced; `traceparent` still propagates |

## Pointers

- [routing.md](routing.md) — every mode and cap in prose, with measured accuracy
- [tracing.md](tracing.md) — trace join, Langfuse environment validation, per-user attribution
- [authorization.md](authorization.md) — the three layers and what is not implemented
- [memory.md](memory.md) — checkpointer behaviour, DSN pitfalls, health semantics
