# A2A Orchestration Layer (POC)

LibreChat → **orchestrator** → **LiteLLM gateway** → external **A2A agents** and **MCP tools**.

LiteLLM is the single gateway. The orchestrator never calls an agent or an MCP server
directly and never holds the master key: discovery, planning, agent calls and tool calls
are all HTTP calls to the gateway with one scoped virtual key. The orchestrator is
**read-only**: a request to create, change or delete something is declined with an
explanation. There is no human-in-the-loop path and no approval workflow.

```
validate_input → retrieve_targets → check_coverage ─┬─(no match / smalltalk / write)→ answer, END
                                                    └─→ plan_tasks ─┬─→ run_task (a2a agent) ─┐
                                                                    ├─→ run_task (mcp tool)  ─┼─→ compose_answer → END
                                                                    └─→ run_task (a2a agent) ─┘
```

| Node | One job |
|---|---|
| `validate_input` | input shape and limits; clears per-turn state |
| `retrieve_targets` | builds search queries from the message and history, then asks the gateway which agents / tools are relevant |
| `check_coverage` | one LLM call: can anything answer this at all, and is it a read or a write? |
| `plan_tasks` | the planner picks targets and splits the message into tasks |
| `run_task` | calls one agent or tool through the gateway (tasks run in parallel) |
| `compose_answer` | builds the reply from the results deterministically, no model call |

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env       # set LITELLM_BASE_URL, LITELLM_API_KEY, PLANNER_MODEL
.\.venv\Scripts\python.exe -m orchestrator.admin.cli "how many annual leave days do I get?"
.\.venv\Scripts\python.exe -m orchestrator --port 8000      # serve it for LibreChat
```

Containers (orchestrator + Postgres + the two sample backends): `docker compose up -d --build`.
See [docs/guides/deployment.md](docs/guides/deployment.md).

All 40 example agents/servers as containers (one image, 40 services):
`docker compose -f docker-compose.suites.yml up -d`, then
`python deploy/register_examples.py --grant`. See
[deployment.md § the example suites as containers](docs/guides/deployment.md#the-example-suites-as-containers).

Step-by-step for a new user — start, authenticate, call, Postman, and registering agents,
MCP servers and models: [docs/guides/user-guide.md](docs/guides/user-guide.md).

```powershell
curl -X POST http://localhost:8000/v1/orchestrate `
  -H "Authorization: Bearer $env:ORCH_TOKEN" -H "Content-Type: application/json" `
  -d '{"message":"leave days and expense status?","conversation_id":"conv-1"}'
```

`python -m orchestrator` is a thin uvicorn wrapper that supplies the asyncio event loop.
Use it when `CHECKPOINT_BACKEND=postgres`: on Windows the plain `uvicorn` CLI hard-codes a
loop that psycopg refuses.

## Repository layout

```
src/orchestrator/          the product
  api/                     FastAPI app and routes
  auth/                    token / shared-key validation, UserContext
  gateway/                 the only module that talks to LiteLLM (client.py, models.py)
  routing/                 how a target is chosen
    target_catalog.py        what is registered; retrieval, retries, fallbacks
    query_builder.py         message + history -> standalone search queries
    rank_fusion.py           merges one ranked list per query
    coverage_gate.py         "can anything answer this?" and read/write intent
    read_only_policy.py      the refusal for write requests
    smalltalk.py             greetings and "what can you do?"
  graph/                   the LangGraph pipeline (build.py wires nodes.py), state, checkpointer
  observability/           trace context shared with LibreChat and LiteLLM, Langfuse tracer
  admin/                   operator commands: agent onboarding, one-shot CLI
  config.py  service.py    settings; the object the API calls
examples/                  sample agents and MCP servers
  ronaldo_agent/             single A2A agent: card, fact base, server
  mcp_field_ops/             single MCP server: three read-only tools
  a2a_suite/                 20 A2A agents on disjoint topics (ports 9110-9129)
  mcp_suite/                 20 MCP servers of lookup tools (ports 9301-9320)
evals/                     retrieval + gate scoring against a labelled question set
deploy/                    Dockerfiles (docker-compose.yml stays at the root)
  Dockerfile.examples        one image for all 40 example agents/MCP servers
  gen_suites_compose.py      renders docker-compose.suites.yml from the catalogues
  register_examples.py       repoints the gateway registry at the containers, then grants
docs/                      architecture/  decisions/  guides/  postman/
tests/                     one folder per area, mirroring src/
```

## Configuration

See [.env.example](.env.example). The settings that matter most:

- `LITELLM_BASE_URL` / `LITELLM_API_KEY`: the only gateway the orchestrator knows.
- `LITELLM_ADMIN_KEY`: optional, read only by `python -m orchestrator.admin.onboarding`. The runtime never uses it.
- `PLANNER_MODEL`: required. Routing happens only here; there is no local fallback.
- `RETRIEVAL_TOP_K`, `QUERY_REWRITE_*`, `SEARCH_RETRIES`: how candidates are found (see below).
- `COVERAGE_GATE_ENABLED` (legacy name `RELEVANCE_GATE_ENABLED` still works), `GATE_MODEL`.
- `READ_ONLY_MODE`: the planner refuses mutating requests.
- `CHECKPOINT_BACKEND`: `memory` (default) or `postgres`.
- `LANGFUSE_*`: leave the keys blank to run untraced. `LANGFUSE_ENVIRONMENT` is validated at boot.
- `AUTH_MODE`: `dev`, `shared_key` or `entra` ([docs/guides/sso-integration.md](docs/guides/sso-integration.md)).

## How a target is chosen

Ranking lives in the gateway (`GET /v1/agents?query=` and `mcp_tool_search`); the orchestrator
never scores candidates itself. Around that:

- **Standalone queries.** A follow-up ("and in 2016?") is rewritten from the recent
  conversation, and a message with several questions is searched once per question, then
  merged by reciprocal rank fusion. One cheap model call, only when the message needs it;
  any failure falls back to the raw message.
- **Resilient search.** A transient search error is retried, then the turn is listed
  without search for that turn only. Only "search is not configured" switches search off.
- **A coverage gate before the planner.** Measured 7/7 rejection of irrelevant queries vs
  2/7 for the planner alone ([ADR 0001](docs/decisions/0001-coverage-gate-before-planning.md)).
  There is no relevance-score threshold ([ADR 0002](docs/decisions/0002-no-relevance-score-threshold.md)).

Detail: [docs/architecture/routing.md](docs/architecture/routing.md). To measure it on your own
agents, build a labelled question set and run the evaluation:

```powershell
Copy-Item evals/golden.example.jsonl evals/golden.jsonl     # then edit it
.\.venv\Scripts\python.exe evals/run_retrieval_eval.py --golden evals/golden.jsonl
```

See [evals/README.md](evals/README.md).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Everything runs against an in-process fake gateway, so no gateway, agent or MCP server is
needed. Postgres tests are skipped unless `TEST_DATABASE_URL` is set.

## Known gap: per-user entitlement

Authentication is per user; **authorization is not**. Every request carries one virtual key,
so LiteLLM cannot tell callers apart: every registered agent is reachable by every user.
Because the orchestrator is read-only, entitlement is the only control over what data a user
can read. Options and costs: [docs/architecture/authorization.md](docs/architecture/authorization.md)
and [docs/guides/entitlement-design.md](docs/guides/entitlement-design.md).

## Documentation

Start at [docs/README.md](docs/README.md): architecture deep dives, decision records,
how-to guides (deployment, onboarding an agent, SSO, key scoping) and the Postman suite.
