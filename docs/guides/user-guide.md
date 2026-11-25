# User guide — start the service, call it, and register targets

One page for a new user: bring the stack up, ask a question, and put agents, MCP servers
and models into the catalogue the orchestrator routes over.

Everything below is copy-pasteable on Windows PowerShell from the repository root.
Where the command differs on Linux/macOS it is called out.

```
LibreChat ──► orchestrator (:8001) ──► LiteLLM gateway (:4001) ──► A2A agents / MCP servers / models
```

The orchestrator holds **one scoped virtual key**. Registration and key management need
the gateway **admin key** — keep that in the CLI only, never in the service's `.env`
runtime settings.

| Thing | Default address | Who talks to it |
|---|---|---|
`orchestrator` | `http://localhost:8001` | LibreChat, Postman, CLI |
`LiteLLM gateway` | `http://localhost:4001` | orchestrator only (at runtime) |
`field-ops` MCP server | `http://localhost:9200/mcp` | gateway |
`ronaldo-agent` A2A agent | `http://localhost:9103` | gateway |
`LibreChat` | `http://localhost:3080` | a browser |

## 0. What you need

| Requirement | Notes |
|---|---|
Python 3.11+ | this repository was verified on 3.13 |
Docker Desktop | for the container path; optional for the host path |
A running LiteLLM gateway **with a database** | without a DB, `POST /v1/agents` answers `No connected db.` |
A gateway **admin key** (`LITELLM_ADMIN_KEY`) | registration, key/team grants, model admin. CLI only. |
A gateway **virtual key** (`LITELLM_API_KEY`) | what the orchestrator runs with; scoped to the agents/tools/models it may use |
A planning model | `PLANNER_MODEL`, e.g. `openai/gpt-4o-mini` — there is no heuristic fallback |

Set the two keys once per shell; every command below reuses them:

```powershell
$env:LITELLM_ADMIN_KEY = "sk-..."   # gateway master key — registration and key/team admin
$env:LITELLM_API_KEY   = "sk-..."   # the orchestrator's scoped virtual key
```

## 1. Start the service

### 1.1 Containers (recommended)

The compose file brings up the orchestrator, its own Postgres, and the two reference
backends. The gateway is deliberately **not** in it — it is an existing compose project
and owns the agent/MCP registry.

```powershell
$env:LITELLM_API_KEY = "sk-..."        # the orchestrator's scoped key
$env:ORCH_SHARED_KEY = "<32+ random characters>"   # what LibreChat/Postman send as apiKey

docker compose up -d --build
docker compose ps
```

Expected — four healthy containers:

```
db            Up (healthy)
field-ops     Up (healthy)
orchestrator  Up (healthy)
ronaldo-agent Up (healthy)
```

The orchestrator joins the gateway's Docker network, so the gateway is reached as
`http://litellm:4000` from inside the container. Verify the network exists:

```powershell
docker network ls | findstr litellm
```

If it is missing, either create it (`docker network create litellm-gateway_default`) or
point the orchestrator at the host with `GATEWAY_URL=http://host.docker.internal:4001`.
Details: [deployment.md](deployment.md).

### 1.2 Host (Python)

