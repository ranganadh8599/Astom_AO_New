# LiteLLM gateway configuration — what it takes to run A2A and MCP

Everything the gateway needs, and every change required to add an agent, an MCP server or a
model. Written against the stack measured in this repository:

| Piece | Value |
|---|---|
LiteLLM | `1.110.1`, image `docker.litellm.ai/berriai/litellm:latest` |
Database | Postgres, `STORE_MODEL_IN_DB=True` |
Config | `config.yaml` mounted read-only at `/app/config.yaml` |
Embeddings | `openai/text-embedding-3-small` |

The orchestrator never configures the gateway. It holds one scoped virtual key and treats
the registry as the source of truth: whatever is registered **is** the catalogue.

---

## 1. Prerequisites — without these, nothing registers

| Requirement | Why it is load-bearing | Failure if missing |
|---|---|---|
**A database** | agents, MCP servers, keys, teams, models are rows, not YAML | `POST /v1/agents` → `400 No connected db.` |
**`STORE_MODEL_IN_DB=True`** | models live in the DB; no `model_list` in YAML | models absent from `/v1/models` |
**`LITELLM_MASTER_KEY`** | authorises `/v1/agents`, `/v1/mcp/server`, `/key/*`, `/team/*`, `/model/*` | every admin call 401s |
**`LITELLM_SALT_KEY`** | encrypts stored credentials | rotating it makes existing rows unreadable |
**`config.yaml` mounted** | the one setting with no API equivalent | agent search stays `not_configured` |
**An embedding model in the model list** | agent search and tool search both embed | search returns 400 |
**A route from gateway → backend** | the gateway dials the URL, not you | agent 500s, MCP `unhealthy` |

Minimal compose, as deployed here:

```yaml
services:
  litellm:
    image: docker.litellm.ai/berriai/litellm:1.110.1   # pin, see §7
    ports: ["${LITELLM_BIND:-}${LITELLM_PORT:-4000}:4000"]
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    volumes:
      - ./config.yaml:/app/config.yaml:ro
    environment:
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY:?set it}
      LITELLM_SALT_KEY: ${LITELLM_SALT_KEY:?set it}
      DATABASE_URL: postgresql://litellm:${POSTGRES_PASSWORD:-litellm}@db:5432/litellm
      STORE_MODEL_IN_DB: "True"
    depends_on:
      db: { condition: service_healthy }
```

---

## 2. `config.yaml` — the only file you must edit

```yaml
litellm_settings:
  # Model used to rank A2A agents against the caller's query.
  # GET /v1/agents?query=<task>&top_k=N does nothing without this.
  agent_search_embedding_model: openai/text-embedding-3-small

general_settings:
  # A key with no `agents` restriction can otherwise reach EVERY agent.
  agent_access_default_deny: true
```

| Rule | Reason |
|---|---|
**Restart required** | `litellm_settings.*` is read at boot; there is no PATCH for `agent_search_embedding_model` |
**No `model_list` while `STORE_MODEL_IN_DB=True`** | two sources of truth for the same thing |
Manage MCP search in the DB, not here | see §3 — the API avoids a restart |
Keep `LITELLM_SALT_KEY` stable | it is not in this file but is equally load-bearing |

`agent_access_default_deny: true` changes the meaning of an empty `agents` list from
*ambiguous* (measured: "denied" on new keys, "unrestricted" on an older key) to **denied**.
Do not enable it before every key that must reach agents has an explicit grant — see §5.

---

## 3. DB-backed settings — change via API, no restart

| Endpoint | Fields | Notes |
|---|---|---|
`GET`/`PATCH /get|/update/mcp_tool_search_settings` | `embedding_model`, `top_k`, `similarity_threshold`, `core_tools` | semantic `mcp_tool_search` |
`GET`/`PATCH /get|/update/mcp_semantic_filter_settings` | `enabled`, `embedding_model`, `top_k`, `similarity_threshold` | which tools are advertised |

Measured values that work, and traps worth remembering:

```json
{"embedding_model":"openai/text-embedding-3-small","top_k":10,"similarity_threshold":0.2}
```

| Trap | Symptom |
|---|---|
`PATCH` **replaces** the object | omitting `embedding_model` nulls it → keyword mode |
`embedding_model: null` (keyword mode) | `"is BA2490 delayed?"` matched **nothing** — the query shares no word with the description |
`similarity_threshold: 0.0` | results come back in insertion order, not "unfiltered but ranked" |
`top_k` below the orchestrator's `RETRIEVAL_TOP_K` | the gateway cap wins; valid tools never reach the gate |
`0.2` | the threshold the 40-target suite is measured against |

---

## 4. Permissions: key ∩ team, team first

Effective access is the **intersection**. A key can narrow the team; it cannot widen it.

