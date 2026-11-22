"""Graph assembly.

    START -> validate_input -> retrieve_targets -> check_coverage -> plan_tasks
          -> (run_task x N, in parallel) -> compose_answer -> END

Each node does one thing:

* ``validate_input``   - input shape and limits; resets the turn-scoped state.
* ``retrieve_targets`` - asks the gateway which registered agents / MCP tools / models are
  relevant to this message, so later steps see a short list instead of the whole registry.
* ``check_coverage``   - a coverage gate decides whether *any* retrieved target can answer
  at all (the decision the planner is measurably bad at), refuses write requests under the
  read-only policy, and ends the turn when nothing fits.
* ``plan_tasks``       - the planner chooses among the remaining targets and splits the
  message into independent tasks.
* ``run_task``         - runs one task through the gateway (A2A agent, MCP tool or model).
* ``compose_answer``   - builds the reply deterministically from the task results; nothing
  an agent said is reworded.

Fan-out uses LangGraph's ``Send`` so independent tasks run concurrently; ``compose_answer``
starts only after every branch completes, because ``results`` is an add-reducer list.

The graph is compiled with a checkpointer: ``thread_id`` is the conversation id, so
``history`` survives across turns (and, with ``CHECKPOINT_BACKEND=postgres``, restarts).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from orchestrator.config import Settings
from orchestrator.gateway import LiteLLMGateway
from orchestrator.graph.nodes import OrchestratorNodes
from orchestrator.graph.state import OrchestratorState
from orchestrator.routing.target_catalog import TargetCatalog


def build_graph(
    settings: Settings,
    gateway: LiteLLMGateway,
    catalog: TargetCatalog,
    checkpointer: object | None = None,
):
    nodes = OrchestratorNodes(settings=settings, gateway=gateway, catalog=catalog)

    graph = StateGraph(OrchestratorState)
    graph.add_node("validate_input", nodes.validate_input)
    graph.add_node("retrieve_targets", nodes.retrieve_targets)
    graph.add_node("check_coverage", nodes.check_coverage)
    graph.add_node("plan_tasks", nodes.plan_tasks)
    graph.add_node("run_task", nodes.run_task)
    graph.add_node("compose_answer", nodes.compose_answer)

    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "retrieve_targets")
    graph.add_edge("retrieve_targets", "check_coverage")
    graph.add_edge("check_coverage", "plan_tasks")
    graph.add_conditional_edges("plan_tasks", nodes.fan_out_tasks, ["run_task", "compose_answer"])
    graph.add_edge("run_task", "compose_answer")
    graph.add_edge("compose_answer", END)

    return graph.compile(checkpointer=checkpointer)  # type: ignore[arg-type]
