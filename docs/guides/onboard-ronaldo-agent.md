# Onboarding the Ronaldo agent — Postman / raw HTTP

Every step as an HTTP request you can paste into Postman, Insomnia, or `curl`.
Ready-made collection: [ronaldo-onboarding.postman_collection.json](../postman/ronaldo-onboarding.postman_collection.json)
(Postman → Import → File → select it).

## 0. What you are onboarding

| Piece | Value |
|---|---|
| Package | `examples/ronaldo_agent/` |
| Card | `examples/ronaldo_agent/card.json` |
| Port | `9103` |
| Card path | `/.well-known/agent-card.json` (and the legacy `/.well-known/agent.json`) |
| Protocol version | `0.3` |
| Skills | `biography`, `career`, `records` |

## Variables to set once

| Variable | Value |
|---|---|
| `agent_base` | `http://localhost:9103` |
| `gateway` | `http://localhost:4001` |
| `orchestrator_base` | `http://localhost:8000` |
| `admin_key` | your LiteLLM **master/admin** key |
| `orchestrator_key` | filled in after step 4 |
| `agent_id` | filled in after step 3 |
| `register_url` | `http://host.docker.internal:9103` |

`gateway` matters: a proxy **without a database** cannot store agents —
`POST /v1/agents` returns `No connected db.` Use the DB-backed one.

## 1. Start the agent

```powershell
# Gateway on the host:
python -m uvicorn ronaldo_agent.server:app --host 0.0.0.0 --port 9103

# Gateway in Docker -> advertise the container-reachable URL:
$env:RONALDO_AGENT_URL = "http://host.docker.internal:9103"
python -m uvicorn ronaldo_agent.server:app --host 0.0.0.0 --port 9103
```

### `GET {{agent_base}}/health`

No auth. Expect `200`:

```json
{ "status": "ok", "knowledge_cutoff": "mid-2025" }
```

## 2. Fetch and validate the card

### `GET {{agent_base}}/.well-known/agent-card.json`

No auth. Expect `200` with the card.

A card is **registrable** when it satisfies all of these — this is exactly what the
pre-check enforces:

| Check | Field |
|---|---|
| has a name | `name` |
| routable by a planner | `description` non-empty |
| has something to match on | `skills[]` non-empty, each with `id` or `name` |
| the gateway can reach it | `url` == the URL you will register |

The agent itself serves this same JSON at `/.well-known/agent.json` for legacy clients.

**Why two URLs.** The gateway runs in a container, the agent on the host:

- you fetch the card from `localhost` — that is the only name the host resolves
- you register `http://host.docker.internal:9103` — the only name the container resolves

The card must report the **register** URL, because LiteLLM may follow the card's
self-reported `url` instead of the one you registered. That mismatch is the classic
"works locally, 500s in the gateway" bug.

## 3. Register the agent

### `POST {{gateway}}/v1/agents`

```http
POST {{gateway}}/v1/agents
Authorization: Bearer {{admin_key}}
Content-Type: application/json
Accept: application/json
```

```json
{
  "agent_name": "ronaldo-agent",
  "agent_card_params": {
    "name": "ronaldo-agent",
    "description": "Answers questions about Cristiano Ronaldo: who he is, his biography, career history, records and achievements.",
    "url": "{{register_url}}",
    "version": "1.0.0",
    "protocolVersion": "0.3",
    "capabilities": {
      "streaming": false,
      "pushNotifications": false,
      "stateTransitionHistory": false
    },
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "provider": {
      "organization": "A2A Orchestration POC",
      "url": "{{register_url}}"
    },
    "skills": [
      {
        "id": "biography",
        "name": "Biography",
        "description": "Who Cristiano Ronaldo is: full name, birth, birthplace, early life and family background.",
        "tags": ["biography", "ronaldo", "early-life", "family"]
      },
      {
        "id": "career",
        "name": "Career history",
        "description": "Club career from Sporting CP through Manchester United, Real Madrid, Juventus and Al Nassr, plus the Portugal national team.",
        "tags": ["career", "clubs", "transfers", "portugal"]
      },
      {
        "id": "records",
        "name": "Records and awards",
        "description": "Goalscoring records, Ballon d'Or wins, Champions League and international records.",
        "tags": ["records", "awards", "goals", "ballon-dor"]
      }
    ]
  },
  "litellm_params": {
    "require_trace_id_on_calls_by_agent": true,
    "max_iterations": 25,
    "max_budget_per_session": 5.0
  }
}
```

