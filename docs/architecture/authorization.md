# Authorization

Three different questions, three different layers. They are often conflated, which is how
"we have auth" becomes "everything is fine" when nothing is authorized.

| Layer | Question | Where enforced | Status |
|---|---|---|---|
1. **Which key reaches which route** | may this caller read keys / teams / models? | LiteLLM `allowed_routes` | ✅ implemented |
2. **What a user may use** | may *this person* reach *this agent*? | nothing | ❌ **not implemented** — the largest gap |
3. **Who the caller is** | is this user authenticated, and how? | `AUTH_MODE` validator | ✅ implemented |

Detail lives in three source docs; this page is the map.

## 1. Which key reaches which route

LiteLLM keys carry `allowed_routes`. The orchestrator's virtual key has
`["llm_api_routes"]`, which covers models, chat, agents and the MCP REST surface.

| Route | Virtual key | Admin key |
|---|---|---|
`/v1/chat/completions`, `/v1/embeddings` | ✅ | ✅ |
`/v1/agents`, `/v1/models` | ✅ | ✅ |
`/mcp-rest/tools/*`, `/v1/mcp/server` | ✅ | ✅ |
`/a2a/{agent_id}` | ✅ | ✅ |
`/key/*`, `/team/*`, `/model/*` | ❌ **403** | ✅ |
`/get/*`, `/update/*` | ❌ **403** | ✅ |

```
{"detail":"Virtual key is not allowed to call this route.
           Only allowed to call routes: ['llm_api_routes'].
           Tried to call route: /key/info"}
```

That 403 is the boundary working. **Rule of thumb:** if the path starts with `/key`,
`/team`, `/model`, `/get` or `/update`, use the admin key. Everything else uses the
virtual key. The orchestrator never calls those routes — it can route traffic but cannot
rewrite its own permissions.

Effective access is **key ∩ team**: a model or server missing from either level is denied.
That is why granting on the key alone fails with `Key requests MCP servers not allowed by
team` — grant at team level first.

Two behaviours worth knowing (both measured on a live gateway):

- **`POST /key/update` merges `object_permission`**, so an agents-only update does not wipe
  MCP grants. But `models` *does* replace wholesale.
- **`agents: []` is ambiguous.** On four freshly generated keys it behaved as *denied*;
  on the orchestrator's own key it behaved as *unrestricted*. Do not treat an empty list
  as "no restriction" — grant agent ids explicitly if agent access matters.

