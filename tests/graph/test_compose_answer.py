"""Merge is deterministic: attribute facts, never rewrite them.

An LLM merge was removed because it could only add paraphrase risk to a read-only,
audit-oriented answer. These tests pin the behaviour that replaced it.
"""

from __future__ import annotations

from orchestrator.gateway import InvocationResult
from orchestrator.graph.nodes import OrchestratorNodes


def _result(name: str, text: str = "", ok: bool = True, error: str = "") -> InvocationResult:
    return InvocationResult(
        agent_id=name, agent_name=name, instruction="q", ok=ok, text=text, error=error
    )


def test_single_successful_result_is_passed_through_unwrapped() -> None:
    answer = OrchestratorNodes._compose([_result("hr-policy-agent", "You get 24 days.")])
    assert answer == "You get 24 days."


def test_single_failure_names_the_target_and_the_reason() -> None:
    answer = OrchestratorNodes._compose([_result("finance-agent", ok=False, error="agent returned 500")])
    assert "finance-agent" in answer
    assert "agent returned 500" in answer


def test_multiple_results_are_attributed_per_target() -> None:
    answer = OrchestratorNodes._compose(
        [
            _result("hr-policy-agent", "You get 24 days."),
            _result("finance-agent", "Approved for 1200 INR."),
        ]
    )
    assert "### hr-policy-agent" in answer
    assert "### finance-agent" in answer
    assert answer.index("hr-policy-agent") < answer.index("finance-agent")


def test_partial_failure_is_reported_without_losing_the_success() -> None:
    answer = OrchestratorNodes._compose(
        [
            _result("hr-policy-agent", "You get 24 days."),
            _result("finance-agent", ok=False, error="timeout"),
        ]
    )
    assert "You get 24 days." in answer
    assert "Failed" in answer
    assert "timeout" in answer


def test_no_results_is_explicit() -> None:
    assert "No target" in OrchestratorNodes._compose([])
