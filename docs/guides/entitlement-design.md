# Per-user entitlement: design options

**Status: not implemented.** The orchestrator authenticates users (it knows *who* is
calling) but does not authorize them (it does not know *what they may use*). This records
the gap, the options, and what each costs, so the decision is made deliberately rather
than by default.

Measured on the current gateway:

```
orchestrator key permissions:
  agents allowed      : ALL (no restriction)
  agent_access_groups : none
  mcp_servers         : ['field_ops']
number of virtual keys: 1
```

## The gap, concretely

Authentication is per-user; the gateway call is not.

```
alice  (HR)         ─┐
bob    (contractor)  ─┼─→ ONE virtual key (sk-2FbL…) ─→ ALL agents
carol  (finance)    ─┘
```

LiteLLM decides access **by key**, using `object_permission`. One key for everyone means
`agents: ALL` applies to everyone. A contractor asking "what is the salary band for L7?"
reaches a payroll agent, because nothing checks whether contractors may use it.

The orchestrator knows who they are. It has no mechanism to act on it.

## Why this is load-bearing, not a nice-to-have

Three consequences, in order of severity:

1. **Read exposure.** The orchestrator is read-only, so the write surface is closed by
   design. Entitlement is the *only* control over what data a user can reach. With none,
   every registered agent is readable by every caller.

2. **Retrieval makes it invisible.** Discovery surfaces whatever the key can reach. The
   planner prompt lists every agent, so an internal-only agent appears in every user's
   candidate set — and the gate may route to it.

3. **Cost attribution collapses.** LiteLLM spend rolls up to one key: you can see that
   money was spent, not who spent it. Langfuse carries `userId`, but the gateway — where
   cost is tracked and budgets enforced — does not.

## Options

### Option 1 — per-user virtual keys

Mint a LiteLLM key per user on first login, cache in-process, refresh on permission
change.

```
alice → sk-alice (agents: hr-policy, finance)
bob   → sk-bob   (agents: hr-policy)
```

| | |
|---|---|
**Enforcement** | in the gateway, which already implements it |
**Cost attribution** | per user, for free — budgets and spend roll up correctly |
**Effort** | key store, minting on first login, cache invalidation, refresh path |
**Risk** | a key store becomes a new secret to protect; stale keys grant stale access |

The `LiteLLMGateway` already takes one key from settings. This would make it take a key
per request, which touches `_request_json` — the single choke point, so the change is
contained.

### Option 2 — filter candidates at request time

Ask the gateway what the user is allowed to see, and drop candidates before the planner.

```python
allowed = await gateway.entitlements(user.oid)      # agents + access groups
candidates = [c for c in candidates if c.agent_name in allowed]
```

| | |
|---|---|
**Enforcement** | in the orchestrator, using the gateway as the policy source |
**Cost attribution** | unchanged — still one key |
**Effort** | one extra call per turn; a filter in `TargetCatalog.discover_for` |
**Risk** | enforcement lives in our code, not the gateway's — a bug means exposure |

The natural insertion point is `discover_for`, which already receives the query and
returns candidates. Filtering there means the planner never sees a disallowed agent, so
it cannot route to one.

### Option 3 — accept a single entitlement

Do nothing, and state explicitly that every registered agent is readable by everyone.

| | |
|---|---|
**Effort** | none |
**Valid when** | the catalogue is genuinely org-wide: no per-team, no per-role agents |
**Invalid when** | any agent is "internal to a team" — which is the usual meaning |

Dangerous as a default because "internal agent" almost always means "internal to a
team", not "internal to the company". If chosen, record it here so a future payroll agent
is a deliberate decision rather than an incident.

## Recommendation

**Option 2 first, Option 1 when cost attribution matters.**

Option 2 is the smaller change and closes the exposure risk — the thing that becomes an
incident. Option 1 additionally fixes cost attribution, but a key store is a bigger
commitment and a new secret surface.

They compose: filter at request time now, and swap the filter's source for a per-user key
later without changing the graph.

## What to decide before implementing

- [ ] Is any planned agent more sensitive than the whole company?
      *(If yes, this is a prerequisite, not a phase.)*
- [ ] Does cost need per-user attribution, or is per-conversation enough?
      *(Per-conversation works today via Langfuse `sessionId`.)*
- [ ] Where does the entitlement source live — LiteLLM `object_permission`, an IdP group
      claim, or a separate policy service (OPA is already in the sibling stack)?
- [ ] What happens on denial: filter silently, or tell the user the agent exists but is
      not available to them?
      *(Silent filtering invites "why can't it find my agent?" support tickets.)*

## Note on `SHARED_KEY_ROLES`

`SHARED_KEY_ROLES=AgentUser` is **not** entitlement. It is one flat role stamped on every
shared-key caller, and it gates nothing: shared-key mode has no role check (the validator
takes no `required_role`) and nothing outside `auth/` reads `UserContext.roles`. It exists
so the identity object has the same shape as an Entra token. Access is decided by
`ORCH_SHARED_KEY` plus a present user-id header. It carries no per-user information,
because shared-key mode has no per-user role source. Do not mistake it for authorization.

---

# Deferred: enforce the role claim

**Status: not implemented — design note only.** No code exists for this. Recorded so the
work is deliberate rather than improvised when it is needed. It is *not* the same as
per-user entitlement above: a role gate is one coarse yes/no for a caller, not a
per-agent allowlist.

## The gap today

Two of the three auth modes ignore roles entirely:

