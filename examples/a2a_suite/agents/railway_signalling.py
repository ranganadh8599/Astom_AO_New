"""Railway signalling agent: block working, interlocking and aspects."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "railway-signalling",
    skills=(
        Skill(
            id="block",
            name="Block working",
            description=(
                "Absolute block, track circuit block and token working, and why one train per "
                "block."
            ),
            tags=("block", "track-circuit", "token"),
            keywords=(
                "block", "blocks", "absolute", "track", "circuit", "token", "section",
                "occupancy", "occupied", "signalman", "bell", "permissive", "headway",
            ),
            text=(
                "In absolute block working the signalman must receive 'line clear' from the box "
                "ahead before accepting a train, so only one train occupies a block at a time. "
                "Track circuit block replaces the human check with continuous detection: a "
                "train shorting the rails proves occupancy and holds the signal at danger. "
                "Token systems hand a physical or electronic token to the driver, which is "
                "required to enter a single-line section."
            ),
        ),
        Skill(
            id="interlocking",
            name="Interlocking and route setting",
            description=(
                "Route locking, flank protection, approach locking and why conflicting routes "
                "cannot be set."
            ),
            tags=("interlocking", "route", "locking"),
            keywords=(
                "interlock", "interlocking", "route", "setting", "lock", "locking", "flank",
                "protection", "approach", "conflicting", "points", "switch", "signal",
                "lever", "panel",
            ),
            text=(
                "An interlocking mechanically or electrically prevents conflicting routes: "
                "setting a route locks the points in position and locks out any route that "
                "would foul it. Flank protection sets points to derail or block an unauthorised "
                "movement into the protected route. Approach locking prevents a signal being "
                "replaced to danger under a train that is already too close to stop, so the "
                "route cannot be pulled until the train has passed or timed out."
            ),
        ),
        Skill(
            id="aspects",
            name="Signal aspects and cab signalling",
            description=(
                "Two-, three- and four-aspect signalling, distant versus home signals, and "
                "ETCS levels."
            ),
            tags=("aspect", "distant", "etcs"),
            keywords=(
                "aspect", "aspects", "signal", "signals", "distant", "home", "starter",
                "green", "yellow", "red", "double", "colour", "light", "etcs", "atp",
                "balise", "cab", "movement",
            ),
            text=(
                "A two-aspect system shows red or green and gives braking distance by signal "
                "spacing; three-aspect adds yellow (caution, next signal at danger); "
                "four-aspect adds double yellow, allowing higher speeds with shorter blocks. A "
                "home signal controls entry to a block section and a distant signal warns of "
                "its aspect. In cab signalling the movement authority is displayed in the cab: "
                "ETCS Level 1 uses balises with lineside signals, Level 2 uses continuous radio "
                "with optional signals, and Level 3 allows moving block."
            ),
        ),
    ),
)
