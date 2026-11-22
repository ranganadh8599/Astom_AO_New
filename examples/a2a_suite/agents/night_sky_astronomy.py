"""Night-sky astronomy agent: constellations, planets and observing conditions."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "night-sky-astronomy",
    skills=(
        Skill(
            id="constellations",
            name="Seasonal constellations",
            description=(
                "Which constellations are up in each season, star hopping, and finding "
                "Polaris."
            ),
            tags=("constellation", "season", "polaris"),
            keywords=(
                "constellation", "constellations", "orion", "cygnus", "lyra", "leo",
                "scorpius", "polaris", "dipper", "star", "stars", "season", "sky",
            ),
            text=(
                "Winter evenings show Orion, Taurus and Canis Major; spring brings Leo and "
                "Virgo; summer evenings belong to Cygnus, Lyra and Aquila (the Summer "
                "Triangle); autumn shows Pegasus and Andromeda. To find north, follow the two "
                "outer stars of the Big Dipper's bowl about five times their separation to "
                "Polaris, which sits within one degree of the celestial pole."
            ),
        ),
        Skill(
            id="planets",
            name="Planet visibility",
            description=(
                "When planets are visible, opposition and greatest elongation, and why Venus "
                "shows phases."
            ),
            tags=("planet", "opposition", "elongation"),
            keywords=(
                "planet", "planets", "jupiter", "saturn", "mars", "venus", "mercury",
                "opposition", "elongation", "conjunction", "retrograde", "phases",
            ),
            text=(
                "A superior planet is best placed at opposition, when it rises at sunset and "
                "is closest and brightest; Jupiter and Saturn reach opposition roughly every "
                "13 and 12.5 months. Mercury and Venus are inner planets, so they never "
                "wander far from the Sun: look for them at greatest elongation, low in twilight. "
                "Venus shows crescent-to-gibbous phases through a small telescope because we "
                "see its illuminated hemisphere at changing angles."
            ),
        ),
        Skill(
            id="observing",
            name="Observing conditions",
            description=(
                "Dark adaptation, red light, the Bortle scale, and the difference between "
                "seeing and transparency."
            ),
            tags=("dark-adaptation", "bortle", "seeing"),
            keywords=(
                "dark", "adaptation", "adapt", "red", "light", "bortle", "pollution",
                "seeing", "transparency", "telescope", "magnification", "moon", "turbulence",
            ),
            text=(
                "Full dark adaptation takes 20-30 minutes; use only dim red light after that "
                "and one white torch undoes it. The Bortle scale runs 1 (pristine) to 9 (inner "
                "city) and Bortle 4 or better is needed for the Milky Way. Seeing is "
                "atmospheric steadiness and limits high magnification on planets; "
                "transparency is clarity and limits faint deep-sky objects. Poor seeing wants "
                "lower power, not more."
            ),
        ),
    ),
)
