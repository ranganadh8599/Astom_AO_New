# Registering a LibreChat agent in LiteLLM

How to make a LibreChat **agent** (e.g. `MAI`) callable through the LiteLLM gateway as a
model, so it can be used from any OpenAI-compatible client — including LibreChat itself.

Verified end to end on LibreChat v0.8.9 (source run, not Docker) + LiteLLM v1.110.1.

## Why this is not an "agent card" registration

LibreChat has **no A2A support**. There is no `/.well-known/agent-card.json`, no JSON-RPC
endpoint, and nothing in `api/` or `packages/api/src/` that mentions `a2a`.

```
GET http://localhost:3081/.well-known/agent-card.json  ->  404
grep -r "agent-card.json|well-known/agent|a2a" api/ packages/api/src/  ->  no matches
```

A LibreChat agent is a MongoDB document — instructions, model, tools. It has no wire
protocol, so LiteLLM's `agents:` registry (which expects an A2A server) cannot host it.

What *does* work: LibreChat exposes an **OpenAI-compatible** chat surface for its agents,
and LiteLLM can proxy any OpenAI-compatible upstream as a model.

```
LibreChat UI → custom endpoint → LiteLLM model "mai"
                                      ↓
                            LibreChat agent API
                            /api/agents/v1/chat/completions
                                      ↓
                            agent_<id>  (MAI)
```

## The endpoint that makes it possible

`POST /api/agents/v1/chat/completions`

In `api/server/routes/agents/index.js` it is mounted **before** `requireJwtAuth`:

```js
router.use('/v1/agents', management);
router.use('/v1/skills', skills);
router.use('/v1/conversations', conversations);

/** OpenAI-compatible API routes (API key authentication handled in route file) */
router.use('/v1', openai);

router.use(requireJwtAuth);   // ← everything after this needs a session JWT
```

So it authenticates by **LibreChat API key**, not by a browser session. That is what makes
server-to-server calls possible.

Request shape:

```json
POST /api/agents/v1/chat/completions
Authorization: Bearer <librechat-api-key>

{"model": "agent_<agentId>", "messages": [{"role": "user", "content": "..."}]}
```

## Steps

### 1. Bind LibreChat so the gateway can reach it

Default `HOST=localhost` binds `127.0.0.1`, which a containerised LiteLLM **cannot** reach.

```dotenv
# librechat/.env
HOST=0.0.0.0
PORT=3081
```

The startup log confirms it:

```
Server listening on all interfaces at port 3081. Use http://localhost:3081 to access it
```

### 2. Find the agent id

```bash
docker exec mongodb mongosh --quiet --eval \
  "printjson(db.getSiblingDB('LibreChat').agents.findOne({name:'MAI'}, {id:1,name:1}))"
```

```
{ id: 'agent_VQ6h7k1Bt3x3GS_tKGZV2', name: 'MAI' }
```

### 3. Grant the owner `REMOTE_AGENTS.USE`

Creating an API key requires the `REMOTE_AGENTS → USE` permission. A plain `USER` gets:

```
403 {"message":"Forbidden: Insufficient permissions"}
```

Promote the account that will hold the key (or grant the permission through the roles
admin UI — the database edit below is the shortcut used for this test):

```js
db.getSiblingDB('LibreChat').users.updateOne(
  {email: 'orchtester@contoso.com'}, {$set: {role: 'ADMIN'}})
```

Log in again afterwards, so a fresh token carries the new role.

### 4. Create a LibreChat API key

```bash
curl -X POST http://localhost:3081/api/api-keys/ \
  -H "Authorization: Bearer <session-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"name":"orchestrator-adapter"}'
```

```json
{"id":"...","name":"orchestrator-adapter","key":"sk-4e5f65...","keyPrefix":"sk-4e5f6"}
```

Treat this like a password: it grants access to the agents it is scoped to.

### 5. Grant the key remote access to the agent

A key can call an agent only if an ACL entry exists. If the agent belongs to a different
account the call fails with:

```
403 {"message":"No remote access to agent: agent_VQ6h7k1Bt3x3GS_tKGZV2",
     "code":"access_denied"}
```

The check (`packages/api/src/apiKeys/service.ts`) resolves `REMOTE_AGENT` permissions for
the key's user, so the entry must name that user:

