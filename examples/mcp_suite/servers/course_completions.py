"""Course completions MCP server: training records and certificate expiry."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

RECORDS: dict[str, list[dict[str, object]]] = {
    "E-1042": [
        {"course": "Fire safety", "score": 92, "completed": "2026-03-12", "expires": "2027-03-12"},
        {"course": "Data protection", "score": 88, "completed": "2026-09-01", "expires": "2027-09-01"},
    ],
    "E-2210": [
        {"course": "Fire safety", "score": 74, "completed": "2025-11-20", "expires": "2026-11-20"},
        {"course": "Manual handling", "score": 81, "completed": "2026-02-14", "expires": "2027-02-14"},
    ],
    "E-3377": [
        {"course": "Data protection", "score": 95, "completed": "2026-07-18", "expires": "2027-07-18"},
    ],
}


def get_training_records(employee_id: str) -> str:
    """List completed compliance courses for one employee, with scores and expiry."""
    key = employee_id.strip().upper()
    rows = RECORDS.get(key)
    if not rows:
        known = ", ".join(sorted(RECORDS))
        return f"No training records for {key}. Employees on file: {known}."
    lines = [
        f"{row['course']}: score {row['score']}, completed {row['completed']}, "
        f"expires {row['expires']}"
        for row in rows
    ]
    return f"Training for {key}: " + "; ".join(lines) + "."


def list_expiring_before(date: str) -> str:
    """List certificates due to expire on or before a date."""
    cutoff = date.strip()
    results: list[str] = []
    for employee, rows in sorted(RECORDS.items()):
        for row in rows:
            if str(row["expires"]) <= cutoff:
                results.append(
                    f"{employee} {row['course']} expires {row['expires']}"
                )
    if not results:
        return f"No certificate expires on or before {cutoff}."
    return f"Expiring on or before {cutoff}: " + "; ".join(results) + "."


SERVER = build_server(
    "course-completions",
    (
        Tool(
            "List the compliance training courses completed by an employee, by employee ID, "
            "with score, completion date and certificate expiry.",
            get_training_records,
        ),
        Tool(
            "List every certificate that expires on or before a given date (YYYY-MM-DD).",
            list_expiring_before,
        ),
    ),
)

if __name__ == "__main__":
    run("course-completions", SERVER)
