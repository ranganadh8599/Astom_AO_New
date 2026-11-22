"""Meeting rooms MCP server: capacity, equipment and free slots."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

ROOMS: dict[str, dict[str, object]] = {
    "ROOM-2A": {
        "name": "Alder",
        "capacity": 8,
        "equipment": ["display", "video conference"],
        "slots": {"09:00": "free", "10:00": "booked", "11:00": "free", "14:00": "free"},
    },
    "ROOM-3C": {
        "name": "Birch",
        "capacity": 4,
        "equipment": ["display"],
        "slots": {"09:00": "booked", "10:00": "booked", "11:00": "free", "14:00": "booked"},
    },
    "ROOM-5B": {
        "name": "Cedar",
        "capacity": 16,
        "equipment": ["display", "video conference", "whiteboard"],
        "slots": {"09:00": "free", "10:00": "free", "11:00": "free", "14:00": "booked"},
    },
}


def get_room(room_id: str) -> str:
    """Report capacity, equipment and the slot states for one meeting room."""
    key = room_id.strip().upper()
    row = ROOMS.get(key)
    if row is None:
        known = ", ".join(sorted(ROOMS))
        return f"No meeting room {key}. Bookable rooms: {known}."
    slots = "; ".join(f"{time} {state}" for time, state in row["slots"].items())
    return (
        f"{key} ({row['name']}) seats {row['capacity']} and has "
        f"{', '.join(row['equipment'])}. Slots: {slots}."
    )


def find_free_room(min_capacity: int, time: str) -> str:
    """List rooms with at least a given capacity that are free at a given hour."""
    wanted = time.strip()
    matches = [
        f"{key} ({row['name']}, seats {row['capacity']})"
        for key, row in sorted(ROOMS.items())
        if int(row["capacity"]) >= min_capacity
        and row["slots"].get(wanted, "booked") == "free"
    ]
    if not matches:
        return (
            f"No room seating {min_capacity} or more is free at {wanted}. "
            "Try another hour or a smaller capacity."
        )
    return f"Free at {wanted} for {min_capacity}+ people: " + "; ".join(matches) + "."


SERVER = build_server(
    "meeting-rooms",
    (
        Tool(
            "Look up a meeting room by ID, such as ROOM-2A. Returns capacity, equipment and "
            "whether each hourly slot is free or booked.",
            get_room,
        ),
        Tool(
            "List meeting rooms with at least the requested capacity that are free at a "
            "given hour, for example 11:00.",
            find_free_room,
        ),
    ),
)

if __name__ == "__main__":
    run("meeting-rooms", SERVER)
