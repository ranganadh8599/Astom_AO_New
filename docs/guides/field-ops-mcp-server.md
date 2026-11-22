# The field-ops MCP server (sample)

`examples/mcp_field_ops/` is a read-only MCP server used to exercise the MCP leg end to end.
It has three tools (`get_asset_status`, `list_open_incidents`, `get_asset_maintenance_history`),
serves streamable HTTP at `/mcp`, and is stateless, so gateway calls never depend on a session
the proxy might have dropped.

```powershell
pip install -e ".[mcp-server]"
python -m mcp_field_ops.server --host 0.0.0.0 --port 9200
```

(`examples/` is on the path when you run from the repository root with `PYTHONPATH=examples`;
the container image sets it for you.)

## Register it on the gateway

Note `host.docker.internal`, not `localhost`: the proxy runs in a container. If LiteLLM runs
on the host, use `127.0.0.1` instead.

```powershell
curl -X POST http://localhost:4001/v1/mcp/server `
  -H "Authorization: Bearer $env:LITELLM_ADMIN_KEY" `
  -H "Content-Type: application/json" `
  -d '{"server_name":"field_ops","transport":"http","url":"http://host.docker.internal:9200/mcp"}'
```

## Let the orchestrator's key use it

A key inherits its team's allowlist, so grant the team first. Otherwise `object_permission`
on the key is rejected with `Key requests MCP servers not allowed by team`.

```powershell
$admin = @{ Authorization = "Bearer $env:LITELLM_ADMIN_KEY"; "Content-Type" = "application/json" }
$body  = '{"team_id":"<team-id>","object_permission":{"mcp_servers":["field_ops"]}}'
Invoke-RestMethod -Method POST -Uri http://localhost:4001/team/update -Headers $admin -Body $body

$body = '{"key":"<virtual-key>","object_permission":{"mcp_servers":["field_ops"]}}'
Invoke-RestMethod -Method Post -Uri http://localhost:4001/key/update -Headers $admin -Body $body
```

## Verify both surfaces resolve for the same key

```powershell
curl -s http://localhost:4001/v1/agents            -H "Authorization: Bearer $env:LITELLM_API_KEY"
curl -s http://localhost:4001/mcp-rest/tools/list  -H "Authorization: Bearer $env:LITELLM_API_KEY"
```

No code or config change is needed after registration: the next discovery pass picks the
tools up. `GET /v1/capabilities` on the orchestrator shows what it found.
