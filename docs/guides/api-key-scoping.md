# Key scoping — which key reaches what

<!-- markdownlint-disable MD033 -->

Reference for the authorization boundary around the orchestrator's LiteLLM virtual key.
Written after measuring a live gateway, because two behaviours here are counter-intuitive
and one is genuinely ambiguous.

Everything below was observed, not inferred. Re-check with
[folder 14 of the Postman collection](../postman/orchestration.postman_collection.json) after
changing a key.

## The error this documents

```
{
  "detail": "Virtual key is not allowed to call this route.
             Only allowed to call routes: ['llm_api_routes'].
             Tried to call route: /key/info"
}
```

This is **the boundary working**, not a broken deployment. The virtual key is scoped to
LLM traffic; key and team management need the admin key.

## Route classes

LiteLLM keys carry `allowed_routes`. The orchestrator's key has
`["llm_api_routes"]`, which covers models, chat, agents and the MCP REST surface.

| Route | Virtual key | Admin key |
|---|---|---|
| `/v1/chat/completions`, `/v1/embeddings` | ✅ 200 | ✅ 200 |
| `/v1/agents`, `/v1/agents?query=` | ✅ 200 | ✅ 200 |
| `/v1/models` | ✅ 200 | ✅ 200 |
| `/mcp-rest/tools/list`, `/mcp-rest/tools/call` | ✅ 200 | ✅ 200 |
| `/v1/mcp/server` (list) | ✅ 200 | ✅ 200 |
| `/a2a/{agent_id}` (invoke) | ✅ 200 | ✅ 200 |
| `/key/info`, `/key/update`, `/key/generate`, `/key/delete` | ❌ **403** | ✅ 200 |
| `/team/info`, `/team/update` | ❌ **403** | ✅ 200 |
| `/model/new`, `/model/delete`, `/model/info` | ❌ **403** | ✅ 200 |
| `/get/*`, `/update/*` (settings) | ❌ **403** | ✅ 200 |

The orchestrator only calls rows marked ✅, so it is unaffected by the 403s. That is the
point of the scoping: the key can route traffic but cannot rewrite its own permissions.

**Rule of thumb:** if the path starts with `/key`, `/team`, `/model`, `/get` or `/update`,
use `LITELLM_ADMIN_KEY`. Everything else uses `LITELLM_API_KEY`.

## The key's full permission surface

Measured via `GET /key/info` with the **admin** key:

```
key_alias:      "Alstom_Test"
allowed_routes: ["llm_api_routes"]
models:         ["openai/*", "mai"]
team_id:        "f3c4411d-724b-4c64-975e-f1e1dadcb29e"

object_permission:
  mcp_servers:              ["field_ops"]
  mcp_access_groups:        []
  mcp_tool_search_enabled:  true
  agents:                   []
  agent_access_groups:      []
```

### Effective access is key ∩ team

Both levels must allow a thing. The team `Alstom` carries `models: ["openai/*", "mai"]`
and `object_permission.mcp_servers: ["field_ops"]`, so:

| Resource | Key says | Team says | Effective |
|---|---|---|---|
| Models | `openai/*`, `mai` | same | `openai/*`, `mai` |
| MCP servers | `field_ops` | `field_ops` | `field_ops` |
| MCP tool search | enabled | — | enabled |
| Agents | `[]` | `[]` | see below |

A model or server missing from **either** level is denied. This is why granting on the key
alone fails with `Key requests MCP servers not allowed by team` — the team must grant
first.

## Two counter-intuitive behaviours

### 1. `/key/update` merges `object_permission`, it does not replace it

Verified on a throwaway key:

```
initial:                  mcp_servers=["field_ops"], tool_search=true, agents=[]
after agents-only update: mcp_servers=["field_ops"], tool_search=true, agents=["<id>"]
                          -> merged, not replaced
```

So `POST /key/update` with only `{"object_permission": {"agents": [...]}}` is safe — it
does not wipe the MCP grants. **But** this only holds for `object_permission`
sub-fields; passing `models` replaces the model list wholesale.

### 2. Empty `agents: []` is ambiguous — do not rely on it

This is the one thing to be careful about. Measured on four freshly generated keys:

| Key configuration | Agents visible |
|---|---|
| team only, no `object_permission` | **0** |
| team + `object_permission.agents: ["<ronaldo-id>"]` | 1 |
| team + `object_permission.agents: []` | **0** |
| no team, no `object_permission` | **0** |

But the orchestrator's key, which also shows `agents: []`, **sees `ronaldo-agent`**.

So an empty list behaved as *denied* on new keys and as *unrestricted* on this one. The
difference is not documented and I could not reproduce it deliberately — most likely the
key predates a change in how the field is interpreted, or the value was never actually
persisted as `[]`.

**Consequence:** do not treat `agents: []` as "no restriction". If agent access matters,
grant explicitly:

