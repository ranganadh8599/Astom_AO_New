"""Water quality MCP server: chlorine, pH and turbidity readings per plant."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

READINGS: dict[str, dict[str, object]] = {
    "PLANT-NORTH": {
        "chlorine_mg_l": 0.62,
        "ph": 7.32,
        "turbidity_ntu": 0.18,
        "sampled": "2026-11-21 06:15",
    },
    "PLANT-EAST": {
        "chlorine_mg_l": 0.21,
        "ph": 7.05,
        "turbidity_ntu": 0.44,
        "sampled": "2026-11-21 06:40",
    },
    "PLANT-SOUTH": {
        "chlorine_mg_l": 0.88,
        "ph": 7.61,
        "turbidity_ntu": 0.09,
        "sampled": "2026-11-21 07:05",
    },
}

# Indicative limits for a treated-water sample.
LIMITS = {"chlorine_min": 0.2, "ph_min": 6.5, "ph_max": 8.5, "turbidity_max": 1.0}


def get_water_reading(plant: str) -> str:
    """Report the latest chlorine, pH and turbidity reading for a treatment plant."""
    key = plant.strip().upper().replace(" ", "-")
    row = READINGS.get(key)
    if row is None:
        known = ", ".join(sorted(READINGS))
        return f"No reading for plant {key}. Plants reporting: {known}."
    return (
        f"{key} at {row['sampled']}: free chlorine {row['chlorine_mg_l']} mg/l, "
        f"pH {row['ph']}, turbidity {row['turbidity_ntu']} NTU."
    )


def list_out_of_spec() -> str:
    """List plants whose latest reading falls outside the indicative limits."""
    breaches: list[str] = []
    for key, row in sorted(READINGS.items()):
        reasons: list[str] = []
        if float(row["chlorine_mg_l"]) < LIMITS["chlorine_min"]:
            reasons.append(f"chlorine {row['chlorine_mg_l']} below {LIMITS['chlorine_min']}")
        if not LIMITS["ph_min"] <= float(row["ph"]) <= LIMITS["ph_max"]:
            reasons.append(f"pH {row['ph']} outside {LIMITS['ph_min']}-{LIMITS['ph_max']}")
        if float(row["turbidity_ntu"]) > LIMITS["turbidity_max"]:
            reasons.append(f"turbidity {row['turbidity_ntu']} above {LIMITS['turbidity_max']}")
        if reasons:
            breaches.append(f"{key}: " + ", ".join(reasons))
    if not breaches:
        return "Every plant is within the indicative limits."
    return "Out of specification: " + " | ".join(breaches) + "."


SERVER = build_server(
    "water-quality",
    (
        Tool(
            "Read the latest drinking-water quality sample for a treatment plant, such as "
            "PLANT-NORTH. Returns free chlorine, pH, turbidity and sample time.",
            get_water_reading,
        ),
        Tool(
            "List every treatment plant whose latest sample is outside the indicative "
            "chlorine, pH or turbidity limits, with the reason.",
            list_out_of_spec,
        ),
    ),
)

if __name__ == "__main__":
    run("water-quality", SERVER)