Why each part:

- `protocolVersion` pinned to `0.3` — callers without a version header otherwise get the
  older wire format, which changes the response shape the orchestrator parses.
- `require_trace_id_on_calls_by_agent` — enables per-session iteration and budget
  accounting keyed by `x-litellm-trace-id`.
- `max_iterations` / `max_budget_per_session` — caps a runaway agentic loop. `429` on breach.
- `skills` — what your planner reasons over to decide which agent to call.

Response contains `agent_id`. Save it as `{{agent_id}}`; every invoke URL needs it.

### `GET {{gateway}}/v1/agents`  (confirm it landed)

```http
GET {{gateway}}/v1/agents
Authorization: Bearer {{admin_key}}
Accept: application/json
```

Find your `agent_name` in the array and copy its `agent_id`.

## 4. Grant the orchestrator access

### `POST {{gateway}}/key/generate`

```http
POST {{gateway}}/key/generate
Authorization: Bearer {{admin_key}}
Content-Type: application/json
Accept: application/json
```

```json
{
  "key_alias": "orchestrator-poc",
  "agents": ["{{agent_id}}"],
  "max_budget": 20.0,
  "rpm_limit": 60
}
```

Response: `{ "key": "sk-..." }`. Put that value into `{{orchestrator_key}}` and into
`.env` as `LITELLM_API_KEY`. The orchestrator runtime only ever holds this key — never the
admin key.

> Until `general_settings.agent_access_default_deny: true` is set, a key with **no**
> `agents` restriction can reach **every** agent. Set it before this leaves your laptop.

## 5. Verify permissions (the real test)

### `GET {{gateway}}/v1/agents`  with the **scoped** key

```http
GET {{gateway}}/v1/agents
Authorization: Bearer {{orchestrator_key}}
Accept: application/json
```

This endpoint only returns agents the key may reach. If your agent is missing here but
present with the admin key, the grant in step 4 did not apply.

## 6. Smoke-test through the gateway

**Use 6b.** On this gateway the simple shape returns `400 Invalid Request: jsonrpc must be
'2.0'`, and the chat shape cannot work at all (6c). The A2A-native JSON-RPC call is the one
that returns `200`.

### 6a. Simple shape — `POST {{gateway}}/a2a/{{agent_id}}`

Rejected by this proxy version with `{"code":-32600,"message":"Invalid Request: jsonrpc must be '2.0'"}`.
Kept here so you recognise the error if you try it.

```http
POST {{gateway}}/a2a/{{agent_id}}
Authorization: Bearer {{orchestrator_key}}
Content-Type: application/json
Accept: application/json
x-litellm-trace-id: {{trace_id}}
```

```json
{
  "message": {
    "role": "user",
    "parts": [
      { "type": "text", "text": "who is ronaldo and what is his biography" }
    ]
  }
}
```

### 6b. Native A2A — JSON-RPC `message/send`

```http
POST {{gateway}}/a2a/{{agent_id}}
Authorization: Bearer {{orchestrator_key}}
Content-Type: application/json
Accept: application/json
x-litellm-trace-id: {{trace_id}}
```

```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "msg-1",
      "role": "user",
      "parts": [
        { "kind": "text", "text": "which clubs has he played for" }
      ]
    }
  }
}
```

### 6c. OpenAI-style — `POST {{gateway}}/v1/chat/completions`

**Does not work on a gateway with wildcard model patterns.** Documented here because the
error is confusing and it's the first thing most people try.

```http
POST {{gateway}}/v1/chat/completions
Authorization: Bearer {{orchestrator_key}}
Content-Type: application/json
Accept: application/json
x-litellm-trace-id: {{trace_id}}
```

```json
{
  "model": "a2a/ronaldo-agent",
  "messages": [
    { "role": "user", "content": "what records does he hold" }
  ]
}
```

Two failures stack up, in this order:

| Symptom | Cause |
|---|---|
| `403 key_model_access_denied` — *"The requested model 'a2a/ronaldo-agent' is not available for this API key"* | the key's `models` allowlist is `["openai/*"]`, which cannot match `a2a/…` |
| `400 no healthy deployments for this model` | even with a wildcard key, the proxy routes to the LLM router first |

