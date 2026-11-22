"""Support queue MCP server: ticket priority, age and SLA state."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

TICKETS: dict[str, dict[str, object]] = {
    "INC-5501": {
        "subject": "Checkout returns HTTP 500 for EU customers",
        "priority": "P1",
        "assignee": "on-call platform",
        "age_hours": 3.5,
        "sla_hours": 4,
        "breached": False,
    },
    "INC-5512": {
        "subject": "Password reset email delayed",
        "priority": "P3",
        "assignee": "identity team",
        "age_hours": 51.0,
        "sla_hours": 48,
        "breached": True,
    },
    "INC-5520": {
        "subject": "Export to CSV missing final row",
        "priority": "P2",
        "assignee": "reporting team",
        "age_hours": 9.0,
        "sla_hours": 24,
        "breached": False,
    },
}


def get_ticket(ticket_id: str) -> str:
    """Report priority, assignee, age and SLA state for one ticket."""
    key = ticket_id.strip().upper()
    row = TICKETS.get(key)
    if row is None:
        known = ", ".join(sorted(TICKETS))
        return f"No ticket {key} in the service desk. Open tickets: {known}."
    return (
        f"{key} ({row['priority']}) '{row['subject']}': assigned to {row['assignee']}, "
        f"open {row['age_hours']} h against a {row['sla_hours']} h response target, "
        f"SLA breached: {row['breached']}."
    )


def list_breached_tickets() -> str:
    """List every ticket whose response SLA has already been breached."""
    breached = [
        f"{tid} ({row['priority']}) {row['subject']} - open {row['age_hours']} h"
        for tid, row in sorted(TICKETS.items())
        if row["breached"]
    ]
    if not breached:
        return "No ticket has breached its response SLA."
    return "Breached tickets: " + " | ".join(breached) + "."


SERVER = build_server(
    "support-queue",
    (
        Tool(
            "Look up a service-desk ticket by ID, such as INC-5501. Returns subject, "
            "priority, assignee, age and whether the response SLA is breached.",
            get_ticket,
        ),
        Tool(
            "List every open ticket whose response SLA has been breached.",
            list_breached_tickets,
        ),
    ),
)

if __name__ == "__main__":
    run("support-queue", SERVER)
