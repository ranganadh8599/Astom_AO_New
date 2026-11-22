"""Knitting agent: gauge, stitch mechanics and finishing."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "knitting",
    skills=(
        Skill(
            id="gauge",
            name="Tension and gauge",
            description=(
                "Swatching, stitch and row gauge, needle sizing and how to recalculate a "
                "pattern."
            ),
            tags=("gauge", "swatch", "needles"),
            keywords=(
                "gauge", "tension", "swatch", "needle", "needles", "stitch", "row", "size",
                "fit", "blocking", "yarn", "meterage",
            ),
            text=(
                "Knit a swatch of at least 15 x 15 cm, wash and block it, then count stitches "
                "and rows over 10 cm. If you have more stitches than the pattern, go up a "
                "needle size; fewer, go down. Stitch gauge affects width and row gauge affects "
                "length, so match stitch gauge first and adjust length by row count. Yarn "
                "substitution needs both gauge and meterage to match."
            ),
        ),
        Skill(
            id="stitches",
            name="Stitch mechanics",
            description=(
                "Knit and purl, mirrored increases, decreases, short rows and picking up "
                "dropped stitches."
            ),
            tags=("increase", "decrease", "short-rows"),
            keywords=(
                "increase", "decrease", "kfb", "m1l", "m1r", "k2tog", "ssk", "yo",
                "short", "row", "wrap", "turn", "dropped", "purl", "knit", "selvedge",
            ),
            text=(
                "Use paired increases for symmetry: M1L leans left, M1R leans right, and "
                "kfb is simpler but leaves a visible bump. For paired decreases, k2tog leans "
                "right and ssk leans left; match the lean to the edge of the shaping. Short "
                "rows shape shoulders and necklines without binding off, wrapping the turning "
                "stitch so no hole appears. A dropped stitch is recoverable with a crochet "
                "hook if you ladder it back up before it runs."
            ),
        ),
        Skill(
            id="finishing",
            name="Finishing and seams",
            description=(
                "Blocking methods, mattress stitch, three-needle bind-off and picking up "
                "neckbands."
            ),
            tags=("blocking", "seaming", "finishing"),
            keywords=(
                "block", "blocking", "seam", "seams", "mattress", "graft", "kitchener",
                "bind", "neckband", "pick", "finish", "weave", "wet",
            ),
            text=(
                "Wet block wool and plant fibres: soak, roll in a towel, pin to measurements "
                "and dry flat; steam only for acrylics and superwash. Mattress stitch joins "
                "side seams invisibly, one bar of each edge at a time. Kitchener stitch grafts "
                "live stitches so the seam disappears. Pick up neckband stitches at roughly "
                "three stitches for every four rows along a vertical edge, or it will flare."
            ),
        ),
    ),
)
