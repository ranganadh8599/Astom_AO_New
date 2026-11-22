"""Calligraphy agent: scripts, tools and practice method."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "calligraphy",
    skills=(
        Skill(
            id="scripts",
            name="Historical scripts",
            description=(
                "Italic, Copperplate, Foundational, Uncial and Blackletter, with the period "
                "and character of each."
            ),
            tags=("italic", "copperplate", "blackletter"),
            keywords=(
                "script", "scripts", "italic", "copperplate", "foundational", "uncial",
                "blackletter", "gothic", "roman", "spencerian", "hand", "alphabet",
            ),
            text=(
                "Italic (Cancellaresca) is a narrow, fast humanist hand with a slight slant. "
                "Foundational is Edward Johnston's 20th-century round hand, the usual starting "
                "point for broad-edge work. Uncial is the wide, rounded book hand of late "
                "antiquity. Copperplate and Spencerian are pointed-pen scripts built on "
                "shaded strokes and hairline joins. Blackletter (Textura) is dense and "
                "angular, with broken vertical strokes."
            ),
        ),
        Skill(
            id="tools",
            name="Nibs, ink and paper",
            description=(
                "Nib width units, broad-edge versus pointed pens, ink choice and paper sizing."
            ),
            tags=("nib", "ink", "paper"),
            keywords=(
                "nib", "nibs", "pen", "broad", "edge", "pointed", "oblique", "ink", "paper",
                "sizing", "bleed", "feather", "gouache", "walnut", "holder",
            ),
            text=(
                "Broad-edge nibs come in widths measured in millimetres, and x-height is "
                "commonly 4-5 nib widths for Italic. Pointed nibs need a flexible tine for "
                "shading and an oblique holder for Copperplate's angled slant. Iron-gall inks "
                "darken with age but are acidic; walnut ink and gouache are safer for practice "
                "and archival work. Sized paper (hot-press watercolour or layout bond) stops "
                "feathering; unsized paper bleeds."
            ),
        ),
        Skill(
            id="practice",
            name="Practice method",
            description=(
                "Guidelines, slant, letter spacing and drills that build consistency."
            ),
            tags=("practice", "guidelines", "drills"),
            keywords=(
                "practice", "drill", "drills", "guideline", "guidelines", "slant", "spacing",
                "x-height", "consistency", "warm", "warmup", "ruler", "pencil",
            ),
            text=(
                "Rule guidelines for baseline, x-height, ascender and descender, plus a slant "
                "line at the script's angle, and never practise without them until the "
                "proportions are automatic. Warm up with oval and straight-line drills across "
                "the page. Work one letter at a time in a short sequence (i, l, n, m) so "
                "spacing and rhythm carry over, and judge the page from arm's length where "
                "inconsistency is obvious."
            ),
        ),
    ),
)
