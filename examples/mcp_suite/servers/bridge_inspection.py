"""Bridge inspection MCP server: condition, defects and recommended action."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

BRIDGES: dict[str, dict[str, object]] = {
    "BR-0142": {
        "name": "Mill Lane over River Cray",
        "type": "three-span concrete beam",
        "last_inspection": "2026-06-11",
        "severity": "2 of 5",
        "defects": ["hairline cracks in deck soffit", "scour marker displaced"],
        "action": "monitor at next routine inspection",
    },
    "BR-0207": {
        "name": "A41 canal crossing",
        "type": "steel truss",
        "last_inspection": "2025-09-03",
        "severity": "4 of 5",
        "defects": ["section loss on two diagonal members", "corroded bearings"],
        "action": "restrict to 7.5 t and schedule strengthening within 6 months",
    },
    "BR-0331": {
        "name": "Station Road footbridge",
        "type": "timber deck footbridge",
        "last_inspection": "2026-10-28",
        "severity": "1 of 5",
        "defects": ["worn anti-slip strips"],
        "action": "replace strips at next maintenance window",
    },
}


def get_bridge_inspection(asset_number: str) -> str:
    """Report inspection date, severity, defects and action for one bridge."""
    key = asset_number.strip().upper()
    row = BRIDGES.get(key)
    if row is None:
        known = ", ".join(sorted(BRIDGES))
        return f"No bridge asset {key}. Inspected assets: {known}."
    return (
        f"{key} ({row['name']}, {row['type']}) last inspected {row['last_inspection']} at "
        f"severity {row['severity']}. Defects: {'; '.join(row['defects'])}. "
        f"Recommended action: {row['action']}."
    )


def list_bridges_above_severity(threshold: int) -> str:
    """List bridges whose recorded severity is higher than a 1-5 threshold."""
    flagged = [
        f"{key} ({row['name']}) at severity {row['severity']}: {row['action']}"
        for key, row in sorted(BRIDGES.items())
        if int(str(row["severity"]).split(" ")[0]) > threshold
    ]
    if not flagged:
        return f"No bridge is recorded above severity {threshold} of 5."
    return f"Above severity {threshold}: " + " | ".join(flagged) + "."


SERVER = build_server(
    "bridge-inspection",
    (
        Tool(
            "Look up a road bridge inspection by asset number, such as BR-0207. Returns "
            "structure type, last inspection date, severity, defects and recommended action.",
            get_bridge_inspection,
        ),
        Tool(
            "List every bridge whose severity rating is above a threshold from 1 to 5.",
            list_bridges_above_severity,
        ),
    ),
)

if __name__ == "__main__":
    run("bridge-inspection", SERVER)
