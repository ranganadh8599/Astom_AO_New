# MCP example suite — 20 servers for retrieval testing

Twenty MCP servers, each a **read-only lookup over a small deterministic fixture**. Domains
are chosen to be unrelated to each other and to the A2A suite, so a retrieval result can only
be explained by the card text — no two servers share a vocabulary.

Every tool is read-only on purpose: the orchestrator refuses mutations, so a write tool here
would only ever exercise the refusal path.

| # | Server id | Port | Tools | Try asking |
|---|---|---|---|---|
1 | `warehouse-inventory` | 9301 | `get_stock_level`, `list_below_reorder` | how many SKU-4471 do we have? |
2 | `payroll-payslips` | 9302 | `get_payslip`, `get_deductions` | what was E-1042's net pay? |
3 | `flight-status` | 9303 | `get_flight_status`, `get_departure_gate` | is BA2490 delayed? |
4 | `hotel-availability` | 9304 | `check_availability`, `cheapest_room` | any rooms free on 2026-12-03? |
5 | `library-catalogue` | 9305 | `find_by_isbn`, `is_available` | is 9780262033848 on the shelf? |
6 | `lab-sample-tracking` | 9306 | `get_sample_status`, `is_result_released` | has LAB-2026-0418 been resulted? |
7 | `fleet-telematics` | 9307 | `get_vehicle_status`, `list_vehicles_with_faults` | which vehicles have fault codes? |
8 | `clinic-appointments` | 9308 | `list_free_slots`, `next_free_slot` | free cardiology slots on 2026-11-24? |
9 | `support-queue` | 9309 | `get_ticket`, `list_breached_tickets` | which tickets breached SLA? |
10 | `fx-rates` | 9310 | `get_rate`, `convert` | convert 500 EUR to GBP |
11 | `subscription-billing` | 9311 | `get_subscription`, `list_renewals_before` | when does ACC-7781 renew? |
12 | `crop-harvest` | 9312 | `get_field_harvest`, `compare_yields` | yield for FIELD-07-2026? |
13 | `water-quality` | 9313 | `get_water_reading`, `list_out_of_spec` | is PLANT-EAST within limits? |
14 | `parcel-tracking` | 9314 | `track_parcel`, `latest_scan` | where is CN-8842-1180? |
15 | `meeting-rooms` | 9315 | `get_room`, `find_free_room` | which room seats 12 at 11:00? |
16 | `bridge-inspection` | 9316 | `get_bridge_inspection`, `list_bridges_above_severity` | severity of BR-0207? |
17 | `customs-tariff` | 9317 | `classify_product`, `get_duty_rate` | duty rate for cotton t-shirts? |
18 | `course-completions` | 9318 | `get_training_records`, `list_expiring_before` | what expires before 2026-12-01? |
19 | `parking-occupancy` | 9319 | `get_occupancy`, `find_accessible_bays` | accessible bays at PARK-RIVERSIDE? |
20 | `cold-chain-temperature` | 9320 | `get_temperature_log`, `list_excursions` | any cold-chain excursions? |

Ports are contiguous in catalog order, so the table and the loops below stay in step.

## Run one

```powershell
pip install -e ".[mcp-server]"
python -m mcp_suite.servers.warehouse_inventory --port 9301
```

Each server serves the streamable-HTTP transport at `/mcp`, stateless, with JSON responses —
so a dropped connection cannot leave the gateway holding a dead session.

Run everything (one process per server):

```powershell
$env:PYTHONPATH = "examples"
python -c "from mcp_suite.catalog import SERVERS; [print(s.id, s.port) for s in SERVERS]" |
    ForEach-Object {
        $id, $port = $_ -split '\s+'
        if ($id) {
            Start-Process python -ArgumentList "-m","mcp_suite.servers.$($id.Replace('-','_'))",
                "--port",$port -WindowStyle Hidden
        }
    }
```

## Register with the gateway

The server name in the gateway is the catalog id — **use the id, not the title**, because
grants are by name and search results are prefixed with it.

