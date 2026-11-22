"""A2A orchestration layer: LibreChat -> orchestrator -> LiteLLM gateway -> external agents."""

from orchestrator.config import Settings
from orchestrator.service import OrchestratorService, RunResult

__all__ = ["OrchestratorService", "RunResult", "Settings"]
__version__ = "0.1.0"