Useful for debugging and for running the onboarding CLI against the same code.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Copy-Item .env.example .env     # first time only, then edit
.\.venv\Scripts\python.exe -m orchestrator --port 8001
```

Minimum `.env` values:

```dotenv
LITELLM_BASE_URL=http://localhost:4001
LITELLM_API_KEY=sk-...        # scoped virtual key
PLANNER_MODEL=openai/gpt-4o-mini
AUTH_MODE=dev                 # or shared_key / entra / none
CHECKPOINT_BACKEND=memory     # or postgres, with the [postgres] extra
```

Notes:

- Use `python -m orchestrator`, **not** plain `uvicorn`, on Windows. It supplies
  `SelectorEventLoop`, which `psycopg` needs when `CHECKPOINT_BACKEND=postgres`.
  With the default `memory` backend, `uvicorn orchestrator.api.app:app --reload` works too.
- If the container is already on port 8001, run the host process on `--port 8002`.
- `--reload` is intentionally not supported by `python -m orchestrator`.
- Postgres memory is optional: `pip install -e ".[postgres]"`.

### 1.3 Check that it is up

```powershell
curl.exe -s http://localhost:8001/health
```

```json
{
  "status": "ok",
  "auth_mode": "dev",
  "gateway": "http://localhost:4001",
  "protocols": ["a2a", "mcp"],
  "read_only": true,
  "memory": "memory",
  "tracing": "langfuse",
  "models": { "status": "ok", "warnings": [] },
  "planner": "openai/gpt-4o-mini",
  "compose_answer": "deterministic"
}
```

| Endpoint | Meaning |
|---|---|
`/health` | liveness. Always `200` while the process runs. Shows configured gateway, memory backend, cached model check |
`/ready` | readiness. `503` when the planner model cannot be reached **or** Postgres is unreachable — the instance is alive but every turn would fail |

If `/health` reports `"models": {"status": "failed"}`, fix `PLANNER_MODEL` or the gateway
key before trying a question.

## 2. Authenticate

| `AUTH_MODE` | How to call |
|---|---|
`dev` | Bearer token minted locally (no identity provider needed) |
`shared_key` | `Authorization: Bearer <ORCH_SHARED_KEY>` **plus** `x-librechat-user-id: <id>` |
`entra` | a real Entra access token whose audience is the orchestrator app |
`none` | no header; localhost experiments only |

Mint a dev token:

```powershell
$token = .\.venv\Scripts\python.exe -c "from orchestrator.config import Settings; from orchestrator.auth import build_authenticator; print(build_authenticator(Settings.from_env()).issue())"
```

Shared key (container default):

```powershell
$headers = @{
  Authorization          = "Bearer $env:ORCH_SHARED_KEY"
  "x-librechat-user-id"  = "user-1"
  "Content-Type"         = "application/json"
}
```

Identity is per user; **authorization is not** — every caller uses the same virtual key,
so every registered target is reachable by every user. See
[authorization.md](../architecture/authorization.md).

## 3. Ask a question

### 3.1 One-shot from the terminal (no server needed)

```powershell
.\.venv\Scripts\python.exe -m orchestrator.admin.cli "who is ronaldo and what records does he hold?"
```

The CLI builds the same settings and service as the API, mints a dev token, runs the
preflight, prints JSON, and exits non-zero unless `status` is `completed`. Use
`--session-id` to group turns into one conversation.

### 3.2 HTTP — the native endpoint

```powershell
curl.exe -s http://localhost:8001/v1/orchestrate `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"message":"who is ronaldo?","conversation_id":"conv-1"}'
```

```powershell
# shared_key mode instead of a dev token
Invoke-RestMethod -Method Post -Uri http://localhost:8001/v1/orchestrate `
  -Headers $headers `
  -Body '{"message":"who is ronaldo?","conversation_id":"conv-1"}'
```

The response carries `answer`, `trace_id`, `tasks`, `results`, `notes` and `denied`.
`notes` is the honest audit trail: retrieval mode, coverage verdict, planner model, and
how many tasks ran. `conversation_id` is the memory thread — reuse it to follow up.

Read-only is policy, not a bug: a request to create, change or delete something returns
`denied: true` with an explanation. There is no approval path.

### 3.3 HTTP — the OpenAI-compatible surface

LibreChat-style clients call `/v1/chat/completions`; streaming is supported (one content
delta containing the complete answer).