```powershell
$admin = @{ Authorization = "Bearer $env:LITELLM_ADMIN_KEY"; "Content-Type" = "application/json" }
python -c "from mcp_suite.catalog import SERVERS; [print(s.id, s.port) for s in SERVERS]" |
    ForEach-Object {
        $id, $port = $_ -split '\s+'
        if ($id) {
            $body = @{
                server_name = $id
                transport   = "http"
                url         = "http://host.docker.internal:$port/mcp"
            } | ConvertTo-Json
            Invoke-RestMethod -Method Post -Uri "$env:LITELLM_BASE_URL/v1/mcp/server" -Headers $admin -Body $body
        }
    }
```

`host.docker.internal` is required when the gateway runs in a container; use `127.0.0.1` if
it runs on the host. Registration is safe to repeat — a duplicate alias is rejected with
`400 An MCP server with alias X already exists` rather than stacking.

Then grant the servers to the orchestrator's key. Team first, then key; a key-only grant is
rejected with `Key requests MCP servers not allowed by team`:

```powershell
$names = python -c "from mcp_suite.catalog import SERVERS; print(','.join(s.id for s in SERVERS))"
$payload = @{
    key = $env:LITELLM_VIRTUAL_KEY
    object_permission = @{
        mcp_servers = $names.Split(',')
        mcp_tool_search_enabled = $true
    }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "$env:LITELLM_BASE_URL/key/update" -Headers $admin -Body $payload
```

Verify with the virtual key:

```powershell
Invoke-RestMethod "$env:LITELLM_BASE_URL/mcp-rest/tools/list" -Headers @{
    Authorization = "Bearer $env:LITELLM_VIRTUAL_KEY"
}
```

## Notes for retrieval testing

- **Tool search must be on** for ranking: `mcp_tool_search_enabled: true` on the key. It is
  DB-backed, so `/key/update` applies without a restart.
- **The gateway's tool search needs all three settings right.** `GET/PATCH
  /get|/update/mcp_tool_search_settings` holds `embedding_model`, `top_k` and
  `similarity_threshold`. Measured on this 40-tool suite:

  | Setting | Effect |
  |---|---|
  `embedding_model` unset | falls back to keyword matching: "is BA2490 delayed?" matched nothing, because the query shares no word with the description |
  `top_k` below the orchestrator's `RETRIEVAL_TOP_K` | the global value is the ceiling, so valid tools never reach the gate |
  `similarity_threshold: 0.0` | results come back effectively unordered (insertion order), not "unfiltered but ranked" |
  `similarity_threshold: 0.2` | the value the shipped suite is measured with |

  `PATCH` **replaces** the settings object, so resend `embedding_model` every time —
  omitting it silently switches the gateway to keyword mode.

  Working values: `{"embedding_model": "openai/text-embedding-3-small", "top_k": 10,
  "similarity_threshold": 0.2}`.
- **Each `server_name` is hyphen-free.** Catalog ids like `warehouse-inventory` are rejected
  with `Server name cannot contain '-'`; register as `warehouse_inventory`. Grants are by
  name, so changing it later breaks access.
- **Check the cached tool list per server**, not just reachability:
  `/mcp-rest/tools/list?server_id=<name>`. A stale cache showed one server exposing another
  server's tools; `PUT /v1/mcp/server` with the same `server_id` forces a re-fetch.
- **Search returns `server-tool` prefixed names**, so two servers can share a verb without
  ambiguity — but keep them distinct anyway; it makes the expected answer obvious.
- **Distance between domains is the point.** If a query lands on the wrong server, the card
  text is the cause; adjust the description rather than tuning a threshold, because the
  orchestrator deliberately applies no local score cutoff.
- **Missing arguments fail locally.** Each tool declares typed parameters; the planner must
  supply them, and the orchestrator validates against `inputSchema` before the call leaves.

## Smoke-test one server by hand

```powershell
python -c "from mcp_suite.servers.warehouse_inventory import get_stock_level; print(get_stock_level('SKU-4471'))"
```

## Layout

```
mcp_suite/
  catalog.py        ids, names, ports, descriptions - one row per server
  common.py         Tool, build_server(), run() - argparse and the streamable-HTTP transport
  servers/          20 modules, each with typed tool functions and a SERVER
```

Adding a server means adding a catalog row and a module; `common.py` supplies everything
else.
