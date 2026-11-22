"""The state every node reads from and writes to.

The graph is checkpointed per conversation, so two things need care:

* ``results`` and ``notes`` are *turn-scoped*: parallel branches append to them, but the
  validate_input node resets both at the start of every turn (otherwise a long conversation would
  replay last turn's results forever).
* ``history`` is conversation-scoped and accumulates one user/assistant pair per turn.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

RESET = "__reset__"


def turn_scoped(left: list[Any], right: list[Any]) -> list[Any]:
    """Append, unless the write starts with the reset marker."""
    if not right:
        return list(left)
    if right[0] == RESET:
        return list(right[1:])
    return [*left, *right]


class TaskSpec(TypedDict, total=False):
    task_id: str
    agent_id: str
    agent_name: str
    protocol: str
    server_id: str
    tool_name: str
    instruction: str
    arguments: dict[str, Any]


class OrchestratorState(TypedDict, total=False):
    # Identity of the run
    run_id: str
    session_id: str
    user_query: str
    user: dict[str, Any]

    # Cross-service context, serialized so it survives checkpointing
    trace: dict[str, Any]
    lineage: dict[str, Any]

    # Conversation memory (persisted by the checkpointer, thread = conversation)
    history: Annotated[list[dict[str, Any]], operator.add]

    # Routing
    candidates: list[dict[str, Any]]
    coverage: dict[str, Any]
    tasks: list[TaskSpec]
    max_agents: int

    # Output
    results: Annotated[list[dict[str, Any]], turn_scoped]
    notes: Annotated[list[str], turn_scoped]
    answer: str
    status: str
    error: str


TERMINAL_STATUSES = ("completed", "failed", "rejected")
