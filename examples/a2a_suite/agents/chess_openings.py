"""Chess openings agent: principles, 1.e4 and 1.d4 repertoires."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "chess-openings",
    skills=(
        Skill(
            id="principles",
            name="Opening principles",
            description=(
                "Centre control, development tempo, king safety and the pawn moves to avoid "
                "early."
            ),
            tags=("principles", "development", "centre"),
            keywords=(
                "principle", "principles", "centre", "center", "develop", "development",
                "tempo", "castle", "castling", "pawn", "move", "opening", "openings",
            ),
            text=(
                "Control the centre with pawns, develop knights and bishops toward it, castle "
                "within the first ten moves, connect the rooks, then choose a plan. Do not move "
                "the same piece twice without reason, do not bring the queen out early, and do "
                "not grab pawns that cost development. A lead in development is worth more than "
                "a pawn in the opening."
            ),
        ),
        Skill(
            id="e4",
            name="1.e4 openings",
            description=(
                "Italian Game, Ruy Lopez, Sicilian Defence, French Defence and Caro-Kann, with "
                "the idea behind each."
            ),
            tags=("e4", "italian", "sicilian", "ruy-lopez"),
            keywords=(
                "e4", "italian", "ruy", "lopez", "sicilian", "french", "caro", "kann",
                "king", "pawn", "open", "game", "najdorf", "dragon",
            ),
            text=(
                "After 1.e4 e5, the Italian (3.Bc4) aims at f7 with a slow build-up, while the "
                "Ruy Lopez (3.Bb5) pressures the knight defending e5 and asks Black to solve "
                "structural questions early. Against 1...c5 the Sicilian fights for the centre "
                "asymmetrically, giving Black counterplay on the queenside in exchange for "
                "space; the Open Sicilian (2.Nf3, 3.d4) is the main line. The French "
                "(1...e6) accepts a cramped position to attack the e4 pawn with ...d5 and "
                "...c5, and the Caro-Kann (1...c6) does the same while keeping the "
                "light-squared bishop free."
            ),
        ),
        Skill(
            id="d4",
            name="1.d4 openings",
            description=(
                "Queen's Gambit, Slav, Nimzo-Indian, King's Indian and Catalan, and the "
                "structures they create."
            ),
            tags=("d4", "queens-gambit", "nimzo", "kings-indian"),
            keywords=(
                "d4", "queen", "gambit", "slav", "nimzo", "indian", "catalan", "london",
                "grunfeld", "closed", "structure", "isolani",
            ),
            text=(
                "The Queen's Gambit (2.c4) offers the c-pawn to deflect Black's d5 pawn and "
                "dominate the centre; the Slav (...c6) holds d5 with a pawn chain. The "
                "Nimzo-Indian (1.d4 Nf6 2.c4 e6 3.Nc3 Bb4) fights for e4 by pinning the "
                "knight, and the King's Indian concedes space to strike with ...e5 or ...c5. "
                "The Catalan combines a fianchettoed bishop with a queenside push and tends to "
                "produce long positional games, and the London System offers White a low-theory "
                "setup with Bf4, e3, c3 and Bd3."
            ),
        ),
    ),
)
