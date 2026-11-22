"""Laboratory sample tracking MCP server: specimen stage and result release."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

SAMPLES: dict[str, dict[str, str]] = {
    "LAB-2026-0417": {
        "collected": "2026-11-19 07:42",
        "stage": "awaiting analysis",
        "analyser": "haematology line 2",
        "released": "no",
    },
    "LAB-2026-0418": {
        "collected": "2026-11-19 08:05",
        "stage": "in analysis",
        "analyser": "chemistry line 1",
        "released": "no",
    },
    "LAB-2026-0402": {
        "collected": "2026-11-18 14:10",
        "stage": "resulted",
        "analyser": "microbiology bench",
        "released": "yes",
    },
}


def get_sample_status(sample_id: str) -> str:
    """Report collection time, analyser stage and release state for a sample."""
    key = sample_id.strip().upper()
    row = SAMPLES.get(key)
    if row is None:
        known = ", ".join(sorted(SAMPLES))
        return f"No specimen {key} in the laboratory system. Known sample IDs: {known}."
    return (
        f"Sample {key} was collected {row['collected']}, is currently '{row['stage']}' on "
        f"{row['analyser']}, and results released: {row['released']}."
    )


def is_result_released(sample_id: str) -> str:
    """Answer only whether a sample's results have been released."""
    key = sample_id.strip().upper()
    row = SAMPLES.get(key)
    if row is None:
        known = ", ".join(sorted(SAMPLES))
        return f"No specimen {key} in the laboratory system. Known sample IDs: {known}."
    if row["released"] == "yes":
        return f"Results for {key} have been released to the requesting clinician."
    return f"Results for {key} are not released yet; the sample is '{row['stage']}'."


SERVER = build_server(
    "lab-sample-tracking",
    (
        Tool(
            "Track a clinical specimen by sample ID, such as LAB-2026-0417. Returns "
            "collection time, current analyser stage and whether results are released.",
            get_sample_status,
        ),
        Tool(
            "Check only whether a specimen's laboratory results have been released.",
            is_result_released,
        ),
    ),
)

if __name__ == "__main__":
    run("lab-sample-tracking", SERVER)