| Field | Level | Effect |
|---|---|---|
`object_permission.agents` | team, key | which `agent_id`s are visible |
`object_permission.mcp_servers` | team, key | which `server_name`s (names, not ids) |
`object_permission.mcp_tool_search_enabled` | key | enables `mcp_tool_search`; **403** without it, even on the admin key |
`models` | team, key | **replaces** the list wholesale; `openai/*` does not match `mai` |
`allowed_routes` | key only | `["llm_api_routes"]` is what stops the orchestrator rewriting its own permissions |

```powershell
$admin = @{ Authorization = "Bearer $env:LITELLM_ADMIN_KEY"; "Content-Type" = "application/json" }

# 1. team first — a key-only grant is rejected:
#    "Key requests MCP servers not allowed by team"
Invoke-RestMethod -Method Post -Uri http://localhost:4001/team/update -Headers $admin -Body @'
{"team_id":"<team-id>","object_permission":{"agents":[],"mcp_servers":["field_ops"]},"models":["openai/*","mai"]}
'@

# 2. then the key
Invoke-RestMethod -Method Post -Uri http://localhost:4001/key/update -Headers $admin -Body @'
{"key":"<virtual-key>","object_permission":{"agents":["<agent-id>"],"mcp_servers":["field_ops"],"mcp_tool_search_enabled":true},"models":["openai/*","mai"]}
'@
```

Merge semantics, measured:

- `/key/update` **merges** `object_permission` sub-fields — an agents-only update keeps the
  MCP grants and `mcp_tool_search_enabled`.
- `models` **replaces**. Always send the full intended list.
- Deleting an MCP server does **not** remove the grant. Grants are by name, so
  re-registering under the same name keeps working with a new `server_id`.

---

## 5. Adding an A2A agent

### 5.1 The card (served by the agent, not by LiteLLM)

| Field | Rule | Enforced by |
|---|---|---|
`name` | non-empty | pre-check |
`description` | non-empty — the planner and the gate reason over this | pre-check |
`skills[]` | at least one, each with `id` or `name` | pre-check |
`url` | equals the URL the **gateway** dials | pre-check (warns) |
`protocolVersion` | `0.3` for the example suite; decides the wire shape | gateway |

### 5.2 Register — the card goes *inside* the body

`POST /v1/agents`, admin key:

```json
{
  "agent_name": "bicycle-repair",
  "agent_card_params": {
    "name": "bicycle-repair",
    "description": "Explains bicycle maintenance and repair: chain and cassette wear, derailleur adjustment, rim and disc brakes, wheel building and tyre setup.",
    "url": "http://a2a-bicycle-repair:9110",
    "version": "1.0.0",
    "protocolVersion": "0.3",
    "capabilities": {"streaming": false},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "provider": {"organization": "Example suite", "url": "http://a2a-bicycle-repair:9110"},
    "skills": [{"id": "drivetrain", "name": "Drivetrain wear and shifting",
                "description": "Chain wear measurement, cassette replacement.", "tags": ["chain"]}]
  },
  "litellm_params": {
    "require_trace_id_on_calls_by_agent": true,
    "max_iterations": 25,
    "max_budget_per_session": 5.0
  }
}
```

Sending the card alone returns `422 body.agent_name Field required`. Sending `agent_name`
alone returns **200** and creates a card-less, unroutable agent — worse, because it is silent.

### 5.3 The URL is a network fact, not a formality

| Gateway runs in | Agent runs in | `url` must be |
|---|---|---|
container | container (same network) | `http://a2a-<id>:<port>` |
container | host | `http://host.docker.internal:<port>` |
host | host | `http://localhost:<port>` |

Change **both** `url` and `provider.url`. A card that says `localhost` while the gateway
runs in a container is the classic "works locally, 500s in the gateway".

### 5.4 After registering

```powershell
GET  /v1/agents                                  # admin: everything; virtual key: only granted
GET  /a2a/{agent_id}/.well-known/agent-card.json # the curated card (url rewritten to the hop)
POST /a2a/{agent_id}                             # exact path — a trailing slash answers 401
```

| Detail | Behaviour |
|---|---|
duplicate name | `409` — delete first or pick another name |
repointing | update the registration, or `DELETE /v1/agents/{agent_id}` then re-create |
invocation shape | `message/send` JSON-RPC only; the `{"message":{...}}` shape returns `400 jsonrpc must be '2.0'` |
the `a2a/` model prefix | resolves against the **model list**, not the agent registry → use `/a2a/{id}` |
orchestrator cache | `CARD_CACHE_TTL_S` (default 300 s); send `"refresh_catalog": true` once |

---

## 6. Adding an MCP server

```json
{
  "server_name": "warehouse_inventory",
  "alias": "warehouse_inventory",
  "transport": "http",
  "url": "http://mcp-warehouse-inventory:9301/mcp",
  "description": "Warehouse stock lookups: on-hand quantity per SKU, bin location, reorder points."
}
```

