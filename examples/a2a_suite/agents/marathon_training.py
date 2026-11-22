"""Marathon training agent: periodisation, long runs and the taper."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "marathon-training",
    skills=(
        Skill(
            id="periodisation",
            name="Periodisation",
            description=(
                "Base, build, peak and taper phases, weekly volume progression and the "
                "easy/hard split."
            ),
            tags=("periodisation", "volume", "phases"),
            keywords=(
                "periodisation", "periodization", "phase", "phases", "base", "build", "peak",
                "taper", "volume", "mileage", "weekly", "plan", "schedule", "intensity",
                "easy", "hard", "80/20",
            ),
            text=(
                "A typical marathon block runs 16-20 weeks: 6-8 weeks of base building, 8-10 "
                "weeks of build with marathon-pace work, a 2-3 week peak, then a 2-3 week "
                "taper. Increase weekly volume by no more than 5-10% and take a lighter week "
                "every fourth one. Keep roughly 80% of running easy (conversational) and 20% "
                "hard; most runners fail by running the easy days too fast."
            ),
        ),
        Skill(
            id="long-run",
            name="Long runs and fuelling",
            description=(
                "Long-run distance, progression, marathon-pace segments and carbohydrate "
                "intake during running."
            ),
            tags=("long-run", "fuelling", "carbs"),
            keywords=(
                "long", "run", "runs", "distance", "kilometre", "kilometres", "mile", "miles",
                "fuel", "fuelling", "fueling", "carb", "carbs", "gel", "gels", "hydrate",
                "hydration", "sodium",
            ),
            text=(
                "Cap the longest run at about 32 km or 3 hours; beyond that recovery cost "
                "outweighs the benefit. Progress the long run by 1-2 km per week and include "
                "2-3 blocks at goal marathon pace in the later ones. Practise race fuelling: "
                "30-60 g of carbohydrate per hour, taken early and often, with fluid matched to "
                "sweat loss. Never try a new gel or drink on race day."
            ),
        ),
        Skill(
            id="taper",
            name="Taper and race week",
            description=(
                "How much volume to cut, which intensity to keep, sleep and the last few days."
            ),
            tags=("taper", "race-week", "recovery"),
            keywords=(
                "taper", "tapering", "race", "week", "recovery", "rest", "sharpen", "sleep",
                "carb", "loading", "expo", "shakeout", "nervous",
            ),
            text=(
                "Cut volume by 40-60% over 2-3 weeks while keeping some race-pace work so the "
                "legs stay sharp; do not stop running entirely. Keep the same number of runs "
                "but shorter, and keep one short session at goal pace 4-5 days out. Sleep is "
                "the main recovery lever. Carbohydrate loading in the last 48 hours helps only "
                "if the taper was adequate, and a short shakeout run the day before is fine."
            ),
        ),
    ),
)
