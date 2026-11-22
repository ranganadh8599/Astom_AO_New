"""The 20 agents in the A2A test suite — one row each, no shared vocabulary.

Every agent owns a disjoint topic. That is deliberate: the suite exists to test
*retrieval*, so any overlap between two cards would make a routing result ambiguous and
the test useless. Descriptions name the domain and the questions it answers, and nothing
else.

Ports 9110-9129 (9103 is the Ronaldo agent, 9301-9320 belong to the MCP samples).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentEntry:
    id: str
    name: str
    title: str
    port: int
    description: str


AGENTS: tuple[AgentEntry, ...] = (
    AgentEntry(
        id="bicycle-repair",
        name="bicycle-repair",
        title="Bicycle repair",
        port=9110,
        description=(
            "Explains bicycle maintenance and repair: chain and cassette wear, derailleur "
            "adjustment, rim and disc brakes, wheel building and tyre setup."
        ),
    ),
    AgentEntry(
        id="sourdough-baking",
        name="sourdough-baking",
        title="Sourdough baking",
        port=9111,
        description=(
            "Coaches naturally leavened bread: maintaining a starter, bulk fermentation, "
            "shaping, scoring and baking with steam."
        ),
    ),
    AgentEntry(
        id="night-sky-astronomy",
        name="night-sky-astronomy",
        title="Night-sky astronomy",
        port=9112,
        description=(
            "Answers observing questions: seasonal constellations, planetary visibility, "
            "dark adaptation, light pollution scales and atmospheric seeing."
        ),
    ),
    AgentEntry(
        id="bird-migration",
        name="bird-migration",
        title="Bird migration",
        port=9113,
        description=(
            "Describes avian migration: flyways, seasonal timing, stopover ecology and the "
            "navigation cues birds use."
        ),
    ),
    AgentEntry(
        id="chess-openings",
        name="chess-openings",
        title="Chess openings",
        port=9114,
        description=(
            "Explains chess opening theory: central control and development principles, "
            "1.e4 and 1.d4 repertoires, and the plans behind named defences."
        ),
    ),
    AgentEntry(
        id="knitting",
        name="knitting",
        title="Knitting",
        port=9115,
        description=(
            "Guides hand knitting: tension swatches and gauge maths, increases and "
            "decreases, short rows, blocking and seam finishing."
        ),
    ),
    AgentEntry(
        id="wine-pairing",
        name="wine-pairing",
        title="Wine pairing",
        port=9116,
        description=(
            "Advises on matching wine with food: acidity against fat, tannin against "
            "protein, sweetness against heat, and classic grape-to-dish pairings."
        ),
    ),
    AgentEntry(
        id="electrical-safety",
        name="electrical-safety",
        title="Electrical safety",
        port=9117,
        description=(
            "Covers low-voltage installation safety: residual current devices, earthing "
            "systems, and the safe isolation procedure before work."
        ),
    ),
    AgentEntry(
        id="volcano-geology",
        name="volcano-geology",
        title="Volcano geology",
        port=9118,
        description=(
            "Explains volcanology: effusive versus explosive eruption styles, primary "
            "hazards, and how observatories monitor restless volcanoes."
        ),
    ),
    AgentEntry(
        id="calligraphy",
        name="calligraphy",
        title="Calligraphy",
        port=9119,
        description=(
            "Teaches Western calligraphy: historical scripts, broad-edge and pointed nibs, "
            "and drills for consistent letterforms."
        ),
    ),
    AgentEntry(
        id="jazz-improvisation",
        name="jazz-improvisation",
        title="Jazz improvisation",
        port=9120,
        description=(
            "Explains jazz soloing: ii-V-I harmony and guide tones, chord-scale choices, "
            "and building vocabulary from transcribed solos."
        ),
    ),
    AgentEntry(
        id="marathon-training",
        name="marathon-training",
        title="Marathon training",
        port=9121,
        description=(
            "Plans distance running: base building and periodisation, long-run progression, "
            "race fuelling and the taper."
        ),
    ),
    AgentEntry(
        id="container-stowage",
        name="container-stowage",
        title="Container stowage",
        port=9122,
        description=(
            "Answers cargo stowage questions: lashing and twist locks, stack weight limits, "
            "verified gross mass and dangerous-goods segregation."
        ),
    ),
    AgentEntry(
        id="beekeeping",
        name="beekeeping",
        title="Beekeeping",
        port=9123,
        description=(
            "Advises hobby beekeepers: seasonal colony management, swarm prevention, "
            "inspection rhythm and honey harvesting."
        ),
    ),
    AgentEntry(
        id="legal-citation",
        name="legal-citation",
        title="Legal citation",
        port=9124,
        description=(
            "Formats legal references: case citations in a reporter series, statutory "
            "citations, and citations to books and journal articles."
        ),
    ),
    AgentEntry(
        id="api-versioning",
        name="api-versioning",
        title="API versioning",
        port=9125,
        description=(
            "Designs HTTP API evolution: URI versus media-type versioning, semantic "
            "versioning, deprecation headers and backward-compatible change."
        ),
    ),
    AgentEntry(
        id="photography-exposure",
        name="photography-exposure",
        title="Photography exposure",
        port=9126,
        description=(
            "Explains exposure control: aperture, shutter speed and ISO trade-offs, "
            "metering modes, histograms and depth of field."
        ),
    ),
    AgentEntry(
        id="wilderness-first-aid",
        name="wilderness-first-aid",
        title="Wilderness first aid",
        port=9127,
        description=(
            "Guides remote-area first aid: recognising and treating hypothermia, splinting "
            "fractures, and deciding when evacuation is urgent."
        ),
    ),
    AgentEntry(
        id="tea-ceremony",
        name="tea-ceremony",
        title="Japanese tea ceremony",
        port=9128,
        description=(
            "Describes chanoyu: the order of a temae, guest etiquette, seasonal utensil "
            "choice and the meaning of the main implements."
        ),
    ),
    AgentEntry(
        id="railway-signalling",
        name="railway-signalling",
        title="Railway signalling",
        port=9129,
        description=(
            "Explains railway signalling: block working principles, interlocking and route "
            "setting, signal aspects and cab signalling systems."
        ),
    ),
)

BY_ID: dict[str, AgentEntry] = {entry.id: entry for entry in AGENTS}


def by_id(agent_id: str) -> AgentEntry:
    try:
        return BY_ID[agent_id]
    except KeyError:  # pragma: no cover - operator typo
        known = ", ".join(entry.id for entry in AGENTS)
        raise SystemExit(f"unknown agent {agent_id!r}. Known agents: {known}") from None
