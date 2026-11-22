"""Ronaldo A2A agent — a real external agent for the orchestration POC."""

from .knowledge import KNOWLEDGE_CUTOFF, answer
from .server import create_app, load_card

__all__ = ["KNOWLEDGE_CUTOFF", "answer", "create_app", "load_card"]
__version__ = "1.0.0"
