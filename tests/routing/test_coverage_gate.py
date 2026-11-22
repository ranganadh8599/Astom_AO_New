"""The coverage gate: an explicit verdict, not an empty list.

Measured reason for this node: asked to route directly, the planner rejected 2 of 7
irrelevant queries and adding scores did not change that. Asked "can anything cover
this?" first, it rejected 7 of 7 while keeping valid queries routed.

The contract follows a sibling implementation in this workspace
(multi-agent-orchestator/classifiers/open_ai_classifier.py): a first-class "no match"
outcome with a mandatory reason and a self-reported confidence.
"""

from __future__ import annotations

import json

from orchestrator.auth import UserContext
from orchestrator.routing.coverage_gate import (
    OUTCOME_NO_MATCH,
    OUTCOME_ROUTE,
    build_prompt,
    parse_decision,
)
from orchestrator.service import OrchestratorService
from tests.conftest import FakeGateway, make_settings


def _user() -> UserContext:
    return UserContext(oid="oid-1", name="Test User", roles=("AgentUser",))


async def _service(fake_gateway: FakeGateway, **overrides) -> OrchestratorService:
    from orchestrator.gateway import LiteLLMGateway

    settings = make_settings(**overrides)
    gateway = LiteLLMGateway(settings, client=fake_gateway.client())
    service = OrchestratorService(settings, gateway=gateway)
    await service.__aenter__()
    return service


# -- parsing ---------------------------------------------------------------


def test_no_match_is_an_explicit_outcome_with_a_reason() -> None:
    screening = parse_decision(
        json.dumps(
            {
                "can_answer": False,
                "targets": [],
                "reason": "no target covers astronomy",
                "confidence": 0.92,
            }
        )
    )

    assert screening is not None
    assert screening.outcome == OUTCOME_NO_MATCH
    assert screening.reason == "no target covers astronomy"
    assert screening.confidence == 0.92


def test_route_carries_the_named_targets() -> None:
    screening = parse_decision(
        json.dumps({"can_answer": True, "targets": ["hr-policy-agent"],
                    "reason": "covers leave", "confidence": 0.8})
    )

    assert screening is not None
    assert screening.outcome == OUTCOME_ROUTE
    # An advisory ranking, not a permission list — hence `named`, not `allowed`.
    assert screening.named == ("hr-policy-agent",)


def test_malformed_reply_is_unusable_not_a_decline() -> None:
    """Failing closed here would discard valid queries on a formatting slip."""
    assert parse_decision("not json at all") is None
    assert parse_decision(json.dumps({"reason": "no verdict"})) is None


# -- a request is never smalltalk -----------------------------------------


async def test_a_content_request_labelled_smalltalk_becomes_a_coverage_miss(
    fake_gateway: FakeGateway,
) -> None:
    """Measured: the model called "write me a short poem about winter" smalltalk.

    Answering a request with a greeting silently drops it, so a deterministic check
    overrides the label rather than trusting prompt compliance.
    """
    from orchestrator.gateway import LiteLLMGateway
    from orchestrator.routing.coverage_gate import CoverageGate
    from orchestrator.observability.trace_context import Lineage, TraceContext

    fake_gateway.gate_raw = json.dumps(
        {"intent": "smalltalk", "can_answer": False, "targets": [],
         "reason": "social message", "confidence": 0.3}
    )
    gate = CoverageGate(LiteLLMGateway(make_settings(), client=fake_gateway.client()), "test/planner")

    verdict = await gate.assess(
        "write me a short poem about winter",
        [],
        trace=TraceContext.root(),
        lineage=Lineage.root(),
    )

    assert verdict is not None
    assert verdict.outcome == OUTCOME_NO_MATCH and verdict.intent == "read"
    assert "request" in verdict.notes[0]
    # The smalltalk reason must not survive: "Why: the message is a greeting" next to a
    # coverage miss reads like a malfunction.
    assert verdict.reason == ""


async def test_real_smalltalk_still_gets_the_smalltalk_outcome(
    fake_gateway: FakeGateway,
) -> None:
    from orchestrator.gateway import LiteLLMGateway
    from orchestrator.routing.coverage_gate import CoverageGate
    from orchestrator.observability.trace_context import Lineage, TraceContext

    fake_gateway.gate_raw = json.dumps(
        {"intent": "smalltalk", "can_answer": False, "targets": [],
         "reason": "greeting", "confidence": 0.95}
    )
    gate = CoverageGate(LiteLLMGateway(make_settings(), client=fake_gateway.client()), "test/planner")

    verdict = await gate.assess(
        "nice work everyone", [], trace=TraceContext.root(), lineage=Lineage.root()
    )

    assert verdict is not None and verdict.is_smalltalk


def test_affirmative_without_targets_does_not_narrow() -> None:
    screening = parse_decision(
        json.dumps({"can_answer": True, "targets": [], "reason": "yes", "confidence": 0.5})
    )

    assert screening is not None
    assert screening.outcome == OUTCOME_ROUTE
    assert screening.named == ()
    # No names means "no hint", never "nothing allowed".
    assert screening.notes


