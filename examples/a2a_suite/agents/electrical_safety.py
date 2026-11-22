"""Electrical safety agent: RCDs, earthing and safe isolation."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "electrical-safety",
    skills=(
        Skill(
            id="rcd",
            name="Residual current devices",
            description=(
                "How an RCD detects earth leakage, trip thresholds and times, testing and "
                "discrimination."
            ),
            tags=("rcd", "leakage", "protection"),
            keywords=(
                "rcd", "rcbo", "residual", "current", "leakage", "earth", "trip", "30ma",
                "30", "ma", "test", "button", "discrimination", "nuisance",
            ),
            text=(
                "An RCD compares live and neutral current and trips when the difference (earth "
                "leakage) exceeds its rating. For additional protection of socket outlets, "
                "30 mA is the limit and it must trip within 300 ms at rated current, faster at "
                "higher leakage. Press the test button quarterly; it proves the mechanism, not "
                "the wiring, so an electrician still needs to test trip times. Nuisance "
                "tripping usually means accumulated leakage from several appliances, not a "
                "faulty device."
            ),
        ),
        Skill(
            id="earthing",
            name="Earthing and bonding",
            description=(
                "TN and TT systems, protective conductors, main bonding and earth loop "
                "impedance."
            ),
            tags=("earthing", "tn-tt", "bonding"),
            keywords=(
                "earth", "earthing", "ground", "grounding", "bonding", "bond", "tt", "tn",
                "tn-s", "tn-c-s", "loop", "impedance", "ze", "conductor", "fault",
            ),
            text=(
                "In a TN-S or TN-C-S system the supply provides the earth path; in a TT system "
                "the installation uses its own earth electrode and must be RCD-protected "
                "because loop impedance is high. Main protective bonding connects incoming "
                "metal services (water, gas) to the main earthing terminal with a conductor "
                "sized to the supply. Earth fault loop impedance (Zs) must be low enough for "
                "the protective device to disconnect within the required time."
            ),
        ),
        Skill(
            id="isolation",
            name="Safe isolation",
            description=(
                "The lock-off and prove-dead procedure before working on a circuit."
            ),
            tags=("isolation", "lock-off", "prove-dead"),
            keywords=(
                "isolate", "isolation", "lock", "lockout", "tag", "prove", "dead", "tester",
                "voltage", "multimeter", "permit", "steps",
            ),
            text=(
                "Identify the circuit, isolate it at the correct device, lock off and tag with "
                "a unique key held by the person working. Then prove the tester on a known "
                "live source, test all conductors at the point of work (line-neutral, "
                "line-earth, neutral-earth), and prove the tester again. Only after a second "
                "person confirms the isolation should work begin, and never rely on a "
                "functional switch or a label alone."
            ),
        ),
    ),
)
