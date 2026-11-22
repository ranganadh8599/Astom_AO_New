"""Clinic appointments MCP server: free and booked outpatient slots."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

SCHEDULE: dict[str, list[dict[str, str]]] = {
    "cardiology-2026-11-24": [
        {"time": "09:00", "state": "booked", "with": "Dr Almeida"},
        {"time": "09:30", "state": "free", "with": "Dr Almeida"},
        {"time": "10:00", "state": "free", "with": "Dr Almeida"},
        {"time": "11:00", "state": "booked", "with": "Dr Novak"},
    ],
    "dermatology-2026-11-24": [
        {"time": "13:00", "state": "free", "with": "Dr Chen"},
        {"time": "13:30", "state": "free", "with": "Dr Chen"},
    ],
    "physiotherapy-2026-11-25": [
        {"time": "08:00", "state": "booked", "with": "K. Brandt"},
        {"time": "08:45", "state": "free", "with": "K. Brandt"},
    ],
}


def list_free_slots(clinic_date: str) -> str:
    """List free appointment times for a clinic and date key."""
    key = clinic_date.strip().lower().replace(" ", "-")
    slots = SCHEDULE.get(key)
    if slots is None:
        known = ", ".join(sorted(SCHEDULE))
        return f"No schedule for {key}. Known clinic-date keys: {known}."
    free = [slot for slot in slots if slot["state"] == "free"]
    if not free:
        return f"Every slot for {key} is booked."
    lines = [f"{slot['time']} with {slot['with']}" for slot in free]
    return f"Free slots for {key}: " + "; ".join(lines) + "."


def next_free_slot(clinic_date: str) -> str:
    """Return the earliest free appointment time for a clinic and date key."""
    key = clinic_date.strip().lower().replace(" ", "-")
    slots = SCHEDULE.get(key)
    if slots is None:
        known = ", ".join(sorted(SCHEDULE))
        return f"No schedule for {key}. Known clinic-date keys: {known}."
    free = [slot for slot in slots if slot["state"] == "free"]
    if not free:
        return f"Every slot for {key} is booked."
    first = sorted(free, key=lambda slot: slot["time"])[0]
    return f"Earliest free slot for {key} is {first['time']} with {first['with']}."


SERVER = build_server(
    "clinic-appointments",
    (
        Tool(
            "List free outpatient appointment slots for a clinic and date, keyed like "
            "'cardiology-2026-11-24'. Returns times and the practitioner.",
            list_free_slots,
        ),
        Tool(
            "Return the earliest free appointment slot for a clinic and date key.",
            next_free_slot,
        ),
    ),
)

if __name__ == "__main__":
    run("clinic-appointments", SERVER)
