# SSO integration: LibreChat → orchestrator

Reference for wiring the orchestrator behind LibreChat's SSO. Written after verifying the
LibreChat v0.8.8 source and the live gateway, because several intuitive settings are
silently wrong.

## How identity reaches the orchestrator

LibreChat's custom endpoint supports per-request header templates:

```yaml
endpoints:
  custom:
    - name: 'A2A Orchestrator'
      # Required by LibreChat's schema; superseded by the Authorization header below.
      apiKey: 'unused-orchestrator-validates-jwt'
      baseURL: 'http://host.docker.internal:8000/v1'
      headers:
        Authorization: 'Bearer {{LIBRECHAT_OPENID_ACCESS_TOKEN}}'
        X-LibreChat-Message-Id: '{{LIBRECHAT_BODY_MESSAGEID}}'
        X-LibreChat-Conversation-Id: '{{LIBRECHAT_BODY_CONVERSATIONID}}'
```

`{{LIBRECHAT_OPENID_ACCESS_TOKEN}}` is a **real signed Entra token**, resolved per request.
Verified in `packages/api/src/utils/oidc.ts`:

```ts
export const OPENID_TOKEN_FIELDS = [
  'ACCESS_TOKEN', 'ID_TOKEN', 'USER_ID', 'USER_EMAIL', 'USER_NAME', 'EXPIRES_AT',
] as const;
```

Requirements:

- **`OPENID_REUSE_TOKENS=true`** on LibreChat. Without it LibreChat holds its own session
  token, and the OpenID placeholders resolve to nothing.
- LibreChat must have `baseURL` fixed in YAML. Headers are dropped when the user supplies
  the URL — the source comment says why: otherwise the template would "leak the user's
  identity token to a destination the user controls".

## Orchestrator configuration

Two supported shapes. Pick one and record the choice.

### Option A — shared key + user header (simplest)

```dotenv
AUTH_MODE=shared_key
ORCH_SHARED_KEY=<min 32 chars — the value LibreChat sends as apiKey>
SHARED_KEY_ROLES=AgentUser
```

```yaml
endpoints:
  custom:
    - name: 'A2A Orchestrator'
      apiKey: '${ORCH_KEY}'                 # → Authorization: Bearer ${ORCH_KEY}
      baseURL: 'http://host.docker.internal:8000/v1'
      headers:
        X-LibreChat-User-Id: '{{LIBRECHAT_USER_ID}}'
        X-LibreChat-User-Email: '{{LIBRECHAT_USER_EMAIL}}'
        X-LibreChat-User-Name: '{{LIBRECHAT_USER_NAME}}'
        X-LibreChat-Message-Id: '{{LIBRECHAT_BODY_MESSAGEID}}'
        X-LibreChat-Conversation-Id: '{{LIBRECHAT_BODY_CONVERSATIONID}}'
```

**What this proves, and what it does not.** The key proves *"the caller is LibreChat"*.
The user header proves **nothing** — it is unsigned, so anyone holding the key can claim
any identity. Accepted deliberately: it needs no per-user token exchange.

Mitigations that are actually implemented:

| Property | Behaviour |
|---|---|
Fails closed | no key, wrong key, or missing user header → 401. No anonymous path |
Constant-time compare | `hmac.compare_digest`, so the key cannot leak by timing |
Identity marked unverified | `claims = {"identity_source": "header", "identity_verified": False}` |
Minimum key length | startup refuses anything under 32 characters |
Startup warning | always emitted, naming the impersonation risk |

If the key leaks, every user is exposed. Rotate it like a password. Prefer Option B when
the threat model includes key compromise or insider risk.

### Option B — Entra token forwarding (verified identity)

```dotenv
AUTH_MODE=entra
ENTRA_TENANT_ID=<tenant-guid>
ENTRA_AUDIENCE=api://librechat      # LibreChat's app ID URI — NOT the orchestrator's
ENTRA_REQUIRED_ROLE=                # leave empty, see below
```

```yaml
      headers:
        Authorization: 'Bearer {{LIBRECHAT_OPENID_ACCESS_TOKEN}}'
```

`DEV_JWT_SECRET`, `DEV_JWT_AUDIENCE`, `DEV_JWT_ISSUER` are ignored in `entra` mode.

### Two settings that fail 100% of requests if wrong

**`ENTRA_AUDIENCE` must be LibreChat's.** The forwarded token is LibreChat's session
access token; its audience comes from LibreChat's `OPENID_SCOPE` (`api://librechat/.default`
per the docs). `EntraValidator` pins audience, so `api://orchestrator` produces:

