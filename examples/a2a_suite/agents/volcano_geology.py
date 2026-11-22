"""Volcano geology agent: eruption styles, hazards and monitoring."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "volcano-geology",
    skills=(
        Skill(
            id="eruption-style",
            name="Eruption styles",
            description=(
                "Effusive versus explosive activity, magma viscosity and the volcanic "
                "explosivity index."
            ),
            tags=("effusive", "explosive", "vei"),
            keywords=(
                "eruption", "effusive", "explosive", "lava", "magma", "viscosity", "vei",
                "plinian", "hawaiian", "strombolian", "basalt", "rhyolite", "andesite",
                "fissure", "caldera",
            ),
            text=(
                "Low-viscosity basalt degasses easily and produces effusive lava flows and "
                "fountains (Hawaiian, Strombolian style). High-viscosity andesite or rhyolite "
                "traps gas until it fragments violently, giving Vulcanian to Plinian columns "
                "and ignimbrites. The Volcanic Explosivity Index runs 0-8 on volume and column "
                "height; VEI 6 and above (Pinatubo 1991, Tambora 1815) can affect global "
                "climate for years through sulphate aerosols."
            ),
        ),
        Skill(
            id="hazards",
            name="Volcanic hazards",
            description=(
                "Pyroclastic density currents, lahars, ash fall, volcanic gas and sector "
                "collapse."
            ),
            tags=("hazards", "lahar", "ash"),
            keywords=(
                "hazard", "hazards", "pyroclastic", "density", "current", "lahar", "mudflow",
                "ash", "tephra", "gas", "so2", "co2", "collapse", "tsunami", "evacuation",
            ),
            text=(
                "Pyroclastic density currents are the deadliest hazard: ground-hugging mixtures "
                "of gas and ash that can exceed 100 km/h and 400 C, so evacuation must precede "
                "them. Lahars are volcanic mudflows, often triggered by rain on fresh ash or "
                "by sudden snowmelt, and they can travel tens of kilometres down valleys long "
                "after the eruption ends. Ash fall closes airports and collapses roofs at "
                "around 100 kg/m2; SO2 and CO2 are hazards in low-lying ground and calderas."
            ),
        ),
        Skill(
            id="monitoring",
            name="Volcano monitoring",
            description=(
                "Seismicity, ground deformation, gas flux and thermal signals, and what each "
                "precursor means."
            ),
            tags=("monitoring", "seismicity", "deformation"),
            keywords=(
                "monitor", "monitoring", "seismic", "seismicity", "earthquake", "tremor",
                "deformation", "gnss", "insar", "tilt", "gas", "flux", "thermal", "precursor",
                "observatory", "alert",
            ),
            text=(
                "Observatories combine four signals. Volcanic earthquakes and harmonic tremor "
                "track magma movement and gas escape. GNSS and InSAR measure inflation and "
                "deflation, often centimetres before an eruption. Gas flux (SO2 by "
                "spectrometer, CO2 by soil probes) shows whether magma is degassing or "
                "stalled. Thermal and satellite imagery detect new hotspots. No single "
                "precursor is reliable; the pattern across all four drives alert levels."
            ),
        ),
    ),
)
