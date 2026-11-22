"""Beekeeping agent: seasonal work, swarm control and harvest."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "beekeeping",
    skills=(
        Skill(
            id="seasonal",
            name="Seasonal management",
            description=(
                "Spring build-up, summer supers, autumn feeding and the winter cluster."
            ),
            tags=("season", "spring", "winter"),
            keywords=(
                "season", "seasonal", "spring", "summer", "autumn", "fall", "winter",
                "cluster", "build", "build-up", "feed", "feeding", "syrup", "fondant",
                "overwinter", "dearth",
            ),
            text=(
                "Spring is for build-up: check food stores, add space before the colony is "
                "crowded, and watch for swarm cells from April. Summer is for supers and "
                "monitoring for varroa; a strong colony can fill a super in two weeks. In "
                "autumn feed thick syrup (2:1) early enough for the bees to ripen and cap it, "
                "then treat for varroa. In winter disturb as little as possible; the cluster "
                "keeps the queen at about 35 C and consumes stored honey."
            ),
        ),
        Skill(
            id="swarm",
            name="Swarm prevention",
            description=(
                "Inspection interval, queen cells, splits and the Demaree method."
            ),
            tags=("swarm", "queen-cells", "splits"),
            keywords=(
                "swarm", "swarming", "queen", "cell", "cells", "inspect", "inspection",
                "split", "nuc", "demaree", "supersedure", "queenless", "laying",
            ),
            text=(
                "Inspect every 7-9 days from spring, because a colony can raise a queen cell "
                "to a sealed cell in eight days. Finding charged queen cells means swarm "
                "preparation is already under way: remove them and either split the colony or "
                "Demaree it (move the queen down, place a queen excluder, and put the brood "
                "above). Swarm cells hang from the comb edges; supersedure cells sit on the "
                "face and are usually fewer."
            ),
        ),
        Skill(
            id="harvest",
            name="Honey harvest",
            description=(
                "Capped frames, refractometer readings, extracting, filtering and leaving "
                "enough stores."
            ),
            tags=("honey", "harvest", "extracting"),
            keywords=(
                "honey", "harvest", "extract", "extracting", "refractometer", "capped",
                "uncapping", "spinner", "filter", "moisture", "stores", "super", "frames",
            ),
            text=(
                "Harvest only capped frames: uncapped honey ferments. Check moisture with a "
                "refractometer and aim below 18% (17% for long storage). Uncapping and "
                "spinning is best done in a warm room, and honey should be filtered and left "
                "to settle before jarring. Always leave enough stores for the colony — "
                "typically a full super or the equivalent in the brood box — and never take "
                "honey from a colony that has not built up properly."
            ),
        ),
    ),
)
