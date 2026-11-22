"""FX rates MCP server: reference rates and conversion between currencies."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

# Rates are quoted per 1 unit of the base currency.
RATES: dict[str, dict[str, float]] = {
    "2026-11-20": {"EUR": 0.92, "GBP": 0.79, "JPY": 155.4, "CHF": 0.88},
    "2026-11-21": {"EUR": 0.925, "GBP": 0.787, "JPY": 156.9, "CHF": 0.882},
}


def get_rate(currency: str, date: str = "2026-11-21") -> str:
    """Return the USD rate for a currency on a business date."""
    day = date.strip()
    table = RATES.get(day)
    if table is None:
        known = ", ".join(sorted(RATES))
        return f"No rate sheet for {day}. Available dates: {known}."
    code = currency.strip().upper()
    rate = table.get(code)
    if rate is None:
        known = ", ".join(sorted(table))
        return f"No rate for {code} on {day}. Quoted currencies: {known}."
    return f"1 USD = {rate} {code} on {day}; 1 {code} = {1 / rate:.4f} USD."


def convert(amount: float, from_currency: str, to_currency: str, date: str = "2026-11-21") -> str:
    """Convert an amount between two currencies using the reference rate for a date."""
    day = date.strip()
    table = RATES.get(day)
    if table is None:
        known = ", ".join(sorted(RATES))
        return f"No rate sheet for {day}. Available dates: {known}."
    src = from_currency.strip().upper()
    dst = to_currency.strip().upper()
    missing = [code for code in (src, dst) if code not in table]
    if missing:
        known = ", ".join(sorted(table))
        return f"No rate for {', '.join(missing)} on {day}. Quoted currencies: {known}."
    usd = amount / table[src]
    converted = usd * table[dst]
    return f"{amount:.2f} {src} = {converted:.2f} {dst} on {day} (via USD)."


SERVER = build_server(
    "fx-rates",
    (
        Tool(
            "Get the daily USD reference rate for a currency on a business date, for "
            "example EUR on 2026-11-21. Also returns the inverse rate.",
            get_rate,
        ),
        Tool(
            "Convert an amount from one currency to another on a business date using the "
            "daily reference rates.",
            convert,
        ),
    ),
)

if __name__ == "__main__":
    run("fx-rates", SERVER)
