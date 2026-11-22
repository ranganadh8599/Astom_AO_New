"""Cold-chain temperature MCP server: reefer logs and excursion detection."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

# Each consignment declares its allowed band and the readings taken in transit.
LOGS: dict[str, dict[str, object]] = {
    "CC-3301": {
        "product": "insulin pens",
        "min_c": 2.0,
        "max_c": 8.0,
        "readings": [4.1, 4.4, 5.0, 6.2, 5.8],
        "last_scan": "2026-11-21 09:20",
    },
    "CC-3318": {
        "product": "fresh salmon fillets",
        "min_c": 0.0,
        "max_c": 2.0,
        "readings": [0.4, 0.9, 3.6, 4.2, 2.8],
        "last_scan": "2026-11-21 08:55",
    },
    "CC-3327": {
        "product": "frozen peas",
        "min_c": -22.0,
        "max_c": -18.0,
        "readings": [-19.4, -19.8, -20.1, -19.9],
        "last_scan": "2026-11-21 09:05",
    },
}


def get_temperature_log(consignment: str) -> str:
    """Report readings, min/max and excursion state for a cold-chain consignment."""
    key = consignment.strip().upper()
    row = LOGS.get(key)
    if row is None:
        known = ", ".join(sorted(LOGS))
        return f"No temperature log for {key}. Consignments on file: {known}."
    readings = [float(value) for value in row["readings"]]
    low, high = float(row["min_c"]), float(row["max_c"])
    excursions = [value for value in readings if value < low or value > high]
    state = "no excursion" if not excursions else f"EXCURSION ({len(excursions)} readings)"
    return (
        f"{key} ({row['product']}) band {low} to {high} C. Readings: "
        f"{', '.join(f'{value:.1f}' for value in readings)} C. "
        f"Observed range {min(readings):.1f} to {max(readings):.1f} C, {state}. "
        f"Last scan {row['last_scan']}."
    )


def list_excursions() -> str:
    """List every consignment with at least one out-of-band temperature reading."""
    flagged: list[str] = []
    for key, row in sorted(LOGS.items()):
        low, high = float(row["min_c"]), float(row["max_c"])
        bad = [
            float(value)
            for value in row["readings"]
            if float(value) < low or float(value) > high
        ]
        if bad:
            flagged.append(
                f"{key} ({row['product']}): {len(bad)} reading(s) outside {low}-{high} C"
            )
    if not flagged:
        return "No cold-chain consignment has recorded an excursion."
    return "Excursions: " + "; ".join(flagged) + "."


SERVER = build_server(
    "cold-chain-temperature",
    (
        Tool(
            "Read the temperature log for a refrigerated consignment, such as CC-3318. "
            "Returns the allowed band, all readings, the observed range and whether an "
            "excursion occurred.",
            get_temperature_log,
        ),
        Tool(
            "List every consignment that recorded at least one out-of-band temperature "
            "reading.",
            list_excursions,
        ),
    ),
)

if __name__ == "__main__":
    run("cold-chain-temperature", SERVER)
