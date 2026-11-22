"""Warehouse inventory MCP server: on-hand stock and reorder points."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

STOCK: dict[str, dict[str, object]] = {
    "SKU-4471": {"item": "M8 hex bolt, 40 mm", "on_hand": 1840, "bin": "A-14-03", "reorder_at": 500},
    "SKU-8820": {"item": "Nitrile gloves, box of 100", "on_hand": 96, "bin": "C-02-11", "reorder_at": 150},
    "SKU-1093": {"item": "Pallet wrap, 500 mm", "on_hand": 42, "bin": "B-07-01", "reorder_at": 60},
    "SKU-6635": {"item": "Thermal label roll", "on_hand": 780, "bin": "C-05-08", "reorder_at": 200},
}


def get_stock_level(sku: str) -> str:
    """Report on-hand quantity and bin location for one SKU."""
    key = sku.strip().upper()
    row = STOCK.get(key)
    if row is None:
        known = ", ".join(sorted(STOCK))
        return f"No SKU {key} in the warehouse catalogue. Known SKUs: {known}."
    return (
        f"{key} ({row['item']}) has {row['on_hand']} units on hand in bin {row['bin']}. "
        f"Reorder point is {row['reorder_at']}."
    )


def list_below_reorder() -> str:
    """List every SKU whose on-hand quantity is below its reorder point."""
    low = [
        f"{sku} ({row['item']}): {row['on_hand']} on hand, reorder at {row['reorder_at']}"
        for sku, row in sorted(STOCK.items())
        if int(row["on_hand"]) < int(row["reorder_at"])
    ]
    if not low:
        return "No SKU is below its reorder point."
    return "Below reorder point: " + "; ".join(low) + "."


SERVER = build_server(
    "warehouse-inventory",
    (
        Tool(
            "Look up warehouse stock for one SKU, for example SKU-4471. Returns the item "
            "name, on-hand quantity, bin location and reorder point.",
            get_stock_level,
        ),
        Tool(
            "List all SKUs whose on-hand quantity has fallen below the configured reorder "
            "point, with both numbers.",
            list_below_reorder,
        ),
    ),
)

if __name__ == "__main__":
    run("warehouse-inventory", SERVER)