```powershell
curl.exe -s http://localhost:8001/v1/chat/completions `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"model":"a2a-orchestrator","messages":[{"role":"user","content":"who is ronaldo?"}],"stream":false}'
```

Only the newest user message is used; earlier turns already live in the checkpointed
history. Send the conversation id in the body (`conversation_id`) or in the
`x-librechat-conversation-id` header.

### 3.4 Discovery endpoints

```powershell
curl.exe -s http://localhost:8001/v1/agents       -H "Authorization: Bearer $token"
curl.exe -s http://localhost:8001/v1/capabilities -H "Authorization: Bearer $token"
```

`/v1/agents` lists what the key can reach, with skills. `/v1/capabilities` reports what the
gateway has registered **right now**, per protocol (`a2a`, `mcp`, `model`), plus whether
semantic search is available or the surface is being listed instead.

## 4. Use the Postman collections

Two collections exist. Both are importable files; no environment file is required because
variables live in the collection.

| Collection | Purpose |
|---|---|
[`docs/postman/orchestration.postman_collection.json`](../postman/orchestration.postman_collection.json) | 109 requests across 17 folders: health, gateway keys, A2A, MCP, routing, memory, traces |
[`docs/postman/ronaldo-onboarding.postman_collection.json`](../postman/ronaldo-onboarding.postman_collection.json) | the agent onboarding path only, step by step |

### 4.1 Import and fill variables

Postman → **Import** → **File** → select the JSON. Open the collection → **Variables**.

| Variable | Value | Needed for |
|---|---|---|
`litellm` | `http://localhost:4001` | all gateway calls |
`orchestrator` | `http://localhost:8001` | folders 08–10, 16 |
`litellm_admin_key` | gateway master key | 01, 04, 12, 14, 15 |
`litellm_virtual_key` | the orchestrator's scoped key | 02, 05, 07 |
`orch_shared_key` | `ORCH_SHARED_KEY` | 08–10, 16 |
`litellm_team_id` | from `/team/info` | 01 |
`librechat` / `librechat_password` | `http://localhost:3081`, a test account | 11 |
`langfuse_public_key` / `langfuse_secret_key` | your Langfuse project | 13 |
`expected_checkpoint_backend` | `memory` or `postgres` | 16 |

Start with **00 · Preflight — unresolved variables**; it names anything still holding a
placeholder.

### 4.2 Run top to bottom once

Folder numbers are a debugging sequence:

1. health and keys
2. A2A and MCP through the gateway
3. the same backends directly
4. the orchestrator's view
5. registration and writes
6. memory/traces last

Run out of order and captured variables (`agent_id_ronaldo`, `mcp_server_id`,
`trace_id`, …) are empty, which surfaces as a confusing 404 rather than "you skipped a
step".

### 4.3 Expected failures are tests

Some requests assert a **failure** because that failure is correct behaviour:

| Request | Code | Why |
|---|---|---|
`chat/completions` with an `a2a/` model | 403 | the `a2a/` prefix resolves against the model list, not the agent registry |
`agent_search` without an embedding model | 400 | the search surface is not configured |
`mcp_tool_search` on the admin key | 403 | needs `mcp_tool_search_enabled` on the key |
`/v1/capabilities` with no auth | 401 | discovery is not public |
virtual key reading `/key/info` | 403 | route scoping working |

A red EXPECTED test means behaviour changed — read the assertion before "fixing" it.

### 4.4 Headless

```powershell
npm install -g newman
newman run docs/postman/orchestration.postman_collection.json `
  --folder "16 · Memory & Postgres checkpointer" `
  --reporters cli
```

Full details, traps and the capture chain: [postman/README.md](../postman/README.md).
Every request with its captured response: [postman/examples.md](../postman/examples.md).

## 5. Register an A2A agent

The whole path is: **fetch card → validate → register → verify → grant key → smoke →
call through the orchestrator**.

### 5.1 What makes a card registrable

The pre-check enforces exactly this:

| Check | Field |
|---|---|
has a name | `name` |
routable by a planner | `description` non-empty |
something to match on | `skills[]` non-empty, each with `id` or `name` |
the gateway can reach it | `url` equals the URL you register |

The sample card is [examples/ronaldo_agent/card.json](../../examples/ronaldo_agent/card.json).

### 5.2 Fetch the card

The onboarding CLI tries these paths in order:

```
/.well-known/agent-card.json
/.well-known/agent.json
/.well-known/agent-card/v1.0/agent-card.json
```

