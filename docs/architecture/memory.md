# Conversation memory

`thread_id` is the `conversation_id`, so the checkpointer *is* the memory: `history` and
the per-turn keys live under that thread. The graph shape does not change between
backends — only where the state is stored.

| | `memory` (default) | `postgres` |
|---|---|---|
Backend | `InMemorySaver` | `AsyncPostgresSaver` + `AsyncConnectionPool` |
Survives restart | no | **yes** |
Survives multiple replicas | no | yes |
Setup | none | `pip install -e ".[postgres]"` + `POSTGRES_DSN` |
Per-turn latency | — | one round-trip to load, one to save |

Switch to Postgres when you need more than one replica or to survive a restart — not
before. In-process memory is faster and needs nothing.

## Turning it on

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[postgres]"
```

```dotenv
CHECKPOINT_BACKEND=postgres
POSTGRES_DSN=postgresql://user:pass@host:5432/orchestrator
```

```powershell
# NOT the uvicorn CLI — see the Windows section below
.\.venv\Scripts\python.exe -m orchestrator --port 8000
```

A bad DSN fails **boot**, not the first request. That is deliberate: `open_checkpointer`
runs during startup, so a broken database is visible immediately rather than as a 500 on
someone's first question.

## What is created automatically

| Thing | Who creates it | When |
|---|---|---|
database | `POSTGRES_AUTO_CREATE` (default on) | first boot, if the name in the DSN is missing |
`checkpoints` | `saver.setup()` | first boot, if absent |
`checkpoint_blobs` | `saver.setup()` | " |
`checkpoint_writes` | `saver.setup()` | " |
`checkpoint_migrations` | `saver.setup()` | " |

Verified from nothing: an empty cluster plus one DSN produced both the database and the
four tables on first boot; a second boot is a no-op.

Set `POSTGRES_AUTO_CREATE=0` where the application role deliberately lacks `CREATEDB`
(managed Postgres, locked-down prod). The failure then names the database to create rather
than surfacing a raw driver error:

```
database 'orch' does not exist and this role may not create it (permission denied).
Create it once manually:
  CREATE DATABASE orch;
```

## Which database? The DSN's path is the answer

There is no separate database-name setting. The name is the path segment after the port:

```
postgresql://postgres:admin@localhost:5433/orchestrator
                                          ^^^^^^^^^^^^ dbname
```

| Piece | Meaning |
|---|---|
application DB | where tables and rows live |
maintenance DB (`postgres`) | used only to issue `CREATE DATABASE` |

Confirm at runtime rather than trusting config:

```sql
-- which database the pooled connections actually reached
select datname, count(*) from pg_stat_activity
where usename = 'postgres' and datname is not null
group by datname order by 2 desc;
```

### Omitting the name is a silent wrong database

libpq falls back to the *user* name:

```
postgresql://postgres:admin@localhost:5433       -> dbname=None
postgresql://postgres:admin@localhost:5433/      -> dbname=None
  -> connected to: current_database = 'postgres'
```

With a role called `postgres`, that writes checkpoint tables into the maintenance database,
alongside the system catalog. Auto-creation also skips, because there is no name to create:

```python
if not dbname or dbname == maintenance_db:
    return
```

Always name the database explicitly.

## Restart semantics

Measured on Postgres 19 (Windows): turn 1 in one process, that process killed, turn 2 in a
fresh process on the same conversation. The follow-up `"and what is its maintenance
history?"` resolved `"its"` from history the dead process wrote.

With `InMemorySaver` the same sequence fails:

```
status  = failed
args    = {"asset_id":""}
answer  = "field_ops-get_asset_maintenance_history could not answer:
           planner did not supply required argument(s): asset_id"
```

That contrast is the entire reason to enable Postgres.

## Connections are pooled, and that is what makes it recover

`AsyncPostgresSaver.from_conn_string` opens **one** connection and keeps it. When Postgres
restarts, the server drops it and the next `aget_tuple` raises:

```
psycopg.OperationalError: consuming input failed: server closed the connection unexpectedly
```

Measured before pooling: every subsequent turn returned **500 until the process was
restarted**, while both `/health` and `/ready` still reported healthy. The instance was
permanently wedged and looked fine.

The pool fixes the wedge:

```python
AsyncConnectionPool(
    conninfo=dsn, min_size=1, max_size=4,
    check=AsyncConnectionPool.check_connection,   # discard dead on checkout
    max_lifetime=600.0, max_idle=180.0,
)
```

Verified: after killing the connections, both a single turn and a history-dependent
follow-up completed normally.

