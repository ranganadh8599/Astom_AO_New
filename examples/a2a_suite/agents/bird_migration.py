"""Bird migration agent: flyways, timing and navigation."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "bird-migration",
    skills=(
        Skill(
            id="flyways",
            name="Migration flyways",
            description=(
                "The major global flyways, and why coasts and mountain passes concentrate "
                "migrants."
            ),
            tags=("flyway", "routes", "corridors"),
            keywords=(
                "flyway", "flyways", "route", "routes", "corridor", "coast", "pass",
                "atlantic", "mississippi", "pacific", "black", "sea", "asia", "australasia",
            ),
            text=(
                "The recognised flyways are the East Atlantic, Mediterranean/Black Sea, East "
                "Asia/Australasian, Pacific Americas and Mississippi Americas, plus the Central "
                "Asian corridor. Migrants funnel along coastlines, ridgelines and river "
                "valleys because thermals and food are concentrated there; a headland after "
                "an overnight crossing can hold thousands of tired birds."
            ),
        ),
        Skill(
            id="timing",
            name="Timing and stopovers",
            description=(
                "Spring versus autumn migration, photoperiod cues, Zugunruhe and refuelling at "
                "stopover sites."
            ),
            tags=("timing", "season", "stopover"),
            keywords=(
                "timing", "time", "spring", "autumn", "fall", "season", "photoperiod",
                "zugunruhe", "stopover", "refuel", "fat", "arrival", "departure",
            ),
            text=(
                "Spring migration is usually faster and more urgent because birds race to "
                "breeding territories; autumn is slower and more spread out, with juveniles "
                "wandering. Lengthening or shortening day length triggers migratory "
                "restlessness (Zugunruhe) and fat deposition. Stopover sites matter as much "
                "as breeding grounds: a small warbler may double its mass in fat before a "
                "single 600 km hop over water."
            ),
        ),
        Skill(
            id="navigation",
            name="Navigation",
            description=(
                "The compass cues birds use: geomagnetism, the sun, the stars and smell."
            ),
            tags=("navigation", "compass", "magnetoreception"),
            keywords=(
                "navigate", "navigation", "compass", "magnetic", "geomagnetic", "sun",
                "stars", "star", "olfaction", "smell", "orientation", "cryptochrome",
            ),
            text=(
                "Migrating birds combine several cues: a magnetic compass sensed through "
                "cryptochrome in the retina, a time-compensated sun compass, a star compass "
                "learned as nestlings and calibrated against the magnetic field, plus "
                "landscape and olfactory information. No single sense explains navigation; "
                "experiments that disrupt one usually show the others compensating."
            ),
        ),
    ),
)
