"""End-to-end graph runs against a fake gateway: one question, many agents, one trace."""

from __future__ import annotations

import json

from orchestrator.auth import UserContext
from orchestrator.service import OrchestratorService
from tests.conftest import FakeGateway, make_settings, tool_calls


def _user(roles: tuple[str, ...] = ("AgentUser",)) -> UserContext:
    return UserContext(oid="oid-1", name="Test User", roles=roles)


async def _service(fake_gateway: FakeGateway, **overrides) -> OrchestratorService:
    settings = make_settings(**overrides)
    from orchestrator.gateway import LiteLLMGateway

    gateway = LiteLLMGateway(settings, client=fake_gateway.client())
    service = OrchestratorService(settings, gateway=gateway)
    await service.__aenter__()
    return service


async def test_single_question_routes_to_one_agent(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway)
    result = await service.run("how many annual leave days do I get?", _user())

    assert result.status == "completed"
    assert "24 days" in result.answer
    assert [task["agent_name"] for task in result.tasks] == ["hr-policy-agent"]


async def test_multi_question_fans_out_in_parallel(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway)
    query = (
        "how many annual leave days do I get? "
        "and is my expense reimbursement approved? "
        "also how do I get VPN access?"
    )
    result = await service.run(query, _user())

    assert result.status == "completed"
    assert len(result.tasks) == 3
    assert {item["agent_name"] for item in result.results} == {
        "hr-policy-agent",
        "finance-agent",
        "it-support-agent",
    }
    # every agent's text made it into the merged answer
    assert "24 days" in result.answer
    assert "1200 INR" in result.answer
    assert "VPN access is granted" in result.answer


async def test_fan_out_respects_max_agents(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway, max_agents_per_request=2)
    query = (
        "leave days? expense reimbursement? VPN access? "
        "laptop provisioning?"
    )
    result = await service.run(query, _user())
    assert len(result.tasks) <= 2


async def test_every_hop_carries_the_same_trace(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway)
    result = await service.run("leave and expenses", _user())

    agent_calls = [r for r in fake_gateway.requests if r.method == "POST"]
    assert agent_calls, "expected at least one agent invocation"
    for request in agent_calls:
        traceparent = request.headers.get("traceparent", "")
        assert traceparent.startswith("00-")
        assert result.trace_id in traceparent, "hop lost the trace context"
        assert request.headers.get("x-litellm-trace-id") == result.trace_id


async def test_partial_failure_still_answers(fake_gateway: FakeGateway) -> None:
    fake_gateway.fail_agents.add("finance-agent")
    service = await _service(fake_gateway)
    result = await service.run(
        "how many annual leave days do I get? is my expense reimbursement approved?",
        _user(),
    )

    assert result.status == "completed"
    assert "24 days" in result.answer
    failed = [item for item in result.results if not item["ok"]]
    assert failed and "failed" in result.answer.lower()


async def test_all_agents_failing_marks_run_failed(fake_gateway: FakeGateway) -> None:
    fake_gateway.fail_agents.update({"hr-1", "fin-1", "it-1"})
    service = await _service(fake_gateway)
    result = await service.run("leave days? expenses?", _user())
    assert result.status == "failed"


async def test_empty_query_is_rejected_before_any_agent_call(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway)
    before = len(fake_gateway.requests)
    result = await service.run("   ", _user())
    assert result.status == "failed"
    assert len(fake_gateway.requests) == before


async def test_inbound_traceparent_is_reused(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway)
    inbound = {"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"}
    result = await service.run("leave policy", _user(), inbound_headers=inbound)
    assert result.trace_id == "a" * 32


async def test_planner_request_is_json_mode_on_the_gateway(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway, planner_model="gpt-4o-mini")
    await service.run("anything", _user())

    planner_calls = [
        r for r in fake_gateway.requests if r.url.path == "/v1/chat/completions"
    ]
    assert planner_calls, "expected the planner to call the gateway"
    body = json.loads(planner_calls[0].content)
    assert body["model"] == "gpt-4o-mini"
    assert body["response_format"] == {"type": "json_object"}


async def test_default_invocation_strategy_is_a2a_jsonrpc(fake_gateway: FakeGateway) -> None:
    """The simple and chat shapes are rejected by current proxies; JSON-RPC is the
    envelope that works, so it must stay the default."""
    service = await _service(fake_gateway)
    await service.run("who is ronaldo", _user())

    agent_calls = [r for r in fake_gateway.requests if r.url.path.startswith("/a2a/")
                   and r.method == "POST"]
    assert agent_calls, "expected an agent invocation"
    body = json.loads(agent_calls[0].content)
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "message/send"
    assert body["params"]["message"]["parts"][0]["kind"] == "text"
    # and it must NOT go through the LLM router
    assert not [r for r in fake_gateway.requests
                if r.url.path == "/v1/chat/completions" and "a2a/" in (r.content or b"").decode()]