## Health: `/ready`, never `/health`

Boot success proves nothing about *now*. The checkpointer is probed on `/ready` with a
cached, timeout-bounded `SELECT 1`:

| Setting | Value | Why |
|---|---|---|
`PROBE_TTL_S` | 5s | load balancers poll; do not hammer a struggling database |
`PROBE_TIMEOUT_S` | 5s | a warm probe is 1–2 ms; the slow case is a cold reconnect, measured over 2s once. Too tight a bound produces a false `not_ready`, which removes a healthy instance from rotation |

```json
{"status": "not_ready",
 "models": {"status": "ok"},
 "memory": {"backend": "postgres", "reachable": false,
            "error": "probe timed out after 5s"}}
```

`/health` carries `memory_state` from the same probe but **never fails on it** — liveness
must not flap on a database blip. See [routing.md](routing.md) and the README for the
liveness-vs-readiness table.

The probe checks out through the pool rather than touching a raw connection, so it
exercises the same repair path the graph takes. A green probe really does predict a
working turn.

## Windows: the event-loop trap

`CHECKPOINT_BACKEND=postgres` **cannot** start through the `uvicorn` CLI on Windows:

```
psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode.
ERROR:    Application startup failed. Exiting.
```

Two things are true and both are surprising:

1. `uvicorn.run()` **ignores** the event-loop policy. `uvicorn/loops/asyncio.py` hard-codes
   `if sys.platform == "win32" and not use_subprocess: return asyncio.ProactorEventLoop`.
2. Therefore `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`
   does **not** help — verified, the policy is bypassed.

The only fix that works without patching uvicorn is to supply the loop explicitly:

```python
asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
```

`python -m orchestrator` does exactly that (`asyncio.Runner`, so it works on 3.11 where
`asyncio.run` has no `loop_factory`). On Linux the factory is left unset, so behaviour
there is unchanged — but the same command works everywhere, which stops the documented
invocation drifting from the tested one.

`--reload` is deliberately absent from that entry point: uvicorn implements it with a
subprocess, which returns to the Proactor loop and re-breaks psycopg.

## Inspecting state

```sql
-- one row set per conversation
select thread_id, count(*) from checkpoints group by thread_id order by 2 desc;

-- the newest checkpoint for one conversation
select thread_id, checkpoint_id, metadata from checkpoints
where thread_id = 'my-conv' order by checkpoint_id desc limit 5;

-- tidy up test conversations
delete from checkpoints        where thread_id like 'pm-%';
delete from checkpoint_blobs   where thread_id like 'pm-%';
delete from checkpoint_writes  where thread_id like 'pm-%';
```

## What agents can see

Nothing from the checkpointer. Invocations are one-shot and stateless:

| Protocol | Payload |
|---|---|
A2A | `message/send` with `parts: [{kind:"text", text: <instruction>}]` |
MCP | `{server_id, name, arguments}` — no instruction text at all |
model | `messages: [{role:"user", content:<instruction>}]` |

No target receives `history`, the conversation id, or another target's output. Two headers
carry cross-service context, and they are observability only:

```
traceparent, tracestate, x-litellm-trace-id
x-orchestrator-depth, x-orchestrator-parent-agent
```

So fan-out is **blind parallelism**: two agents in the same turn do not know about each
other. The only channel between them is the planner, which must copy any needed value into
each task's `instruction`/`arguments` upstream. Cross-agent reasoning therefore happens at
plan time, not at execution time.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
`ModuleNotFoundError: psycopg` at boot | built without the `[postgres]` extra | `pip install -e ".[postgres]"`; in Docker, request `a2a-orchestrator[postgres]` at install |
`RuntimeError: CHECKPOINT_BACKEND=postgres requires POSTGRES_DSN` | DSN empty | set it |
`database "x" does not exist` | name wrong, or auto-create disabled | check the DSN path; see above |
turns 500 until restart | pre-pooling behaviour, or a very old image | ensure the pool is in use |
`/ready` 503, `reachable:false` | database down | expected; the instance should leave rotation, not restart |
history missing after restart | `CHECKPOINT_BACKEND=memory` | switch to postgres |
history missing after restart, backend is postgres | DSN points at a different database than the one you inspect | `pg_stat_activity` query above |

## Related

- [decisions/0007](../decisions/0007-postgres-pooling.md) — pooling and the wedge it fixed
- [../guides/deployment.md](../guides/deployment.md) — the compose Postgres, volumes, backup
- [routing.md](routing.md) — how `history` reaches the planner
