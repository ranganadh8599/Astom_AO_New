# Documentation

Where to look, by what you need to do.

## Understand how it works (`architecture/`)

| Doc | Answers |
|---|---|
[diagrams.md](architecture/diagrams.md) | one Mermaid picture per configuration: the turn, each retrieval mode, identity, tracing, memory, caps |
[hld.md](architecture/hld.md) | high-level design: purpose, actors, containers, topology, responsibilities, non-functional targets, known gaps |
[lld.md](architecture/lld.md) | low-level design: module map, node contracts, state schema, gateway API, error taxonomy, invariants, test map |
[routing.md](architecture/routing.md) | how a target gets chosen: query building, retrieval, the coverage gate, the planner, fan-out, and the measured accuracy numbers |
[memory.md](architecture/memory.md) | conversation state: in-process vs Postgres, DSN to database name, restart semantics, the Windows event-loop trap |
[tracing.md](architecture/tracing.md) | how one trace spans LibreChat and the orchestrator, per-message vs per-conversation, Langfuse environment validation |
[authorization.md](architecture/authorization.md) | three layers of access control: which key reaches which route, per-user entitlement (not implemented), SSO identity |

## Why it is built this way (`decisions/`)

[Decision records](decisions/README.md): the choices that were measured, with the evidence that settled them.

## Do something (`guides/`)

| Guide | Covers |
|---|---|
[user-guide.md](guides/user-guide.md) | **start here**: run the service, authenticate, ask a question, use the Postman suite, register agents / MCP servers / models, fetch agent cards |
[deployment.md](guides/deployment.md) | containers, compose, gateway networking, health checks, backup, **and the 40-service example-suite stack** |
[litellm-gateway-config.md](guides/litellm-gateway-config.md) | **the gateway side**: prerequisites, `config.yaml`, DB-backed search settings, grants, and every change needed to add an agent, MCP server or model |
[onboard-ronaldo-agent.md](guides/onboard-ronaldo-agent.md) | registering an A2A agent end to end |
[field-ops-mcp-server.md](guides/field-ops-mcp-server.md) | running and registering the sample MCP server |
[librechat-agent-as-model.md](guides/librechat-agent-as-model.md) | exposing a LibreChat agent as a LiteLLM model |
[sso-integration.md](guides/sso-integration.md) | LibreChat to orchestrator identity: token forwarding vs shared key |
[api-key-scoping.md](guides/api-key-scoping.md) | key and team permission resolution in detail |
[entitlement-design.md](guides/entitlement-design.md) | per-user authorization options and the deferred role gate |
[../examples/a2a_suite/README.md](../examples/a2a_suite/README.md) | 20 A2A agents on disjoint topics, with ports and sample questions |
[../examples/mcp_suite/README.md](../examples/mcp_suite/README.md) | 20 MCP servers of read-only lookup tools, with ports and tool lists |

## Try the API (`postman/`)

[postman/README.md](postman/README.md) explains the 109-request collection;
[examples.md](postman/examples.md) lists every request with its captured response.

## Measure routing quality

[../evals/README.md](../evals/README.md): score retrieval and the coverage gate against questions you label.

## The shape of a turn

```
validate_input -> retrieve_targets -> check_coverage -+-(no match)-> END
                                                      +-(smalltalk)-> END
                                                      +-(write request)-> END  (read-only refusal)
                                                      +-> plan_tasks -+-> run_task (a2a agent) -+
                                                                      +-> run_task (mcp tool)  -+-> compose_answer -> END
                                                                      +-> run_task (a2a agent) -+
```

| Node | One job | Cost | Doc |
|---|---|---|---|
`validate_input` | input shape and limits; clears per-turn state | 0 | [routing.md](architecture/routing.md#validate-input) |
`retrieve_targets` | build search queries, ask the gateway what is relevant | 0-1 LLM call + 2 gateway calls per query | [routing.md](architecture/routing.md#discovery-and-retrieval) |
`check_coverage` | can anything answer at all? read or write? | 1 LLM call | [routing.md](architecture/routing.md#why-a-separate-gate) |
`plan_tasks` | which targets, what instructions, what arguments | 1 LLM call | [routing.md](architecture/routing.md#planning) |
`run_task` | one call per task, concurrent, mixed protocols | 1 per task | [routing.md](architecture/routing.md#fan-out) |
`compose_answer` | attribute each result to its source, invent nothing | 0 | [routing.md](architecture/routing.md#compose-answer) |

State lives in the checkpointer between turns: see [memory.md](architecture/memory.md).

## Conventions

- **Measured numbers are labelled as such**, with the setup that produced them.
- **Failure modes are documented with the real error text**, because that is what you search for.
- Anything marked **not implemented** has a design note and no code.
