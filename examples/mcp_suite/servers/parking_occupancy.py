"""Parking occupancy MCP server: live bay counts per car park."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

FACILITIES: dict[str, dict[str, object]] = {
    "PARK-CENTRAL": {
        "total": 420,
        "occupied": 388,
        "accessible_total": 18,
        "accessible_free": 1,
        "updated": "2026-11-21 10:42",
    },
    "PARK-RIVERSIDE": {
        "total": 260,
        "occupied": 141,
        "accessible_total": 12,
        "accessible_free": 7,
        "updated": "2026-11-21 10:41",
    },
    "PARK-STATION": {
        "total": 95,
        "occupied": 94,
        "accessible_total": 6,
        "accessible_free": 0,
        "updated": "2026-11-21 10:40",
    },
}


def get_occupancy(facility: str) -> str:
    """Report free bays, occupancy percentage and accessible bays for a car park."""
    key = facility.strip().upper().replace(" ", "-")
    row = FACILITIES.get(key)
    if row is None:
        known = ", ".join(sorted(FACILITIES))
        return f"No facility {key}. Car parks reporting: {known}."
    free = int(row["total"]) - int(row["occupied"])
    pct = 100.0 * int(row["occupied"]) / int(row["total"])
    return (
        f"{key} at {row['updated']}: {free} of {row['total']} bays free "
        f"({pct:.1f}% occupied). Accessible bays free: {row['accessible_free']} of "
        f"{row['accessible_total']}."
    )


def find_accessible_bays() -> str:
    """List car parks that currently have at least one free accessible bay."""
    rows = [
        f"{key}: {row['accessible_free']} free"
        for key, row in sorted(FACILITIES.items())
        if int(row["accessible_free"]) > 0
    ]
    if not rows:
        return "No car park currently has a free accessible bay."
    return "Accessible bays available at: " + "; ".join(rows) + "."


SERVER = build_server(
    "parking-occupancy",
    (
        Tool(
            "Check live car-park occupancy for a facility, such as PARK-CENTRAL. Returns "
            "free bays, occupancy percentage and accessible bays free.",
            get_occupancy,
        ),
        Tool(
            "List car parks that currently have at least one free accessible (blue badge) "
            "bay.",
            find_accessible_bays,
        ),
    ),
)

if __name__ == "__main__":
    run("parking-occupancy", SERVER)