| Constraint | Error |
|---|---|
`server_name` must not contain `-` | `400 Server name cannot contain '-'` |
name is the identity (grants are by name) | rename ⇒ existing grants stop matching |
`url` must end at the MCP transport path (`/mcp`) | server `unhealthy`, zero tools |
`server_id` is generated by `POST` | — |
`PUT` **requires** `server_id` in the body | `422 body.server_id Input should be a valid string` |

### 6.1 Prove reachability before registering

```powershell
POST /mcp-rest/test/connection  {"url":"http://mcp-warehouse-inventory:9301/mcp","transport":"http"}
POST /mcp-rest/test/tools/list   same body → the tools the gateway would see
```

A literal `{{placeholder}}` is accepted by the gateway and then fails opaquely
("An unexpected error occurred while testing the MCP connection"). Postman does not
substitute collection variables inside a raw body unless they resolve first — check the
port is a number, not a placeholder.

### 6.2 Verify the cached tool list, not just health

```powershell
GET /v1/mcp/server/health                        # per server: healthy | unhealthy
GET /mcp-rest/tools/list?server_id=<name>        # the tools actually cached
```

This is the reliable check. A stale cache in this environment made `bridge_inspection`
serve `payroll_payslips`' tools; `PUT` with the same `server_id` forced a re-fetch.

With semantic tool search on, `tools/list` without `server_id` returns the four **virtual**
tools (`mcp_tool_search`, `mcp_tool_call`, `agent_search`, `skill_search`) instead of real
ones — expected, not a bug.

---

## 7. Adding a model as a routable target

Two independent steps. Being on the gateway does not make a model routable.

```powershell
# 1. the deployment — NOT idempotent: every call adds one
POST /model/new
{"model_name":"mai",
 "litellm_params":{"model":"openai/agent_<id>","api_base":"http://host.docker.internal:3081/api/agents/v1","api_key":"<key>"},
 "model_info":{"description":"LibreChat agent MAI"}}

GET  /model/info                    # read the deployment; note model_info.id (not model_name)
POST /model/delete {"id":"<model_info.id>"}   # exactly one deployment; no delete-by-name
```

```dotenv
# 2. the orchestrator — semicolon-separated "model|description"
MODEL_TARGETS=mai|The MAI agent: Alstom corporate facts only, company name and main office location.
```

Duplicate deployments load-balance, so a second one with a bad `api_base` makes roughly half
of calls fail — which reads as flakiness. Always `GET /model/info` before re-registering.

---

## 8. Status and failure map

| Symptom | Cause | Fix |
|---|---|---|
`No connected db.` | gateway has no database | DB-backed proxy |
`422 body.agent_name Field required` | card sent instead of the envelope | wrap in `agent_card_params` |
`409` on register | name already registered | delete first, or rename |
`400 Server name cannot contain '-'` | catalogue id used as `server_name` | underscores |
`agent_search_not_configured` | `agent_search_embedding_model` unset | `config.yaml` + restart |
`403` on `mcp_tool_search` | key lacks `mcp_tool_search_enabled` | `/key/update` |
`Key requests MCP servers not allowed by team` | key granted before team | `/team/update` first |
`team_model_access_denied` / `key_model_access_denied` | model missing at that level | add to both lists |
`Access denied to agent` / agent missing from `/v1/agents` | no explicit grant (`default_deny`) | `/key/update` with `agents` |
`401 Authentication Error, No api key passed in.` | trailing slash on `/a2a/{id}/` | use the exact path |
server `unhealthy`, no tools | URL not dialable from the container | `/mcp-rest/test/connection` |
tools belong to another server | stale cached list | `PUT /v1/mcp/server` with `server_id` |
`No api key passed in.` on `/key/info` with the virtual key | route scoping working (`llm_api_routes`) | use the admin key |

---

## 9. Two structural risks

**The image is unpinned.** `litellm:latest` resolves to a new release on every pull, and
several behaviours above are version-specific: A2A accepts only the JSON-RPC `message/send`
shape, and the `a2a/` model prefix resolves against the model list rather than the agent
registry. Pin the tag that is running here — `1.110.1` — in compose.

**One key serves every user.** Every request carries the same virtual key, so the gateway
cannot distinguish callers and every granted target is reachable by every user. That is
recorded as a known gap in [README.md](../../README.md#known-gap-per-user-entitlement);
enabling `agent_access_default_deny` narrows *what* the key reaches, not *who* may use it.
Per-user entitlement is a separate, unimplemented layer — see
[entitlement-design.md](entitlement-design.md).

---

## 10. Related

- [api-key-scoping.md](api-key-scoping.md) — measured permission behaviour, route classes
- [onboard-ronaldo-agent.md](onboard-ronaldo-agent.md) — one agent, every request by hand
- [field-ops-mcp-server.md](field-ops-mcp-server.md) — one MCP server end to end
- [deployment.md](deployment.md) — containers, networks, the 40-service suite stack
- [../architecture/routing.md](../architecture/routing.md) — how the orchestrator uses all of it
