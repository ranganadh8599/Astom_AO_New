"""Parcel tracking MCP server: scan events per consignment."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

CONSIGNMENTS: dict[str, dict[str, object]] = {
    "CN-8842-1177": {
        "depot": "Leipzig hub",
        "promised": "2026-11-23",
        "events": [
            "2026-11-20 18:02 collected from sender",
            "2026-11-21 03:44 arrived at Leipzig hub",
            "2026-11-21 09:10 sorted for onward linehaul",
        ],
    },
    "CN-8842-1180": {
        "depot": "Rotterdam depot",
        "promised": "2026-11-22",
        "events": [
            "2026-11-20 15:30 collected from sender",
            "2026-11-21 07:20 out for delivery",
        ],
    },
    "CN-8842-1193": {
        "depot": "awaiting collection",
        "promised": "2026-11-25",
        "events": ["2026-11-21 11:05 label created, not yet in network"],
    },
}


def track_parcel(consignment: str) -> str:
    """Report current depot, promised date and the full scan history."""
    key = consignment.strip().upper()
    row = CONSIGNMENTS.get(key)
    if row is None:
        known = ", ".join(sorted(CONSIGNMENTS))
        return f"No consignment {key}. Tracked consignments: {known}."
    return (
        f"{key} is at {row['depot']}, promised for {row['promised']}. "
        f"Scans: " + "; ".join(row["events"]) + "."
    )


def latest_scan(consignment: str) -> str:
    """Return only the most recent scan event for a consignment."""
    key = consignment.strip().upper()
    row = CONSIGNMENTS.get(key)
    if row is None:
        known = ", ".join(sorted(CONSIGNMENTS))
        return f"No consignment {key}. Tracked consignments: {known}."
    events = row["events"]
    latest = events[-1] if events else "no scans recorded"
    return f"Latest scan for {key}: {latest}."


SERVER = build_server(
    "parcel-tracking",
    (
        Tool(
            "Track a parcel by consignment number, such as CN-8842-1177. Returns current "
            "depot, promised delivery date and every scan event.",
            track_parcel,
        ),
        Tool(
            "Return only the most recent scan event for a consignment number.",
            latest_scan,
        ),
    ),
)

if __name__ == "__main__":
    run("parcel-tracking", SERVER)