```js
var db2 = db.getSiblingDB('LibreChat');
var src = db2.aclentries.findOne({
  resourceType: 'remoteAgent',
  principalId: ObjectId('<original-owner-user-id>')
});
src._id = ObjectId();
src.principalId = ObjectId('<key-owner-user-id>');
src.grantedBy = ObjectId('<key-owner-user-id>');
src.grantedAt = new Date();
src.updatedAt = new Date();
db2.aclentries.insertOne(src);
```

Normally this is done through the sharing UI; the insert is the reproducible version.

### 6. Register the model in LiteLLM

```bash
curl -X POST http://localhost:4001/model/new \
  -H "Authorization: Bearer $LITELLM_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "mai",
    "litellm_params": {
      "model": "openai/agent_VQ6h7k1Bt3x3GS_tKGZV2",
      "api_base": "http://host.docker.internal:3081/api/agents/v1",
      "api_key": "<librechat-api-key>"
    },
    "model_info": {"description": "LibreChat agent MAI"}
  }'
```

`api_base` must be reachable **from the LiteLLM container**. On Docker Desktop that is
`host.docker.internal`; for a LiteLLM running on the host, use `127.0.0.1`.

### 7. Allow the model on the key *and* the team

LiteLLM checks both, and the error tells you which one refused:

| Error `type` | Fix |
|---|---|
`key_model_access_denied` | add the model to the key's `models` |
| `team_model_access_denied` | add the model to the **team's** `models` |

```bash
curl -X POST http://localhost:4001/key/update -H "Authorization: Bearer $LITELLM_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key":"<virtual-key>","models":["openai/*","mai"]}'

curl -X POST http://localhost:4001/team/update -H "Authorization: Bearer $LITELLM_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"team_id":"<team-id>","models":["openai/*","mai"]}'
```

The key alone is not enough — a keyed request still inherits its team's allowlist.

### 8. Verify through the gateway

```bash
curl -s http://localhost:4001/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_VIRTUAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"mai","messages":[{"role":"user","content":"What is our company name?"}]}'
```

```
The company name is Alstom and the office location is ITC green park.
```

## Optional: make it selectable in the LibreChat UI

Registering in LiteLLM is enough for API clients, but LibreChat **validates models against
its own YAML list** — it will reject `mai` before making any network call:

```
The model "mai" is not available for LiteLLM. Please select a different model.
```

So declare it on the endpoint, and expose it as a model spec:

```yaml
endpoints:
  custom:
    - name: 'LiteLLM'
      apiKey: '${LITELLM_KEY}'
      baseURL: 'http://localhost:4001/v1'
      models:
        default: ['openai/gpt-4o-mini', 'mai']   # ← must be listed here
        fetch: false

modelSpecs:
  list:
    - name: 'mai'
      label: 'MAI (via LiteLLM)'
      preset:
        endpoint: 'LiteLLM'
        model: 'mai'
```

Restart LibreChat after editing `librechat.yaml`.

## Failure modes seen while wiring this up

| Symptom | Cause |
|---|---|
`Connection error` from LiteLLM | LibreChat bound to `127.0.0.1`; the container cannot reach it |
`Missing or invalid Authorization header` | sent a session JWT; this route wants an API key |
`Forbidden: Insufficient permissions` (key creation) | account lacks `REMOTE_AGENTS.USE` |
`No remote access to agent` | no `remoteAgent` ACL entry for the key's owner |
`key_model_access_denied` | model missing from the key's `models` |
`team_model_access_denied` | model missing from the **team's** `models` |
`The model "mai" is not available for LiteLLM` | model missing from `librechat.yaml` |

## What this does *not* give you

**MAI is a model, not an agent target.** It is callable as an LLM but invisible to the
orchestrator's catalogue, so the gate and planner will never route to it:

- ✅ selectable in LibreChat, callable from any OpenAI client through LiteLLM
- ❌ not discoverable via `GET /v1/agents`, not routable by the A2A Orchestrator

To make it a routing target it needs a thin **A2A adapter** — a service serving
`/.well-known/agent-card.json` and JSON-RPC `message/send`, forwarding to the same
`/api/agents/v1/chat/completions` URL. `examples/ronaldo_agent/server.py` is the working
template for that shape.

**Identity is the adapter's, not the user's.** The LiteLLM model holds one LibreChat API
key, so every caller of `mai` through the gateway acts as that key's owner. Per-user
identity is lost at this hop — the same single-credential problem as the orchestrator's
shared `LITELLM_API_KEY`.
