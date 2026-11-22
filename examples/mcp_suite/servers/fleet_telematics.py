"""Fleet telematics MCP server: odometer, fuel and fault codes per vehicle."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

VEHICLES: dict[str, dict[str, object]] = {
    "FLT-014": {
        "model": "18 t box truck",
        "odometer_km": 148320,
        "fuel_pct": 62,
        "position": "depot yard, Bay 4",
        "faults": [],
    },
    "FLT-027": {
        "model": "7.5 t curtain-side",
        "odometer_km": 88210,
        "fuel_pct": 18,
        "position": "A12 northbound, near junction 9",
        "faults": ["P0299 turbo underboost"],
    },
    "FLT-031": {
        "model": "3.5 t van",
        "odometer_km": 44105,
        "fuel_pct": 74,
        "position": "customer site, Reading",
        "faults": ["C1234 wheel speed sensor"],
    },
}


def get_vehicle_status(registration: str) -> str:
    """Report odometer, fuel level, position and fault codes for a fleet vehicle."""
    key = registration.strip().upper()
    row = VEHICLES.get(key)
    if row is None:
        known = ", ".join(sorted(VEHICLES))
        return f"No telemetry for vehicle {key}. Tracked vehicles: {known}."
    faults = row["faults"]
    fault_text = "no active faults" if not faults else "faults: " + "; ".join(faults)
    return (
        f"{key} ({row['model']}): odometer {row['odometer_km']} km, fuel {row['fuel_pct']}%, "
        f"last position {row['position']}, {fault_text}."
    )


def list_vehicles_with_faults() -> str:
    """List every fleet vehicle with at least one active diagnostic trouble code."""
    flagged = [
        f"{reg} ({row['model']}): " + "; ".join(row["faults"])
        for reg, row in sorted(VEHICLES.items())
        if row["faults"]
    ]
    if not flagged:
        return "No fleet vehicle has an active fault code."
    return "Vehicles with active fault codes: " + " | ".join(flagged) + "."


SERVER = build_server(
    "fleet-telematics",
    (
        Tool(
            "Look up telematics for a fleet vehicle by registration, such as FLT-027. "
            "Returns model, odometer, fuel percentage, last position and fault codes.",
            get_vehicle_status,
        ),
        Tool(
            "List every fleet vehicle that currently has an active engine or chassis fault "
            "code, with the code text.",
            list_vehicles_with_faults,
        ),
    ),
)

if __name__ == "__main__":
    run("fleet-telematics", SERVER)