# -- read-only policy ------------------------------------------------------
# The mutation verdict itself is covered in tests/graph/test_planning.py; here we only assert
# that the conversation still records the refusal.


async def test_refused_turn_is_still_remembered_in_the_conversation(
    fake_gateway: FakeGateway,
) -> None:
    fake_gateway.default_mutation = True
    service = await _service(fake_gateway)
    await service.run("approve the expense report", _user(), session_id="conv-refused")

    state = await service._graph.aget_state({"configurable": {"thread_id": "conv-refused"}})
    assert [item["role"] for item in state.values["history"]] == ["user", "assistant"]


async def test_turn_ended_before_execution_is_recorded_once(
    fake_gateway: FakeGateway,
) -> None:
    """A no-match turn must appear once, not twice.

    Regression: `check_coverage` wrote the assistant message into history, and `compose_answer` appended
    the same text again on its `status == "completed"` branch. Every turn that ended
    early therefore appeared twice in the stored history, which then padded the planner
    prompt with a duplicate on each later turn.
    """
    service = await _service(fake_gateway)
    result = await service.run(
        "what is the boiling point of liquid nitrogen?", _user(), session_id="conv-nomatch"
    )

    assert result.status == "completed"
    assert result.tasks == []

    state = await service._graph.aget_state({"configurable": {"thread_id": "conv-nomatch"}})
    history = list(state.values["history"])

    assert [item["role"] for item in history] == ["user", "assistant"]
    answers = [item["content"] for item in history if item["role"] == "assistant"]
    assert len(answers) == 1, f"duplicate assistant entries: {answers}"
    assert "Nothing in the registered catalogue" in answers[0]


# -- MCP through the same gateway -----------------------------------------


async def test_mcp_tool_is_discovered_and_called_through_the_gateway(
    fake_gateway: FakeGateway,
) -> None:
    service = await _service(fake_gateway, protocols=("a2a", "mcp"))

    result = await service.run("what is the status of order ord-1?", _user())

    assert result.status == "completed"
    assert "shipped" in result.answer
    mcp_results = [item for item in result.results if item["protocol"] == "mcp"]
    assert mcp_results and mcp_results[0]["tool_name"] == "get_order_status"

    calls = tool_calls(fake_gateway)
    assert calls, "expected the MCP tool call to go through LiteLLM"
    body = json.loads(calls[0].content)
    assert body["server_id"] == "orders"
    assert body["name"] == "get_order_status"
    assert body["arguments"], "MCP calls must carry an arguments object"
    # discovery went through the gateway, never to the MCP server directly
    assert [r.url.path for r in fake_gateway.requests if r.url.path == "/v1/mcp/server"]


async def test_one_request_can_fan_out_across_both_protocols(
    fake_gateway: FakeGateway,
) -> None:
    service = await _service(fake_gateway, protocols=("a2a", "mcp"))

    result = await service.run(
        "how many annual leave days do I get? what is the status of order ord-1?",
        _user(),
    )

    assert {item["protocol"] for item in result.results} == {"a2a", "mcp"}
    assert "24 days" in result.answer
    assert "shipped" in result.answer


# -- one trace per conversation + turn-scoped state -----------------------



async def test_conversation_keeps_one_trace_and_resets_turn_state(
    fake_gateway: FakeGateway,
) -> None:
    service = await _service(fake_gateway)

    first = await service.run(
        "how many annual leave days do I get?", _user(), session_id="conv-42"
    )
    second = await service.run(
        "and is my expense reimbursement approved?", _user(), session_id="conv-42"
    )

    assert first.trace_id == second.trace_id
    assert len(first.trace_id) == 32
    # The second turn must not replay the first turn's results from the checkpoint.
    assert {item["agent_name"] for item in second.results} == {"finance-agent"}

    state = await service._graph.aget_state({"configurable": {"thread_id": "conv-42"}})
    assert [item["role"] for item in state.values["history"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


async def test_different_conversations_get_different_traces(
    fake_gateway: FakeGateway,
) -> None:
    service = await _service(fake_gateway)
    one = await service.run("leave policy", _user(), session_id="conv-a")
    two = await service.run("leave policy", _user(), session_id="conv-b")
    assert one.trace_id != two.trace_id


async def test_every_hop_carries_the_conversation_trace(fake_gateway: FakeGateway) -> None:
    service = await _service(fake_gateway, protocols=("a2a", "mcp"))
    result = await service.run(
        "leave days? order status?", _user(), session_id="conv-trace"
    )

    calls = [
        r for r in fake_gateway.requests
        if r.method == "POST" and r.url.path in ("/a2a/hr-1",) 
    ] + tool_calls(fake_gateway)
    assert calls
    for request in calls:
        assert result.trace_id in request.headers.get("traceparent", "")
        assert request.headers.get("x-litellm-trace-id") == result.trace_id
