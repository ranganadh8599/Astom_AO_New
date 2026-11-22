"""Bicycle repair agent: drivetrain, brakes, wheels and tyres."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "bicycle-repair",
    skills=(
        Skill(
            id="drivetrain",
            name="Drivetrain wear and shifting",
            description=(
                "Chain wear measurement, cassette and chainring replacement, derailleur "
                "limit screws and cable tension."
            ),
            tags=("chain", "cassette", "derailleur", "shifting"),
            keywords=(
                "chain", "cassette", "derailleur", "shift", "shifting", "sprocket",
                "stretch", "wear", "indexing", "cable",
            ),
            text=(
                "Measure chain wear with a 0.5% / 0.75% gauge. Past 0.5% on an 11- or "
                "12-speed drivetrain, fit a new chain before it rounds the cassette teeth; "
                "past 0.75% on older 8-10 speed systems the cassette usually needs replacing "
                "too. For poor shifting, check hanger alignment first, then set the low and "
                "high limit screws, then cable tension, then indexing one gear at a time."
            ),
        ),
        Skill(
            id="brakes",
            name="Rim and disc brakes",
            description=(
                "Pad and rotor wear limits, bedding in new pads, rotor truing and hydraulic "
                "brake bleeding."
            ),
            tags=("brakes", "pads", "rotor", "hydraulic"),
            keywords=(
                "brake", "brakes", "pad", "pads", "rotor", "disc", "rim", "hydraulic",
                "bleed", "bleeding", "cable", "rub", "squeal",
            ),
            text=(
                "Replace disc pads at roughly 0.5 mm of pad material, and rotors below the "
                "manufacturer's minimum thickness (often 1.5 mm). Bed in new pads with 10-20 "
                "moderate stops from about 25 km/h, never one hard stop. A rubbing rotor is "
                "usually a bent disc: true it with a rotor tool in small increments. "
                "Hydraulic levers that feel spongy need a bleed, and mineral oil and DOT "
                "fluid systems are not interchangeable."
            ),
        ),
        Skill(
            id="wheels",
            name="Wheels and tyres",
            description=(
                "Spoke tension and wheel truing, tubeless setup, tyre pressure and sidewall "
                "inspection."
            ),
            tags=("wheel", "spokes", "tyre", "tubeless"),
            keywords=(
                "wheel", "wheels", "spoke", "spokes", "true", "truing", "tyre", "tire",
                "tubeless", "pressure", "rim", "puncture", "sealant",
            ),
            text=(
                "A wheel is true when the rim runs evenly past both brake pads with spokes "
                "under even tension; tighten a quarter turn at a time and re-check. Tubeless "
                "tyres need a clean rim bed, two layers of tape, a valve with an intact "
                "grommet and 60-120 ml of sealant, then a fast burst of air to seat the bead. "
                "For 28-32 mm road tyres, 4.5-5.5 bar (65-80 psi) suits most riders; wider "
                "tyres run lower, and hookless rims have a hard maximum printed on the rim."
            ),
        ),
    ),
)
