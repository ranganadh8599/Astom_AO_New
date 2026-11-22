"""Crop harvest MCP server: tonnage, moisture and yield per field."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

HARVEST: dict[str, dict[str, object]] = {
    "FIELD-07-2026": {
        "crop": "winter wheat",
        "variety": "Skyfall",
        "hectares": 42.5,
        "tonnes": 361.2,
        "moisture_pct": 14.6,
    },
    "FIELD-12-2026": {
        "crop": "oilseed rape",
        "variety": "DK Excited",
        "hectares": 28.0,
        "tonnes": 116.2,
        "moisture_pct": 8.9,
    },
    "FIELD-19-2026": {
        "crop": "spring barley",
        "variety": "Laureate",
        "hectares": 35.0,
        "tonnes": 224.0,
        "moisture_pct": 12.4,
    },
}


def get_field_harvest(field_season: str) -> str:
    """Report crop, tonnage, moisture and yield for a field-season record."""
    key = field_season.strip().upper().replace(" ", "-")
    row = HARVEST.get(key)
    if row is None:
        known = ", ".join(sorted(HARVEST))
        return f"No harvest record for {key}. Records on file: {known}."
    yield_tha = float(row["tonnes"]) / float(row["hectares"])
    return (
        f"{key}: {row['crop']} ({row['variety']}) over {row['hectares']} ha produced "
        f"{row['tonnes']} t at {row['moisture_pct']}% moisture, a yield of "
        f"{yield_tha:.2f} t/ha."
    )


def compare_yields() -> str:
    """Rank all recorded fields by yield in tonnes per hectare, highest first."""
    ranking = sorted(
        (
            (float(row["tonnes"]) / float(row["hectares"]), key, row["crop"])
            for key, row in HARVEST.items()
        ),
        reverse=True,
    )
    lines = [f"{key} ({crop}): {value:.2f} t/ha" for value, key, crop in ranking]
    return "Yield ranking: " + "; ".join(lines) + "."


SERVER = build_server(
    "crop-harvest",
    (
        Tool(
            "Look up a harvest record by field-season key, such as FIELD-07-2026. Returns "
            "crop, variety, hectares, tonnes, moisture percentage and yield per hectare.",
            get_field_harvest,
        ),
        Tool(
            "Rank every recorded field by harvest yield in tonnes per hectare.",
            compare_yields,
        ),
    ),
)

if __name__ == "__main__":
    run("crop-harvest", SERVER)
