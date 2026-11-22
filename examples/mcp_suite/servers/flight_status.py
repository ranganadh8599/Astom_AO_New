"""Flight status MCP server: departure, gate and delay reason per flight."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

FLIGHTS: dict[str, dict[str, str]] = {
    "BA2490": {
        "route": "London Heathrow to Rome Fiumicino",
        "scheduled": "08:15",
        "actual": "08:52",
        "gate": "A12",
        "terminal": "5",
        "reason": "late arrival of the inbound aircraft",
    },
    "LH1187": {
        "route": "Frankfurt to Zurich",
        "scheduled": "12:40",
        "actual": "12:40",
        "gate": "B03",
        "terminal": "1",
        "reason": "on time",
    },
    "AF1681": {
        "route": "Paris Charles de Gaulle to Lisbon",
        "scheduled": "18:05",
        "actual": "",
        "gate": "F41",
        "terminal": "2E",
        "reason": "boarding not yet started",
    },
}


def get_flight_status(flight_number: str) -> str:
    """Report schedule, actual time, gate and delay reason for one flight."""
    key = flight_number.strip().upper()
    row = FLIGHTS.get(key)
    if row is None:
        known = ", ".join(sorted(FLIGHTS))
        return f"No flight {key} in the status feed. Tracked flights: {known}."
    actual = row["actual"] or "not yet departed"
    return (
        f"{key} ({row['route']}) was scheduled {row['scheduled']}, actual {actual}. "
        f"Gate {row['gate']}, terminal {row['terminal']}. Status: {row['reason']}."
    )


def get_departure_gate(flight_number: str) -> str:
    """Return only the terminal and gate for one flight."""
    key = flight_number.strip().upper()
    row = FLIGHTS.get(key)
    if row is None:
        known = ", ".join(sorted(FLIGHTS))
        return f"No flight {key} in the status feed. Tracked flights: {known}."
    return f"{key} departs from terminal {row['terminal']}, gate {row['gate']}."


SERVER = build_server(
    "flight-status",
    (
        Tool(
            "Look up an airline flight by flight number, for example BA2490. Returns the "
            "route, scheduled and actual departure times, gate, terminal and delay reason.",
            get_flight_status,
        ),
        Tool(
            "Look up only the departure terminal and gate for a flight number.",
            get_departure_gate,
        ),
    ),
)

if __name__ == "__main__":
    run("flight-status", SERVER)
