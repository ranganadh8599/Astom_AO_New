# Tracing

Two separate questions, often confused:

- **Does one user message produce one trace that spans LibreChat and the orchestrator?**
  Yes — when the message id is forwarded.
- **How are turns grouped into a conversation?** By session id, independently of the trace.

Langfuse's own model is one trace per request, one session per conversation. This layer
follows it rather than inventing a third grouping.

## Joining LibreChat's trace

LibreChat derives its trace id as `sha256(messageId)[:32]`
(`api/packages/api/src/langfuse/trace.ts`) and forwards the message id in a header. The
orchestrator computes the same digest, so its spans land inside the trace LibreChat
already opened:

```python
trace_id = sha256(message_id)[:32]   # identical to LibreChat's formula
```

Verified end to end: message id `librechat-msg-7f3a9c21` produced trace `b4417be3…` in
both systems.

### Resolution order

Highest precedence first:

| Source | Used when |
|---|---|
`traceparent` | the caller already has W3C context |
`X-LibreChat-Message-Id` | LibreChat is the front end — **the normal path** |
conversation-derived | standalone use: CLI, direct calls |

The order is why `TRACE_PER_CONVERSATION=true` is safe in this stack even with LibreChat
in front: the header outranks the setting, so the conversation-derived id is only the
fallback.

## Session grouping is independent

```
session_id = conversationId
```

So a per-message trace still appears inside one conversation in Langfuse. That is what
makes "show me everything that happened in this conversation" possible while "show me this
one request" stays one trace.

## Spans

The orchestrator adds one turn span and one child per outbound call:

| Span | Around |
|---|---|
`orchestrator.turn` | the whole graph invocation |
`litellm.a2a.list_agents` | discovery |
`litellm.mcp.list_tools` | discovery |
`litellm.a2a.search_agents` | retrieval |
`litellm.mcp.search_tools` | retrieval |
`litellm.chat <model>` | planner / gate completions |
`litellm.a2a.invoke <agent>` | one A2A task |
`litellm.mcp.call <tool>` | one MCP task |
`litellm.model.invoke <model>` | one model-target task |

These appear alongside LibreChat's own LLM call in the same trace, which is the point —
you can see the routing decision and the completion in one place.

## Lineage headers

Sent on every gateway call. Observability only; they carry no state:

| Header | Meaning |
|---|---|
`traceparent`, `tracestate` | W3C context |
`x-litellm-trace-id` | LiteLLM's own correlation id |
`x-litellm-agent-id` | attributes spend to the agent |
`x-orchestrator-depth` | how deep in a sub-agent chain |
`x-orchestrator-parent-agent` | which agent spawned this call |

If the backend agent calls LiteLLM again, it should forward `X-LiteLLM-Trace-Id` and
`X-LiteLLM-Agent-Id` so the chain stays one trace and spend attributes correctly.

## `TRACE_PER_CONVERSATION`

| Value | Effect |
|---|---|
`false` (this stack's effective behaviour, because the header wins) | one trace per message when LibreChat forwards the id |
`true` | conversation-scoped traces **for standalone use** |

With LibreChat in front and no message id, `true` produces **two disconnected trees** —
the routing decision in one trace, the LLM call in the other. Prefer forwarding the
message id over relying on this setting.

## Langfuse environment: validated at boot because it fails silently

`LANGFUSE_ENVIRONMENT` is a filter dimension, not a behaviour switch. A bad value does not
raise — the SDK logs `Dropping value` at warning level and sends every trace to `default`:

```
LANGFUSE_ENVIRONMENT=POC  ->  turn completes, no exception
                          ->  "must be a lowercase alphanumeric string ... Dropping value"
```

So the label is validated at startup against Langfuse's own rule
(`^(?!langfuse)[a-z0-9-_]+$`, max 40 characters):

| Value | Result |
|---|---|
`dev`, `staging`, `prod`, `production` | accepted |
`POC`, `Dev`, `prod env`, `prod.env` | **startup error** |
`langfuse-prod` | **startup error** (reserved prefix) |

A new value **creates a new environment**; existing traces keep the label they were
ingested with. Switching `poc` → `dev` splits history into two filter buckets, and Langfuse
cannot rename either.

## Per-user attribution

`LANGFUSE_USER_ID_FIELD` selects which identity attribute becomes Langfuse's `userId`.

| Value | Resolves |
|---|---|
`oid` (default) | stable user id |
`email` | address, when the token or header carries one |
`name` | display name |
`tenant_id` | tenant |
`roles` | the role tuple, stringified — rarely useful |

This is a `getattr` on `UserContext`, so an unknown name falls back to `oid` silently.
That used to be invisible; it now warns at startup:

```
LANGFUSE_USER_ID_FIELD='mail' is not an attribute of UserContext;
traces will fall back to 'oid'. Valid: oid, name, email, roles, tenant_id
```

`email` only became a real field recently — before that it lived in a claims dict that
`to_state()` dropped, so `email` resolved to nothing.

## Turning tracing off

Leave `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` blank. `Tracer` becomes a no-op and
the turn runs unchanged. `/health` reports `"tracing": "off"`.

`LANGFUSE_TRACING_ENABLED=true` with blank keys produces a startup warning rather than an
error — untraced is a valid deployment for local work.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
traces land in `default` | invalid `LANGFUSE_ENVIRONMENT` | boot now errors; fix the label |
two disconnected trees per message | `TRACE_PER_CONVERSATION=true` without a message id | forward `X-LibreChat-Message-Id`, or set `false` |
all traces attributed to one user | `LANGFUSE_USER_ID_FIELD` unset in a shared-key deployment | set `email` or `name` |
orchestrator spans missing, LibreChat's present | trace ids computed differently | confirm the forwarded header name matches `LIBRECHAT_MESSAGE_ID_HEADER` |
`userId` all `oid` despite `email` set | older build before `email` became a field | upgrade; check the startup warning |

## Related

- [decisions/0004](../decisions/0004-one-trace-per-message.md) — why per-message, not per-conversation
- [authorization.md](authorization.md#3-identity) — where `oid` / `email` come from in each auth mode
- [../guides/deployment.md](../guides/deployment.md) — passing Langfuse keys into a container
