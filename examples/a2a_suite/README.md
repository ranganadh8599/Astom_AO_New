# A2A example suite — 20 agents for retrieval testing

Twenty A2A agents on **deliberately unrelated topics**. The suite exists to test routing:
if two cards overlapped, a correct routing decision could not be distinguished from a lucky
one, so every domain here is disjoint.

Answers are deterministic keyword matches over a small fact base — no model call, no cost,
same reply every time. An out-of-scope question is refused explicitly, so a test can tell
"wrong agent chosen" from "right agent, wrong answer".

| # | Agent id | Port | Topic | Try asking |
|---|---|---|---|---|
1 | `bicycle-repair` | 9110 | drivetrain, brakes, wheels | how do I check chain wear? |
2 | `sourdough-baking` | 9111 | starter, bulk, bake | how long should bulk fermentation take? |
3 | `night-sky-astronomy` | 9112 | constellations, planets, seeing | which constellations are visible in winter? |
4 | `bird-migration` | 9113 | flyways, timing, navigation | what is a flyway? |
5 | `chess-openings` | 9114 | principles, 1.e4, 1.d4 | what is the idea behind the Sicilian Defence? |
6 | `knitting` | 9115 | gauge, stitches, finishing | how do I fix my stitch gauge? |
7 | `wine-pairing` | 9116 | principles, whites, reds | what wine goes with steak? |
8 | `electrical-safety` | 9117 | RCDs, earthing, isolation | how do I prove a circuit is dead? |
9 | `volcano-geology` | 9118 | eruption styles, hazards, monitoring | what is a lahar? |
10 | `calligraphy` | 9119 | scripts, tools, practice | which nib should I use for italic? |
11 | `jazz-improvisation` | 9120 | harmony, scales, vocabulary | how do I solo over a ii-V-I? |
12 | `marathon-training` | 9121 | periodisation, long runs, taper | how long should my longest run be? |
13 | `container-stowage` | 9122 | lashing, weight, dangerous goods | what is verified gross mass? |
14 | `beekeeping` | 9123 | seasons, swarms, harvest | how often should I inspect for swarm cells? |
15 | `legal-citation` | 9124 | cases, statutes, secondary | how do I cite a journal article? |
16 | `api-versioning` | 9125 | strategy, deprecation, compatibility | when is an API change breaking? |
17 | `photography-exposure` | 9126 | triangle, metering, depth of field | what does one stop mean? |
18 | `wilderness-first-aid` | 9127 | hypothermia, fractures, evacuation | how do I splint a broken leg? |
19 | `tea-ceremony` | 9128 | procedure, utensils, seasonality | what is a chasen for? |
20 | `railway-signalling` | 9129 | block, interlocking, aspects | what is absolute block working? |

The same list is available at runtime:

```powershell
python -m a2a_suite.server --list
```

## Run one

```powershell
# Gateway on the host:
python -m a2a_suite.server --agent bicycle-repair --port 9110

# Gateway in Docker: advertise the container-reachable URL, or the card is unusable
python -m a2a_suite.server --agent bicycle-repair --port 9110 --url http://host.docker.internal:9110
```

`--url` (or the `A2A_AGENT_URL` environment variable) rewrites the card's `url` and
`provider.url`. The card must report the URL the **gateway** will call, not the one your
browser uses — `localhost` in a card is the classic "works locally, 500s in the gateway" bug.

Run everything (one process per agent, from the repository root):

```powershell
$env:PYTHONPATH = "examples"
9110..9129 | ForEach-Object {
    Start-Process python -ArgumentList "-m","a2a_suite.server","--port","$_",
        "--url","http://host.docker.internal:$_" -WindowStyle Hidden
}
```

Stop them all with `Get-Process python | Stop-Process`.

## Check a card before registering

```powershell
Invoke-RestMethod http://localhost:9110/.well-known/agent-card.json | ConvertTo-Json -Depth 6
```

The card carries `name`, a non-empty `description`, a matching `url` and three `skills` with
`id`, `name` and `description` — exactly what `validate_card()` in the onboarding tool
requires.

## Register with the gateway

The gateway needs the admin key; the runtime never sees it.

```powershell
$admin = @{ Authorization = "Bearer $env:LITELLM_ADMIN_KEY"; "Content-Type" = "application/json" }
9110..9129 | ForEach-Object {
    $card = Invoke-RestMethod "http://localhost:$($_)/.well-known/agent-card.json"
    $body = @{ agent_name = $card.name; agent_card_params = $card } | ConvertTo-Json -Depth 12
    Invoke-RestMethod -Method Post -Uri "$env:LITELLM_BASE_URL/v1/agents" -Headers $admin -Body $body
}
```

Then grant them to the orchestrator's key — team first, then key, remembering that an
explicit `agents` list makes unlisted agents invisible:

```powershell
$ids = (Invoke-RestMethod "$env:LITELLM_BASE_URL/v1/agents" -Headers $admin).agent_id
$body = @{ key = $env:LITELLM_VIRTUAL_KEY; object_permission = @{ agents = $ids } } |
    ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "$env:LITELLM_BASE_URL/key/update" -Headers $admin -Body $body
```

Verify with the **virtual** key, not `/key/info` — only `GET /v1/agents` shows what the
runtime will actually discover:

```powershell
Invoke-RestMethod "$env:LITELLM_BASE_URL/v1/agents" -Headers @{
    Authorization = "Bearer $env:LITELLM_VIRTUAL_KEY"
} | Measure-Object
```

## Smoke-test one agent directly

```powershell
curl -s -X POST http://localhost:9110/ -H "Content-Type: application/json" -d '{
  "jsonrpc": "2.0", "id": "1", "method": "message/send",
  "params": {"message": {"messageId": "m1", "role": "user",
             "parts": [{"kind": "text", "text": "how do I check chain wear?"}]}}}'
```

## Layout

```
a2a_suite/
  catalog.py        ids, names, ports, descriptions - one row per agent
  spec.py           AgentSpec/Skill, the card builder and the keyword matcher
  server.py         one generic FastAPI app + CLI (--agent, --port, --url, --list)
  agents/           20 modules, each exporting SPEC
```

Adding an agent means adding a catalog row and a module with three skills — the server,
card and CLI need no changes.
