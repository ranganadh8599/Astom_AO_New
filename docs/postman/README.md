# Running the Postman suite

**109 requests across 17 folders.** Every request carries a saved example with the real
captured response, so you can compare against what you get. The same information is
readable as prose in [examples.md](examples.md).

Import [`docs/postman/orchestration.postman_collection.json`](orchestration.postman_collection.json).
No environment file is needed — variables live in the collection.

## Folder order is a debugging sequence

Run it top to bottom once. Then use folders individually to isolate a failure.

| # | Folder | Requests | Answers |
|---|---|---|---|
00 | Setup & health | 6 | is anything broken before I start? |
01 | LiteLLM — keys & teams | 8 | which key exists, what may it reach |
02 | A2A agents via gateway | 8 | can the gateway reach agents |
03 | Ronaldo agent (direct) | 3 | is the agent itself healthy, bypassing the gateway |
04 | MCP servers on the gateway | 8 | is the server registered and reachable |
05 | MCP tools & search | 7 | are tools discoverable and callable |
06 | field_ops MCP server (direct) | 2 | is the MCP server itself healthy |
07 | LiteLLM MCP settings | 5 | semantic search configuration |
08 | Orchestrator — discovery | 3 | what does the orchestrator see |
09 | Orchestrator — routing | 8 | does a question route correctly |
10 | Orchestrator — OpenAI-compatible | 3 | the LibreChat-shaped surface |
11 | LibreChat | 4 | login and agent calls |
12 | Register a LibreChat agent as a model | 7 | the model-target route |
14 | Authorization boundary | 7 | which key reaches what |
15 | Azure AI Foundry agents | 15 | registering an externally hosted A2A agent |
16 | Memory & Postgres checkpointer | 10 | does state persist and recover |
13 | Langfuse traces | 5 | did the trace arrive, joined correctly |

**Folder 13 is physically last** despite its number: traces are only meaningful once
routing works, so it sits after everything that could make a trace wrong. Health first,
traces last.

## Fill these before running

Collection variables, **Variables** tab. The preflight request reports anything still
holding a placeholder.

| Variable | Where to get it | Required |
|---|---|---|
`litellm` | gateway base URL, e.g. `http://localhost:4001` | yes |
`orchestrator` | `http://localhost:8001` | yes |
`librechat` | `http://localhost:3081` | folder 11 |
`litellm_admin_key` | gateway master key | folders 01, 04, 12, 14, 15 |
`litellm_virtual_key` | the orchestrator's scoped key | folders 02, 05, 07 |
`orch_shared_key` | `ORCH_SHARED_KEY` | folders 08–10, 16 |
`litellm_team_id` | `/team/info` | folder 01 |
`librechat_password` | a test account | folder 11 |
`langfuse_public_key` / `langfuse_secret_key` | Langfuse project | folder 13 |
`expected_checkpoint_backend` | `memory` or `postgres` | folder 16 |

`litellm_admin_key` **cannot** substitute for `litellm_virtual_key` on the virtual-tool
routes: `mcp_tool_search`, `agent_search` and `skill_search` return **403** for the admin
key and **200** for a key with `mcp_tool_search_enabled`. That is a permission difference,
not a broken gateway — folder 05 documents it as EXPECTED.

## EXPECTED tests

Requests marked **EXPECTED** assert a *failure*. They document behaviour that looks like a
bug and is not:

| Request | Code | Why it is correct |
|---|---|---|
`Invoke agent — chat/completions a2a prefix` | 403 | the `a2a/` model prefix resolves against the model list, not the agent registry |
`Search agents — without embedding model` | 400 | `agent_search_not_configured` until the gateway config is set |
`mcp_tool_search` on the admin key | 403 | needs `mcp_tool_search_enabled` on the key |
`Capabilities with no auth` | 401 | discovery is not public; the orchestrator requires a caller |
`Virtual key CANNOT read /key/info` | 403 | route scoping working |

A red EXPECTED test means the behaviour changed — read the assertion before "fixing" it.

## What depends on what

Variables captured by one request and used by a later one:

| Captured | By | Used by |
|---|---|---|
`mcp_server_id` | 04 · List MCP servers | 04 · Server detail |
`probe_server_id` | 04 · Register throwaway server | 04 · Edit / Delete |
`agent_id_ronaldo` | 02 · List agents | 02 · Agent card |
`mcp_tool_name` | 05 · List tools | 05 · Call a tool |
`trace_id`, `session_id` | 09 · first orchestrate call | 13 · Langfuse |
`memory_conv_seed`, `memory_seed_asset` | 16 · seed turn | 16 · turn 2, 3 |
`memory_restart_asset` | 16 · seed restart conversation | 16 · after restart |

Run out of order and those arrive empty, which surfaces as a confusing 404 or a `null`
comparison rather than "you skipped a step".

## Two traps that cost real time

### 1. `{{var}}` is not interpolated inside scripts

Postman substitutes variables in URL, headers and body — **not** in pre-request or test
script source. So this silently never matches:

```javascript
const real = s.find(x => x.server_name === '{{mcp_server_name}}');   // WRONG
```

`'{{mcp_server_name}}'` is the literal string. Read it explicitly:

```javascript
const real = s.find(x => x.server_name === pm.collectionVariables.get('mcp_server_name'));
```

Verified with Newman: `LITERAL=[{{foo}}]` while `GET=[bar]` from the same script. Five
scripts in this collection had the bug; the symptom is a variable that keeps its default
placeholder, and an error like:

```
{"detail": {"error": "MCP Server with id <captured by List MCP servers> not found"}}
```

If a request fails with a value that contains angle brackets, this is why.

### 2. `POST /model/new` is not idempotent

Every call adds a *deployment* of the same `model_name`, and LiteLLM load-balances across
all of them. A duplicate with a bad `api_base` makes roughly half of all calls fail
intermittently, which reads as flakiness:

```
 1: 200  2: 500 Connection error  3: 200
```

Folder 12 is written to converge: it inspects first, deletes at most one duplicate, and
**skips** registration when a deployment exists. Repeat it while `Verify exactly one
deployment` fails.

## Safe to run against a shared gateway

- **Write tests use a throwaway server** (`postman_probe`), never `field_ops`. Deleting the
  configured server breaks every orchestrator MCP route until it is re-registered.
- **Folder 16 creates its own conversations**, named `pm-*`, with a fresh id per run. The
  folder description carries the SQL to delete them.
- **Folder 15 registers a real agent.** Delete it before re-running, or the second
  registration fails on the duplicate name.

## Folder 16 is a manual gate

Folder 16's last two requests need a **process restart between them** — that is the only
way to prove persistence. Without a restart the conversation is still in memory, so the
check passes for the wrong reason. The request description says so, and the test accepts
only two outcomes: state restored (gate exercised) or the same-process control.

If you want the strict version, stop and start the orchestrator between request 08 and 09.

## Running headless

```bash
npm install -g newman
newman run docs/postman/orchestration.postman_collection.json \
  --folder "16 · Memory & Postgres checkpointer" \
  --reporters cli
```

Newman honours the same capture chain, so single-folder runs work as long as the folder is
self-contained. Folders 04, 05 and 16 are; folders 09 and 13 are not (13 needs a captured
trace id from 09).

## Related

- [examples.md](examples.md) — every request with its real response
- [../architecture/authorization.md](../architecture/authorization.md) — what folder 14 proves
- [../architecture/memory.md](../architecture/memory.md) — what folder 16 proves, and the SQL to inspect it
