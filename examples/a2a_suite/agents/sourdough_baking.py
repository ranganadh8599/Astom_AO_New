"""Sourdough baking agent: starter, bulk fermentation and the bake."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "sourdough-baking",
    skills=(
        Skill(
            id="starter",
            name="Maintaining a starter",
            description=(
                "Feeding ratios, rise timing, temperature, float test and reviving a weak "
                "starter."
            ),
            tags=("starter", "levain", "feeding"),
            keywords=(
                "starter", "levain", "feed", "feeding", "flour", "float", "rise", "hooch",
                "active", "yeast",
            ),
            text=(
                "Feed a mature starter at 1:1:1 by weight (starter:flour:water) and it should "
                "double in 4-6 hours at 24-26 C. A 1:5:5 feed slows it down and suits an "
                "overnight schedule. It is ready when domed, bubbly and it floats in water. "
                "Dark liquid on top is alcohol (hooch), not spoilage: pour it off, feed twice "
                "daily for two days, and the culture recovers."
            ),
        ),
        Skill(
            id="bulk",
            name="Bulk fermentation",
            description=(
                "Dough temperature, fermentation time, aliquot jars, fold schedule and how "
                "to judge when bulk is finished."
            ),
            tags=("bulk", "ferment", "folds"),
            keywords=(
                "bulk", "ferment", "fermentation", "proof", "rise", "fold", "folds",
                "temperature", "aliquot", "dough", "hydration", "autolyse",
            ),
            text=(
                "Hold dough at 24-26 C for bulk fermentation: typically 4-6 hours with 20% "
                "starter, longer when cold. Judge by rise, not the clock — 50-75% growth in an "
                "aliquot jar, a domed surface and a few bubbles at the edges. Do 4 sets of "
                "stretch-and-folds 30 minutes apart in the first two hours, then leave it "
                "alone. Higher hydration doughs need more folds, not more time."
            ),
        ),
        Skill(
            id="bake",
            name="Shaping and baking",
            description=(
                "Pre-shape and final shape, cold retard, scoring, oven temperature, steam and "
                "internal temperature."
            ),
            tags=("shaping", "scoring", "bake", "steam"),
            keywords=(
                "shape", "shaping", "bake", "baking", "oven", "steam", "score", "scoring",
                "dutch", "retard", "fridge", "crust", "temperature", "crumb",
            ),
            text=(
                "Pre-shape, rest 20-30 minutes, then shape tightly and retard in the fridge "
                "12-16 hours for flavour and easier scoring. Bake in a preheated Dutch oven at "
                "250 C for 20 minutes with the lid on, then 20-25 minutes at 230 C uncovered. "
                "Score at a shallow 30-degree angle just before it goes in. The loaf is done "
                "at an internal temperature of 96-99 C, and it must cool fully before slicing "
                "or the crumb turns gummy."
            ),
        ),
    ),
)
