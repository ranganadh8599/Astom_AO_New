"""Test MCP server registered on the LiteLLM gateway.

A small field-operations server used to exercise the *MCP* leg of the orchestrator:
discovery via ``/mcp-rest/tools/list`` and invocation via ``/mcp-rest/tools/call``,
both terminated by the gateway.

Every tool is read-only on purpose — the orchestrator refuses mutations, so a mutating
tool here would only ever prove the refusal path.

Run it (the gateway is containerised, so it must bind 0.0.0.0 and be addressed through
``host.docker.internal``):

    python -m mcp_field_ops.server --host 0.0.0.0 --port 9200

It serves the streamable-HTTP transport at ``/mcp``.
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

# Deterministic fixture data: the point is to prove routing, not to model reality.
ASSETS: dict[str, dict[str, str]] = {
    "PUMP-1042": {
        "site": "Rotterdam",
        "status": "in service",
        "health": "degraded",
        "note": "vibration above threshold since 14 Nov",
        "last_service": "2026-09-02",
    },
    "PUMP-2077": {
        "site": "Lyon",
        "status": "out of service",
        "health": "failed",
        "note": "seal failure, awaiting replacement part",
        "last_service": "2026-06-18",
    },
    "VALVE-3310": {
        "site": "Rotterdam",
        "status": "in service",
        "health": "nominal",
        "note": "no open issues",
        "last_service": "2026-10-11",
    },
}

INCIDENTS: dict[str, list[dict[str, str]]] = {
    "Rotterdam": [
        {
            "id": "INC-8841",
            "asset_id": "PUMP-1042",
            "severity": "medium",
            "summary": "Vibration alarm on pump seal",
            "opened": "2026-11-14",
        }
    ],
    "Lyon": [
        {
            "id": "INC-8790",
            "asset_id": "PUMP-2077",
            "severity": "high",
            "summary": "Pump seized during start-up",
            "opened": "2026-11-11",
        },
        {
            "id": "INC-8702",
            "asset_id": "PUMP-2077",
            "severity": "low",
            "summary": "Lubrication schedule overdue",
            "opened": "2026-10-30",
        },
    ],
}

MAINTENANCE: dict[str, list[dict[str, str]]] = {
    "PUMP-1042": [
        {"date": "2026-09-02", "type": "preventive", "summary": "Seal and bearing inspection"},
        {"date": "2026-03-14", "type": "corrective", "summary": "Coupling alignment"},
    ],
    "PUMP-2077": [
        {"date": "2026-06-18", "type": "preventive", "summary": "Full overhaul"},
    ],
    "VALVE-3310": [
        {"date": "2026-10-11", "type": "preventive", "summary": "Actuator calibration"},
    ],
}

server = MCPServer(
    name="field-ops-mcp",
    version="1.0.0",
    instructions=(
        "Read-only field operations data: equipment status, open incidents and "
        "maintenance history for industrial assets."
    ),
)


@server.tool(
    description=(
        "Look up the current status and health of an industrial asset by asset ID, "
        "for example PUMP-1042. Returns site, service status, health and the last "
        "service date."
    )
)
def get_asset_status(asset_id: str) -> str:
    key = asset_id.strip().upper()
    asset = ASSETS.get(key)
    if asset is None:
        known = ", ".join(sorted(ASSETS))
        return f"No asset found with ID {key}. Known asset IDs: {known}."
    return (
        f"Asset {key} at {asset['site']}: status is {asset['status']}, "
        f"health is {asset['health']}. Note: {asset['note']}. "
        f"Last service was {asset['last_service']}."
    )


@server.tool(
    description=(
        "List the open incidents for a site, such as Rotterdam or Lyon. Returns "
        "incident ID, severity, the affected asset and a summary."
    )
)
def list_open_incidents(site: str) -> str:
    key = site.strip().capitalize()
    incidents = INCIDENTS.get(key)
    if not incidents:
        known = ", ".join(sorted(INCIDENTS))
        return f"No open incidents recorded for {key}. Sites with incidents: {known}."
    lines = [
        f"{item['id']} ({item['severity']}) on {item['asset_id']}: "
        f"{item['summary']}, opened {item['opened']}"
        for item in incidents
    ]
    return f"Open incidents at {key}: " + "; ".join(lines) + "."


@server.tool(
    description=(
        "Show the maintenance history for an industrial asset by asset ID, such as "
        "PUMP-1042. Returns past service dates, service type and work performed."
    )
)
def get_asset_maintenance_history(asset_id: str) -> str:
    key = asset_id.strip().upper()
    history = MAINTENANCE.get(key)
    if not history:
        known = ", ".join(sorted(MAINTENANCE))
        return f"No maintenance history for {key}. Assets with history: {known}."
    lines = [
        f"{item['date']} {item['type']}: {item['summary']}" for item in history
    ]
    return f"Maintenance history for {key}: " + "; ".join(lines) + "."


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the field-ops MCP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9200)
    args = parser.parse_args()

    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        # Stateless + JSON responses: every gateway call is self-contained, so a
        # dropped container connection cannot leave the proxy holding a dead session.
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