```powershell
curl.exe -s http://localhost:9103/.well-known/agent-card.json
```

### 5.3 Pre-check it

```powershell
.\.venv\Scripts\python.exe -m orchestrator.admin.onboarding check `
  --url http://localhost:9103 `
  --register-url http://host.docker.internal:9103
```

Two URLs matter when the gateway is containerised and the agent runs on the host:

- you fetch from `localhost` — the only name the host resolves
- you register `http://host.docker.internal:9103` — the only name the container resolves
- the card must report the **register** URL, because the gateway may follow the card's own `url`

### 5.4 Register it

Preferred (runs the pre-check first, pins the wire format):

```powershell
$env:LITELLM_ADMIN_KEY = "sk-..."     # or pass --admin-key

.\.venv\Scripts\python.exe -m orchestrator.admin.onboarding register `
  --name ronaldo-agent `
  --url http://localhost:9103 `
  --register-url http://host.docker.internal:9103 `
  --protocol-version 0.3
```

The response contains `agent_id`. Save it — every invoke URL needs it.

Raw HTTP equivalent: `POST {gateway}/v1/agents` with
`{"agent_name", "agent_card_params": {name, url, description, skills, protocolVersion,…},
"litellm_params": {...}}`. The exact body, and why each field exists, is in
[onboard-ronaldo-agent.md](onboard-ronaldo-agent.md#3-register-the-agent).

Points that matter:

- pin `protocolVersion` (the sample agent speaks `0.3`; the current A2A spec is `1.0`)
- `skills` is what the planner reasons over — a thin card is unroutable
- a duplicate name returns `409`; delete the old registration or pick a new name
- the gateway must be the **DB-backed** one, or you get `No connected db.`

### 5.5 Verify and smoke-test

```powershell
.\.venv\Scripts\python.exe -m orchestrator.admin.onboarding verify --name ronaldo-agent

.\.venv\Scripts\python.exe -m orchestrator.admin.onboarding smoke `
  --name ronaldo-agent --text "which clubs has he played for?"
```

`verify` lists the agents visible to a key. `smoke` sends one real message through the
gateway using the A2A-native JSON-RPC shape (`message/send`) — the only shape current
gateways accept.

### 5.6 Grant the orchestrator's key access

Create the scoped key (or update an existing one) so it may reach this agent:

```powershell
curl.exe -X POST http://localhost:4001/key/generate `
  -H "Authorization: Bearer $env:LITELLM_ADMIN_KEY" `
  -H "Content-Type: application/json" `
  -d '{"key_alias":"orchestrator-poc","agents":["<agent_id>"],"max_budget":20,"rpm_limit":60}'
```

Put the returned `sk-...` into `LITELLM_API_KEY` (and `.env`). Then confirm the **scoped**
key sees it:

```powershell
curl.exe -s http://localhost:4001/v1/agents -H "Authorization: Bearer $env:LITELLM_API_KEY"
```

Missing here but present with the admin key means the grant did not apply. Until
`general_settings.agent_access_default_deny: true` is set, a key with **no** `agents`
restriction can reach every agent.

### 5.7 Call it through the orchestrator

```powershell
curl.exe -s http://localhost:8001/v1/orchestrate `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"message":"who is ronaldo and what records does he hold?","conversation_id":"conv-1"}'
```

Expect `status: "completed"`, a `results[]` entry with `agent_name: "ronaldo-agent"` and
`ok: true`, and notes showing the coverage verdict and planner call.

If the card was just registered, the catalogue may still be cached for
`CARD_CACHE_TTL_S` (default 300 s). Send `"refresh_catalog": true` once, or restart.

Full walkthrough and failure map: [onboard-ronaldo-agent.md](onboard-ronaldo-agent.md).

## 6. Register an MCP server

MCP servers are registered by URL and expose tools; they do not have agent cards.

### 6.1 Run the sample server

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[mcp-server]"
$env:PYTHONPATH = "examples"
.\.venv\Scripts\python.exe -m mcp_field_ops.server --host 0.0.0.0 --port 9200
```