def test_contradictory_reply_is_recorded() -> None:
    screening = parse_decision(
        json.dumps({"can_answer": False, "targets": ["hr-policy-agent"],
                    "reason": "no", "confidence": 0.4})
    )

    assert screening is not None
    assert screening.outcome == OUTCOME_NO_MATCH
    assert any("contradicted" in note or "targets listed" in note for note in screening.notes)


def test_confidence_is_clamped() -> None:
    high = parse_decision(json.dumps({"can_answer": True, "targets": ["a"],
                                      "reason": "r", "confidence": 5}))
    low = parse_decision(json.dumps({"can_answer": True, "targets": ["a"],
                                     "reason": "r", "confidence": -2}))
    assert high is not None and high.confidence == 1.0
    assert low is not None and low.confidence == 0.0


def test_prompt_shows_scores_as_a_hint_not_a_verdict() -> None:
    from orchestrator.gateway.models import Target

    record = Target(
        agent_id="a", agent_name="hr-policy-agent",
        description="leave policy", search_score=0.42,
    )
    prompt = build_prompt("leave days?", [record])

    assert "relevance: 0.42" in prompt
    assert "hr-policy-agent" in prompt


# -- graph behaviour -------------------------------------------------------


async def test_gate_no_match_ends_the_turn_without_planning(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.gate_no_match = True
    service = await _service(fake_gateway)

    result = await service.run("what is the capital of France", _user())

    assert result.status == "completed"
    assert result.tasks == []
    assert "Why:" in result.answer
    assert not fake_gateway.planner_prompts, "planner must not run after a no-match verdict"


async def test_gate_runs_before_the_planner(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway)
    await service.run("how many annual leave days do I get?", _user())

    assert fake_gateway.gate_prompts, "expected the coverage gate to be consulted"
    assert fake_gateway.planner_prompts, "expected the planner to run after an affirmative"


async def test_gate_failure_degrades_to_planning(fake_gateway: FakeGateway) -> None:
    """A broken gate must not become an outage: the planner is still a gate."""
    fake_gateway.gate_fails = True
    service = await _service(fake_gateway)

    result = await service.run("how many annual leave days do I get?", _user())

    assert result.status == "completed"
    assert "24 days" in result.answer
    assert fake_gateway.planner_prompts


async def test_gate_naming_does_not_hide_candidates(fake_gateway: FakeGateway) -> None:
    """A wrong gate pick must not remove retrieval's other candidates.

    Regression: the gate was asked about both leave and expenses and named only
    `finance-agent`. `check_coverage` then *filtered* the candidate list to that name, so the
    planner never saw `hr-policy-agent` and could not answer the leave half at all.

    Measured live on the same defect: with a follow-up question, retrieval ranked
    `get_asset_maintenance_history` at 0.63 while the gate named `get_asset_status`
    (0.39). The top match was deleted before planning, which made the wrong answer
    unrecoverable.
    """
    fake_gateway.gate_raw = json.dumps(
        {"can_answer": True, "targets": ["finance-agent"],
         "reason": "covers expenses", "confidence": 0.9}
    )
    service = await _service(fake_gateway)

    result = await service.run(
        "how many annual leave days do I get? is my expense reimbursement approved?",
        _user(),
    )

    # Both remain reachable, so the planner can answer both halves.
    assert sorted(t["agent_name"] for t in result.tasks) == [
        "finance-agent",
        "hr-policy-agent",
    ]
    # And the turn says what the gate named without pretending it narrowed.
    assert any("1 of" in note and "kept" in note for note in result.notes)


async def test_planner_sees_one_ranked_list_and_no_second_opinion(
    fake_gateway: FakeGateway,
) -> None:
    """The gateway's ranking is the only ordering the planner gets.

    Regression: after the destructive filter was removed, a "Gate hint" line was added
    so the gate's opinion would not be wasted. Measured, that made the planner fan out to
    **two** targets for a one-target question — two competing rankings made both look
    defensible. LiteLLM's own design is a single ordered list (`mcp_tool_search` ranks,
    `similarity_threshold` cuts), so the extra signal was removed.
    """
    fake_gateway.gate_raw = json.dumps(
        {"can_answer": True, "targets": ["hr-policy-agent"],
         "reason": "covers leave", "confidence": 0.9}
    )
    service = await _service(fake_gateway)

    await service.run("how many annual leave days do I get?", _user())

    planner_prompt = fake_gateway.planner_prompts[-1]
    assert "Gate hint" not in planner_prompt
    # Every candidate still reaches the planner — nothing is filtered out.
    assert "finance-agent" in planner_prompt
    assert "it-support-agent" in planner_prompt
    # Exactly one task: one target requested, one target chosen.
    assert len(fake_gateway.requests) >= 1


async def test_gate_can_be_disabled(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway, coverage_gate_enabled=False)
    result = await service.run("how many annual leave days do I get?", _user())

    assert not fake_gateway.gate_prompts
    assert result.status == "completed"
    assert "24 days" in result.answer