The second one is a routing-order issue in `route_llm_request.py`:

```python
elif (llm_router.settings().default_deployment is not None
      or len(llm_router.registry().patterns().patterns) > 0):
    return getattr(llm_router, f"{route_type}")(**data)      # <-- taken first
...
elif _is_a2a_agent_model(data.get("model", "")):
    route_a2a_agent_request(...)                             # <-- never reached
```

If the model table contains any wildcard (`openai/*` here), `patterns` is non-empty, so
`a2a/…` goes to the router and the A2A bridge below is unreachable. Confirm with:

```sql
SELECT model_name FROM "LiteLLM_ProxyModelTable" WHERE model_name LIKE '%*%';
```

**Use 6a/6b instead.** Set `INVOCATION_STRATEGY=jsonrpc`, never `chat`.

The `x-litellm-trace-id` you send is the handle for the hop: look it up in your gateway
logs or Langfuse to prove the call was traced rather than assumed.

Expected answer text (any shape):

```
Who he is

Cristiano Ronaldo dos Santos Aveiro is a Portuguese professional footballer, widely
regarded as one of the greatest players of all time.
```

## 7. Call it through the orchestrator

Start it first:

```powershell
python -m uvicorn orchestrator.api.app:app --port 8000
```

### `GET {{orchestrator_base}}/health`

No auth. Shows `auth_mode`, the gateway it targets, and whether planner/merge are model-backed.

### `GET {{orchestrator_base}}/v1/agents`

```http
GET {{orchestrator_base}}/v1/agents
Authorization: Bearer {{user_token}}
Accept: application/json
```

### `POST {{orchestrator_base}}/v1/orchestrate`

```http
POST {{orchestrator_base}}/v1/orchestrate
Authorization: Bearer {{user_token}}
Content-Type: application/json
Accept: application/json
traceparent: 00-{{trace_id}}-{{span_id}}-01
```

```json
{
  "message": "who is ronaldo and what is his biography",
  "conversation_id": "conv-1",
  "refresh_catalog": true
}
```

Response:

```json
{
  "run_id": "…",
  "status": "completed",
  "answer": "Cristiano Ronaldo — biography\n\nWho he is\n…",
  "error": "",
  "trace_id": "…",
  "tasks": [{ "task_id": "…", "agent_id": "…", "agent_name": "ronaldo-agent", "instruction": "…" }],
  "results": [{ "agent_name": "ronaldo-agent", "ok": true, "text": "…", "latency_ms": 12 }],
  "notes": ["input: accepted 43 chars", "retrieve: 1 candidate(s)", "plan: 1 task(s) via heuristic"]
}
```

`trace_id` here is the same value carried on every downstream hop — in `traceparent` and
`x-litellm-trace-id` — so one user request maps to one trace tree.

**`user_token`:** with `AUTH_MODE=dev` mint one locally:

```powershell
python -c "from orchestrator.config import Settings; from orchestrator.auth import build_authenticator; a=build_authenticator(Settings.from_env()); print(a.issue())"
```

With `AUTH_MODE=entra` use the Entra access token whose audience is your orchestrator's
`api://` app ID.

## Failure map

| Symptom | HTTP | Cause | Fix |
|---|---|---|---|
| `No connected db.` | 400 | gateway has no database | use the DB-backed proxy |
| `Access denied to agent` | 403 | key not granted that agent | step 4 |
| `agent returned no text` | 200 but empty | response shape unparsed | use 6b (`message/send`) |
| `jsonrpc must be '2.0'` | 400 | proxy requires the A2A-native envelope | use the JSON-RPC body in 6b |
| `key_model_access_denied` | 403 | key scoped to `openai/*`, model is `a2a/…` | don't use the chat shape; use 6b |
| `no healthy deployments for a2a/…` | 400 | wildcard model pattern routes to the LLM router | use 6b |
| card fetch fails | 404 | `agent_base` not host-resolvable | use `localhost` for the fetch |
| card url mismatch | — | card reports `localhost`, you registered `host.docker.internal` | set `RONALDO_AGENT_URL`, restart |
| pre-check `no 'skills'` | — | card too thin to route | add skills to `card.json` |
| `401 missing bearer token` | 401 | no `Authorization` header | add `Bearer {{user_token}}` |
| wrong model name | 400 | chat shape needs the **name**, not the id | `model: "a2a/ronaldo-agent"` |