It serves streamable HTTP at `/mcp` and is stateless. Tools:
`get_asset_status`, `list_open_incidents`, `get_asset_maintenance_history`.

### 6.2 Prove the gateway can reach it before registering

```powershell
curl.exe -X POST http://localhost:4001/mcp-rest/test/connection `
  -H "Authorization: Bearer $env:LITELLM_ADMIN_KEY" `
  -H "Content-Type: application/json" `
  -d '{"url":"http://host.docker.internal:9200/mcp","transport":"http"}'
```

Use `host.docker.internal` when the gateway is containerised and the server is on the
host; use `127.0.0.1` when the gateway itself runs on the host.

### 6.3 Register

```powershell
curl.exe -X POST http://localhost:4001/v1/mcp/server `
  -H "Authorization: Bearer $env:LITELLM_ADMIN_KEY" `
  -H "Content-Type: application/json" `
  -d '{"server_name":"field_ops","alias":"field_ops","transport":"http","url":"http://host.docker.internal:9200/mcp","description":"Read-only field operations tools"}'
```

`GET /v1/mcp/server` lists what is registered, including the server id. `PUT` edits a
server and **requires `server_id` in the body**; `DELETE` by id removes it. The Postman
collection folder 04 exercises all of these against a throwaway server (`postman_probe`),
never the configured one.

### 6.4 Grant the team **and** the key

A key inherits its team's allowlist; granting only the key is rejected with
`Key requests MCP servers not allowed by team`.

```powershell
$h = @{ Authorization = "Bearer $env:LITELLM_ADMIN_KEY"; "Content-Type" = "application/json" }

Invoke-RestMethod -Method Post -Uri http://localhost:4001/team/update -Headers $h `
  -Body '{"team_id":"<team-id>","object_permission":{"mcp_servers":["field_ops"]}}'

Invoke-RestMethod -Method Post -Uri http://localhost:4001/key/update -Headers $h `
  -Body '{"key":"<virtual-key>","object_permission":{"mcp_servers":["field_ops"]}}'
```

### 6.5 Verify and call

```powershell
# Tools visible to the orchestrator's key
curl.exe -s http://localhost:4001/mcp-rest/tools/list -H "Authorization: Bearer $env:LITELLM_API_KEY"

# Call one directly
curl.exe -X POST http://localhost:4001/mcp-rest/tools/call `
  -H "Authorization: Bearer $env:LITELLM_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"server_id":"field_ops","name":"get_asset_status","arguments":{"asset_id":"PUMP-1042"}}'
```

With semantic tool search enabled, `tools/list` returns the four **virtual** tools
(`mcp_tool_search`, `mcp_tool_call`, `agent_search`, `skill_search`) instead of the real
ones — that is expected. The orchestrator uses `mcp_tool_search` + `mcp_tool_call`; direct
callers invoke the real tool as above.

No restart is needed after registration: the next discovery pass (or
`"refresh_catalog": true`) picks the tools up. `GET /v1/capabilities` shows what was found.

Details: [field-ops-mcp-server.md](field-ops-mcp-server.md) and
[examples/mcp_suite/README.md](../../examples/mcp_suite/README.md).

## 7. Register a model

A "model" here is a deployment on the gateway. There are two separate ideas:

| Idea | What it does | Where |
|---|---|---|
gateway **model** | an OpenAI-compatible upstream callable as `model: "<name>"` | `POST /model/new` |
orchestrator **model target** | makes that model a *routable target* alongside agents and tools | `MODEL_TARGETS` in `.env` |

Registering a model on the gateway does **not** make the orchestrator route to it. Do both
if you want the planner to choose it.

### 7.1 Register the deployment

Example — a LibreChat agent exposed as a model named `mai`:

```powershell
curl.exe -X POST http://localhost:4001/model/new `
  -H "Authorization: Bearer $env:LITELLM_ADMIN_KEY" `
  -H "Content-Type: application/json" `
  -d '{
    "model_name":"mai",
    "litellm_params":{
      "model":"openai/agent_<librechat_agent_id>",
      "api_base":"http://host.docker.internal:3081/api/agents/v1",
      "api_key":"<librechat-api-key>"
    },
    "model_info":{"description":"LibreChat agent MAI"}
  }'
