"""Hotel availability MCP server: rooms and nightly rates by date."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

ROOMS: dict[str, list[dict[str, object]]] = {
    "2026-12-02": [
        {"type": "standard double", "free": 6, "rate": 128},
        {"type": "superior king", "free": 2, "rate": 176},
        {"type": "family suite", "free": 0, "rate": 240},
    ],
    "2026-12-03": [
        {"type": "standard double", "free": 9, "rate": 118},
        {"type": "superior king", "free": 4, "rate": 168},
        {"type": "family suite", "free": 1, "rate": 235},
    ],
    "2026-12-04": [
        {"type": "standard double", "free": 1, "rate": 142},
        {"type": "superior king", "free": 0, "rate": 189},
        {"type": "family suite", "free": 0, "rate": 250},
    ],
}


def check_availability(date: str) -> str:
    """Report free rooms and nightly rate per room type for one date."""
    key = date.strip()
    rooms = ROOMS.get(key)
    if rooms is None:
        known = ", ".join(sorted(ROOMS))
        return f"No availability data for {key}. Dates on file: {known}."
    lines = [
        f"{room['type']}: {room['free']} free at {room['rate']} per night" for room in rooms
    ]
    return f"Availability on {key}: " + "; ".join(lines) + "."


def cheapest_room(date: str) -> str:
    """Return the lowest nightly rate available on a date, if any room is free."""
    key = date.strip()
    rooms = ROOMS.get(key)
    if rooms is None:
        known = ", ".join(sorted(ROOMS))
        return f"No availability data for {key}. Dates on file: {known}."
    free = [room for room in rooms if int(room["free"]) > 0]
    if not free:
        return f"No rooms are free on {key}."
    best = min(free, key=lambda room: int(room["rate"]))
    return (
        f"Cheapest available room on {key} is the {best['type']} at {best['rate']} per "
        f"night, with {best['free']} left."
    )


SERVER = build_server(
    "hotel-availability",
    (
        Tool(
            "Check hotel room availability for a date in YYYY-MM-DD form. Returns free room "
            "count and nightly rate for each room type.",
            check_availability,
        ),
        Tool(
            "Find the cheapest room type with at least one free room on a given date.",
            cheapest_room,
        ),
    ),
)

if __name__ == "__main__":
    run("hotel-availability", SERVER)
