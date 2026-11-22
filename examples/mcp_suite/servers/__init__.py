"""Server modules for the MCP example suite.

Each module builds its own ``MCPServer`` at import time and runs it when executed directly:

    python -m mcp_suite.servers.warehouse_inventory --port 9301

Run one at a time; nothing here is imported by the orchestrator.
"""

from __future__ import annotations

__all__ = [
    "warehouse_inventory",
    "payroll_payslips",
    "flight_status",
    "hotel_availability",
    "library_catalogue",
    "lab_sample_tracking",
    "fleet_telematics",
    "clinic_appointments",
    "support_queue",
    "fx_rates",
    "subscription_billing",
    "crop_harvest",
    "water_quality",
    "parcel_tracking",
    "meeting_rooms",
    "bridge_inspection",
    "customs_tariff",
    "course_completions",
    "parking_occupancy",
    "cold_chain_temperature",
]
