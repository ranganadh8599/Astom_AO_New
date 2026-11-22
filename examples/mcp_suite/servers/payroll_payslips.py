"""Payroll payslips MCP server: gross, deductions and net pay per employee."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

PAYSLIPS: dict[str, dict[str, object]] = {
    "E-1042": {
        "name": "A. Fernandes",
        "period": "2026-10",
        "gross": 4820.00,
        "deductions": 1318.40,
        "ytd_gross": 48200.00,
    },
    "E-2210": {
        "name": "M. Okafor",
        "period": "2026-10",
        "gross": 6150.00,
        "deductions": 1742.50,
        "ytd_gross": 61500.00,
    },
    "E-3377": {
        "name": "S. Iyer",
        "period": "2026-10",
        "gross": 3990.00,
        "deductions": 1010.20,
        "ytd_gross": 39900.00,
    },
}


def get_payslip(employee_id: str) -> str:
    """Return the latest payslip lines for one employee."""
    key = employee_id.strip().upper()
    row = PAYSLIPS.get(key)
    if row is None:
        known = ", ".join(sorted(PAYSLIPS))
        return f"No payslip for employee {key}. Employees on file: {known}."
    net = float(row["gross"]) - float(row["deductions"])
    return (
        f"Payslip {row['period']} for {row['name']} ({key}): gross {row['gross']:.2f}, "
        f"deductions {row['deductions']:.2f}, net {net:.2f}, year-to-date gross "
        f"{row['ytd_gross']:.2f}."
    )


def get_deductions(employee_id: str) -> str:
    """Return only the deduction total and the resulting net pay."""
    key = employee_id.strip().upper()
    row = PAYSLIPS.get(key)
    if row is None:
        known = ", ".join(sorted(PAYSLIPS))
        return f"No payslip for employee {key}. Employees on file: {known}."
    net = float(row["gross"]) - float(row["deductions"])
    return (
        f"{key} ({row['name']}) deductions for {row['period']} total "
        f"{row['deductions']:.2f}, giving net pay {net:.2f}."
    )


SERVER = build_server(
    "payroll-payslips",
    (
        Tool(
            "Get the latest payslip for an employee by employee ID, such as E-1042: gross "
            "pay, total deductions, net pay and year-to-date gross.",
            get_payslip,
        ),
        Tool(
            "Get just the deduction total and net pay for an employee's latest pay period.",
            get_deductions,
        ),
    ),
)

if __name__ == "__main__":
    run("payroll-payslips", SERVER)