```

- `api_base` must be reachable **from the gateway container**
- `POST /model/new` is **not** idempotent: every call adds a deployment and LiteLLM
  load-balances across all of them, so a duplicate with a bad `api_base` makes roughly
  half of calls fail
- inspect with `GET /model/info`; delete one deployment with `POST /model/delete` and
  `{"id":"<model_info.id>"}` — deleting by name is not supported

### 7.2 Allow the model on the key **and** the team

```powershell
$h = @{ Authorization = "Bearer $env:LITELLM_ADMIN_KEY"; "Content-Type" = "application/json" }

Invoke-RestMethod -Method Post -Uri http://localhost:4001/key/update -Headers $h `
  -Body '{"key":"<virtual-key>","models":["openai/*","mai"]}'

Invoke-RestMethod -Method Post -Uri http://localhost:4001/team/update -Headers $h `
  -Body '{"team_id":"<team-id>","models":["openai/*","mai"]}'
```

`key_model_access_denied` means the key list is missing it; `team_model_access_denied`
means the team list is.

### 7.3 Verify through the gateway

```powershell
curl.exe -s http://localhost:4001/v1/chat/completions `
  -H "Authorization: Bearer $env:LITELLM_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"mai","messages":[{"role":"user","content":"What is our company name?"}]}'
```

### 7.4 Make it routable by the orchestrator

Add it to `.env` as `model|description`, entries separated by **semicolons**:

```dotenv
MODEL_TARGETS=mai|LibreChat agent MAI: answers questions about Alstom corporate facts.;openai/gpt-4o-mini|General fallback model
```

- the pipe separates model from description; descriptions may contain commas and colons
- empty `MODEL_TARGETS` = only agents and tools are routable
- nothing is inferred from `/v1/models` (it lists hundreds of models)
- restart the orchestrator, then check `GET /v1/capabilities` — models appear under the
  `model` protocol
- a model that declines in words is marked failed, so merge reports the refusal instead of
  passing it off as an answer (`REFUSAL_MARKERS` extends the built-in list)

### 7.5 Reasoning models and `temperature`

OpenAI's reasoning models — `gpt-5.6-luna`, `gpt-6-luna`, the `o`-series — reject any
temperature but the one they name, usually `1.0`:

```
HTTP 400 litellm.UnsupportedParamsError: gpt-5.6-luna doesn't support temperature=0.0
while reasoning is active. Only temperature=1 is supported ...
```

The gateway client recognises that specific error, retries once at the required value and
remembers it for the model, so any model works as planner, gate or rewrite with no config.
The first call to such a model costs one extra round trip; every later call is correct on
the first attempt. `MODEL_PREFLIGHT_ENABLED` reports `models.status: ok` once the same
retry succeeds.

To skip the extra round trip, set the temperatures explicitly:

```dotenv
PLANNER_MODEL=openai/gpt-5.6-luna
PLANNER_TEMPERATURE=1
GATE_TEMPERATURE=1
QUERY_REWRITE_TEMPERATURE=1
```

Two related traps:

- **A small `max_tokens` returns empty content**, not an error: reasoning tokens are
  charged first, so `max_tokens: 16` can produce `finish_reason: length` with
  `content: ""`. Leave the cap unset.
- **`drop_params: true`** on the request (or in the gateway's `litellm_settings`) also
  works — LiteLLM strips the unsupported parameter instead of retrying — but it hides the
  same mistake for every other model, which is why the orchestrator retries narrowly
  instead.

## 8. Fetch agent cards

Four ways, depending on what you want to know.

| Want | Request | Auth |
|---|---|---|
the agent's own card | `GET {agent}/.well-known/agent-card.json` | usually none |
legacy path | `GET {agent}/.well-known/agent.json` | usually none |
the card **as the gateway serves it** | `GET {gateway}/a2a/{agent_id}/.well-known/agent-card.json` | virtual key |
what is registered | `GET {gateway}/v1/agents` | admin (all) or virtual key (allowed only) |
what the orchestrator can route to | `GET {orchestrator}/v1/agents` | caller token |

```powershell
# direct
curl.exe -s http://localhost:9103/.well-known/agent-card.json