Full detail: [../guides/api-key-scoping.md](../guides/api-key-scoping.md#2-empty-agents--is-ambiguous--do-not-rely-on-it).

### The admin key is CLI-only

`LITELLM_ADMIN_KEY` has one consumer: `python -m orchestrator.admin.onboarding`, which ships four
subcommands:

| Subcommand | Does |
|---|---|
`check --url <agent>` | fetch the agent's card and reject it if unusable (no description, no skills, URL mismatch) |
`register --name <n> --url <agent>` | `POST /v1/agents` |
`verify --name <n>` | confirm it is visible to a key |
`smoke --name <n> --text <msg>` | send one harmless message through the gateway |

Steps 1 and 4 are read-mostly; only `register` needs the admin key. The runtime never reads
it and `Settings.validate()` does not require it, which is why it is optional in `.env`.
Keeping it out of the service environment means an orchestrator compromise cannot mint
keys, edit teams, or register agents. Preferred posture: leave it blank and export it only
for the onboarding run, or pass `--admin-key`.

It runs as a CLI rather than inside the service for exactly that reason — registration needs
the admin key, and the service holds only a scoped virtual key. Walkthrough:
[../guides/onboard-ronaldo-agent.md](../guides/onboard-ronaldo-agent.md).

## 2. What a user may use (not implemented)

Authentication is per-user; the gateway call is not:

```
alice  (HR)         ─┐
bob    (contractor)  ─┼─→ ONE virtual key (sk-…) ─→ ALL agents
carol  (finance)    ─┘
```

LiteLLM decides access **by key**, so one key for everyone means `agents: ALL` applies to
everyone. The orchestrator knows who is calling and has no mechanism to act on it.

Three consequences, in order of severity:

1. **Read exposure.** The orchestrator is read-only, so the write surface is closed by
   design. Entitlement is the *only* control over what data a user can reach — and there
   is none.
2. **Retrieval makes it invisible.** Discovery surfaces whatever the key can reach, so an
   internal-only agent appears in every user's candidate set and the gate may route to it.
3. **Cost attribution collapses.** Spend rolls up to one key: you can see that money was
   spent, not who spent it. Langfuse carries `userId`; the gateway, where budgets are
   enforced, does not.

Options and costs: [../guides/entitlement-design.md](../guides/entitlement-design.md). The recommendation
there is filter-at-request-time first (closes the exposure risk), then per-user keys when
cost attribution matters.

### The role claim is not a gate

`SHARED_KEY_ROLES=AgentUser` is one flat role stamped on every shared-key caller. In
`shared_key` mode it **grants and denies nothing**: the validator has no `required_role`
and nothing outside `auth/` reads `UserContext.roles`. It exists so the identity object has
the same shape as an Entra token.

Role *enforcement* exists only in `entra` and `dev` mode, through `ENTRA_REQUIRED_ROLE` —
and behind LibreChat SSO that must stay empty, because delegated tokens carry `scp`, not
`roles`. See the deferred design in
[../guides/entitlement-design.md](../guides/entitlement-design.md#deferred-enforce-the-role-claim).

## 3. Identity

One dependency on the router, so a new route cannot be added without inheriting the check.

| `AUTH_MODE` | Validates | Identity from | Role gate |
|---|---|---|---|
`dev` | locally signed HS256 token, Entra-shaped | token claims | `ENTRA_REQUIRED_ROLE` |
`entra` | signature against tenant JWKS, issuer + audience pinned | token claims | `ENTRA_REQUIRED_ROLE` |
`shared_key` | one secret, constant-time compare | **unsigned header** | none |
`none` | nothing | constant `anonymous` | none |

All four produce the same `UserContext` (`oid`, `name`, `email`, `roles`, `tenant_id`,
`scopes`), so switching mode changes only which validator is constructed.

### `shared_key` trades verification for simplicity

The key proves *"the caller is LibreChat"* — or anything else holding it. The user header
proves **nothing**: it is unsigned, so anyone with the key can claim any user id.

Properties that make it survivable rather than reckless:

| Property | Behaviour |
|---|---|
Fails closed | no key, wrong key, or missing user header → 401. No anonymous path |
Constant-time compare | `hmac.compare_digest`, so the key cannot leak by timing |
Identity marked unverified | `claims = {"identity_source": "header", "identity_verified": false}` |
Minimum key length | startup refuses anything under 32 characters |
Startup warning | always emitted, naming the impersonation risk |

The three header names are configurable (`USER_ID_HEADER`, `USER_EMAIL_HEADER`,
`USER_NAME_HEADER`) because they are a contract with the front end — but changing them
means changing `librechat.yaml` too. The id header is **required**; email and name are
optional enrichment.

### `entra`

For a standalone deployment validating its own audience, no code changes are needed —
`build_authenticator` swaps the validator and the claim shape is identical, so
`UserContext` and everything downstream are untouched:

```dotenv
AUTH_MODE=entra
ENTRA_TENANT_ID=<tenant-guid>
ENTRA_AUDIENCE=api://<orchestrator-app-id>
ENTRA_REQUIRED_ROLE=AgentUser
```

Behind LibreChat SSO two settings differ and both fail every request if wrong:

```dotenv
# Option A: shared key + user header (simplest, identity unverified)
AUTH_MODE=shared_key
ORCH_SHARED_KEY=<min 32 chars>

# Option B: forwarded Entra token (identity verified)
AUTH_MODE=entra
ENTRA_TENANT_ID=<tenant-guid>
ENTRA_AUDIENCE=api://librechat      # LibreChat's app ID URI, not the orchestrator's
ENTRA_REQUIRED_ROLE=                # empty: delegated tokens carry `scp`, not `roles`
```

Option A is one secret and no token exchange, but a key holder can impersonate any user —
the header is unsigned. Option B verifies the user but validates LibreChat's audience, so
**any LibreChat token opens the orchestrator**; the correct fix is an on-behalf-of exchange,
which LibreChat supports for MCP servers only, not for custom endpoint headers.

The consequence to understand: validating LibreChat's audience means any LibreChat token
opens the orchestrator. The record of that trade:
[../guides/sso-integration.md](../guides/sso-integration.md).

## What is verified, and how

Folder **14 · Authorization boundary** in the Postman collection proves each route case for
both keys:

```
Virtual key CAN list agents              200
Virtual key CAN list models              200
Virtual key CAN list MCP tools           200
Virtual key CANNOT read /key/info        403  (EXPECTED)
Virtual key CANNOT read /team/info       403  (EXPECTED)
Admin key CAN read /key/info             200
Admin key CAN read /team/info            200
```

The `/key/info` example doubles as a permission inspector: it logs `allowed_routes`,
effective `models`, `mcp_servers` and `agents`.

## Operational rules

1. **Never give the orchestrator the admin key.** Separate settings, separate consumers.
2. **Grant at team level first**, then key level. Key-only grants are rejected.
3. **Use the admin key for inspection.** `/key/info` is the only way to see effective
   permissions.
4. **Do not tighten `agents` until the agent list is stable** — an explicit list means new
   agents are invisible until granted.

## Where each write goes

Registration and grants are operator actions, not runtime ones: the admin key exists only
for the onboarding CLI and is never in the service environment. Team before key, always.

| Action | Endpoint | Credential | Why |
|---|---|---|---|
| register agent | `POST /v1/agents` | admin | returns the `agent_id` you need to grant |
| register MCP server | `POST /v1/mcp/server` | admin | returns `server_name` / `server_id` |
| register model | `POST /model/new` | admin | **not idempotent** — check `/model/info` first |
| grant team | `POST /team/update` | admin | must come first |
| grant key | `POST /key/update` | admin | merges `object_permission` |
| create key with grants | `POST /key/generate` | admin | top-level `agents: [...]`, not nested |
| inspect | `GET /key/info`, `GET /team/info` | admin | the only way to see effective permissions |
| verify | `GET /v1/agents`, `GET /mcp-rest/tools/list` | **virtual** | proves what the runtime actually sees |

5. **A 403 is a boundary, not an outage.** Read the message: `not allowed to call this
   route` = wrong key; `access_denied` on a model = the allowlist; `No remote access to
   agent` = a LibreChat ACL, not LiteLLM.
6. **Treat `shared_key` as a trusted-network mode.** Prefer `entra` when the threat model
   includes insider or key-compromise risk.

## Related

- [../guides/api-key-scoping.md](../guides/api-key-scoping.md) — route classes, key ∩ team, the two counter-intuitive behaviours
- [../guides/entitlement-design.md](../guides/entitlement-design.md) — per-user options, and the deferred role gate
- [../guides/sso-integration.md](../guides/sso-integration.md) — token forwarding vs shared key, the OBO gap
- [../postman/README.md](../postman/README.md) — how to run folder 14