```bash
curl -X POST "$LITELLM/v1/agents" ...          # note the agent_id
curl -X POST "$LITELLM/key/update" \
  -H "Authorization: Bearer $LITELLM_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key":"'$LITELLM_VIRTUAL_KEY'",
       "object_permission":{"agents":["<agent_id>"]}}'
```

Then re-run folder 14 to confirm the expected count.

## Why the orchestrator is unaffected

Every call the orchestrator makes is on an allowed route:

```
retrieve    GET  /v1/agents?query=          allowed
retrieve    GET  /v1/mcp/server             allowed
retrieve    GET  /mcp-rest/tools/list       allowed
retrieval   POST /mcp-rest/tools/call       allowed
plan        POST /v1/chat/completions       allowed
run_task    POST /a2a/{agent_id}            allowed
run_task    POST /mcp-rest/tools/call       allowed
```

It never calls `/key/*`, `/team/*` or `/model/*`. Those are operator actions performed
once during setup, with the admin key, outside the request path.

## Non-idempotent writes to watch for

Two LiteLLM endpoints **add** a row on every call rather than upserting. Repeating either
silently degrades behaviour.

### `POST /model/new`

Each call adds a **deployment** of the same `model_name`. LiteLLM load-balances across all
deployments, so two entries for `mai` means roughly half your calls go to each.

This bit us for real: a registration with `api_base: http://host.docker.internal:{{librechat_port}}/...`
was sent with the placeholder **unsubstituted** — LiteLLM accepted it — so one deployment
pointed at a hostname that does not resolve. `mai` then failed intermittently (about half
of requests), which reads as flakiness rather than misconfiguration:

```
  1: 200 The company name is Alstom.
  2: 500 Connection error        ← routed to the broken deployment
  3: 200 The company name is Alstom.
```

**Rules:**

- Register once. Check `/model/info` before re-registering; duplicates must be deleted
  individually (`POST /model/delete` takes one `id`).
- Never send a `{{placeholder}}` in a body — LiteLLM validates nothing about `api_base`
  and will store a URL that cannot resolve.
- After registering, read the deployment's `api_base` back and confirm it contains no
  `{{` and does name `host.docker.internal` (not `localhost`) when the proxy is
  containerised.

### Deleting a model

`POST /model/delete` with `{"id": "<model_info.id>"}` removes exactly one deployment.
There is no bulk delete and no delete-by-name.

| Result | Meaning |
|---|---|
| `200` `{"message":"Model: <id> deleted successfully"}` | removed |
| `400` `Model with id=<id> not found in db` | already gone, or wrong id |
| `422` `Field required` / `Input should be a valid string` | body missing `id`, or `id` is not a string |

Take the id from `/model/info` → `data[].model_info.id`, **not** the `model_name`.
Deleting the last deployment of a name makes that model unavailable until re-registered;
if a `MODEL_TARGETS` entry points at it, the planner loses that target on the next turn.

Folder **12** in the collection is now safe to run repeatedly: it inspects first, deletes
at most one duplicate, and **skips** registration when a deployment already exists. Repeat
the folder while `Verify exactly one deployment` fails, and it converges without ever
adding a second entry.

### `POST /v1/mcp/server`

Each call with a new `server_name` adds a server; a duplicate alias is rejected with
`400 An MCP server with alias X already exists`. That one is safe to repeat — it fails
loudly rather than stacking.

But deleting a server **does not** remove the key's grant. Re-registering gets a **new
`server_id`**, and anything holding the old id breaks. Grants are by name, so tool access
survives.

## Operational rules

1. **Never give the orchestrator the admin key.** `LITELLM_ADMIN_KEY` exists only for
   onboarding tooling; `config.py` keeps them as separate settings.
2. **Grant at team level first**, then key level. Key-only grants are rejected.
3. **Use the admin key for inspection.** `/key/info` is the only way to see
   `allowed_routes`, effective models and `object_permission`.
4. **Do not tighten `agents` until the agent list is stable.** An explicit list means new
   agents are invisible until granted — which silently hides them from the planner.
5. **A 403 is a boundary, not an outage.** Check the message: `not allowed to call this
   route` means the wrong key; `access_denied` on a model means the allowlist; `No remote
   access to agent` is a LibreChat ACL, not LiteLLM.

## Verifying all of it

Folder **14 · Authorization boundary** in
[orchestration.postman_collection.json](../postman/orchestration.postman_collection.json) has seven
requests proving each case, for both keys, with captured real responses:

```
Virtual key CAN list agents              200
Virtual key CAN list models              200
Virtual key CAN list MCP tools           200
Virtual key CANNOT read /key/info        403  (EXPECTED)
Virtual key CANNOT read /team/info       403  (EXPECTED)
Admin key CAN read /key/info             200
Admin key CAN read /team/info            200
```

The `/key/info` example also asserts `allowed_routes == ["llm_api_routes"]` and logs the
effective `models`, `mcp_servers` and `agents` — it doubles as a permission inspector.
