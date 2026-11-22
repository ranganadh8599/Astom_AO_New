"""Customs tariff MCP server: commodity classification and duty rates."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

TARIFF: dict[str, dict[str, object]] = {
    "8471.30": {
        "description": "portable automatic data processing machines under 10 kg",
        "duty_pct": 0.0,
    },
    "0901.21": {
        "description": "roasted coffee, not decaffeinated",
        "duty_pct": 7.5,
    },
    "6109.10": {
        "description": "cotton t-shirts, knitted",
        "duty_pct": 12.0,
    },
}

KEYWORDS: dict[str, str] = {
    "laptop": "8471.30",
    "notebook": "8471.30",
    "computer": "8471.30",
    "coffee": "0901.21",
    "t-shirt": "6109.10",
    "tshirt": "6109.10",
    "shirt": "6109.10",
}


def classify_product(product: str) -> str:
    """Suggest an HS commodity code for a plain product description."""
    text = product.strip().lower()
    for keyword, code in KEYWORDS.items():
        if keyword in text:
            row = TARIFF[code]
            return (
                f"'{product.strip()}' classifies under HS {code} "
                f"({row['description']}) at a duty rate of {row['duty_pct']}%."
            )
    known = ", ".join(sorted(TARIFF))
    return (
        f"No classification rule matched '{product.strip()}'. "
        f"Codes on file: {known}. A customs broker must classify unlisted goods."
    )


def get_duty_rate(hs_code: str) -> str:
    """Return the duty rate for an HS commodity code."""
    key = hs_code.strip()
    row = TARIFF.get(key)
    if row is None:
        known = ", ".join(sorted(TARIFF))
        return f"No tariff line for HS {key}. Codes on file: {known}."
    return f"HS {key} ({row['description']}) attracts {row['duty_pct']}% duty."


SERVER = build_server(
    "customs-tariff",
    (
        Tool(
            "Suggest the HS commodity code and duty rate for a product description such as "
            "'cotton t-shirts'.",
            classify_product,
        ),
        Tool(
            "Return the duty rate and description for a specific HS commodity code, for "
            "example 0901.21.",
            get_duty_rate,
        ),
    ),
)

if __name__ == "__main__":
    run("customs-tariff", SERVER)
