# 0007 — Pooled Postgres connections, probed on readiness

**Status:** Accepted · **Date:** 2026-11 (POC)

## Context

`AsyncPostgresSaver.from_conn_string` opens a single connection and keeps it. That is fine
until Postgres restarts or drops the connection, at which point the next `aget_tuple` raises:

```
psycopg.OperationalError: consuming input failed: server closed the connection unexpectedly
```

Measured consequence: **every subsequent turn returned 500 until the process was restarted**,
while both `/health` and `/ready` still reported healthy. The instance was permanently
wedged and looked fine — the worst possible failure shape.

Two separate problems hide behind that:

- **No recovery.** A dead connection is handed out forever.
- **No detection.** Boot success was treated as permanent health.

## Decision

Two changes, each solving one half.

**1. Pool with health checking.**

```python
AsyncConnectionPool(
    conninfo=dsn, min_size=1, max_size=4,
    check=AsyncConnectionPool.check_connection,   # discard dead on checkout
    max_lifetime=600.0, max_idle=180.0,
)
```

A connection whose server went away is replaced on checkout rather than handed to the graph.

**2. Probe on `/ready`, never `/health`.**

| Setting | Value | Why |
|---|---|---|
`PROBE_TTL_S` | 5s | load balancers poll; don't hammer a struggling database |
`PROBE_TIMEOUT_S` | 5s | a warm probe is 1–2 ms; the slow case is a cold reconnect. A tight bound produced a false `not_ready` and would remove a healthy instance from rotation |

`/health` carries the cached `memory_state` but never fails on it. Liveness must not flap
on a database blip; readiness must, because every turn would 500.

## Consequences

- **The instance self-heals.** Verified: after killing the connections, `/ready` stayed
  green because the next checkout replaced the dead one, and both a single turn and a
  history-dependent follow-up completed normally.
- **A readiness probe is safe to point a load balancer at** — bounded, cached, and it goes
  through the pool so a green result predicts a working turn.
- **A 503 now has two possible causes**, and the body always names which:
  `models.status == "failed"` or `memory.reachable == false`.
- **Boot still fails on a bad DSN.** That is deliberate and unchanged: `open_checkpointer`
  runs during startup, so a broken database is visible immediately.
- The probe only detects a database that is **down**. A partially degraded one (slow
  writes, lock contention) can still pass `SELECT 1` while turns time out — that needs
  latency metrics on the checkpointer calls, not a boolean.

## Windows: the event loop

Unrelated to pooling but found in the same investigation, and it makes Postgres
unbootable there: `uvicorn.run()` hard-codes `ProactorEventLoop` on Windows and **ignores
the loop policy**, which psycopg refuses for async connections.

```python
# uvicorn/loops/asyncio.py
if sys.platform == "win32" and not use_subprocess:
    return asyncio.ProactorEventLoop
```

Setting `WindowsSelectorEventLoopPolicy` does not help — verified, the policy is bypassed.
`python -m orchestrator` supplies the loop explicitly via `asyncio.Runner(loop_factory=...)`.
On Linux the factory is left unset.

## Alternatives rejected

| Alternative | Why not |
|---|---|
retry the single connection | the pool already does this correctly, with lifetime bounds |
reconnect on exception inside the graph | hides the failure in the wrong layer, and a failed turn still fails |
probe on `/health` | a DB blip would restart the container in a loop |
probe with no timeout | a stalled database makes `/ready` hang, which looks like the orchestrator is down |
`--reload` in the entry point | uvicorn implements it with a subprocess, returning to the Proactor loop |

## Evidence

`src/orchestrator/graph/checkpointer.py`, `src/orchestrator/__main__.py`,
`docs/architecture/memory.md#connections-are-pooled`.
