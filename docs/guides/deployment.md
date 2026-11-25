# Deployment: containers

Three images, one compose file. The orchestration layer, its Postgres, and the two
reference backends are separate containers with separate images, because they have
different lifetimes, different dependency trees and different owners.

| Image | Dockerfile | Size | Contains |
|---|---|---|---|
`a2a-orchestrator` | `deploy/Dockerfile` | ~410 MB | FastAPI + LangGraph + psycopg, runs `python -m orchestrator` |
`a2a-mcp-field-ops` | `deploy/Dockerfile.mcp-field-ops` | ~255 MB | only `mcp`, runs the fixture MCP server |
`a2a-ronaldo-agent` | `deploy/Dockerfile.ronaldo-agent` | ~221 MB | only `fastapi` + `uvicorn`, runs the reference A2A agent |

Splitting them is not cosmetic. Putting LangGraph in the image that serves a 150-line MCP
fixture means rebuilding the orchestration image every time the fixture changes, and
shipping a gateway credential to a container that never calls the gateway.

## Quick start

```powershell
# required: the two secrets compose cannot invent
$env:LITELLM_API_KEY  = "sk-..."   # the orchestrator's scoped virtual key
$env:ORCH_SHARED_KEY  = "..."      # what LibreChat sends as apiKey, min 32 chars

docker compose up -d --build
docker compose ps
curl -s localhost:8001/health | jq
```

Expected:

```
db           | Up (healthy)
field-ops    | Up (healthy)
orchestrator | Up (healthy)
ronaldo-agent| Up (healthy)

{"status":"ok", "gateway":"http://litellm:4000", "memory":"postgres",
 "memory_state":{"backend":"postgres","reachable":true}, "models":{"status":"ok"}}
```

## The gateway is not in this compose file

`litellm-gateway-litellm-1` is already running as its own compose project and it owns the
agent registry, the MCP registry, the virtual keys and the model list. A second gateway
would mean two sources of truth for "what can be routed to".

So the orchestrator joins the gateway's network instead. **Option A (default)**:

```yaml
networks:
  gateway:
    external: true
    name: litellm-gateway_default      # verify: docker network ls | grep litellm
```

The orchestrator then uses `LITELLM_BASE_URL=http://litellm:4000`, and the gateway can
reach `field-ops:9200` and `ronaldo-agent:9103` by name without leaving the bridge.

**Option B**, when the gateway is not on a shared network:

```yaml
environment:
  LITELLM_BASE_URL: http://host.docker.internal:4001
```

`extra_hosts: host.docker.internal:host-gateway` is already set on the orchestrator so
this also works on plain Linux, not only Docker Desktop.

### Why `GATEWAY_URL`, not `LITELLM_BASE_URL`, on the left-hand side

`docker compose` reads the project `.env` for `${...}` substitution — and that file is
written for a process running **on the host**, where the gateway is `localhost:4001`.
Interpolating it directly puts a loopback address inside the container, where it can only
fail. This was observed, not theorised:

```
LITELLM_BASE_URL=http://localhost:4001        # inherited from .env
{"models":{"status":"degraded",
 "warnings":["could not verify model 'openai/gpt-4o-mini'
             (All connection attempts failed)"]}}
```

Hence `GATEWAY_URL` as the container-facing input:

```yaml
LITELLM_BASE_URL: ${GATEWAY_URL:-http://litellm:4000}
```

Override it only when the gateway is somewhere else; never let the host's value through.

## Re-registration: the step people miss

Containerising changes the address the **gateway** must dial, and the gateway stores that
address in its database. Publishing a port is not enough — the registry has to be updated.

```powershell
$admin = "<LITELLM_ADMIN_KEY>"

# MCP server: host.docker.internal -> field-ops
$sid = (curl -s localhost:4001/v1/mcp/server -H "Authorization: Bearer $admin" |
        jq -r '.[0].server_id')
curl -X PUT localhost:4001/v1/mcp/server -H "Authorization: Bearer $admin" `
  -H "Content-Type: application/json" `
  -d "{`"server_id`":`"$sid`",`"server_name`":`"field_ops`",`"transport`":`"http`",`"url`":`"http://field-ops:9200/mcp`"}"

