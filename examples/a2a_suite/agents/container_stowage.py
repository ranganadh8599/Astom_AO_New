"""Container stowage agent: lashing, weight and dangerous goods."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "container-stowage",
    skills=(
        Skill(
            id="lashing",
            name="Lashing and securing",
            description=(
                "Twist locks, lashing rods, stack weight limits and securing for heavy "
                "weather."
            ),
            tags=("lashing", "twist-lock", "stack"),
            keywords=(
                "lash", "lashing", "rod", "rods", "twist", "lock", "locks", "secure",
                "securing", "stack", "tier", "deck", "weather", "iso", "corner", "casting",
            ),
            text=(
                "Containers are secured by twist locks between tiers and by lashing rods from "
                "the deck stack to the hatch cover or lashing bridge. Stack weight limits come "
                "from the container's ISO rating, the corner casting strength and the ship's "
                "stacking plan; exceeding them crushes the bottom box. Lashing plans are "
                "recalculated for each voyage based on stack height, container weight and the "
                "expected sea state."
            ),
        ),
        Skill(
            id="weight",
            name="Weight distribution and VGM",
            description=(
                "Verified gross mass, heavy-at-the-bottom stowage, GM and stability."
            ),
            tags=("vgm", "stability", "weight"),
            keywords=(
                "weight", "mass", "vgm", "gross", "solas", "heavy", "stability", "gm",
                "ballast", "trim", "list", "distribution", "payload", "overweight",
            ),
            text=(
                "SOLAS requires a Verified Gross Mass for every packed container before "
                "loading, either by weighing the packed box or by weighing cargo and adding "
                "tare. Stow heavy containers low and near the middle to keep the vertical "
                "centre of gravity low and the GM positive. Weight distribution affects list, "
                "trim and hull stress; a mis-declared box is the most common cause of stack "
                "collapse."
            ),
        ),
        Skill(
            id="dangerous-goods",
            name="Dangerous goods segregation",
            description=(
                "IMDG classes, the segregation table and stowage away from heat and living "
                "quarters."
            ),
            tags=("imdg", "segregation", "hazmat"),
            keywords=(
                "dangerous", "danger", "dg", "imdg", "hazard", "hazmat", "class", "classes",
                "segregation", "segregate", "flammable", "explosive", "corrosive", "placard",
                "declaration",
            ),
            text=(
                "The IMDG Code splits dangerous goods into nine classes (1 explosives, 2 "
                "gases, 3 flammable liquids, 4 flammables, 5 oxidisers, 6 toxic/infectious, 7 "
                "radioactive, 8 corrosives, 9 miscellaneous). The segregation table sets "
                "minimum separation: 'away from', 'separated from', 'separated by a complete "
                "compartment or hold'. Class 1 and 7 have their own stowage rules, and "
                "reactive goods must sit away from heat sources and living quarters."
            ),
        ),
    ),
)
