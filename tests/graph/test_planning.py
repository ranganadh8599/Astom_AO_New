"""Routing is the planner model's job — there is no local fallback.

These tests assert the contract rather than the wording: the planner is always consulted,
its intent verdict is honoured, and its task list is what gets executed.
"""

from __future__ import annotations

import json

from orchestrator.auth import UserContext
from orchestrator.service import OrchestratorService
from tests.conftest import FakeGateway, make_settings, tool_calls


def _user() -> UserContext:
    return UserContext(oid="oid-1", name="Test User", roles=("AgentUser",))


async def _service(fake_gateway: FakeGateway, **overrides) -> OrchestratorService:
    from orchestrator.gateway import LiteLLMGateway

    settings = make_settings(**overrides)
    gateway = LiteLLMGateway(settings, client=fake_gateway.client())
    service = OrchestratorService(settings, gateway=gateway)
    await service.__aenter__()
    return service


async def test_planner_is_always_consulted(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway)
    await service.run("how many annual leave days do I get?", _user())

    assert fake_gateway.planner_prompts, "the planner must be called to route a request"
    prompt = fake_gateway.planner_prompts[0]
    assert "annual leave" in prompt
    # The planner is given the discovered targets, not a pre-filtered guess.
    assert "hr-policy-agent" in prompt


async def test_missing_planner_model_fails_instead_of_guessing(
    fake_gateway: FakeGateway,
) -> None:
    service = await _service(fake_gateway, planner_model="")
    result = await service.run("how many annual leave days do I get?", _user())

    assert result.status == "failed"
    assert "PLANNER_MODEL" in result.error
    assert not fake_gateway.planner_prompts
    assert not [r for r in fake_gateway.requests if r.url.path.startswith("/a2a/")
                and r.method == "POST"]


async def test_unparseable_planner_reply_fails_closed(fake_gateway: FakeGateway) -> None:
    fake_gateway.planner_fails = True
    service = await _service(fake_gateway)
    result = await service.run("how many annual leave days do I get?", _user())

    assert result.status == "failed"
    assert result.tasks == []


async def test_unparseable_reply_is_retried_once(fake_gateway: FakeGateway) -> None:
    """A formatting slip must not end the turn.

    Measured in practice: roughly one turn in a handful came back as prose around the
    JSON, which surfaced as `planner did not return a usable decision` and read like a
    broken orchestrator. One retry fixes it without masking a genuinely unusable planner
    (that case still fails, per the test above).
    """
    fake_gateway.planner_fail_times = 1
    service = await _service(fake_gateway)

    result = await service.run("how many annual leave days do I get?", _user())

    assert result.status == "completed"
    assert [task["agent_name"] for task in result.tasks] == ["hr-policy-agent"]
    # Two planner calls: the unusable one and the retry.
    assert len(fake_gateway.planner_prompts) == 2
    # The retry says why, rather than repeating the same prompt verbatim.
    assert "could not be parsed" in fake_gateway.planner_prompts[-1]


async def test_retry_gives_up_after_the_second_unusable_reply(
    fake_gateway: FakeGateway,
) -> None:
    """Bounded: two bad replies in a row still fail rather than looping."""
    fake_gateway.planner_fails = True
    service = await _service(fake_gateway)

    result = await service.run("how many annual leave days do I get?", _user())

    assert result.status == "failed"
    assert len(fake_gateway.planner_prompts) == 2


async def test_rate_limit_is_retried_then_succeeds(fake_gateway: FakeGateway) -> None:
    """429 is transient upstream; the same call succeeds moments later.

    Observed in practice on this gateway during a burst of turns. Without a retry the
    turn failed as `planner did not return a usable decision`, which pointed at the model
    rather than at rate limiting.
    """
    fake_gateway.planner_429_times = 1
    service = await _service(fake_gateway)

    result = await service.run("how many annual leave days do I get?", _user())

    assert result.status == "completed"
    assert [task["agent_name"] for task in result.tasks] == ["hr-policy-agent"]


async def test_persistent_rate_limit_fails_with_the_status(
    fake_gateway: FakeGateway,
) -> None:
    """Bounded retries, and the error names the cause so it is not mistaken for a model bug."""
    fake_gateway.planner_429_times = 99
    service = await _service(fake_gateway)

    result = await service.run("how many annual leave days do I get?", _user())

    assert result.status == "failed"
    assert "429" in result.error
    # 1 attempt + 4 rate-limit retries, never unbounded.
    assert len(fake_gateway.planner_prompts) == 5


async def test_planner_supplied_arguments_reach_the_mcp_tool(
    fake_gateway: FakeGateway,
) -> None:
    service = await _service(fake_gateway, protocols=("a2a", "mcp"))
    result = await service.run("what is the status of my order?", _user())

    assert result.status == "completed"
    calls = tool_calls(fake_gateway)
    assert calls
    body = json.loads(calls[0].content)
    assert body["arguments"] == {"order_id": "ord-1"}
    assert body["server_id"] == "orders"
    assert body["name"] == "get_order_status"


async def test_incomplete_planner_arguments_are_never_sent(
    fake_gateway: FakeGateway,
) -> None:
    """A knowingly incomplete call must not leave the orchestrator."""
    fake_gateway.planner_raw = json.dumps(
        {
            "intent": "read",
            "tasks": [
                {
                    "agent": "orders-get_order_status",
                    "instruction": "Look up the order",
                    "arguments": {},
                }
            ],
        }
    )
    service = await _service(fake_gateway, protocols=("a2a", "mcp"))
    result = await service.run("what is the status of my order?", _user())

    assert not tool_calls(fake_gateway)
    assert result.status == "failed"
    assert "order_id" in result.answer


async def test_mutation_intent_is_refused_without_invoking_anything(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.default_mutation = True
    service = await _service(fake_gateway)
    before = len(fake_gateway.requests)

    result = await service.run("please delete my annual leave request", _user())

    assert result.status == "rejected"
    assert result.denied is True
    assert result.tasks == []
    assert "read-only" in result.answer.lower()
    # Only the planner call itself is allowed to happen.
    invoked = [
        r for r in fake_gateway.requests[before:]
        if r.url.path.startswith("/a2a/") and r.method == "POST"
    ]
    assert not invoked


async def test_mutation_verdict_can_be_ignored_when_the_policy_is_off(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.default_mutation = True
    service = await _service(fake_gateway, read_only_mode=False)
    result = await service.run("delete my leave request", _user())

    assert result.status != "rejected"