# A2A agent: card url must match, or the fetched card advertises an unreachable address
curl -X PATCH localhost:4001/v1/agents/<agent_id> -H "Authorization: Bearer $admin" `
  -H "Content-Type: application/json" `
  -d '{"agent_card_params":{"url":"http://ronaldo-agent:9103"}}'
```

`PUT` on the MCP server requires `server_id` in the body; without it the gateway answers
`{"detail":[{"type":"missing","loc":["body","server_id"]}]}`.

`RONALDO_AGENT_URL` sets the `url` the agent's own card advertises. It must be what the
gateway can resolve — `http://ronaldo-agent:9103` in this stack — not `localhost`.

## Health checks are per-service, deliberately

| Service | Check | Why not the obvious one |
|---|---|---|
orchestrator | `GET /ready` | `/health` is liveness and stays 200 while the database is unreachable, so it cannot pull a broken instance out of rotation. `/ready` probes the checkpointer. |
field-ops | TCP connect to 9200 | `GET /mcp` is a **streamable** transport: it answers 200 and holds the connection open, so `curl` never exits and the check times out. Observed as `health: starting` forever. |
ronaldo-agent | `GET /.well-known/agent-card.json` | That is the one thing an A2A peer needs to work. |
db | `pg_isready -d orchestrator` | Without `-d`, `pg_isready` reports ready before the application database exists. |

## Persistence

`pgdata` is a named volume. Conversations survive `docker compose down` and
`restart`; they do **not** survive `down -v`.

```powershell
docker compose exec db psql -U postgres -d orchestrator -c "\dt"
docker compose exec db psql -U postgres -d orchestrator `
  -c "select thread_id, count(*) from checkpoints group by thread_id order by 2 desc;"
```

Verified in this stack: a turn before `docker compose restart orchestrator`, a follow-up
after it, and the pronoun resolved from state written by the previous container.

**Backup / restore:**

```powershell
docker compose exec -T db pg_dump -U postgres orchestrator > orchestrator.sql
docker compose exec -T db psql -U postgres -d orchestrator < orchestrator.sql
```

## Secrets

Nothing secret is in an image. `.dockerignore` excludes `.env` and `*.env`, so a stray
`docker build .` cannot bake credentials in. Secrets arrive as environment variables at
run time; `LITELLM_API_KEY` is marked required in compose (`:?`) so a missing value stops
the stack instead of starting a container that fails every call.

`LITELLM_ADMIN_KEY` is deliberately **absent**: it is CLI-only (onboarding), and the
running orchestrator has no code path that reads it. Keeping it out means a compromised
container cannot mint keys or rewrite agent registrations.

## Single-container runs

```powershell
docker build -t a2a-orchestrator:0.1.0 .
docker run --rm -p 8001:8001 `
  -e LITELLM_BASE_URL=http://host.docker.internal:4001 `
  -e LITELLM_API_KEY=sk-... `
  -e PLANNER_MODEL=openai/gpt-4o-mini `
  -e AUTH_MODE=shared_key -e ORCH_SHARED_KEY=... `
  -e CHECKPOINT_BACKEND=postgres `
  -e POSTGRES_DSN=postgresql://postgres:admin@db:5432/orchestrator `
  --add-host host.docker.internal:host-gateway `
  a2a-orchestrator:0.1.0
```

To run without Postgres, set `CHECKPOINT_BACKEND=memory` and drop `POSTGRES_DSN`.
Conversations are then lost when the container stops.

## The example suites as containers

Twenty A2A agents (9110-9129) and twenty MCP servers (9301-9320), one container each, from
one image. Useful when you want the routing tests to exercise the gateway the way it runs
in production — by service name on a shared network, not back to the host.

| File | Purpose |
|---|---|
`deploy/Dockerfile.examples` | one image for both suites (`a2a-examples:0.1.0`, ~240 MB) |
`docker-compose.suites.yml` | **generated**: 40 services, one per catalogue entry |
`deploy/gen_suites_compose.py` | renders the compose file from `examples/*/catalog.py` |
`deploy/register_examples.py` | repoints the gateway registry at the containers and grants |
`deploy/healthcheck_suites.py` | kind-aware probe (A2A card vs MCP TCP) |

