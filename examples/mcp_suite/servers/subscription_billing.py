"""Subscription billing MCP server: plan, seats, renewal and next invoice."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

ACCOUNTS: dict[str, dict[str, object]] = {
    "ACC-7781": {
        "company": "Northwind Logistics",
        "plan": "Business",
        "seats": 45,
        "price_per_seat": 24.0,
        "renews": "2027-02-01",
    },
    "ACC-8120": {
        "company": "Cedar Analytics",
        "plan": "Starter",
        "seats": 8,
        "price_per_seat": 12.0,
        "renews": "2026-12-15",
    },
    "ACC-9044": {
        "company": "Ridgeway Health",
        "plan": "Enterprise",
        "seats": 320,
        "price_per_seat": 19.5,
        "renews": "2027-06-30",
    },
}


def get_subscription(account_id: str) -> str:
    """Report plan, seat count, renewal date and next invoice for an account."""
    key = account_id.strip().upper()
    row = ACCOUNTS.get(key)
    if row is None:
        known = ", ".join(sorted(ACCOUNTS))
        return f"No subscription for account {key}. Accounts on file: {known}."
    amount = int(row["seats"]) * float(row["price_per_seat"])
    return (
        f"{row['company']} ({key}) is on the {row['plan']} plan with {row['seats']} seats at "
        f"{row['price_per_seat']:.2f} per seat, renewing {row['renews']}. "
        f"Next invoice: {amount:.2f}."
    )


def list_renewals_before(date: str) -> str:
    """List accounts renewing on or before a given date."""
    cutoff = date.strip()
    rows = [
        f"{key} ({row['company']}) renews {row['renews']}"
        for key, row in sorted(ACCOUNTS.items())
        if str(row["renews"]) <= cutoff
    ]
    if not rows:
        return f"No subscription renews on or before {cutoff}."
    return f"Renewals on or before {cutoff}: " + "; ".join(rows) + "."


SERVER = build_server(
    "subscription-billing",
    (
        Tool(
            "Look up a SaaS subscription by account ID, such as ACC-7781. Returns plan, "
            "seat count, price per seat, renewal date and the next invoice amount.",
            get_subscription,
        ),
        Tool(
            "List every subscription account that renews on or before a given date "
            "(YYYY-MM-DD).",
            list_renewals_before,
        ),
    ),
)

if __name__ == "__main__":
    run("subscription-billing", SERVER)