```
AuthError: token audience is not 'api://orchestrator'
```

**`ENTRA_REQUIRED_ROLE` must stay empty.** `has_role()` reads the `roles` claim, but
delegated user tokens carry `scp` (scopes). `roles` appear only on app-only tokens or where
an app role is assigned to the user in Enterprise Applications. Setting it rejects every
SSO user.

## Verified behaviour (Option A)

```
no headers             -> 401 missing bearer token
key only, no user      -> 401 missing 'x-librechat-user-id' header
wrong key              -> 401 invalid shared key
key + user             -> 200, trace joined, Langfuse userId=user-sso-42
```

## The audience trade — and the on-behalf-of fix

Validating with LibreChat's audience means the token proves *"Entra issued this for
LibreChat"*, **not** *"for the orchestrator"*. Any client able to obtain a LibreChat API
token can call the orchestrator and act as that user. That is inherent to token forwarding,
not a bug in either side.

### Correct fix: on-behalf-of (OBO)

Exchange the user's token for one scoped to the orchestrator, and keep the orchestrator's
own audience:

```
LibreChat --(user token, aud=api://librechat)--> middle layer
middle layer --(OBO, aud=api://orchestrator)--> orchestrator
orchestrator: ENTRA_AUDIENCE=api://orchestrator
```

Then the token genuinely names the orchestrator as its audience, and a LibreChat-scoped
token no longer opens it.

**Why this is not available today:** LibreChat supports OBO only for **MCP servers**
(`mcpServers.<name>.obo.scopes`), not for custom endpoint headers. Verified in v0.8.8 —
the custom endpoint path forwards `endpointConfig.headers` verbatim and has no token
exchange hook. So with the current integration you get the **forwarded** token, not an
exchanged one.

### The middle layer, when you need it

Between LibreChat and the orchestrator, a small service that:

1. Receives the forwarded token on a header (`X-Idp-Token`, not `Authorization`).
2. Calls Entra's OBO endpoint with its own confidential-client credentials:
   `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, `assertion=<user token>`,
   `scope=api://orchestrator/.default`.
3. Forwards the resulting token as `Authorization: Bearer <new token>`.

This is the only place a client secret lives, so it is also the natural place to do
per-user entitlement lookups (see below).

## Per-user entitlement is still unsolved

A validated identity does not grant per-user agent access. Every request carries the same
`LITELLM_API_KEY`, so LiteLLM's `object_permission` cannot distinguish users:

```
SSO user A ─┐
SSO user B ─┼─> one virtual key ─> same agent catalogue for everyone
SSO user C ─┘
```

Measured on the current gateway: `agents: ALL`, one virtual key. Until this changes,
treat the orchestrator as **authenticated but not authorized** — it knows *who* is
calling, not *what they may use*.

Full options, costs, and the decisions needed before implementing:
**[entitlement-design.md](entitlement-design.md)**.

Note that `SHARED_KEY_ROLES` is *not* entitlement, and in this mode it is not access
control either: it is one flat role stamped on every caller so the identity object has
the same shape as an Entra one. There is no role gate in `shared_key` mode — the
validator has no `required_role` and nothing outside `auth/` reads `UserContext.roles`.
Access is decided by `ORCH_SHARED_KEY` plus a present user-id header, nothing else.

Role enforcement exists only in `entra` and `dev` mode, through `ENTRA_REQUIRED_ROLE`
(and read the warning above before setting it behind LibreChat).

## Checklist before enabling

- [ ] `OPENID_REUSE_TOKENS=true` on LibreChat, container restarted
- [ ] Entra app exposes an API and issues a JWT (not opaque) access token for LibreChat
- [ ] `ENTRA_AUDIENCE` matches the token's actual `aud` (decode one and check)
- [ ] `ENTRA_REQUIRED_ROLE` empty
- [ ] Same Langfuse project on both sides, or trace ids match but land in different tenants
- [ ] Decision recorded on the audience trade (accept forwarding, or add OBO)
- [ ] Decision recorded on per-user entitlement

## Verifying a token

Rather than discovering these from 401s in production, decode a sample:

```python
import jwt
claims = jwt.decode(token, options={"verify_signature": False})
print("aud:", claims.get("aud"))
print("iss:", claims.get("iss"))
print("scp:", claims.get("scp"), "roles:", claims.get("roles"))
print("oid:", claims.get("oid"))
```

`aud` must equal `ENTRA_AUDIENCE`; `oid` is the stable user key the orchestrator requires.