| `AUTH_MODE` | Reads `roles` | Gate applied |
|---|---|---|
`entra` | yes (token `roles` claim) | `ENTRA_REQUIRED_ROLE`, if set |
`dev` | yes (locally signed token) | `ENTRA_REQUIRED_ROLE`, if set |
`shared_key` | yes — stamped from `SHARED_KEY_ROLES` | **none** |
`none` | no | none |

So `SHARED_KEY_ROLES=AgentUser` is a claim-shape filler; and `ENTRA_REQUIRED_ROLE` is
mode-specific despite the neutral-sounding name. Verified by construction: `has_role()` is
called only from `EntraValidator.validate` and `DevValidator.validate`, both gated on a
`required_role` argument that `SharedKeyValidator.__init__` does not accept.
`UserContext.roles` is written to the LangGraph checkpoint via `to_state()` and read by
nothing outside `auth/`.

## Why the gate is worth having anyway

Not for per-user authorization — that is the entitlement problem above. Three narrower
reasons:

1. **Coarse kill switch without rotating the key.** "Only callers holding `AgentUser` may
   use this deployment" is expressible today only in `entra` mode. In `shared_key` mode
   the only lever is rotating `ORCH_SHARED_KEY`, which logs everyone out.
2. **Mode parity.** Switching `shared_key` → `entra` should change *how* identity is
   proven, not *what* is enforced. Today it silently turns an ignored setting into a live
   401.
3. **Attachment point for the policy check.** Whatever replaces this — OPA, an IdP group
   claim, per-agent entitlement — needs a decision already being made per request.
   Establishing the hook now is cheaper than retrofitting it.

It does **not** solve read exposure: every caller in shared-key mode holds the same flat
role, so the gate is all-or-nothing for the deployment. Saying otherwise in a review would
be the same mistake this document exists to prevent.

## Proposed shape (when implemented)

One setting, honoured by every mode, with the old name kept for compatibility.

```dotenv
# empty = no role gate (default, today's behaviour)
REQUIRED_ROLE=AgentUser
# legacy alias, still honoured in entra/dev so existing deployments keep working
ENTRA_REQUIRED_ROLE=
```

```python
# config.py
auth_required_role: str = ""          # REQUIRED_ROLE

@property
def effective_required_role(self) -> str:
    return self.auth_required_role or (
        self.entra_required_role if self.auth_mode in ("entra", "dev") else ""
    )
```

Then the check moves from the validators into one place, so it cannot be forgotten by a
future mode:

```python
# api/app.py :: current_user — the single dependency every route already depends on
user = authenticator.validate(token, dict(request.headers))
required = settings.effective_required_role
if required and not user.has_role(required):
    raise HTTPException(status_code=403, detail=f"missing required role {required!r}")
return user
```

Prefer this over a per-validator parameter. `current_user` is the one chokepoint every
route passes through; the validators are three separate implementations and a fourth mode
would silently skip the gate.

## Startup validation to add

Fail loudly rather than 403 every request at runtime:

- `REQUIRED_ROLE` set in `shared_key` mode but absent from `SHARED_KEY_ROLES` → startup
  **error**, because the role is flat and no caller could ever satisfy it.
- `shared_key` mode with `REQUIRED_ROLE=AgentUser` and the default
  `SHARED_KEY_ROLES=("AgentUser",)` → permitted, but log a warning that the gate is a
  no-op: the role is stamped on every caller, so it cannot exclude anyone. The gate only
  has teeth in `entra`/`dev`, where the role comes from a token.
- Both `REQUIRED_ROLE` and `ENTRA_REQUIRED_ROLE` set to different values → startup
  **warning** naming which one wins (`REQUIRED_ROLE`), so the dead setting is visible.

## Tests to add

In `tests/auth/test_shared_key_auth.py` and `tests/auth/test_auth.py`:

1. `shared_key`: `REQUIRED_ROLE` matching a stamped role → 200.
2. `shared_key`: `REQUIRED_ROLE` not in `SHARED_KEY_ROLES` → 401/403 at the route, and a
   startup error from `Settings.validate()`.
3. `shared_key`: `REQUIRED_ROLE` empty → unchanged behaviour (regression guard for every
   existing test, which run without it).
4. `entra`/`dev`: `REQUIRED_ROLE` behaves exactly as `ENTRA_REQUIRED_ROLE` does today.
5. `entra`/`dev`: both set, different values → `REQUIRED_ROLE` wins.
6. `AUTH_MODE=none` → gate skipped, and a warning is logged if `REQUIRED_ROLE` is set.

## Decisions to make first

- [ ] Status code on denial: `401` (identity rejected) or `403` (identity accepted, role
      missing)? The codebase uses `401` for every `AuthError` today; `403` is more honest
      and matches LiteLLM's own convention for permission failures.
- [ ] Does the gate apply to `/health` and `/ready`? It should not — a probe carries no
      identity, and gating them would fail liveness.
- [ ] Should `SHARED_KEY_ROLES` remain a list? With a gate in place a list implies "any
      of", which is fine, but if only one role is ever meaningful, a single value is
      clearer.
- [ ] Behind LibreChat SSO, delegated tokens carry `scp`, not `roles` — so the gate is
      unusable in `entra` mode there. See the checklist in
      [sso-integration.md](sso-integration.md); decide whether that is acceptable or
      whether scope-based gating is needed instead.

## What this does not change

Nothing in this section is implemented. Current behaviour is unchanged: no role is
enforced in `shared_key` or `none` mode, and `ENTRA_REQUIRED_ROLE` continues to work as
before in `entra` and `dev`.
