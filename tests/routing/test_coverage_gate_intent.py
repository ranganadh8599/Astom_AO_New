"""A mutation request must get the read-only refusal, not a coverage message.

Regression this pins: once the coverage gate ran before the planner, a denied request
was answered with "nothing covers that request" and ``denied`` was False — technically
not routed, but the user was not told the system is read-only. The gate now triages
intent too, so the refusal is decided independently of whether any target exists.
"""

from __future__ import annotations

import json

from orchestrator.auth import UserContext
from orchestrator.routing.coverage_gate import OUTCOME_NO_MATCH
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


async def test_gate_mutation_verdict_produces_the_readonly_refusal(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.gate_raw = json.dumps(
        {
            "intent": "mutation",
            "can_answer": False,
            "targets": [],
            "reason": "asks to delete a leave request",
            "confidence": 0.95,
        }
    )
    service = await _service(fake_gateway)

    result = await service.run("delete my leave request", _user())

    assert result.denied is True
    assert result.status == "rejected"
    assert "read-only" in result.answer.lower()
    # Not the coverage message.
    assert "catalogue" not in result.answer.lower()


async def test_mutation_is_refused_without_consulting_the_planner(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.gate_raw = json.dumps(
        {"intent": "mutation", "can_answer": False, "targets": [],
         "reason": "asks to approve something", "confidence": 0.9}
    )
    service = await _service(fake_gateway)

    await service.run("approve the expense report", _user())

    assert not fake_gateway.planner_prompts
    assert not [
        r for r in fake_gateway.requests
        if r.method == "POST" and r.url.path.startswith("/a2a/")
    ]


async def test_intent_is_defaulted_to_read_when_absent(fake_gateway: FakeGateway) -> None:
    """An older gate reply without `intent` must not be read as a mutation."""
    fake_gateway.gate_raw = json.dumps(
        {"can_answer": True, "targets": ["hr-policy-agent"],
         "reason": "covers leave", "confidence": 0.8}
    )
    service = await _service(fake_gateway)

    result = await service.run("how many annual leave days do I get?", _user())

    assert result.denied is False
    assert result.status == "completed"


async def test_no_match_on_a_read_request_is_not_a_refusal(fake_gateway: FakeGateway) -> None:
    """Coverage failure and policy refusal are different outcomes and different text."""
    fake_gateway.gate_raw = json.dumps(
        {"intent": "read", "can_answer": False, "targets": [],
         "reason": "no target covers astronomy", "confidence": 0.9}
    )
    service = await _service(fake_gateway)

    result = await service.run("what is the mass of Jupiter", _user())

    assert result.denied is False
    assert result.status == "completed"
    assert "astronomy" in result.answer
    assert "read-only" not in result.answer.lower()


def test_screening_records_intent() -> None:
    from orchestrator.routing.coverage_gate import parse_decision

    screening = parse_decision(
        json.dumps({"intent": "mutation", "can_answer": False, "targets": [],
                    "reason": "r", "confidence": 0.9})
    )
    assert screening is not None
    assert screening.intent == "mutation"
    assert screening.outcome == OUTCOME_NO_MATCH