```powershell
docker build -f deploy/Dockerfile.examples -t a2a-examples:0.1.0 .
docker compose -f docker-compose.suites.yml up -d
docker compose -f docker-compose.suites.yml ps

.\.venv\Scripts\python.exe deploy/register_examples.py --dry-run --grant   # plan
.\.venv\Scripts\python.exe deploy/register_examples.py --grant            # apply + verify
```

### Why one image for 40 services

Every service is the same code with a different `python -m ...` and port, and all three
dependencies (`fastapi`, `uvicorn`, `mcp`) are shared. Building 40 images would multiply
build time and disk for no isolation gain — the processes are separate containers anyway.

### The compose file is generated, on purpose

Forty near-identical blocks drift from the catalogues. A renamed agent or a shifted port
would leave a container the gateway was never told about, and the symptom is silence. So
`examples/*/catalog.py` is the source of truth:

```powershell
.\.venv\Scripts\python.exe deploy/gen_suites_compose.py           # regenerate
.\.venv\Scripts\python.exe deploy/gen_suites_compose.py --check   # CI: fail if stale
```

`tests/examples/test_suites_compose.py` asserts the shipped file matches the catalogues,
that every port is unique, and that no card advertises `localhost`.

### Addresses: the part that has to be right

The gateway dials the **service name**, so each A2A card advertises
`http://a2a-<id>:<port>` (`--url`, which rewrites `url` and `provider.url`) and each MCP
server is registered as `http://mcp-<id>:<port>/mcp`.

The suites join the gateway's own network, declared external:

```yaml
networks:
  gateway:
    external: true
    name: ${GATEWAY_NETWORK:-litellm-gateway_default}
```

Nothing is published to the host by default. If you want to poke one service from the
host, add `ports: ["9110:9110"]` to it — but do not publish all 40, or they collide with a
host-run suite.

### Registration repoints, it does not duplicate

`register_examples.py` reads the registry first: a target already pointing at the container
URL is left alone, one pointing elsewhere (typically `host.docker.internal:<port>` from a
host run) is updated, and a missing one is created. Then it **unions** the ids into the team
and key grants, so `ronaldo-agent` and `field_ops` survive. Finally it verifies with the
*virtual* key — `GET /v1/agents` plus one `/mcp-rest/tools/list` per server — because that
is the view the orchestrator actually gets.

```powershell
.\.venv\Scripts\python.exe deploy/register_examples.py --verify-only   # no writes
```

MCP server names replace `-` with `_` (`warehouse_inventory`): the gateway rejects a hyphen
in `server_name`, and grants are by name.

### Switching back to host-run suites

Re-register with the host form, then stop the containers:

```powershell
.\.venv\Scripts\python.exe deploy/register_examples.py `
  --a2a-host localhost --mcp-host host.docker.internal
docker compose -f docker-compose.suites.yml down
```

## Why the entry point is `python -m orchestrator`

The image does not use the plain `uvicorn` CLI. `uvicorn.run()` hard-codes
`ProactorEventLoop` on Windows and ignores the loop policy, which psycopg refuses for
async connections. `python -m orchestrator` passes `loop_factory` explicitly. On Linux the
factory is left unset, so behaviour there is unchanged — but the image uses the same
command everywhere, so the documented invocation cannot drift from the tested one.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
`models.status: degraded`, `All connection attempts failed` | `LITELLM_BASE_URL` is a loopback address inside the container | use `GATEWAY_URL=http://litellm:4000` or `host.docker.internal:4001` |
`memory.reachable: false`, `/ready` 503 | database unreachable, or DSN points at another database | `docker compose logs db`; check `POSTGRES_DSN` names `orchestrator` |
`field-ops health: starting` forever | healthcheck waits for a stream to close | already fixed: TCP check, not HTTP |
`ModuleNotFoundError: psycopg` at boot | built without the `[postgres]` extra | the `deploy/Dockerfile` requests `a2a-orchestrator[postgres]` at install time |
gateway returns `agent_search_not_configured` | `litellm_settings.agent_search_embedding_model` not set in the gateway's config | orchestrator falls back to listing; see README |
turns fail with `429` | upstream provider burst limit | the planner retries with 1/2/4/8s backoff; persistent 429 is reported with the status |
`no configuration file provided` | ran `docker compose` outside the project directory | `cd` to the repo root, or use `-f` |