# through the gateway (readable name first)
$id = (curl.exe -s http://localhost:4001/v1/agents -H "Authorization: Bearer $env:LITELLM_ADMIN_KEY" |
       ConvertFrom-Json | Where-Object agent_name -eq 'ronaldo-agent').agent_id
curl.exe -s "http://localhost:4001/a2a/$id/.well-known/agent-card.json" `
  -H "Authorization: Bearer $env:LITELLM_API_KEY"

# what the orchestrator sees
curl.exe -s http://localhost:8001/v1/agents -H "Authorization: Bearer $token"
```

The gateway-served card is curated: its `url` is rewritten to the gateway hop, and
`protocolVersion` decides the wire shape of responses. Use the direct card to debug the
agent, and the gateway card to debug what the orchestrator will actually route over.

Card fetch failures are almost always a name-resolution problem: the host resolves
`localhost`, the container resolves `host.docker.internal` or a service name.

## 9. When changes take effect

| Change | Takes effect |
|---|---|
register/delete agent or MCP server | next discovery pass; force it once with `"refresh_catalog": true` |
new agent card content | after `CARD_CACHE_TTL_S` (default 300 s) or a restart |
grant/revoke on key or team | immediately for the next gateway call |
`MODEL_TARGETS`, `PLANNER_MODEL`, policy | orchestrator restart |
`ORCH_SHARED_KEY` | orchestrator restart (and LibreChat/Postman clients) |

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
`No connected db.` | gateway has no database | use the DB-backed gateway |
`409` on agent register | name already registered | delete the old agent or choose a new name |
`Access denied to agent` / agent missing from `/v1/agents` | key not granted it | `/key/generate` or `/key/update` |
`jsonrpc must be '2.0'` | legacy A2A shape | use `message/send` (the orchestrator always does) |
`key_model_access_denied` | `a2a/` model used via chat, or model not on the key | use the JSON-RPC A2A path; add the model to the key |
`Key requests MCP servers not allowed by team` | team not granted first | `/team/update`, then `/key/update` |
MCP tools missing | server not registered, or URL unreachable from the container | `/mcp-rest/test/connection` first |
`/health` models `failed` | `PLANNER_MODEL` not served by the gateway | fix the model name or key |
`/ready` 503 | planner model failed or Postgres unreachable | `/ready` body names the cause |
every turn returns "nothing covers that" | card too thin, retrieval found nothing, or catalogue cache | check `/v1/capabilities`, fix `description`/`skills`, `refresh_catalog` |
`401 missing bearer token` | no `Authorization` header | add `Bearer …` |
shared-key request `401` | missing `x-librechat-user-id` | add the header |
plain `uvicorn` + Postgres on Windows | Proactor loop vs psycopg | use `python -m orchestrator` |

## 11. Where to go next

- [deployment.md](deployment.md) — container topology, gateway network, backups
- [onboard-ronaldo-agent.md](onboard-ronaldo-agent.md) — every onboarding request in full
- [field-ops-mcp-server.md](field-ops-mcp-server.md) — the MCP sample end to end
- [librechat-agent-as-model.md](librechat-agent-as-model.md) — models and model targets in depth
- [api-key-scoping.md](api-key-scoping.md) — key and team permission resolution
- [sso-integration.md](sso-integration.md) — LibreChat identity, shared key vs token forwarding
- [../postman/README.md](../postman/README.md) — the Postman suite
- [../architecture/routing.md](../architecture/routing.md) — how a target is actually chosen
