"""The 20 servers in the MCP test suite — one data domain each, no shared vocabulary.

Each server answers *lookup* questions over a small deterministic fixture: stock levels,
flight status, meter readings and so on. The domains are deliberately unrelated to each
other and to the A2A suite, so a retrieval result can only be explained by the card text.

Ports 9301-9320 (9200 is the field-ops sample).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServerEntry:
    id: str
    name: str
    title: str
    port: int
    description: str


SERVERS: tuple[ServerEntry, ...] = (
    ServerEntry(
        id="warehouse-inventory",
        name="warehouse-inventory",
        title="Warehouse inventory",
        port=9301,
        description=(
            "Stock lookups for a distribution warehouse: on-hand quantity per SKU, the bin "
            "location holding it, and which SKUs have fallen below their reorder point."
        ),
    ),
    ServerEntry(
        id="payroll-payslips",
        name="payroll-payslips",
        title="Payroll payslips",
        port=9302,
        description=(
            "Employee payslip lines for a pay period: gross pay, deductions, net pay and "
            "year-to-date totals for one employee."
        ),
    ),
    ServerEntry(
        id="flight-status",
        name="flight-status",
        title="Flight status",
        port=9303,
        description=(
            "Live airline flight status by flight number: scheduled and actual departure, "
            "gate, terminal and delay reason."
        ),
    ),
    ServerEntry(
        id="hotel-availability",
        name="hotel availability",
        title="Hotel availability",
        port=9304,
        description=(
            "Room availability and nightly rates for a hotel on given dates, broken down by "
            "room type."
        ),
    ),
    ServerEntry(
        id="library-catalogue",
        name="library-catalogue",
        title="Library catalogue",
        port=9305,
        description=(
            "Bibliographic lookups for a public library: title, author and shelf location for "
            "an ISBN, and whether copies are on loan."
        ),
    ),
    ServerEntry(
        id="lab-sample-tracking",
        name="lab-sample-tracking",
        title="Laboratory sample tracking",
        port=9306,
        description=(
            "Status of clinical laboratory specimens by sample ID: collection time, current "
            "analyser stage and whether results are released."
        ),
    ),
    ServerEntry(
        id="fleet-telematics",
        name="fleet-telematics",
        title="Fleet telematics",
        port=9307,
        description=(
            "Vehicle telematics for a delivery fleet: odometer, fuel level, last known "
            "position and open engine fault codes by registration."
        ),
    ),
    ServerEntry(
        id="clinic-appointments",
        name="clinic appointments",
        title="Clinic appointments",
        port=9308,
        description=(
            "Outpatient appointment slots by clinic and date: free times, booked times and the "
            "practitioner assigned."
        ),
    ),
    ServerEntry(
        id="support-queue",
        name="support-queue",
        title="Support queue",
        port=9309,
        description=(
            "Service-desk ticket state by ticket ID: priority, assignee, age and how long "
            "until the response SLA is breached."
        ),
    ),
    ServerEntry(
        id="fx-rates",
        name="fx-rates",
        title="FX rates",
        port=9310,
        description=(
            "Foreign exchange reference rates for a currency pair on a business date, with the "
            "inverse rate and the daily change."
        ),
    ),
    ServerEntry(
        id="subscription-billing",
        name="subscription-billing",
        title="Subscription billing",
        port=9311,
        description=(
            "SaaS subscription state for an account: plan name, number of seats, renewal date "
            "and the next invoice amount."
        ),
    ),
    ServerEntry(
        id="crop-harvest",
        name="crop-harvest",
        title="Crop harvest",
        port=9312,
        description=(
            "Harvest records for arable fields: crop variety, harvested tonnage, moisture "
            "percentage and yield per hectare for a field and season."
        ),
    ),
    ServerEntry(
        id="water-quality",
        name="water quality",
        title="Water quality",
        port=9313,
        description=(
            "Drinking-water treatment readings by plant: chlorine residual, pH, turbidity and "
            "the time of the last sample."
        ),
    ),
    ServerEntry(
        id="parcel-tracking",
        name="parcel tracking",
        title="Parcel tracking",
        port=9314,
        description=(
            "Parcel movement history by consignment number: scan events, current depot and the "
            "promised delivery date."
        ),
    ),
    ServerEntry(
        id="meeting-rooms",
        name="meeting rooms",
        title="Meeting rooms",
        port=9315,
        description=(
            "Bookable meeting-room availability for an office floor: capacity, equipment and "
            "which slots are already taken."
        ),
    ),
    ServerEntry(
        id="bridge-inspection",
        name="bridge inspection",
        title="Bridge inspection",
        port=9316,
        description=(
            "Structural inspection findings for road bridges by asset number: last inspection "
            "date, defect severity and recommended action."
        ),
    ),
    ServerEntry(
        id="customs-tariff",
        name="customs tariff",
        title="Customs tariff",
        port=9317,
        description=(
            "Customs classification lookup: the HS commodity code for a product description "
            "and the duty rate that applies."
        ),
    ),
    ServerEntry(
        id="course-completions",
        name="course completions",
        title="Course completions",
        port=9318,
        description=(
            "Training records by employee: which compliance courses were completed, the score "
            "and the expiry date of the certificate."
        ),
    ),
    ServerEntry(
        id="parking-occupancy",
        name="parking occupancy",
        title="Parking occupancy",
        port=9319,
        description=(
            "Live car-park occupancy by facility: total bays, occupied bays, accessible bays "
            "free and the last sensor update."
        ),
    ),
    ServerEntry(
        id="cold-chain-temperature",
        name="cold-chain temperature",
        title="Cold-chain temperature",
        port=9320,
        description=(
            "Refrigerated shipment temperature logs by consignment: readings, min/max over the "
            "trip and whether an excursion was recorded."
        ),
    ),
)

BY_ID: dict[str, ServerEntry] = {entry.id: entry for entry in SERVERS}


def by_id(server_id: str) -> ServerEntry:
    try:
        return BY_ID[server_id]
    except KeyError:  # pragma: no cover - operator typo
        known = ", ".join(entry.id for entry in SERVERS)
        raise SystemExit(f"unknown server {server_id!r}. Known servers: {known}") from None
