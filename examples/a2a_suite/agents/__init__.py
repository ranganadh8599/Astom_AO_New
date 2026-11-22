"""Agent modules for the A2A example suite.

Each module exports ``SPEC: a2a_suite.spec.AgentSpec``. They are imported on demand by
``a2a_suite.server`` (``--agent <id>``), so starting one agent never loads the other
nineteen.
"""

from __future__ import annotations

__all__ = [
    "bicycle_repair",
    "sourdough_baking",
    "night_sky_astronomy",
    "bird_migration",
    "chess_openings",
    "knitting",
    "wine_pairing",
    "electrical_safety",
    "volcano_geology",
    "calligraphy",
    "jazz_improvisation",
    "marathon_training",
    "container_stowage",
    "beekeeping",
    "legal_citation",
    "api_versioning",
    "photography_exposure",
    "wilderness_first_aid",
    "tea_ceremony",
    "railway_signalling",
]
